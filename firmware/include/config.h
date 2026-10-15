#pragma once

#include <Arduino.h>

// Wi-Fi + API settings: secrets.h (git-ignored) if present, otherwise the example defaults.
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

// All pins, thresholds and timings in one place.
namespace cfg {

constexpr const char* DEVICE_ID = "esp32-parking-01";

struct SpotPins {
  const char* id;
  uint8_t trig;
  uint8_t echo;  // GPIO 34/35/36/39 are input-only: ideal for echo signals
  uint8_t ledGreen;
  uint8_t ledRed;
};

constexpr SpotPins SPOTS[] = {
    {"P1", 4, 34, 16, 17},
    {"P2", 5, 35, 18, 19},
    {"P3", 23, 36, 25, 26},
    {"P4", 27, 39, 32, 33},
};
constexpr size_t SPOT_COUNT = sizeof(SPOTS) / sizeof(SPOTS[0]);

constexpr uint8_t GATE_TRIG = 13;
constexpr uint8_t GATE_ECHO = 14;
constexpr uint8_t SERVO_PIN = 21;

// Detection
constexpr float OCCUPIED_THRESHOLD_CM = 50.0f;  // spot: closer than this = car parked
constexpr float GATE_THRESHOLD_CM = 50.0f;      // gate: closer than this = car waiting
constexpr uint8_t SPOT_DEBOUNCE_COUNT = 3;      // identical readings needed to change a spot
constexpr uint8_t GATE_DEBOUNCE_COUNT = 2;      // gate reacts a bit faster

// Sensor scheduling: one sensor per tick, round-robin over the 4 spots + gate,
// so each sensor is read every 5 x 100 ms = 500 ms and two never fire together.
constexpr uint32_t SENSOR_TICK_MS = 100;
constexpr uint32_t ECHO_TIMEOUT_US = 25000;  // ~4.3 m, beyond the HC-SR04 range
constexpr float NO_ECHO_CM = 400.0f;         // value used when no echo comes back

// Reporting. The heartbeat is also how the ESP32 picks up dashboard commands (they come
// back in the API's reply), so it is kept short. The API marks the device offline after 15 s.
constexpr uint32_t HEARTBEAT_MS = 2000;
constexpr size_t REPORT_MAX_LEN = 512;      // the 4-spot report is ~330 bytes
constexpr uint32_t HTTP_TIMEOUT_MS = 3000;  // give up on a request after 3 s
constexpr uint32_t API_TASK_STACK = 12288;  // enough for HTTPClient + TLS (tunnel fallback)

// Barrier (servo)
constexpr int SERVO_CLOSED_DEG = 0;
constexpr int SERVO_OPEN_DEG = 90;
constexpr int SERVO_STEP_DEG = 3;
constexpr uint32_t SERVO_STEP_MS = 15;              // 90 deg in ~0.45 s
constexpr uint32_t BARRIER_CLOSE_DELAY_MS = 5000;  // close 5 s after the car has passed

}  // namespace cfg
