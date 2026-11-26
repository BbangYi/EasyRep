// DFR1172 native successor. No cage sensor/actuator/IR GPIO is controlled here.
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <WebServer.h>
#include <ESP_Video.h>
#include <atomic>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include "esp_chip_info.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_video_ioctl.h"
#include "esp_video_isp_pipeline.h"
#include "esp_h264_enc_single_hw.h"
#include "esp_rtsp.h"
#include "media_lib_adapter.h"
#include "camera_contract.h"

#if !defined(ARDUINO_DFROBOT_FIREBEETLE2_ESP32P4) || !CONFIG_ESP32P4_SELECTS_REV_LESS_V3
#error "Build for DFR1172 ESP32-P4 before revision 3.00"
#endif

using namespace habitat_camera;
static Preferences storage;
static cJSON *config = nullptr;
static WebServer http(5000);
static ESPVideoClass video;
static int cameraFd = -1;
static uint8_t *captureBuffers[2] = {};
static size_t captureSizes[2] = {};
static esp_h264_enc_handle_t encoder = nullptr;
static esp_rtsp_handle_t rtsp = nullptr;
static esp_rtsp_video_info_t rtspVideo = {};
static esp_rtsp_data_cb_t rtspCallbacks = {};
static String bindAddress;
static std::atomic<bool> healthy{false}, playing{false}, waitIdr{true};
static std::atomic<uint32_t> encodedFrames{0}, droppedFrames{0}, lastFrameMs{0};
static const char *failure = "starting";
static char serialLine[MaxConfig + 32];
static size_t serialLength = 0;
static bool serialOverflow = false;
static uint32_t retryAt = 0;

struct Frame { uint8_t *data; uint32_t length, pts; bool idr; };
static QueueHandle_t frames;
static SemaphoreHandle_t frameLock;
static uint8_t *idrCache = nullptr;
static uint32_t idrLength = 0, idrPts = 0;

static void clearFrames() {
    Frame old;
    while (xQueueReceive(frames, &old, 0) == pdTRUE) free(old.data);
}

static void fail(const char *reason) {
    failure = reason;
    healthy = false;
    playing = false;
    Serial.printf("CAMERA_ERROR %s\n", reason);
}

