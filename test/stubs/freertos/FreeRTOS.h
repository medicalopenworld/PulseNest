#pragma once
// Minimal FreeRTOS stub for native unit tests
#include <stdint.h>
typedef void*    TaskHandle_t;
typedef void*    SemaphoreHandle_t;
typedef void*    QueueHandle_t;
typedef uint32_t TickType_t;
typedef uint32_t UBaseType_t;
typedef int      BaseType_t;
#define pdTRUE       1
#define pdFALSE      0
#define pdPASS       1
#define portMAX_DELAY ((TickType_t)0xFFFFFFFF)
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
#define portYIELD_FROM_ISR(x) ((void)(x))
