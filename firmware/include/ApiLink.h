#pragma once

#include <stddef.h>

// Link between the firmware and the API, running in its own FreeRTOS task on core 0.
// Wi-Fi and HTTP calls can take hundreds of milliseconds; doing them in a separate task
// keeps the sensor loop (core 1) on schedule, with no blocking call in loop().
//
//   loop() --submit(json)-->  [report slot, latest only] --> task: POST /sensors/reading
//   loop() <--pollCommand()-- [command queue]            <-- task: barrier_command in the reply
//
// Only the latest report is kept: each report carries the full state, so if a newer one
// is ready before the previous one was sent, the old one is useless. While Wi-Fi or the
// API is down, reports are dropped and the next heartbeat brings the API up to date.
namespace ApiLink {

enum class Command { NONE, OPEN, CLOSE };

void begin();

// Queues a report (JSON) for sending. Never blocks.
void submit(const char* json);

// Next barrier command received from the API, or NONE. Never blocks.
Command pollCommand();

// True while the API runs the gate in "account" mode (only identified, paying users get in):
// the local "free spot -> open" rule must then stay off. Turns false again if the API has
// not answered for API_GATE_TAKEOVER_MS, so a network failure never locks the parking.
bool apiControlsGate();

}  // namespace ApiLink
