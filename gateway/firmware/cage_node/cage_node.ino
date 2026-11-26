// BB6 ESP32: sensor GPIOs are configured per node; legacy defaults below.
// Sensors remain the default. Optional N1 R15 request bridge is locked by default.
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Adafruit_SHT31.h>
#include <OneWire.h>
#include <esp_system.h>
#include <driver/gpio.h>
#include <time.h>
#include <string.h>
#include <sys/time.h>
#include "config.h"
#ifndef HABITAT_IR_CONTROL
#define HABITAT_IR_CONTROL 0
#endif
#ifndef HABITAT_IR_OUTPUTS
#define HABITAT_IR_OUTPUTS 0
#endif
#if HABITAT_IR_CONTROL != 0 && HABITAT_IR_CONTROL != 1
#error "HABITAT_IR_CONTROL must be 0 or 1."
#endif
#if HABITAT_IR_OUTPUTS != 0 && HABITAT_IR_OUTPUTS != 1
#error "HABITAT_IR_OUTPUTS must be 0 or 1."
#endif
#if HABITAT_IR_OUTPUTS && !HABITAT_IR_CONTROL
#error "IR outputs require the IR lease controller."
#endif
#ifndef HABITAT_R11_PUMP
#define HABITAT_R11_PUMP 0
#endif
#ifndef HABITAT_R11_PUMP_OUTPUTS
#define HABITAT_R11_PUMP_OUTPUTS 0
#endif
#if HABITAT_R11_PUMP != 0 || HABITAT_R11_PUMP_OUTPUTS != 0
#error "Pump support is not installed; both pump options must remain 0."
#endif
#ifndef HABITAT_R15_CENTRAL
#define HABITAT_R15_CENTRAL 0
#endif
#ifndef HABITAT_R15_REQUEST_OUTPUTS
#define HABITAT_R15_REQUEST_OUTPUTS 0
#endif
#if HABITAT_R15_CENTRAL != 0 || HABITAT_R15_REQUEST_OUTPUTS != 0
#error "BB6 sensor wiring requires both R15 options to be 0."
#endif
// Sensor GPIO configuration: override the complete set in private config.h.
#if defined(HABITAT_SHT_SDA_PIN) || defined(HABITAT_SHT_SCL_PIN) || defined(HABITAT_T2_PIN) || defined(HABITAT_T3_PIN)
#if !defined(HABITAT_SHT_SDA_PIN) || !defined(HABITAT_SHT_SCL_PIN) || !defined(HABITAT_T2_PIN) || !defined(HABITAT_T3_PIN)
#error "Configure all four sensor GPIOs together."
#endif
#else
#define HABITAT_SHT_SDA_PIN 21
#define HABITAT_SHT_SCL_PIN 22
#define HABITAT_T2_PIN 18
#define HABITAT_T3_PIN 19
#endif
constexpr bool sensorOutputPin(int pin) {
  // Classic ESP32: exclude flash, UART, strapping and input-only pins.
  return pin == 4 || pin == 13 || pin == 14 || pin == 16 || pin == 17 ||
         pin == 18 || pin == 19 || pin == 21 || pin == 22 || pin == 23 ||
         pin == 25 || pin == 26 || pin == 27 || pin == 32 || pin == 33;
}
static_assert(sensorOutputPin(HABITAT_SHT_SDA_PIN) && sensorOutputPin(HABITAT_SHT_SCL_PIN) &&
              sensorOutputPin(HABITAT_T2_PIN) && sensorOutputPin(HABITAT_T3_PIN),
              "Sensor GPIO must be an available classic ESP32 output pin.");
static_assert(HABITAT_SHT_SDA_PIN != HABITAT_SHT_SCL_PIN && HABITAT_SHT_SDA_PIN != HABITAT_T2_PIN &&
              HABITAT_SHT_SDA_PIN != HABITAT_T3_PIN && HABITAT_SHT_SCL_PIN != HABITAT_T2_PIN &&
              HABITAT_SHT_SCL_PIN != HABITAT_T3_PIN && HABITAT_T2_PIN != HABITAT_T3_PIN,
              "Sensor GPIOs must be distinct.");
