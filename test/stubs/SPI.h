#pragma once
// Minimal SPI stub for native unit tests
#include <stdint.h>
#define MSBFIRST 1
#define SPI_MODE0 0
struct SPISettings { SPISettings(uint32_t, uint8_t, uint8_t) {} };
struct SPIClass {
    void begin(int=-1, int=-1, int=-1, int=-1) {}
    void beginTransaction(SPISettings) {}
    void endTransaction() {}
    uint8_t  transfer(uint8_t)   { return 0; }
    uint32_t transfer32(uint32_t){ return 0; }
};
inline SPIClass SPI;
