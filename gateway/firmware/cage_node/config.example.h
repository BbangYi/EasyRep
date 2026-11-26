#pragma once
// Public example only. Generate/store actual node configuration outside source.
// The MQTT identity and topic must match this node's store/cage registration.
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "YOUR_STORE_BROKER_IP";
const char* MQTT_USER = "YOUR_NODE_ID";
const char* MQTT_PASSWORD = "YOUR_NODE_PASSWORD";
const char* TOPIC_BASE = "habitat/v1/YOUR_SITE_ID/cages/YOUR_CAGE_ID/nodes/YOUR_NODE_ID";
const char* MQTT_CA = "REPLACE_WITH_YOUR_BROKER_CA_PEM";

#define HABITAT_R15_CENTRAL 0
#define HABITAT_R15_REQUEST_OUTPUTS 0
// Legacy BB6 layout. For the reviewed 38-pin A1 sensor layout use 25/26/32/33.
// Configure all four together; use the verified wiring for the target node.
#define HABITAT_SHT_SDA_PIN 21
#define HABITAT_SHT_SCL_PIN 22
#define HABITAT_T2_PIN 18
#define HABITAT_T3_PIN 19

// Pump hardware is not installed; nonzero values are rejected by this firmware.
#define HABITAT_R11_PUMP 0
#define HABITAT_R11_PUMP_OUTPUTS 0

// Optional IR GPIO4 -> DFR0457 S on the reviewed 30-pin BB6 layout only.
// External R3 10k pull-down holds OFF during reset. Cameras use USB/Wi-Fi.
// Enable CONTROL in the private node config to commission with OUTPUTS locked.
#define HABITAT_IR_CONTROL 0
#define HABITAT_IR_OUTPUTS 0
