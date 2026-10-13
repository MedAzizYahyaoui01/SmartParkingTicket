#pragma once

#include <Arduino.h>
#include <ESP32Servo.h>

// Entry barrier driven by a servo, as a non-blocking state machine:
//
//   CLOSED --requestOpen--> OPENING --(reached 90 deg)--> OPEN
//   OPEN --(gate clear for 5 s, or requestClose)--> CLOSING --(reached 0 deg)--> CLOSED
//   CLOSING --(car appears at the gate, or requestOpen)--> OPENING   (safety: never close on a car)
//
// update() must be called on every loop; it moves the servo a few degrees at a time.
class Barrier {
 public:
  enum class State { CLOSED, OPENING, OPEN, CLOSING };

  void begin(uint8_t servoPin);
  void requestOpen();
  void requestClose();
  void update(uint32_t nowMs, bool carAtGate);

  State state() const { return state_; }
  const char* stateName() const;  // "closed", "opening", "open", "closing" (API format)

 private:
  void setState(State s);

  Servo servo_;
  State state_ = State::CLOSED;
  int angle_ = 0;
  uint32_t lastStepMs_ = 0;
  uint32_t gateClearSinceMs_ = 0;  // when the gate sensor last became clear while OPEN
  bool gateWasClear_ = false;
};
