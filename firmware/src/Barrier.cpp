#include "Barrier.h"

#include "config.h"

void Barrier::begin(uint8_t servoPin) {
  servo_.setPeriodHertz(50);
  servo_.attach(servoPin, 500, 2400);
  angle_ = cfg::SERVO_CLOSED_DEG;
  servo_.write(angle_);
  state_ = State::CLOSED;
}

void Barrier::requestOpen() {
  if (state_ == State::CLOSED || state_ == State::CLOSING) setState(State::OPENING);
}

void Barrier::requestClose() {
  if (state_ == State::OPEN || state_ == State::OPENING) setState(State::CLOSING);
}

void Barrier::update(uint32_t nowMs, bool carAtGate) {
  switch (state_) {
    case State::CLOSED:
      break;  // opening is decided by the controller (local rule or API command)

    case State::OPENING:
      if (nowMs - lastStepMs_ >= cfg::SERVO_STEP_MS) {
        lastStepMs_ = nowMs;
        angle_ = min(angle_ + cfg::SERVO_STEP_DEG, cfg::SERVO_OPEN_DEG);
        servo_.write(angle_);
        if (angle_ >= cfg::SERVO_OPEN_DEG) {
          gateWasClear_ = false;
          setState(State::OPEN);
        }
      }
      break;

    case State::OPEN:
      if (carAtGate) {
        gateWasClear_ = false;  // car still under the barrier: keep it open
      } else if (!gateWasClear_) {
        gateWasClear_ = true;  // car just passed: start the countdown
        gateClearSinceMs_ = nowMs;
      } else if (nowMs - gateClearSinceMs_ >= cfg::BARRIER_CLOSE_DELAY_MS) {
        setState(State::CLOSING);
      }
      break;

    case State::CLOSING:
      if (carAtGate) {  // safety: never come down on a car
        setState(State::OPENING);
        break;
      }
      if (nowMs - lastStepMs_ >= cfg::SERVO_STEP_MS) {
        lastStepMs_ = nowMs;
        angle_ = max(angle_ - cfg::SERVO_STEP_DEG, cfg::SERVO_CLOSED_DEG);
        servo_.write(angle_);
        if (angle_ <= cfg::SERVO_CLOSED_DEG) setState(State::CLOSED);
      }
      break;
  }
}

const char* Barrier::stateName() const {
  switch (state_) {
    case State::CLOSED:
      return "closed";
    case State::OPENING:
      return "opening";
    case State::OPEN:
      return "open";
    case State::CLOSING:
      return "closing";
  }
  return "unknown";
}

void Barrier::setState(State s) {
  if (s == state_) return;
  state_ = s;
  Serial.printf("[barrier] %s (angle %d)\n", stateName(), angle_);
}