// End sensor GPIO configuration.
#if HABITAT_R15_CENTRAL
#include "r15_bridge.h"
r15::Bridge r15Bridge(HABITAT_R15_REQUEST_OUTPUTS == 1);
portMUX_TYPE r15Mux = portMUX_INITIALIZER_UNLOCKED;
bool r15Network = false, r15Ready = false;
char r15CommandTopic[256] = {};
uint32_t r15NextStatus = 0;
constexpr unsigned r15ReqPins[] = {25, 32, 23};
constexpr unsigned r15HbPin = 26, r15ArmedPin = 19, r15LevelPin = 33;
#endif

Adafruit_SHT31 sht;
WiFiClientSecure tls;
PubSubClient mqtt(tls);
constexpr uint8_t shtSdaPin = HABITAT_SHT_SDA_PIN, shtSclPin = HABITAT_SHT_SCL_PIN,
                  hotPin = HABITAT_T2_PIN, coolPin = HABITAT_T3_PIN;
OneWire hotBus(hotPin), coolBus(coolPin);
uint8_t hotRom[8], coolRom[8];
bool hotFound = false, coolFound = false, shtFound = false, converting = false;
bool hotStarted = false, coolStarted = false;
const char *hotDiagnostic = "not_sampled", *coolDiagnostic = "not_sampled";
uint32_t nextSample = 0, convertAt = 0, nextConnect = 0;

void setProbeDiagnostic(const char **diagnostic, const char *reason) {
  if (diagnostic) *diagnostic = reason;
}

bool findProbe(OneWire &bus, uint8_t *rom, const char *channel, unsigned gpio,
               const char **diagnostic = nullptr) {
  bus.reset_search();
  uint8_t candidate[8], other[8];
  if (!bus.search(candidate)) {
    setProbeDiagnostic(diagnostic, "not_detected"); return false;
  }
  if (candidate[0] != 0x28) {
    setProbeDiagnostic(diagnostic, "unexpected_family"); return false;
  }
  if (OneWire::crc8(candidate, 7) != candidate[7]) {
    setProbeDiagnostic(diagnostic, "rom_crc_error"); return false;
  }
  if (bus.search(other)) {
    setProbeDiagnostic(diagnostic, "multiple_devices"); return false;
  }
  setProbeDiagnostic(diagnostic, "found");
  if (memcmp(rom, candidate, 8) != 0) {
    // Session-only diagnostics: identity is not pinned or stored across reboots.
    Serial.printf("probe channel=%s gpio=%u rom=", channel, gpio);
    for (uint8_t value : candidate) Serial.printf("%02X", value);
    Serial.printf(" event=%s\n", rom[0] == 0x28 ? "changed" : "found");
    memcpy(rom, candidate, 8);
  }
  return true;
}

bool startProbe(OneWire &bus, const uint8_t *rom, bool found,
                const char **diagnostic = nullptr) {
  if (!found) return false;  // Preserve the discovery failure.
  if (!bus.reset()) {
    setProbeDiagnostic(diagnostic, "lost_before_power_check"); return false;
  }
  // Completion polling requires VDD power, not parasite power (DS18B20 datasheet).
  bus.select(rom); bus.write(0xB4);
  if (bus.read_bit() != 1) {
    setProbeDiagnostic(diagnostic, "external_power_not_reported"); return false;
  }
  if (!bus.reset()) {
    setProbeDiagnostic(diagnostic, "lost_before_conversion"); return false;
  }
  bus.select(rom); bus.write(0x44, 0);
  if (bus.read_bit() != 0) {
    setProbeDiagnostic(diagnostic, "conversion_not_started"); return false;
  }
  setProbeDiagnostic(diagnostic, "converting");
  return true;  // A busy response was observed for this conversion.
}