static cJSON *imagingStatus() {
    auto *result = cJSON_CreateObject();
    if (!result) return nullptr;
    if (!healthy || cameraFd < 0 || millis() - lastFrameMs > 2000) {
        cJSON_AddBoolToObject(result, "available", false);
        return result;
    }
    // Read-only, fixed sensor registers. No generic register-write/debug endpoint.
    // Stop at the first I/O error or a 50 ms total read budget; capture is separate.
    constexpr uint16_t addresses[] = {
        0x3500, 0x3501, 0x3502, 0x3503, 0x350a, 0x350b,
        0x3a00, 0x3a0f, 0x3a10, 0x3a18, 0x3a19,
        0x380c, 0x380d, 0x380e, 0x380f, 0x5001, 0x5180
    };
    uint8_t values[sizeof(addresses) / sizeof(addresses[0])] = {};
    const int64_t started = esp_timer_get_time();
    for (size_t i = 0; i < sizeof(values); ++i) {
        if (!healthy || esp_timer_get_time() - started > 50000) {
            cJSON_AddBoolToObject(result, "available", false); return result;
        }
        esp_cam_sensor_reg_val_t reg = {addresses[i], 0};
        struct v4l2_ext_control control = {};
        control.id = ESP_CAM_SENSOR_IOC_G_REG;
        control.size = sizeof(reg); control.p_u8 = reinterpret_cast<uint8_t *>(&reg);
        struct v4l2_ext_controls controls = {};
        controls.ctrl_class = V4L2_CTRL_CLASS_ESP_CAM_IOCTL;
        controls.count = 1; controls.controls = &control;
        if (ioctl(cameraFd, VIDIOC_G_EXT_CTRLS, &controls) != 0) {
            cJSON_AddBoolToObject(result, "available", false); return result;
        }
        values[i] = static_cast<uint8_t>(reg.value);
    }
    cJSON_AddBoolToObject(result, "available", true);
    cJSON_AddNumberToObject(result, "sampled_at_ms", millis());
    cJSON_AddNumberToObject(result, "exposure_raw", ((values[0] & 15u) << 16) | (values[1] << 8) | values[2]);
    cJSON_AddNumberToObject(result, "gain_raw", ((values[4] & 3u) << 8) | values[5]);
    cJSON_AddBoolToObject(result, "aec_manual", values[3] & 1);
    cJSON_AddBoolToObject(result, "agc_manual", values[3] & 2);
    cJSON_AddBoolToObject(result, "vts_manual", values[3] & 4);
    cJSON_AddNumberToObject(result, "manual_control_raw", values[3]);
    cJSON_AddNumberToObject(result, "aec_control_raw", values[6]);
    cJSON_AddNumberToObject(result, "ae_target_high", values[7]);
    cJSON_AddNumberToObject(result, "ae_target_low", values[8]);
    cJSON_AddNumberToObject(result, "gain_ceiling_raw", ((values[9] & 3u) << 8) | values[10]);
    cJSON_AddNumberToObject(result, "hts_raw", (values[11] << 8) | values[12]);
    cJSON_AddNumberToObject(result, "vts_raw", (values[13] << 8) | values[14]);
    cJSON_AddBoolToObject(result, "awb_enabled", values[15] & 1);
    cJSON_AddBoolToObject(result, "awb_manual", values[16] & 8);
    cJSON_AddNumberToObject(result, "awb_control_raw", values[16]);
    esp_video_isp_pipeline_agc_status_t status = ESP_VIDEO_ISP_PIPELINE_AGC_DISABLE;
    const auto agcResult = esp_video_isp_pipeline_get_agc_status(&status);
    cJSON_AddNumberToObject(result, "isp_agc_result", agcResult);
    if (agcResult == ESP_OK) cJSON_AddBoolToObject(result, "isp_agc_enabled", status == ESP_VIDEO_ISP_PIPELINE_AGC_ENABLE);
    return result;
}

static cJSON *statusDocument() {
    auto *result = cJSON_CreateObject();
    if (!result) return nullptr;
    const bool live = healthy && millis() - lastFrameMs <= 2000;
    cJSON_AddStringToObject(result, "firmware", "habitatos_dfr1172_h264");
    cJSON_AddBoolToObject(result, "configured", config != nullptr);
    cJSON_AddBoolToObject(result, "ready", live);
    cJSON_AddNumberToObject(result, "frames", encodedFrames.load());
    cJSON_AddNumberToObject(result, "dropped", droppedFrames.load());
    cJSON_AddStringToObject(result, "error", live ? "" : failure);
    if (auto *imaging = imagingStatus()) cJSON_AddItemToObject(result, "imaging", imaging);
    return result;
}

static cJSON *identity() {
    auto *result = cJSON_CreateObject();
    cJSON_AddNumberToObject(result, "schema_version", 2);
    for (const auto *field : IdentityFields) cJSON_AddStringToObject(result, field, stringField(config, field));
    cJSON_AddStringToObject(result, "device_type", "dfr1172_camera");
    cJSON_AddStringToObject(result, "stream_transport", "rtsp_tcp");
    cJSON_AddStringToObject(result, "codec", "h264");
    cJSON_AddNumberToObject(result, "stream_port", 8554);
    cJSON_AddStringToObject(result, "stream_path", "/stream");
    cJSON_AddNumberToObject(result, "width", Width);
    cJSON_AddNumberToObject(result, "height", Height);
    cJSON_AddNumberToObject(result, "fps", Fps);
    cJSON_AddNumberToObject(result, "bitrate_bps", Bitrate);
    cJSON_AddNumberToObject(result, "gop_frames", Gop);
    cJSON_AddStringToObject(result, "profile", "baseline");
    cJSON_AddBoolToObject(result, "sps_pps_at_idr", true);
    cJSON_AddStringToObject(result, "color_range", "limited");
    cJSON_AddStringToObject(result, "color_matrix", "bt601");
    return result;
}

