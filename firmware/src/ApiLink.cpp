#include "ApiLink.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <atomic>

#include "config.h"

namespace ApiLink {
namespace {

struct Report {
  char json[cfg::REPORT_MAX_LEN];
};

QueueHandle_t reportSlot;    // length 1, overwritten: only the latest report is kept
QueueHandle_t commandQueue;  // commands from the API, applied by loop()

// Gate mode from the last reply: written by the API task (core 0), read by loop() (core 1)
std::atomic<bool> accountMode{false};
std::atomic<uint32_t> accountModeSeenMs{0};

bool isHttps() { return strncmp(secrets::API_URL, "https://", 8) == 0; }

// Logs Wi-Fi state changes once, instead of on every report.
bool wifiReady() {
  static bool wasConnected = false;
  const bool connected = WiFi.status() == WL_CONNECTED;
  if (connected != wasConnected) {
    wasConnected = connected;
    if (connected) {
      Serial.printf("[wifi] connected, IP %s\n", WiFi.localIP().toString().c_str());
    } else {
      Serial.println("[wifi] disconnected, reconnecting...");
    }
  }
  return connected;
}

void handleReply(const String& body, uint32_t elapsedMs) {
  JsonDocument doc;
  if (deserializeJson(doc, body)) {
    Serial.printf("[api] 200 in %lu ms, but the reply is not JSON\n", (unsigned long)elapsedMs);
    return;
  }
  const char* command = doc["barrier_command"] | "none";
  const int freeSpots = doc["free_spots"] | -1;
  const char* gateMode = doc["gate_mode"] | "auto";
  Serial.printf("[api] 200 in %lu ms -> command %s, %d free, gate %s\n", (unsigned long)elapsedMs,
                command, freeSpots, gateMode);

  const bool account = strcmp(gateMode, "account") == 0;
  if (account) accountModeSeenMs = millis();
  accountMode = account;

  Command c = Command::NONE;
  if (strcmp(command, "open") == 0) c = Command::OPEN;
  if (strcmp(command, "close") == 0) c = Command::CLOSE;
  if (c != Command::NONE) xQueueSend(commandQueue, &c, 0);
}

void post(const char* json) {
  // One client of each kind, reused across requests. https is for the tunnel fallback;
  // the certificate isn't checked (demo only, the API key still protects the endpoint).
  static WiFiClient plainClient;
  static WiFiClientSecure tlsClient;
  static bool tlsReady = false;
  if (isHttps() && !tlsReady) {
    tlsClient.setInsecure();
    tlsReady = true;
  }

  HTTPClient http;
  if (isHttps()) {
    http.begin(tlsClient, secrets::API_URL);
  } else {
    http.begin(plainClient, secrets::API_URL);
  }
  http.setConnectTimeout(cfg::HTTP_TIMEOUT_MS);
  http.setTimeout(cfg::HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", secrets::API_KEY);

  const uint32_t start = millis();
  const int code = http.POST(reinterpret_cast<uint8_t*>(const_cast<char*>(json)), strlen(json));
  const uint32_t elapsed = millis() - start;

  if (code == HTTP_CODE_OK) {
    handleReply(http.getString(), elapsed);
  } else if (code > 0) {  // the API answered, but refused the report (401 key, 422 format...)
    Serial.printf("[api] HTTP %d: %s\n", code, http.getString().c_str());
  } else {  // no answer at all: API not running, wrong URL, gateway off...
    Serial.printf("[api] unreachable (%s): %s\n", HTTPClient::errorToString(code).c_str(),
                  secrets::API_URL);
  }
  http.end();
}

void task(void*) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  Serial.printf("[wifi] connecting to %s...\n", secrets::WIFI_SSID);
  WiFi.begin(secrets::WIFI_SSID, secrets::WIFI_PASSWORD, secrets::WIFI_CHANNEL);

  Report report;
  for (;;) {
    // Sleeps until loop() submits a report (at least one heartbeat every few seconds).
    if (xQueueReceive(reportSlot, &report, portMAX_DELAY) != pdTRUE) continue;
    if (!wifiReady()) continue;  // dropped: the next heartbeat carries the full state
    post(report.json);
  }
}

}  // namespace

void begin() {
  reportSlot = xQueueCreate(1, sizeof(Report));
  commandQueue = xQueueCreate(4, sizeof(Command));
  // Core 0 runs the Wi-Fi stack; loop() runs on core 1, so sensing is never held up.
  xTaskCreatePinnedToCore(task, "api_link", cfg::API_TASK_STACK, nullptr, 1, nullptr, 0);
}

void submit(const char* json) {
  Report report;
  strlcpy(report.json, json, sizeof(report.json));
  xQueueOverwrite(reportSlot, &report);
}

Command pollCommand() {
  Command c = Command::NONE;
  xQueueReceive(commandQueue, &c, 0);
  return c;
}

bool apiControlsGate() {
  return accountMode && millis() - accountModeSeenMs < cfg::API_GATE_TAKEOVER_MS;
}

}  // namespace ApiLink
