#pragma once

// Network settings and the API key.
// Copy this file to secrets.h (git-ignored) and put your own values there;
// config.h uses secrets.h when it exists, otherwise these defaults.
namespace secrets {

// Wokwi's simulated open access point. On real hardware: your Wi-Fi.
constexpr const char* WIFI_SSID = "Wokwi-GUEST";
constexpr const char* WIFI_PASSWORD = "";
constexpr int WIFI_CHANNEL = 6;  // Wokwi-GUEST is on channel 6 (skips the scan); 0 = any

// host.wokwi.internal = the computer running the Wokwi VS Code extension.
// Through a tunnel instead: "https://<your-tunnel>/api/v1/sensors/reading".
constexpr const char* API_URL = "http://host.wokwi.internal:8000/api/v1/sensors/reading";

// Must match API_KEY in the backend's .env
constexpr const char* API_KEY = "change-me";

}  // namespace secrets