float readProbe(OneWire &bus, const uint8_t *rom, bool &started,
                 const char **diagnostic = nullptr) {
  const bool active = started;
  started = false;  // One result per conversion, including failed attempts.
  if (!active) return NAN;  // Preserve the discovery/conversion failure.
  if (bus.read_bit() != 1) {
    setProbeDiagnostic(diagnostic, "conversion_incomplete"); return NAN;
  }
  if (!bus.reset()) {
    setProbeDiagnostic(diagnostic, "lost_before_read"); return NAN;
  }
  bus.select(rom); bus.write(0xBE);
  uint8_t raw[9];
  for (int i=0; i<9; ++i) raw[i] = bus.read();
  if (OneWire::crc8(raw, 8) != raw[8]) {
    setProbeDiagnostic(diagnostic, "scratchpad_crc_error"); return NAN;
  }
  int16_t number = (int16_t)((raw[1] << 8) | raw[0]);
  float value = number / 16.0f;
  if (value < -20 || value > 60) {
    setProbeDiagnostic(diagnostic, "out_of_range"); return NAN;
  }
  setProbeDiagnostic(diagnostic, "ok");
  return value;
}

String reading(float value) {
  if (!isfinite(value)) return "{\"value\":null,\"quality\":\"invalid\"}";
  return "{\"value\":" + String(value, 3) + ",\"quality\":\"valid\"}";
}

void logSensorDiagnostics(const char *shtReason, const char *hotReason, const char *coolReason) {
  static uint32_t nextLog = 0;
  uint32_t nowMs = millis();
  if ((int32_t)(nowMs - nextLog) < 0) return;
  nextLog = nowMs + 30000;
  // Address-only checks on the existing sensor bus, never a scan of other GPIOs.
  // Wire's existing transaction timeout bounds each check (50ms on this core).
  Wire.beginTransmission(0x44); uint8_t ack44 = Wire.endTransmission();
  Wire.beginTransmission(0x45); uint8_t ack45 = Wire.endTransmission();
  // Read peripheral input levels directly; digitalRead is restricted by the
  // Arduino pin manager when these pins belong to Wire. These are not voltages.
  Serial.printf("SENSOR sda=%d scl=%d dq_t2=%d dq_t3=%d i2c44=%u i2c45=%u sht=%s T2=%s T3=%s\n",
    gpio_get_level(gpio_num_t(shtSdaPin)), gpio_get_level(gpio_num_t(shtSclPin)),
    gpio_get_level(gpio_num_t(hotPin)), gpio_get_level(gpio_num_t(coolPin)),
    ack44, ack45, shtReason, hotReason, coolReason);
}

String uuid() {
  uint8_t b[16]; esp_fill_random(b, sizeof(b));
  b[6] = (b[6]&15)|64; b[8] = (b[8]&63)|128;
  char s[37];
  snprintf(s, sizeof(s), "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
    b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7],b[8],b[9],b[10],b[11],b[12],b[13],b[14],b[15]);
  return String(s);
}

#if HABITAT_R15_CENTRAL
uint64_t r15UtcMs() {
  struct timeval value; gettimeofday(&value, nullptr);
  return uint64_t(value.tv_sec)*1000+uint64_t(value.tv_usec)/1000;
}

// This independent task enforces GPIO deadlines while TLS/MQTT/I2C may block.
// Pico's separate request/heartbeat timeout and locked BENCH image are unchanged.
void r15SafetyTask(void *) {
  uint8_t lastMask=0; bool lastHb=false; TickType_t wake=xTaskGetTickCount();
  for (;;) {
    bool armed=digitalRead(r15ArmedPin)==HIGH, level=digitalRead(r15LevelPin)==HIGH;
    portENTER_CRITICAL(&r15Mux);
    r15Bridge.tick(millis(),r15Network,armed,level);
    uint8_t mask=r15Bridge.requests(); bool hb=r15Bridge.heartbeat();
    if (mask!=lastMask) {
      for (unsigned pin:r15ReqPins) gpio_set_level(gpio_num_t(pin),LOW);
      for (unsigned i=0;i<3;++i) if (mask&(1u<<i)) gpio_set_level(gpio_num_t(r15ReqPins[i]),HIGH);
      lastMask=mask;
    }
    if (hb!=lastHb) { gpio_set_level(gpio_num_t(r15HbPin),hb?HIGH:LOW); lastHb=hb; }
    // Apply the snapshot before a concurrent STOP can return: no stale reassertion.
    portEXIT_CRITICAL(&r15Mux);
    vTaskDelayUntil(&wake,pdMS_TO_TICKS(20));
  }
}

