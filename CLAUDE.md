# CLAUDE.md — PulseNest (AFE4490)

https://github.com/medicalopenworld/PulseNest

## Este proyecto
Herramienta de test para validar el sistema PPG/SpO2 con el chip AFE4490, dentro del proyecto mayor **IncuNest** (incubadora neonatal open-source de Medical Open World).
El objetivo es verificar la lectura de señal PPG y el cálculo de SpO2 del AFE4490 de forma aislada, antes de integrarlo en el firmware principal de IncuNest.

En el fichero project_info.md está la información del proyecto Incunest.
La librería `incunest_afe4490` vive en su propio repo: https://github.com/medicalopenworld/incunest_afe4490
La spec `incunest_afe4490_spec.md` vive en ese repo (no en PulseNest)
En el fichero conversation_log.md está todo lo que Alex dialoga con Claude
En el fichero `docs/boards.md` está el inventario de TODAS las tarjetas físicas: MAC, revisión, preset de build que le corresponde, cómo identificarlas y los procedimientos de flasheo. **Consultarlo antes de cualquier OTA** y mantenerlo al día cuando aparezca una tarjeta nueva.


## Hardware y entorno
- **MCU:** ESP32-S3 (placas IncuNest V17 y V18; V15 en desuso, V16 muerta)
- **Sensor:** AFE4490 por SPI
- **Framework:** **ESP-IDF v6.0.1 nativo** (sin Arduino, sin PlatformIO) desde 2026-09-15. Instalado en `C:\esp\v6.0.1\esp-idf`.
- **Build:** `.\scripts\build.ps1 V18` (un `build_Vxx/` y un `sdkconfig` por placa a partir de `sdkconfig.defaults` + `sdkconfig.board.Vxx`); `-Ota <ip>` flashea por OTA (cuerpo raw), `-Usb COMxx` por USB. Firmware en `main/pulsenest_main.cpp`; pines por Kconfig (`main/Kconfig.projbuild`).
- **OS:** FreeRTOS (multitarea)
- **Librería AFE4490:** `incunest_afe4490` — repo propio: https://github.com/medicalopenworld/incunest_afe4490 (consumida como componente IDF: `EXTRA_COMPONENT_DIRS` → `lib/incunest_afe4490`, symlink al repo local)

## Especificación de incunest_afe4490
- Ver `incunest_afe4490_spec.md` en https://github.com/medicalopenworld/incunest_afe4490 — leer antes de tocar cualquier cosa relacionada con incunest_afe4490
- La spec y la librería están **versionadas juntas** (misma versión semántica) en el repo de la librería
- **Regla obligatoria:** cualquier modificación de diseño en la librería debe reflejarse inmediatamente en `incunest_afe4490_spec.md`, sin necesidad de que el usuario lo pida explícitamente
- Objetivo: cada versión de la spec debe ser capaz por sí sola de regenerar la librería correspondiente

## Herramientas del proyecto
- **Firmware ESP32-S3:** validación de señal PPG y SpO2 en las placas IncuNest V17/V18
- **`pulsenest_lab.py`:** script Python para visualizar, analizar y capturar las señales PPG (forma parte del proyecto, no es un script auxiliar). Ver `pulsenest_lab_spec.md` antes de modificarlo.

## Log de conversaciones
- Ver `conversation_log.md` — historial de decisiones de diseño tomadas en cada sesión
- **Regla obligatoria:** al final de cada sesión, añadir un bloque al fichero `conversation_log.md` con fecha, preguntas clave y decisiones tomadas. Nunca sobreescribir — siempre añadir al final (incremental).

## Reglas de desarrollo (obligatorias)

1. **Nunca usar `delay()`** — usar `vTaskDelay()` con `pdMS_TO_TICKS()`.
6. **Idioma del código fuente:** todo el código, comentarios, identificadores y textos de interfaz de usuario (botones, labels, tooltips, mensajes de estado, cabeceras de tabla, títulos de ventana) deben estar en **inglés** (sin excepción). Aplica a firmware C++, `pulsenest_lab.py` y cualquier otro fichero del proyecto.
2. **Thread-safe** — proteger recursos compartidos con mutex (`SemaphoreHandle_t`).
3. **Manejo de errores SPI/I2C** — siempre comprobar el resultado de las comunicaciones.
4. **Pines desde `main.h`** — no hardcodear pines, seguir las definiciones del diccionario global.
5. **Dispositivo médico** — la fiabilidad es prioridad 1. Nada de hacks o workarounds frágiles.

## Stack tecnológico
- C++ (ESP-IDF v6 + FreeRTOS; gnu++26, `-Wall -Wextra -Werror`)
- ESP-IDF para configuración de hardware a bajo nivel (logs, Bluetooth)
- FreeRTOS para multitarea (`freertos/semphr.h`)

## Contexto del proyecto padre (IncuNest)
- Repo: https://github.com/medicalopenworld/IncuNest/tree/master/Firmware
- Arquitectura de tareas FreeRTOS: `sensors_Task`, `PID_Task`, `UI_Task`, `Security_Task`, `Comm_Tasks`
- HAL con versiones de placa: V13, V14, V15, V16 (pines en `include/board.h`)
- Depuración mediante flags en `main.h` y macros `logI`, `logE`, `logAlarm`
