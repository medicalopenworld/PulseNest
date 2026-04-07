#pragma once
#include "FreeRTOS.h"
inline SemaphoreHandle_t xSemaphoreCreateBinary()  { return nullptr; }
inline SemaphoreHandle_t xSemaphoreCreateMutex()   { return nullptr; }
inline BaseType_t xSemaphoreGive(SemaphoreHandle_t)                        { return pdTRUE; }
inline BaseType_t xSemaphoreGiveFromISR(SemaphoreHandle_t, BaseType_t*)    { return pdTRUE; }
inline BaseType_t xSemaphoreTake(SemaphoreHandle_t, TickType_t)            { return pdTRUE; }
inline void vSemaphoreDelete(SemaphoreHandle_t) {}
