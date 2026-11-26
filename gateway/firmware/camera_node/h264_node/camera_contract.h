#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include "cJSON.h"

namespace habitat_camera {
constexpr int Width = 800, Height = 800, Fps = 20, Bitrate = 2000000, Gop = 20;
constexpr size_t MaxConfig = 4096, MaxFrame = Width * Height * 3 / 2;
constexpr const char *IdentityFields[] = {"site_id", "gateway_id", "cage_id", "camera_id", "view"};
constexpr const char *ConfigFields[] = {"schema_version", "site_id", "gateway_id", "cage_id", "camera_id", "view", "wifi_ssid", "wifi_password"};

inline bool identifier(const char *value) {
    if (!value || !*value || std::strlen(value) > 64) return false;
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(value); *p; ++p)
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') || *p == '_' || *p == '-')) return false;
    return true;
}

inline const char *stringField(const cJSON *config, const char *field) {
    const auto *item = cJSON_GetObjectItemCaseSensitive(config, field);
    return cJSON_IsString(item) ? item->valuestring : nullptr;
}

// Strictly preserve the deployed v1 private configuration schema. It is separate
// from the public v2 transport identity; neither protocol accepts remote URLs.
inline bool validConfig(const cJSON *config) {
    if (!cJSON_IsObject(config)) return false;
    unsigned seen = 0, count = 0;
    for (auto *item = config->child; item; item = item->next) {
        unsigned flag = 0;
        for (unsigned i = 0; i < 8; ++i) if (item->string && !std::strcmp(item->string, ConfigFields[i])) flag = 1u << i;
        if (!flag || (seen & flag)) return false;
        seen |= flag;
        ++count;
    }
    if (count != 8 || seen != 255) return false;
    const auto *version = cJSON_GetObjectItemCaseSensitive(config, "schema_version");
    if (!cJSON_IsNumber(version) || version->valuedouble != 1) return false;
    for (unsigned i = 0; i < 4; ++i) if (!identifier(stringField(config, IdentityFields[i]))) return false;
    const char *view = stringField(config, "view");
    if (!view || (std::strcmp(view, "top") && std::strcmp(view, "front"))) return false;
    const char *ssid = stringField(config, "wifi_ssid"), *password = stringField(config, "wifi_password");
    if (!ssid || !password || !*ssid || std::strlen(ssid) > 32) return false;
    size_t n = std::strlen(password);
    if (n >= 8 && n <= 63) return true;
    if (n != 64) return false;
    return std::strspn(password, "0123456789abcdefABCDEF") == 64;
}

inline cJSON *parseConfig(const char *data, size_t size) {
    if (!data || !size || size > MaxConfig || std::memchr(data, 0, size)) return nullptr;
    // cJSON strings cannot represent embedded NULs; reject their JSON spelling.
    for (size_t i = 0; i + 5 < size; ++i)
        if (data[i] == '\\' && !std::memcmp(data + i, "\\u0000", 6)) return nullptr;
    const char *end = nullptr;
    auto *config = cJSON_ParseWithLengthOpts(data, size, &end, false);
    while (end && end < data + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t')) ++end;
    if (!config || end != data + size || !validConfig(config)) { cJSON_Delete(config); return nullptr; }
    return config;
}

struct NalSummary { bool sps = false, pps = false, idr = false, baseline = false; };
inline NalSummary inspectAnnexB(const uint8_t *data, size_t length) {
    NalSummary result;
    for (size_t i = 0; i + 3 < length; ++i) {
        if (data[i] || data[i + 1]) continue;
        size_t prefix = data[i + 2] == 1 ? 3 : (data[i + 2] == 0 && data[i + 3] == 1 ? 4 : 0);
        if (!prefix || i + prefix >= length) continue;
        const auto type = data[i + prefix] & 31;
        if (type == 7) { result.sps = true; result.baseline = i + prefix + 1 < length && data[i + prefix + 1] == 66; }
        if (type == 8) result.pps = true;
        if (type == 5) result.idr = true;
        i += prefix;
    }
    return result;
}
}  // namespace habitat_camera
