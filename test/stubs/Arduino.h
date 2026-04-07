#pragma once
// Minimal Arduino stub for native unit tests
#include <stdint.h>
#include <stddef.h>
#define HIGH 1
#define LOW  0
#define INPUT  0
#define OUTPUT 1
#define RISING 1
#define INPUT_PULLUP 2
#define IRAM_ATTR
template<typename T> T constrain(T val, T lo, T hi) { return val < lo ? lo : (val > hi ? hi : val); }
inline int digitalPinToInterrupt(uint8_t pin) { return (int)pin; }
inline void pinMode(uint8_t, uint8_t) {}
inline void digitalWrite(uint8_t, uint8_t) {}
inline int  digitalRead(uint8_t) { return 0; }
inline void attachInterrupt(uint8_t, void(*)(), int) {}
inline void detachInterrupt(uint8_t) {}
inline unsigned long millis() { return 0; }
inline void delay(unsigned long) {}