bool r15PublishAck(const r15::Command &command,r15::Result result) {
  char payload[768];
  int size=snprintf(payload,sizeof(payload),
    "{\"schema_version\":1,\"session_id\":\"%s\",\"command_id\":\"%s\",\"sequence\":%lu,"
    "\"zone\":%lu,\"status\":\"%s\",\"reason\":\"%s\",\"requested_state\":%s,"
    "\"duplicate\":%s,\"request_hold_ms\":%lu,\"execution_status\":\"unverified\","
    "\"actual_state\":null,\"observed_at_ms\":%llu}",
    command.session,command.id,(unsigned long)command.sequence,(unsigned long)command.zone,
    result.status,result.reason,result.requested?"true":"false",result.duplicate?"true":"false",
    (unsigned long)command.hold_ms,(unsigned long long)r15UtcMs());
  return size>0 && size<int(sizeof(payload)) &&
    mqtt.publish((String(TOPIC_BASE)+"/r15/ack").c_str(),payload,false);
}

void r15Message(char *topic,uint8_t *payload,unsigned int length) {
  if (!r15Ready || strcmp(topic,r15CommandTopic)) return;
  r15::Command command;
  if (!r15::parse(payload,length,command)) { Serial.println("r15_invalid_frame"); return; }
  const bool armed=digitalRead(r15ArmedPin)==HIGH, level=digitalRead(r15LevelPin)==HIGH;
  const uint64_t utc=r15UtcMs(); const uint32_t at=millis();
  portENTER_CRITICAL(&r15Mux);
  r15::Result result=r15Bridge.receive(command,utc,at,armed,level);
  portEXIT_CRITICAL(&r15Mux);
  // Heartbeats are reported in status, not as a stream of command acknowledgements.
  if (command.action!=r15::Action::Heartbeat || !strcmp(result.status,"rejected"))
    r15PublishAck(command,result);
}

void r15Connected() {
  if (!r15Ready) return;
  String nonce=uuid();
  int length=snprintf(r15CommandTopic,sizeof(r15CommandTopic),"%s/r15/command/%s",TOPIC_BASE,nonce.c_str());
  if (length<=0 || length>=int(sizeof(r15CommandTopic))) {
    Serial.println("r15_topic_too_long"); return;
  }
  portENTER_CRITICAL(&r15Mux);
  r15Bridge.connect(nonce.c_str()); r15Network=true;
  portEXIT_CRITICAL(&r15Mux);
  if (!mqtt.subscribe(r15CommandTopic,1)) {
    portENTER_CRITICAL(&r15Mux);
    r15Bridge.disconnect(); r15Network=false;
    portEXIT_CRITICAL(&r15Mux);
  }
  r15NextStatus=0;
}

