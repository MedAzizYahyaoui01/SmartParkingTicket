#pragma once

#include <stdint.h>

// Turns noisy boolean readings into a stable state: the state only changes after
// `required` identical readings in a row, so a slider passing by doesn't flicker.
// Plain C++ with no Arduino dependency, so it can be unit-tested on the PC.
class Debouncer {
 public:
  Debouncer(uint8_t required = 3, bool initial = false)
      : required_(required), state_(initial), candidate_(initial), count_(0) {}

  // Feeds one raw reading. Returns true when the stable state has just changed.
  bool update(bool raw) {
    if (raw == state_) {  // agrees with the current state: forget any pending change
      candidate_ = state_;
      count_ = 0;
      return false;
    }
    if (raw != candidate_) {  // a new candidate value: start counting again
      candidate_ = raw;
      count_ = 0;
    }
    if (++count_ >= required_) {
      state_ = raw;
      count_ = 0;
      return true;
    }
    return false;
  }

  bool state() const { return state_; }

 private:
  uint8_t required_;
  bool state_;
  bool candidate_;
  uint8_t count_;
};
