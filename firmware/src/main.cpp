// Smart Parking — ESP32 firmware
//
// Reads 4 spot sensors + 1 gate sensor, shows each spot's state on its LEDs,
// drives the entry barrier, and builds the JSON report for the API.
// Fully non-blocking: everything is scheduled with millis(), never delay().
//
// Phase 2: the report is printed on the serial monitor.
// Phase 4: the same report will be POSTed to the API over Wi-Fi.

#include <Arduino.h>
#include <ArduinoJson.h>

#include "Barrier.h"
#include "Debouncer.h"
#include "Ultrasonic.h"
#include "config.h"

namespace {

Debouncer spotOccupied[cfg::SPOT_COUNT];
float spotDistanceCm[cfg::SPOT_COUNT];

Debouncer gateCar;
float gateDistanceCm = cfg::NO_ECHO_CM;

Barrier barrier;

size_t nextSensor = 0;  // 0..SPOT_COUNT-1 = spots, SPOT_COUNT = gate
uint32_t lastSensorTickMs = 0;
uint32_t lastReportMs = 0;
bool reportPending = true;  // send one report right after boot
bool fullWarningShown = false;

size_t freeSpotCount() {
  size_t free = 0;
  for (size_t i = 0; i < cfg::SPOT_COUNT; i++) {
    if (!spotOccupied[i].state()) free++;
  }
  return free;
}

void showSpotLeds(size_t i) {
  const bool occupied = spotOccupied[i].state();
  digitalWrite(cfg::SPOTS[i].ledGreen, occupied ? LOW : HIGH);
  digitalWrite(cfg::SPOTS[i].ledRed, occupied ? HIGH : LOW);
}

// Measures one sensor and updates its debounced state.
void readSensor(size_t index) {
  if (index < cfg::SPOT_COUNT) {
    const cfg::SpotPins& pins = cfg::SPOTS[index];
    spotDistanceCm[index] = measureDistanceCm(pins.trig, pins.echo);
    const bool raw = spotDistanceCm[index] < cfg::OCCUPIED_THRESHOLD_CM;

    if (spotOccupied[index].update(raw)) {
      showSpotLeds(index);  // local feedback first: works even without network
      Serial.printf("[spot] %s -> %s (%.1f cm), %u/%u free\n", pins.id,
                    spotOccupied[index].state() ? "occupied" : "free", spotDistanceCm[index],
                    (unsigned)freeSpotCount(), (unsigned)cfg::SPOT_COUNT);
      reportPending = true;
    }
  } else {
    gateDistanceCm = measureDistanceCm(cfg::GATE_TRIG, cfg::GATE_ECHO);
    const bool raw = gateDistanceCm < cfg::GATE_THRESHOLD_CM;

    if (gateCar.update(raw)) {
      Serial.printf("[gate] car %s (%.1f cm)\n", gateCar.state() ? "detected" : "gone",
                    gateDistanceCm);
      fullWarningShown = false;
      reportPending = true;
    }
  }
}

// Local gate rule: a car is waiting and there is room -> open.
// (From Phase 4 on, a command from the API can also open or close the barrier.)
void applyGateRule() {
  if (!gateCar.state() || barrier.state() != Barrier::State::CLOSED) return;

  if (freeSpotCount() > 0) {
    barrier.requestOpen();
  } else if (!fullWarningShown) {
    Serial.println("[gate] parking full: barrier stays closed");
    fullWarningShown = true;
  }
}

float roundTo1Decimal(float x) { return roundf(x * 10.0f) / 10.0f; }

// Builds the report in the exact format the API expects (docs/contracts/).
void sendReport(const char* reason) {
  JsonDocument doc;
  doc["device_id"] = cfg::DEVICE_ID;

  JsonArray spots = doc["spots"].to<JsonArray>();
  for (size_t i = 0; i < cfg::SPOT_COUNT; i++) {
    JsonObject spot = spots.add<JsonObject>();
    spot["spot_id"] = cfg::SPOTS[i].id;
    spot["distance_cm"] = roundTo1Decimal(spotDistanceCm[i]);
    spot["occupied"] = spotOccupied[i].state();
  }
  doc["gate_car_detected"] = gateCar.state();
  doc["barrier_state"] = barrier.stateName();

  Serial.printf("[report:%s] ", reason);
  serializeJson(doc, Serial);
  Serial.println();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  Serial.println("\n=== Smart Parking ESP32 ===");

  for (size_t i = 0; i < cfg::SPOT_COUNT; i++) {
    const cfg::SpotPins& pins = cfg::SPOTS[i];
    pinMode(pins.trig, OUTPUT);
    pinMode(pins.echo, INPUT);
    pinMode(pins.ledGreen, OUTPUT);
    pinMode(pins.ledRed, OUTPUT);

    spotOccupied[i] = Debouncer(cfg::SPOT_DEBOUNCE_COUNT);
    spotDistanceCm[i] = cfg::NO_ECHO_CM;
    showSpotLeds(i);  // all spots start as free (green)
  }
  pinMode(cfg::GATE_TRIG, OUTPUT);
  pinMode(cfg::GATE_ECHO, INPUT);
  gateCar = Debouncer(cfg::GATE_DEBOUNCE_COUNT);

  barrier.begin(cfg::SERVO_PIN);
  Serial.printf("Ready: %u spots, sensor cycle %lu ms\n", (unsigned)cfg::SPOT_COUNT,
                (unsigned long)(cfg::SENSOR_TICK_MS * (cfg::SPOT_COUNT + 1)));
}

void loop() {
  const uint32_t now = millis();

  // 1. Read the next sensor (round-robin, one per tick)
  if (now - lastSensorTickMs >= cfg::SENSOR_TICK_MS) {
    lastSensorTickMs = now;
    readSensor(nextSensor);
    nextSensor = (nextSensor + 1) % (cfg::SPOT_COUNT + 1);
  }

  // 2. Barrier: local rule, then move the servo a step if needed
  applyGateRule();
  barrier.update(now, gateCar.state());

  // 3. Report: immediately on a change, otherwise a heartbeat every 5 s
  if (reportPending || now - lastReportMs >= cfg::HEARTBEAT_MS) {
    sendReport(reportPending ? "change" : "heartbeat");
    reportPending = false;
    lastReportMs = now;
  }
}