void r15Service() {
  const bool network=mqtt.connected() && WiFi.status()==WL_CONNECTED;
  portENTER_CRITICAL(&r15Mux);
  if (!network && r15Network) r15Bridge.disconnect();
  r15Network=network;
  portEXIT_CRITICAL(&r15Mux);
  if (!r15Ready || !network) return;
  r15::Completion completed;
  portENTER_CRITICAL(&r15Mux);
  bool pending=r15Bridge.completion(completed);
  portEXIT_CRITICAL(&r15Mux);
  if (pending && r15PublishAck(completed.command,{"execution_unverified",completed.reason,false,false})) {
    portENTER_CRITICAL(&r15Mux);
    r15Bridge.acknowledged_completion(completed.command.sequence);
    portEXIT_CRITICAL(&r15Mux);
  }
  uint32_t now=millis();
  if ((int32_t)(now-r15NextStatus)<0) return;
  r15NextStatus=now+500;
  char session[37],active[37]; bool lease,stopped,hb; uint8_t mask;
  portENTER_CRITICAL(&r15Mux);
  memcpy(session,r15Bridge.nonce(),37); strcpy(active,r15Bridge.active());
  lease=r15Bridge.lease(now); stopped=r15Bridge.latched(); hb=r15Bridge.heartbeat(); mask=r15Bridge.requests();
  portEXIT_CRITICAL(&r15Mux);
  if (!session[0]) return;
  // Topic/session and raw GPIO levels are not proof of Pico power, ARM or water flow.
  char payload[1024];
  int size=snprintf(payload,sizeof(payload),
    "{\"schema_version\":1,\"session_id\":\"%s\",\"command_topic\":\"%s\","
    "\"outputs_locked\":%s,\"max_request_hold_ms\":%lu,\"request_mask\":%u,\"active_command_id\":\"%s\","
    "\"gateway_lease_valid\":%s,\"stop_latched\":%s,\"heartbeat_output\":%s,"
    "\"status_pin_levels\":{\"armed\":%s,\"level\":%s},"
    "\"execution_status\":\"unverified\",\"actual_state\":null,\"observed_at_ms\":%llu}",
    session,r15CommandTopic,HABITAT_R15_REQUEST_OUTPUTS==1?"false":"true",
    (unsigned long)r15::MAX_HOLD_MS,unsigned(mask),active,
    lease?"true":"false",stopped?"true":"false",hb?"true":"false",
    digitalRead(r15ArmedPin)==HIGH?"true":"false",digitalRead(r15LevelPin)==HIGH?"true":"false",
    (unsigned long long)r15UtcMs());
  if (size>0 && size<int(sizeof(payload)))
    mqtt.publish((String(TOPIC_BASE)+"/r15/hello").c_str(),payload,false);
}
#endif

#if HABITAT_IR_CONTROL
#include "ir_runtime.h"
#endif

void setup() {
#if HABITAT_IR_CONTROL
  irSetup();
#endif
  Serial.begin(115200);
#if HABITAT_IR_CONTROL
  if (!irReady) Serial.println("IR safety task failed; IR locked LOW");
#endif
#if HABITAT_R15_CENTRAL
  // Set the output latch before enabling the driver; digitalWrite needs OUTPUT mode.
  for (unsigned pin:r15ReqPins) { gpio_set_level(gpio_num_t(pin),LOW); pinMode(pin,OUTPUT); }
  gpio_set_level(gpio_num_t(r15HbPin),LOW); pinMode(r15HbPin,OUTPUT);
  // Destination-domain pull-ups only; raw HIGH cannot distinguish SAFE power loss.
  pinMode(r15ArmedPin,INPUT_PULLUP); pinMode(r15LevelPin,INPUT_PULLUP);
  r15Ready=xTaskCreate(r15SafetyTask,"r15-safety",3072,nullptr,3,nullptr)==pdPASS;
  if (!r15Ready) Serial.println("r15_task_unavailable_outputs_low");
#endif
  Wire.begin(shtSdaPin, shtSclPin);
  Serial.printf("SENSOR_PINS sda=%u scl=%u T2=%u T3=%u\n",
                shtSdaPin, shtSclPin, hotPin, coolPin);
  shtFound = sht.begin(0x45) || sht.begin(0x44);
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.cloudflare.com");
  tls.setCACert(MQTT_CA);
  mqtt.setServer(MQTT_HOST, 8883); mqtt.setBufferSize(1536); mqtt.setSocketTimeout(5);
#if HABITAT_IR_CONTROL
  mqtt.setCallback(irMessage); mqtt.setSocketTimeout(1);
  Serial.println("IR GPIO4 lease control enabled; actual illumination unverified");
#endif
#if HABITAT_R15_CENTRAL
  mqtt.setCallback(r15Message); mqtt.setSocketTimeout(1);
  Serial.println("HabitatOS N1 R15 request bridge; physical execution unverified");
#elif HABITAT_IR_CONTROL
  Serial.println("HabitatOS sensor node with IR lease control");
#else
  Serial.println("HabitatOS sensor node; outputs absent; waiting for network/time");
#endif
}

