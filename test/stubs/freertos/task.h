#pragma once
#include "FreeRTOS.h"
typedef void (*TaskFunction_t)(void*);
inline BaseType_t xTaskCreate(TaskFunction_t, const char*, uint32_t, void*, UBaseType_t, TaskHandle_t*) { return pdPASS; }
inline BaseType_t xTaskCreatePinnedToCore(TaskFunction_t, const char*, uint32_t, void*, UBaseType_t, TaskHandle_t*, int) { return pdPASS; }
inline void vTaskDelete(TaskHandle_t) {}
inline void vTaskDelay(TickType_t) {}
