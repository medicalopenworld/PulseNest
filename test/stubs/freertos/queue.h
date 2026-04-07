#pragma once
#include "FreeRTOS.h"
inline QueueHandle_t xQueueCreate(uint32_t, uint32_t)                    { return nullptr; }
inline BaseType_t    xQueueSend(QueueHandle_t, const void*, TickType_t)   { return pdTRUE; }
inline BaseType_t    xQueueReceive(QueueHandle_t, void*, TickType_t)      { return pdFALSE; }
inline void          vQueueDelete(QueueHandle_t) {}
