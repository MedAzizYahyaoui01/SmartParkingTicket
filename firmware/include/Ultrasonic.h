#pragma once

#include <Arduino.h>

#include "config.h"

// One HC-SR04 measurement in centimetres.
// The 10 us trigger pulse and pulseIn() are short, bounded waits (at most
// ECHO_TIMEOUT_US); only one sensor is measured per loop tick, so the loop stays responsive.
inline float measureDistanceCm(uint8_t trigPin, uint8_t echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long echoUs = pulseIn(echoPin, HIGH, cfg::ECHO_TIMEOUT_US);
  if (echoUs == 0) return cfg::NO_ECHO_CM;  // nothing in range
  return echoUs / 58.0f;                    // sound: ~58 us per cm, round trip
}