void loop() {
  uint32_t nowMs = millis();
  time_t now = time(nullptr);
  // BB6_NETWORK_DIAGNOSTICS
  static uint32_t nextNetLog = 0;
  if ((int32_t)(nowMs - nextNetLog) >= 0) {
    nextNetLog = nowMs + 5000;
    Serial.printf(
      "NET wifi=%d ip=%s clock_gate=%d mqtt=%d mqtt_state=%d\n",
      WiFi.status() == WL_CONNECTED ? 1 : 0,
      WiFi.localIP().toString().c_str(),
      now > 1700000000 ? 1 : 0,
      mqtt.connected() ? 1 : 0,
      mqtt.state());
  }

  if (WiFi.status() == WL_CONNECTED && now > 1700000000 && !mqtt.connected()
      && (int32_t)(nowMs-nextConnect) >= 0) {
    nextConnect = nowMs+5000;
    String topic = String(TOPIC_BASE)+"/status";
    if (mqtt.connect(MQTT_USER, MQTT_USER, MQTT_PASSWORD, topic.c_str(), 1, true, "{\"online\":false}")) {
      mqtt.publish(topic.c_str(), "{\"online\":true}", true);
#if HABITAT_R15_CENTRAL
      r15Connected();
#endif
#if HABITAT_IR_CONTROL
      irConnected();
#endif
    }
  }
  mqtt.loop();
#if HABITAT_IR_CONTROL
  irService();
#endif
#if HABITAT_R15_CENTRAL
  r15Service();
#endif
  if (!converting && (int32_t)(nowMs-nextSample) >= 0) {
    hotFound = findProbe(hotBus, hotRom, "T2", hotPin, &hotDiagnostic);
    coolFound = findProbe(coolBus, coolRom, "T3", coolPin, &coolDiagnostic);
    hotStarted = startProbe(hotBus, hotRom, hotFound, &hotDiagnostic);
    coolStarted = startProbe(coolBus, coolRom, coolFound, &coolDiagnostic);
    // MQTT connection attempts above may have blocked; time from the actual start.
    uint32_t sampleStartedAt = millis();
    convertAt = sampleStartedAt+800; nextSample = sampleStartedAt+5000; converting = true;
  }
  if (converting && (int32_t)(nowMs-convertAt) >= 0) {
    converting = false;
    if (!shtFound) shtFound = sht.begin(0x45) || sht.begin(0x44);
    float air = shtFound ? sht.readTemperature() : NAN;
    float rh = shtFound ? sht.readHumidity() : NAN;
    const char *shtReason = !shtFound ? "init_failed" :
      (!isfinite(air) || !isfinite(rh)) ? "read_failed" :
      (air < -20 || air > 60 || rh < 0 || rh > 100) ? "out_of_range" : "ok";
    if (!isfinite(air) || !isfinite(rh)) shtFound = false;
    if (air < -20 || air > 60) air = NAN;
    if (rh < 0 || rh > 100) rh = NAN;
    float hot = readProbe(hotBus, hotRom, hotStarted, &hotDiagnostic);
    float cool = readProbe(coolBus, coolRom, coolStarted, &coolDiagnostic);
    if (mqtt.connected() && now > 1700000000) {
      struct tm utc; gmtime_r(&now, &utc); char stamp[32];
      strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%SZ", &utc);
      String data = "{\"schema_version\":1,\"data_source\":\"sensor\",\"message_id\":\""+uuid()+
        "\",\"sampled_at\":\""+String(stamp)+"\",\"geometry_revision\":1,\"placement_revision\":1,\"readings\":{"+
        "\"T1\":"+reading(air)+",\"RH1\":"+reading(rh)+",\"T2\":"+reading(hot)+",\"T3\":"+reading(cool)+"},\"actuators\":{}}";
      if (!mqtt.publish((String(TOPIC_BASE)+"/telemetry").c_str(), data.c_str(), false)) Serial.println("telemetry_publish_failed");
    }
    logSensorDiagnostics(shtReason, hotDiagnostic, coolDiagnostic);
  }
  delay(5);
}