static bool startCamera() {
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    if (chip.model != CHIP_ESP32P4 || chip.revision >= 300 || ESP.getFlashChipSize() != 16 * 1024 * 1024 || ESP.getPsramSize() < 16 * 1024 * 1024) {
        fail("unsupported_board"); return false;
    }
    ESPVideoCamConfigClass sensorConfig;
    sensorConfig.begin(0, 8, 7);  // Official DFR1172 SCCB SCL/SDA.
    ESPVideoCSIConfigClass csiConfig;
    csiConfig.begin(sensorConfig);
    if (!video.begin(csiConfig)) { fail("csi_init_failed"); return false; }
    cameraFd = open(ESP_VIDEO_MIPI_CSI_DEVICE_NAME, O_RDWR);
    if (cameraFd < 0) { fail("camera_open_failed"); return false; }
    esp_cam_sensor_id_t sensorId = {};
    struct v4l2_ext_control control = {};
    control.id = ESP_CAM_SENSOR_IOC_G_CHIP_ID;
    control.size = sizeof(sensorId);
    control.p_u8 = reinterpret_cast<uint8_t *>(&sensorId);
    struct v4l2_ext_controls controls = {};
    controls.ctrl_class = V4L2_CTRL_CLASS_ESP_CAM_IOCTL;
    controls.count = 1;
    controls.controls = &control;
    if (ioctl(cameraFd, VIDIOC_G_EXT_CTRLS, &controls) != 0 || sensorId.pid != 0x5647) { fail("sensor_probe_failed"); return false; }
    struct v4l2_format format = {};
    format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(cameraFd, VIDIOC_G_FMT, &format) != 0 || format.fmt.pix.width != Width || format.fmt.pix.height != Height) { fail("sensor_dimensions_unsupported"); return false; }
    format.fmt.pix.pixelformat = V4L2_PIX_FMT_YUV420;
    // CSI defaults to full-range YUV, whereas the hardware encoder's SPS does
    // not signal full range. Ask the ISP for video-range YUV to prevent players
    // clipping valid dark pixels below code16. This is a sensor-side conversion.
    format.fmt.pix.quantization = V4L2_QUANTIZATION_LIM_RANGE;
    format.fmt.pix.ycbcr_enc = V4L2_YCBCR_ENC_601;
    format.fmt.pix.colorspace = V4L2_COLORSPACE_SMPTE170M;
    if (ioctl(cameraFd, VIDIOC_S_FMT, &format) != 0 || ioctl(cameraFd, VIDIOC_G_FMT, &format) != 0 || format.fmt.pix.width != Width || format.fmt.pix.height != Height || format.fmt.pix.pixelformat != V4L2_PIX_FMT_YUV420 || format.fmt.pix.quantization != V4L2_QUANTIZATION_LIM_RANGE || format.fmt.pix.ycbcr_enc != V4L2_YCBCR_ENC_601) { fail("capture_format_failed"); return false; }
    struct timeval timeout = {1, 0};
    if (ioctl(cameraFd, VIDIOC_S_DQBUF_TIMEOUT, &timeout) != 0) { fail("capture_timeout_setup_failed"); return false; }
    struct v4l2_requestbuffers request = {};
    request.count = 2;
    request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request.memory = V4L2_MEMORY_MMAP;
    if (ioctl(cameraFd, VIDIOC_REQBUFS, &request) != 0 || request.count != 2) { fail("capture_buffers_failed"); return false; }
    for (unsigned i = 0; i < 2; ++i) {
        struct v4l2_buffer buffer = {};
        buffer.type = request.type; buffer.memory = request.memory; buffer.index = i;
        if (ioctl(cameraFd, VIDIOC_QUERYBUF, &buffer) != 0 || buffer.length < MaxFrame) { fail("capture_buffer_size_failed"); return false; }
        captureSizes[i] = buffer.length;
        captureBuffers[i] = static_cast<uint8_t *>(mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, cameraFd, buffer.m.offset));
        if (captureBuffers[i] == MAP_FAILED || !captureBuffers[i] || ioctl(cameraFd, VIDIOC_QBUF, &buffer) != 0) { fail("capture_map_failed"); return false; }
    }
    esp_h264_enc_cfg_hw_t codecConfig = {};
    // esp_video maps its CSI YUV420 to this hardware packed format (not I420).
    codecConfig.pic_type = ESP_H264_RAW_FMT_O_UYY_E_VYY;
    codecConfig.gop = Gop; codecConfig.fps = Fps;
    codecConfig.res = {Width, Height};
    codecConfig.rc = {Bitrate, 20, 40};
    if (esp_h264_enc_hw_new(&codecConfig, &encoder) != ESP_H264_ERR_OK || esp_h264_enc_open(encoder) != ESP_H264_ERR_OK) { fail("hardware_encoder_failed"); return false; }
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(cameraFd, VIDIOC_STREAMON, &type) != 0) { fail("capture_start_failed"); return false; }
    Serial.printf("CAMERA_SENSOR pid=%04x width=%d height=%d format=packed_yuv420 range=limited matrix=bt601 revision=%d\n", sensorId.pid, Width, Height, chip.revision);
    return true;
}

