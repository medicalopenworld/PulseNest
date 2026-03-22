# CLAUDE.md — Pulsioximeter Test (AFE4490)

https://github.com/acuesta-mow/mow_afe4490_test

## Este proyecto
Herramienta de test para validar el sistema PPG/SpO2 con el chip AFE4490, dentro del proyecto mayor **IncuNest** (incubadora neonatal open-source de Medical Open World).
El objetivo es verificar la lectura de señal PPG y el cálculo de SpO2 del AFE4490 de forma aislada, antes de integrarlo en el firmware principal de IncuNest.

En el fichero project_info.md está la información del proyecto Incunest.
En el fichero mow_afe4490_spec.md está la información de la nueva librería propia que se comparará con la de protocentral
En el fichero conversation_log.md está todo lo que Alex dialoga con Claude


## Hardware y entorno
- **MCU:** ESP32-S3 (placa in3ator V15)
- **Sensor:** AFE4490 por SPI
- **Framework:** Arduino + PlatformIO
- **platformio.ini:** `platform = espressif32@6.6.0`, `framework = arduino`, `board = esp32-s3-devkitc-1`
- **OS:** FreeRTOS (multitarea)
- **Librería AFE4490:** ProtoCentral AFE4490 PPG and SpO2 boards library

## Arquitectura de librerías y fases
- **Fase 1 (actual):** implementación con `protocentral-afe4490-arduino`
- **Fase 2 (próxima):** se añadirá la librería propia `mow_afe4490`
- Ambas librerías coexistirán simultáneamente para poder **comparar** su comportamiento
- No eliminar ni consolidar una librería sobre la otra — la coexistencia es intencional

## Especificación de mow_afe4490
- Ver `mow_afe4490_spec.md` — leer antes de tocar cualquier cosa relacionada con mow_afe4490
- La spec y la librería están **versionadas juntas** (misma versión semántica)
- **Regla obligatoria:** cualquier modificación de diseño en la librería debe reflejarse inmediatamente en `mow_afe4490_spec.md`, sin necesidad de que el usuario lo pida explícitamente
- Objetivo: cada versión de la spec debe ser capaz por sí sola de regenerar la librería correspondiente

## Herramientas del proyecto
- **Firmware ESP32-S3:** validación de señal PPG y SpO2 en la placa in3ator
- **`ppg_plotter.py`:** script Python para visualizar, analizar y capturar las señales PPG (forma parte del proyecto, no es un script auxiliar)

## Log de conversaciones
- Ver `conversation_log.md` — historial de decisiones de diseño tomadas en cada sesión
- **Regla obligatoria:** al final de cada sesión, añadir un bloque al fichero `conversation_log.md` con fecha, preguntas clave y decisiones tomadas. Nunca sobreescribir — siempre añadir al final (incremental).

## Reglas de desarrollo (obligatorias)

1. **Nunca usar `delay()`** — usar `vTaskDelay()` con `pdMS_TO_TICKS()`.
6. **Idioma del código fuente:** todo el código, comentarios e identificadores deben estar en **inglés** (sin excepción).
2. **Thread-safe** — proteger recursos compartidos con mutex (`SemaphoreHandle_t`).
3. **Manejo de errores SPI/I2C** — siempre comprobar el resultado de las comunicaciones.
4. **Pines desde `main.h`** — no hardcodear pines, seguir las definiciones del diccionario global.
5. **Dispositivo médico** — la fiabilidad es prioridad 1. Nada de hacks o workarounds frágiles.

## Stack tecnológico
- C++ (Arduino + ESP-IDF + FreeRTOS)
- ESP-IDF para configuración de hardware a bajo nivel (logs, Bluetooth)
- FreeRTOS para multitarea (`freertos/semphr.h`)

## Contexto del proyecto padre (IncuNest)
- Repo: https://github.com/medicalopenworld/IncuNest/tree/master/Firmware
- Arquitectura de tareas FreeRTOS: `sensors_Task`, `PID_Task`, `UI_Task`, `Security_Task`, `Comm_Tasks`
- HAL con versiones de placa: V13, V14, V15 (pines en `include/board.h`)
- Depuración mediante flags en `main.h` y macros `logI`, `logE`, `logAlarm`