static void captureTask(void *) {
    auto *encoded = static_cast<uint8_t *>(heap_caps_aligned_alloc(64, MaxFrame, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    idrCache = static_cast<uint8_t *>(heap_caps_malloc(MaxFrame, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!encoded || !idrCache) { free(encoded); fail("encoder_buffer_failed"); vTaskDelete(nullptr); return; }
    int64_t nextFrameUs = 0;
    bool firstIdr = false;
    for (;;) {
        struct v4l2_buffer buffer = {};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; buffer.memory = V4L2_MEMORY_MMAP;
        if (ioctl(cameraFd, VIDIOC_DQBUF, &buffer) != 0) { fail("capture_timeout"); break; }
        if (buffer.index >= 2 || buffer.bytesused < MaxFrame || buffer.bytesused > captureSizes[buffer.index] || (buffer.flags & V4L2_BUF_FLAG_ERROR)) { fail("capture_incomplete"); break; }
        int64_t now = esp_timer_get_time();
        if (now < nextFrameUs) { ioctl(cameraFd, VIDIOC_QBUF, &buffer); continue; }
        // Drain sensor frames continuously; never queue old images behind network I/O.
        if (!nextFrameUs || now - nextFrameUs > 1000000 / Fps) nextFrameUs = now;
        nextFrameUs += 1000000 / Fps;
        esp_h264_enc_in_frame_t input = {};
        input.raw_data = {captureBuffers[buffer.index], MaxFrame}; input.pts = static_cast<uint32_t>(now / 1000);
        esp_h264_enc_out_frame_t output = {};
        output.raw_data = {encoded, MaxFrame};
        auto result = esp_h264_enc_process(encoder, &input, &output);
        if (ioctl(cameraFd, VIDIOC_QBUF, &buffer) != 0) { fail("capture_requeue_failed"); break; }
        if (result != ESP_H264_ERR_OK || !output.length || output.length > MaxFrame) { fail("encode_failed"); break; }
        auto nals = inspectAnnexB(encoded, output.length);
        const bool idr = output.frame_type == ESP_H264_FRAME_TYPE_IDR;
        if (idr && !(nals.idr && nals.sps && nals.pps && nals.baseline)) { fail("encoder_contract_failed"); break; }
        if (idr) {
            xSemaphoreTake(frameLock, portMAX_DELAY);
            memcpy(idrCache, encoded, output.length);
            idrLength = output.length; idrPts = input.pts;
            xSemaphoreGive(frameLock);
            firstIdr = true;
        }
        healthy = firstIdr;
        ++encodedFrames; lastFrameMs = millis();
        // Keep a bounded GOP start available before PLAY too: RTSP implementations
        // may request codec data while building the DESCRIBE response.
        if (waitIdr && !idr) continue;
        xSemaphoreTake(frameLock, portMAX_DELAY);
        if (waitIdr && !idr) { xSemaphoreGive(frameLock); continue; }
        if (uxQueueSpacesAvailable(frames) == 0) { clearFrames(); waitIdr = true; ++droppedFrames; }
        if (!waitIdr || idr) {
            auto *copy = static_cast<uint8_t *>(heap_caps_malloc(output.length, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
            if (copy) {
                memcpy(copy, encoded, output.length);
                Frame frame{copy, output.length, input.pts, idr};
                if (xQueueSend(frames, &frame, 0) == pdTRUE) waitIdr = false;
                else { free(copy); waitIdr = true; }
            } else { clearFrames(); waitIdr = true; ++droppedFrames; }
        }
        xSemaphoreGive(frameLock);
    }
    free(encoded);
    vTaskDelete(nullptr);
}

static int sendVideo(unsigned char *data, unsigned int *length, uint32_t *pts, void *) {
    if (!healthy) { *length = 0; return 0; }
    if (!playing) {
        // DESCRIBE may request codec headers before PLAY. Always have the latest
        // complete SPS/PPS/IDR available, independently of the live queue cadence.
        xSemaphoreTake(frameLock, portMAX_DELAY);
        if (idrLength && idrLength <= *length) {
            memcpy(data, idrCache, idrLength); *length = idrLength; *pts = idrPts;
        } else *length = 0;
        xSemaphoreGive(frameLock);
        return 0;
    }
    Frame frame;
    if (xQueueReceive(frames, &frame, pdMS_TO_TICKS(100)) != pdTRUE) { *length = 0; return 0; }
    if (frame.length > *length || millis() - frame.pts > 500) {
        free(frame.data); *length = 0;
        xSemaphoreTake(frameLock, portMAX_DELAY); clearFrames(); waitIdr = true; xSemaphoreGive(frameLock);
        return 0;
    }
    memcpy(data, frame.data, frame.length);
    *length = frame.length; *pts = frame.pts;
    free(frame.data);
    return 0;
}

static int streamCodec(esp_rtsp_aud_info_t *, esp_rtsp_video_info_t *result, void *) {
    if (result) *result = rtspVideo;
    return 0;
}

static int streamState(esp_rtsp_state_t state, void *) {
    if (state == RTSP_STATE_PLAY || state == RTSP_STATE_TEARDOWN) {
        xSemaphoreTake(frameLock, portMAX_DELAY);
        playing = state == RTSP_STATE_PLAY;
        clearFrames(); waitIdr = true;
        xSemaphoreGive(frameLock);
    }
    return 0;
}

static bool startRtsp() {
    bindAddress = WiFi.localIP().toString();
    rtspVideo = {RTSP_VCODEC_H264, Width, Height, Fps, MaxFrame};
    rtspCallbacks.send_video = sendVideo; rtspCallbacks.stream_codec = streamCodec;
    esp_rtsp_config_t settings = {};
    settings.video_enable = true; settings.local_port = 8554; settings.local_addr = bindAddress.c_str();
    settings.stack_size = 8192; settings.task_prio = 5; settings.mode = RTSP_SERVER;
    settings.video_info = &rtspVideo; settings.data_cb = &rtspCallbacks; settings.state = streamState; settings.trans = RTSP_TRANSPORT_TCP;
    rtsp = esp_rtsp_server_start(&settings);
    return rtsp != nullptr;
}

static void processSerial() {
    while (Serial.available()) {
        const char ch = static_cast<char>(Serial.read());
        if (ch == '\r') continue;
        if (ch != '\n') {
            if (serialLength < sizeof(serialLine) - 1 && !serialOverflow) serialLine[serialLength++] = ch;
            else serialOverflow = true;
            continue;
        }
        serialLine[serialLength] = 0;
        if (!serialOverflow && !std::strcmp(serialLine, "HABITAT_STATUS")) {
            auto *document = statusDocument(); char *body = document ? cJSON_PrintUnformatted(document) : nullptr;
            Serial.println(body ? body : "{\"error\":\"status_unavailable\"}");
            cJSON_free(body); cJSON_Delete(document);
        } else if (!serialOverflow && !std::strncmp(serialLine, "HABITAT_CONFIG ", 15)) {
            auto *candidate = parseConfig(serialLine + 15, serialLength - 15);
            if (candidate && storage.putString("config", serialLine + 15) == serialLength - 15) {
                cJSON_Delete(candidate); memset(serialLine, 0, sizeof(serialLine));
                Serial.println("{\"configured\":true,\"restarting\":true}"); Serial.flush(); delay(200); ESP.restart();
            } else { cJSON_Delete(candidate); Serial.println("{\"configured\":false,\"error\":\"config_invalid_or_write_failed\"}"); }
        } else Serial.println("{\"error\":\"command_invalid\"}");
        memset(serialLine, 0, sizeof(serialLine)); serialLength = 0; serialOverflow = false;
    }
}

void setup() {
    // A whole private configuration line can exceed Arduino's 256-byte default.
    Serial.setRxBufferSize(MaxConfig + 32);
    Serial.begin(115200);
    storage.begin("habitat-camera", false);
    String stored = storage.getString("config", "");
    config = parseConfig(stored.c_str(), stored.length());
    for (size_t i = 0; i < stored.length(); ++i) stored.setCharAt(i, 0);
    stored = "";
    if (!config) { fail("unprovisioned"); return; }
    frames = xQueueCreate(2, sizeof(Frame)); frameLock = xSemaphoreCreateMutex();
    if (!frames || !frameLock) { fail("queue_allocation_failed"); return; }
    if (media_lib_add_default_os_adapter() != ESP_OK || media_lib_add_default_adapter() != ESP_OK) { fail("network_adapter_failed"); return; }
    http.on("/identity", HTTP_GET, []() {
        http.sendHeader("Cache-Control", "no-store");
        if (!healthy || !rtsp || millis() - lastFrameMs > 2000) { http.send(503, "application/json", "{\"error\":\"camera_unavailable\"}"); return; }
        auto *value = identity(); char *body = cJSON_PrintUnformatted(value);
        if (body) http.send(200, "application/json", body); else http.send(503, "application/json", "{}");
        cJSON_free(body); cJSON_Delete(value);
    });
    http.on("/health", HTTP_GET, []() {
        const bool live = healthy && millis() - lastFrameMs <= 2000;
        auto *document = statusDocument(); char *body = document ? cJSON_PrintUnformatted(document) : nullptr;
        http.sendHeader("Cache-Control", "no-store");
        http.send(live && body ? 200 : 503, "application/json", body ? body : "{\"error\":\"status_unavailable\"}");
        cJSON_free(body); cJSON_Delete(document);
    });
    WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.setSleep(false);
    WiFi.begin(stringField(config, "wifi_ssid"), stringField(config, "wifi_password"));
    http.begin();
    if (startCamera()) {
        if (xTaskCreatePinnedToCore(captureTask, "camera-h264", 8192, nullptr, 4, nullptr, 1) != pdPASS) fail("capture_task_failed");
    }
}

void loop() {
    processSerial();
    if (config && frames) {
        http.handleClient();
        if (rtsp && (WiFi.status() != WL_CONNECTED || bindAddress != WiFi.localIP().toString())) {
            playing = false; esp_rtsp_server_stop(rtsp); rtsp = nullptr;
        }
        if (!rtsp && healthy && WiFi.status() == WL_CONNECTED && static_cast<int32_t>(millis() - retryAt) >= 0) {
            if (startRtsp()) Serial.printf("CAMERA_READY camera_id=%s ip=%s transport=rtsp_tcp port=8554\n", stringField(config, "camera_id"), bindAddress.c_str());
            else Serial.println("CAMERA_ERROR rtsp_start_failed");
            retryAt = millis() + 5000;
        }
    }
    delay(5);
}
