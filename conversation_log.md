# Log de conversaciones — PulseNest (AFE4490)

---

## Sesión 1 — 2026-03-14

### Tema: Configuración de Claude Code y diseño de mow_afe4490

---

**¿Vale project_info.md como CLAUDE.md?**
El contenido era bueno pero el fichero no se llamaba CLAUDE.md (no se carga automáticamente) y estaba orientado a describir en lugar de instruir. Se creó CLAUDE.md nuevo basado en él, con sección específica del proyecto de test y reglas en formato imperativo.

---

**¿Se puede ejecutar Claude Code en una shell de Windows?**
Sí, desde PowerShell, CMD o Windows Terminal. El atajo para saltos de línea en prompts es **Alt+Enter**.

---

**Metodología agent-first: ¿cómo pasar la spec de mow_afe4490?**
Decisión: crear `mow_afe4490_spec.md` en la raíz del proyecto y referenciarlo desde CLAUDE.md. La spec debe ser suficientemente completa para regenerar la librería sin contexto adicional.

---

**¿Hay otras librerías AFE4490 con SpO2/HR además de Protocentral?**
Búsqueda ampliada (Arduino + ESP-IDF + C/C++ embedded). Hallazgos:
- `uutzinger/Arduino_AFE44XX`: driver completo pero módulos SpO2/HR vacíos.
- `qyyMriel/Embedded-System---SpO2-Testor`: usa MAX30100, no AFE4490.
- **Conclusión:** Protocentral es la única referencia funcional con SpO2/HR para AFE4490.

---

**Diseño de mow_afe4490 — Modo de operación**

*¿Gestión de DRDY interna o externa?*
Decisión: **interna**. A diferencia de Protocentral que requiere gestión externa.

*¿Arquitectura: tarea propia (Opción A) o callback (Opción B)?*
Decisión: **Opción A — tarea FreeRTOS propia**.
```
DRDY ISR → semáforo → afe4490_task interna → procesa → cola FreeRTOS
sensors_Task (usuario) → afe.getData()
```

---

**Diseño de mow_afe4490 — Struct de datos pública**

*¿Qué exponer externamente?*
- Internamente: 6 señales del AFE4490 (LED1VAL, LED2VAL, ALED1VAL, ALED2VAL, LED1-ALED1VAL, LED2-ALED2VAL)
- Externamente: solo `ppg` (señal filtrada del canal seleccionado) + spo2, hr, spo2_valid, hr_valid

```cpp
struct AFE4490Data {
    int32_t ppg;
    float   spo2;
    uint8_t hr;
    bool    spo2_valid;
    bool    hr_valid;
};
```

*¿getData() bloqueante o no bloqueante?*
Decisión: **no bloqueante**. `bool getData(AFE4490Data& data)`.

---

**Diseño de mow_afe4490 — Configurabilidad**

Todo configurable en runtime (proyecto de test para comparar soluciones).

```cpp
afe.setPPGChannel(AFE4490Channel::LED1_ALED1);  // canal fuente del ppg
afe.setFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 20.0f);  // filtro pasa-banda
```

---

**Diseño de mow_afe4490 — Inicialización del chip**

*¿begin() + setters o struct de configuración?*
Decisión: **begin() + setters individuales** (más cómodo para experimentar).

*Parámetros configurables (con respaldo en datasheet afe4490-datasheet.pdf):*

| Setter | Default | Notas datasheet |
|--------|---------|-----------------|
| `setSampleRate(hz)` | 500 Hz | PRPCOUNT = 4MHz / PRF, rango 63–5000 Hz |
| `setLED1Current(mA)` | 11.7 mA | código 20/256 × 150mA (Protocentral default) |
| `setLED2Current(mA)` | 11.7 mA | ídem |
| `setLEDRange(mA)` | 150 mA | ⚠️ Protocentral dice 100mA — **datasheet dice 150mA** con TX_REF=0.75V |
| `setTIAGain(gain)` | RF_500K | 000=500kΩ default, opciones: 10K–1MΩ |
| `setTIACF(cf)` | CF_5P | 5pF default, hasta ~205pF |
| `setStage2Gain(gain)` | GAIN_0DB | Protocentral no expone este parámetro |

*Timing registers:* calculados automáticamente por la librería desde `setSampleRate()`. No expuestos al usuario.

---

**Diseño de mow_afe4490 — Filtro pasa-banda**

- Se aplica a: señal del canal seleccionado → publicada como `ppg` y usada para HR
- SpO2 usa un camino separado (LED1-ALED1 y LED2-ALED2 sin filtrar)

*¿Por qué señales ambiente-corregidas para SpO2?*
Obvio: sin corrección de ambiente, cualquier cambio de luz ambiental distorsiona el cálculo.

---

**Diseño de mow_afe4490 — Cola FreeRTOS**

- Tamaño: `#define MOW_AFE4490_QUEUE_SIZE 10` (configurable antes de compilar)
- Cola llena: **descartar dato más antiguo** (conservar siempre la muestra más reciente)

---

**Diseño de mow_afe4490 — Prioridad de tarea interna**

- `#define MOW_AFE4490_TASK_PRIORITY 5` (configurable antes de compilar)

---

**Diseño de mow_afe4490 — Algoritmos SpO2/HR**

*¿Adoptar Protocentral, adaptar, o desde cero?*
Decisión: **desde cero (Opción B)**. Protocentral usa señales incorrectas (sin corrección de ambiente), decimación hardcodeada y lookup table de dudosa precisión.

- **SpO2:** `R = (AC_RED/DC_RED) / (AC_IR/DC_IR)`, `SpO2 = a - b×R` (coeficientes calibrables)
- **HR:** detección de picos sobre PPG filtrado, intervalo RR → `HR = 60 / T_RR`

---

**Resultado de la sesión:**
- `CLAUDE.md` creado y actualizado con reglas de versionado de spec y log de conversaciones
- `mow_afe4490_spec.md` v0.1 generado — spec completa lista para implementación
- `conversation_log.md` creado (este fichero)

**Pendiente para próxima sesión:**
- Revisión de `mow_afe4490_spec.md` por el usuario
- Implementación de la librería

---

## Sesión 2 — 2026-03-15

### Tema: Análisis de registros AFE4490 — fuentes de referencia y valores para mow_afe4490

---

**¿Qué son AFE44x0.c y AFE44x0.h?**
Firmware oficial de TI para el kit de evaluación AFE4490EVM v1.4, escrito para MSP430. El código C no es portable al ESP32, pero contiene los valores de registro autoritativos y las fórmulas de timing de TI.

---

**¿Por qué TI usa PRF=100Hz en el EVM si el datasheet recomienda 500Hz?**
NUMAV no afecta a la frecuencia de salida (siempre es PRF). Lo que hace NUMAV es promediar varias conversiones ADC dentro de la ventana de conversión de cada fase (25% del período). Cada conversión dura 50µs.
- A PRF=100Hz: ventana conversión = 2.5ms → caben hasta ~50 conversiones. EVM usa NUMAV=7 (8 conversiones).
- A PRF=500Hz: ventana = 0.5ms → caben hasta ~10 conversiones.
El EVM usa 100Hz porque tiene más margen para promediar y la herramienta de evaluación no necesita alta resolución temporal. Para SpO2/HR en producción se usa 500Hz.

---

**Análisis comparativo de tres fuentes de referencia**
Se compararon todos los registros del AFE4490 entre:
1. AFE44x0.h con PRF=500Hz (fórmulas del EVM TI trasladadas a 500Hz)
2. Datasheet AFE4490 Tabla 2 (extraído con pdftotext — se instaló poppler via winget)
3. Protocentral src/protocentral_afe44xx.cpp

Hallazgos principales:
- **La fórmula del EVM TI desborda a 500Hz**: ALED1CONVEND = 8000 > PRPCOUNT = 7999. La fórmula fue diseñada para 100Hz y no es válida a 500Hz.
- **Duty cycle**: Datasheet y Protocentral usan 25%; EVM TI usa 20%.
- **Margen de estabilización TIA**: Datasheet=50 counts (12.5µs), EVM TI=80 counts, Protocentral=0 counts.
- **ADC reset**: Datasheet=3 counts (−60dB crosstalk), EVM TI=5 counts, Protocentral=0 counts (riesgo).
- **RF TIA**: EVM TI=1MΩ, Protocentral=500kΩ/250kΩ.
- **Corriente LED**: EVM TI≈3.9mA (TX_REF=0.5V + RANGE_1), Protocentral≈11.7mA (TX_REF=0.75V + RANGE_0).
- **CONTROL1 bit16**: Protocentral activa un bit no documentado (0x010707 vs 0x000107). Origen desconocido.

---

**Decisiones de diseño para mow_afe4490 (registros)**

Timing: seguir Datasheet Tabla 2 exactamente (duty cycle 25%, margen 50 counts, ADC reset 3 counts, CONVST = reset_end + 1).

Analógica:
- RF=500kΩ (TIAGAIN y TIA_AMB_GAIN), ENSEPGAIN=0, Stage2 deshabilitado, CF=5pF.
- LED current: código 20, RANGE_0, TX_REF=0.75V → 11.7mA.
- FLTRCNRSEL=500Hz, AMBDAC=0µA.

Control:
- NUMAV=7 (8 promedios → SNR ×√8, caben a 500Hz).
- SW_RST en init (CONTROL0=0x000008).
- CONTROL1=0x000107 (TIMEREN + NUMAV=7, sin CLKALMPIN).
- Secuencia de init: PDN reset → CONTROL0 → SW_RST → analógica → timing → CONTROL1 (último) → delay 1000ms.

---

**Resultado de la sesión:**
- `mow_afe4490_spec.md` actualizado a v0.2 con sección 9 completa: tablas comparativas de todos los registros con valores mow_afe4490 y justificaciones.
- poppler instalado en el sistema (winget: oschwartz10612.Poppler) para lectura de PDFs.

**NUMAV configurable (sección 8.4.1 del datasheet)**

Decisión: hacer el ADC averaging configurable mediante `setNumAverages(uint8_t num)`.

Fórmula del datasheet (Ecuación 5):
```
NUMAV_max = floor(5000 / PRF) − 1
```
A PRF=500Hz → NUMAV_max=9 → hasta 10 muestras. Límite hardware absoluto: 16 (NUMAV=15).

Comportamiento diseñado:
- `num` = número de muestras (1=sin promedio). Internamente NUMAV = num−1.
- Si num > NUMAV_max: clampear + logE.
- `setSampleRate()` recalcula y clampea NUMAV_max automáticamente.
- Default: num=8 (NUMAV=7).

Reflejado en spec v0.3: nuevo setter en sección 2.3, sección 9.5 nueva, tabla NUMAV_max por PRF.

**Pendiente resuelto en sesión 3:**
- El bit 16 de CONTROL1 que activa Protocentral es `RST_CLK_ON_PD_ALM_PIN_ENABLE` (0x010000), documentado en AFE44x0.h pero no identificado previamente. Protocentral también activa `LED2_CONVERT_LED1_CONVERT` (bits 9–10) para sacar señales de conversión en los pines ALM (útil con osciloscopio). mow_afe4490 no replica esto: usa 0x000107 (TIMEREN + NUMAV=7, sin outputs en ALM).
- Implementación de la librería mow_afe4490 completada — ver sesión 3.

---

## Sesión 3 — 2026-03-15

### Tema: Primera implementación de mow_afe4490 (include/mow_afe4490.h + src/mow_afe4490.cpp)

---

**Archivos creados:**
- `include/mow_afe4490.h` — declaración completa de clase, structs y enumeraciones
- `src/mow_afe4490.cpp` — implementación completa v0.3

---

**Estructura de implementación**

*¿Cómo se evita el conflicto de nombres con protocentral y AFE44x0.h?*
Todas las direcciones de registros se declaran como `constexpr` en un `namespace {}` anónimo en el .cpp. No se definen macros ni constantes en el .h. Así coexisten sin colisiones los tres conjuntos de defines.

---

**Resolución del misterio del bit 16 de CONTROL1**

Al leer AFE44x0.h con más detalle:
- `RST_CLK_ON_PD_ALM_PIN_ENABLE = 0x010000` → Protocentral activa la salida de reloj de reset en el pin PD_ALM.
- Bits 9–10 en el byte 1 del CONTROL1 de Protocentral (0x0600) corresponden a `LED2_CONVERT_LED1_CONVERT` → salida de señales de conversión en pines ALM (útil para debug con osciloscopio).
- Protocentral: 0x010707 = RST_CLK_ON_PD_ALM + LED2_CONVERT_LED1_CONVERT + TIMEREN + NUMAV=7
- mow_afe4490: 0x000107 = TIMEREN + NUMAV=7 (sin salidas de debug, sin RST_CLK)

---

**Decisiones de implementación — SPI**

- Escritura: `_write_reg(addr, data)` — CS low, 1 byte addr + 3 bytes data, CS high.
- Lectura individual: `_read_reg(addr)` — habilita CTRL0_SPI_READ, lee, deshabilita.
- Lectura en ráfaga (en la tarea): habilita SPI_READ una sola vez, lee los 6 registros con `_read_spi_raw()`, deshabilita. Minimiza la sobrecarga de CONTROL0 en el camino crítico.

---

**Decisiones de implementación — Tarea FreeRTOS**

- ISR → `xSemaphoreGiveFromISR` → semáforo binario → `_task_body()`.
- Timeout del semáforo: 100 ms → logW si no llega DRDY (chip parado o desconectado).
- Mutex `_cfg_mutex`: protege SPI durante lectura de 6 registros Y durante escrituras de configuración de los setters.
- Trampolín estático: `static MOW_AFE4490* _g_instance` + `static void IRAM_ATTR _drdy_isr_static()`.

---

**Decisiones de implementación — Filtro**

- Biquad Butterworth 0.5–20 Hz @ 500 Hz: coeficientes hardcodeados (mismos que Protocentral).
- Direct Form II Transposed: `y = B0*x + v1; v1 = B1*x - A1*y + v2; v2 = B2*x - A2*y`.
- Moving average: ring buffer de 8 muestras (simple, no necesita f_low/f_high).
- TODO: cálculo dinámico de coeficientes biquad a partir de sample_rate y frecuencias de corte. Por ahora se emite logW si se piden coeficientes distintos a los hardcodeados.
- `setPPGChannel()` y `setFilter()` resetean el estado del filtro (evita transitorio al cambiar señal).

---

**Decisiones de implementación — SpO2**

- DC: IIR → `dc = 0.99875 * dc + 0.00125 * sample` (τ ≈ 800 samples @ 500 Hz)
- AC²: EMA → `ac2 = 0.002 * (sample − dc)² + 0.998 * ac2` (τ ≈ 500 samples)
- R = (√ac2_red / dc_red) / (√ac2_ir / dc_ir)
- SpO2 = a − b × R (defaults: a=104, b=17, calibrables vía `setSpO2Coefficients()`)
- `spo2_valid = false` durante los primeros 2500 muestras (5 s @ 500 Hz) y si dc_ir < 1000.
- Señales de entrada: `led1_aled1` (IR) y `led2_aled2` (RED), sin filtrar (spec §1.3).

---

**Decisiones de implementación — HR**

- Umbral adaptativo: `threshold = 0.6 × running_max` donde `running_max` decae lentamente (×0.9999 por muestra).
- Detección de flanco ascendente sobre la señal PPG filtrada con periodo de refracción de 150 muestras (300 ms).
- Buffer circular de 5 intervalos RR; HR = (sample_rate × 60) / media_5_intervalos.
- Rango válido: 40–240 BPM.

---

**Resultado de la sesión:**
- `include/mow_afe4490.h` creado — API pública completa según spec v0.3
- `src/mow_afe4490.cpp` creado — implementación completa

**main.cpp actualizado — flag USE_MOW_AFE4490**

Decisión: comparación mediante flag de compilación en lugar de ejecución simultánea de ambas librerías.

*¿Por qué no simultáneo?*
Ambas librerías hablan con el mismo chip físico. Si ambas llaman a su init(), la segunda sobreescribe la configuración de la primera. Ejecución simultánea requeriría sincronización SPI compleja innecesaria para un test.

*Solución adoptada:*
- `// #define USE_MOW_AFE4490` → protocentral (path original sin modificar)
- `#define USE_MOW_AFE4490` → mow_afe4490 (path nuevo)
- El código de protocentral queda idéntico al original, envuelto en `#ifndef USE_MOW_AFE4490`.
- La `Mow_Task` gestiona el PWDN externamente (antes de `mow.begin()`) ya que mow no toma ese pin.
- Salida serie MODE_3 en ambos paths (mismo flag `SERIAL_DOWNSAMPLING_RATIO`).
- Columnas mow por ahora: `sample, ppg, spo2, hr` (menos que protocentral porque `AFE4490Data` no expone canales raw).

**Feedback registrado:**
- Actualizar conversation_log.md y mow_afe4490_spec.md después de cada decisión relevante, sin esperar al final de sesión ni a que el usuario lo pida.

**Pendiente para próxima sesión:**
- Validar carga y arranque en la placa (había problema de carga con el IDE Antigravity al cerrar esta sesión).
- Calcular coeficientes biquad dinámicamente (TODO en setFilter).
- Calibrar coeficientes SpO2 con sensor real.
- Valorar si ampliar `AFE4490Data` con canales raw para equiparar la salida serie con protocentral.

---

## Sesión 4 — 2026-03-16

### Tema: Mejoras al sistema de debug/visualización (main.cpp + ppg_plotter.py)

---

**Análisis previo del protocolo de trama**

Antes de modificar nada se analizaron `main.cpp` y `ppg_plotter.py` conjuntamente. Inconsistencias detectadas:
- HR y SpO2 estaban invertidos en posición entre PATH A (protocentral) y PATH B (mow) — PATH A tenía un bug de visualización.
- PATH B: campos REDFilt/IRFilt (posiciones 11–12) enviaban datos SUB en lugar de datos filtrados (limitación de `AFE4490Data` en ese momento).
- PATH B: timestamp con `micros()` tras `getData()`, no con el timestamp de la ISR.
- Header hardcodeado en consola inconsistente con el mapeo real.

---

**Renombrado de variables y etiquetas**

- `data_counter` → `data_sample_counter` en ppg_plotter.py (3 ocurrencias).
- Etiqueta `Cnt` → `SmpCnt` en headers de consola y cabecera visual (líneas 244 y 311).

---

**Añadido campo LibID al inicio de la trama**

Motivación: identificar inequívocamente qué librería generó cada muestra, especialmente útil en ficheros CSV grabados.

- PATH A (protocentral): envía `P1` (P=Protocentral, 1=versión).
- PATH B (mow): envía `M0` (M=MOW, 0=versión).
- La trama pasa de 13 a 14 campos: `LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt`.
- ppg_plotter.py actualizado: nuevo deque `data_lib_id`, parser requiere 14 campos, todos los headers CSV actualizados.

---

**Renombrado de flag de compilación**

`USE_MOW_AFE4490` → `USE_LIB_MOW_AFE4490` para mayor claridad semántica.

---

**Añadido flag USE_LIB_PROTOCENTRAL_AFE44XX + guard de compilación**

Motivación: con un solo flag (`USE_LIB_MOW_AFE4490`), la ausencia del flag implicaba protocentral de forma implícita. No es escalable si se añaden más librerías.

Solución adoptada:
```cpp
#define USE_LIB_MOW_AFE4490
// #define USE_LIB_PROTOCENTRAL_AFE44XX

#if (defined(USE_LIB_MOW_AFE4490) + defined(USE_LIB_PROTOCENTRAL_AFE44XX)) != 1
  #error "Debe estar definida EXACTAMENTE UNA librería AFE4490: ..."
#endif
```
- Todos los `#ifndef USE_LIB_MOW_AFE4490` / `#else` sustituidos por `#ifdef USE_LIB_PROTOCENTRAL_AFE44XX`.
- Código simétrico entre ambas librerías. Añadir una tercera es trivial.

---

**Terminología: librería vs driver vs API**

Decisión: usar el término **librería** (no driver, no API).

Razonamiento: lo que diferencia a `protocentral_afe44xx` de `mow_afe4490` no es el hardware (ambas hablan con el mismo AFE4490 por SPI) sino los algoritmos de procesado. Eso es territorio de librería. Driver implicaría solo la capa de acceso al hardware.

Comentarios de `main.cpp` actualizados con esta terminología.

---

**Mejoras visuales en ppg_plotter.py**

- Consola más ancha: splitter `[1400, 800]` → `[1800, 900]`, ventana `2200` → `2700px`.
- Valor instantáneo de SpO2 y HR: se actualiza dinámicamente en el título de sus respectivas gráficas (`p_spo2`, `p_hr`) en cada ciclo de refresco.

---

**Resultado de la sesión:**
- `main.cpp` y `ppg_plotter.py` mejorados en robustez, claridad y visualización.
- Protocolo de trama documentado y consistente entre ambas librerías.

**Pendiente:**
- Continuar desarrollo de `mow_afe4490` en sesión paralela (nueva CLI).

---

## Sesión 3 — 2026-03-16

**Preguntas y decisiones:**

- **¿Dónde poner las constantes internas?** — En el namespace anónimo del `.cpp`, al principio, en snake_case. Se descartó crear `mow_afe4490_config.h` (el `.h` es solo interfaz pública). Los `#define` de configuración FreeRTOS (QUEUE_SIZE, TASK_PRIORITY, TASK_STACK) permanecen en el `.h` por ser configurables por el usuario.
- **¿`#define` o `constexpr`?** — `constexpr` en namespace, estilo snake_case (idiomático en C++ moderno). Excepción: registros de hardware `REG_*` mantienen UPPER_CASE por convención embedded.
- **Parámetros temporales dependientes de sample rate** — Identificados y expresados en unidades físicas. `_recalc_rate_params()` los deriva de `_sample_rate_hz` en constructor y en `setSampleRate()`. Algoritmos SpO2 y HR ahora correctos a cualquier PRF.

**Cambios implementados (v0.5):**
- Namespace anónimo reorganizado: constantes de algoritmo al principio en snake_case.
- Constantes temporales en segundos: `spo2_warmup_s=5s`, `dc_iir_tau_s=1.6s`, `ac_ema_tau_s=1.0s`, `hr_refractory_s=0.3s`.
- Nuevos miembros: `_spo2_warmup_samples`, `_hr_refractory_samples`, `_dc_iir_alpha`, `_ac_ema_beta`.
- Nueva función privada `_recalc_rate_params()`.
- `MA_LEN` → `static constexpr int ma_len` en la clase.
- **(v0.6)** Coeficientes biquad dinámicos: `_recalc_biquad()` implementa la transformada bilineal sobre prototipo Butterworth bandpass 2º orden. Coeficientes como miembros `_bq_b0..a2`. `setFilter()` completamente funcional para cualquier fs/f_low/f_high.

**Pendiente:**
- Integración de `mow_afe4490` en `main.cpp` y validación con hardware real.

---

## Sesión 5 — 2026-03-17

### Tema: Corrección del protocolo de trama en main.cpp (PATH A y PATH B)

---

**Bugs corregidos en `main.cpp`:**

- **PATH A (protocentral):** SpO2 y HR estaban invertidos en la trama. `heart_rate` se enviaba en la posición de SpO2 (pos 5) y `spo2` en la de HR (pos 6). Corregido: ahora `spo2, heart_rate`.

- **PATH B (mow):** Todas las columnas raw (pos 7-14) tenían led1/led2 swapeados. En `AFE4490Data`: `led1=IR`, `led2=RED`, pero el código enviaba `led1` en la columna RED y `led2` en la columna IR. Corregido para todas las columnas: RED→`led2`, IR→`led1`, AmbRED→`aled2`, AmbIR→`aled1`, REDSub→`led2_aled2`, IRSub→`led1_aled1`. Columnas REDFilt/IRFilt (pos 13-14) también swapeadas; siguen siendo placeholders (sin datos filtrados reales — pendiente problema 3).

**Decisión explícita — ¿los cambios de main.cpp se reflejan en mow_afe4490_spec.md?**
No. La spec documenta el diseño de la librería. El formato de trama serie es responsabilidad de `main.cpp` y `ppg_plotter.py`, no de la spec.

**Pendiente:**
- Problema 3: exponer `led1_aled1_filtered` y `led2_aled2_filtered` en `AFE4490Data` (requiere segundo estado biquad en la librería).
- Validación con hardware real.

---

## Sesión 6 — 2026-03-18

### Tema: Hot-swap de librerías en runtime + mejoras a ppg_plotter.py

---

**Hot-swap de librerías:**
- `mow_afe4490`: añadido `stop()` (v0.7) — detach ISR, delete tarea interna y objetos FreeRTOS, reset estado. Permite llamar `begin()` de nuevo.
- `main.cpp` reescrito: ambas librerías siempre compiladas, selección en runtime mediante `g_active_lib`. Comandos serie: `'m'` → mow, `'p'` → protocentral. `Cmd_Task` en core 0 gestiona el switch.
- `start_mow()` / `stop_mow()` / `start_protocentral()` / `stop_protocentral()` — funciones simétricas. `'m'` y `'p'` siempre paran todo antes de arrancar la librería pedida (sirven como reset).

**ppg_plotter.py:**
- Botón único `btn_lib_switch` → reemplazado por dos botones independientes (`btn_lib_mow`, `btn_lib_pc`) con estilos activo/inactivo. Preparado para un tercer botón futuro.
- Botones de librería movidos al final del sidebar con etiqueta `LIBRARY` encima.
- Protocolo de trama: prefijo `$` en líneas de datos (`$P1,...` / `$M0,...`). Parser Python exige `$` — cualquier otra línea (logs ESP-IDF, boot messages) se muestra en consola pero no se parsea.
- Headers de consola y `header_label` corregidos: orden `PPG,SpO2,HR` (bug sesión 5) y prefijo `$` reflejado.
- `SERIAL_PRINT_MODE_3` eliminado — el código de serialización queda incondicional.
- `PAUSAR CAPTURA`: añadido drenado del buffer serie durante la pausa para que el ESP32 no se bloquee en `Serial.print()`.
- `WINDOW_SIZE`: reducido a 500 (luego a 250 según ajuste del usuario). `SERIAL_DOWNSAMPLING_RATIO` subido a 20 por el usuario.

**Bug abierto — ESP32 deja de enviar al cambiar de librería:**
- Investigación iniciada pero no resuelta. Siguiente paso: reproducir y leer consola Python buscando `Guru Meditation Error`, `DRDY timeout` o corte silencioso de tramas.

**Pendiente:**
- Filtro PMAF (Periodic Moving Average Filter) para motion artifacts — apuntado en memoria.
- Problema 3: `led1_aled1_filtered` y `led2_aled2_filtered` en `AFE4490Data`.
- Validación con hardware real.

---

### Sesión 7 — 2026-03-18 (continuación)

**Backlog de funcionalidades avanzadas añadido:**

Se registra el siguiente paquete de funcionalidades futuras para `mow_afe4490` (no implementar hasta que el usuario lo pida):

- **HRV**: variabilidad de la frecuencia cardíaca a partir de intervalos RR del PPG.
- **Detección de arritmias**: clasificación de patrones irregulares (taquicardia, bradicardia, FA, extrasístoles).
- **Detector de ritmo respiratorio**: frecuencia respiratoria por modulación de amplitud/baseline del PPG (RSA).
- **Detector de apneas**: ausencia o irregularidad prolongada del patrón respiratorio derivado del PPG.
- **Detector de artefactos**: movimiento del sensor/cuerpo, cambios de luz ambiental u otras perturbaciones. Base para PMAF.
- **Cambios vasculares agudos**: vasoconstricción/vasodilatación, tono simpático, perfusión periférica, indicadores hemodinámicos (PTT, amplitud, área bajo la curva, tiempo de subida).

---

### Sesión 8 — 2026-03-18

**Tema:** Subida del proyecto a GitHub

**Acciones realizadas:**
- Inicializado repositorio git en el directorio del proyecto.
- Actualizado `.gitignore` para excluir: `.claude/` (permisos locales), `compile_commands.json` (5 MB autogenerado), logs de build (`build_log.txt`, `pio_build_log.txt`, `pio_output.txt`), y `src/AFE44x0.c.to_delete`.
- Primer commit con 33 archivos (firmware, headers, librerías, spec, plotter, docs).
- Creado repositorio privado en GitHub: https://github.com/acuesta-mow/mow_afe4490_test
- Cuenta GitHub usada: `acuesta-mow` / `acuesta@medicalopenworld.org`

**Decisiones:**
- Repositorio creado como privado.
- La carpeta `.claude/` se excluye siempre del repo (contiene rutas locales de máquina).

---

**Decisión — Problema 3 descartado:**

`AFE4490Data` es solo observabilidad externa. Los algoritmos SpO2/HR son internos y no usan la struct como entrada — reciben los valores directamente en `_process_sample()`. Por tanto, no hay necesidad de exponer `led1_aled1_filtered` / `led2_aled2_filtered`. Las columnas `IRFilt`/`REDFilt` de la trama (pos 13-14) se mantienen como placeholders hasta que haya una necesidad concreta del plotter.

---

## Sesión 9 — 2026-03-18

### Tema: Refactoring de nomenclatura en main.cpp + regla de idioma en CLAUDE.md

---

**`vTaskDelay(1ms)` añadido a `Protocentral_Task`**

`SPO2_Task` hacía polling activo sin ceder CPU. Añadido `vTaskDelay(pdMS_TO_TICKS(1))` igual que `Mow_Output_Task`. Se eligió 1 ms en lugar de 2 ms (período exacto a 500 Hz) para evitar perder DRDY por jitter de fase del scheduler.

---

**Regla de idioma añadida a CLAUDE.md**

Todo el código fuente, comentarios e identificadores deben estar en inglés (regla 6). Los comentarios en español de las líneas `vTaskDelay` fueron corregidos a inglés.

---

**Renombrados en main.cpp**

| Nombre anterior | Nombre nuevo | Motivo |
|---|---|---|
| `SPO2_Task` | `Protocentral_Task` | Identifica la librería, no la función |
| `Mow_Output_Task` | `Mow_Task` | `_Output` era redundante |
| `afe4490ADCReady` | `protocentral_drdy_isr` | camelCase aislado; DRDY es el término del datasheet |
| `AFE44XX_CS_PIN` / `AFE44XX_PWDN_PIN` / `AFE44XX_ADC_RDY_PIN` | `AFE4490_CS_PIN` / `AFE4490_PWDN_PIN` / `AFE4490_DRDY_PIN` | Pines del hardware concreto, no de la librería |
| `afe44xx` | `protocentral` | Prefijo consistente con el bloque mow |
| `afe44xx_raw_data` | `protocentral_raw_data` | ídem |
| `last_intr_time_us` / `sample_counter` / `afe4490_ADC_ready` / `g_spo2_task` | `protocentral_last_intr_us` / `protocentral_sample_count` / `protocentral_drdy_flag` / `g_protocentral_task` | Simetría con variables de mow |
| `"MOW_OUT"` / `"SPO2"` (etiquetas FreeRTOS) | `"MOW"` / `"PROTOCENTRAL"` | Consistentes con los nuevos nombres de tarea |
| `g_mow_output_task` | `g_mow_task` | Consistente con el renombrado de la tarea |

---

**Refactoring de estructura**

`main.cpp` reorganizado: globals → ISR → task → start → stop por cada librería. `start_mow` / `stop_mow` movidos junto a `Mow_Task`; `start_protocentral` / `stop_protocentral` junto a `Protocentral_Task`.

---

**Decisión — convención de prefijos**

Se valoró aplicar prefijos `protocentral_` / `mow_` a todas las funciones (tareas incluidas). Descartado para las tareas: `Protocentral_Task` / `Mow_Task` ya expresan la distinción visualmente y la distinción tarea/función de control tiene valor. El fichero es suficientemente pequeño para que la convención de prefijo no aporte.

---

## Sesión 10 — 2026-03-21

### Tema: Análisis de cambios sin commitear detectados por revisión de código

*Nota: esta entrada fue reconstruida a partir del diff del código fuente (git diff HEAD), ya que la sesión anterior fue cerrada sin guardar el log.*

---

**Cambios en `mow_afe4490` (v0.7 → sin versión asignada todavía)**

**1. Split del mutex `_cfg_mutex` → `_spi_mutex` + `_state_mutex`**

El mutex único `_cfg_mutex` fue separado en dos con responsabilidades distintas:
- `_spi_mutex`: protege el bus SPI (`_write_reg` / `_read_spi_raw`)
- `_state_mutex`: protege el estado interno de procesamiento (`_ppg_channel`, buffers biquad, acumuladores SpO2/HR)

Consecuencia importante: en `_task_body()`, ahora se libera `_spi_mutex` inmediatamente después de la lectura SPI, y se toma `_state_mutex` por separado antes de `_process_sample()`. Esto elimina el bloqueo innecesario del bus SPI durante el procesado de señal.

Config setters: los que tocan hardware (`setSampleRate`, `setLED*`, `setTIAGain`, etc.) usan `_spi_mutex`; los que solo tocan estado interno (`setPPGChannel`, `setFilter`, `setSpO2Coefficients`) usan `_state_mutex`.

**2. Biquad pre-charge (`_biquad_precharge()`)**

Nuevo método privado que pre-carga el estado del filtro biquad a su valor DC de estado estacionario antes de la primera muestra, eliminando el transitorio inicial. Fórmulas para DF-II transpuesto:
```
y_ss  = x0 * (b0+b1+b2) / (1+a1+a2)   → 0 para bandpass
v1_ss = y_ss - b0*x0
v2_ss = b2*x0 - a2*y_ss
```
Flag `_bq_ppg_needs_precharge` (bool): se activa al hacer reset/cambiar canal/cambiar filtro; se consume en el primer sample.

**3. Renombrado `_hr_*` → `_hr1_*`**

Todos los miembros y métodos del algoritmo HR renombrados con sufijo `_hr1_`. Señala que el diseño contempla un segundo algoritmo (`_hr2`) en el futuro. `_update_hr()` → `_update_hr1()`.

Bug fix menor: `_hr_running_max` antes hacía `fmaxf(..., fabsf(ppg_filtered))`. Ahora es `fmaxf(..., ppg_filtered)` — el max se calcula sobre el valor positivo directo, no su valor absoluto.

**4. Contrato SPI.begin() documentado explícitamente**

Añadido comentario en `begin()` y en la declaración del header aclarando que la librería no llama `SPI.begin()` internamente — debe ser llamado por la aplicación antes de `begin()`. Motivo: SPI es un bus compartido; llamar `SPI.begin()` dentro de la librería podría reinicializar el bus y romper otros dispositivos.

**5. Comentarios de documentación interna añadidos**

- ISR trampoline (`_drdy_isr_static`): documentada la limitación del singleton `_g_instance` y las dos alternativas para soportar dos chips AFE4490 simultáneos.
- Task trampoline (`_task_trampoline`): documentado el patrón trampoline+member como idioma estándar para FreeRTOS.
- Static member definition de `_g_instance`: explicado por qué debe estar en el .cpp.

---

**Cambios en `main.cpp`**

- `protocentral_raw_data` → `protocentral_data` (eliminado sufijo `_raw_` para simetría con naming de mow).
- `SPI.begin()` en `setup()`: ampliado el comentario explicando por qué se llama aquí y no dentro de cada librería.

---

**Cambios en `ppg_plotter.py` (MAYOR — nuevas ventanas de laboratorio)**

**Nuevos algoritmos Python de estimación HR:**

Dos funciones de análisis (lado Python, para experimentar y comparar, no reemplazan el HR del firmware):

- `_estimate_hr_xcorr_v1(seg, fs, max_lag_n, ...)`: cross-correlación entre dos segmentos solapados de la misma señal (`np.correlate` en modo `valid`). Selecciona el PRIMER pico significativo por encima de `min_lag_s` (no el mayor) para evitar bloqueo en armónicos.
- `_estimate_hr_autocorr_v2(seg, fs, max_lag_n, ...)`: autocorrelación verdadera con `scipy.signal.correlate(seg, seg, method='direct')`. Más eficiente en ventanas largas.

Ambas devuelven `HRResult` (namedtuple): `acorr`, `lags_s`, `peak_lag`, `hr_bpm`, `peak_val`, `hr_status`.
`HRStatus` (IntEnum): `VALID`, `OUT_OF_RANGE`, `INVALID`.
Ambas aplican interpolación parabólica sub-muestra al pico detectado.

**Nuevas ventanas de laboratorio (secundarias, abiertas desde botones del sidebar):**

- `HRLabWindow`: ventana principal de análisis HR. 3 columnas (A, B, C) con 3 plots cada una. Columna B: xcorr_v1 sobre PPG raw y PPG filtrado por biquad mow. Columna C: autocorr_v2 sobre los mismos. Incluye `_mow_biquad_coeffs()` (reimplementación Python de los coeficientes biquad de mow_afe4490). Actualización a 5 Hz.
- `SpO2LabWindow`: 3×3 grid (1A-3C), para análisis SpO2. Layout: QSplitter proporciones 1:1:1.
- `HRLab2Window`: 3×3 grid, proporciones 2:1:1. Uso pendiente de definir.

**Nuevos botones sidebar:** `HRLAB`, `SPO2LAB`, `HRLAB2` (toggle checkable). HRLAB abre por defecto al inicio.

---

**Pendientes activos (sin cambios respecto a sesión anterior):**
- Bug hot-swap: ESP32 deja de enviar datos al cambiar de librería — no resuelto.
- Validación con hardware real.
- Cambios sin commitear: los 4 archivos modificados no han sido commiteados aún.

---

## Sesión 11 — 2026-03-21

### Tema: Bug fix `_update_hr1()` — señal no invertida

**Bug:** `_update_hr1()` recibía `filtered` (señal sin invertir, picos hacia abajo). El algoritmo de detección de picos busca cruces hacia arriba, por lo que nunca detectaba nada.

**Fix:** `src/mow_afe4490.cpp` — `_update_hr1(filtered)` → `_update_hr1(-filtered)`.

La inversión ya existía para `_current_data.ppg` (línea `= -(int32_t)filtered`), pero no se había aplicado a la llamada al algoritmo HR. El AFE4490 produce una señal que cae en sístole; invertirla da la polaridad convencional PPG (picos hacia arriba).

**También configurado en esta sesión:**
- Hook automático de guardado de contexto (`PostToolUse` + `Stop asyncRewake`) en `.claude/settings.local.json`.
- Modo `bypassPermissions` activado en el proyecto.

---

## Sesión 12 — 2026-03-21

### Tema: Commit + push de cambios acumulados; ajuste de f_high del filtro biquad

---

**Commit y push realizados**

Commiteados y pusheados los cambios acumulados de sesiones 10–11 (commit `60f68a7`):
- `mow_afe4490`: mutex split, biquad pre-charge, hr1 rename, fix inversión señal `_update_hr1(-filtered)`, documentación SPI.begin() y trampolines
- `main.cpp`: rename `protocentral_raw_data` → `protocentral_data`
- `ppg_plotter.py`: ventanas de laboratorio HRLabWindow / SpO2LabWindow / HRLab2Window + estimadores HR Python

Autenticación gh: resuelto con `gh auth setup-git` (Windows Credential Manager no tenía el token; gh CLI sí).

---

**Observación HR — sesgo sistemático al alza**

Con simulador a 60 BPM, `_update_hr1` devuelve ~64 BPM (sesgo ~4 BPM, variable). No es redondeo.

Causa identificada: el decay del `running_max` (×0.9999/muestra) hace que el umbral baje ligeramente entre ciclos → el cruce de umbral en el siguiente ciclo ocurre antes en la rampa ascendente → intervalo medido más corto → HR sobreestimada.

---

**Prueba: reducir f_high del filtro biquad**

Hipótesis: con f_high = 20 Hz el filtro deja pasar componentes de alta frecuencia que distorsionan la forma de la rampa ascendente y adelantan el cruce de umbral.

Decisión: probar f_high = 8 Hz. Añadido en `start_mow()`:
```cpp
mow.setFilter(AFE4490Filter::BUTTERWORTH, 0.5f, 8.0f);
```

**Resultado:** firmware flasheado con f_high = 8 Hz. Señal visualmente no parecía filtrada a 8 Hz — pendiente de evaluar con más datos.

---

**HR cambiado de `uint8_t` a `float` en `AFE4490Data`**

Motivación: `uint8_t` (0–255) cubría el rango 40–240 BPM pero perdía resolución decimal. Con `float` se conserva la precisión del cálculo interno (`(sample_rate * 60) / avg_interval`).

Cambios:
- `include/mow_afe4490.h`: `uint8_t hr` → `float hr`
- `src/mow_afe4490.cpp`: `(uint8_t)roundf(hr)` → `hr` (asignación directa)

**Pendiente:** compilar, flashear y observar HR con mayor resolución.

**`main.cpp` línea 134 — formato consistente con SpO2**

`data.hr_valid ? (int)data.hr : -1` → `data.hr_valid ? data.hr : -1.0f` para mantener el mismo formato float que SpO2 en línea 132.

**`ppg_plotter.py` — título p_hr con un decimal**

`{int(self.data_hr[-1])} bpm` → `{self.data_hr[-1]:.1f} bpm` para mostrar resolución decimal en el título de la gráfica HR.

**`main.cpp` — exploración de f_high para reducir sesgo HR**

Secuencia de pruebas: 20 Hz (default) → 8 Hz → 4 Hz → 2 Hz. Conclusión: el sesgo no mejora con f_high más bajo — el filtro no es la causa. Revertido a 20 Hz: `setFilter(BUTTERWORTH, 0.5f, 20.0f)`.

**`mow_afe4490.cpp` — eliminadas constantes `ppg_f_low_hz` / `ppg_f_high_hz`**

Solo se usaban para inicializar `_filter_f_low` / `_filter_f_high` en el constructor. Sustituidas por literales directos `0.5f` / `20.0f`. Sin cambio de comportamiento.

---

**Decisión de arquitectura — HR independiente del filtro de visualización PPG**

Los algoritmos SpO2 y HR deben operar sobre los 6 canales raw del AFE4490, independientes del filtro biquad de visualización (`_bq_ppg`). Motivo: cambiar `f_high` para visualización no debe afectar al algoritmo HR (acoplamiento indeseable detectado durante la exploración de f_high).

SpO2 ya operaba sobre canales raw (correcto). HR operaba sobre `filtered` (incorrecto).

**Solución implementada — filtro MA dedicado para HR1:**
- Filtro de visualización PPG (biquad configurable): intacto, no toca HR
- HR1 recibe `raw_ppg` y aplica su propio MA interno de 5 Hz cutoff
- Ventana MA: `_hr1_ma_len = round(fs / (2 × 5.0))` → 50 muestras a 500 Hz
- Se adapta automáticamente si cambia `_sample_rate_hz` (`_recalc_rate_params()`)
- Buffer fijo `_hr1_ma_buf[64]` (soporta hasta 640 Hz @ 5 Hz cutoff)
- Negación aplicada después del MA dentro de `_update_hr1()`, no fuera

**Cambios:**
- `include/mow_afe4490.h`: nuevos miembros `_hr1_ma_buf[64]`, `_hr1_ma_len`, `_hr1_ma_idx`, `_hr1_ma_sum`
- `src/mow_afe4490.cpp` namespace: nueva constante `hr1_ma_cutoff_hz = 5.0f`
- `src/mow_afe4490.cpp` constructor: inicialización de nuevos miembros
- `_recalc_rate_params()`: calcula `_hr1_ma_len` con clamp a [1, 64]
- `_reset_algorithms()`: resetea buffer y estado MA de HR1
- `_process_sample()`: pasa `raw_ppg` a `_update_hr1()` (antes `-filtered`)
- `_update_hr1()`: aplica MA interno + negación antes de detección de picos

**`_process_sample()` — HR fijado a `led1_aled1`**

`_update_hr1(raw_ppg)` → `_update_hr1(led1_aled1)`. HR usa siempre el canal IR ambiente-corregido, igual que SpO2. Desacopla HR del canal de visualización PPG (`_ppg_channel`).

**`_update_hr1()` — firma cambiada a `int32_t led1_aled1`**

`float raw` → `int32_t led1_aled1`. El nombre del parámetro documenta el contrato: solo acepta ese canal. La conversión a float se hace dentro. Actualizado también en la declaración del header.

**`_update_hr1()` — negación movida antes del MA**

La negación es lineal y conmuta con la media, así que el resultado es idéntico. Moverla antes hace que el buffer MA almacene ya la señal con polaridad convencional (picos hacia arriba). `raw = -(float)led1_aled1` antes de entrar al buffer; `ppg_filtered = _hr1_ma_sum / len` sin negación al salir.

**Decisión de diseño — visualización de hr1_ppg**

Opciones descartadas: ESP_LOGD (no graficable, mezcla con protocolo), BLE (demasiado costoso). Decisión: añadir `hr1_ppg` al final de `AFE4490Data` marcado explícitamente como diagnóstico/temporal. Truco elegante: `hr1_ppg` vale 0.0 en la muestra de detección de pico → los impulsos hacia abajo en la gráfica marcan exactamente cuándo dispara el algoritmo.

**`AFE4490Data` — campo diagnóstico `hr1_ppg`**

```cpp
// ── Diagnostic (temporary — may be removed in final release) ──
float hr1_ppg;  // HR1 internal signal (DC-removed + MA); set to 0.0 on detected peak
```

En `_update_hr1()`: `_current_data.hr1_ppg = ppg_filtered` cada muestra; `_current_data.hr1_ppg = 0.0f` en la detección de pico.

**Bug: marcador de pico invisible por diezmado serie**

Con `SERIAL_DOWNSAMPLING_RATIO=20`, la probabilidad de que la muestra del cero sea enviada es 1/20. Solución: mantener `hr1_ppg = 0.0` durante 25 muestras consecutivas tras cada pico (`hr1_peak_marker_samples = 25`). Garantiza al menos 1 muestra con cero en la trama enviada.

Implementación:
- Namespace: `hr1_peak_marker_samples = 10` (SERIAL_DOWNSAMPLING_RATIO = 10, no 20 como se asumió inicialmente)
- Header: nuevo miembro `_hr1_peak_marker_countdown`
- Constructor/reset: inicializado a 0
- `_update_hr1()`: en detección de pico, `_hr1_peak_marker_countdown = 25`; cada muestra: si countdown > 0 → `hr1_ppg = 0.0, countdown--`; si no → `hr1_ppg = ppg_filtered`

**Trama serie — nueva columna `HR1PPG` (pos 15, índice 14)**

Decisión: columna nueva al final (no reutilizar placeholder `IRFilt`). Trama pasa de 14 a 15 campos:
`LibID,SmpCnt,Ts_us,PPG,SpO2,HR,RED,IR,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG`

`main.cpp`: añadido `Serial.print(","); Serial.println(data.hr1_ppg)` al final de la trama MOW.

`ppg_plotter.py`:
- `data_hr1_ppg` deque añadido
- Parser: `len(parts) >= 15`, `p[13]` → `data_hr1_ppg`
- `curve_hr1_ppg`: curva naranja (#FF8800) superpuesta en `p_ppg`
- `curve_hr1_ppg.setData()` en el ciclo de refresco
- Headers de consola y CSV (snapshot y streaming) actualizados con `HR1PPG`

---

**Bug: HR devuelve -1 — causa: DC no eliminado en path HR1**

El MA es pasa-bajo y conserva el DC. Tras negar, la señal queda en un gran valor negativo → `_hr1_running_max` nunca supera 0 → umbral = 0 → sin cruces → `hr_valid = false` → -1. El biquad anterior era pasa-banda y eliminaba el DC, por eso funcionaba.

**Fix: IIR DC removal dedicado para HR1**

Añadido antes del MA en `_update_hr1()`:
```cpp
_hr1_dc = alpha * _hr1_dc + (1-alpha) * s;
raw = -(s - _hr1_dc);  // AC con polaridad convencional
```
- Constante `hr1_dc_tau_s = 1.6f` (igual que SpO2, propia e independiente)
- Alpha calculado en `_recalc_rate_params()`: `_hr1_dc_alpha = expf(-1/(tau*fs))`
- Nuevos miembros: `_hr1_dc` (estado), `_hr1_dc_alpha` (rate-dependent)
- Reset en `_reset_algorithms()`: `_hr1_dc = 0.0f`

**Pendiente:** compilar, flashear y validar HR.

---

## Sesión 7 — 2026-03-21

### Tema: Validación de marcadores de pico HR1 y ajuste visual del plotter

---

**Continuación de sesión anterior: hr1_peak_marker_samples = 10**

Se confirmó que `SERIAL_DOWNSAMPLING_RATIO = 10` (main.cpp línea 1), no 20 como se había asumido. Se redujo `hr1_peak_marker_samples` de 25 a 10 para que el marcador de pico (hr1_ppg=0.0) tenga exactamente la duración mínima necesaria para sobrevivir el diezmado serial.

Firmware compilado y flasheado a COM15. Script ppg_plotter.py relanzado.

---

**ppg_plotter.py: redimensionado relativo de los plots de la fila inferior**

Petición del usuario: hacer el plot "Inverted PPG" más ancho y SpO2/HR más estrechos.

Cambio en `ppg_plotter.py` (líneas ~843-845): `setColumnStretchFactor` de `stats_layout`:
- Antes: columnas 0, 1, 2 con stretch 1, 1, 1 (igual ancho)
- Después: columna 0 (PPG) = 3, columna 1 (SpO2) = 1, columna 2 (HR) = 1

El plot PPG pasa a ocupar ~60% del ancho de la fila, SpO2 y HR ~20% cada uno.

---

**ppg_plotter.py: renombrado título del plot PPG**

Cambiado el título de `p_ppg` de "Inverted PPG" a "PPG".

---

**ppg_plotter.py: ventana temporal reducida a 5 segundos**

`WINDOW_SIZE` reducido de 500 a 250 muestras (5 s a 50 Hz efectivos).

---

**ppg_plotter.py: ventana de p_ppg reducida a 5 s sin afectar al resto**

`WINDOW_SIZE` restaurado a 500 (10 s). Añadida constante `PPG_WINDOW_SIZE = 250` (5 s).
`curve_ppg` y `curve_hr1_ppg` reciben `[-PPG_WINDOW_SIZE:]` en cada refresco.
SpO2 y HR siguen mostrando los 10 s completos.

---

## Sesión 8 — 2026-03-21

### Tema: Implementación de HR2 (autocorrelación) + refactor BiquadFilter struct

---

**Decisión: agrupar miembros biquad en struct BiquadFilter**

Propuesto por el usuario. Se crea `BiquadFilter` (struct privado de la clase) que agrupa:
- `f_low`, `f_high` — frecuencias de corte parametrizables (y futuro adaptativo en runtime)
- `b0, b1, b2, a1, a2` — coeficientes DF-II transpuesto
- `BiquadState state` — estado del filtro
- `bool needs_precharge`

Ventajas: limpieza semántica, patrón reutilizable para HR2/HR3, facilita setters adaptativos.

**Refactor PPG display filter**

Eliminados miembros sueltos: `_filter_f_low`, `_filter_f_high`, `_bq_b0/_bq_b1/_bq_b2/_bq_a1/_bq_a2`, `_bq_ppg`, `_bq_ppg_needs_precharge`.
Sustituidos por: `BiquadFilter _ppg_bpf` (default 0.5–20 Hz).

`_recalc_biquad()` refactorizado a `_recalc_biquad(BiquadFilter& filt)` — calcula coeficientes desde `filt.f_low/f_high` y `_sample_rate_hz`, escribe en `filt.b0...a2`.
`_biquad_step()` y `_biquad_precharge()` toman `BiquadFilter&` en vez de `BiquadState&` separado.

**Implementación HR2**

Algoritmo: `_update_hr2(int32_t led1_aled1)`, corre en paralelo con HR1 en `_process_sample()`.

Pipeline:
1. Biquad bandpass 0.5–5 Hz (BiquadFilter `_hr2_bpf`) a tasa completa (500 Hz) — elimina DC y altas frecuencias, actúa de antialiasing
2. Negar (polaridad convencional, peaks up)
3. Decimación ×10 → 50 Hz efectivos
4. Buffer circular `_hr2_buf[400]` (8 s a 50 Hz, mismo que autocorr_v2 Python)
5. Recomputo cada 25 muestras decimadas (0.5 s)
6. Autocorrelación normalizada: lags [min_lag=11..max_lag=75] a 50 Hz (40–272 BPM)
7. Primer máximo local ≥ 0.5 → interpolación parabólica → HR = 60/lag_s

Constantes (en clase): `hr2_buf_len=400`, `hr2_acorr_max_lag=75`, `hr2_decim_factor=10`, `hr2_update_interval=25`.
Constantes (namespace): `hr2_min_lag_s=0.22f`, `hr2_min_corr=0.5f`.

Nuevo setter público: `setHR2Filter(float f_low_hz, float f_high_hz)` — para adaptación futura en runtime.

Nuevos campos en `AFE4490Data`: `float hr2`, `bool hr2_valid`.

**main.cpp**: añadido HR2 como campo 15 (0-indexed) de la trama serial.

**ppg_plotter.py**: parser ampliado a 16 campos, `data_hr2` deque, `curve_hr2` (rojo #FF4444) en `p_hr`, cabeceras CSV actualizadas.

**Compilación**: SUCCESS. RAM 7.6% (+3.2 KB respecto a sesión anterior, principalmente `_hr2_buf[400]` + `_hr2_seg[400]`).

**Pendiente**: flash y validación con simulador/hardware real.

---

**ppg_plotter.py: p_ppg vuelve a 10 s**

`PPG_WINDOW_SIZE` restaurado a 500 (10 s). El plot PPG vuelve a mostrar la ventana completa.

---

## Sesión 9 — 2026-03-22

### Tema: Refactor _biquad_process + commit HR2

---

**Refactor: _biquad_process()**

Observación del usuario: el bloque precharge+step se repetía en dos sitios (_process_sample y _update_hr2).
Solución: nueva función `_biquad_process(float x, BiquadFilter& filt)` que encapsula el patrón:
- Si `needs_precharge`: llama `_biquad_precharge` y baja el flag
- Siempre llama `_biquad_step` y devuelve el resultado

Los dos call-sites quedan en una sola línea cada uno. Compilación OK.

---

**Refactor: eliminadas _biquad_step() y _biquad_precharge()**

Consolidadas en `_biquad_process()`. El precharge y el step viven ahora en una sola función autocontenida. Eliminadas del header y del .cpp. Compilación OK.

---

## Sesión 10 — 2026-03-22

### Tema: Gestión de TODO y ajuste de parámetros en ppg_plotter.py

---

**Tareas añadidas al TODO.md**

- Pendientes firmware: "HR1 — derivada antes de buscar picos" (aplicar derivada a la señal filtrada antes del detector de picos).
- Pendientes firmware: "Validar algoritmo HR en condiciones adversas: baja perfusión, luz ambiental, artefactos por movimiento".
- Backlog funcionalidades avanzadas: "Elasticidad arterial" — estimación basada en el tiempo de subida (rise time) del pulso PPG como indicador indirecto de rigidez vascular.

---

**ppg_plotter.py — window_n de 8 s a 4 s**

En `HRLabWindow`, el parámetro `window_n` para `autocorr_v2` (columna C) se redujo de `8.0 * fs` a `4.0 * fs`.
A 100 Hz: de 800 muestras a 400 muestras.
`max_lag_n` (2 s / 200 muestras) no se modificó.

---

## Sesión 11 — 2026-03-22

### Tema: Hint de interacción con pyqtgraph en todas las ventanas

---

**Añadido mensaje de ayuda en la statusBar de las 4 ventanas**

Constante `_MOUSE_HINT` definida una sola vez antes de las clases:
`"pyqtgraph: use mouse buttons and wheel on the plots to zoom/pan (right-click for more options)"`

Añadido `self.statusBar().showMessage(_MOUSE_HINT)` en:
- `PPGMonitor`
- `HRLabWindow`
- `HRLab2Window`
- `SpO2LabWindow`

Decisión: usar la statusBar nativa de QMainWindow (parte inferior, no intrusiva) en lugar de un QLabel adicional.

---

## Sesión 12 — 2026-03-22

### Tema: HR con un decimal en títulos de columnas B y C de HRLab

---

**HR con 1 decimal en columnas B y C**

Cambiado `:.0f` → `:.1f` en los 4 títulos de plots afectados:
- Plot 1B (xcorr_v1, raw PPG)
- Plot 2B (xcorr_v1, mow BPF)
- Plot 1C (autocorr_v2, raw PPG)
- Plot 2C (autocorr_v2, mow BPF)

`corr` no se modificó (sigue con 2 decimales).

---

## Sesión 13 — 2026-03-22

### Tema: HR con dos decimales en títulos de columnas B y C de HRLab

---

Cambiado `:.1f` → `:.2f` en los 4 títulos de plots (1B, 2B, 1C, 2C).

---

## Sesión 14 — 2026-03-22

### Tema: HR con dos decimales en ventana principal

---

Cambiado `:.1f` → `:.2f` en `p_hr.setTitle` de `PPGMonitor` (línea 1155).

---

## Sesión 15 — 2026-03-22

### Tema: Mostrar HR2 en el título del plot HR de la ventana principal

---

Añadido `HR2` al título de `p_hr` en `PPGMonitor`. El título muestra ahora:
- HR (amarillo `#FFDD44`) con 2 decimales
- HR2 (rojo `#FF4444`) con 2 decimales

Color rojo elegido para coincidir con el de `curve_hr2` ya existente.

---

## Sesión 16 — 2026-03-22

### Tema: Renombrado hr → hr1 en firmware, script y spec

---

**Motivación:** el campo `hr` era ambiguo (podía interpretarse como "HR genérico del chip"). Como el chip AFE4490 no calcula HR, el valor siempre corresponde al algoritmo 1 propio. Se renombra para simetría con `hr2`.

**Cambios aplicados:**

- `mow_afe4490.h`: `float hr` → `float hr1`, `bool hr_valid` → `bool hr1_valid` en `AFE4490Data`
- `mow_afe4490.cpp`: variable local `hr` → `hr1`, `_current_data.hr` → `_current_data.hr1`, `_current_data.hr_valid` → `_current_data.hr1_valid`
- `main.cpp`: `data.hr_valid ? data.hr` → `data.hr1_valid ? data.hr1`
- `ppg_plotter.py`: `data_hr` → `data_hr1`, `curve_hr` → `curve_hr1`, cabeceras CSV `HR` → `HR1`, título del plot `HR:` → `HR1:`
- `mow_afe4490_spec.md`: struct y referencia a `hr_valid` actualizados

Pendiente: compilar para verificar que no hay errores de build.

---

## Sesión 17 — 2026-03-22

### Tema: Documentación de parámetros en _update_spo2()

---

Añadido comentario antes de `_update_spo2()` en `mow_afe4490.cpp` documentando que `ir_corr` y `red_corr` son señales ambient-corrected (`led1 - aled1` y `led2 - aled2` respectivamente).

---

## Sesión 18 — 2026-03-22

### Tema: Rango del plot SpO2 en ventana principal

---

`p_spo2.setYRange` cambiado de `[80, 100]` a `[50, 100]` en `PPGMonitor`.

---

## Sesión 19 — 2026-03-22

### Tema: Fix plots no actualizados al cambiar a PROTOCENTRAL

---

**Causa:** la trama PROTOCENTRAL (`$P1`) tenía 14 campos pero el parser del script exige `len(parts) >= 16` → las tramas se descartaban silenciosamente.

**Fix:** añadidos dos campos placeholder al final de la trama PROTOCENTRAL en `main.cpp`:
- `0.0` para HR1PPG (no disponible en protocentral)
- `-1.0` para HR2 (no disponible en protocentral)

Así ambas librerías envían 16 campos y el parser los procesa correctamente sin modificar el script.

---

## Sesión 20 — 2026-03-22

### Tema: Calibración SpO2 y optimización de tokens

**Decisiones:**

- `conversation_log.md` no se cargará por defecto en cada sesión para reducir consumo de tokens. Solo se leerá si el usuario lo pide explícitamente. Guardado en memoria.

- Los coeficientes actuales `spo2_a=104, spo2_b=17` no tienen fuente trazable conocida. Se identificaron las fuentes de referencia reales:
  - **Webster 1997:** `SpO2 = 110 - 25·R` (lineal, fuente primaria estándar)
  - **Wukitsch 1988:** `SpO2 = -45.06·R² - 30.34·R + 110.2` (cuadrática, mayor precisión)
  - **NXP AN4327 (2012):** lookup table para sonda Nellcor DS-100 (940 nm)

- La sonda **UpnMed U401-D** usa IR a **905 nm**, no 940 nm. Ninguna de las fórmulas publicadas aplica directamente — error sistemático estimado de 1–3 puntos porcentuales. Requiere calibración empírica comparando contra oxímetro de referencia certificado.

**Pendiente (no implementado aún):**
- Cambiar defaults a Webster (`a=110, b=25`) con fuente documentada
- Documentar en spec y código que los coeficientes asumen 940 nm IR
- Evaluar si añadir soporte para modelo cuadrático (Wukitsch)

---

## Sesión 21 — 2026-03-23

### Tema: Ejemplo mínimo de uso de la librería

**Creado:** `examples/basic/main.cpp`

Ejemplo tutorial para usuarios nuevos de `mow_afe4490`. Documenta los 4 pasos obligatorios:
1. `SPI.begin()` — el usuario gestiona el bus SPI (la librería no lo inicializa)
2. Reset hardware vía PWDN — la librería no gestiona este pin
3. `mow.begin(CS, DRDY)` — configura chip, ISR y tarea interna
4. Tarea FreeRTOS con `getData()` + `vTaskDelay(1ms)` para consumir datos

Incluye bloque de configuración opcional comentado: `setFilter`, `setSpO2Coefficients` (con nota sobre el problema 905 nm de la U401-D), `setLEDCurrent`.

**Cabeceras estandarizadas** en `src/main.cpp` y `examples/basic/main.cpp` para alinearlas con el estilo de `mow_afe4490.h`: `// nombre — descripción`, `// vX.X — plataforma`, `// Spec/referencia`. Todos en v0.7.

**Documentados coeficientes de calibración SpO2** en `mow_afe4490.cpp` y `mow_afe4490.h`:
- Los valores `spo2_a_default` / `spo2_b_default` corresponden a calibración experimental con sonda **UpnMed U401-D(01AS-F)**, tipo Nellcor Non-Oximax. Comentario: "Coefficients a and b derived from experimental calibration with a UpnMed U401-D(01AS-F) probe, type Nellcor Non-Oximax."
- Documentado en `mow_afe4490.cpp` junto a los constexpr (con fórmula `SpO2 = a - b·R`).
- Documentado en `mow_afe4490.h` en el comentario de `setSpO2Coefficients()`.

---

## Sesión 20 (anterior) — 2026-03-22

### Tema: Añadir R ratio a la trama para calibración de SpO2

---

**Motivación:** para calibrar los coeficientes `a` y `b` de `spo2 = a - b·R` se necesita capturar R junto con el SpO2 de referencia del calibrador.

**Cambios en firmware:**
- `mow_afe4490.h`: añadido campo `float spo2_r` al struct `AFE4490Data`
- `mow_afe4490.cpp`: `_current_data.spo2_r = R` en `_update_spo2()` tras calcular R; inicializador del struct actualizado a 15 valores
- `main.cpp` (trama MOW): añadido `data.spo2_r` como campo 17 de la trama
- `main.cpp` (trama PROTOCENTRAL): añadido `-1.0` como placeholder del campo 17

**Cambios en script:**
- Nuevo deque `data_spo2_r`
- Parser actualizado: `len(parts) >= 17`, índice 16 → `data_spo2_r`
- Título del plot SpO2 muestra `R: x.xxxx` en gris
- Cabeceras CSV (snapshot y tiempo real) actualizadas con columna `SpO2_R`

**Spec actualizada:** `spo2_r` añadido al struct en `mow_afe4490_spec.md`.

**Procedimiento de calibración previsto:**
1. Estabilizar sensor en cada nivel del calibrador (mín. 3-4 niveles)
2. Anotar pares `(R_medido, SpO2_ref)`
3. Regresión lineal → coeficientes `a` y `b` óptimos

---

## Sesión 21 — 2026-03-22

### Tema: Rediseño completo de SpO2LabWindow para calibración

---

**Motivación:** preparar una ventana dedicada para calibrar los coeficientes `a` y `b` de `spo2 = a - b·R` usando un calibrador externo y regresión lineal.

**SpO2LocalCalc (nueva clase):**
Replica el algoritmo firmware `_update_spo2()` en Python (mismo IIR DC + EMA AC²).
Constantes: dc_iir_tau_s=1.6, ac_ema_tau_s=1.0, spo2_min_dc=1000, warmup_s=5, a=104, b=17.
Alimentada con REDSub/IRSub muestra a muestra. fs=50 Hz (SPO2_RECEIVED_FS).

**Nuevo SpO2LabWindow — panel izquierdo (4 plots, zoom libre):**
- SpO2 fw (amarillo) + SpO2 local (naranja) + línea ref blanca punteada
- R ratio fw (amarillo) + R local (naranja)
- DC IR (azul) + DC RED (rojo)
- RMS AC IR (azul claro) + RMS AC RED (rojo claro)
- Títulos con valor instantáneo coloreado por curva

**Panel derecho (calibración):**
- Sensor info: Model (pre-relleno "UpnMed U401-D(01AS-F)"), LOT, Part No.
- SpO2 ref spinbox (50-100 %, paso 0.5) + ventana de promedio (1-30 s)
- ADD POINT → promedia R_fw y R_local en la ventana → añade fila a tabla
- Tabla: #, SpO2_ref, R_fw, R_local
- RUN REGRESSION → polyfit → a, b, R² + texto listo para copiar en setSpO2Coefficients()
- CLEAR / EXPORT CSV (con cabecera modelo/LOT/PartNo y parámetros del algoritmo)

**Constantes añadidas:** SPO2_CAL_BUFSIZE=3000, SPO2_RECEIVED_FS=50.0

**Sensor documentado:** UpnMed U401-D(01AS-F) — campo LOT y Part No. pendientes de rellenar en cada sesión de calibración.

---

## Sesión 22 — 2026-03-22

### Tema: SPO2LAB se abre por defecto al arrancar

---

Cambiado `_open_hrlab_default` → `_open_spo2lab_default` en el `showEvent` de `PPGMonitor`.

---

## Sesión 23 — 2026-03-22

### Tema: Mejoras en SpO2LabWindow — Simulator info, tabla más alta, ventana más alta

---

- Añadido grupo "Simulator info" entre "Sensor info" y "Calibration point":
  - Device: (default "MS100")
  - Setting: (default "R-Curve Criticare")
  - Ambos campos se exportan al CSV como # SimDevice y # SimSetting
- Ventana redimensionada: 940 → 1080 px de alto
- Tabla "Calibration points": maxHeight 160 → 260 px

---

## Sesión 24 — 2026-03-23

### Tema: Ajustes de layout en SpO2LabWindow

---

- Ventana: 1080 → 1200 px de alto
- Tabla "Calibration points": maxHeight 260 → 360 px
- Altura de fila de la tabla reducida a 22 px (`setDefaultSectionSize(22)`)

---

## Sesión 25 — 2026-03-23

### Tema: Cambio de valor por defecto de Simulator Setting

---

`_edit_sim_setting` default: "R-Curve Criticare" → "R-Curve Nellcor, 100 bpm"

---

## Sesión 26 — 2026-03-23

### Tema: Nuevos coeficientes de calibración SpO2 + R con 5 decimales en trama

---

**Coeficientes SpO2 actualizados** (primeros valores calibrados con simulador MS100, R-Curve Nellcor 100 bpm):
- `spo2_a_default`: 104.0 → **114.9208**
- `spo2_b_default`: 17.0 → **30.5547**
- Aplicado en: `mow_afe4490.cpp` (firmware) y `SpO2LocalCalc` en `ppg_plotter.py`

**R con 5 decimales en trama serie:**
- `Serial.println(data.spo2_r)` → `Serial.println(data.spo2_r, 5)`

---

## Sesión 27 — 2026-03-23

### Tema: Truncado de SpO2 ligeramente por encima de spo2_max

---

Añadida constante `spo2_clamp_margin = 3.0f` en `mow_afe4490.cpp`.

Lógica de validación actualizada en `_update_spo2()`:
- spo2 ∈ [70, 100] → se publica tal cual
- spo2 ∈ (100, 103] → se trunca a 100.0 con `fminf` y se publica como válido
- spo2 > 103 → se descarta como inválido

Motivación: errores numéricos del algoritmo pueden producir valores ligeramente por encima de 100%, que fisiológicamente son válidos.

---

## Sesión 28 — 2026-03-27

### Tema: Reordenación de campos en AFE4490Data

---

**Pregunta:** ¿Por qué `spo2_valid` aparece después de `hr1` en el struct `AFE4490Data`?

**Causa:** orden histórico de adición de campos, sin razón técnica de fondo.

**Decisión:** reordenar para agrupar cada valor con su flag de validez:
- `spo2` / `spo2_r` / `spo2_valid`
- `hr1` / `hr1_valid`
- `hr2` / `hr2_valid`

**Ficheros modificados:**
- `include/mow_afe4490.h` — struct `AFE4490Data`
- `mow_afe4490_spec.md` — sección 2.1 Data struct

---

## Sesión 29 — 2026-03-31

### Tema: Spec v0.8, roadmap de algoritmos HR, estrategia de test y env:native

---

**HR2 validado con simulador**

HR2 visible en el plotter con valores coherentes con HR1. Marcado como completado en TODO.md.

---

**Spec actualizada a v0.8**

Cambios aplicados a `mow_afe4490_spec.md`:
- §1.1 y §1.3: diagramas de arquitectura actualizados con HR2
- §2.1 struct: añadidos `hr2` / `hr2_valid`
- §2.4 API: añadido `setHR2Filter()`
- §5.2 HR1: documentación completa de la cadena de procesado (DC removal IIR, MA LP, running-max, threshold crossing, 5 intervalos RR, peak marker)
- §5.2 nota: threshold crossing es implementación actual; mejora prevista es detección por derivada (máximo de la derivada = pendiente máxima ascendente)
- §5.3 HR2: nueva sección con pipeline completo y tabla de constantes
- §5.4 Roadmap HR: tabla con HR1–HR4 y estado de implementación
- §8 historial: entrada v0.8

---

**Decisión de naming — algoritmos HR**

Debate sobre si llamar HR1 "peak detection" o "threshold crossing / rising edge detection".

**Decisión:** mantener "peak detection" porque es el objetivo del algoritmo; el threshold crossing es solo el mecanismo actual. HR4 será el "true peak detection" mediante derivada. Cambiar el nombre ahora y luego volver a cambiarlo no tiene sentido.

---

**Roadmap de algoritmos HR**

Añadidos a TODO.md y a spec §5.4:
- HR3: FFT
- HR4: peak detection via derivada (máximo de la derivada = flanco de subida preciso)

---

**Protocentral descartada como referencia de validación**

El usuario considera que la librería protocentral es de baja calidad algorítmica. No se usará como ground truth para comparar con mow_afe4490. Guardado en memoria.

---

**Estrategia de test — decisiones**

Dos tareas de test priorizadas (añadidas a TODO.md):
1. Tests unitarios en PC con PlatformIO `env:native` + Unity
2. Dataset de referencia con simulador MS100 (golden CSV a SpO2/HR conocidos)

La comparación mow vs protocentral descartada como tarea de test (protocentral de baja calidad).

Se empieza por la tarea 1 (sin simulador disponible hoy).

---

**Configuración env:native + primer test**

- `platformio.ini`: añadido `[env:native]` con `platform = native` y `test_framework = unity`
- Creado `test/test_hello/test_hello.cpp`: test de sanidad `1+1==2`
- Resultado: **PASSED** — entorno nativo operativo
- Unity 2.6.1 instalado automáticamente por PlatformIO


---

## Sesión 30 — 2026-03-31

### Tema: Setup de tests unitarios nativos (env:native + Unity) — en progreso

---

**Objetivo:** configurar PlatformIO env:native + Unity para tests unitarios de algoritmos sin ESP32.

**Avances:**

- `platformio.ini`: añadido `[env:native]` con `platform = native`, `test_framework = unity`, `build_flags = -DUNIT_TEST -I test/stubs -I include -I src`, `build_src_filter = +<mow_afe4490.cpp>`
- Creados stubs mínimos en `test/stubs/` para que el código compile en PC:
  - `Arduino.h` (tipos, IRAM_ATTR, GPIO stubs)
  - `SPI.h` (SPIClass stub)
  - `freertos/FreeRTOS.h`, `task.h`, `semphr.h`, `queue.h` (tipos y funciones vacías)
  - `esp_log.h` (macros ESP_LOG* → printf)
- `include/mow_afe4490.h`: añadido bloque `#ifdef UNIT_TEST` al final de la clase que expone `TestBiquadFilter`, `test_recalc_biquad()` y `test_biquad_process()` como public
- Creado `test/test_biquad/test_biquad.cpp` con 5 tests del filtro biquad:
  1. Frecuencia en banda pasa (~1.0 de amplitud)
  2. DC bloqueado (~0 a la salida)
  3. Alta frecuencia atenuada (100 Hz con cutoff 20 Hz)
  4. Filtro HR2 (0.5–5 Hz) atenúa 20 Hz
  5. Salida decae a cero con entrada cero

**Problema encontrado:** PlatformIO native no compila `src/` automáticamente para tests. `mow_afe4490.cpp` no se enlaza → "undefined reference".

**Solución propuesta (pendiente de confirmar):** mover la librería a `lib/mow_afe4490/` (PlatformIO descubre y enlaza automáticamente el contenido de `lib/` en todos los entornos). `src/main.cpp` queda solo en `src/` para el build ESP32.


---

## Sesión 31 — 2026-03-31

### Tema: Tests unitarios nativos — librería a lib/, stubs completos, test_biquad 5/5 PASSED

---

**Reestructuración: librería movida a lib/**

`mow_afe4490.h` y `mow_afe4490.cpp` movidos de `include/` y `src/` a `lib/mow_afe4490/`. PlatformIO descubre y enlaza automáticamente el contenido de `lib/` en todos los entornos (ESP32 y native). `src/main.cpp` queda en `src/` exclusivamente para el build ESP32.

**platformio.ini** simplificado para native:
```ini
[env:native]
platform = native
test_framework = unity
build_flags =
    -DUNIT_TEST
    -I test/stubs
```

---

**Stubs completados**

Añadidos a `test/stubs/Arduino.h`: `INPUT_PULLUP`, `digitalPinToInterrupt`, `constrain`, `IRAM_ATTR`.
Añadido a `test/stubs/freertos/task.h`: `xTaskCreatePinnedToCore`.
Añadido a `test/stubs/freertos/FreeRTOS.h`: `portYIELD_FROM_ISR`.

---

**Bug corregido: inicializador de AFE4490Data**

En `mow_afe4490.cpp` (dos sitios: constructor y `_reset_algorithms()`), el inicializador del struct tenía `spo2_valid` y `hr1` intercambiados:

```cpp
// Antes (incorrecto — narrowing conversion float→bool):
_current_data = {0, 0.0f, 0.0f, 0.0f, false, false, 0.0f, false, ...};
// Después (correcto):
_current_data = {0, 0.0f, 0.0f, false, 0.0f, false, 0.0f, false, ...};
```

El compilador ESP32 no detectaba el error (más permisivo con narrowing); el compilador GCC nativo sí lo rechaza.

---

**test_biquad — 5/5 PASSED**

`test/test_biquad/test_biquad.cpp` con 5 tests del filtro Butterworth bandpass:
1. Frecuencia en banda (5 Hz, 0.5–20 Hz) → amplitud ~1.0 ✓
2. DC bloqueado → salida ~0 ✓
3. Alta frecuencia atenuada (100 Hz, cutoff 20 Hz) → amplitud < 0.25 ✓
4. Filtro HR2 (0.5–5 Hz) atenúa 20 Hz → amplitud < 0.30 ✓
5. Salida decae a cero con entrada cero ✓

Nota: umbrales de atenuación ajustados a la pendiente real de un filtro biquad de 2.º orden (~20 dB/década), no 40 dB/década.


---

## Sesión 32 — 2026-03-31

### Tema: Tests unitarios HR1 — 4/4 PASSED

---

**Accesores de test añadidos al header (bloque UNIT_TEST)**

`lib/mow_afe4490/mow_afe4490.h` — ampliado el bloque `#ifdef UNIT_TEST` con accesores para HR1 y HR2:
- `test_feed_hr1(int32_t)` / `test_hr1()` / `test_hr1_valid()`
- `test_feed_hr2(int32_t)` / `test_hr2()` / `test_hr2_valid()`

---

**test/test_hr1/test_hr1.cpp — 4/4 PASSED**

1. `test_hr1_not_valid_too_soon` — tras 1 s (< 5 intervalos), `hr1_valid = false` ✓
2. `test_hr1_60bpm` — seno 1 Hz → HR1 ≈ 60 BPM ± 5 ✓
3. `test_hr1_120bpm` — seno 2 Hz → HR1 ≈ 120 BPM ± 5 ✓
4. `test_hr1_flat_signal_invalid` — señal DC constante (sin pulsos) → `hr1_valid = false` ✓

Señal de test: seno con DC offset (500000 + 50000 × sin), 6000 muestras a 500 Hz (12 s).


---

## Sesión 33 — 2026-03-31

### Tema: Tests unitarios HR2 — 4/4 PASSED. Suite completa 14/14 PASSED.

---

**test/test_hr2/test_hr2.cpp — 4/4 PASSED**

1. `test_hr2_not_valid_until_buffer_full` — antes de 2000 muestras raw (mitad del buffer), `hr2_valid = false` ✓
2. `test_hr2_60bpm` — seno 1 Hz → HR2 ≈ 60 BPM ± 5 ✓
3. `test_hr2_120bpm` — seno 2 Hz → HR2 ≈ 120 BPM ± 5 ✓
4. `test_hr2_flat_signal_invalid` — señal DC constante → `hr2_valid = false` ✓

Señal de test: 4000 + 1000 muestras raw (buffer completo + margen).

---

**Suite completa: 14/14 PASSED en 8 segundos**

| Grupo       | Tests | Estado |
|-------------|-------|--------|
| test_biquad | 5     | PASSED |
| test_hello  | 1     | PASSED |
| test_hr1    | 4     | PASSED |
| test_hr2    | 4     | PASSED |

Comando: `pio test -e native`

---

**Estado tarea de test**

Tarea 1 (tests unitarios env:native) completada para biquad, HR1 y HR2.
Pendiente: tests de SpO2 (si se decide abordar).


---

## Sesión 34 — 2026-03-31

### Tema: Tests unitarios SpO2 — 6/6 PASSED. Suite completa 20/20 PASSED.

---

**Accesor de test añadido al header**

`lib/mow_afe4490/mow_afe4490.h` — bloque UNIT_TEST ampliado con:
- `test_feed_spo2(ir_corr, red_corr)` / `test_spo2()` / `test_spo2_r()` / `test_spo2_valid()`

---

**test/test_spo2/test_spo2.cpp — 6/6 PASSED**

Señal de test: senos duales IR+RED con DC=100000, frecuencia 1 Hz, amplitudes elegidas para producir R exacto.
Derivación: R = a_red/a_ir (los factores √2 del RMS se cancelan).

1. `test_spo2_not_valid_during_warmup` — tras 1000 muestras (2 s < warmup 5 s), `spo2_valid = false` ✓
2. `test_spo2_no_finger_invalid` — DC=500 < spo2_min_dc=1000 → `spo2_valid = false` ✓
3. `test_spo2_98_percent` — a_ir=10000, a_red=5538 → R≈0.554 → SpO2 ≈ 98% ± 2 ✓
4. `test_spo2_90_percent` — a_ir=10000, a_red=8156 → R≈0.816 → SpO2 ≈ 90% ± 2 ✓
5. `test_spo2_clamp_above_100` — a_red=4500 → R≈0.45 → SpO2_raw≈101.2 → clamped a 100.0 y válido ✓
6. `test_spo2_too_high_invalid` — a_red=3000 → R≈0.30 → SpO2_raw≈105.8 > 103 → inválido ✓

---

**Suite completa: 20/20 PASSED en 10 segundos**

| Grupo       | Tests |
|-------------|-------|
| test_biquad | 5     |
| test_hello  | 1     |
| test_hr1    | 4     |
| test_hr2    | 4     |
| test_spo2   | 6     |

Tarea 1 de test (tests unitarios env:native) completada.


---

## Sesión 35 — 2026-03-31

### Tema: Rango HR extendido a 30–250 BPM — spec v0.9

---

**Cambios en código fuente**

`lib/mow_afe4490/mow_afe4490.cpp`:
- `hr_min_bpm`: 40.0 → **30.0** BPM
- `hr_max_bpm`: 240.0 → **250.0** BPM
- `hr_refractory_s`: 0.300 → **0.200** s — motivo: 0.3 s bloqueaba pulsos >200 BPM; 0.2 s permite hasta ~300 BPM

`lib/mow_afe4490/mow_afe4490.h`:
- `hr2_acorr_max_lag`: 75 → **100** samples — motivo: 75 samples a 50 Hz = 1.5 s → 40 BPM mínimo; 100 samples = 2.0 s → 30 BPM mínimo

**Spec actualizada a v0.9**

`mow_afe4490_spec.md` — §5.2, §5.3 y §8 (historial) actualizados con los nuevos valores.

**Tests: 20/20 PASSED** tras los cambios.


---

## Sesión 36 — 2026-03-31

### Tema: Dataset golden MS100 — diseño, downsampling y prueba a 500 Hz

---

**Bug HR1/HR2 a 30 BPM**
Detectado con simulador MS100: HR1 y HR2 no funcionan correctamente a 30 BPM. Añadido a TODO. Pendiente investigar causa.

**build_src_filter en env:native**
Añadido `build_src_filter = -<*>` al env native para excluir `src/` (main.cpp, protocentral) del build nativo. Solo se compila `lib/mow_afe4490/`.

**Diseño del dataset golden**

Contexto neonatal (IncuNest): HR normal 100–180 BPM, bradicardia severa desde 60 BPM.

Matriz reducida (no completa — los puntos centrales aportan poco):
- SpO2: 100%, 98%, 95%, 92%, 88%, 85%
- HR: 40, 60, 100, 150, 180, 220, 240 BPM
- 42 combinaciones × 20 s ≈ 14 minutos

Parámetros del AFE4490 pendiente de documentar junto al dataset (pregunta aplazada).

**Uso del dataset golden**
Validación de integración (no regresión continua): cuando se modifica un algoritmo importante, se recaptura o se corre el CSV golden por un replay offline. No para cada cambio pequeño — para eso ya existen los tests unitarios.

**Opción B elegida: replay nativo (C++)**
Para el replay offline se usará `env:native` — un programa C++ que lee CSV de entrada, pasa las muestras por `mow_afe4490` real, y escribe CSV de salida. Ventaja: siempre valida el algoritmo exacto del firmware.

**Problema detectado: downsampling**
`SERIAL_DOWNSAMPLING_RATIO 10` → el CSV solo tiene 50 Hz (1 de cada 10 muestras). Insuficiente para replay a 500 Hz. Para el dataset golden hay que capturar a ratio 1 (500 Hz completo).

**Prueba con SERIAL_DOWNSAMPLING_RATIO = 1**
`src/main.cpp` cambiado a ratio 1, flasheado y plotter lanzado. Pendiente observar comportamiento del plotter a 500 Hz.


---

## Sesión 37 — 2026-03-31

### Tema: Subida de baud rate a 921600 para captura del dataset golden a 500 Hz

---

**Motivación**

Para el replay nativo (opción B) se necesita capturar las muestras RAW a 500 Hz. A 115200 bps solo caben ~100 tramas/s (trama ~120 chars). La solución es subir el baud rate.

Alternativa descartada: replay a 50 Hz con `setSampleRate(50)` — rechazada porque cambiar la frecuencia de muestreo altera el comportamiento de los algoritmos.

**Cambios aplicados**

- `src/main.cpp`: `Serial.begin(115200)` → `Serial.begin(921600)`
- `src/main.cpp`: `SERIAL_DOWNSAMPLING_RATIO 10` → `SERIAL_DOWNSAMPLING_RATIO 1`
- `platformio.ini`: `monitor_speed = 115200` → `monitor_speed = 921600`
- `ppg_plotter.py`: `BAUD = 115200` → `BAUD = 921600`

**Estado**

Firmware flasheado y plotter lanzado. Pendiente observar si el plotter puede gestionar 500 tramas/s a 921600 bps.



---

## Sesión 38 — 2026-03-31

### Tema: Control de decimación en ppg_plotter.py

---

**Problema**

A 921600 bps con SERIAL_DOWNSAMPLING_RATIO=1, el ESP32 envía 500 tramas/s. El plotter no era capaz de renderizar a esa frecuencia: los plots se refrescaban cada varios segundos.

**Solución implementada**

Añadido control de decimación en la ventana principal del plotter:

- Sidebar: nueva sección "DECIMACIÓN" con un `QSpinBox` ("1 de cada N tramas"), rango 1–500, valor por defecto 10.
- `update_data()`: el contador `_decim_counter` se incrementa en cada trama `$`-prefijada. Solo 1 de cada N tramas se procesa para consola y gráficas.
- **File save (GUARDAR DATOS)** siempre guarda a tasa completa (500 Hz), independientemente del factor de decimación. Esto es esencial para la captura del dataset golden a 500 Hz.

**Comportamiento resultante**

- Factor 10 (defecto): consola y plots a ~50 Hz. Fichero CSV a 500 Hz.
- Factor 1: todo a 500 Hz (sin decimación).
- El factor es ajustable en caliente (sin reiniciar), cambiándolo con el spinbox.


---

## Sesión 39 — 2026-03-31

### Tema: Botón GUARDAR RAW (500 Hz) en ppg_plotter.py

---

**Motivación**

Se necesitaban dos modos de guardado independientes:
- **GUARDAR DATOS** → guarda las tramas decimadas (lo que se ve en consola y plots, a ~50 Hz con decim=10)
- **GUARDAR RAW (500 Hz)** → guarda todas las tramas antes del diezmado, a la tasa completa del ESP32

**Cambios aplicados**

- `__init__`: nuevos campos `is_saving_raw`, `save_file_raw`, `auto_save_raw_timer`
- Sidebar: nuevo botón "GUARDAR RAW (500 Hz)" debajo de "GUARDAR DATOS"
- `update_data()`: el `save_file_raw.write` se ejecuta **antes** del check de decimación (tasa plena); el `save_file.write` se ejecuta **después** (solo tramas no diezmadas)
- `toggle_save_raw()`: abre/cierra `ppg_data_raw_<timestamp>.csv`; en modo pausado devuelve error (no hay tramas entrando)
- `auto_stop_save_raw()`: Auto-Stop de 1000 s idéntico al del botón normal
- `closeEvent()`: cierra también `save_file_raw` si estaba abierto

**Nombres de fichero generados**

- GUARDAR DATOS (decimado): `ppg_data_stream_<timestamp>.csv`
- GUARDAR RAW (500 Hz): `ppg_data_raw_<timestamp>.csv`

---

## Sesión 40 — 2026-03-31

### Tema: Thread dedicado para lectura serie en ppg_plotter.py

---

**Problema detectado**

Al capturar a 500 Hz (SERIAL_DOWNSAMPLING_RATIO=1, 921600 baud) se perdían tramas. El `QTimer` de 20 ms disparaba `update_data()` en el hilo de la UI, y si el renderizado tardaba, el buffer serie se llenaba antes de que se leyera.

**Solución implementada: producer/consumer con `threading` + `queue.Queue`**

- Nuevo thread daemon `_serial_reader()`: solo hace `ser.readline()` + `queue.put()`, sin UI, sin decimación, sin ficheros. Al estar desacoplado de la UI, el buffer hardware nunca se queda sin drenar.
- `update_data()` (QTimer 20 ms) drena la cola con `get_nowait()` en vez de leer directamente del puerto serie.
- Flag `_new_data`: los plots solo se actualizan si al menos un frame fue parseado correctamente en ese tick.
- Modo pausa: drena la cola (antes drenaba el buffer HW) para evitar acumulación de RAM.
- `closeEvent()`: llama `_reader_stop.set()` + `_reader_thread.join(timeout=1.0)` antes de cerrar el puerto.

**Cambios en `ppg_plotter.py`**

- Imports: añadidos `import threading`, `import queue`
- Tras `serial.Serial(...)`: crea `_serial_queue`, `_reader_stop`, arranca `_reader_thread`
- Nuevo método `_serial_reader()`
- `update_data()`: bloque paused y bucle principal reescritos para usar la cola
- `closeEvent()`: parada ordenada del thread

**Nota:** el GIL de Python no bloquea la I/O de pyserial — el thread lector libera el GIL durante `readline()`, por lo que no compite con la UI.

---

## Sesión 2026-04-02

### Tema: Flash + arranque del plotter; bug de indentación en ppg_plotter.py

---

**Flujo ejecutado:** kill Python → `pio run` → `pio run -t upload --upload-port COM15` → `start pythonw ppg_plotter.py`
Build y upload de `in3ator_V15` exitosos (10.9% Flash, 7.6% RAM). El entorno `native` falla por no tener src (esperado, es el entorno de tests unitarios).

---

**Bug corregido en ppg_plotter.py (línea 1594):**
`_new_data = False` tenía indentación incorrecta dentro del bloque `try:`, causando `IndentationError: unindent does not match any outer indentation level`. El script no arrancaba silenciosamente al usar `pythonw`. Corregida la indentación al nivel correcto del `if hasattr(...)` siguiente.

---

## Sesión 2026-04-02 (continuación)

### Tema: Reducción de trama serie a 3 campos — diagnóstico de pérdida de tramas

---

**Problema detectado:** usando PuTTY directamente sobre COM15 (921600 baud), el PC no recibía todas las tramas. Sospecha: la trama era demasiado larga y saturaba el puerto serie a 500 Hz.

**Decisión:** reducir ambas tramas ($P1 y $M0) a solo los tres primeros campos: prefijo, contador de muestra y timestamp.

**Cambio en `src/main.cpp`:**
- Trama `$P1`: de 17 campos a 3 → `$P1,cnt,ts,ppg`
- Trama `$M0`: de 17 campos a 3 → `$M0,cnt,ts,ppg`
- Build: SUCCESS (10.9% Flash, 7.6% RAM)
- Upload pendiente: PuTTY ocupaba COM15 al intentar flashear

**Revertido:** tras flashear y verificar con PuTTY, se deshizo el cambio — ambas tramas ($P1 y $M0) restauradas a los 17 campos originales.

---

## Sesión 2026-04-02 (continuación 2)

### Tema: Dos modos de trama serie para mow_afe4490

---

**Motivación:** con tramas cortas (3 campos) no se pierden muestras en PuTTY. Para captura de calibración/test se necesitan los 6 valores raw del AFE4490 sin perder tramas.

**Decisión de diseño:**
- `$M0` renombrado a `$M1` — trama completa (17 campos), modo por defecto al arrancar
- Nueva trama `$M2` — 7 campos: `$M2,cnt,led2,led1,aled2,aled1,led2_aled2,led1_aled1`
- Comando serie `'1'` → activa `$M1` (solo si lib activa es mow_afe4490)
- Comando serie `'2'` → activa `$M2` (solo si lib activa es mow_afe4490)
- Al cambiar de librería (`'m'`/`'p'`) → reset a `$M1`

**Implementación en `src/main.cpp`:**
- Añadido `enum class MowFrameMode { FULL, RAW }` y variable `g_mow_frame_mode`
- `Mow_Task`: bifurcación según `g_mow_frame_mode` para emitir `$M1` o `$M2`
- `Cmd_Task`: comandos `'1'` y `'2'` con confirmación por Serial; reset en `'m'` y `'p'`
- Build y flash realizados con éxito

---

## Sesión 2026-04-02 (continuación 3)

### Tema: Panel de log de estado en ppg_plotter.py

---

**Cambio en `ppg_plotter.py`:** sustituido el widget `QLabel` (`self.status_bar`) por un `QTextEdit` de solo lectura (`self.log_panel`) que actúa como log acumulativo.

- Altura fija: 130px (~5 líneas visibles), fondo oscuro `#1A1A2E`, fuente monospace 13px
- `set_status()` ya no sobreescribe — añade una línea con timestamp `[HH:MM:SS]`, icono (✔/⚠/✖/●) y color según tipo (success/warning/error/info)
- Auto-scroll al final en cada nueva línea
- `datetime.datetime.now()` usado correctamente (módulo importado como `import datetime`)

---

## Sesión 2026-04-02 (continuación 4)

### Tema: Control de frame mode ($M1/$M2) en ppg_plotter.py

---

**Cambios en `ppg_plotter.py`:**

- Nueva sección "FRAME MODE" en sidebar con botones `$M1 FULL` y `$M2 RAW`
  - Botón activo en azul (`#44AAFF`), inactivo en gris; deshabilitados si lib activa es PROTOCENTRAL
  - `_send_frame_cmd(mode)`: envía `'1'`/`'2'` al ESP32, actualiza `self.frame_mode`, refresca UI
  - `_update_frame_button()`: sincroniza estilos según `active_lib` y `frame_mode`
  - `_update_lib_button()` llama a `_update_frame_button()` si los botones ya existen

- Al recibir confirmación `#` del ESP32 al cambiar de librería: `frame_mode` se resetea a `"M1"` automáticamente
- Mensajes `# Frame mode: ...` del ESP32 se muestran en el log de estado

- Parser extendido para trama `$M2` (8 partes: prefijo + 7 campos):
  - `$M2,cnt,led2(RED),led1(IR),aled2(AmbRED),aled1(AmbIR),led2_aled2(REDSub),led1_aled1(IRSub)`
  - Campos no disponibles en M2 se rellenan con `0.0` / `-1.0` para no romper las gráficas

---

## Sesión 2026-04-02 (continuación 5)

### Tema: Ajuste visual del log_panel

---

- `log_panel`: altura aumentada 130 → 180px, fuente 13 → 16px

---

## Sesión 2026-04-02 (continuación 6)

### Tema: Curvas por defecto al arrancar

---

- `check_red_sub` y `check_ir_sub` arrancaban en `False` → cambiados a `True`
- Al iniciar el script, las gráficas `RED (clean)` e `IR (clean)` ya están visibles por defecto
- `RED (filt)` e `IR (filt)` cambiadas a `False` — ocultas por defecto

---

## Sesión 2026-04-02 (continuación 7)

### Tema: Rizado en señales ambient — corrección de temporización ALED

---

**Diagnóstico:** las señales `aled1`/`aled2` mostraban rizado sincronizado con la señal PPG. Causa: `ALED2STC`/`ALED1STC` arrancaban solo 50 counts (12.5 µs) después del apagado del LED — insuficiente para que el LED se extinga completamente antes de muestrear el ambient.

**Decisión:** añadir `ambient_margin = 200` counts (50 µs) separado de `tia_margin` (que es para el encendido), y aplicarlo a `ALED2STC` y `ALED1STC`.

**Cambios en `lib/mow_afe4490/mow_afe4490.cpp`:**
- Nueva constante `ambient_margin = 200` counts (50 µs)
- `ALED2STC`: 50 → 200 (t5)
- `ALED1STC`: 2*q+50 → 2*q+200 (t11)
- Ventana ambient se acorta 150 counts (37.5 µs) por el lado inicial; sigue siendo ~450 µs

**`mow_afe4490_spec.md` actualizado:** tabla de registros de timing corregida para ALED2STC y ALED1STC.

---

## Sesión 2026-04-02 (continuación 8)

### Tema: Rizado persistent en ambient — subida de ambient_margin a 400 counts

---

**Observación:** con `ambient_margin = 200` (50 µs) el rizado en `aled1`/`aled2` persistía con amplitud ~1500 counts pk-pk, sincronizado con la señal LED. Hipótesis: crosstalk óptico/eléctrico (no timing).

**Acción:** subido `ambient_margin` a 400 counts (100 µs) para confirmar o descartar la causa de timing. Si el rizado no varía → es crosstalk → siguiente paso: cancelación software.

**Resultado con 400 counts:** rizado bajó de ~1500 a ~750 counts pk-pk. Parecía timing.
**Resultado con 600 counts:** rizado volvió a 1500 counts — la bajada anterior probablemente fue variación de condiciones, no timing.
**Conclusión definitiva:** el rizado en ambient es crosstalk óptico/eléctrico, no timing.

**Caracterización del crosstalk:**
- Señal RED pk-pk: ~30.000 counts → k_RED = 1500/30000 = **5%**
- Señal IR pk-pk: ~15.000 counts → k_IR = 1500/15000 = **10%**
- Relevante para SpO2 → pendiente cancelación software

**Revertido a 200 counts (50 µs):** mayor margin no aporta nada y acorta la ventana ambient.
- `lib/mow_afe4490/mow_afe4490.cpp`: `ambient_margin` → 200
- `mow_afe4490_spec.md`: ALED2STC → 200, ALED1STC → 4200

---

## Sesión 2026-04-04

### Tema: Documentación NUMAV, parámetros AFE4490, tareas pendientes

---

**Parámetros AFE4490 actuales (por defecto):**
- LED RED/IR: 11,7 mA, rango 150 mA
- TIA: RF_500K (500 kΩ), CF_5P (5 pF), stage2 = 0 dB
- Sample rate: 500 Hz, NUMAV: 8 (registro = 7)

**Aclaración NUMAV:** campo de 8 bits en CONTROL1, máximo registro = 15 (16 averages). A 500 Hz el límite real es 10 averages (ventana conversión ~500 µs ÷ 50 µs/conversión), NUMAV registro máximo = 9. Valor actual (8) dentro del límite con margen.

**Mejora documentación `mow_afe4490.cpp` línea 224:** comentario reescrito siguiendo el formato propuesto por el usuario — referencia explícita a PRP/4, ejemplo a 500 Hz (max_averages=10, NUMAV=9), y límite hardware NUMAV≤15.

**Tareas pendientes actualizadas:**
1. Validación SpO2 con simulador MS100 *(en curso)*
2. Cancelación software crosstalk ambient (k_RED≈5%, k_IR≈10%)
3. Detección de asístole y otros eventos
4. Eliminar filtro moving average si no se usa
5. Tests unitarios
6. Integración en IncuNest
7. Detección de luz ambiental excesiva (sensor mal colocado) — umbral sobre ALED1/ALED2


---

## Sesión 2026-04-05

### Tema: Análisis de trazas $M2, refactor MowFrameMode

---

**Análisis de trazas $M2 — intervalos temporales:**
- Formato $M2: `$M2, SmpCnt, RED, IR, AmbRED, AmbIR, REDSub, IRSub` (sin Ts_us)
- El segundo campo de la consola (`Df_us`) es el delta de tiempo en µs entre tramas consecutivas medido en el PC
- Saltos de SmpCnt consistentes de 10: causados por la decimación de display del script (`spin_decim.setValue(10)` por defecto) — el firmware con `SERIAL_DOWNSAMPLING_RATIO=1` envía todas las muestras, pero la consola Qt muestra solo 1 de cada 10
- Gaps irregulares (59, 21) sí son drops reales del firmware o del buffer serie
- Patrón de llegada en pares + silencio de ~40-50 ms: comportamiento normal del QTimer drenando el buffer en ráfagas

**Refactor `MowFrameMode` en `main.cpp`:**
- Renombrado `MowFrameMode::FULL` → `MowFrameMode::M1` y `MowFrameMode::RAW` → `MowFrameMode::M2`
- Motivación: los nombres semánticos FULL/RAW son una capa de indirección innecesaria; M1/M2 corresponden directamente al identificador de protocolo y son más extensibles (futuro M3)
- Todos los usos actualizados: enum, variable global, `Cmd_Task`, `Mow_Task`

### Tema: Check temporal resta ambiente (CHK_AMB_SUB)

**Hipótesis a verificar:** `led1_aled1` y `led2_aled2` (valores restados por hardware del AFE4490) son exactamente iguales a `led1 - aled1` y `led2 - aled2` calculados por software a partir de los registros individuales.

**Implementación:** bloque `#ifdef CHK_AMB_SUB` en `main.cpp`, antes de `Mow_Task`:
- Función `chk_amb_sub()` acumula estadísticas por muestra: conteo total, mismatches, máxima diferencia en IR y RED
- Reporta una línea `# CHK n=... mis=... max_d_ir=... max_d_red=...` cada 500 muestras (~1 s)
- Para eliminar: comentar `#define CHK_AMB_SUB` y recompilar

**Motivación:** la resta hardware ocurre en el dominio analógico (antes del ADC), por lo que el resultado puede diferir de la resta digital de los registros individuales. Si `mis` es siempre 0 y `max_d` es 0, los valores son idénticos y `led1_aled1`/`led2_aled2` son redundantes con la resta software.

### Tema: Resultado CHK_AMB_SUB y coste de campos redundantes en M2

**Resultado del check:** `led1_aled1` y `led2_aled2` son siempre idénticos bit a bit a `led1 - aled1` y `led2 - aled2`. La resta en el AFE4490 se hace en dominio digital (no analógico). TI los incluye por conveniencia SPI (leer 2 registros en vez de 4 cuando solo se necesita la señal corregida).

**Coste identificado:** incluir REDSub/IRSub en M2 añade ~15 chars/trama → ~75 kbps extra a 500 Hz. Eliminarlos de M2 permitiría bajar de 921600 a 230400 baud (el script puede calcularlos como RED-AmbRED / IR-AmbIR). Pendiente decidir si se hace el cambio.

**CHK_AMB_SUB desactivado:** `#define CHK_AMB_SUB` comentado en `main.cpp` línea 137. El bloque de código queda en el fichero por si se necesita en el futuro.

---

## Sesión 2026-04-06

### Tema: Revisión de algoritmos HR y diseño de HR3 (FFT)

---

**Revisión de algoritmos HR implementados:**

- **HR1** (línea 783 `mow_afe4490.cpp`): IIR DC removal (tau=1.6s) → MA low-pass 5 Hz → detección de cruce de umbral en flanco ascendente (0.6 × running_max) + refractario 300 ms → media de 5 intervalos RR
- **HR2** (línea 854): biquad BPF 0.5–5 Hz → decimación ×10 → buffer circular 400 muestras → autocorrelación normalizada cada 0.5 s → primer máximo local ≥ 0.5 + interpolación parabólica

**Observación sobre HR1 — no es detección de pico sino cruce de umbral:**

El disparo de HR1 ocurre cuando la señal cruza `0.6 × running_max` en el flanco de subida, no en el máximo real de la onda PPG. Consecuencia: el timing del disparo depende de la amplitud (perfusión variable → jitter sistemático en el intervalo RR medido). Un verdadero pico requeriría detectar el cruce por cero descendente de la derivada (`d/dt(PPG) = 0` con `d²/dt² < 0`). Pendiente en TODO.md, no se implementa en esta sesión.

**Nuevo algoritmo HR3 — diseño preliminar (pendiente decisiones):**

Algoritmo basado en FFT. Parámetros propuestos:
- Señal de entrada: `led1_aled1` (igual que HR1/HR2)
- Decimación ÷10 → 50 Hz (igual que HR2)
- Buffer: 512 muestras decimadas = 10.24 s → resolución ≈ 0.098 Hz ≈ 5.9 BPM
- Ventana: Hann
- Update: cada 0.5 s, buffer circular (ventana deslizante)
- Búsqueda de pico dominante en [0.5, 3.5 Hz] = [30, 210 BPM] + interpolación parabólica sub-bin

**Decisiones pendientes para HR3:**
1. Librería FFT: `arduinoFFT` vs `ESP-DSP` (Espressif, optimizada para ESP32-S3)
2. Tamaño de buffer: 512 (5.9 BPM res.) vs 256 (11.7 BPM res., menor RAM)
3. ¿Prototipo Python primero (como se hizo con HR2/autocorr_v2) antes de portar al firmware?

---

## Sesión 2026-04-06

### Tema: Baudios, headers CSV y tarea pendiente de precisión temporal

---

**¿Tener baudios altos tiene inconvenientes?**
No en este contexto. La conexión es USB-CDC (no RS232 físico); el baud rate 921600 es virtual y no afecta a la velocidad real del cable USB. Solo sería relevante con adaptadores UART físicos de baja calidad o cables largos. Conclusión: no hace falta bajar de 921600.

---

**Bug corregido — headers CSV erróneos en `ppg_plotter.py`**

*Problema 1:* los botones GUARDAR DATOS y GUARDAR RAW siempre escribían el header de M1, aunque `frame_mode` fuera M2.

*Problema 2:* el header de M1/P1 tenía `PPG,HR1,SpO2` pero la trama firmware tiene `PPG,SpO2,HR1` (campos intercambiados).

**Corrección (líneas 1569 y 1604):** header elegido en función de `self.frame_mode` al abrir el fichero:
- M2: `Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub`
- M1/P1: `Timestamp_PC,Diff_us_PC,LibID,ESP32_Sample_Cnt,ESP32_Timestamp_us,PPG,SpO2,HR1,Red,Infrared,AmbRED,AmbIR,REDSub,IRSub,REDFilt,IRFilt,HR1PPG,HR2,SpO2_R`

El snap (paused) no se modificó — es internamente consistente (escribe campo a campo desde los arrays).

Limitación conocida: si se cambia de M1 a M2 mientras se graba, el header queda desfasado.

---

**Nueva tarea añadida a TODO.md (backlog):**
- Comprobar precisión temporal del muestreo (500 Hz) por si afecta a las medidas HR (jitter/deriva del timer).


---

## Sesión 2026-04-06 (continuación)

### Tema: Diagnóstico de tramas cortadas — checksum NMEA + diagnóstico TX

---

**Análisis del CSV `ppg_data_raw_20260405_003154.csv`:**
- 5 tramas malformadas confirmadas (campos 6-14 en lugar de 10): truncadas en el campo IR (led1) y una fusionada (dos tramas en un solo readline).
- Tras cada trama malformada, gap de 260–440 frames consecutivos.
- El Diff_us_PC tras el gap es ~300µs → los frames llegaban al PC pero no se guardaban/procesaban.
- Causa raíz probable: bytes descartados por el stack USB-CDC cuando el buffer TX del ESP32 se satura; readline() con timeout=0.1s devuelve trama parcial.

**Cambios en `main.cpp`:**
- Nueva función helper `frame_xor_chk()` — XOR NMEA de bytes entre '$' y '*'.
- Contador `mow_tx_dropped` — frames intentados con TX buffer < 30 bytes libres.
- **M1, M2, P1:** refactorizados de múltiples `Serial.print()` a un único `snprintf` + `Serial.print(buf)` → envío atómico (elimina corte entre prints).
- Checksum `*XX\r\n` añadido al final de cada trama (estilo NMEA).
- `# STAT n=... tx_dropped=...` cada 5000 muestras (~10 s a 500 Hz).
- Primera versión tenía umbral tx_dropped=200 (siempre disparaba con buffer de 256 B) → corregido a 30.

**Cambios en `ppg_plotter.py`:**
- Verificación checksum NMEA antes de procesar cualquier trama '$'.
- Tramas con checksum incorrecto → `# BAD CHK (got XX exp YY): ...` en consola + descartadas.
- `*XX` eliminado de `line` antes de crear `csv_line` → CSVs sin checksum.
- Reordenado flujo `update_data()`: check '$' y checksum ANTES de crear csv_line.

**Resultado con primer firmware:**
- BAD CHK detectados correctamente (bytes faltando mid-frame, no solo truncamiento al final).
- `tx_dropped=30000` para n=30000 → umbral incorrecto (corregido a 30).
- Ejemplo BAD CHK revelador: `$M1,27679,571,...` — Ts_us debería ser ~57173338 pero llegó truncado a 571 → bytes descartados dentro de la trama.
- Pendiente: confirmar tx_dropped con umbral 30 en la siguiente sesión.


---

## Sesión 2026-04-06 (continuación 2)

### Tema: Parámetro --save-chk para diagnóstico autónomo de tramas

---

**Motivación:** necesidad de que Claude pueda analizar directamente los CSVs de diagnóstico sin intervención manual del usuario.

**Cambios en `ppg_plotter.py`:**
- `PPGMonitor.__init__(save_chk=False)` — nuevo parámetro.
- `--save-chk` como argumento de línea de comandos (argparse en `__main__`).
- Cuando activo: abre automáticamente `ppg_chk_<timestamp>.csv` con header `Timestamp_PC,Diff_us_PC,CHK_OK,RawFrame`.
- Escribe TODAS las tramas '$' incluyendo el `*XX` (antes de stripping), con `CHK_OK=1` (válida) o `CHK_OK=0` (checksum fallido).
- Frames sin checksum (firmware antiguo) también se guardan con `CHK_OK=1`.
- Fichero line-buffered (`buffering=1`) — no se pierden datos si el script se cierra.
- `closeEvent()` cierra el fichero correctamente.

**Pendiente:** analizar el fichero `ppg_chk_*.csv` generado para confirmar patrón de BAD CHK y correlacionar con SmpCnt gaps.


---

## Sesión 2026-04-06 (continuación 3)

### Tema: Auto-cierre del fichero CHK para análisis autónomo por Claude

---

**Motivación:** que Claude pueda lanzar el script, esperar N segundos, y analizar el fichero sin depender del usuario.

**Cambios en `ppg_plotter.py`:**
- `PPGMonitor.__init__(save_chk_duration=15)` — nuevo parámetro.
- `--save-chk-duration N` como argumento de línea de comandos (default 15s).
- `_auto_close_chk()`: cierra el fichero CHK, imprime `[save-chk] DONE: <filename>` por stdout y llama a `QApplication.quit()`.
- QTimer singleShot activa `_auto_close_chk` tras N segundos si `save_chk=True` y `save_chk_duration > 0`.

**Flujo de uso autónomo:**
```
python ppg_plotter.py --save-chk --save-chk-duration 20
→ script corre 20s, cierra fichero, sale
→ Claude lee stdout para obtener el nombre del fichero
→ Claude lee y analiza ppg_chk_*.csv directamente
```

**Pendiente:** verificar que el script se cierra correctamente y analizar el contenido del primer fichero CHK generado.


---

## Sesión 2026-04-06 (continuación 4)

### Tema: Análisis del fichero ppg_chk — diagnóstico de corrupción USB-CDC

---

**Fix segfault en _auto_close_chk:** `QApplication.quit()` directo desde callback de timer causa segfault durante cleanup Qt. Corregido a `QtCore.QTimer.singleShot(0, QApplication.instance().quit)` (quit diferido al siguiente ciclo del event loop).

**Análisis de ppg_chk_20260406_231914.csv (20 segundos, 3218 tramas):**
- BAD CHK: 51/3218 = 1.58% de tramas corruptas
- Tramas sin checksum: 35 (posiblemente de inicio de sesión o firmware antiguo)

**Tipos de corrupción identificados:**
1. Truncación mid-field: trama cortada en mitad de un campo numérico
2. Fusión de 2 tramas: `...-$M1,...` — el `\n` entre tramas se perdió
3. Dígitos concatenados: `96.56102` en lugar de `96.56,102` — la coma fue eliminada
4. Byte corrupto: `$M8` en lugar de `$M1` — bit flip 0x31→0x38, no es solo eliminación
5. SmpCnt/Ts_us truncados a 1-2 dígitos

**Conclusión:** el `snprintf` + `Serial.print()` atómico NO eliminó el problema. La corrupción ocurre en el stack USB-CDC del ESP32, no entre llamadas a print(). El caso `$M8` (bit flip) confirma que es corrupción de datos, no solo truncamiento.

**Hipótesis:** contención entre `Mow_Task` (prioridad 3, core 1) y el driver USB-CDC del ESP32. Posibles vías de investigación: aumentar stack de Mow_Task (4096→8192), ajustar prioridad, o usar UART física en lugar de USB-CDC.

**Pendiente:** decidir si investigar la corrupción USB-CDC o aceptarla como conocida (el checksum ya la filtra).


---

## Sesión 2026-04-06 (continuación 5)

### Tema: Investigación corrupción USB-CDC — stack y core affinity

---

**Hipótesis:** corrupción de bytes (incluido bit flip $M1→$M8) causada por contención entre Mow_Task y el driver USB-CDC del ESP32-S3, que corre en core 1.

**Cambios en `main.cpp`:**
- `Mow_Task`: stack 4096 → 8192 bytes (el buf[256] + snprintf + llamadas USB pueden agotar el stack anterior).
- `Mow_Task`: core 1 → core 0 (separa la tarea de transmisión serie del driver USB-CDC que usa core 1 en ESP32-S3).

**Test en curso:** `python ppg_plotter.py --save-chk --save-chk-duration 20` para comparar tasa de BAD CHK con el firmware anterior (baseline: 1.58%).

**Pendiente:** analizar resultado del test y decidir siguiente paso.


---

## Sesión 2026-04-06 (continuación 6)

### Tema: Opción B — Serial.setTxBufferSize(1024)

---

**Resultado del test anterior (core 0 + stack 8192):** 1.402% BAD CHK — sin mejora significativa respecto al baseline 1.58%. La corrupción es estructural en el driver USB-CDC.

**Cambio en `main.cpp`:**
- `Serial.setTxBufferSize(1024)` antes de `Serial.begin(921600)` — buffer TX de ~256 a 1024 bytes.

**Opinión:** puede reducir frecuencia de saturación pero no eliminará bit flips. Si baja de 1.5% a <0.3% → mejora útil. Si se mantiene en ~1.5% → confirma race condition en driver, no saturación de buffer.

**Test en curso:** save-chk 20s para medir nueva tasa.
**Pendiente:** analizar resultado y decidir si se acepta la tasa residual o se investiga opción D (UART física).

---

## Sesión 2026-04-06 (continuación 7)

### Tema: Algoritmos HR existentes, revisión HR1, diseño e implementación prototipo HR3 (FFT)

---

**Revisión de algoritmos HR implementados:**

- **HR1** (`_update_hr1`, línea 783 `mow_afe4490.cpp`): IIR DC removal (tau=1.6s) → MA low-pass 5 Hz → detección de cruce de umbral en flanco ascendente (0.6 × running_max) + refractario 300 ms → media de 5 intervalos RR. Salida: `hr1`, `hr1_valid`, `hr1_ppg`.
- **HR2** (`_update_hr2`, línea 854): biquad BPF 0.5–5 Hz → decimación ×10 → buffer circular 400 muestras → autocorrelación normalizada cada 0.5 s → primer máximo local ≥ 0.5 + interpolación parabólica. Salida: `hr2`, `hr2_valid`.

**Observación sobre HR1 — cruce de umbral, no pico real:**
HR1 no detecta el máximo de la onda PPG sino el cruce por `0.6 × running_max` en el flanco ascendente. El timing del disparo depende de la amplitud → jitter sistemático en RR cuando la perfusión cambia. Un pico real requeriría `d/dt(PPG) = 0` con `d²/dt² < 0` (cruce por cero descendente de la derivada). Pendiente en TODO.md, no implementado en esta sesión.

**HR3 (FFT) — decisiones de diseño:**
- Señal entrada: `led1_aled1` (= IRSub en trama M1)
- Filtro pre-FFT: biquad LP 10 Hz dedicado (opción B, independiente de HR2). Preserva armónicos PPG hasta ~10 Hz; la FFT selecciona el rango internamente. No decima: la señal llega al script a 50 Hz (SPO2_RECEIVED_FS).
- Buffer: 512 muestras @ 50 Hz = 10.24 s → resolución frecuencial ≈ 0.098 Hz ≈ 5.9 BPM
- Ventana: Hann
- Update: cada 0.5 s (25 muestras nuevas → 95% solapamiento). Parámetro configurable.
- Búsqueda: pico dominante en [0.5, 3.5 Hz] = [30, 210 BPM] + interpolación parabólica sub-bin
- Librería firmware: ESP-DSP (Espressif, optimizada para ESP32-S3)
- Tarea pendiente: analizar carga computacional de HR1 + HR2 + HR3 en ESP32-S3

**Aclaración "Update cada 0.5 s":** FFT se computa sobre las 512 muestras del buffer completo (ventana deslizante). El intervalo de 0.5 s es con qué frecuencia se recalcula, no el tamaño de la ventana.

**Prototipo Python implementado (`ppg_plotter.py`):**
- Clase `HRFFTCalc` añadida (top-level junto a `SpO2LocalCalc`)
  - `update(led1_aled1, fs)` → `(hr_bpm, hr_valid)`
  - Pipeline: butter LP 10 Hz (scipy) → buffer circular 512 → `np.roll` → Hann → `np.fft.rfft` → `signal.find_peaks` en banda HR → interpolación parabólica (misma fórmula que `_estimate_hr_autocorr_v2`)
- `data_hr3` deque + `hr3_calc = HRFFTCalc()` en `PPGMonitor`
- `curve_hr3` en `p_hr` (cyan `#00CCFF`, 1.5px)
- Loop M1: `hr3_calc.update(p[10], SPO2_RECEIVED_FS)` (p[10]=IRSub=led1_aled1); M2: append -1.0
- Título `p_hr` actualizado: HR1 (amarillo) + HR2 (rojo) + HR3 (cyan)

---

## Sesión 2026-04-07

### Tema: HR3LabWindow — ventana de diagnóstico FFT; tarea fiabilidad HR

---

**`HRFFTCalc` — nuevos atributos diagnósticos:**
- `last_spectrum`: espectro FFT normalizado al máximo de la banda HR (0–1)
- `last_freqs`: eje de frecuencias (Hz)
- `last_peak_freq`: frecuencia del pico detectado (Hz, tras interpolación parabólica)
- `last_peak_power_ratio`: fracción de potencia en banda HR concentrada en el pico (0–1); métrica de fiabilidad provisional de HR3
- `last_filtered_buf`: 512 muestras LP-filtradas ordenadas (antes de ventana Hann)
Inicializados en `__init__` y `_recalc_params`; actualizados en `update()` en cada ciclo FFT.

**`HR3LabWindow` — reemplaza `HRLab2Window` (era placeholder 3×3):**
- Botón: "HRLAB2" → "HR3LAB"
- Layout: splitter horizontal (izquierda ancho / derecha 2 plots apilados) + barra de info inferior
- **Plot FFT** (izquierda): espectro normalizado, banda [0.5–3.5 Hz] sombreada, línea cyan sólida en pico, líneas discontinuas en 2× y 3× (armónicos para verificar fundamental)
- **Plot señal filtrada** (derecha arriba, verde claro): últimas 512 muestras LP-filtradas que entran al FFT
- **Plot comparativa HR** (derecha abajo): HR1 amarillo + HR2 rojo + HR3 cyan sobre mismo eje temporal
- **Barra inferior**: parámetros del algoritmo (LP, BUF, ventana, update, banda) + diagnóstico en tiempo real (freq_res BPM/bin, peak Hz/BPM, power_ratio %, buf fill %)
- `update_plots(data_hr1, data_hr2, data_hr3, calc)` llamado desde loop principal

**TODO.md actualizado:**
- `HRLab2Window` marcado `[x]` como completado → `HR3LabWindow`
- Nueva tarea: **Fiabilidad (confidence) de HR1/HR2/HR3** — valor porcentual por algoritmo:
  - HR1: CV inverso de los 5 intervalos RR
  - HR2: `peak_val` autocorrelación (ya disponible, 0–1)
  - HR3: `peak_power_ratio` (ya disponible en `HRFFTCalc`)

**Ventana por defecto al arrancar:** cambiado `_open_spo2lab_default` → `_open_hrlab2_default` en `showEvent` de `PPGMonitor`. Ahora HR3LAB se abre automáticamente en lugar de SPO2LAB.

**Botón "PAUSE MAIN WINDOW":**
- Renombrado de "PAUSAR GRÁFICAS" → "PAUSE MAIN WINDOW" / "RESUME MAIN WINDOW"
- La pausa ahora congela también la consola de tramas (además de las gráficas): `console.appendPlainText` condicionado a `not is_plot_paused`
- PAUSE MAIN WINDOW congela también HR3LAB (la llamada a `update_plots` está dentro del mismo bloque `not is_plot_paused`)

**Renombrado hrlab2 → hr3lab:**
- Todas las referencias `hrlab2` renombradas a `hr3lab` en `ppg_plotter.py`: `btn_hr3lab`, `hr3lab_window`, `toggle_hr3lab`, `_open_hr3lab_default`

**PAUSE MAIN WINDOW — scope acotado a ventana principal:**
- Las llamadas `update_plots` de sub-ventanas (HRLAB, SPO2LAB, HR3LAB) movidas fuera del bloque `not is_plot_paused` a un bloque `if _new_data:` independiente
- Resultado: PAUSE MAIN WINDOW congela solo plots + consola de la ventana principal; HR3LAB, SPO2LAB y HRLAB siguen actualizándose

**Fix kill script — wmic + pythonw:**
- `taskkill /F` no funciona desde bash (convierte `/F` en ruta `F:/`); `Stop-Process -Name python` tampoco porque el proceso es `pythonw.exe`
- Solución definitiva: `wmic process where "name='pythonw.exe'" delete`
- Lanzamiento con `pythonw.exe` en lugar de `python.exe` para evitar la ventana de consola negra

**Fix HR3LAB — batch console update:**
- Causa del problema: `appendPlainText` + operaciones de scroll se ejecutaban para CADA muestra dentro del `while True:` de drenado de cola (50 veces/s). Qt es lento con estas operaciones, ralentizando el loop completo y haciendo que `hr3_calc.update()` recibiera muestras de forma irregular.
- Solución: acumular líneas en `_console_lines` durante el while loop (sin ninguna operación Qt) y hacer un único `appendPlainText('\n'.join(...))` + scroll al salir del loop.
- Resultado: el inner loop es puro Python/numpy sin overhead Qt; HR3LAB recibe muestras correctamente independientemente del estado de PAUSE MAIN WINDOW.

**Métrica de fiabilidad HR3 — harmonic_ratio (sustituye a power_ratio):**
- Motivación: la señal PPG no es sinusoidal — tiene armónicos significativos en 2·f₀, 3·f₀. El `power_ratio` anterior medía solo el bin fundamental, dando valores bajos incluso para señales limpias.
- Nueva métrica `harmonic_ratio`:
  - Numerador: potencia en f₀ ± 1 bin + 2·f₀ ± 1 bin + 3·f₀ ± 1 bin (los 3 armónicos que definen la estructura periódica del PPG)
  - Denominador: potencia total en [HR_MIN_HZ, min(3·f₀ + 2 bins, Nyquist=25 Hz)] — se extiende más allá de la banda HR para incluir armónicos aunque estén fuera de [0.5–3.5 Hz]
  - Valor alto → señal periódica con estructura de armónicos clara → estimación fiable
- Atributo renombrado `last_peak_power_ratio` → `last_harmonic_ratio` en `HRFFTCalc`; etiquetas actualizadas en `HR3LabWindow`

**HR3 — Harmonic Product Spectrum (HPS) para detección robusta de fundamental:**
- Problema: a 35 BPM el 2° armónico (1.17 Hz) tenía más potencia que la fundamental (0.58 Hz); el algoritmo elegía el armónico.
- Solución: **Harmonic Product Spectrum** — `HPS[i] = S[i] · S[2i] · S[3i]`. Refuerza la fundamental (todos los armónicos coinciden) y suprime los picos armónicos aislados (sus sub-armónicos son débiles). El peak-finding se hace sobre HPS; la interpolación parabólica de precisión se hace sobre el espectro original.
- `last_hps` añadido como atributo diagnóstico en `HRFFTCalc`
- `HR3LabWindow`: curva naranja (HPS normalizado) superpuesta sobre la cyan (espectro) en el plot FFT

**Rango HR unificado a 30–250 BPM en todos los ficheros:**
- `ppg_plotter.py` funciones autocorr: `hr_min=38, hr_max=252` → `hr_min=30, hr_max=250`
- `ppg_plotter.py` `HRFFTCalc.HR_MAX_HZ`: `3.5` (210 BPM) → `4.167` (250 BPM)
- `mow_afe4490_spec.md` línea HR1: `[40, 240] BPM` → `[30, 250] BPM`
- `mow_afe4490.cpp`: ya estaba en 30–250 BPM ✓

**Instrucción de flujo de trabajo:** ejecutar automáticamente tras cada cambio de código.

---


## Sesión — 2026-04-07

### Tema: Diagnóstico de corrupción serial USB-CDC + conclusiones; preguntas conceptuales

---

**Resultado del test Serial.setTxBufferSize(1024) (Opción B):**
- Test completado: `ppg_chk_20260406_233852.csv`, 3729 frames, **1.770% BAD CHK**
- Comparativa completa:
  - Baseline (múltiples Serial.print): 1.752%
  - core0 + stack 8192: 1.402%
  - setTxBufferSize(1024): 1.770%
- **Conclusión:** `setTxBufferSize(1024)` no mejora la tasa de corrupción. El problema es intrínseco a la capa USB-CDC (HWCDC) del ESP32-S3, no al buffer de la aplicación.
- **Decisión:** aceptar la tasa de corrupción actual (~1.5–1.8%). El checksum XOR ya filtra los frames corruptos correctamente. Para producción (dispositivo médico), usar UART físico (Opción D, pendiente en backlog).

---

## Sesión — 2026-04-07 (continuación)

### Tema: Guard band HR, rango neonatal 25–300 BPM, preguntas DSP

---

**np.fft.rfftfreq() — explicación:**
- Devuelve el array de frecuencias (Hz) correspondientes a cada bin del output de `rfft`.
- Parámetro `d=1/fs`; sin él devuelve frecuencias normalizadas [0..0.5].
- Con BUF_LEN=512 y fs_dec=50 Hz: resolución = 50/512 ≈ 0.098 Hz ≈ 5.9 BPM.

**Resolución FFT — 5.9 BPM no es el techo:**
- El 5.9 BPM es el espaciado entre bins (bin spacing), no la resolución efectiva.
- La interpolación parabólica ya implementada en `HRFFTCalc` da resolución efectiva < 1 BPM para señal limpia.
- La norma ISO 80601-2-61 exige ±3 BPM o ±3% — sobradamente cubierto.

**Por qué la ISO exige solo ±3 BPM o ±3%:**
- La HR fisiológica tiene variabilidad natural (HRV) de ±5–10 BPM en reposo: exigir más precisión que la variabilidad del propio parámetro no tiene sentido clínico.
- El valor clínico es categórico (bradicardia / normal / taquicardia), no continuo.
- El método de referencia (ECG) tiene su propio error de medida.
- El ±3% para HR altas refleja la degradación real de la señal PPG a frecuencias elevadas.

**HRV añadida al backlog con detalle:**
- Dominio temporal: RMSSD, SDNN, NN50/pNN50, media RR.
- Dominio frecuencial: VLF (<0.04 Hz), LF (0.04–0.15 Hz), HF (0.15–0.4 Hz), ratio LF/HF.
- Prerequisito: HR4 (detección de pico real, no threshold crossing) para RR precisos.
- Añadido análisis de validez PPG vs ECG para HRV: el PPG introduce retardo mecánico variable (PTT) y jitter adicional; revisar literatura sobre concordancia PPG-HRV vs ECG-HRV.

**FFT magnitude-only — respuesta teórica:**
- No existe un FFT estándar que omita la fase: las butterfly de Cooley-Tukey calculan real e imaginario conjuntamente — la fase no se puede separar del cómputo.
- `|X|² = real² + imag²` evita el `sqrt` (para comparar picos basta el cuadrado). En firmware ESP-DSP, útil para buscar el bin ganador; `sqrt` solo en el bin final si se necesita amplitud absoluta.
- En Python con NumPy esto es irrelevante (vectorizado en C).

---

**Guard band ±3 BPM — decisión de diseño:**
- Motivación: si el algoritmo busca en [25, 300] y el corazón late a 24.5 BPM, el resultado sería erróneo. Con guard band, se busca en [22, 303] y se reporta válido solo si cae en [25, 300].
- Decisión: usar ±3 BPM absolutos (coherente con la tolerancia de la norma).
- Flujo: búsqueda interna [22, 303] BPM → validez reportada [25, 300] BPM.

**Corrección de rango — ISO 80601-2-61 + uso neonatal:**
- Rango anterior: [30, 250] BPM (incorrecto — norma exige mínimo 25 BPM).
- Rango nuevo: **[25, 300] BPM** (ISO mínimo 25; neonatal hasta 300 BPM).
- Guard band nueva: **[22, 303] BPM**.

**Cambios aplicados (spec v0.11):**

| Parámetro | Antes | Después |
|---|---|---|
| `hr_min_bpm` | 30 | 25 |
| `hr_max_bpm` | 250 | 300 |
| `hr_search_min_bpm` | 27 | 22 |
| `hr_search_max_bpm` | 253 | 303 |
| `hr_refractory_s` | 200 ms | 185 ms (cubre 303 BPM: periodo 198 ms) |
| `hr2_min_lag_s` | 0.22 s | 0.185 s |
| `hr2_acorr_max_lag` | 111 | 137 (22 BPM @ 50 Hz) |
| `HR_MIN_HZ` Python | 0.5 Hz (30 BPM) | 0.4167 Hz (25 BPM) |
| `HR_MAX_HZ` Python | 4.167 Hz (250 BPM) | 5.0 Hz (300 BPM) |
| `HR_SEARCH_MIN_HZ` | 0.45 Hz (27 BPM) | 0.3667 Hz (22 BPM) |
| `HR_SEARCH_MAX_HZ` | 4.217 Hz (253 BPM) | 5.05 Hz (303 BPM) |
| `max_lag_n` HRLabWindow | 2.0×fs | 2.73×fs |
| Defaults autocorr Python | hr_min=30, hr_max=250 | hr_min=25, hr_max=300 |

**Ficheros modificados:** `lib/mow_afe4490/mow_afe4490.h`, `lib/mow_afe4490/mow_afe4490.cpp`, `ppg_plotter.py`, `mow_afe4490_spec.md` (v0.11), `TODO.md`.

---

**Trabajo en paralelo con otra sesión de Claude Code:**
- Pregunta sobre riesgos de dos sesiones simultáneas sobre el mismo proyecto.
- Conclusión: el riesgo principal es que una sesión sobreescriba los cambios de la otra si edita un fichero que ya había leído al inicio de su contexto. Ficheros críticos: `mow_afe4490_spec.md`, `conversation_log.md`, `TODO.md`. Protocolo acordado: hacer commit en cada sesión antes de que la otra modifique ficheros compartidos.

---

**Explicación de showEvent() y _dbg_print_ranges():**
- `showEvent()`: método Qt que se dispara al hacerse visible la ventana. Se usa para ajustar tamaños de splitter con `QTimer.singleShot(0, ...)` (diferido al siguiente ciclo de event loop, cuando el layout ya es definitivo).
- `_dbg_print_ranges()`: función de diagnóstico temporal (timer cada 1 s) que imprime el rango visible y ancho del panel `p_1b`. Sin utilidad funcional, se puede eliminar junto con `_dbg_timer`.

---

**Normas HR — ISO 80601-2-61:**
- Rango mínimo obligatorio: 25–250 BPM (uso general); neonatal puede requerir hasta 300 BPM.
- Precisión: ±3 BPM o ±3% (el mayor), medido como RMSE.
- Resolución: 1 BPM.
- Gap identificado: `mow_afe4490` v0.9 cubre 30–250 BPM (límite inferior 30 vs. 25 de la norma). Para neonatal estricto, revisar cobertura hasta 300 BPM.
- Precisión sin validar aún (pendiente dataset de referencia con simulador MS100).

---

## Sesión — 2026-04-08

### Tema: Guard band HR, rango neonatal 25–300 BPM, build/upload automático, throttle sub-ventanas

---

**Instrucción de flujo de trabajo — build + upload automático tras cambio de firmware:**
- El usuario ha confirmado que al modificar `.cpp`/`.h` hay que hacer automáticamente: kill script → build → upload → relaunch, sin esperar a que lo pida.
- Si solo hay cambios Python, solo kill → relaunch.
- Guardado en memoria `feedback_platformio_tasks.md`.

---

**Corrección de rango HR — ISO 80601-2-61 + uso neonatal (spec v0.11):**
- Rango anterior incorrecto: [30, 250] BPM.
- Rango nuevo: **[25, 300] BPM** (25 BPM = mínimo ISO; 300 BPM = neonatal).
- Guard band interna: **[22, 303] BPM** (±3 BPM).

Cambios en firmware (`mow_afe4490.cpp` / `.h`):

| Parámetro | Antes | Después |
|---|---|---|
| `hr_min_bpm` | 30 | 25 |
| `hr_max_bpm` | 250 | 300 |
| `hr_search_min_bpm` | 27 | 22 |
| `hr_search_max_bpm` | 253 | 303 |
| `hr_refractory_s` | 200 ms | 185 ms |
| `hr2_min_lag_s` | 0.22 s | 0.185 s |
| `hr2_acorr_max_lag` | 111 | 137 |

Cambios en Python (`ppg_plotter.py`):
- `HR_MIN_HZ` / `HR_MAX_HZ`: 0.5/4.167 → 0.4167/5.0 Hz
- `HR_SEARCH_MIN_HZ` / `HR_SEARCH_MAX_HZ`: 27/60 / 253/60 → 22/60 / 303/60
- Defaults autocorr: `hr_min=30, hr_max=250` → `hr_min=25, hr_max=300`
- `max_lag_n` HRLabWindow: `2.0×fs` → `(60/22)×fs`

Firmware compilado y flasheado. Spec v0.11 actualizada.

---

**Bug de rendimiento — plots a mitad de velocidad con SpO2LAB + HR3LAB abiertas:**

**Síntoma:** los plots avanzan a ~mitad de velocidad esperada cuando SpO2LAB y HR3LAB están abiertas simultáneamente con la ventana principal. Desaparece al cerrar SpO2LAB y HR3LAB o al pausar la ventana principal.

**Causa:** SpO2LabWindow y HR3LabWindow se renderizaban a 50 Hz (cada llamada a `update_data()`), pero su contenido cambia mucho más lento (SpO2 lento, HR3 solo actualiza cada 0.5 s). El rendering Qt de múltiples plots a 50 Hz superaba la capacidad de proceso disponible.

**Solución:** throttle independiente por sub-ventana con contadores en `update_data()`:
- `_SUBWIN_REFRESH_EVERY = 5` → actualización a **10 Hz** (1 de cada 5 llamadas)
- `_spo2lab_refresh_counter` y `_hr3lab_refresh_counter` incrementan solo cuando hay `_new_data`
- HRLabWindow sin cambio (el usuario confirmó que sola es fluida)

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08

### Tema: Refactor ppg_plotter.py — extracción de plots y consola serie a ventanas independientes

**Objetivo:** Extraer los plots y la consola serie de `PPGMonitor` a dos ventanas flotantes independientes, siguiendo el mismo patrón que `HRLabWindow`, `SpO2LabWindow` y `HR3LabWindow`.

**Decisiones tomadas:**

- Nueva clase `PPGPlotsWindow(QWidget)`: contiene todos los plots (RED, IR, PPG, SpO2, HR) + checkboxes RED/IR. Abierta por defecto al arrancar (via `_open_ppgplots_default()`). Throttle a 25 Hz (cada 2 llamadas a `update_data()`).
- Nueva clase `SerialComWindow(QWidget)`: contiene la consola de texto (`QPlainTextEdit`) + `header_label`. Abierta por defecto al arrancar. Sin throttle propio (batch por ciclo ya es suficiente).
- `PPGMonitor` queda sólo con: sidebar de controles, `log_panel` de estado, y dispatch a sub-ventanas.
- Eliminados de `PPGMonitor`: `is_plot_paused`, `btn_pause_plot`, `toggle_pause_plot()`, `splitter`, `graphics_layout`, `console`, `header_label`, todos los `curve_*` y `p_*` de plots, los checkboxes RED/IR.
- Sidebar reorganizado: secciones DECIMACIÓN, LIBRARY, FRAME MODE, DISPLAY (PPGPLOTS, SERIALCOM), ANALYSIS (HRLAB, SPO2LAB, HR3LAB).
- `showEvent()` abre automáticamente PPGPlotsWindow + SerialComWindow + HR3LabWindow.
- `closeEvent()` cierra todas las sub-ventanas en orden.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación)

### Tema: Ajustes visuales PPGMonitor

**Ventana principal más estrecha:** `resize(2700, 1600)` → `resize(600, 1000)`.

**Log panel — texto el doble de tamaño:** `font-size: 16px` → `font-size: 32px`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 2)

### Tema: Ajustes visuales PPGMonitor (iteración 2)

**Ventana principal más ancha:** `resize(600, 1000)` → `resize(900, 1000)`.

**Log panel — texto reducido:** `font-size: 32px` → `font-size: 22px`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 3)

### Tema: Ajustes visuales PPGMonitor (iteración 3)

**Ventana principal más alta y doble de ancha:** `resize(900, 1000)` → `resize(1800, 1100)`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 4)

### Tema: Fix texto bold en log_panel + reubicación mouse hint

**Log panel — texto en negrita:** `font-weight:bold` → `font-weight:normal` en `set_status()`. El texto de los mensajes de estado aparecía en negrita; corregido a peso normal.

**Mouse hint reubicado:** El mensaje "pyqtgraph: use mouse buttons and wheel..." se eliminó de la ventana principal `PPGMonitor` (que ya no tiene plots) y se añadió a las ventanas con plots:
- `PPGPlotsWindow`: añadido como `QLabel` gris en la parte inferior del layout (es `QWidget`, no tiene `statusBar()`). Layout externo cambiado a `QVBoxLayout` para contener el hint.
- `SpO2LabWindow`, `HR3LabWindow`, `HRLabWindow`: ya tenían el hint via `statusBar()` — sin cambios.
- `SerialComWindow`: sin plots → sin hint.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 5)

### Tema: Ajuste tamaño fuente log_panel

**Log panel — tamaño de fuente:** `font-size: 22px` → `font-size: 26px`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 6)

### Tema: Sección DECIMATION del sidebar — inglés + layout + tamaño

- "DECIMACIÓN" → "DECIMATION"
- "1 de cada" → "1 out of every": movido a línea propia encima del spinbox, `font-size: 16px` → `20px`
- Spinbox: `font-size: 16px` → `20px`; sufijo "tramas" → "frames"
- Layout cambiado de `QHBoxLayout` (label + spin en fila) a widgets independientes en el `sidebar_layout`

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 7)

### Tema: Tabla de estadísticas numéricas en PPGMonitor

Añadida tabla `SIGNAL STATS` encima del `log_panel` en `PPGMonitor`.

**Diseño:**
- 15 señales (filas): PPG, SpO2, SpO2_R, HR1, HR2, HR3, RED, IR, Amb RED, Amb IR, RED sub, IR sub, RED filt, IR filt, HR1 PPG
- 5 columnas: Signal | Last | Mean | Min | Max
- **Modo reset periódico (opción B):** buffers acumulan muestras entre disparos del timer; al disparar → calcula stats, actualiza tabla, limpia buffers
- Spinbox "Update interval" (1–60 s, por defecto 1 s) en cabecera de la tabla
- Solo se alimentan buffers con tramas M1 válidas (post-checksum, post-decimación)

**Cambios en layout:** lado derecho de `content_layout` cambiado de `log_panel` directo a `right_layout (QVBoxLayout)` → stats_container + log_panel.

**Nuevos elementos en código:**
- `_STATS_SIGNALS`: lista de (nombre, atributo) para las 15 señales
- `_stats_buf`: dict de listas, una por señal
- `_stats_timer` (`QTimer`): conectado a `_update_stats_table()`
- `spin_stats_interval`: spinbox que ajusta el intervalo del timer
- `stats_table` (`QTableWidget` 15×5)
- `_update_stats_table()`: calcula last/mean/min/max, actualiza tabla, limpia buffers

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 8)

### Tema: Tabla de estadísticas — mayor tamaño

- Texto filas: `font-size: 14px` → `18px`
- Cabecera: `font-size: 13px` → `17px`
- Alto de fila: `setDefaultSectionSize(22)` → `32`
- Padding de celda: `2px 6px` → `4px 8px`

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 9)

### Tema: Tabla de estadísticas — mayor tamaño (iteración 2)

- Texto filas: `18px` → `22px`
- Cabecera: `17px` → `21px`
- Alto de fila: `32` → `40`
- Padding de celda: `4px 8px` → `6px 10px`

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 10)

### Tema: Splitter entre tabla de estadísticas y log_panel

`right_layout (QVBoxLayout)` reemplazado por `right_splitter (QSplitter vertical)`. La tabla y el log_panel son ahora redimensionables por el usuario arrastrando el separador. `stretchFactor=1` en ambos paneles (50/50 por defecto).

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 11)

### Tema: Tabla de estadísticas — uniformizar tamaño de texto a 22px

Título "SIGNAL STATS", label "Update interval:", spinbox y cabeceras de columna igualados al tamaño de las celdas (`22px`). Ancho del spinbox ajustado a `110px`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 12)

### Tema: Tabla de estadísticas — alineación y color de celdas HR

- Valores (cols 1–4): alineados a la derecha (`AlignRight | AlignVCenter`)
- Celdas Mean (col 2) de HR1, HR2, HR3 (filas 3, 4, 5): fondo granate oscuro `#5C001A`
- Constantes de clase `_STATS_HR_ROWS`, `_STATS_MEAN_COL`, `_STATS_MAROON` para mantener coherencia entre init y `_update_stats_table()`

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 13)

### Tema: Selector de puerto serie configurable en el sidebar

- Añadida sección **PORT** al top del sidebar: `QComboBox` con puertos disponibles + botón `↺` (refresh) + botón `CONNECT`
- `from serial.tools import list_ports` añadido a imports
- **`_populate_ports()`**: rellena el combobox con `list_ports.comports()`, preserva selección
- **`_connect_serial(port)`**: para el hilo lector anterior, cierra el puerto, abre el nuevo, relanza el hilo; sin `sys.exit` — fallo muestra error en status y botón rojo `#3A1A1A`; éxito → botón verde `CONNECTED`
- Conexión inicial al arrancar auto-selecciona `COM15` (fallback al primero disponible)
- `_serial_reader` protegido contra `self.ser is None`
- `self.ser`, `_serial_queue`, `_reader_stop`, `_reader_thread` inicializados antes de construir la UI

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 14)

### Tema: Persistencia de estado UI con QSettings

Implementada persistencia completa del estado de la UI en `ppg_plotter.ini` (directorio del script).

**Mecanismo:** `QSettings(SETTINGS_FILE, QSettings.IniFormat)`. Se guarda en `closeEvent` y se restaura en `__init__` / `_restore_settings()`.

**Estado guardado por ventana:**

| Ventana | Datos |
|---|---|
| PPGMonitor | geometría, splitter derecho, `spin_decim`, `spin_stats_interval`, puerto COM, qué subventanas estaban abiertas |
| PPGPlotsWindow | geometría, 8 checkboxes RED/IR |
| SerialComWindow | geometría |
| HRLabWindow | geometría |
| HR3LabWindow | geometría |
| SpO2LabWindow | geometría, `spin_spo2_ref` |

**Cambios estructurales:**
- `SETTINGS_FILE` constante global; `import os` añadido
- `right_splitter` → `self.right_splitter` (era variable local)
- `_restore_settings()` llamado en `__init__` antes de `_connect_serial()` (para restaurar puerto)
- `showEvent` usa settings para decidir qué subventanas abrir (defecto: PPGPlots+SerialCom+HR3Lab)
- `_save_settings()` llamado al inicio de `closeEvent` de PPGMonitor
- Primer arranque sin `.ini`: valores por defecto de siempre

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 15)

### Tema: Tooltips descriptivos en SIGNAL STATS

`_STATS_SIGNALS` ampliado de tuplas `(name, attr)` a `(name, attr, tooltip)`. Cada señal lleva su descripción técnica completa inline, junto al nombre y atributo — si el código cambia, la descripción está justo al lado.

El tooltip se asigna a **todas las celdas de la fila** (nombre + Last/Mean/Min/Max) mediante `item.setToolTip(tooltip)`. Aparece al pasar el ratón sobre cualquier celda de la fila.

Descripciones incluidas para las 15 señales: PPG, SpO2, SpO2_R, HR1, HR2, HR3, RED, IR, Amb RED, Amb IR, RED sub, IR sub, RED filt, IR filt, HR1 PPG.

Todos los bucles que desempaquetaban `(name, attr)` actualizados a `(name, attr, _tooltip)` o `(name, attr, _)`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09

### Tema: HR3LabWindow — anchura mínima libre

`setMinimumWidth(0)` en `left_gw`, `right_gw` y `self._splitter` dentro de `HR3LabWindow`. Los `pg.GraphicsLayoutWidget` tenían un ancho mínimo implícito que impedía reducir la ventana.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 1)

### Tema: HR3LAB anchura mínima (fix 2) + autosave de settings

**HR3LAB:** el verdadero limitante de anchura era `_info_label` (texto largo). Corregido con `setSizePolicy(Ignored, Preferred)` + `setMinimumWidth(0)`.

**ppg_plotter.ini no se guardaba al forzar cierre:** `Stop-Process -Force` mata Python sin ejecutar `closeEvent`, por lo que `_save_settings()` nunca se llamaba. Solución: `_autosave_settings_timer` (QTimer, cada 10 s) que llama a `_save_settings()` periódicamente. Máxima pérdida posible: 10 s de cambios de posición/tamaño.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 2)

### Tema: Traer ventanas al frente al arrancar el script

Al lanzar el script, las ventanas quedaban detrás de otras ventanas del sistema operativo. Solución: método `_bring_all_to_front()` en `PPGMonitor` que llama a `raise_()` + `activateWindow()` sobre todas las ventanas abiertas (`self`, `ppgplots_window`, `serialcom_window`, `hrlab_window`, `spo2lab_window`, `hr3lab_window`). Se invoca desde `showEvent` via `QTimer.singleShot(300, ...)` — 300 ms para que todas las sub-ventanas hayan sido creadas.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 3)

### Tema: Traer ventanas al frente — fix Win32 con AttachThreadInput

`raise_()` + `activateWindow()` no es suficiente en Windows: el SO bloquea el robo de foco si la app no es el proceso en primer plano. Solución: usar la API Win32 directamente con `ctypes`:
1. `GetForegroundWindow()` + `GetWindowThreadProcessId()` para obtener el TID del proceso en primer plano.
2. `AttachThreadInput(my_tid, fg_tid, True)` para adjuntar el hilo de la app al hilo en primer plano (le da permiso para cambiar el foco).
3. `SetForegroundWindow(hwnd)` para cada ventana.
4. `AttachThreadInput(my_tid, fg_tid, False)` para desadjuntar.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 4)

### Tema: Tooltips SIGNAL STATS — fuente doble y ventana estrecha multilínea

Los tooltips de la tabla SIGNAL STATS usaban texto plano, lo que producía un popup de una sola línea muy ancho. Cambiado a HTML con `_make_tooltip()`: tabla de 360px de ancho + `font-size:26px` (doble del default ~13px) + `white-space:normal` para que el texto haga wrap en varias líneas.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 5)

### Tema: Tooltips SIGNAL STATS — fuente más grande, fondo más claro, delay reducido

- Fuente: 26px → 30px en el HTML del tooltip.
- Fondo: `QToolTip` stylesheet global → `background-color: #2E2E40` (azul oscuro medio), `color: #E8E8E8`, `border: 1px solid #7070A0`.
- Delay: `QProxyStyle` (`_FastTipStyle`) sobreescribe `SH_ToolTip_WakeUpDelay` a 150 ms (por defecto ~700 ms). Se aplica como `app.setStyle(_FastTipStyle('Fusion'))`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 6)

### Tema: Tooltips SIGNAL STATS — fondo llamativo + nombre de variable resaltado

- Fondo tooltip: `#1A0040` (púrpura oscuro) con borde `2px solid #9955FF`.
- `_make_tooltip(name, text)`: primera línea con el nombre de la señal en negrita, `font-size:32px`, color `#FFE066` (amarillo dorado). Descripción debajo en `font-size:30px`.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-09 (continuación 7)

### Tema: Tooltips SIGNAL STATS — color de fondo llamativo (fix)

Qt ignora el `QToolTip` stylesheet cuando el tooltip usa rich text (HTML). Solución: color embebido directamente en el `style` de la tabla HTML (`background-color:#7700CC`). También se mantiene en el stylesheet como fallback. Borde amarillo dorado `#FFE066` tanto en stylesheet como en tabla.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08

### Tema: Aprendizaje de Claude Code — agentes en background, bash, WSL

**Sin modificaciones de código fuente en esta sesión.**

---

**¿Por qué aparece el error 401 "Invalid authentication credentials"?**
Token de sesión expirado o invalidado. Con dos sesiones abiertas simultáneamente puede ocurrir cuando una renueva el token e invalida el de la otra. Solución: ejecutar `/login`.

---

**Agentes en background — demostración práctica**
Se lanzó un agente `Explore` en background para analizar sincronización entre `mow_afe4490_spec.md` y el código en `lib/mow_afe4490/`. Resultado: spec en v0.11, código en v0.7 — brecha de 4 versiones. API pública y struct correctamente sincronizados; desincronizaciones en rangos HR y constantes de timing. Pendiente decidir si adelantar código a v0.11 o rebajar spec a v0.7.

---

**PATH y diagnóstico de instalación**
`C:\Users\alexc\.local\bin` sí está en el PATH de usuario (en minúsculas). El aviso del diagnóstico es un falso positivo por diferencia de capitalización. Claude ejecutado: `claude.exe` v2.1.81 desde esa ruta.

---

**WSL instalado sin saberlo**
Al ejecutar `bash` en terminal se lanzó WSL (no Git Bash). El usuario tiene Ubuntu real instalado. `/mnt/c` apunta a `C:\`.

---

## Sesión — 2026-04-08 (continuación 1)

### Tema: Tooltips en todos los controles del script + splitter en SPO2LAB + ajuste color tooltip

---

**Tooltips rich HTML extendidos a todos los controles del script**

Se añadió `setToolTip(_make_tooltip(...))` a todos los controles interactivos del script (antes solo existía en la tabla SIGNAL STATS):

- `PPGMonitor` sidebar: `combo_port`, `btn_port_refresh`, `btn_port_connect`, `btn_pause`, `btn_save`, `btn_save_raw`, `spin_decim`, `btn_lib_mow`, `btn_lib_pc`, `btn_frame_m1`, `btn_frame_m2`, `btn_ppgplots`, `btn_serialcom`, `btn_hrlab`, `btn_spo2lab`, `btn_hr3lab`, `spin_stats_interval`
- `PPGPlotsWindow`: 8 checkboxes (RED raw/amb/clean/filt, IR raw/amb/clean/filt)
- `SpO2LabWindow`: `_spin_spo2_ref`, `_spin_avg_win`, `btn_add`, `btn_reg`, `btn_clear`, `btn_export`

Decisión de diseño: `_make_tooltip(name, text)` promovida de función local anidada en `_setup_stats_table` a **función de módulo** (antes de `class SpO2LabWindow`), accesible desde todas las clases. La versión local fue eliminada.

Regla establecida: todo control nuevo o modificado en `ppg_plotter.py` debe tener siempre tooltip con `_make_tooltip`. Guardado en memoria `feedback_tooltips.md`.

---

**Splitter horizontal en SPO2LAB**

El sidebar de calibración (antes ancho fijo 390 px) es ahora redimensionable con un `QSplitter(Qt.Horizontal)`. Tamaño por defecto: plots 1100 px / sidebar 390 px. Estado del splitter persistido en `ppg_plotter.ini` como `SpO2LabWindow/splitter`.

---

**Color de fondo del tooltip: ajuste a más oscuro**

Color cambiado de `#7700CC` a `#5500AA` (dos sitios: HTML embebido en `_make_tooltip` y stylesheet `QToolTip`).

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 2)

### Tema: Texto _MOUSE_HINT

Cambiado "on the plots" por "on plots and axes" en `_MOUSE_HINT` (línea 465).

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 3)

### Tema: _MOUSE_HINT — consistencia y color llamativo en las 4 ventanas

PPGPlotsWindow usaba un QLabel con `color: #555555; font-size: 11px` (casi invisible). Las otras 3 ventanas (SPO2LAB, HR3LAB, HRLAB) heredaban `#E0E0E0` del stylesheet global del QMainWindow sin tamaño explícito.

Solución: las 4 ventanas muestran ahora `_MOUSE_HINT` en `#FFAA44` (naranja ámbar) a 13px. Las 3 QMainWindow usan `statusBar().setStyleSheet(...)` antes del `showMessage`; PPGPlotsWindow cambia el estilo del QLabel.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 4)

### Tema: _MOUSE_HINT — tamaño mayor e itálica

`_MOUSE_HINT` subido de 13px a 16px y añadida `font-style: italic` en las 4 ventanas (SPO2LAB, HR3LAB, HRLAB statusBars + PPGPlotsWindow QLabel).

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 5)

### Tema: _MOUSE_HINT — tamaño de letra aumentado de nuevo

`_MOUSE_HINT` subido de 16px a 20px en las 4 ventanas.

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 6)

### Tema: Tooltip — ventana más ancha

Ancho del tooltip aumentado de 360px a 540px (~50% más).

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 7)

### Tema: Cierre de sesión — resumen de cambios en ppg_plotter.py

Sesión dedicada exclusivamente a mejoras de UI en `ppg_plotter.py`. Sin cambios en firmware ni en la librería `mow_afe4490`.

**Cambios acumulados en esta sesión:**
- `_make_tooltip` promovida a función de módulo (antes función local anidada)
- Tooltips rich HTML añadidos a todos los controles del script: sidebar PPGMonitor (17 controles), checkboxes PPGPlotsWindow (8), SpO2LabWindow (6)
- Splitter horizontal en SPO2LAB entre plots y sidebar; estado persistido en `ppg_plotter.ini`
- Color tooltip: `#7700CC` → `#5500AA` (más oscuro)
- Ancho tooltip: 360px → 540px
- `_MOUSE_HINT`: texto "on the plots" → "on plots and axes", color `#555555`/`#E0E0E0` → `#FFAA44`, tamaño 11px → 20px, añadida itálica, aplicado en las 4 ventanas con consistencia

**Fichero modificado:** `ppg_plotter.py`.

---

## Sesión — 2026-04-08 (continuación 8)

### Tema: Implementación firmware HR3 (FFT + HPS)

**Pregunta principal:** Implementar HR3 en la librería `mow_afe4490` (firmware) — algoritmo FFT + Harmonic Product Spectrum, como tercer algoritmo de HR en paralelo con HR1 y HR2.

---

**¿Por qué FFT radix-2 DIT propio en lugar de ESP-DSP?**
ESP-DSP requiere configuración IDF como componente externo y no está disponible en `env:native` (tests en PC). Se implementó un FFT radix-2 DIT Cooley-Tukey autocontenido en el namespace anónimo del `.cpp`, que funciona en ambos entornos.

**¿Por qué `_hr3_fft[1024]` como miembro de clase en lugar de variable local?**
Con 4096 bytes en stack causaría stack overflow en la task interna (que tenía MOW_AFE4490_TASK_STACK=4096). Al moverlo al heap (miembro de clase) se elimina el riesgo. Se aumentó también MOW_AFE4490_TASK_STACK de 4096 a 8192 para dar margen a `cosf`/`sinf` durante los stages butterfly.

**¿Por qué `_recalc_biquad_lp()` nueva función en lugar de usar `_recalc_biquad()`?**
`_recalc_biquad()` sólo implementa bandpass. HR3 necesita un LP de anti-aliasing (10 Hz) antes de decimación. Se añadió `_recalc_biquad_lp()` con la transformada bilineal para Butterworth LP 2º orden (ganancia DC = 1.0).

**¿Por qué HPS (P[k]·P[2k]·P[3k]) en lugar de peak del espectro directo?**
El PPG frecuentemente tiene armónicos dominantes (2.ª o 3.ª) con mayor potencia que el fundamental a FC elevada. HPS refuerza el fundamental multiplicando el espectro por sus versiones decimadas; evita que el algoritmo bloquee en un armónico.

**¿Por qué `search_max <= nyquist/3`?**
Garantiza que `P[3k]` esté siempre dentro de la banda de Nyquist. Si `search_max` fuera mayor, `P[3*search_max]` caería fuera del espectro calculado.

**Decisiones de diseño:**
- Sustracción de media (DC removal) antes de la ventana Hann → elimina DC offset que quedaría tras el filtro LP
- Negación de la señal LP filtrada en `_update_hr3()` igual que en `_update_hr2()` → picos hacia arriba
- Guard band idéntica a HR1/HR2: búsqueda interna [22, 303] BPM, reporte válido [25, 300] BPM
- `hr3_update_interval = 25` → actualización cada 0.5 s al igual que HR2
- Interpolación parabólica sobre espectro original (no sobre HPS) para mayor precisión sub-bin

**Trama serie:**
- Trama `$M1` ampliada: campo 17 (índice 0) = HR3 (`%.2f`, `-1.0f` si no válido)
- Trama `$P1` ampliada igualmente: campo 17 = `-1.0f` (placeholder, no disponible en protocentral)
- `buf[256]` en main.cpp suficiente (trama crece ~7 bytes)

**ppg_plotter.py:**
- Parser: `>= 17` → `>= 18`, `parts[1:17]` → `parts[1:18]`, `data_hr3` = `p[16]` (firmware) en lugar de calculado en Python
- `hr3_calc.update()` se mantiene para uso exclusivo en HR3LabWindow (diagnósticos)
- Todos los CSV headers actualizados con columna `HR3`
- Tooltip `$M1` actualizado: "17 fields" → "18 fields"
- Descripción HR3 en stats actualizada: "computed in Python" → "computed in firmware"

**Archivos modificados:** `lib/mow_afe4490/mow_afe4490.h`, `lib/mow_afe4490/mow_afe4490.cpp`, `src/main.cpp`, `ppg_plotter.py`, `mow_afe4490_spec.md` (v0.11 → v0.12), `TODO.md`.

**Build:** SUCCESS (303 KB Flash, 31 KB RAM). Flashed a COM15.

---

## Sesión 2026-04-08 — Consulta sobre /context

**Tema:** Uso informativo de Claude Code — sin cambios de código.

**Pregunta:** El usuario pidió explicación de la salida del comando `/context`.

**Respuesta:** Se explicó el desglose de tokens: system prompt (6.4k), system tools (8.4k), memory files (1.7k), skills (476), messages (183), espacio libre (~150k, 75%), buffer autocompact (33k). Sesión al 9% de uso de ventana de contexto.

**Decisiones:** Ninguna. Sesión puramente informativa.

---

## Sesión 2026-04-09 — GUI i18n, AMDF task, CLAUDE.md update

**Tema:** Traducción de textos en español a inglés en `ppg_plotter.py`, añadir tarea pendiente HR4-AMDF, y ampliar consigna de idioma en CLAUDE.md.

**Preguntas y decisiones:**

1. **Verificación de implementación HR3:** Se confirmó que el commit `cd93f15` contiene la implementación completa (FFT+HPS firmware, plotter, spec v0.12). Los cambios sin commitear en `ppg_plotter.py` son mejoras menores post-implementación; el usuario decidió no commitearlos por ahora.

2. **Explicación de HPS:** Harmonic Product Spectrum — `HPS[k] = |X[k]|·|X[2k]|·|X[3k]|`; amplifica el fundamental donde coinciden sus armónicos.

3. **Tarea HR4 — AMDF:** Añadida en `TODO.md` como nuevo método de cálculo de HR mediante Average Magnitude Difference Function normalizado, con ventana adaptativa y threshold dinámico. El antiguo HR4 (peak detection por derivada) renombrado a HR5.
   - AMDF normalizado: `AMDF_n[τ] = AMDF[τ] / (AMDF_mean + ε)`
   - Ventana adaptativa: ajustada a 2–3 ciclos según estimación previa de HR
   - Threshold dinámico: mínimo válido si cae bajo fracción configurable de la media (p.ej. 0.6·mean)

4. **GUI i18n — ppg_plotter.py:** 22 strings en español traducidos a inglés (botones, tooltips, mensajes de estado, docstring). Ningún cambio funcional.
   - Botones: PAUSAR→PAUSE, GUARDAR→SAVE, REANUDAR→RESUME, DETENER→STOP, GRABACIÓN→RECORDING
   - Status: "Sistema ONLINE"→"System ONLINE", "Librería activa"→"Active library", "Memoria guardada"→"Snapshot saved", etc.

5. **CLAUDE.md — regla de idioma ampliada:** La regla 6 ahora cubre explícitamente textos de GUI (botones, labels, tooltips, mensajes de estado, cabeceras, títulos de ventana) además de código y comentarios.

---

## Sesión 2026-04-09 — PPG Plots bottom row equal width; HRLAB→HR2LAB; side panel reorder

**Tema:** Renombrado de botón HRLAB a HR2LAB y reordenación de la sección ANALYSIS del side panel.

**Decisiones:**

1. **HRLAB → HR2LAB:** El botón y la ventana se renombraron a HR2LAB para ser consistentes con la nomenclatura HR3LAB. El tooltip se actualizó para reflejar que muestra la autocorrelación normalizada (HR2). Variables internas (`btn_hrlab`, `hrlab_window`) se mantienen sin cambio.

2. **Reorden ANALYSIS:** El orden anterior era HR2LAB → SPO2LAB → HR3LAB (inconsistente). El nuevo orden es `HR2LAB → HR3LAB → SPO2LAB`: algoritmos de HR en orden numérico, SpO2 al final.

3. **PPG Plots — anchura igual en los tres plots inferiores:** Varios intentos fallidos con pyqtgraph `GraphicsLayout` (stretch factors, colspan, setWidth en ejes Y) — la distribución de anchuras en pyqtgraph es poco fiable cuando los ejes Y tienen anchos distintos.
   Solución definitiva: los tres plots inferiores (PPG, SpO2, HR) se sacan del `GraphicsLayoutWidget` y se implementan como tres `pg.PlotWidget` independientes en un `QHBoxLayout` estándar de Qt. Qt distribuye el espacio equitativamente por defecto. RED e IR permanecen en el `GraphicsLayoutWidget` original.

---

## Sesión 2026-04-09 — Deep serial frame restructure

**Tema:** Reestructuración profunda de la trama serie en firmware y plotter.

**Decisiones:**

1. **Nueva trama $M1 (18 campos de datos):**
   `LibID,SmpCnt,Ts_us,RED,IR,AmbRED,AmbIR,REDSub,IRSub,PPG,SpO2,SpO2SSI,SpO2_R,HR1,HR1SSI,HR2,HR2SSI,HR3,HR3SSI`
   - Eliminados: REDFilt, IRFilt, HR1PPG (señales de diagnóstico obsoletas)
   - Añadidos: SpO2SSI, HR1SSI, HR2SSI, HR3SSI (Signal Inadequacy Index: 0.0=adecuado, 1.0=inadecuado)

2. **SSI (Signal Inadequacy Index):** Derivado directamente de los booleanos `spo2_valid`/`hr1_valid`/`hr2_valid`/`hr3_valid` existentes en la librería. Sin nuevo cómputo en firmware.

3. **Trama $P1 (protocentral):** Mismo formato que $M1; campos no disponibles = -1.0.

4. **hr1_ppg eliminado de mow_afe4490:** Campo `hr1_ppg` y `_hr1_peak_marker_countdown` eliminados del struct `AFE4490Data` y de la librería (eran diagnóstico temporal).

5. **Fix crítico en parser plotter:** El checksum NMEA (`*XX`) causaba `ValueError: could not convert string to float` silencioso en el parser. Fix: `line[1:].split('*')[0].split(',')` antes del split de campos.

6. **Archivos modificados:** `mow_afe4490.h`, `mow_afe4490.cpp`, `src/main.cpp`, `ppg_plotter.py`.

---

## Sesión 2026-04-09 — Corrección nomenclatura SII

**Tema:** Renombrado HR1SSI→HR1SII, HR2SSI→HR2SII, HR3SSI→HR3SII en firmware y plotter.

**Decisión:** El acrónimo correcto es SII (Signal Inadequacy Index), no SSI. SpO2SSI no cambia (era correcto). Afecta a `src/main.cpp` y `ppg_plotter.py` (comentarios, headers CSV, tooltip, SERIAL_HEADER, parser).

---

## Sesión 2026-04-09 — Fix build: initializer list AFE4490Data

**Tema:** Error de compilación tras eliminar `hr1_ppg` del struct.

**Decisión:** El initializer list `_current_data = {0, 0.0f, ..., 0.0f}` en `mow_afe4490.cpp` (líneas 208 y 484) tenía 17 valores (sobraba el antiguo `hr1_ppg`). Reemplazado por `_current_data = AFE4490Data{}` (zero-init agregado), más robusto ante futuros cambios del struct. Build + upload COM15 exitosos.

---

## Sesión 2026-04-09 — AFE4490Data: raw signals primero (orden = trama serie)

**Tema:** Completar el reordenamiento del struct para que las señales raw precedan a las calculadas, igual que en la trama $M1/$P1.

**Decisión:** En el cambio anterior se había reordenado el bloque de señales procesadas pero no se había movido el bloque raw al principio. Corregido en `mow_afe4490.h` y `mow_afe4490_spec.md`. El `.cpp` no necesita cambios (acceso por nombre, no por posición). Orden final del struct: led2(RED), led1(IR), aled2(AmbRED), aled1(AmbIR), led2_aled2(REDSub), led1_aled1(IRSub), ppg, spo2, spo2_sqi, spo2_r, pi, hr1, hr1_sqi, hr2, hr2_sqi, hr3, hr3_sqi.

---

## Sesión 2026-04-09 — AFE4490Data: bool _valid → float _sqi + reorden struct

**Tema:** Eliminar los campos `bool *_valid` de `AFE4490Data` y sustituirlos por `float *_sqi` (Signal Quality Index, 0=inválido, 1=válido). Reordenar el struct para que coincida con el orden de la trama serie $M1/$P1.

**Decisión:** El usuario decidió no mantener los bools. El struct pasa a tener `spo2_sqi`, `hr1_sqi`, `hr2_sqi`, `hr3_sqi` como `float`. El orden del struct refleja ahora exactamente el orden de la trama serie. Ficheros afectados: `mow_afe4490.h` (struct + test helpers), `mow_afe4490.cpp` (19 asignaciones), `src/main.cpp` (snprintf usa SQI directamente), `test/test_spo2`, `test/test_hr1`, `test/test_hr2` (assertions `TRUE/FALSE` → `EQUAL_FLOAT`), `examples/basic/main.cpp` (`*_valid` → `*_sqi > 0.0f`), `mow_afe4490_spec.md` (struct y descripciones).

---

## Sesión 2026-04-09 — Corrección lógica SQI (invertida)

**Tema:** SQI = Signal Quality Index, rango 0–1, siendo 1 la calidad máxima (señal válida).

**Decisión:** El firmware enviaba `valid ? 0.0f : 1.0f` (invertido). Corregido a `valid ? 1.0f : 0.0f` en `main.cpp` para los cuatro campos (SpO2SQI, HR1SQI, HR2SQI, HR3SQI). En `ppg_plotter.py`, deques SQI inicializados a `0.0` (antes `1.0`) y fallback M2 también a `0.0`. Definición guardada en memoria del proyecto.

---

## Sesión 2026-04-09 — Renombrado variables internas _ssi → _sqi en ppg_plotter.py

**Tema:** Coherencia de nomenclatura interna Python con el protocolo serie.

**Decisión:** Las variables `data_spo2_ssi`, `data_hr1_ssi`, `data_hr2_ssi`, `data_hr3_ssi` renombradas a `data_spo2_sqi`, `data_hr1_sqi`, `data_hr2_sqi`, `data_hr3_sqi` en todas sus ocurrencias (deques, parser, guardado snapshot, fallback M2). Completa el renombrado SII→SQI iniciado antes, que sólo afectaba a strings del protocolo.

---

## Sesión 2026-04-09 — Añadido PI (Perfusion Index) al protocolo serie

**Tema:** Añadir PI como nuevo campo en la trama serie, después de SpO2_R.

**Decisión:** PI = (AC_IR / DC_IR) × 100 [%], calculado en `mow_afe4490.cpp::_update_spo2()` a partir de los ya existentes `_ac2_ir` y `_dc_ir`. Se actualiza siempre (independiente del warmup de SpO2). Añadido al struct `AFE4490Data` como `float pi`. Tramas `$M1` y `$P1` pasan de 18 a 19 campos de datos. En `$P1` (protocentral) se envía `-1`. Plotter actualizado: deque `data_pi`, parser (índice 13), todos los CSV headers, `_STATS_SIGNALS` y M2 fallback.

---

## Sesión 2026-04-09 — Renombrado SII → SQI

**Tema:** Corrección de acrónimo: SII pasa a SQI (Signal Quality Index).

**Decisión:** `SpO2SSI` → `SpO2SQI`, `HR1SII` → `HR1SQI`, `HR2SII` → `HR2SQI`, `HR3SII` → `HR3SQI`. Afecta a `src/main.cpp` y `ppg_plotter.py` (20 ocurrencias en total: comentarios, headers CSV, SERIAL_HEADER, parser). El acrónimo SQI es más estándar en la literatura de señales biomédicas (Signal Quality Index).

---

## Sesión 2026-04-09 — SQI continuo (0–1) en todos los algoritmos

**Tema:** Reemplazar SQI binario (0/1) por métricas continuas de calidad de señal.

**Decisiones:**

- **SpO2 SQI:** basado en Perfusion Index. `SQI = clamp((PI − 0.5) / (2.0 − 0.5), 0, 1)`. PI < 0.5 % → 0, PI ≥ 2.0 % → 1. Umbrales Nellcor/Masimo. Si SpO2 fuera del rango válido → SQI = 0.

- **HR1 SQI:** coeficiente de variación de los 5 intervalos RR. `CV = std / mean`, `SQI = clamp(1 − CV / 0.15, 0, 1)`. Ritmo perfecto → 1, CV ≥ 15 % (criterio clínico de arritmia) → 0.

- **HR2 SQI:** valor de la autocorrelación normalizada en el lag dominante (`y_peak`). Ya en [0, 1] por construcción. Alta periodicidad → SQI cercano a 1.

- **HR3 SQI:** concentración espectral. `fraction = P[peak] / Σ P[k]`, `SQI = clamp((fraction − 1/N_bins) / (1 − 1/N_bins), 0, 1)`. Espectro con tono dominante → 1, espectro difuso → 0.

**Versión:** librería y spec pasan a v0.13.

**Tests actualizados:** los `ASSERT_EQUAL_FLOAT(1.0f, sqi)` de HR1/HR2 pasan a `ASSERT_GREATER_THAN(0.7f, sqi)` (señal sintética pura tiene SQI alto pero no necesariamente 1.0 exacto). SpO2 tests se mantienen con `== 1.0f` (PI ≈ 7 % con los parámetros de test → SQI = 1.0 tras clamp).

---

## Sesión 2026-04-09 — ppg_plotter.py: SQI continuo en tabla de señales y títulos de gráficas

**Tema:** Actualizar el plotter para reflejar el SQI continuo [0–1].

**Decisiones:**

- **Tabla de señales (`_STATS_SIGNALS`):** añadidas 4 filas SQI intercaladas después de su señal padre: SpO2 SQI (fila 2), HR1 SQI (fila 6), HR2 SQI (fila 8), HR3 SQI (fila 10). La tabla pasa de 13 a 17 filas.

- **`_HR_ROWS` / `_STATS_HR_ROWS`:** corregidos de {3,4,5} (que apuntaban a PI/HR1/HR2, era un bug) a {5,7,9} (HR1, HR2, HR3 con la nueva numeración). El fondo maroon en columna Mean sigue aplicándose solo a las filas HR.

- **`PPGPlotsWindow.update_plots`:** firma ampliada con `data_spo2_sqi`, `data_hr1_sqi`, `data_hr2_sqi`, `data_hr3_sqi`. Títulos de gráficas actualizados: SpO2 muestra `SQI: 0.85`, HR muestra `[0.92]` gris junto a cada valor de BPM.

- **Call site:** llamada a `ppgplots_window.update_plots` actualizada con los 4 deques SQI.

---

## Sesión 2026-04-09 — ppg_plotter.py: tabla SIGNAL STATS reordenada según trama serie

**Tema:** Alinear el orden de filas de `_STATS_SIGNALS` con el orden exacto de los campos en la trama $M1/$P1.

**Decisión:** Orden nuevo: RED, IR, Amb RED, Amb IR, RED sub, IR sub, PPG, SpO2, SpO2 SQI, SpO2_R, PI, HR1, HR1 SQI, HR2, HR2 SQI, HR3, HR3 SQI. `_STATS_HR_ROWS` / `_HR_ROWS` actualizados a {11, 13, 15}.

---

## Sesión — 2026-04-09

### Tema: Diseño e implementación de las ventanas TEST (SPO2TEST, HR1TEST, HR2TEST, HR3TEST)

**Pregunta clave:** ¿Es buena idea añadir 4 ventanas TEST que reimplementen los algoritmos en Python para comparar con el ESP32?

**Decisión:** Sí. Se adopta el patrón LAB (pre-implementación, exploratorio) vs TEST (post-implementación, verificación). Las ventanas TEST son réplicas Python exactas del spec, no reutilizan código LAB. El spec (`mow_afe4490_spec.md`) actúa como contrato entre firmware y mirror Python.

**Diseño acordado:**
- 4 ventanas independientes: SPO2TEST, HR1TEST, HR2TEST, HR3TEST
- Todo implementado desde cero (sin reutilizar código LAB)
- Modo live: datos desde serial; modo offline: carga CSV → batch → plot estático zoomable
- Parámetros ajustables en UI con indicador verde (FIRMWARE DEFAULTS) / naranja (CUSTOM PARAMS) + botón RESET TO DEFAULTS
- HR1 mirror: ejecutar a 500 Hz (antes del continue de decimación)
- Spec actualizado con sección 8 (LAB/TEST philosophy, design rules)

**Implementado esta sesión:** SPO2TEST completo
- `SpO2TestCalc`: mirror from scratch de firmware _update_spo2() según spec §5.1
- `SpO2TestWindow`: 6 plots (SpO2 fw/py, delta, R fw/py, SQI fw/py, DC, RMS AC), panel de parámetros, tabla de valores, modo offline CSV, export
- Integrado en PPGMonitor: botón SPO2TEST en sidebar sección TEST, toggle, settings persistence

---

---

## Sesión 2026-04-09 (continuación) — HR3TEST

### Tema: Implementación de HR3TEST (4ª y última ventana TEST)

**Contexto:** Esta sesión continuó directamente desde la anterior (contexto resumido). SPO2TEST, HR1TEST y HR2TEST ya estaban implementados y funcionando. HR3TEST era el único pendiente.

**Decisión:** HR3TEST sigue el mismo patrón que HR2TEST. El mirror corre a 50 Hz (tasa decimada), alimentado por `PPGMonitor.update_plots()`. No hay hook a 500 Hz (a diferencia de HR1TEST).

**Implementado:**

`HR3TestCalc`:
- Mirror from scratch de firmware _update_hr3() según spec §5.4
- Pipeline: LP Butterworth 2nd-order 10 Hz → buffer circular 512 muestras → cada 25 muestras: sustracción de media → ventana Hann → rfft → HPS P[k]·P[2k]·P[3k] → argmax en rango HR → interpolación parabólica (sobre espectro original)
- SQI: fraction = P[peak_bin]/ΣP[k], baseline = 1/N_bins, SQI = clamp((fraction−baseline)/(1−baseline), 0, 1) — exactamente como spec §5.4
- Estado diagnóstico: last_spectrum, last_freqs, last_hps, last_peak_freq, last_filtered_buf
- Parámetros: lp_cutoff_hz, buf_len, update_n, hps_harmonics (con FW_* como defaults)

`HR3TestWindow`:
- 4 plots: FFT+HPS spectrum (con LinearRegionItem rango HR, InfiniteLine peak, curvas cyan/naranja), buffer LP filtrado, HR3 fw/py vs tiempo, SQI fw/py vs tiempo
- Panel derecho: parámetros (LP cutoff, buf_len, update_n, HPS harmonics), botón RESET TO DEFAULTS, tabla de valores (HR3, SQI, peak freq)
- Indicador verde/naranja FIRMWARE DEFAULTS / CUSTOM PARAMS
- Modo offline: carga CSV (CHK y raw), batch process, plot estático
- Export CSV

`PPGMonitor`:
- `self.hr3test_window = None`, `_HR3TEST_REFRESH_EVERY = 5`, `_hr3test_refresh_counter`
- Botón HR3TEST en sidebar (sección TEST, después de HR2TEST)
- `toggle_hr3test()`, `_open_hr3test_default()`
- `_save_settings()`: hr3test_open
- `showEvent()`: restaura hr3test si estaba abierto
- `_bring_all_to_front()`: incluye hr3test_window
- `update_data()`: bloque de refresco HR3TEST cada 5 ticks (≈10 Hz), pasa data_ir_sub, data_hr3, data_hr3_sqi

**Nota técnica (CSV parsing):**
- CHK format: parts[18]=HR3, parts[19]=HR3SQI (tras split del raw $M1 frame)
- Raw CSV format: row[offset+17]=HR3, row[offset+18]=HR3SQI (offset=3, raw CSV cols 0..21)

**Estado final:** Las 4 ventanas TEST están completas e integradas. ppg_plotter.py ~5870 líneas, pasa py_compile sin errores.

---

## Sesión 2026-04-09 — Instrumentación de timing (v0.14)

### Objetivo
Implementar la instrumentación de timing para medir el consumo de CPU de los 4 algoritmos (HR1, HR2, HR3, SpO2) y verificar que el ciclo cabe en los 2000 µs del período de muestreo a 500 Hz.

### Decisiones tomadas

**Firmware:**
- Flag `MOW_TIMING_STATS` (compilado in/out, default 0, activo en `platformio.ini` con `-DMOW_TIMING_STATS=1`)
- `TimingStat` struct privada en `MOW_AFE4490` (max_us, sum_us, count, update, mean_us, reset)
- Medición con `esp_timer_get_time()` (resolución 1 µs, ESP-IDF)
- Algoritmos instrumentados en `_process_sample()` con bloques `{ uint64_t _t = ...; algo(); _ts_X.update(...); }`
- Ciclo completo (SPI + todo) instrumentado en `_task_body()` con `_t_cycle` antes del SPI mutex
- `_emit_timing()`: método privado, emite trama `$TIMING` cada `ts_emit_interval=2500` samples (~5 s a 500 Hz), luego resetea todos los acumuladores
- Trama: `$TIMING,hr1_mean,hr1_max,hr2_mean,hr2_max,hr3_mean,hr3_max,spo2_mean,spo2_max,cycle_mean,cycle_max,stack_free*XX`

**ppg_plotter.py:**
- `TimingWindow`: tabla (Algorithm / Mean µs / Max µs / Budget %) + status bar verde/naranja/rojo
- Thresholds: WARN=1800 µs, BUDGET=2000 µs
- Parser `$TIMING` antes de la decimación (con `continue`, se muestra en consola)
- Botón `TIMING` en sidebar (checkable, persistente con QSettings)

**Spec:** actualizada a v0.14 (sección §8.4 añadida, entrada en historial de versiones)

### Estado final
Todos los archivos modificados: `platformio.ini`, `mow_afe4490.h`, `mow_afe4490.cpp`, `ppg_plotter.py`, `mow_afe4490_spec.md`. Pendiente: compilar + flashear y leer primeras tramas `$TIMING`.

---

## Sesión 2026-04-09 — Fixes ppg_plotter.py post-timing (v0.14 patch)

### Cambios
- **`closeEvent` añadido a 5 ventanas** (SpO2TestWindow, HR1TestWindow, HR2TestWindow, HR3TestWindow, TimingWindow): al cerrar con la X el botón del sidebar se desactiva y la referencia en PPGMonitor se pone a None
- **TimingWindow más alta**: `resize(480, 340)` en lugar de 260 (5 filas visibles sin scroll)
- **Tabla TimingWindow copiable**: selección `ContiguousSelection` + `keyPressEvent` con `Ctrl+C` copia celdas seleccionadas como TSV

---

## Sesión 2026-04-09 — TimingWindow resize 340→400

- `resize(480, 400)` para que la última fila de la tabla sea visible.

---

---

## Sesión 2026-04-09 — Async HR2/HR3 tasks (v0.14 async split)

### Contexto
Las mediciones de timing con `MOW_TIMING_STATS` mostraron que en el frame en que coinciden HR2 autocorrelación (~3885 µs max) y HR3 FFT (~1657 µs max), el ciclo completo superaba los 5945 µs (casi 3× el presupuesto de 2000 µs). La causa es estructural: ambos algoritmos se ejecutaban síncronamente en la tarea de muestreo a 500 Hz.

### Decisión de diseño
Separar HR2 y HR3 en tareas FreeRTOS independientes (prio 4, una prioridad por debajo de la tarea de muestreo a prio 5). La tarea de muestreo (Task A) solo ejecuta el camino rápido (filtrar + decimarı + buffer), y señaliza las tareas lentas cuando hay un nuevo intervalo disponible. Las tareas lentas (Task B para HR2, Task C para HR3) bloquean en un semáforo binario y solo se activan cada ~0.5 s.

### Patrón skip-if-busy
Si Task B/C todavía está computando cuando llega el siguiente intervalo, Task A salta (`if (!_hrX_computing)`) — no bloquea, no hace cola, simplemente descarta ese intervalo. La frecuencia de actualización de HR2/HR3 es 0.5 s, no hace falta actualizarlos más rápido.

### Cambios en mow_afe4490.cpp

**HR2 — split en 4 funciones:**
- `_update_hr2_sample()`: camino rápido (biquad BPF + decimación + circular buffer), devuelve `true` cuando el intervalo se dispara
- `_linearize_hr2()`: copia el buffer circular en `_hr2_seg` (snapshot linealizado, bajo `_state_mutex`)
- `_compute_hr2()`: autocorrelación sobre `_hr2_seg` → `_hr2_result`/`_hr2_sqi_result` (sin mutex, solo lee `_hr2_seg`)
- `_update_hr2()`: wrapper síncrono mantenido para compatibilidad con unit tests

**HR3 — split en 4 funciones (mismo patrón):**
- `_update_hr3_sample()`: camino rápido (biquad LPF + decimación + circular buffer), devuelve `true` cuando el intervalo se dispara
- `_linearize_hr3()`: DC removal + ventana Hann → `_hr3_fft[]` (bajo `_state_mutex`)
- `_compute_hr3()`: FFT radix-2 + HPS + interpolación parabólica sobre `_hr3_fft` → `_hr3_result`/`_hr3_sqi_result`
- `_update_hr3()`: wrapper síncrono mantenido para compatibilidad con unit tests

**Tareas FreeRTOS añadidas:**
- `_hr2_task_trampoline()` / `_hr2_task_body()`: bloquea en `_hr2_calc_sem`, llama `_compute_hr2()`, escribe resultados bajo `_state_mutex`, limpia `_hr2_computing`
- `_hr3_task_trampoline()` / `_hr3_task_body()`: mismo patrón para HR3

**`_process_sample()` actualizado:** reemplazadas las llamadas directas `_update_hr2/hr3()` por el patrón fast-path + signal:
```cpp
if (_update_hr2_sample(led1_aled1)) {
    if (!_hr2_computing) {
        _linearize_hr2();
        _hr2_computing = true;
        xSemaphoreGive(_hr2_calc_sem);
    }
}
```

### Resultado esperado
Con el split, el `cycle_max` en la ventana TIMING debería bajar a < 500 µs. Los valores de HR2/HR3 en la tabla TIMING miden solo el camino rápido (< 50 µs), no la computación lenta.

### Estado
Compilado y flasheado sin errores. Pendiente: leer primera trama `$TIMING` con plotter para confirmar mejora.


---

## Sesión 2026-04-10 — Precompute Hann window (v0.14 patch)

### Problema
Con el async split, HR3 fast path mostraba max = 819 µs en la ventana TIMING. Causa: `_linearize_hr3()` ejecutaba 512 llamadas a `cosf()` para la ventana Hann en cada frame donde se dispara el intervalo, y eso corre en Task A (ciclo de muestreo).

### Fix
Precomputar la ventana Hann una sola vez en `begin()`, guardada en el nuevo miembro `float _hr3_hann[hr3_buf_len]`. `_linearize_hr3()` ahora solo hace multiply-add sin trigonometría.

**Cambios:**
- `mow_afe4490.h`: añadido `float _hr3_hann[hr3_buf_len]` (2 KB RAM adicionales)
- `mow_afe4490.cpp` — `begin()`: bucle de precomputo `_hr3_hann[i] = 0.5f * (1.0f - cosf(...))` antes de lanzar las tareas
- `mow_afe4490.cpp` — `_linearize_hr3()`: `sample * _hr3_hann[i]` en lugar de `sample * cosf(...)`

### Resultado esperado
- HR3 fast path max: < 50 µs (solo multiply-add)
- Cycle max: < 500 µs


---

## Sesión 2026-04-10 — Task B/C CPU load en ventana TIMING

### Motivación
La columna "Budget %" de la ventana TIMING solo tenía sentido para Task A (tiempo por muestra vs 2 ms). Task B y C (async) no se miden contra ese presupuesto — su métrica correcta es CPU load % = tiempo de cómputo / período de invocación.

### Cambios firmware

**mow_afe4490.h:**
- Añadidos `_ts_hr2_compute` y `_ts_hr3_compute` (tipo `TimingStat`) junto a los stats existentes de Task A

**mow_afe4490.cpp:**
- `_hr2_task_body()`: instrumentado `_compute_hr2()` con `esp_timer_get_time()` (bajo `#if MOW_TIMING_STATS`)
- `_hr3_task_body()`: ídem para `_compute_hr3()`
- `_emit_timing()`: frame extendido de 11 a 15 valores:
  `$TIMING,hr1,hr2fp,hr3fp,spo2,cycle, hr2cmp,hr3cmp, stack_free`
  (cada par = mean_us + max_us)
- `buf[192]` → `buf[256]` para el frame más largo
- Reset de `_ts_hr2_compute` y `_ts_hr3_compute` al emitir

### Cambios ppg_plotter.py

**TimingWindow rediseñada:**
- Título: "TIMING — CPU Budget & Load"
- 9 filas físicas: 1 header + 5 datos Task A + 1 header + 2 datos Task B/C
- Headers de sección con `setSpan()` y estilo azulado
- Task A: columna "Metric" muestra "Budget %" (max / 2000 µs)
- Task B/C: columna "Metric" muestra "CPU load %" (mean / 500 000 µs)
- `update_timing()` acepta ahora 15 parámetros (antes 11)
- Ventana ampliada a 520×490 px

**Parser `$TIMING`:**
- `len(_tp) >= 16` (antes 12)
- `_tp[1:16]` (antes `_tp[1:12]`)


---

## Sesión 2026-04-10 — TimingWindow resize 520x490 → 640x980

- `self.resize(640, 980)` — un poco más ancha y el doble de alta.


---

## Sesión 2026-04-10 — FreeRTOS task CPU% en ventana TIMING ($TASK frames)

### Motivación
El usuario quería ver el consumo de CPU de todas las tareas de la librería (A, B, C) para estimar el impacto al integrarla en IncuNest.

### Enfoque elegido
`uxTaskGetSystemState()` requiere `configUSE_TRACE_FACILITY=1` en FreeRTOS, pero Arduino ESP32 usa una librería FreeRTOS precompilada que no lo activa — no se puede cambiar sin recompilar el framework. Solución: calcular CPU% directamente desde los `sum_us` ya medidos por los `TimingStat` existentes.

### CPU% por tarea (intervalo actual, no acumulado desde boot)
- `mow_afe4490` (Task A): `_ts_cycle.sum_us / window_us × 100`
- `mow_hr2` (Task B): `_ts_hr2_compute.sum_us / window_us × 100`
- `mow_hr3` (Task C): `_ts_hr3_compute.sum_us / window_us × 100`
- `window_us = ts_emit_interval * 1,000,000 / sample_rate_hz = 5,000,000 µs`

### Tramas emitidas (al final de cada ciclo de $TIMING)
```
$TASK,mow_afe4490,cpu_pct_x10,stack_words*XX
$TASK,mow_hr2,cpu_pct_x10,stack_words*XX
$TASK,mow_hr3,cpu_pct_x10,stack_words*XX
$TASKS_END*XX
```
`cpu_pct_x10` = CPU% × 10 (entero, resolución 0.1%). `stack_words` = `uxTaskGetStackHighWaterMark()`.

**Importante:** `_emit_tasks()` se llama ANTES de `_ts_*.reset()` para leer los `sum_us` del intervalo actual.

### Cambios firmware
- `mow_afe4490.h`: declaración `_emit_tasks()` bajo `#if MOW_TIMING_STATS`
- `mow_afe4490.cpp`: implementación de `_emit_tasks()` con struct `LibTask[]` para las 3 tareas; reordenado el final de `_emit_timing()`: emit_tasks() → resets

### Cambios ppg_plotter.py
- `PPGMonitor.__init__`: añadido `self._pending_tasks = []`
- Parser `$TIMING`: resetea `_pending_tasks = []` al inicio de cada nuevo ciclo
- Parser `$TASK`: acumula `(name, pct_x10, stack)` en `_pending_tasks`
- Parser `$TASKS_END`: llama `timing_window.update_tasks(_pending_tasks)` si la ventana está abierta
- `TimingWindow`: añadida sección "FreeRTOS Tasks" con `QTableWidget` dinámico (filas según número de tareas, ordenadas por CPU% desc), amarillo para tareas ≥ 20% CPU
- `TimingWindow.update_tasks()`: nuevo método que reconstruye la tabla en cada ciclo


---

## Sesión 2026-04-10 — TimingWindow: Ctrl+C en tabla de tareas

- `keyPressEvent` actualizado para copiar de `_tasks_table` además de `_table` (el que tenga selección activa).


---

## Sesión 2026-04-10 — Corrección etiqueta stack (words → bytes)

### Mediciones confirmadas
- mow_afe4490 (Task A): 19.5% CPU, 5640 bytes stack libre (de 8192)
- mow_hr2 (Task B): 1.1% CPU, 1772 bytes libre (de 3072)
- mow_hr3 (Task C): 0.4% CPU, 1176 bytes libre (de 2048) ← más ajustado
- **Total librería: ~21% CPU de un core**

### Corrección
`uxTaskGetStackHighWaterMark()` en ESP32 devuelve **bytes** (no words), porque el puerto Xtensa usa `portSTACK_TYPE = uint8_t`. Corregida la cabecera de la tabla en ppg_plotter.py: "Stack (words)" → "Stack free (bytes)". Añadida nota en mow_afe4490.h.

### Nota de integración
mow_hr3 usa 57% del stack (2048 bytes). Considerar subir `MOW_AFE4490_HR3_TASK_STACK` a 3072 al integrar en IncuNest si se añaden más llamadas en ese contexto.


---

## Sesión 2026-04-10 — TimingWindow: etiquetas Task A/B/C en tabla de tareas

- Añadido `_TASK_LABELS` dict en `TimingWindow`: `mow_afe4490 (Task A)`, `mow_hr2 (Task B)`, `mow_hr3 (Task C)`.
- `update_tasks()` usa `_TASK_LABELS.get(name, name)` para mostrar el nombre enriquecido.


---

## Sesión 2026-04-10 — Análisis de corriente LED y parámetros AFE4490

**Revisión de la corriente LED por defecto (11.7 mA):**
- El valor provenía de Protocentral (código DAC 20, TX_REF=0.75V, RANGE_0).
- Decisión: los valores de Protocentral no son fuente fiable. La única referencia válida es el datasheet del AFE4490.
- Además, la corriente real calculada con TX_REF=0.75V + LEDRANGE=0 es ~5.9 mA (full scale = 75 mA), no 11.7 mA como se asumía.

**Añadida tarea pendiente:** análisis de sensibilidad de corriente LED (LED1/LED2), ganancia TIA (RF) y ganancia etapa 2, basado en el datasheet del AFE4490.

---

## Sesión 2026-04-10 — Correcciones examples/basic/main.cpp

- Añadido `// Author: Medical Open World` en la cabecera del fichero.
- Añadido bloque HR3 (FFT + HPS) en `ReaderTask()`, con el mismo patrón de SQI guard que HR1 y HR2.

---

## Sesión 2026-04-10 — Versión en examples/basic/main.cpp

- Corregida versión de `v0.7` a `v0.14` en la cabecera del fichero (estaba desactualizada).

---

## Sesión 2026-04-10 — Cabecera examples/basic/main.cpp

- Ampliado comentario de spec: `// Spec: mow_afe4490_spec.md  — full design specification, register map and algorithm details`

---

## Sesión 2026-04-10 — Cabecera examples/basic/main.cpp (versión)

- Cambiado `// v0.14 — ESP32-S3...` por `// Library version: v0.14 — ESP32-S3...` para indicar explícitamente que el número corresponde a la versión de la librería.

---

## Sesión 2026-04-10 — Cabecera examples/basic/main.cpp (spec)

- Revertida descripción de spec: eliminado `— full design specification, register map and algorithm details`, dejado solo `// Spec: mow_afe4490_spec.md`.

---

## Sesión 2026-04-10 — Cabecera examples/basic/main.cpp (autor)

- Ampliada línea de autor: `// Author: Medical Open World — http://medicalopenworld.org — contact@medicalopenworld.org`

---

## Sesión 2026-04-10 — Cabecera examples/basic/main.cpp (email entre ángulos)

- Email del autor puesto entre ángulos: `<contact@medicalopenworld.org>` (convención estándar en cabeceras de código).

---

## Sesión 2026-04-10 — Sincronización cabeceras librería

- Añadidas líneas `Library version:` y `Author:` en `mow_afe4490.h` y `mow_afe4490.cpp` para sincronizar con `examples/basic/main.cpp`.
- Los tres ficheros tienen ahora la misma cabecera estándar: versión, spec y autor con web y email.

---

## Sesión 2026-04-10 — examples/basic/main.cpp: SQI siempre visible

- Añadido `(SQI: x.xx)` tras cada valor (SpO2, HR1, HR2, HR3), siempre impreso independientemente de si el valor es válido o no.
- Formato: `SpO2: 98.0 % (SQI: 0.85)  HR1: 72 bpm (SQI: 0.91) ...`

---

## Sesión 2026-04-10 — ppg_plotter.py: cierre de ventanas TEST al cerrar ventana principal

- Bug: al cerrar la ventana principal, las ventanas SPO2TEST, HR1TEST, HR2TEST, HR3TEST y TimingWindow no se cerraban.
- Fix: añadidas en `closeEvent` de `PPGMonitor` las llamadas a `.close()` para `spo2test_window`, `hr1test_window`, `hr2test_window`, `hr3test_window` y `timing_window`.

---

## Sesión 2026-04-10 — System info ESP32 al arranque + botón RESET en plotter

### Preguntas clave
- ¿LED1_ALED1 es siempre igual a LED1 − ALED1? (pregunta planteada, no implementada aún)
- ¿Cómo resetear el ESP32 con el script en ejecución sin conflictos de puerto?

### Decisiones tomadas
- El ESP-Prog (FT2232HL) actúa como bridge UART: el puerto serie no se cierra al resetear el ESP32. No hay conflicto.
- El circuito auto-reset del ESP-Prog conecta RTS→EN y DTR→IO0, igual que esptool.py.
- Protocolo acordado: el firmware emite `# SYS: <info>` en setup(); el plotter detecta ese prefijo y lo muestra en el log principal vía `set_status()`.

### Cambios implementados
**`examples/basic/main.cpp`**:
- Añadidos `#include <esp_chip_info.h>` y `#include <esp_mac.h>`
- En `setup()`, tras `mow.begin()`: 4 líneas `# SYS:` con chip rev/cores/MHz, Flash/PSRAM, Heap/IDF version, MAC address.

**`ppg_plotter.py`**:
- Parser de `#` lines: añadida rama `elif line.startswith('# SYS:')` → `set_status(..., "info")`.
- Botón **RESET ESP32** en sidebar (después de CONNECT), estilo naranja. Llama a `_reset_esp32()`.
- Método `_reset_esp32()`: toggle RTS/DTR via pyserial (dtr=False, rts=True → sleep 100ms → rts=False, dtr=True).

---

## Sesión 2026-04-10 — Fix botón RESET ESP32: bootloader mode

### Bug
Al pulsar RESET ESP32, el ESP32 arrancaba en modo bootloader y dejaba de enviar datos.

### Causa
La última línea del método `_reset_esp32()` ponía `dtr = True`, lo que a través del transistor del ESP-Prog tiraba IO0 a LOW → bootloader mode.

### Fix
Eliminada la línea `self.ser.dtr = True`. DTR permanece en False durante todo el reset → IO0 queda HIGH → firmware normal arranca correctamente.

Secuencia correcta: `dtr=False, rts=True` → sleep 100ms → `rts=False` (DTR no se toca).

---

## Sesión 2026-04-10 — Fix: # SYS: estaba en fichero incorrecto (examples/ vs src/)

### Bug
Las líneas `# SYS:` no aparecían porque los cambios se habían hecho en `examples/basic/main.cpp`, que es solo documentación. El firmware compilado por PlatformIO es `src/main.cpp`.

### Fix
- Añadidos `#include <esp_chip_info.h>` y `#include <esp_mac.h>` en `src/main.cpp`.
- Añadido bloque `# SYS:` en `setup()` de `src/main.cpp`, tras `Serial.begin(921600)`.
- Los cambios equivalentes en `examples/basic/main.cpp` se mantienen como documentación del ejemplo.

### Nota
El firmware en `src/main.cpp` usa 921600 baud (no 115200), tiene `Serial_printf()` propio y no tiene `while (!Serial)`. Las líneas `# SYS:` se emiten justo tras `Serial.begin()`, antes de `SPI.begin()` y `start_mow()`.

---

## Sesión 2026-04-10 — Limpieza examples/basic/main.cpp

- Eliminado el bloque Step 4 (# SYS:) y los includes `esp_chip_info.h` / `esp_mac.h` que se habían añadido por error en `examples/basic/main.cpp`.
- El ejemplo queda limpio: solo muestra el uso básico de la librería, sin dependencias del sistema de diagnóstico del plotter.

---

## Sesión 2026-04-10 — ppg_plotter: aumento de fuente en stats_table

### Cambio
Aumentados los tamaños de fuente en la tabla de estadísticas (`stats_table`) de `ppg_plotter.py`:
- **Header (títulos de columna):** `22px → 44px` (×2)
- **Celdas (datos):** `22px → 33px` (×1.5)

### Restricción
La altura de las filas (`setDefaultSectionSize(40)`) no se ha modificado.

---

## Sesión 2026-04-10 — ppg_plotter: ajuste fino de fuente en stats_table

### Cambio
Ajustados los tamaños de fuente en `stats_table` de `ppg_plotter.py`:
- **Header (títulos de columna):** `44px → 22px` (−50%)
- **Celdas (datos):** `33px → 26px` (−20%)

---

## Sesión 2026-04-10 — ppg_plotter: ajuste título stats_table +50%

### Cambio
- **Header (títulos de columna):** `22px → 33px` (+50%)
- Celdas sin cambio (`26px`)

---

## Sesión 2026-04-10 — ppg_plotter: HR3LAB HPS normalizado a banda HR

### Cambio
En `HR3LabWindow.update_plots` (`ppg_plotter.py`): el HPS se normalizaba al máximo global del array. Corregido para normalizar al máximo dentro de la banda HR (`HR_SEARCH_MIN_HZ`–`HR_SEARCH_MAX_HZ`), igual que hace `HR3TestCalc`.

El espectro FFT ya estaba correcto (normalizado a HR-band max desde `HRFFTCalc.update`).

### Análisis adicional (sin cambios de código)
Se analizó por qué `hr3_sqi` es sistemáticamente bajo (< 0.3):
- El denominador `power_sum` del SQI incluye los bins armónicos (2°, 3°) que caen dentro del rango de búsqueda [22–303 BPM]
- Para FC 60–180 BPM, los armónicos 2° y 3° están bien dentro del paso del LP (< 10 Hz) y contribuyen 20–40% de la energía espectral
- Esto infla el denominador estructuralmente, deprimiendo `fraction` y el SQI resultante
- Opciones de mejora: SQI basado en el espectro HPS (opción A, recomendada), exclusión de bins armónicos del denominador (opción B), o SNR local (opción C)
- Pendiente decisión del usuario sobre qué opción implementar

---

## Sesión 2026-04-10 — HR3 SQI v0.15: HPS peak prominence

### Problema identificado
El `hr3_sqi` era sistemáticamente bajo (< 0.3) porque el denominador `power_sum` acumulaba la potencia lineal P[k] de todos los bins del rango de búsqueda [22–303 BPM], incluyendo los armónicos 2° y 3° de la señal PPG. Como estos caen dentro del paso del filtro LP (< 10 Hz) y dentro del rango de búsqueda, inflaban el denominador estructuralmente aunque la señal fuese buena.

### Solución implementada (Opción A)
SQI calculado en el dominio HPS en lugar del espectro lineal:
- `fraction = HPS[peak_bin] / Σ HPS[k]` en lugar de `P[peak_bin] / Σ P[k]`
- En el dominio HPS, solo el bin fundamental acumula potencia de los tres armónicos simultáneamente → el pico domina naturalmente la suma HPS cuando la señal es periódica
- Sin buffer nuevo: `hps_sum` se acumula en el bucle existente (4 bytes de stack adicionales)

### Ficheros modificados
- `mow_afe4490.cpp`: `_compute_hr3()` — `power_sum` → `hps_sum`, SQI formula actualizada
- `mow_afe4490.h`: comentario `hr3_sqi` actualizado
- `ppg_plotter.py`: `HR3TestCalc` — SQI formula y docstring actualizados
- `mow_afe4490_spec.md`: §5.4 reescrito, versión v0.14 → v0.15, changelog añadido

---

## Sesión 2026-04-10 — ppg_plotter: guardado periódico de geometría de todas las ventanas

### Problema
La geometría de las ventanas solo se guardaba en `closeEvent`. Al matar el proceso con `taskkill`, ese evento no se dispara y las posiciones/tamaños se pierden.

### Solución
`PPGMonitor._save_settings()` ya corría cada 10 s pero solo guardaba la geometría de la ventana principal. Se extendió para guardar también la geometría de todos los subwindows abiertos.

Adicionalmente, 5 ventanas que nunca habían tenido save/restore de geometría se actualizaron:
- `SpO2TestWindow`, `HR1TestWindow`, `HR2TestWindow`, `HR3TestWindow`: restore añadido al final de `__init__`, save añadido en `closeEvent`.
- `TimingWindow`: `self.resize(640, 980)` sustituido por restore+default, save añadido en `closeEvent`.

### Resultado
Todas las 11 ventanas del script persisten su geometría:
- Al cerrar correctamente: vía `closeEvent`.
- Al matar con taskkill: vía el timer de 10 s en `_save_settings()`.

---

## Sesión 2026-04-10 — Fix: HR3TestCalc spec_hr undefined tras refactor SQI

### Bug
Al refactorizar el bloque SQI de `HR3TestCalc.update()` para usar HPS en lugar del espectro lineal, se eliminó por error la línea `spec_hr = spectrum[mask]`. La sección de normalización para display (línea `spec_max = float(np.max(spec_hr))`) seguía referenciando `spec_hr`, causando `NameError` en cada ciclo de cálculo. Efecto: FFT plot parado, HR no calculado, plot temporal congelado.

### Fix
Añadida de nuevo `spec_hr = spectrum[mask]` al inicio del bloque SQI en `HR3TestCalc.update()`.

---

## Sesión 2026-04-11 — Diseño offline runner (spec v0.16)

### Contexto
Las incubadoras Incunest enviarán ficheros CSV de 10 s / 500 Hz con las 6 señales brutas del AFE4490 a un repositorio Google Drive. El objetivo es pasar esos ficheros por los algoritmos HR1/HR2/HR3/SpO2 para calibrar y mejorar el firmware.

### Opciones evaluadas
- **Opción 1 (ESP32 + serie):** posible en batch pero requiere hardware físico siempre conectado.
- **Opción 2 (C++ nativo):** seleccionada. Los algoritmos HR1/HR2/HR3 son C++ puro, sin Arduino ni FreeRTOS. Coste de setup mínimo.
- **Opción 3 (Python):** descartada por riesgo de divergencia respecto al firmware (ya ha ocurrido con HR3 SQI).

### Decisiones de diseño

**Formato CSV de entrada**
- Formato propio de Incunest, variable entre versiones de firmware.
- Siempre contiene las 6 señales brutas con nombres: `RED`, `IR`, `AmbRED`, `AmbIR`, `REDSub`, `IRSub`.
- El parser detecta columnas **por nombre** (no por posición). Columnas extra ignoradas.

**Columnas opcionales de firmware**
- Si el CSV incluye `FW_HR1`, `FW_HR2`, `FW_HR3`, `FW_SpO2`, se añaden columnas `delta_*` al resultado.
- Propósito: comprobar equivalencia firmware ↔ runner, no calibración.

**Flag `MOW_OFFLINE`**
- Nueva flag de compilación que sustituye includes de Arduino/SPI/FreeRTOS por `mow_offline_platform.h`.
- Deshabilita `begin()`, `stop()`, `getData()`, ISR y tareas FreeRTOS.
- Activa implícitamente `UNIT_TEST` → expone `test_feed_*` / `test_hr*`.
- Requiere mover precálculo de la ventana Hann de `begin()` a `_reset_algorithms()`.

**Estructura de ficheros**
```
tools/offline_runner/
  CMakeLists.txt
  main.cpp
  mow_offline_platform.h
```

**Salidas**
- `<basename>_result.csv` por fichero (muestra a muestra)
- `batch_summary.csv` acumulativo (estadísticas por fichero)

### Cambios especificados (sin implementar aún)
- `mow_afe4490_spec.md` v0.15 → v0.16: añadida §9 completa con diseño del runner.
- Pendiente de implementar: cambios en `.h`/`.cpp` y ficheros `tools/`.

### Nota
Todo lo relativo al runner queda documentado en `mow_afe4490_spec.md` §9 como parte permanente de la spec.

---

## Sesión 2026-04-11 — MOW_OFFLINE guards en mow_afe4490.h y mow_afe4490.cpp

### Tema
Añadir soporte al flag de compilación `MOW_OFFLINE` en la librería `mow_afe4490`.

### Cambios implementados

**`mow_afe4490.h`**
- Sustituidos los includes de plataforma por bloque `#ifdef MOW_OFFLINE / #else / #endif` que incluye `mow_offline_platform.h` (y fuerza `UNIT_TEST`) o los includes normales de Arduino/FreeRTOS.
- Guardados con `#ifndef MOW_OFFLINE` los métodos públicos `begin()`, `stop()`, `getData()` y `_drdy_isr()`.
- Guardados con `#ifndef MOW_OFFLINE` los métodos privados de hardware: SPI primitivos (`_write_reg`, `_read_spi_raw`, `_read_reg`), chip init (`_chip_init`, `_apply_timing_regs`, `_apply_analog_regs`, `_apply_control_regs`, `_build_tiagain`), FreeRTOS tasks (`_task_trampoline`, `_task_body`, `_hr2_task_trampoline`, `_hr2_task_body`, `_hr3_task_trampoline`, `_hr3_task_body`), ISR (`_drdy_isr_static`), y static `_g_instance`.

**`mow_afe4490.cpp`**
- `esp_log.h` guardado con `#ifndef MOW_OFFLINE`; `esp_timer.h` con `#if MOW_TIMING_STATS && !defined(MOW_OFFLINE)`.
- Añadido bloque `#ifdef MOW_OFFLINE` para `TAG` + macros `ESP_LOGE/I/W` como `((void)0)`.
- `MOW_AFE4490::_g_instance = nullptr` guardado con `#ifndef MOW_OFFLINE`.
- Cuerpo del destructor guardado con `#ifndef MOW_OFFLINE` (destructor vacío bajo offline).
- Hann window precomputation movida de `begin()` a `_reset_algorithms()`.
- `begin()` completo guardado con `#ifndef MOW_OFFLINE`.
- Constructor ahora llama `_reset_algorithms()` al final (precomputa la ventana Hann también en construcción).
- `getData()` y `stop()` guardados con `#ifndef MOW_OFFLINE`.
- SPI primitivos y chip-init functions (`_write_reg` .. `_apply_control_regs`) en un bloque `#ifndef MOW_OFFLINE`.
- `_task_trampoline`, `_task_body`, `_drdy_isr_static`, `_drdy_isr` en un bloque `#ifndef MOW_OFFLINE`.
- Block `#if MOW_TIMING_STATS` de `_emit_timing`/`_emit_tasks` cambiado a `#if MOW_TIMING_STATS && !defined(MOW_OFFLINE)`.
- Setters de hardware (`setSampleRate`, `setNumAverages`, `setLED1Current`, `setLED2Current`, `setLEDRange`, `setTIAGain`, `setTIACF`, `setStage2Gain`): bloques `if (_initialized) xSemaphoreTake(_spi_mutex, ...)` y `if (_initialized) { _apply_*; xSemaphoreGive(...); }` guardados con `#ifndef MOW_OFFLINE`.
- `_hr2_task_trampoline`/`_hr2_task_body` y `_hr3_task_trampoline`/`_hr3_task_body` guardados con `#ifndef MOW_OFFLINE`.

### Decisiones clave
- `setSpO2Coefficients` y los demás setters de algoritmo (`setPPGChannel`, `setFilter`, `setHR2Filter`, `setHR3Filter`) no se tocan: sus `xSemaphoreTake/Give(_state_mutex, ...)` son condicionales a `_initialized` (siempre false en offline) y compilarán con los stubs de `mow_offline_platform.h`.
- `_sign_extend_22`, `_recalc_rate_params`, `_recalc_biquad`, `_recalc_biquad_lp`, `_biquad_process`, `_process_sample`, `_update_*`, `_linearize_*`, `_compute_*`, `_reset_algorithms` se dejan siempre activos (son los algoritmos puros que el runner offline necesita).


---

## Sesión — 2026-04-11

### Tema: Preguntas sobre señales AFE4490 y gestión de tareas pendientes

### Preguntas y respuestas clave

- **¿Qué señal usa cada algoritmo HR?** — Los tres (HR1, HR2, HR3) usan `LED1_ALED1` (IR con corrección de ambiental). Pre-procesado distinto: HR1 MA 5 Hz, HR2 BPF 0.5–5 Hz + decimate ×10, HR3 LPF 10 Hz + decimate ×10.
- **¿Cómo confirmar que LED1 = IR?** — Tres fuentes: (1) datasheet AFE4490 (SBAS491, p.18), (2) código ProtoCentral (`IRtemp = afe44xxRead(LED1VAL)`), (3) comentarios en `mow_afe4490.h:50`.
- **¿Qué es la detección de dedo?** — No existe un algoritmo propio. Es implícita: umbral DC (`spo2_min_dc = 1000` cuentas ADC) en SpO2, y PI < umbral → SQI = 0.
- **¿Hay verificación de que `LED1_ALED1 == LED1 - ALED1`?** — No. El chip hace la resta internamente (registro 0x2F) y se usa tal cual sin comparar con la resta software.

### Decisiones y cambios

- **TODO.md** — Añadidas tres tareas nuevas:
  - Actualizar `mow_afe4490_spec.md` §6 con arquitectura async FreeRTOS.
  - Probe presence detection (módulo explícito, genérico/configurable).
  - Utilizar registro DIAG (0x30) para diagnosticar estado del sistema/sonda.
- **Regla de workflow** — Las tareas pendientes van siempre en `TODO.md`, no en la memoria persistente de Claude.
- **Memoria** — Corregido `project_limb_detection_task.md` (eliminada referencia a tobillo neonatal; la librería es agnóstica al sitio anatómico).

### Añadido tras primera actualización de sesión

- **¿Hay verificación de `LED1_ALED1 == LED1 - ALED1` en ppg_plotter.py?** — No. El plotter recibe `IRSub`/`REDSub` como campos de trama y los acepta sin calcular la resta por su cuenta. Queda como posible tarea de diagnóstico futura.
- **Gestión de tareas pendientes** — Corregido el workflow: las tareas van siempre en `TODO.md`, no en la memoria persistente de Claude. Regla guardada en `feedback_general.md`.

---

## Sesión 2026-04-11 — Implementación offline runner + corrección spec

### Corrección de la spec (mow_afe4490_spec.md v0.16)
Errores de numeración corregidos:
- `### 9.5 ADC Averaging` dentro de §7 → `### 7.1`
- `### 8.4 TIMING window` flotando tras version history → devuelta a §8
- Tres secciones `## 9.` → renumeradas: offline runner=§9, version history=§10, chip registers=§11, bibliography=§12
- Version history reordenada descendente (v0.16 → v0.1)

### Ficheros creados/modificados

- `lib/mow_afe4490/mow_afe4490.h` — guards `#ifdef MOW_OFFLINE` en includes y declaraciones de hardware
- `lib/mow_afe4490/mow_afe4490.cpp` — guards en funciones hardware; ventana Hann movida a `_reset_algorithms()`; macros ESP_LOG como no-ops
- `tools/offline_runner/mow_offline_platform.h` (nuevo) — stubs FreeRTOS + Arduino
- `tools/offline_runner/CMakeLists.txt` (nuevo) — C++17, sin deps externas, linkado estático Windows
- `tools/offline_runner/main.cpp` (nuevo) — parser CSV por nombre de columna, batch processing, result CSV + batch_summary.csv
- `.gitignore` — añadido `tools/offline_runner/build/` y ficheros generados

### Prueba
Señal sintética 1.2 Hz (72 BPM), 5000 muestras: HR1=72.7 BPM, HR2=72.3 BPM ✓

### Uso
```
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build
build/mow_offline_runner.exe fichero.csv
build/mow_offline_runner.exe directorio/
```

---

## Sesión 2026-04-11 — Renombrado mow_afe4490_platform_stub.h

### Cambio
`mow_offline_platform.h` renombrado a `mow_afe4490_platform_stub.h`.

### Motivo
- Prefijo `mow_afe4490_` es coherente con el resto de la librería
- `_stub` es el término técnico estándar para implementación vacía que sustituye a la real
- `platform` describe con precisión qué se stubs (Arduino + FreeRTOS), más preciso que `offline`

### Ficheros actualizados
- `lib/mow_afe4490/mow_offline_platform.h` → `lib/mow_afe4490/mow_afe4490_platform_stub.h`
- `lib/mow_afe4490/mow_afe4490.h` — include actualizado
- `mow_afe4490_spec.md` — todas las referencias actualizadas


---

## Sesión 2026-04-11 — Corrección comentario en mow_afe4490_platform_stub.h

### Cambio
Corrección menor: el comentario de cabecera en `mow_afe4490_platform_stub.h` línea 2 aún tenía el nombre antiguo `mow_offline_platform.h`. Actualizado a `mow_afe4490_platform_stub.h`.

### Fichero actualizado
- `lib/mow_afe4490/mow_afe4490_platform_stub.h` — comentario de cabecera corregido

---

## Sesión 2026-04-11 — Firma estándar de cabecera en todos los ficheros de la librería

### Cambio
Aplicada firma estándar de 4 líneas en todos los ficheros de código del proyecto, y corregida la versión v0.14 → v0.16 en los ficheros que estaban desactualizados.

### Ficheros actualizados
- `lib/mow_afe4490/mow_afe4490_platform_stub.h` — firma estándar añadida (v0.16), comentario descriptivo anterior eliminado
- `lib/mow_afe4490/mow_afe4490.h` — v0.14 → v0.16
- `lib/mow_afe4490/mow_afe4490.cpp` — v0.14 → v0.16
- `tools/offline_runner/main.cpp` — firma estándar aplicada (v0.16), línea Build eliminada

### Regla
Todo fichero de código nuevo debe incluir la firma de 4 líneas desde su creación. Al subir versión, actualizar todos los ficheros afectados. Guardado en memoria persistente.

---

## Sesión 2026-04-11 — Correcciones menores offline runner y ppg_plotter

### Cambios en ppg_plotter.py
Persistencia de geometría añadida a todas las ventanas TEST y herramientas que la tenían pendiente: SpO2TestWindow, HR1TestWindow, HR2TestWindow, HR3TestWindow, TimingWindow. Además, PPGMonitor._save_settings() guarda geometría de todas las subventanas abiertas para que sobrevivan a taskkill.

### Cambios en tools/offline_runner/main.cpp
- Firma estándar de 4 líneas aplicada al encabezado del fichero.
- Fix parser CSV: las líneas `#` (metadatos) ahora se descartan correctamente también **antes de la cabecera**. Anteriormente solo se descartaban en el bucle de datos. El fix usa un `while(getline)` que salta líneas vacías y `#` hasta encontrar la primera línea de cabecera real.

### Cambios en lib/mow_afe4490/ y herramientas
- Versión v0.14 → v0.16 corregida en mow_afe4490.h y mow_afe4490.cpp.
- mow_afe4490_platform_stub.h: comentario de cabecera corregido (nombre antiguo → nuevo) y firma estándar de 4 líneas aplicada.

### Regla nueva guardada en memoria
Todo fichero de código nuevo debe incluir la firma estándar de 4 líneas desde su creación.

---

## Sesión 2026-04-11 — Refactor set_status → log() en ppg_plotter.py

### Pregunta clave
¿Tiene sentido la función `set_status()`? ¿El script tiene un "estado"?

### Decisión
No — la función no gestiona ningún estado. Es un `log_panel.append()` con timestamp y color. El nombre `set_status` era engañoso. Se renombra a `log()` y se elimina el parámetro `status_type`.

### Cambio en ppg_plotter.py
- `set_status(text, status_type)` → `log(text)`: el nivel se infiere automáticamente a partir de keywords en el texto.
  - `"error"`, `"failed"`, `"cannot"`, `"not connected"`, `"no port"` → error (rojo)
  - `"online"`, `"saved"` → success (verde)
  - `"recording"`, `"paused"` → warning (naranja)
  - resto → info (azul)
- 25 llamadas migradas, cero residuos de `set_status`.

---

## Sesión 2026-04-11 — LabCaptureWindow + offline_runner fixes

### Tema: Nueva funcionalidad de captura controlada de laboratorio

---

**Fix previo commiteado: skip comment/empty lines antes del header CSV en offline_runner**
El parser del offline_runner asumía que la primera línea era siempre el header. Se corrigió para saltar líneas vacías y líneas `#` antes del header. Commit `85b1be5`.

---

**Decisión: reemplazar "SAVE RAW (500 Hz)" por "CAPTURE LAB"**
El botón antiguo iniciaba la grabación inmediatamente al pulsarse. El nuevo abre una ventana de configuración (`LabCaptureWindow`) antes de capturar. Motivación: las capturas serán enviadas al `mow_offline_runner` para análisis batch — necesitan metadatos y columnas bien definidas.

---

**Diseño de LabCaptureWindow — decisiones clave:**
- **Nombre del botón:** `CAPTURE LAB` (sidebar) / `Lab Capture` (título de ventana).
- **Pre-capture notes:** texto libre escrito como líneas `# comment` ANTES del header CSV. El offline_runner ya las salta (fix `85b1be5`).
- **Post-capture notes:** texto libre escrito como líneas `# comment` DESPUÉS del último dato.
- **Columnas obligatorias** (siempre incluidas, requeridas por offline_runner): `RED, IR, AmbRED, AmbIR, REDSub, IRSub`.
- **Columnas opcionales:** PPG, SpO2→`FW_SpO2`, SpO2SQI, SpO2_R, PI, HR1→`FW_HR1`, HR1SQI, HR2→`FW_HR2`, HR2SQI, HR3→`FW_HR3`, HR3SQI. Las columnas FW_* usan el nombre que espera el offline_runner directamente.
- **Dos modos de captura:** timed (N muestras, spin a su lado) + continuous (hasta STOP).
- **Ventana persiste abierta** tras cada captura para permitir capturas consecutivas.
- **Settings persistidos** en `ppg_plotter.ini` bajo `LabCaptureWindow/`: notas, dir, prefix, spin_samples, checkboxes.
- **Compatibilidad offline_runner total:** CSV generado es procesable por `mow_offline_runner` sin conversión.

---

**Commit:** `b5e92e4` — feat(plotter): replace SAVE RAW with LabCaptureWindow

**Fix 1:** fuentes subidas a 18px — insuficiente.
**Fix 2:** subidas a 20px + `font-size: 20px` en el window stylesheet — no bastó.
**Fix 3:** `_GRP` a 20px + selectores de tipo en todos los controles.
**Fix 4:** texto sigue pequeño + ventana reducida sin pedirlo. Causa: altura 800px insuficiente para el contenido con 22px fonts, Qt comprime el layout. Solución: fonts a 22px, `setMinimumSize(680, 980)`, default `resize(720, 1050)`. Commit `fd14688`.
**Fix 5 (esta sesión):** usuario pidió aumentar fuentes de 22px a 24px y cambiar color/borde de los checkboxes.
- Todos los `font-size:22px` y `font-size: 22px` en `LabCaptureWindow` subidos a 24px: `_GRP`, window-level stylesheet, todos los controles (QPlainTextEdit, QLineEdit, QSpinBox, QLabel, QProgressBar, browse button).
- Checkbox stylesheet actualizado: fondo `#1E2A1E`, borde `1px solid #4A7A4A`, `border-radius:3px`, `padding:3px 6px`. Al estar checked: fondo `#1E3A1E`, borde `#66BB44`.
- Las fuentes en el Stats panel de PPGMonitor (3 líneas a 22px) permanecen a 22px — pertenecen a otra clase.


## Sesión 2026-04-11 — LabCaptureWindow: notas 8 filas

**Cambio:** `setFixedHeight(90)` → `setFixedHeight(250)` en `_pre_notes` y `_post_notes`.
Con fuente 24px Consolas, 250px muestra ~8 filas visibles.


## Sesión 2026-04-11 — LabCaptureWindow: revert notas height

Revertido `setFixedHeight(250)` → `setFixedHeight(90)` en `_pre_notes` y `_post_notes`.
El aumento a 8 filas rompió el layout — se vuelve a 3 filas (90px).


## Sesión 2026-04-11 — LabCaptureWindow: notas 8 filas (v2)

**Cambio:** `setFixedHeight(90)` → `setFixedHeight(250)` en `_pre_notes` y `_post_notes` (+160px × 2 = +320px).
Compensado aumentando `setMinimumSize(680, 980)` → `(680, 1300)` y `resize(720, 1050)` → `(720, 1370)`.
Eliminada geometría guardada de `[LabCaptureWindow]` en `ppg_plotter.ini` para que arranque con el nuevo tamaño.


## Sesión 2026-04-11 — LabCaptureWindow: notas elásticas al redimensionar

`setFixedHeight(250)` → `setMinimumHeight(250)` en `_pre_notes` y `_post_notes`.
`outer.addWidget(grp_pre/grp_post)` → `outer.addWidget(..., stretch=1)` para que absorban el espacio sobrante.
Eliminado `outer.addStretch()` (absorbía el espacio en vez de las notas).
Resultado: al crecer la ventana, Pre/Post-capture notes crecen a partes iguales; el resto de secciones mantienen altura fija.


## Sesión 2026-04-11 — LabCaptureWindow: reorden de secciones

Nuevo orden de secciones en LabCaptureWindow: Output → Capture → Pre-capture notes → Columns → Post-capture notes.
Antes: Pre-notes → Columns → Output → Capture → Post-notes.
Comportamiento elástico de las notas (stretch=1) sin cambios.


## Sesión 2026-04-11 — LabCaptureWindow: Columns grid 3→6 columnas

`grid_cols.addWidget(cb, i // 3, i % 3)` → `i // 6, i % 6`. Los 17 checkboxes se distribuyen en 3 filas × 6 columnas.


## Sesión 2026-04-11 — Uniformidad de nombres de señales + estilo checkboxes

### Nomenclatura de señales — patrón Signal_Metric

Decisión: adoptar patrón `Signal_Metric` con guión bajo como separador, sin excepciones.
Renombrado en `ppg_plotter.py`, `src/main.cpp`, `tools/offline_runner/main.cpp`, `mow_afe4490.h`, `mow_afe4490_spec.md`:

| Antes | Después |
|---|---|
| AmbRED / Amb RED | RED_Amb |
| AmbIR / Amb IR | IR_Amb |
| REDSub / RED sub | RED_Sub |
| IRSub / IR sub | IR_Sub |
| SpO2SQI / SpO2 SQI | SpO2_SQI |
| HR1SQI / HR1 SQI | HR1_SQI |
| HR2SQI / HR2 SQI | HR2_SQI |
| HR3SQI / HR3 SQI | HR3_SQI |

`SpO2_R` ya era correcto — sin cambios.
Inspiración para Amb/Sub: datasheet AFE4490 (ALED2VAL, LED2-ALED2VAL) → señal primero, descriptor después.
Separador `=` elegido para el formato key=value de las notas de captura (robusto, sin ambigüedad de espacios).

### Checkboxes LabCaptureWindow — contraste on/off

Desmarcado: fondo `#1A1A1A`, borde `#3A4A3A`, texto gris `#777777`.
Marcado: fondo `#2A5A2A`, borde `#77CC44`, texto blanco `#E0E0E0`.
Contraste visual claramente diferenciable entre estados.


## Sesión 2026-04-11 — LabCaptureWindow: checkbox estilo verde on/off

Desmarcado: cuerpo `#0E2A0E`, borde `#2A5A2A`, texto gris `#777777`. Indicador `#0E2A0E`.
Marcado: cuerpo `#2A6A2A`, borde `#77CC44`, texto blanco `#FFFFFF`. Indicador `#1A5A1A` + borde `#88EE55`.
Truco para tick blanco: indicador oscuro → Qt elige blanco por contraste automáticamente.


## Sesión 2026-04-11 — LabCaptureWindow: fix tick invisible en checkboxes

Eliminadas las reglas `QCheckBox::indicator` y `QCheckBox::indicator:checked` — al sobreescribir el background del indicador Qt deja de renderizar la marca nativa.
Solución: dejar que Qt dibuje el indicador nativamente; el contraste on/off se logra solo con el cuerpo del checkbox (verde oscuro/gris → verde medio/blanco).


## Sesión 2026-04-11 — LabCaptureWindow: tick blanco en checkboxes via SVG

Problema: al sobreescribir `QCheckBox::indicator` background, Qt deja de renderizar el tick nativo.
Solución: crear `check_white.svg` (polyline blanca, stroke 2.5px) en la raíz del proyecto y referenciarlo con `image: url(check_white.svg)` en `QCheckBox::indicator:checked`.
Indicador final: unchecked=`#0E2A0E` + borde `#3A7A3A`; checked=`#1A5A1A` + borde `#88EE55` + tick blanco SVG.
Cuerpo checkbox: unchecked=verde oscuro/texto gris; checked=`#2A6A2A`/texto blanco.


## Sesión 2026-04-11 — LabCaptureWindow: checkbox clickable en toda su área

Añadida clase `_FullClickCheckBox(QCheckBox)` que sobreescribe `hitButton()` para devolver `self.rect().contains(pos)`.
Causa del problema: en algunos estilos Qt el área de click del QCheckBox se restringe al indicador + texto, ignorando el padding del stylesheet.
Los checkboxes de LabCaptureWindow usan ahora `_FullClickCheckBox` en lugar de `QtWidgets.QCheckBox`.


## Sesión 2026-04-11 — LabCaptureWindow: guardar checkboxes en tiempo real

Bug: `_save_settings` solo se llamaba desde `closeEvent`, que no se ejecuta con `Stop-Process -Force`.
Fix: conectar `cb.stateChanged` → `self._save_settings` en cada checkbox opcional. El ini se actualiza en el momento del cambio, sin depender del cierre de la ventana.


## Sesión 2026-04-11 — Ajustes de fuente varios

- LabCaptureWindow: fuentes 24px → 26px → 28px (ajuste iterativo hasta tamaño definitivo).
- TimingWindow (líneas 4293 y 4303): `_lbl_stack` y cabecera "FreeRTOS Tasks" subidas de 11px a 22px.


## Sesión 2026-04-12 — offline_runner: fix column header matching

Bug crítico: el parser del offline_runner comparaba headers CSV en minúsculas contra los nombres antiguos (`ambred`, `ambir`, `redsub`, `irsub`). Con los nombres nuevos del protocolo nunca encontraba las columnas obligatorias y rechazaba todos los CSV.
Fix: actualizar las 4 strings de comparación → `red_amb`, `ir_amb`, `red_sub`, `ir_sub`.
Los identificadores C++ internos (`amb_red`, `amb_ir`, etc.) se mantienen — son cosmética sin riesgo de error.


## Sesión 2026-04-12 — Consistencia nomenclatura señales + offline_runner

### offline_runner/main.cpp
- Índices renombrados: `idx_amb_red` → `idx_red_amb`, `idx_amb_ir` → `idx_ir_amb`.
- Struct fields renombrados: `amb_red` → `red_amb`, `amb_ir` → `ir_amb`.
- Consistencia total con el protocolo serie y los nombres de columna CSV.

### ppg_plotter.py — _COLS línea 5203
- `"SpO2 R"` → `"SpO2_R"`: inconsistencia con espacio que se escapó en el renombrado masivo.
- La clave ini `check_SpO2_R` no cambia (`.replace(' ','_')` daba el mismo resultado).


## Sesión 2026-04-12 — LabCaptureWindow: prefijo FW_ en columnas opcionales CSV

Todos los opcionales tienen ahora `FW_` en el nombre de columna CSV (segundo elemento de `_COLS`).
Los labels de la UI (checkboxes) se mantienen sin prefijo para legibilidad.
Razón: distinguir valores generados por firmware de los que podría calcular el offline_runner/script.
Columnas afectadas: FW_PPG, FW_SpO2_SQI, FW_SpO2_R, FW_PI, FW_HR1_SQI, FW_HR2_SQI, FW_HR3_SQI.
FW_SpO2, FW_HR1, FW_HR2, FW_HR3 ya tenían el prefijo — sin cambios.


## Sesión 2026-04-12 — LabCaptureWindow: SmpCnt+Ts_us, grid 8 cols, checkbox padding

- Añadidas columnas `SmpCnt`/`FW_SmpCnt` (p[1]) y `Ts_us`/`FW_Ts_us` (p[2]) al inicio de `_COLS` como opcionales. Aparecen primeras visualmente para parecer obligatorias.
- Grid de checkboxes: 6 → 8 columnas (`i // 8, i % 8`). Total 19 checkboxes en 3 filas × 8 cols (última fila incompleta).
- Padding de checkboxes reducido: `3px 6px` → `2px 3px` para que quepan mejor en 8 columnas.
- FW_ en todos los opcionales: política consolidada (FW_SmpCnt, FW_Ts_us, FW_PPG, FW_SpO2_SQI, FW_SpO2_R, FW_PI, FW_HR1_SQI, FW_HR2_SQI, FW_HR3_SQI + los ya existentes FW_SpO2, FW_HR1/2/3).
- Homogeneización en ppg_plotter.py: `data_amb_red/ir` → `data_red_amb/ir_amb`, `curve_amb_red/ir` → `curve_red_amb/ir_amb`.


## Sesión 2026-04-12 — LabCaptureWindow: fix padding checkbox

Padding horizontal: `2px 3px` → `2px 6px`. El texto de `SpO2_SQI` quedaba cortado con 3px.


## Sesión 2026-04-12 — LabCaptureWindow: ancho mínimo checkboxes

`cb.setMinimumWidth(150)` en cada checkbox. El padding interno no controla el ancho total cuando la QGridLayout comprime las celdas — el mínimo fuerza el espacio correcto.


## Sesión 2026-04-12 — LabCaptureWindow: fix padding checkboxes (v2)

Revertido `setMinimumWidth(150)` — forzaba todos los checkboxes demasiado anchos.
Padding horizontal: `6px` → `10px` para que `SpO2_SQI` se muestre completo sin bloquear el ancho.


## Sesión 2026-04-12 — LabCaptureWindow: setMinimumWidth(200) en checkboxes

`cb.setMinimumWidth(200)` — fuerza ancho mínimo suficiente para mostrar "SpO2_SQI" completo con fuente 28px.


## Sesión 2026-04-12 — LabCaptureWindow: ancho ventana para 8 columnas × 180px

`cb.setMinimumWidth(180)` — ancho mínimo por checkbox.
`setMinimumSize(1480, 1300)` y `resize(1480, 1370)` — ventana suficientemente ancha para 8 col × 180px sin solapamiento.
Geometría guardada en ini borrada para que aplique el nuevo tamaño.


## Sesión 2026-04-12 — LabCaptureWindow: setMinimumWidth 180→185

Ajuste fino: `cb.setMinimumWidth(185)`.


## Sesión 2026-04-12 — LabCaptureWindow: ancho ventana 1480→1510

`setMinimumSize(1510, 1300)` y `resize(1510, 1370)` — compensación para 8 × 185px de checkbox.


## Sesión 2026-04-12 — ppg_plotter: color "HPS" en título del gráfico FFT

En `_refresh_fft_plot` (línea ~4159), el texto "HPS" del título del panel FFT ahora se muestra en naranja `#FF8800`, igual que `curve_hps`.


## Sesión 2026-04-12 — ppg_plotter: título dinámico plot SQI en HR3TEST

En `_refresh_hr_plots` de HR3TEST, el título de `p_sqi` ahora muestra los valores instantáneos: `SQI fw: X.XX` en verde (#00CC66, dato firmware) y `py: X.XX` en amarillo (#FFDD44, dato script). Criterio de color verde=firmware / amarillo=script aplicado.


## Sesión 2026-04-12 — ppg_plotter: HR3TEST color peak amarillo

En el primer plot de HR3TEST (FFT+HPS):
- Texto "peak=..." en el título: color `#00FF88` → `#FFDD44` (amarillo = cálculo del script).
- Barra vertical `_peak_line` (pen + labelOpts): color `#00FF88` → `#FFDD44`.
Criterio: todo lo calculado por el script Python usa amarillo `#FFDD44`.


## Sesión 2026-04-12 — ppg_plotter: HR3TEST título segundo plot amarillo

El título del segundo plot (`p_filt`, "LP filtered signal (512-sample buffer)") cambia de gris `#CCCCCC` a amarillo `#FFDD44`, consistente con la curva `FILT_PEN` que ya era amarilla (dato calculado por el script).


## Sesión 2026-04-12 — ppg_plotter: HR3TEST títulos tercer y cuarto plot

- Tercer plot (`p_hr`): el texto "HR3" del título pasa a blanco `#FFFFFF`; " fw: X bpm" sigue en verde, "py: X bpm" en amarillo, Δ en rojo.
- Cuarto plot (`p_sqi`): el texto "SQI" del título pasa a blanco `#FFFFFF`; " fw: X.XX" sigue en verde, "py: X.XX" en amarillo.


## Sesión 2026-04-12 — Análisis: HR3TEST pierde datos con varias ventanas abiertas

**Síntoma reportado:** con varias ventanas abiertas, el pico de la FFT aparece a mayor frecuencia de lo esperado.

**Análisis:** no hay pérdida real de muestras en la cola serie (thread dedicado + queue ilimitada). El problema es de rendimiento: con muchas ventanas abiertas, el QTimer de `update_data()` se retrasa (rendering PyQtGraph en hilo UI único). El `_hr3test_refresh_counter` incrementa UNA VEZ por llamada a `update_data()`, no por muestra. Esto hace que `update_plots()` — y con él `_calc.update()` — se llame menos veces en tiempo real. El usuario percibe saltos grandes en el pico FFT.

**Causa raíz:** `HR3TestCalc._calc.update()` está dentro de `update_plots()`, throttled al refresco de display (10 Hz). Debería correr a 50 Hz independientemente del display.

**Solución diseñada (pendiente de implementar):** mover `_calc.update(ir, SPO2_RECEIVED_FS)` a `update_data()` directamente, antes del bloque de throttle, siguiendo el modelo de HR1TEST (línea ~6649). Display sigue a 10 Hz, cálculo a 50 Hz.



## Sesión 2026-04-12 — Eliminación de la librería Protocentral

**Decisión:** eliminar completamente la librería `protocentral-afe4490-arduino` del proyecto.

**Motivo:** protocentral fue descartada como referencia de validación (calidad algorítmica insuficiente). Solo queda `mow_afe4490` como librería activa.

**Cambios realizados:**
- Borrados: `src/protocentral_afe44xx.cpp`, `src/protocentral_hr_algorithm.cpp`, `src/Protocentral_spo2_algorithm.cpp`, `include/protocentral_afe44xx.h`, `include/protocentral_hr_algorithm.h`, `include/Protocentral_spo2_algorithm.h`, `include/SPO2.h`
- `platformio.ini`: eliminada la dependencia `protocentral-afe4490-arduino.git`
- `src/main.cpp` (v0.8): eliminados todos los objetos, tareas, ISR y comandos de protocentral; eliminado `enum class ActiveLib`; comando `'p'` eliminado; comandos `'1'`/`'2'` ya no requieren condición `ActiveLib::MOW`
- `ppg_plotter.py`: eliminada detección de `"Active library: protocentral"` en el parser serie
- `CLAUDE.md`: actualizado para reflejar que la única librería es `mow_afe4490`


## Sesión 2026-04-13 — SIGNAL STATS: color dinámico HR Mean según SQI

**Cambio:** en la tabla SIGNAL STATS, las celdas "Mean" de HR1, HR2 y HR3 ahora cambian de color dinámicamente según el SQI correspondiente.

- Verde (`#1A5C1A`) si `mean(HR*_SQI) > 0.9` durante el intervalo de stats
- Rojo oscuro (`#5C001A`) en caso contrario (sin datos o SQI insuficiente)

**Implementación:** en `_update_stats_table()`, al refrescar cada celda HR Mean, se calcula el mean del buffer `HR*_SQI` correspondiente y se aplica el color. Constantes de clase: `_STATS_GREEN`, `_STATS_SQI_THRESHOLD = 0.9`.


## Sesión 2026-04-13 — test_hr3: nuevo test unitario para algoritmo HR3

**Cambio:** creado `test/test_hr3/test_hr3.cpp` con 4 tests unitarios para el algoritmo HR3 (FFT + HPS).

**Tests:**
1. `test_hr3_not_valid_until_buffer_full` — SQI=0 si buffer no está lleno (HR3_BUF_RAW/2 = 2560 muestras)
2. `test_hr3_60bpm` — señal multi-armónica a 1 Hz → HR3 converge a 60±5 BPM, SQI>0.7
3. `test_hr3_120bpm` — señal multi-armónica a 2 Hz → HR3 converge a 120±5 BPM, SQI>0.7
4. `test_hr3_flat_signal_invalid` — DC constante → SQI=0

**Decisiones de diseño:**
- Señal de test: fundamental + 2.º + 3.º armónico (no senoidal pura). HPS requiere energía en armónicos; una senoidal pura da HPS≈0 en todos los bins → SQI≈0.
- Macro de aserción: `TEST_ASSERT_GREATER_THAN_FLOAT` (no `TEST_ASSERT_GREATER_THAN`). El macro genérico de Unity castea a UNITY_INT: 0.7f→0 y sqi<1.0→0, haciendo que el test nunca pase. HR3 SQI está siempre clampeado a ≤1.0 (a diferencia de HR2 que no está clampeado y puede ser >1.0).

**Resultado:** 4/4 pasan en entorno native.


## Sesión 2026-04-13 — test_hr1/hr2/hr3: corrección TEST_ASSERT_GREATER_THAN_FLOAT

**Cambio:** en `test_hr1.cpp`, `test_hr2.cpp` y `test_hr3.cpp`, reemplazado `TEST_ASSERT_GREATER_THAN(0.7f, ...)` por `TEST_ASSERT_GREATER_THAN_FLOAT(0.7f, ...)`.

**Motivo:** `TEST_ASSERT_GREATER_THAN` en Unity castea los argumentos a `UNITY_INT` (entero), convirtiendo `0.7f→0` y `sqi→0` para cualquier SQI en [0, 1). HR1 y HR2 pasaban por coincidencia (HR1 SQI es exactamente 1.0f con senoidal perfecta; HR2 SQI no está clampeado y puede ser ≥ 1.0). HR3 expuso el bug latente. La corrección robusta es usar el macro float en todos los tests SQI.


## Sesión 2026-04-13 — test_hr1/hr2/hr3: tests con ruido añadido

**Cambio:** añadidos 2 tests por algoritmo (`_60bpm_noisy`, `_120bpm_noisy`) en test_hr1.cpp, test_hr2.cpp y test_hr3.cpp.

**Señal:** misma que los tests limpios + ruido uniforme ±10% de amplitud (~20 dB SNR). `srand(42)` para reproducibilidad.

**Umbrales:** SQI > 0.3 (vs 0.7 en tests limpios), HR ± 8 BPM (vs ± 5). Verifican que los algoritmos no fallan ante ruido moderado, sin exigir la misma precisión que con señal perfecta.

**Resultado:** 18/18 pasan (6 por algoritmo).


## Sesión 2026-04-13 — test_hr1/hr2/hr3: calibración de umbrales con valores reales

**Contexto:** Los umbrales anteriores (SQI>0.7/0.3, HR±5/8 BPM) eran estimaciones sin datos. Se instrumentó temporalmente cada test con `printf` para capturar los valores reales.

**Valores medidos (señal de test sintética):**

| Algoritmo | Señal       | HR medido | SQI medido |
|-----------|-------------|-----------|------------|
| HR1       | 60bpm clean | 60.00     | 1.0000     |
| HR1       | 120bpm clean| 120.00    | 1.0000     |
| HR1       | 60bpm noisy | 60.02     | 0.9900     |
| HR1       | 120bpm noisy| 120.00    | 0.9761     |
| HR2       | 60bpm clean | 60.06     | 0.8750     |
| HR2       | 120bpm clean| 120.00    | 0.9375     |
| HR2       | 60bpm noisy | 60.04     | 0.8753     |
| HR2       | 120bpm noisy| 119.99    | 0.9374     |
| HR3       | 60bpm clean | 59.40     | 1.0000     |
| HR3       | 120bpm clean| 119.82    | 0.7303     |
| HR3       | 60bpm noisy | 59.40     | 1.0000     |
| HR3       | 120bpm noisy| 119.82    | 0.7287     |

**Nuevos umbrales (margen ~25% respecto al valor medido):**

| Algoritmo | Señal   | SQI (antes→ahora) | HR ±BPM (antes→ahora) |
|-----------|---------|-------------------|-----------------------|
| HR1 clean | ambas   | >0.7 → >0.95      | ±5 → ±1               |
| HR1 noisy | ambas   | >0.3 → >0.80      | ±8 → ±2               |
| HR2 60bpm | clean   | >0.7 → >0.80      | ±5 → ±1               |
| HR2 120bpm| clean   | >0.7 → >0.85      | ±5 → ±1               |
| HR2       | noisy   | >0.3 → >0.75      | ±8 → ±1               |
| HR3 60bpm | ambas   | >0.7/0.3 → >0.95  | ±5/8 → ±2             |
| HR3 120bpm| ambas   | >0.7/0.3 → >0.65  | ±5/8 → ±2             |

**Observaciones:**
- HR1 es el más preciso (SQI=1.0 exacto, HR exactísimo). La senoidal perfecta produce jitter RR = 0.
- HR2 (autocorrelación) tiene SQI algo menor (~0.875) pero HR muy preciso. El ruido no cambia significativamente la forma de la autocorrelación.
- HR3 (HPS/FFT) a 1 Hz tiene SQI=1.0, pero a 2 Hz baja a ~0.73. Esto es intrínseco: la resolución del bin FFT es ~0.098 Hz = ~5.9 BPM en la zona de 120 BPM, lo que dificulta que el pico domine sobre los vecinos.

**Resultado:** 30/30 tests pasan con los nuevos umbrales.


## Sesión 2026-04-13 — Rename mow → incunest en toda la librería y el proyecto

**Cambio:** rename completo de todos los identificadores con "mow" a "incunest":
- Carpeta `lib/mow_afe4490/` → `lib/incunest_afe4490/`
- Ficheros: `mow_afe4490.{h,cpp,_platform_stub.h}` → `incunest_afe4490.*`
- Spec: `mow_afe4490_spec.md` → `incunest_afe4490_spec.md`
- Clase C++: `MOW_AFE4490` → `INCUNEST_AFE4490`
- Macros: `MOW_AFE4490_*` → `INCUNEST_AFE4490_*`, `MOW_OFFLINE` → `INCUNEST_OFFLINE`, `MOW_TIMING_STATS` → `INCUNEST_TIMING_STATS`
- FreeRTOS: `Mow_Task`, `"mow_hr2"`, `"mow_hr3"` → `Incunest_Task`, `"incunest_hr2"`, `"incunest_hr3"`
- Funciones firmware: `start_mow()`, `stop_mow()` → `start_incunest()`, `stop_incunest()`
- Variables: `mow_sample_count`, `g_mow_task`, `MowFrameMode`, `g_mow_frame_mode` → `incunest_*`
- Offline runner: `mow_offline_runner` → `incunest_offline_runner`
- Repo GitHub renombrado a `incunest_afe4490_test`. Remote local actualizado.

**Decisión:** mantener `afe4490` en el nombre (no sustituir por `ppg`). La librería es un driver de hardware para el chip AFE4490, no una interfaz PPG genérica. Si en el futuro se añade otro sensor PPG, quedarían como `incunest_afe4490` vs `incunest_max30102`.

**Resultado:** 31/31 tests pasan. Sin residuos de "mow" en el código fuente.


## Sesión 2026-04-13 — fix(hr3): SQI se desplomaba a ~0.5 a 85 BPM

**Problema observado:** con el simulador PPG a 85 BPM, el SQI de HR3 bajaba a ~0.5 sin razón aparente.

**Diagnóstico:** 85 BPM = 1.417 Hz = bin 14.5 — exactamente entre dos bins FFT (peor caso de leakage inter-bin). El HPS = P[k]·P[2k]·P[3k] es un *producto* de tres espectros de potencia. Con la ventana Hann, una distribución 50/50 entre bins adyacentes hace que el HPS peak baje a ~12% del valor ideal (pérdida cúbica: 0.5³ = 0.125). Consecuencia: el pico no domina el resto del espectro HPS → SQI ≈ 0.5 aunque la señal sea perfectamente limpia.

**Fix aplicado (`_compute_hr3()`):** interpolación parabólica sobre los valores HPS en los tres puntos (peak_bin−1, peak_bin, peak_bin+1) para calcular el valor real del pico a la posición fraccionaria. Este valor interpolado se usa como numerador del SQI, en lugar del valor entero `peak_hps`. Consistente con la interpolación parabólica ya existente para calcular la frecuencia a partir de P[k].

**Fórmula SQI actualizada (spec §5.4, v0.17):**
```
HPS_interp = interpolación parabólica de HPS en (peak_bin-1, peak_bin, peak_bin+1)
fraction   = HPS_interp / Σ HPS[k]
SQI        = clamp((fraction - baseline) / (1 - baseline), 0, 1)
```

**Test nuevo:** `test_hr3_85bpm` — señal multi-armónica a 85 BPM, verifica SQI > 0.80 y HR ± 2 BPM.

**Resultado:** 31/31 tests pasan. Spec bumpeada a v0.17.


## Sesión 2026-04-13 — fix(hr2): SQI sesgado por estimador biased de autocorrelación

**Problema observado:** con el simulador MS100 (señal casi perfecta), HR1 y HR3 dan SQI ≈ 1.0 pero HR2 da SQI ≈ 0.9.

**Diagnóstico:** el estimador de autocorrelación era biased. El numerador suma (N−τ) términos pero el denominador (acorr0 = Σ x²) refleja N términos. Para una señal perfectamente periódica, el SQI máximo teórico es (N−τ)/N, no 1.0. A 60 BPM (τ=50, N=400): (400−50)/400 = 0.875. A 120 BPM (τ=25): 375/400 = 0.9375. El SQI observado ~0.9 encajaba exactamente con la HR del simulador.

**Fix aplicado:**
- `_compute_hr2()` en `incunest_afe4490.cpp`: cambio de `sum / acorr0` a `sum * N / (acorr0 * (N−τ))` — estimador no sesgado.
- `HR2TestCalc.update()` en `ppg_plotter.py`: misma corrección con `acorr * n / (acorr0_val * n_terms)`.
- `test_hr2.cpp`: umbrales actualizados (clean: >0.80→>0.95, noisy: >0.75→>0.80).
- Tooltip HR2_SQI en ppg_plotter.py actualizado.
- Spec bumpeada a v0.18, §5.3 y changelog.

**Resultado:** 31/31 tests pasan. HR2 SQI ahora ≈ 1.0 con señal limpia, consistente con HR1 y HR3.


## Sesión 2026-04-13 — Multi-board: environments incunest_V15 / incunest_V16

**Contexto:** nueva placa Incunest V16 con mismo chip ESP32-S3. Único pin diferente respecto a V15: DRDY (45→17). Resto idéntico.

**Decisión de diseño (comparativa de 4 opciones):** pines en `platformio.ini` como build_flags. Descartadas: `#ifdef` en `main.cpp` (mezcla config/código), `board.h` dedicado (fichero extra innecesario para pocos pines), pines en `incunest_afe4490.h` (rompe genericidad de la librería). El proyecto IncuNest padre usa `board.h` porque gestiona decenas de periféricos — aquí no aplica.

**Cambios aplicados:**
- `platformio.ini`: sección base `[base_incunest_esp32s3]` con settings compartidos y pines SCK/MISO/MOSI/CS/PWDN. `[env:incunest_V15]` (DRDY=45) y `[env:incunest_V16]` (DRDY=17) heredan la base. Renombrado desde `in3ator_V15`.
- `main.cpp`: eliminados `#define` hardcodeados, `SPI.begin()` usa símbolos, guard `#error` si faltan pines, cabecera actualizada a v0.9.

**Resultado:** ambos environments compilan correctamente.


## Sesión 2026-04-13 — Renombrado AFE4490_SCK/MISO/MOSI_PIN → SPI_SCK/MISO/MOSI_PIN

**Motivo:** los pines SCK/MISO/MOSI pertenecen al bus SPI compartido, no al chip AFE4490. El prefijo `AFE4490_` era semánticamente incorrecto y confuso si en el futuro se añade otro dispositivo al bus.

**Cambios:** `platformio.ini` y `main.cpp` — tres símbolos renombrados. Sin cambio funcional.


## Sesión 2026-04-13 — Actualización examples/basic/main.cpp

**Cambios:** añadidos `SPI_SCK_PIN/MISO_PIN/MOSI_PIN` como `#define` explícitos (apropiado para un ejemplo — el usuario los adapta a su placa), `SPI.begin()` usa los símbolos, corregido comentario erróneo MOSI/MISO, versión actualizada a v0.18.


## Sesión 2026-04-13 — Startup banner + BOARD_VERSION

**Cambio:** añadido mensaje de bienvenida antes del bloque `# SYS:` en `setup()`:
```
# incunest_afe4490 test firmware v0.9 [incunest_V16] — Medical Open World
```

**Implementación:** `BOARD_VERSION` definido como string en cada environment de `platformio.ini` (`-DBOARD_VERSION=\"incunest_V15\"` / `\"incunest_V16\"`). `PIOENV` no es un macro C automático — requiere pasarse explícitamente.

**Pendiente:** verificar en placa V16 que el pin DRDY correcto. Ambos environments (V15/V16) dan DRDY timeout — el pin real de la V16 está por confirmar con el esquemático.


## Sesión 2026-04-13 — Fix: banner no aparecía tras reset desde script

**Problema:** el mensaje de bienvenida se enviaba antes de que la conexión USB CDC estuviera estable, por lo que los bytes se perdían. Los mensajes `# SYS:` sí aparecían porque llegaban más tarde (tras las llamadas a `esp_chip_info()` etc.).

**Fix:** añadido `vTaskDelay(pdMS_TO_TICKS(500))` después de `Serial.begin()` para dar tiempo a que la conexión USB CDC se estabilice antes de imprimir el banner.


## Sesión 2026-04-13 — Eliminación residuos Protocentral

**Cambios:**
- `ppg_plotter.py`: eliminado botón `PROTOCENTRAL` y su tooltip. Limpiado `_update_lib_button` para no referenciar `btn_lib_pc`. El comando `'p'` ya no existe en el firmware.
- `README.md`: eliminadas referencias a Protocentral como testbed de comparación y al comando `'p'`. Actualizado hardware (V15/V16), comandos de flash con environments, estructura del proyecto y baud rate (921600).


## Sesión 2026-04-13 — SIGNAL STATS: nueva columna Max-Min

**Cambio:** añadida columna "Max-Min" entre "Mean" y "Min" en la tabla SIGNAL STATS de ppg_plotter.py. Muestra hi−lo del intervalo de actualización. Cambios: columnas 5→6, header labels, init loop range(1,5)→range(1,6), vals en _update_stats_table, tooltip del spin_stats_interval.


## Sesión 2026-04-14 — SIGNAL STATS: resaltado manual de celdas con borde dorado

**Cambio:** click en cualquier celda de SIGNAL STATS → borde dorado (#FFD700, 3px) mediante `_StatsHighlightDelegate`. Segundo click quita el resaltado. Las celdas resaltadas se persisten en `ppg_plotter.ini` (clave `PPGMonitor/stats_highlighted`, formato `row,col;row,col`). No interfiere con los colores SQI de HR1/HR2/HR3 (el delegate pinta el borde encima).


## Sesión 2026-04-14 — QMenu min-width para submenús de plots

**Cambio:** añadido `QMenu { min-width: 360px; }` al stylesheet global de la aplicación. Corrige los submenús del botón derecho de los plots pyqtgraph que aparecían demasiado estrechos para leerlos.


## Sesión 2026-04-14 — Chequeo integridad RED_Sub / IR_Sub por trama

**Cambio:** en el parsing de tramas M1 en vivo, se verifica que `RED_Sub == RED - RED_Amb` e `IR_Sub == IR - IR_Amb`. Si hay discrepancia, se loguea en Serial Console como `[CHK] SUB MISMATCH #N` con SmpCnt y Δ por canal. Los primeros 5 se loguan siempre; luego uno de cada 100. Contador `_sub_mismatch_count` en PPGMonitor.

**Motivación:** investigar si los picos esporádicos en la señal DC-removed de HR1TEST se originan en el firmware (datos incoherentes entre campos del frame) o en hardware (transitorio real en IR_Sub).


## Sesión 2026-04-14 — SIGNAL STATS: formato entero con separador de millares para señales brutas

**Cambio:** en `_update_stats_table`, las primeras 6 filas (RED, IR, RED_Amb, IR_Amb, RED_Sub, IR_Sub — ADC counts) se formatean sin decimales y con separador de millares de espacio fino tipográfico (`\u202f`), p.ej. `1 234 567`. El resto de señales mantiene 2 decimales.


## Sesión 2026-04-13 — Capturas redirigidas a carpeta captures/

**Cambio:** todas las capturas del script se guardan ahora en la subcarpeta `captures/` (creada automáticamente al arrancar). Afecta a 9 puntos de escritura: `ppg_data_stream`, `ppg_data_snap`, `ppg_chk`, `spo2_cal`, `spo2test`, `hr1test`, `hr2test`, `hr3test` y `LabCaptureWindow` (directorio por defecto y fallback). Añadida constante `CAPTURES_DIR` junto a `SETTINGS_FILE`.


## Sesión 2026-04-14 — Rename y reubicación del proyecto: PulseNest

**Cambio:** el proyecto ha sido renombrado de `Pulsioximeter_test` a **PulseNest** y reubicado de `C:\PRJ\MOW\Misc\AFE4490\Pulsioximeter_test_PABLO\Pulsioximeter_test` a `C:\PRJ\MOW\PulseNest`.

**Motivación:** el nombre PulseNest encaja con la nomenclatura del ecosistema (IncuNest), y la nueva ubicación refleja que el proyecto ha madurado de herramienta de test a proyecto propio dentro de Medical Open World.

**Ficheros actualizados:**
- `CLAUDE.md`, `TODO.md`, `project_info.md`, `conversation_log.md`: título actualizado a PulseNest
- `ppg_plotter.ini`: `output_dir` apuntando a `C:/PRJ/MOW/PulseNest/captures`
- Memorias de Claude Code: paths de comandos pio y pythonw actualizados a nueva ubicación


## Sesión 2026-04-14 — Extracción librería + workflows GitHub

### Eliminación repo viejo
Eliminado `acuesta-mow/incunest_afe4490_test` (repo obsoleto). El repo activo es `medicalopenworld/PulseNest`.

### Extracción de incunest_afe4490 a repo propio
**Decisión:** la librería vive en su propio repo `medicalopenworld/incunest_afe4490`. PulseNest la consume via `lib_deps = ...#master` durante desarrollo.

**Motivo:** ciclos de vida independientes, changelog limpio, lib_deps semántico para Pablo/Juan en IncuNest.

**Cambios:**
- Nuevo repo `medicalopenworld/incunest_afe4490` — ficheros: `.h`, `.cpp`, `_platform_stub.h`, `incunest_afe4490_spec.md`, `library.json`, `README.md`, `examples/basic/main.cpp`. Tag `v0.18` creado.
- PulseNest: eliminados `lib/incunest_afe4490/` e `incunest_afe4490_spec.md`. `platformio.ini` actualizado con `lib_deps = ...#master`. `CLAUDE.md` actualizado.
- Versión en headers corregida de v0.16 a v0.18.

### Junction local para desarrollo simultáneo
`PulseNest\lib\incunest_afe4490\` → junction → `C:\PRJ\MOW\incunest_afe4490\`. PlatformIO usa los ficheros locales directamente. `.gitignore` de PulseNest ignora `lib/incunest_afe4490/`. Son dos repos independientes — se commitean por separado.

### Spec pulsenest_lab.py
Creada `pulsenest_lab_spec.md` v1.0 en PulseNest. Cubre: protocolo serial, clases de algoritmos, layout UI, subventanas, outputs CSV, persistencia .ini, convenciones de color.

### Primera versión compartida de la librería
`medicalopenworld/incunest_afe4490` tag `v0.18` — primera versión disponible para Pablo y Juan.

**Mensaje para Pablo/Juan:**
```ini
lib_deps =
    https://github.com/medicalopenworld/incunest_afe4490.git#v0.18
```


---

## Sesión 2026-04-14b

### Tema: SIGNAL STATS — celdas seleccionables y copiables

**Pregunta clave:** ¿Cómo hacer que la tabla SIGNAL STATS permita seleccionar celdas arrastrando el ratón y copiarlas al clipboard?

**Decisiones:**
- `setSelectionMode` cambiado de `NoSelection` a `ContiguousSelection` + `setSelectionBehavior(SelectItems)` — permite seleccionar rangos arrastrando.
- Eliminado `setFocusPolicy(NoFocus)` para que el widget reciba eventos de teclado.
- Añadido `QTableWidget::item:selected { background-color: #2A4A6A; }` para resaltado visual de selección.
- Añadido `QShortcut(Ctrl+C)` en la tabla que llama a `_copy_stats_selection()`.
- `_copy_stats_selection()`: copia las celdas seleccionadas al clipboard en formato TSV (tab-separated), compatible con Excel/LibreOffice Calc.
- El mecanismo de highlight persistente por click (`_stats_highlighted` + `_StatsHighlightDelegate`) no se modificó — sigue funcionando de forma independiente.

---

## Sesión 2026-04-14c

### Tema: incunest_afe4490 v0.19 — getConfig() / AFE4490Config

**Pregunta clave:** ¿Cómo añadir lectura de los parámetros de configuración del chip AFE4490?

**Decisiones:**
- Nuevo struct `AFE4490Config` en el header: agrupa todos los parámetros configurables (sample_rate_hz, num_averages, led1/2_current_mA, led_range_mA, tia_gain, tia_cf, stage2_gain, ppg_channel, filter_type, filter_f_low/high_hz, hr2_f_low/high_hz, hr3_f_high_hz, spo2_a/b).
- Nuevo método `AFE4490Config getConfig()` en la API pública.
- Implementación: toma `_spi_mutex` para los campos de hardware (sample rate, LED, TIA, stage2) y `_state_mutex` para los campos de señal/filtros/SpO2, siguiendo el mismo patrón que los setters. Seguro antes y después de `begin()`.
- Librería bumpeada a **v0.19** (h, cpp, library.json, spec).
- Spec actualizada: §2.3b (nueva sección), §10 (historial v0.19).

---

## Sesión 2026-04-14d

### Tema: Botón "Read chip config" en Lab Capture + comando $CFG? en firmware

**Pregunta clave:** ¿Cómo añadir un botón en Lab Capture que pida la configuración del AFE4490 por serie y la inserte en Pre-capture notes, sin distorsionar el stream de medidas?

**Decisiones:**

**Firmware (main.cpp):**
- `Cmd_Task` extendido: acumula bytes hasta `\n` en lugar de leer un carácter a la vez. Mantiene compatibilidad con `'1'` y `'2'` (single-char). Nuevo comando: `$CFG?\n`.
- Helpers estáticos: `tia_gain_str`, `tia_cf_str`, `stage2_str`, `channel_str`, `filter_str` — convierten los enums de `AFE4490Config` a string.
- `send_cfg_frame()`: llama a `afe.getConfig()`, formatea la trama `$CFG,...*XX\r\n` con checksum XOR NMEA. Sin mutex adicional: el buffer UART del hardware serializa las escrituras entre tareas.

**Script (pulsenest_lab.py):**
- `PPGMonitor._cfg_listener`: atributo callable (None por defecto), registrable por LabCaptureWindow.
- `PPGMonitor.request_chip_config()`: envía `b'$CFG?\n'` al puerto serie. Devuelve False si no conectado.
- `PPGMonitor._on_cfg_frame_received(line)`: parsea los campos key=value del frame `$CFG`, formatea texto legible, llama a `_cfg_listener`.
- Parser serial: handler `$CFG,` añadido antes de la decimación (igual que `$TIMING`, `$TASK`).
- `LabCaptureWindow`: botón "Read chip config" en cabecera del grupo Pre-capture notes.
- `_on_read_cfg()`: llama a `request_chip_config()`, muestra aviso si no conectado.
- `_on_cfg_received(text)`: añade el texto al final de `_pre_notes` (con separador si ya hay contenido).
- Listener registrado en `__init__` de LabCaptureWindow.

**Pendiente:** compilar y flashear el firmware con los cambios (nuevo `Cmd_Task` + `send_cfg_frame`).

---

## Sesión 2026-04-14e

### Tema: Correcciones post-flash + banner de versión

**Problemas detectados y resueltos:**

1. **Bug en `_on_cfg_frame_received`**: línea espuria `self.log(f"Frame mode: ${mode}")` (variable `mode` inexistente). Eliminada. Añadido logging completo de la respuesta (7 líneas en el log). Añadido `self.log("CFG request sent → $CFG?")` en `request_chip_config()`.

2. **Build fallaba con v0.19**: PlatformIO usaba la caché git (v0.18) en lugar de los archivos locales. Causa: `lib_deps` apunta a git y el include path era `.pio/libdeps/...` (v0.18), no la junction local. Solución: commit + push v0.19 a git, limpiar caché libdeps, rebuild.

3. **Banner de versión**: actualizado para mostrar ambas versiones (firmware + librería) y añadir "Board:":
   - Antes: `# incunest_afe4490 test firmware v0.9 [incunest_V15] — Medical Open World`
   - Después: `# PulseNest v0.9 | incunest_afe4490 v0.19 | Board: incunest_V15 — Medical Open World`

**Cambios en incunest_afe4490:**
- Añadido `#define INCUNEST_AFE4490_VERSION "0.19"` en el header.
- Commit `d759054` pusheado a master.

**Nota de arquitectura (lib_deps):** PlatformIO siempre descarga la librería desde git para V15/V16. La junction local `lib/incunest_afe4490/` no se usa como include path. Para usar cambios locales hay que hacer commit+push a git y limpiar `.pio/libdeps/`.

---

## Sesión 2026-04-14f

### Tema: Versión de librería en traza "Active library:"

**Cambio:** El log "Active library:" ahora extrae la versión directamente del banner del firmware (`# PulseNest v0.9 | incunest_afe4490 v0.19 | Board: ...`) con regex `incunest_afe4490\s+(v[\d.]+)`. Resultado: `Active library: incunest_afe4490 v0.19`. Si el banner no incluye versión, se muestra `Active library: incunest_afe4490` (sin cambio de comportamiento).

---

## Sesión 2026-04-14g

### Tema: Eliminación del botón INCUNEST (librería única)

**Cambios en pulsenest_lab.py:**
- Eliminados del sidebar: label "LIBRARY" + botón "INCUNEST" + llamada a `_update_lib_button()`.
- Eliminado `active_lib` del `__init__` (ya no tiene sentido con una sola librería).
- Eliminado método `_update_lib_button()` (actualizaba estilo del botón eliminado).
- Eliminado método `_send_lib_cmd()` (solo lo usaba el botón eliminado).
- Simplificado `_update_frame_button()`: eliminado `incunest_active`, los botones M1/M2 siempre habilitados.
- En el parser serial: sustituido `self.active_lib = "INCUNEST"` + `_update_lib_button()` por `_update_frame_button()` directamente.

---

## Sesión 2026-04-14h

### Tema: Fix traza "Active library:" duplicada al resetear el ESP32

**Problema:** Al resetear el ESP32, la traza "Active library: incunest_afe4490" aparecía dos veces: la primera con versión, la segunda sin versión.

**Causa raíz:** El parser del script disparaba el log "Active library:" para cualquier línea `#` que contuviera "incunest" y no contuviera "frame". El firmware envía dos líneas que cumplen esta condición:
1. `# PulseNest v0.9 | incunest_afe4490 v0.19 | Board: ...` — tiene versión → correcto
2. `# incunest_afe4490 started` (emitida desde `start_incunest()`) — sin versión → duplicado incorrecto

**Fix (pulsenest_lab.py):** La traza "Active library:" ahora solo se emite cuando el regex `incunest_afe4490\s+(v[\d.]+)` encuentra la versión en la línea. Si no hay versión, el `frame_mode = "M1"` y `_update_frame_button()` siguen ejecutándose (la línea sigue siendo útil), pero no se genera el log duplicado.

---

## Sesión 2026-04-14i

### Tema: Log de versión de placa al resetear el ESP32

**Cambio (pulsenest_lab.py):** Al detectar el banner del firmware (línea con `incunest_afe4490 vX.XX`), se añade una segunda traza en el log con la versión de placa extraída del campo `Board:`:
- `Active library: incunest_afe4490 v0.19`
- `Board: incunest_V15`

Regex: `r'Board:\s*(\S+)'` aplicado sobre la misma línea del banner. Solo se emite si el campo `Board:` está presente.

---

## Sesión 2026-04-14j

### Tema: Fix stack overflow en Cmd_Task + color botón "Read chip config" + migración a placa V16

**Migración a incunest_V16:**
- La placa física es V16 (DRDY_PIN=17), no V15 (DRDY_PIN=45). Solo hay que flashear con el environment correcto: `pio run -e incunest_V16 -t upload --upload-port COM15`.
- La librería cacheada era v0.18 para V16 → limpiado `.pio/libdeps/incunest_V16/` y rebuildeado con v0.19.

**Bug: stack overflow en Cmd_Task → crash → reinicio del ESP32:**
- Síntoma: pulsar "Read chip config" producía las mismas trazas que el botón "RESET ESP32".
- Causa raíz: `Cmd_Task` tenía solo 2048 bytes de stack. `send_cfg_frame()` pone en el stack `char buf[256]` + `AFE4490Config cfg` (~68 bytes) + overhead de `snprintf` con múltiples `%f` (~300-400 bytes en newlib/ESP32). Stack overflow → crash → reboot → banner de startup.
- Los comandos `'1'` y `'2'` no llaman a `send_cfg_frame()` por eso funcionaban bien.
- Fix: `Cmd_Task` stack 2048 → 4096 bytes en `main.cpp`.

**Botón "Read chip config" (pulsenest_lab.py):**
- Añadido fondo más claro: `background-color:#2A3D5A; color:#AACCFF`.

---

## Sesión 2026-04-14k

### Tema: Board y MAC en la trama $CFG

**Cambios en main.cpp:**
- `send_cfg_frame()`: añadidos campos `board` y `mac` al frame `$CFG` (key=value, coherente con el resto). Buffer ampliado de 256 a 320 bytes para acomodar los nuevos campos. La MAC se obtiene con `esp_read_mac()` (header `esp_mac.h` ya incluido).
- Formato: `...,board=incunest_V16,mac=XX:XX:XX:XX:XX:XX*chk`

**Cambios en pulsenest_lab.py:**
- `_on_cfg_frame_received()`: añadida línea de log `board=...  mac=...` (segunda línea tras el timestamp).
- Texto Pre-capture notes: añadida línea `Board: ...   MAC: ...` al bloque de texto insertado.

---

## Sesión 2026-04-14l

### Tema: Hash git + timestamp de compilación en el banner del firmware

**Motivación:** combinar hash git (trazabilidad del código) con timestamp (identificar cuándo se compiló).

**Nuevo fichero: `scripts/pre_build_hash.py`**
- PlatformIO `extra_scripts` pre-build en Python.
- Extrae el hash git corto de `.pio/libdeps/<env>/incunest_afe4490` con `git rev-parse --short HEAD`.
- Inyecta `-DINCUNEST_GIT_HASH=\"xxxxxxx\"` en los flags de compilación.
- Fallback a `"unknown"` si git no está disponible o el directorio no existe.

**`platformio.ini`:** añadido `extra_scripts = pre:scripts/pre_build_hash.py` en `[base_incunest_esp32s3]`.

**`main.cpp`:** banner actualizado con concatenación de literales en tiempo de compilación (cero overhead runtime):
```
# PulseNest v0.9 | incunest_afe4490 v0.19+sha.d759054 | build: Apr 14 2026 15:23:01 | Board: incunest_V16
```

**`pulsenest_lab.py`:** parser del banner actualizado:
- Regex `v[\d.]+` → `v\S+` para capturar también `+sha.xxxxxxx`.
- Añadida extracción del campo `build:` → log `Build: Apr 14 2026 15:23:01`.
- Al conectar aparecen tres trazas: `Active library:`, `Build:`, `Board:`.

---

## Sesión 2026-04-14m

### Tema: Splitters con persistencia INI en todas las ventanas

**Objetivo:** añadir QSplitter entre plots y sidebars en todas las ventanas del script, guardando posición en `pulsenest_lab.ini`.

**Ventanas completadas (sesión anterior):**
- SpO2TestWindow, HR1TestWindow, HR2TestWindow, HR3TestWindow: `self._splitter` + INI.
- HR3LabWindow, HRLabWindow: `self._splitter` ya existía, añadida persistencia INI.
- SpO2LabWindow: ya tenía INI completo.

**Ventanas completadas (esta sesión):**

**PPGMonitor:**
- Eliminada `content_layout = QtWidgets.QHBoxLayout()`.
- Sidebar (`self.sidebar_layout`) envuelto en `_sidebar_container` (QWidget).
- Nuevo `self.main_splitter` (QSplitter Horizontal) entre sidebar y `self.right_splitter`.
- `_save_settings()`: guarda `PPGMonitor/main_splitter`.
- `_restore_settings()`: restaura o aplica defecto `[340, 1200]`.

**PPGPlotsWindow:**
- Eliminado `root = QHBoxLayout()`.
- Nuevo `self._splitter` (QSplitter Horizontal) entre sidebar (`sb_widget`) y plots.
- Eliminado `sb_widget.setFixedWidth(180)` (el splitter gestiona el tamaño).
- Nuevo `self._plots_splitter` (QSplitter Vertical) dentro del área de plots.
- `graphics_layout` (RED/IR) en slot superior del `_plots_splitter`.
- Bottom row (PPG/SpO2/HR) convertida de QHBoxLayout a `_bottom_splitter` (QSplitter Horizontal), añadido al slot inferior de `_plots_splitter`.
- INI: `PPGPlotsWindow/splitter` y `PPGPlotsWindow/plots_splitter` en `__init__`, `closeEvent` y `_save_settings` de PPGMonitor.

**Ventanas sin splitter (no aplicable):**
- TimingWindow: solo tabla, sin paneles múltiples.
- LabCaptureWindow: solo formulario, sin paneles múltiples.

---

## Sesión 2026-04-15 — Auto-CF: selección automática de capacidad TIA

**Tema:** Cálculo automático de `_tia_cf` (capacidad de realimentación del TIA del AFE4490) en función de la frecuencia de muestreo (`_sample_rate_hz`), la resistencia TIA (`_tia_gain` = RF) y el tiempo de settle de los LEDs antes de que el ADC tome la muestra.

**Decisiones tomadas:**

1. **Fórmula del settle time adaptativo:**
   - Margen = `max(50, floor(q × 0.10))` counts, donde `q = afeclk / (4 × Fs)` (ventana LED-on)
   - Mínimo: 12.5 µs (50 counts a 4 MHz) — floor que cubre RF_500K/CF_5P al límite
   - A 500 Hz: margen = 200 counts = 50 µs (era 50 counts = 12.5 µs fijo)
   - El mismo margen lo usan `_apply_timing_regs()` y `_recalc_tia_cf()` — siempre sincronizados vía `_compute_settle_margin()`

2. **Criterio de selección CF:**
   - Restricción: `5τ ≤ settle_time` → `CF ≤ settle_time / (5 × RF)` (5 tau = error < 0.7%)
   - Se selecciona el mayor enum `AFE4490TIACF` cuyo valor físico en pF satisface la restricción
   - Fallback: CF_5P (mínimo absoluto)

3. **Impacto en la configuración por defecto (500 Hz, RF_500K):**
   - Antes: CF_5P (5 pF) — tau=2.5 µs, 5τ=12.5 µs (al límite con margen fijo)
   - Ahora: CF_20P (20 pF) — tau=10 µs, 5τ=50 µs (con margen adaptativo)
   - f_polo TIA: 63.7 kHz → 15.9 kHz (bien por encima de la banda PPG 0.5–20 Hz)

4. **Implementación:**
   - `_compute_settle_margin()` → uint32_t: método privado const, usado por ambos callers
   - `_recalc_tia_cf()` → void: selecciona CF; llamado desde `_recalc_rate_params()` y `setTIAGain()`
   - `setTIACF()` sigue disponible para override manual; puede ser reoverridenado por `setTIAGain()` / `setSampleRate()`
   - Constantes en anonymous namespace: `afeclk`, `tia_rf_ohm[]`, `tia_cf_pF[]`, `tia_settle_fraction=0.10`, `tia_settle_min=50`, `tia_n_tau=5.0`

5. **Spec:** v0.19 → v0.20. Sección §7.2 añadida con tabla de CF por RF a 500 Hz.

---

## Sesión 2026-04-15 (cont.) — Documentación comportamiento getData() y cola interna

**Tema:** Análisis y documentación del comportamiento de `getData()` en función de la frecuencia de consumo respecto a la frecuencia de muestreo del AFE (500 Hz).

**Conclusiones del análisis:**

- `getData()` es no bloqueante (`xQueueReceive(..., 0)`)
- La cola (10 items, `INCUNEST_AFE4490_QUEUE_SIZE`) actúa como buffer de jitter
- Cuando la cola está llena, el productor descarta el más antiguo e inserta el más reciente (líneas 1020–1024 .cpp)
- El consumidor siempre saca por el frente (FIFO)
- Con consumidor consistentemente más lento (< 500 Hz): cola llena en estado estacionario → retardo fijo de **10 × T_muestreo = 20 ms** + muestras intermedias descartadas
- Los algoritmos internos (HR1/HR2/HR3/SpO2) procesan todas las muestras a 500 Hz independientemente de la frecuencia de consumo

**Cambios realizados:**

- `incunest_afe4490_spec.md` §2.5: tabla de comportamiento por frecuencia de consumo añadida
- `incunest_afe4490.h`: comentario Doxygen completo sobre `getData()` con los 4 casos (> 500 Hz, ≈ 500 Hz, jitter ocasional, consistentemente < 500 Hz)
- Pendiente "documentar estrategia de cola" eliminado de la lista de pendientes (ya completado)

---

## Sesión 2026-04-15 (cont.) — Datasheet URL + versión v0.20

**Tema:** Añadir referencia al datasheet oficial del AFE4490 en todos los ficheros relevantes.

**URL:** https://www.ti.com/lit/ds/symlink/afe4490.pdf

**Cambios realizados:**
- `README.md`: sección References añadida con enlace al datasheet
- `incunest_afe4490_spec.md`: URL en cabecera, §7.1 y §11 (reference sources)
- `incunest_afe4490.h`: URL en cabecera + versión v0.19 → v0.20
- `incunest_afe4490.cpp`: URL en cabecera + versión v0.19 → v0.20

---

## Sesión — 2026-04-15

### Tema: Clasificación de parámetros y Parameters Reference en la spec

**Preguntas clave:**
- ¿Qué tipos de parámetros afectan a los resultados de la librería?
- ¿Dónde documentarlos?
- ¿Cómo tratar los factores de entorno/condición física que están fuera del alcance de la librería?

**Decisiones tomadas:**
1. **Clasificación en 5 capas**: (1) hardware AFE4490, (2) pre-procesado compartido, (3) parámetros por algoritmo (SpO2/HR1/HR2/HR3), (4) rango/validación, (5) entorno/condición física
2. **Toda la documentación de parámetros va en `incunest_afe4490_spec.md`** — es la única fuente de verdad que puede regenerar la librería
3. **Los factores de entorno** (perfusión, luz ambiental, movimiento, sonda) **no son parámetros configurables** pero sus efectos son observables a través de los campos SQI y raw de `AFE4490Data`. Se documentan explícitamente como out-of-scope.
4. **Spec actualizada a v0.21**: nueva §10 "Parameters Reference" con subsecciones §10.1–§10.8. Secciones anteriores §10–§12 renumeradas a §11–§13.

**Cambios realizados:**
- `incunest_afe4490_spec.md`: v0.20 → v0.21, §10 Parameters Reference añadida (8 subsecciones), Version history movida a §13 (final del documento), §11 AFE4490 register config, §12 Bibliographic references

---

## Sesión — 2026-04-15 (continuación)

### Tema: Remote Parameter Control — diseño e implementación fase 1 (parámetros hardware AFE4490)

**Preguntas clave:**
- ¿Qué estrategia seguir para cambiar parámetros de la librería en tiempo de ensayo sin reflashear?
- ¿Qué parámetros hardware del AFE4490 exponer en esta primera fase?
- ¿Apply individual por parámetro o Apply All?
- ¿Los parámetros `amb_tiagain`/`amb_tiacf` (TIA_AMB_GAIN) son implementables directamente?

**Decisiones tomadas:**
1. **Protocolo:** trama NMEA-style `$SET,key,value*XX\r\n` (PC → ESP32). Checksum XOR idéntico al de las tramas de datos existentes. Confirmación: el firmware responde con `$CFG` actualizado, o `$ERR,key,reason` si el valor es inválido.
2. **Apply individual por parámetro** — botón "Set" por control en la ventana. Más ergonómico en lab (cambios aislados durante medidas).
3. **8 parámetros en fase 1:** `led1`, `led2`, `ledrange`, `tiagain`, `tiacf`, `stg2`, `sr`, `numav`. Los analógicos se aplican en caliente (los setters ya escriben SPI directo bajo `_spi_mutex`). `sr` requiere stop/restart (recalcula timing y algoritmos).
4. **`amb_tiagain`/`amb_tiacf` aplazados:** la librería tiene ENSEPGAIN=0 en TIAGAIN (bit 15), por lo que TIA_AMB_GAIN RF/CF son ignorados por el chip. Añadirlos requeriría activar ENSEPGAIN=1, que es un cambio de diseño independiente. Se diseñarán en una iteración futura.
5. **Timing registers** (0x01–0x1C): aplazados para una iteración futura. Son 20 registros interdependientes; un error puede dejar el chip en estado inválido.
6. **TX_REF** (CONTROL2 bit): aplazado. Valor actual hardcodeado a 0 (0.75 V). Requiere verificar el datasheet antes de exponer.

**Cambios realizados:**
- `src/main.cpp`: `cmd_buf` 32→64 bytes; helpers `parse_tia_gain()`, `parse_tia_cf()`, `parse_stage2()`; función `apply_set_cmd()` con lógica stop/restart para `sr`; `Cmd_Task` ampliado para parsear `$SET,key,val*XX` con verificación de checksum.
- `pulsenest_lab.py`: nueva clase `HWConfigWindow` (8 controles con botón Set individual, se puebla desde `$CFG`, geometría persistente); botón `HW CONFIG` en sidebar; `_on_cfg_frame_received()` actualiza `HWConfigWindow` si está abierta; `$ERR` frames mostrados en log y statusbar; ventana integrada en save/restore/raise/close.
- `pulsenest_lab.py`: botón `btn_pause` renombrado de "PAUSE CAPTURE" / "RESUME CAPTURE" a "FREEZE DISPLAY" / "RESUME DISPLAY" (más preciso: el puerto serial y la recepción de datos no se interrumpen, solo se congela la visualización).
- `pulsenest_lab.py`: `HWConfigWindow` refactorizada para usar el patrón `main_monitor` (igual que el resto de ventanas del proyecto): `self.main_monitor = parent` en `__init__`, reemplazados todos los `self.parent()` por `self.main_monitor`, y añadido `main_monitor = None` antes de cada `close()` en `toggle_hw_config()` y `PPGMonitor.closeEvent()` para evitar callbacks recursivos durante el cierre.
- `pulsenest_lab.py`: corregido bug por el que `btn_read` de `HWConfigWindow` escribía en Pre-capture notes de `LabCaptureWindow`, y `btn_read_cfg` de `LabCaptureWindow` actualizaba los controles de `HWConfigWindow`. Solución: dos flags independientes en `PPGMonitor` (`_cfg_notify_lab_capture`, `_cfg_notify_hw_config`) que controlan a quién se enruta cada `$CFG` recibido. `request_chip_config()` ampliado con parámetros `notify_lab_capture` y `notify_hw_config`. Cada ventana activa solo su propio flag. Los flags se resetean a sus valores por defecto (`True`/`False`) tras cada frame procesado.

---

## Sesión 2026-04-15 (continuación) — Timing registers t1–t28

### Tema: Implementación completa del acceso a los 28 registros de timing del AFE4490

### Cambios implementados

**`lib/incunest_afe4490/incunest_afe4490.h`** (ya estaba de sesión anterior):
- Struct `AFE4490TimingConfig` con 28 campos t1–t28
- Declaraciones `getTimingConfig()` y `setTimingReg(uint8_t addr, uint32_t value)`

**`lib/incunest_afe4490/incunest_afe4490.cpp`** (ya estaba de sesión anterior):
- `getTimingConfig()`: activa SPI_READ, lee los 28 registros (0x01–0x1C) bajo `_spi_mutex`, emite struct
- `setTimingReg()`: escribe un registro bajo `_spi_mutex`

**`src/main.cpp`**:
- `send_tcfg_frame()`: ya existía; emite `$TCFG,t1=<v>,...,t28=<v>*XX`
- `send_cfg_frame()`: ampliada para llamar `send_tcfg_frame()` al final → $CFG? siempre emite también $TCFG
- `apply_set_cmd()`: añadida tabla de lookup (t1–t28 → addr 0x01–0x1C); `$SET,tN,v` escribe el registro vía `setTimingReg()` y emite `send_tcfg_frame()` (sin $CFG, solo $TCFG); rango validado: 0–65535

**`pulsenest_lab.py`**:
- `PPGMonitor._on_tcfg_frame_received()`: parsea `$TCFG`, siempre entrega a `hw_config_window` si está abierta
- Reader loop: nuevo handler `if line.startswith('$TCFG,')` antes de `$ERR`
- `HWConfigWindow._setup_ui()`: nuevo grupo "Timing Registers" con QScrollArea (altura fija 400 px), 28 QSpinBox (0–65535) con etiqueta `tN  REGNAME`, botón Set individual, y label de validación
- `HWConfigWindow._make_timing_set_btn()`: botón Set para timing (llama `_send_timing_set`)
- `HWConfigWindow._validate_timing()`: comprueba 14 pares start<end, enclosing LED, conv≥sample-end, reset≤conv-start → lista de violaciones
- `HWConfigWindow._on_timing_changed()`: actualiza label verde/naranja en tiempo real
- `HWConfigWindow._send_timing_set()`: avisa de violaciones en statusbar pero no bloquea el envío
- `HWConfigWindow.update_from_tcfg()`: puebla los 28 spinboxes bloqueando señales, luego valida
- Tamaño de ventana por defecto: 520×560 → 560×900

### Decisiones de diseño
- $TCFG siempre se enruta a HWConfigWindow sin depender de los flags `_cfg_notify_*` (es información exclusiva de esa ventana)
- Las violaciones de constraint advierten pero no bloquean el envío (el usuario puede estar ajustando valores de forma incremental)
- Rango firmware: 0–65535 (cubre cualquier PRF a ≥63 Hz con AFECLK=4 MHz)
- Workaround build: los cambios de librería se sincronizan manualmente a `.pio/libdeps/incunest_V16/` mientras no se haga push a GitHub (la lib_deps apunta a GitHub)

---

## Sesión 2026-04-15 (fix menor) — HWConfigWindow scroll resize

- `pulsenest_lab.py`: en `HWConfigWindow`, el scroll area del grupo Timing Registers cambia de `setFixedHeight(400)` a `setMinimumHeight(150)` + `stretch=1` en ambos `addWidget` (scroll dentro de timing_vbox, y grp_timing dentro de vbox). Ahora al agrandar la ventana crece el scroll, no el label de validación.

---

## Sesión 2026-04-15 (fix validación timing) — Opción A: sólo checks intra-par

- `pulsenest_lab.py` `HWConfigWindow._validate_timing()`: eliminados todos los checks inter-fase (LED encompass, conv > sample end, reset < conv start) porque requieren aritmética modular con el período PRF para ser correctos en configuraciones circulares. Sólo se mantienen los 14 checks intra-par (start < end dentro de cada fase), que son siempre válidos independientemente del layout circular.

---

## Sesión 2026-04-15 (fix layout) — Margen superior grp_timing

- `pulsenest_lab.py` `HWConfigWindow._setup_ui()`: `timing_vbox.setContentsMargins` top 6→18 px para que `_lbl_timing_status` no tape el título del QGroupBox "Timing Registers".

---

## Sesión 2026-04-15 (fix layout 2) — Margen superior grp_timing

- `pulsenest_lab.py`: `timing_vbox.setContentsMargins` top 18→24 px (ajuste fino).

---

## Sesión 2026-04-15 (fix layout 3) — Márgenes form_t

- `pulsenest_lab.py`: `form_t.setContentsMargins` top/bottom 4→1 px (compactar filas del scroll de timing).

---

## Sesión 2026-04-15 (fix layout 4) — Spacing form_t

- `pulsenest_lab.py`: `form_t.setSpacing` 3→1 px para reducir la altura de cada fila del scroll de timing.

---

## Sesión 2026-04-15 (fix layout 5) — Fondo HWConfigWindow

- `pulsenest_lab.py`: fondo de `HWConfigWindow` cambiado de `#121212` a `#2A2A2A` (gris más claro).

---

## Sesión 2026-04-15 (fix layout 6) — Fondo spinboxes timing

- `pulsenest_lab.py`: fondo de `HWConfigWindow` revertido a `#121212`. Spinboxes del grupo Timing Registers: `background-color:#3A3A3A; color:#E0E0E0` para distinguirlos visualmente del fondo de la ventana.

---

## Sesión 2026-04-16 (fix layout 7) — Fondo spinboxes HWConfigWindow

- `pulsenest_lab.py`: fondo de todos los `QSpinBox` y `QDoubleSpinBox` de `HWConfigWindow` unificado a `#252525` (gris oscuro) mediante regla en el stylesheet global de la ventana. Eliminado el `background-color` inline previo de los spinboxes de timing.

---

## Sesión 2026-04-16 (fix layout 8) — Fondo spinboxes timing

- `pulsenest_lab.py`: revertido cambio de stylesheet global de `HWConfigWindow`. Spinboxes del grupo Timing Registers: `background-color` ajustado a `#202020`.

---

## Sesión 2026-04-16 (fix layout 9) — Fondo #202020 en todos los spinboxes de HWConfigWindow

- `pulsenest_lab.py`: `background-color:#202020; color:#E0E0E0` aplicado a `_spin_led1`, `_spin_led2`, `_spin_sr`, `_spin_numav` (igual que los spinboxes del grupo Timing Registers).

---

## Sesión 2026-04-16 — Auto-lectura config al abrir HWConfigWindow

- `pulsenest_lab.py` `HWConfigWindow.__init__()`: añadida llamada `self._on_read_cfg()` al final del constructor para leer automáticamente la configuración del chip ($CFG? + $TCFG) cada vez que se abre la ventana. El botón "Read from chip" se mantiene para lecturas manuales adicionales.

---

## Sesión 2026-04-16 — Fix auto-lectura HWConfigWindow al arranque

- `pulsenest_lab.py`: la auto-lectura en `__init__` fallaba si el puerto serie aún no estaba abierto. Fix: tras una conexión serie exitosa, si `hw_config_window` está abierta se lanza `_on_read_cfg()` con `QTimer.singleShot(500ms)` para dar tiempo al ESP32 a arrancar antes de enviar `$CFG?`.

---

## Sesión 2026-04-16 — Fix delay auto-lectura HWConfigWindow

- `pulsenest_lab.py`: delay del `QTimer.singleShot` para auto-lectura al conectar 500→2000 ms. El ESP32 puede tardar hasta ~1.5 s en arrancar tras el reset por apertura del puerto serie.

---

## Sesión 2026-04-16 — Indicador dirty/clean en HWConfigWindow

- `pulsenest_lab.py` `HWConfigWindow`: cuando el usuario cambia el valor de un control sin haberlo enviado, el texto se pone en rojo (#FF4444). Al pulsar "Set" el color vuelve al normal (#E0E0E0).
  - Constantes de clase `_SPIN_SS_CLEAN/DIRTY` y `_TSPIN_SS_CLEAN/DIRTY`
  - Flag `_updating_from_cfg` para evitar marcar dirty durante actualizaciones desde $CFG/$TCFG
  - `_mark_dirty(widget)` / `_mark_clean(widget)`: aplican el stylesheet correcto según tipo (spinbox normal, timing spinbox, combobox)
  - `_make_row()`: conecta `valueChanged`/`currentIndexChanged` a `_mark_dirty` y pasa el widget al botón Set
  - `_make_set_btn()`: acepta `widget` opcional y llama `_mark_clean` tras el envío
  - `_spin_sr`: señal y widget añadidos manualmente (no pasa por `_make_row`)
  - Timing spinboxes: señal `_mark_dirty` añadida junto a `_on_timing_changed`
  - `_make_timing_set_btn()`: llama `_mark_clean` tras el envío
  - `update_from_cfg()`: protegido con `_updating_from_cfg = True/False`

---

## Sesión 2026-04-16 — Reset color dirty al recargar config en HWConfigWindow

- `pulsenest_lab.py`: `update_from_cfg()` llama `_mark_clean` en los 8 controles principales tras actualizar. `update_from_tcfg()` llama `_mark_clean` en todos los timing spinboxes tras actualizar. Así al cargar config (botón o auto al arrancar) todos los widgets vuelven al color normal.

---

## Sesión 2026-04-16 — Fix auto-lectura HWConfigWindow al arranque (2ª iteración)

Diagnóstico: al arrancar el script, `_connect_serial()` se ejecuta en línea (antes de que `_restore_settings()` haya creado `hw_config_window` vía `QTimer.singleShot(0,...)`). El timer anterior capturaba `self.hw_config_window` (que era `None`) y no se creaba.

Fix: en `_connect_serial()`, el `QTimer.singleShot` usa un lambda que evalúa `self.hw_config_window` en el momento de dispararse (2500 ms después), no en el momento de crearse. Para entonces `_open_hw_config_default()` ya ha creado la ventana. Cuando la ventana se abre manualmente, `__init__` sigue llamando `_on_read_cfg()` directamente (puerto ya estable).

---

## Sesión 2026-04-16 — Corrección tooltip wavelength IR

**Pregunta:** LED2 es IR o RED?
**Respuesta:** LED2 = RED (660 nm), LED1 = IR.

**Cambio:** tooltip de la señal IR en `pulsenest_lab.py` (línea 6119) actualizado de `~880 nm` a `~880–940 nm` para reflejar el rango típico de LEDs IR en sondas SpO2. Información meramente orientativa.

**Cambio:** tamaño de letra de todos los tooltips reducido en `_make_tooltip()`: nombre 32→30 px, texto 30→24 px.

**Cambio:** en `HWConfigWindow`, los labels de los Timing Registers ahora se crean como `QLabel` explícito (en lugar de string pasado a `addRow`), con el mismo tooltip que el spinbox. Así el tooltip aparece tanto sobre el número como sobre el texto de la izquierda.

**Cambio:** todas las ventanas secundarias (`HRLabWindow`, `PPGPlotsWindow`, `SerialComWindow`, `HR3LabWindow`, `SpO2LabWindow`, `SpO2TestWindow`, `HR1TestWindow`, `HR2TestWindow`, `HR3TestWindow`, `TimingWindow`, `HWConfigWindow`) ahora se instancian con `parent=None` en lugar de `self`. Criterio: todas las ventanas deben aparecer como entradas independientes en Alt-TAB de Windows (comportamiento estándar en apps de instrumentación).

**Fix:** al relanzar el script, usar siempre PowerShell (`Get-Process pythonw | Stop-Process -Force`) en lugar de `taskkill`, que no es fiable desde Git Bash en este sistema.

---

## Sesión 2026-04-16 — Fix botones que se quedaban en rojo al cerrar ventanas con Alt-F4

**Problema:** una sesión anterior cambió todas las ventanas secundarias a `parent=None` para independencia en Alt-TAB, pero no inyectó `main_monitor = self` tras la construcción. Al cerrar con Alt-F4, el `closeEvent` de cada ventana intentaba acceder a `self.main_monitor` (o `self.parent()`) para llamar `setChecked(False)` en el botón, pero ambas referencias eran `None` → el botón se quedaba en rojo (checked) aunque la ventana estuviera cerrada.

**Fix:** en cada función `toggle_X()`, añadida la línea `window.main_monitor = self` entre la construcción con `Window(None)` y el `show()`. Ventanas afectadas (11): `HRLabWindow`, `PPGPlotsWindow`, `SerialComWindow`, `HR3LabWindow`, `SpO2LabWindow`, `SpO2TestWindow`, `HR1TestWindow`, `HR2TestWindow`, `HR3TestWindow`, `TimingWindow`, `HWConfigWindow`.

**Fix adicional `TimingWindow`:** su `closeEvent` usaba `self.parent()` en lugar de `self.main_monitor` (inconsistente con el resto). Cambiado a `getattr(self, 'main_monitor', None)` para alinearlo con el patrón del resto de ventanas.

---

## Sesión 2026-04-16 — Auto-lectura HW CONFIG al abrir ventana y tras RESET ESP32

**Problema:** la ventana HW CONFIG no mostraba valores actuales al abrirse ni tras pulsar RESET ESP32 — había que pulsar manualmente "Read from chip".

**Causa raíz:** `_on_read_cfg()` se llamaba en `HWConfigWindow.__init__()` cuando `main_monitor` era aún `None` (se asigna después en `toggle_hw_config`), por lo que mostraba "Not connected" y no hacía nada.

**Fix 1 — `__init__`:** eliminada la llamada `_on_read_cfg()` del constructor (inútil con `main_monitor=None`).

**Fix 2 — `toggle_hw_config`:** añadido `QTimer.singleShot(200ms, _on_read_cfg)` tras inyectar `main_monitor` y hacer `show()`. Cubre el caso de abrir la ventana con el ESP32 ya corriendo.

**Fix 3 — `_reset_esp32`:** añadido `QTimer.singleShot(2500ms, _on_read_cfg)` tras el reset (mismo delay que al conectar el puerto), para dar tiempo al ESP32 a arrancar antes de solicitar la config.

El caso de conectar el puerto ya estaba cubierto con el timer de 2500ms en `_connect_serial`.

---

## Sesión 2026-04-16b — Botón "Set all" en HWConfigWindow

**Petición:** añadir botón "Set all" a la derecha del botón "Read from chip" en HWConfigWindow, que configure todos los parámetros de una sola vez.

**Implementación:**
- Los dos botones van en un `QHBoxLayout` en la parte superior de la ventana (`btn_top_row`).
- `btn_read` ocupa el espacio disponible (`stretch=1`); `btn_set_all` tiene ancho fijo al texto.
- Estilo verde igual a los botones "Set" individuales (`#1E3A1E` / `#88FF88`).
- Método `_on_set_all()`: envía `$SET` para los 8 parámetros HW (led1, led2, ledrange, tiagain, tiacf, stg2, sr, numav) y después para todos los registros de timing t1–t28 iterando `self._timing_spins`.
- Tras cada envío marca el widget como clean (color normal).
- Si hay violaciones de constraints de timing, la status bar lo muestra con `⚠`; si todo OK, muestra "Set all — sent N parameters".
- Tooltip descriptivo con `_make_tooltip()`.

---

## Sesión 2026-04-16c — Botones "Read from file" / "Save to file" en HWConfigWindow

**Petición:** añadir dos botones de fichero a la izquierda del botón "Read from chip" en HWConfigWindow.

**Formato de fichero elegido:** plain key=value, extensión `.pncfg`. Claves idénticas a las del protocolo `$SET`. Cabecera con fecha/hora como comentario `#`.

**Implementación:**
- Fila superior (izq → der): `[Read from file]` `[Save to file]` `[Read from chip ($CFG?)]` `[Set all]`
- Estilo ámbar (`#2D2010` / `#FFCC66`) para distinguirlos de azules (chip) y verdes (set).
- `_on_save_to_file`: guarda todos los valores de la UI (led1, led2, ledrange, tiagain, tiacf, stg2, sr, numav, t1–t28) al fichero seleccionado.
- `_on_read_from_file`: carga el fichero y aplica valores **sin** suprimir dirty marking (`_updating_from_cfg` queda en False). Los valores que cambien disparan `valueChanged`/`currentIndexChanged` → se marcan rojos automáticamente. Los que coinciden con la UI actual no emiten señal → quedan limpios.
- Último directorio guardado en `QSettings` bajo `HWConfigWindow/last_file_dir`.
- Añadido `from pathlib import Path` a los imports globales.

---

## Sesión 2026-04-16d — Comentarios inline en fichero .pncfg

**Petición:** añadir nombre de registro y descripción como comentario a la derecha de cada parámetro en el fichero .pncfg guardado por "Save to file".

**Implementación:**
- `_TIMING_REGS` movida de variable local en `_setup_ui` a atributo de clase, para que sea accesible desde `_on_save_to_file`.
- Helper `kv_line(key, value, comment)` formatea cada línea con `key=value` alineado a 20 chars y `# comment` a la derecha.
- Comentarios para parámetros HW: descripciones cortas (p.ej. "LED1 (IR) — IR LED drive current (mA)").
- Comentarios para timing t1–t28: `reg_name — tip` extraídos directamente de `_TIMING_REGS`.
- Parser `_on_read_from_file` actualizado: `v.split("#")[0].strip()` para ignorar comentarios inline al leer.

---

## Sesión 2026-04-16e — Ajuste padding comentarios .pncfg

Reducido el padding entre `key=value` y `# comment` de 20 a 15 caracteres en `kv_line()`.

---

## Sesión 2026-04-16f — Revertido ajuste padding comentarios .pncfg

Revertido el cambio de padding de 15 a 20 caracteres en `kv_line()`. Padding queda en 20.

---

## Sesión 2026-04-16g — Rehecho ajuste padding + fix kill pythonw

Rehecho: padding `kv_line()` de 20 → 15 caracteres en fichero .pncfg.

Fix relanzado: `taskkill /F /IM pythonw.exe` no mata los procesos en este entorno. Solución: `powershell -Command "Get-Process pythonw | Stop-Process -Force"`.

---

## Sesión 2026-04-16h — Bloqueo rueda ratón en spins/combos de HWConfigWindow

**Problema:** los QSpinBox y QComboBox cambiaban de valor al pasar la rueda del ratón por encima aunque no estuvieran activos, produciendo cambios indeseados.

**Solución:** clase `_WheelBlockFilter(QObject)` con `eventFilter` que ignora `QEvent.Wheel` si el widget no tiene foco. Se instala en todos los spins y combos de HWConfigWindow al final de `_setup_ui`, y se fija `FocusPolicy = StrongFocus` en cada uno.

---

## Sesión 2026-04-17 — Ventana Diagnostics (AFE4490 Diagnostic Module)

**Petición:** añadir botón en sidebar que abra ventana con resultados del Diagnostic Module del AFE4490.

**Fuente:** datasheet AFE4490 sección 8.4.3.3 (Table 3, Figure 130). El módulo chequea 9 tipos de fallo en secuencia y devuelve 11 flags en el registro DIAG (0x30, 13 bits significativos).

**Protocolo:** `$DIAG?` → `$DIAG,XXXXXX*YY\r\n` (6 dígitos hex del registro DIAG de 24 bits).

**Implementación:**

*Librería incunest_afe4490 (V15 y V16):*
- Nuevo método público `uint32_t runDiagnostics()`:
  - Retiene `_spi_mutex` durante todo el diagnóstico (~10 ms).
  - Motivo: el data task escribe `CONTROL0=0` tras cada lectura ADC (línea 848 del .cpp), lo que borraría DIAG_EN y aborta el diagnóstico. Con mutex retenido se bloquea el data task esos 10 ms (~2-3 muestras perdidas, aceptable para one-shot).
  - Secuencia: CONTROL0=0x000004 (DIAG_EN) → delay 10 ms → CONTROL0=0x000001 (SPI_READ) → leer REG_DIAG → CONTROL0=0x000000.
- Spec `incunest_afe4490_spec.md`: añadida sección 2.3c con tabla completa de bits y justificación del mutex. Actualizada nota del registro ALARM.

*Firmware main.cpp:*
- Nuevo comando `$DIAG?` en `Cmd_Task`: llama `afe.runDiagnostics()` y emite frame `$DIAG,XXXXXX*YY`.

*Python pulsenest_lab.py:*
- Nueva clase `DiagnosticsWindow`: tabla de 13 flags (OK verde / FAULT rojo), raw hex, botón "Run diagnostic ($DIAG?)", status bar, save/restore geometry.
- Botón `DIAGNOSTICS` en sidebar (después de HW CONFIG).
- Parser `$DIAG,` en serial reader → `_on_diag_frame_received()`.
- `diag_window` gestionado igual que las demás ventanas secundarias (toggle, closeEvent, close-all).

---

## Sesión 2026-04-17b — runDiagnostics en repo real + documentación platformio.ini

### Corrección: runDiagnostics() solo existía en la caché de PlatformIO

**Problema detectado:** `runDiagnostics()` fue añadida en la sesión anterior directamente en `.pio\libdeps\incunest_V16\incunest_afe4490` (caché de PlatformIO), no en el repo real `C:\PRJ\MOW\incunest_afe4490`. Si PlatformIO limpiaba la caché, la función se perdía.

**Corrección:** se copió `runDiagnostics()` al repo real de la librería:
- `incunest_afe4490.h`: declaración pública bajo `#ifndef INCUNEST_OFFLINE`
- `incunest_afe4490.cpp`: implementación completa (igual que en la caché)
- `incunest_afe4490_spec.md`: bumped a v0.22, añadida sección 2.5b con tabla de 13 bits y justificación del mutex
- Commit + push a GitHub: `feat: v0.22 — runDiagnostics() hardware self-test`

### Documentación del sistema de dos fuentes en platformio.ini

**Contexto aclarado:** la librería existe en dos lugares por razones distintas:
- `C:\PRJ\MOW\incunest_afe4490` → repo local de la librería (fuente de verdad)
- `C:\PRJ\MOW\PulseNest\lib\incunest_afe4490` → symlink al repo local (creado en sesión anterior)
- `C:\PRJ\MOW\PulseNest\.pio\libdeps\...\incunest_afe4490` → caché de PlatformIO (descargada de GitHub)

**Resolución de PlatformIO (prioridad):**
1. `lib/` del proyecto → usa symlink → repo local (sin push necesario)
2. `lib_deps` URL GitHub → fallback para otras máquinas / CI

**Documentado en `platformio.ini`:** comentario explicativo con ambas opciones y comando `mklink` para reproducir el symlink en máquina nueva. Commit + push a PulseNest.

### Build y flash

- Build para `incunest_V16` (V15 no compila: usa `AFE4490TimingConfig`/`setTimingReg` que solo existen en V16).
- Flash OK en COM15 tras cerrar pulsenest_lab.py.

---

## Sesión 2026-04-17c — Limpieza platformio.ini y flujo de librería

**Tema:** reorganización del sistema de dependencias de `incunest_afe4490` y documentación de `platformio.ini`.

**Decisiones:**

- Eliminada la URL de GitHub de `lib_deps` en `platformio.ini`. La librería se sirve exclusivamente desde `lib/incunest_afe4490` (symlink o copia directa). Esto elimina la caché redundante en `.pio\libdeps\` que podía ser editada por error.
- Documentadas dos opciones en `platformio.ini`:
  - **Opción A (desarrollador de librería):** symlink `lib/incunest_afe4490` → repo local. Cambios visibles en el siguiente build sin push.
  - **Opción B (usuario de librería):** clone directo en `lib/incunest_afe4490`. Sin symlink ni permisos de administrador.
- Nota añadida para advertir que los paths del ejemplo son específicos de la máquina de referencia y deben adaptarse.
- Build verificado OK con `incunest_V16` sin `lib_deps`.

---

## Sesión 2026-04-17d — Fix runDiagnostics() en incunest_afe4490

**Tema:** corrección del comportamiento de `runDiagnostics()` durante la adquisición continua de datos.

**Análisis:**

- Pregunta inicial: ¿continúa la recepción de datos durante `runDiagnostics()`?
- Traza exacta: `runDiagnostics()` sostenía `_spi_mutex` durante 10 ms (incluyendo `vTaskDelay`). `_task_body()` (prioridad 5) bloqueaba en el mutex. La semáfora binaria `_drdy_sem` colapsaba los DRDY intermedios.
- Resultado antes del fix: 5 DRDYs en 10 ms → solo 2 lecturas post-diagnóstico (back-to-back sin DRDY entre medias, potencialmente duplicadas), 3 muestras perdidas.
- La `_data_queue` no puede compensar: es un buffer de muestras ya procesadas, no de registros ADC del chip.

**Decisión de diseño:**

- Fix dentro de la librería (transparente para el usuario): flag `_diag_active`.
- `runDiagnostics()` activa el flag → toma mutex brevemente para escribir DIAG_EN → libera mutex → duerme 10 ms → lee DIAG → desactiva flag.
- `_task_body()` añade dos checks: fast path tras `_drdy_sem` y race guard tras `_spi_mutex`.
- Durante los 10 ms, `_task_body()` consume cada DRDY limpiamente sin tocar el SPI bus. Reanudación limpia en el siguiente DRDY real.
- El gap de ~10 ms (≈5 muestras a 500 Hz) es inevitable por limitación hardware.
- Mejoras respecto al código anterior: sin hold largo del mutex, sin lecturas espurias post-diagnóstico, sin inversión de prioridad.

**Ficheros modificados:**

- `incunest_afe4490/incunest_afe4490.h` — v0.20 → v0.22: `volatile bool _diag_active` en sección FreeRTOS privada.
- `incunest_afe4490/incunest_afe4490.cpp` — constructor inicializa `_diag_active(false)`; `runDiagnostics()` y `_task_body()` actualizados.
- `incunest_afe4490/incunest_afe4490_spec.md` — v0.22: sección 2.5b reescrita, entrada v0.22 en changelog.

---

## Sesión 2026-04-17e — Simplificación race guard en _task_body()

**Tema:** eliminación del race guard redundante en `_task_body()`.

**Análisis:**

- La línea 937 (`if (_diag_active) { xSemaphoreGive(_spi_mutex); continue; }`) era un race guard para el caso en que `runDiagnostics()` activara el flag entre la comprobación rápida (línea 930) y el `xSemaphoreTake(_spi_mutex)` (línea 936).
- En esta plataforma la race es imposible: `_task_body` (prioridad 5) y `Cmd_Task` (prioridad 2) están ambas en core 0. FreeRTOS no puede preemptar una tarea de mayor prioridad en favor de una de menor sin llamada bloqueante. Entre líneas 930 y 936 no hay ninguna.
- La línea 937 se eliminó. Comportamiento observable idéntico.

**Ficheros modificados:**

- `incunest_afe4490/incunest_afe4490.cpp` — eliminada línea de race guard en `_task_body()`.

---

## Sesión 2026-04-18 — Muestra repetida durante runDiagnostics()

**Tema:** mejora del comportamiento durante el diagnóstico: sustituir el gap de muestras por repetición de la última muestra válida.

**Análisis previo (correcciones):**
- Gap vs. muestra repetida en filtros IIR: ambas opciones producen la misma discontinuidad en la entrada del filtro al reanudar (`|nueva_muestra - última_válida|`). El estado del filtro sí se preserva con el gap, pero el salto al reanudar es igual en ambos casos.
- Gap vs. muestra repetida en HR1/HR2/HR3: el gap rompe el equiespaciado temporal que asumen autocorrelación (HR2) y FFT (HR3), introduciendo distorsión de fase y espectral. La muestra repetida preserva la continuidad temporal — es claramente superior.
- HR1: el gap introduce error temporal en los intervalos RR (el índice de muestras no avanza). La muestra repetida preserva el timing.

**Decisión:** implementar muestra repetida. Es equivalente en filtros IIR y mejor en HR1/HR2/HR3.

**Implementación:**
- En `_task_body()`, cuando `_diag_active=true`, en lugar de `continue` directo se copia `_current_data` a la queue bajo `_state_mutex`, preservando la misma lógica de drop-oldest que usa `_process_sample()`.
- Completamente transparente para el usuario de la librería.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.cpp` — `_task_body()`: muestra repetida bajo `_state_mutex` durante diagnóstico.
- `incunest_afe4490/incunest_afe4490_spec.md` — §2.5b y changelog v0.22 actualizados con el rationale.

---

## Sesión 2026-04-19 — runDiagnostics: parámetro diag_holdoff_ms

**Tema:** añadir post-diagnostic holdoff a `runDiagnostics()` para neutralizar los artefactos de re-asentamiento del front-end analógico tras el diagnóstico.

**Debate de diseño:**
- Propuesta inicial de Claude: suspender los algoritmos durante el holdoff.
- Corrección de Alex: los algoritmos nunca se detienen. El holdoff debe sustituir las muestras problemáticas por datos congelados con la menor influencia posible en los algoritmos.
- Análisis: un outlier de diagnóstico (spike grande) es mucho más dañino para HR1/HR2/HR3/SpO2 que un valor constante repetido. Los filtros IIR/BPF/LP absorben entrada constante con salida AC ≈ 0. El valor repetido es la estrategia correcta.
- Orden de asignación en `runDiagnostics()`: `_diag_holdoff_samples` se escribe ANTES de limpiar `_diag_active` para evitar la race condition.
- Valor por defecto: 100 ms (~50 muestras a 500 Hz), cubre holgadamente el peor caso de re-asentamiento analógico.
- diag_holdoff_ms=0: observar artefactos reales (útil para debugging).

**Decisión:** implementar `runDiagnostics(uint32_t diag_holdoff_ms = 100)`.
- Los raw ADC values se guardan en cada ciclo normal de `_task_body()` y se reutilizan durante el holdoff.
- `_process_sample()` se llama con los valores congelados → los algoritmos procesan normalmente entrada neutral.
- Acceso a `_diag_last_*` exclusivo de `_task_body()` → sin mutex necesario.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h` — nueva firma, nuevos miembros privados, v0.23.
- `incunest_afe4490/incunest_afe4490.cpp` — constructor, `runDiagnostics()`, `_task_body()`.
- `incunest_afe4490/incunest_afe4490_spec.md` — §2.5b y changelog v0.23.

---

## Sesión 2026-04-21 — diag_holdoff_ms: ajuste del valor por defecto

**Tema:** revisión del default de `diag_holdoff_ms` en `runDiagnostics()`.

**Análisis:** 100 ms era excesivo. El tiempo de re-asentamiento real del TIA es 5τ = RF×CF×5. Peor caso (RF_1M + CF_155P): 5τ ≈ 775 µs, menos de un sample a 500 Hz. Con margen conservador de 2-3 ciclos PRP, 10 ms cubre holgadamente el peor caso.

**Decisión:** default cambiado de 100 ms a **10 ms** (~5 samples a 500 Hz).

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h` — default `diag_holdoff_ms = 10`, comentario actualizado con justificación de settling.
- `incunest_afe4490/incunest_afe4490_spec.md` — §2.5b y changelog v0.23 actualizados.

---

## Sesión 2026-04-21b — Persistencia de DiagnosticsWindow

**Tema:** la ventana DIAGNOSTICS no recordaba su estado abierto/cerrado al cerrar el script de forma forzada.

**Causa:** `_save_settings()` guardaba la geometría de `DiagnosticsWindow` pero no la clave `PPGMonitor/diagnostics_open`. `_restore_settings()` tampoco la reabría. `_bring_all_to_front()` tampoco incluía `diag_window`.

**Fix:** 4 cambios en `pulsenest_lab.py`:
1. `_save_settings()` — añadida clave `PPGMonitor/diagnostics_open`.
2. Nuevo método `_open_diagnostics_default()` — patrón idéntico al resto de ventanas.
3. `_restore_settings()` — reabrir `DiagnosticsWindow` si `diagnostics_open` era True.
4. `_bring_all_to_front()` — añadida `diag_window` a la lista de ventanas a traer al frente.

---

## Sesión 2026-04-21c — Lab Capture CSV: encoding UTF-8-sig

**Tema:** el CSV de Lab Capture fallaba al guardar caracteres como "Ω" (TIA: 500K Ω).

**Causa:** `open(filepath, "w", buffering=1)` sin `encoding` → Python usa cp1252 (Windows default) → Ω (U+03A9) no existe en cp1252 → excepción.

**Decisión:** `encoding="utf-8-sig"` (UTF-8 con BOM). Cubre cualquier Unicode en notas del usuario y en cadenas de config. Excel en Windows detecta el BOM y abre el CSV correctamente.

**Ficheros modificados:**
- `pulsenest_lab.py` — línea `open(filepath, "w", buffering=1)` → `open(filepath, "w", buffering=1, encoding="utf-8-sig")`.

---

## Sesión 2026-04-23 — Diagnóstico outlier serial + fix validación checksum $M1/$M2

**Tema:** outlier simultáneo en los 6 canales recibidos en pulsenest_lab.py.

**Diagnóstico:**
- Valores RED=20,969,268,024 e IR=129,815,102 superan el límite 24-bit del AFE4490 (2²⁴=16,777,216) → imposible que vengan del AFE.
- Los campos 3–6 del frame corrupto coinciden con los valores normales de los campos 1–4 → frame desplazado dos posiciones. Causa: byte separador perdido en UART que concatenó dígitos adyacentes.
- La validación XOR ya existía en el script (líneas 7561–7583), pero tenía una laguna: frames `$M1`/`$M2` sin campo `*XX` pasaban sin validar (el `else` no los rechazaba).
- El firmware tiene `chk_amb_sub` para verificar `led_sub == led - aled` a nivel AFE/SPI, pero está desactivado (`// #define CHK_AMB_SUB`). Es una capa ortogonal (errores AFE vs. errores UART), no necesita acoplarse al check Python.

**Fix implementado (`pulsenest_lab.py`):**
Tres casos nuevos de rechazo de frames `$M1`/`$M2`:
1. `*XX` presente pero mal formado (`len ≠ 2`) → rechazado + log `# BAD CHK (malformed *field)`.
2. `*XX` ausente en frame de datos → rechazado + log `# BAD CHK (no checksum field)` + `chk_ok=0` en fichero `--save-chk`.
3. Frames sin `*XX` que no sean datos (`$ERR`, etc.) → siguen pasando sin cambio.

**Ficheros modificados:**
- `pulsenest_lab.py` — bloque de validación checksum NMEA en el hilo serial.

---

## Sesión 2026-04-23

### Tema: Renombrado de `setNumAverages` → `setAdcAverages`

**Decisión:**
`setNumAverages` era ambiguo (podría referirse a promedios en algoritmos de cálculo). Se renombra a `setAdcAverages` para dejar claro que el averaging ocurre en la fase de adquisición ADC (hardware), no en el software.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h` — declaración del método
- `incunest_afe4490/incunest_afe4490.cpp` — definición + log de error interno
- `incunest_afe4490/incunest_afe4490_spec.md` — todas las ocurrencias (§2.3, §7.x, tabla de parámetros, tabla registro CONTROL1, changelog v0.3)
- `PulseNest/src/main.cpp` — llamada en el handler del protocolo $SET

---

## Sesión 2026-04-23b

### Tema: Prefijos de dominio en `AFE4490Config`

**Decisión:**
Los campos del struct `AFE4490Config` se renombran con prefijos de dominio para que cada campo sea inequívocamente identificable sin leer su comentario:

- `afe_` → parámetros del chip AFE4490 (escritos vía SPI): `afe_sample_rate_hz`, `afe_adc_averages`, `afe_led1_current_mA`, `afe_led2_current_mA`, `afe_led_range_mA`, `afe_tia_gain`, `afe_tia_cf`, `afe_stage2_gain`
- `ppgdisp_` → parámetros de visualización PPG (procesado en ESP32, sin escritura HW): `ppgdisp_channel`, `ppgdisp_filter_type`, `ppgdisp_f_low_hz`, `ppgdisp_f_high_hz`
- `hr2_`, `hr3_`, `spo2_` → sin cambio (ya tenían prefijo)

El patrón es ahora consistente: todos los campos del struct tienen prefijo de subsistema.
Los miembros privados (`_sample_rate_hz`, etc.) no se tocan — son implementación interna.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h` — struct `AFE4490Config`
- `incunest_afe4490/incunest_afe4490.cpp` — bloque `getConfig()`
- `incunest_afe4490/incunest_afe4490_spec.md` — definición del struct en §2.3b
- `PulseNest/src/main.cpp` — accesos `cfg.xxx` en el serializador `$CFG`

---

## Sesión 2026-04-24

### Tema: Exposición de parámetros de algoritmo en AFE4490Config

**Decisión:**
Se exponen en `AFE4490Config` y se hacen configurables en runtime 16 parámetros que estaban hardcoded como `static constexpr`:

- **SpO2 (8):** `spo2_warmup_s`, `spo2_dc_iir_tau_s`, `spo2_ac_ema_tau_s`, `spo2_min`, `spo2_max`, `spo2_min_dc`, `spo2_pi_sqi_lo`, `spo2_pi_sqi_hi`
- **HR1 (3):** `hr1_dc_tau_s`, `hr1_ma_cutoff_hz`, `hr1_sqi_cv_max`
- **HR2 (2):** `hr2_min_corr`, `hr2_update_interval`
- **HR3 (1):** `hr3_update_interval`
- **HR global (2):** `hr_min_bpm`, `hr_max_bpm`

`hr_search_{min,max}_bpm` ya no son constexpr: se derivan en el algoritmo como `_hr_{min,max}_bpm ± 3 BPM`.
`hr2_min_lag_s` también eliminado: se calcula inline como `60 / (_hr_max_bpm + 3) * fs2`.
`hr2_update_interval` y `hr3_update_interval` pasan de `static constexpr int` a miembros de instancia `_hr2/3_update_interval`.

Se añaden 13 setters (`setSpO2WarmupS`, `setSpO2DcIirTauS`, `setSpO2AcEmaTauS`, `setSpO2Range`, `setSpO2MinDC`, `setSpO2PiSqiThresholds`, `setHR1DcTauS`, `setHR1MaCutoffHz`, `setHR1SqiCvMax`, `setHR2MinCorr`, `setHR2UpdateInterval`, `setHR3UpdateInterval`, `setHRValidRange`).

Los que modifican parámetros usados en `_recalc_rate_params()` llaman a ese método internamente.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h` — struct, setters, private members
- `incunest_afe4490/incunest_afe4490.cpp` — constructor, _recalc_rate_params, algoritmos, getConfig, setters
- `incunest_afe4490/incunest_afe4490_spec.md` — struct §2.3b, nueva §2.5, changelog v0.21

---

## Sesión 2026-04-24b

### Tema: Prefijos de dominio en miembros privados de INCUNEST_AFE4490

**Decisión:**
Se aplican los mismos prefijos de dominio a los miembros privados de la clase (19 renombrados):

- `afe_` (8): `_sample_rate_hz`→`_afe_sample_rate_hz`, `_num_averages`→`_afe_adc_averages`, `_led1/2_current_mA`→`_afe_led1/2_current_mA`, `_led_range_mA`→`_afe_led_range_mA`, `_tia_gain`→`_afe_tia_gain`, `_tia_cf`→`_afe_tia_cf`, `_stage2_gain`→`_afe_stage2_gain`
- `ppgdisp_` (5): `_ppg_channel`→`_ppgdisp_channel`, `_filter_type`→`_ppgdisp_filter_type`, `_ppg_bpf`→`_ppgdisp_bpf`, `_ma_buf/idx/sum`→`_ppgdisp_ma_buf/idx/sum`
- `spo2_` (6): `_dc_iir_alpha`→`_spo2_dc_iir_alpha`, `_ac_ema_beta`→`_spo2_ac_ema_beta`, `_dc_ir/red`→`_spo2_dc_ir/red`, `_ac2_ir/red`→`_spo2_ac2_ir/red`

La función privada `_recalc_tia_cf()` también renombrada a `_recalc_afe_tia_cf()` por coherencia.

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`

---

## Sesión 2026-04-24c

### Tema: Prefijos de dominio en constexpr del namespace anónimo + reorganización

**Decisión 1:** `dc_iir_tau_s` y `ac_ema_tau_s` carecían de prefijo → renombrados a `spo2_dc_iir_tau_s` y `spo2_ac_ema_tau_s`.

**Decisión 2:** Las "Algorithm time constants" eran un grupo legacy que mezclaba dominios. Se reorganizan todos los constexpr del namespace anónimo por dominio:
- `// ── Math ──` → pi
- `// ── SpO2 ──` → spo2_warmup_s, spo2_dc_iir_tau_s, spo2_ac_ema_tau_s, spo2_a/b_default, spo2_min/max, spo2_clamp_margin, spo2_min_dc, spo2_pi_sqi_lo/hi
- `// ── HR1 ──` → hr1_dc_tau_s, hr1_ma_cutoff_hz, hr1_sqi_cv_max
- `// ── HR2 ──` → hr2_min_corr
- `// ── HR3 ──` → hr3_decim_factor
- `// ── HR (all) ──` → hr_refractory_s, hr_min_bpm, hr_max_bpm

**Decisión 3:** Eliminados 3 constexpr muertos: `hr2_min_lag_s`, `hr_search_min_bpm`, `hr_search_max_bpm` (ya habían sido reemplazados inline en sesión anterior).

**Ficheros modificados:**
- `incunest_afe4490/incunest_afe4490.cpp`

---

## Sesión 2026-04-24d

### Tema: Verificación firmware tras refactoring de prefijos

Firmware subido con `incunest_V16` y verificado en placa. El LED de la sonda funcionó correctamente tras el upload — el problema inicial era de conexión/timing hardware, no del código. Todos los renombrados de prefijos de dominio (private members, constexpr namespace) son correctos.

`pulsenest_lab.py` tiene cambios pendientes de commitear (de sesión anterior, no relacionados con el refactoring de hoy).

---

## Sesión 2026-04-25d

### Tema: PPGSignalsWindow — alineación horizontal de los ejes Y

**Problema:** Los tres plots (RED, IR, PPGdisp) tenían el eje Y izquierdo de ancho variable según el número de dígitos del rango, desalineando las áreas de plot.

**Decisión:** `setWidth(80)` en el `AxisItem` izquierdo de `p1`, `p2` y `p3`. Ancho fijo de 80 px garantiza alineación independientemente del rango Y.

**Ficheros modificados:**
- `pulsenest_lab.py` — tres llamadas `getAxis('left').setWidth(80)` en `PPGSignalsWindow._setup_ui`.

---

## Sesión 2026-04-25c

### Tema: Fix ancho controles en submenús de plots (monkey-patch ViewBoxMenu)

**Problema:** Los controles (spinboxes, radiobuttons) dentro de los submenús "X axis" / "Y axis" del menú contextual de pyqtgraph seguían siendo estrechos a pesar de `QMenu { min-width: 360px }`. Causa raíz: `axisCtrlTemplate_generic.py` hace `Form.setMaximumSize(QSize(200, ...))` — un límite programático que ningún CSS puede superar.

**Decisión:** Monkey-patch de `ViewBoxMenu.__init__` aplicado una vez al arrancar el script. Tras la inicialización original, itera los submenús, llama `w.setMaximumWidth(16777215)` (elimina el límite de 200 px) y `w.setMinimumWidth(360)` sobre cada widget de los `QWidgetAction`. Se aplica a todos los plots del script sin necesidad de modificar pyqtgraph.

**Ficheros modificados:**
- `pulsenest_lab.py` — función `_patch_viewbox_menu()` añadida tras `_MOUSE_HINT`.

---

## Sesión 2026-04-25b

### Tema: Fix QMenu::item min-width en menús contextuales de plots

**Problema:** `QMenu { min-width: 360px; }` ampliaba el marco del menú pero los items (`QMenu::item`) no se estiraban para llenarlo — el contenido seguía estrecho.

**Decisión:** Añadir `QMenu::item { min-width: 340px; padding: 4px 20px 4px 28px; }` al stylesheet global para forzar que las filas de texto ocupen el ancho completo del menú.

**Ficheros modificados:**
- `pulsenest_lab.py` — stylesheet global actualizado.

---

## Sesión 2026-04-25

### Tema: Nueva tarea prioridad máxima + división de PPGPlotsWindow

**Tarea añadida (prioridad máxima):** Resolver saturación del ADC del AFE4490 por exceso de luz ambiental intensa (cerca de ventana). Guardada en memoria `project_ambient_saturation_task.md`.

**División de PPGPlotsWindow en dos ventanas:**

**Decisión de diseño:** PPGPlotsWindow mezclaba señales AFE4490 con resultados de algoritmos. Se separa en dos ventanas independientes.

- **PPGSignalsWindow** (botón `SIGNALS`): muestra las 6 señales del AFE4490 (RED raw/amb/sub, IR raw/amb/sub) + señal PPGdisp (antes llamada PPG en el script). 3 plots en columna dentro de un GraphicsLayoutWidget. Sidebar con checkboxes RED/IR idéntico al anterior. Throttle 25 Hz.
- **AlgoResultsWindow** (botón `RESULTS`): muestra SpO2 (arriba) + HR1/HR2/HR3 (abajo). 2 plots en columna. Sin sidebar. Throttle 10 Hz.

**Rename:** `data_ppg` → `data_ppgdisp` en todo el script Python. El campo de la trama serie sigue siendo `PPG` (viene del firmware). El label en la tabla SIGNAL STATS pasa de `PPG` a `PPGdisp`.

**PPGPlotsWindow:** se mantiene intacta por ahora. Se eliminará cuando se confirme que las dos nuevas ventanas cubren toda su funcionalidad.

**Ficheros modificados:**
- `pulsenest_lab.py` — nuevas clases `PPGSignalsWindow` y `AlgoResultsWindow`, botones `SIGNALS`/`RESULTS`, métodos toggle/open, loop de refresh, showEvent, closeEvent, bring-to-front.

---

## Sesión 2026-04-28 — AMBDAC: hardware ambient cancellation exposed + RSQM design

### Tema: Saturación ADC por luz ambiental (PRIORIDAD MÁXIMA)

**Problema:** El AFE4490 hace cancelación de ambiente por hardware (LED_on − LED_off), pero si aled1/aled2 saturan el ADC durante la fase LED_off, la sustracción falla. El registro DIAG (0x30) no tiene bit de saturación ambiental — la detección debe ser por software.

**Solución a corto plazo:** Exponer AMBDAC (único parámetro de cancelación ambiental hardware) en la ventana HW CONFIG para que el usuario pueda ajustarlo cuando la señal ambiental sea excesiva.

### Decisiones de diseño — RawSignalQualityMonitor (RSQM)

Se diseñó una arquitectura de supervisión de señal en bruto:
- **Nombre:** `RawSignalQualityMonitor` (RSQM)
- **Ejecución:** inline en `_process_sample()` (Task A, 500 Hz) — no es una FreeRTOS task separada
- **Salida por muestra:** `float rsqi` [0.0–1.0] + `uint16_t diag_code` (bitmask)
- **RSQI v1:** binario (1.0 = limpio, 0.0 = problema); v2: continuo
- **RSQI único** = min(IR quality, RED quality) — no por canal
- **DiagCode:** bit0 AMB_SAT_IR, bit1 AMB_SAT_RED, bit2 SIGNAL_WEAK_IR, bit3 SIGNAL_WEAK_RED, bit4 HW_SETTLING (reservado), bit5 HW_ADJUSTED (reservado)
- **RSQM NO modifica SQI** de ningún algoritmo consumidor — cada algoritmo decide
- **HR2/HR3:** opción B — contador de muestras inválidas por ventana (sin buffer por muestra)
- **"Raw"** = lo que entrega el AFE con su configuración actual; las correcciones HW afectan muestras futuras, no la actual
- v2 del RSQM coincide con project_agc_readjust_task (AGC dinámico)
- **Implementación aplazada** — guardada en memory/project_rsqm_task.md

### Tarea implementada esta sesión: AMBDAC en HW CONFIG

**Parámetro:** AMBDAC[3:0] en TIA_AMB_GAIN D19:D16 (4-bit, 0–10 µA, 1 µA/step).

**Ficheros modificados:**
- `incunest_afe4490.h` — `setAmbDac(uint8_t uA)` setter, `afe_ambdac_uA` en `AFE4490Config`, `_afe_ambdac_uA` private member
- `incunest_afe4490.cpp` — constructor init, setter con `_apply_analog_regs()`, `_apply_analog_regs()` aplica `tia | ((uint32_t)_afe_ambdac_uA << 16)` a TIA_AMB_GAIN, `getConfig()` rellena campo
- `src/main.cpp` — `apply_set_cmd()` case `"ambdac"`, `send_cfg_frame()` añade campo `ambdac=%u`
- `pulsenest_lab.py` — nuevo `QGroupBox("Ambient Cancellation")` entre TIA Gain y Sampling, `_spin_ambdac` QSpinBox 0–10 µA, actualizado `_on_set_all`, `_on_save_to_file`, `_on_read_from_file`, `update_from_cfg`
- `incunest_afe4490_spec.md` — `setAmbDac()` en API, `afe_ambdac_uA` en AFE4490Config, tabla parámetros actualizada, versión bump v0.24→v0.25

## Sesión 2026-04-29 — Fix AMBDAC: STAGE2EN2 requerido + nuevas tareas

### Tema: AMBDAC no producía ningún efecto en las señales

**Diagnóstico:** AMBDAC requiere que Stage 2 esté activo para tener efecto. Stage 2 no es solo un amplificador — es el bloque encargado de la cancelación ambiental. El bit STAGE2EN2 (D14 de TIA_AMB_GAIN) activa Stage 2 para las fases ambientales (aled1/aled2). Con `stg2=0dB` (Stage 2 desactivado), nuestro código escribía `0x000000` en TIAGAIN → bit D14=0, y al copiar `tia` a TIA_AMB_GAIN también quedaba STAGE2EN2=0 → AMBDAC sin efecto.

**Hallazgo clave (usuario):** STAGE2EN1 (TIAGAIN D14) y STAGE2EN2 (TIA_AMB_GAIN D14) son independientes incluso con ENSEPGAIN=0. AMBDAC actúa inyectando corriente en Stage 2; sin STAGE2EN2=1, la corriente no tiene camino al ADC.

**Fix aplicado:** En `_apply_analog_regs()`, cuando `_afe_ambdac_uA > 0`, se fuerza STAGE2EN2=1 en TIA_AMB_GAIN independientemente del Stage 2 de los canales LED:
```cpp
uint32_t amb = tia | ((uint32_t)_afe_ambdac_uA << 16);
if (_afe_ambdac_uA > 0) amb |= 0x004000UL;  // STAGE2EN2 required for AMBDAC
_write_reg(REG_TIA_AMB_GAIN, amb);
```

**Ficheros modificados:**
- `incunest_afe4490.cpp` — `_apply_analog_regs()`: fix + comentarios actualizados
- `incunest_afe4490_spec.md` — tabla parámetros y version bump v0.25 → v0.25b

### Nuevas tareas añadidas

- **Tarea #5:** Investigar por qué hay bleed de LEDs en la medida ambiental (probablemente timing)
- **Tarea #6:** Detector de sonda desconectada en RSQM (todos los canales ~-4000 counts)
- **Tarea #7:** Estudiar efecto de FLTRCNRSEL en tiempo de asentamiento post-diagnóstico (500 Hz: ~28 ms, 1000 Hz: ~16 ms)

## Sesión 2026-04-24e

### Tema: Indicador visual `*` en botones del sidebar para ventanas a 500 Hz

**Pregunta:** ¿Qué ventanas del sidebar trabajan con señales PPG sin diezmar (antes del gate de `spin_decim`)?

**Análisis:** Solo dos ventanas reciben datos PPG a tasa completa (500 Hz), antes del gate de decimación:
- **HR1TEST** — `hr1test_calc.update()` se alimenta a 500 Hz (el display sí usa datos decimados)
- **CAPTURE LAB** — guarda a tasa completa antes del gate

El resto (PPGPlots, HRLab, HR3Lab, SpO2Lab, SpO2Test, HR2TEST, HR3TEST, SerialCom) usan datos decimados. Timing, HW Config y Diagnostics no son PPG — reciben tramas de control propias que no pasan por el gate.

**Decisión:** Añadir `*` al label de los botones `HR1TEST` y `CAPTURE LAB` para indicar visualmente que operan a frecuencia original. El tooltip de cada uno explica: `* = runs at full 500 Hz rate, unaffected by the Decimation setting`.

**Ficheros modificados:**
- `pulsenest_lab.py` — labels `"HR1TEST *"` / `"CAPTURE\nLAB *"` y tooltips actualizados; la explicación del `*` comienza tras `<br/>` (salto de línea HTML)

## Sesión 2026-04-30 — Diseño HGAC + fix cierre ventanas secundarias

### Tema 1: Diseño conceptual del sistema de control analógico (RSQM + HGAC)

**Discusión:** El control del exceso de luz ambiental y la degradación de señal puede gestionarse mediante un sistema que controle LEDCURRENT, RF, RG y AMBDAC. Se debatió si este sistema (HGAC) debería estar dentro del RSQM o ser un módulo separado.

**Decisiones de diseño:**

- **Nombre acordado:** HGAC (Hardware Gain/Ambient Controller)
- **Separación obligatoria de RSQM y HGAC:** RSQM observa y califica (por muestra, 500 Hz). HGAC actúa sobre hardware (~2 Hz, sobre condición sostenida). Los artefactos de movimiento son detectables por RSQM pero NO son corregibles por HGAC.
- **Entrada de HGAC:** `RSQMResult` completo (no raw ADC). Incluye `diag_code` (qué está mal) + `amb_ir_pct`, `amb_red_pct`, `sig_ir_pct`, `sig_red_pct` (cuánto ajustar). El RSQM normaliza los counts ADC → HGAC no conoce el formato del AFE4490.
- **No ahora:** Módulo HWSETTER descartado por prematuro. Los setters de la librería ya cubren esa función. Si en el futuro hay 3+ escritores concurrentes, se reconsiderará.
- **Orden de implementación:** RSQM primero → validar en banco → HGAC después.
- **Política de ficheros de tarea en memory/:** Completadas → conservar con `status: done`. Canceladas/obsoletas/absorbidas → borrar.

**Preguntas abiertas de HGAC (pendientes de respuesta del usuario):**
- Paso de ajuste: ¿fijo o proporcional al error?
- RF/RG compartidos (ENSEPGAIN=0): política ante IR saturado y RED débil simultáneamente
- AMBDAC: ¿por canal o compartido? (verificar datasheet)
- Conflicto AMB_SAT + SIGNAL_WEAK simultáneos con RF/RG implicados
- Histéresis alrededor del punto de operación objetivo
- Límites de ajuste seguros por parámetro
- Tiempo de ventana de acumulación de diag_code antes de actuar

**Cambios en memory/:**
- Creado `project_hgac_task.md` — diseño conceptual HGAC completo
- Eliminados `project_ambient_saturation_task.md` (absorbida por RSQM) y `project_agc_readjust_task.md` (absorbida por HGAC)
- Creado `feedback_memory_file_policy.md` — política de gestión de ficheros de tarea

### Tema 2: Bug — ventanas secundarias no se cerraban al cerrar el script

**Síntoma:** Al cerrar la ventana principal de `pulsenest_lab.py`, las ventanas secundarias (PPGSignalsWindow, AlgoResultsWindow, etc.) permanecían abiertas.

**Causa raíz:** En `PPGMonitor.closeEvent()`, la línea:
```python
if hasattr(self, '_reader_thread'):
    self._reader_thread.join(timeout=1.0)
```
`_reader_thread` se inicializa a `None` en `__init__` y solo se asigna a un thread real al conectar un puerto serie. `hasattr()` devuelve `True` (el atributo existe), pero el valor es `None` → `None.join()` lanza `AttributeError` → `closeEvent` aborta antes de llegar a las llamadas `close()` de las ventanas secundarias. El `QCloseEvent` se acepta por defecto y la ventana principal se cierra, dejando las secundarias huérfanas. Bug latente solo cuando no hay puerto serie conectado.

**Fix:**
```python
if hasattr(self, '_reader_thread') and self._reader_thread is not None:
    self._reader_thread.join(timeout=1.0)
```

**Ficheros modificados:**
- `pulsenest_lab.py` — `PPGMonitor.closeEvent()`: añadido `and self._reader_thread is not None`

## Sesión 2026-05-02 — RSQM diseño ampliado + HR3 explicación + hr_min_bpm

### Tema 1: RSQM — rsqi como float + HPS-Index + PI-Index

**Decisiones:**
- `rsqi` será `float` [0.0–1.0] desde v1 (aunque v1 sea binario), pensando en v2 continuo.
- v1: `rsqi = (diag_code == 0) ? 1.0f : 0.0f` (binario)
- v2: función de PI-Index + HPS-Index + diag_flags

**HPS-Index (propuesta para v2):**
Detecta si la señal tiene estructura armónica periódica coherente con un pulso cardíaco. Requiere buffer (~2–4 s), FFT + HPS. No es stateless → necesita Task D propia (como HR2/HR3). Actualiza cada ~2–4 s.

**PI-Index (propuesta para v2):**
`PI = AC_amplitude / DC_level × 100%`. Bajo coste, calculable en ventana ~1 s. Detecta señal débil aunque sea periódica. No distingue ruido periódico de PPG real.

**Colaboración PI + HPS:**
Se complementan: PI detecta señal débil, HPS detecta falta de periodicidad. Un artefacto de movimiento rítmico puede engañar al PI pero no al HPS.

**Arquitectura RSQM con tres capas:**
- Capa rápida (stateless, 500 Hz): AMB_SAT, SIGNAL_WEAK, PROBE_OFF → Task A
- PI-Index (ventana ~1 s): Task A, overhead mínimo
- HPS-Index (ventana ~2–4 s, FFT): Task D propia

### Tema 2: HR3 — revisión del algoritmo

Revisado el código completo de HR3. Pipeline confirmado:
- LP filter (biquad, 10 Hz) → decimación ×10 → buffer circular 512 muestras (10.24 s @ 50 Hz)
- Resolución: 0.098 Hz/bin = 5.9 BPM/bin
- Linearización: DC removal + ventana Hann precomputada
- FFT radix-2 DIT 512 puntos (Task C)
- HPS = P[k]·P[2k]·P[3k], búsqueda en rango [hr_min, hr_max] con guard band ±3 BPM
- Interpolación parabólica sobre espectro Y sobre HPS (fix inter-bin energy split cúbico)
- SQI = prominencia del pico HPS normalizada: `(fraction - baseline) / (1 - baseline)`

HR1, HR2, HR3 comparten `hr_min_bpm` y `hr_max_bpm` (rango ISO 80601-2-61, uso neonatal).

### Tema 3: hr_min_bpm 25 → 30 BPM

**Decisión del usuario:** cambiar el límite inferior de HR de 25 a 30 BPM.

**Ficheros modificados:**
- `incunest_afe4490.cpp` — `hr_min_bpm = 30.0f` (era 25.0f). Aplica a HR1, HR2 y HR3.

## Sesión 2026-05-02b — hr_max_bpm + revisión de filtros

### Tema 1: Revisión de filtros por algoritmo

Revisados los filtros de los 4 algoritmos:
- **SpO2:** IIR DC removal (τ=1.6s) + EMA AC² (τ=1.0s). Sin biquad.
- **HR1:** IIR DC removal (τ=1.6s) + Moving Average LP (cutoff 5 Hz, buffer hasta 64 muestras). Sin biquad.
- **HR2:** Butterworth bandpass biquad (0.5–5 Hz) + decimación ×10.
- **HR3:** Butterworth low-pass biquad (10 Hz) + decimación ×10 + ventana Hann 512 puntos.

### Tema 2: hr_max_bpm 300 → 260 BPM

**Decisión del usuario:** cambiar el límite superior de HR de 300 a 260 BPM.

**Ficheros modificados:**
- `incunest_afe4490.cpp` — `hr_max_bpm = 260.0f` (era 300.0f). Aplica a HR1, HR2 y HR3.

## Sesión 2026-05-02c — rename hr_refractory_s → hr1_refractory_s

**Decisión:** `hr_refractory_s` renombrado a `hr1_refractory_s` ya que solo lo utiliza HR1 (para calcular `_hr1_refractory_samples`). Coherente con el prefijo `hr1_` del resto de parámetros del algoritmo.

Comentario actualizado: "covers 303 BPM" → "covers 263 BPM guard band" (refleja el nuevo hr_max_bpm=260 + guard band de 3 BPM).

**Ficheros modificados:**
- `incunest_afe4490.cpp` — constexpr renombrado + comentario actualizado
- `incunest_afe4490_spec.md` — 5 ocurrencias renombradas

## Sesión 2026-05-02d — mover hr1_refractory_s a sección HR1

`hr1_refractory_s` estaba en la sección `// ── HR (all algorithms)` del bloque de constexpr. Movida a `// ── HR1` donde le corresponde por ser un parámetro exclusivo de ese algoritmo.

**Ficheros modificados:**
- `incunest_afe4490.cpp` — `hr1_refractory_s` movida a sección HR1

## Sesión 2026-05-02e — HR3: LP → BP (0.4–15 Hz)

**Decisión:** Cambiar el filtro de HR3 de paso bajo (10 Hz) a paso banda (0.4–15 Hz).

**Razones:**
- Upper 15 Hz (antes 10 Hz): el 3er armónico de 260 BPM es 13 Hz — con 10 Hz quedaba atenuado, con 15 Hz se preserva → mejor HPS a FC alta.
- Lower 0.4 Hz: elimina DC y deriva de baseline lenta antes de la FFT. Más robusto que el DC removal por resta de media en `_linearize_hr3()`.
- Anti-aliasing sigue siendo seguro: 15 Hz << 25 Hz (Nyquist de 50 Hz decimado).

**Ficheros modificados:**
- `incunest_afe4490.h` — `_hr3_lpf` → `_hr3_bpf`; `hr3_f_low_hz` añadido a `AFE4490Config`; `setHR3Filter()` actualizado a dos parámetros
- `incunest_afe4490.cpp` — init, `setHR3Filter()`, `getConfig()`, `_reset_algorithms()`, `_recalc_rate_params()`, `_update_hr3_sample()` actualizados
- `incunest_afe4490_spec.md` — API, struct y tabla de parámetros actualizados

## Sesión 2026-05-03a — HR3TEST: LP → BP + correcciones HR range

### Tema 1: Actualización HR3TestCalc en pulsenest_lab.py

La ventana HR3TEST del script usaba filtro paso bajo (10 Hz) y rangos de HR 25–300 BPM, desalineados con el firmware actualizado en sesiones anteriores.

**Cambios realizados en `HR3TestCalc`:**
- Filtro: `FW_LP_CUTOFF_HZ=10.0` → `FW_BP_LOW_HZ=0.4`, `FW_BP_HIGH_HZ=15.0`
- Atributo instancia: `lp_cutoff_hz` → `bp_low_hz` + `bp_high_hz`
- `_recalc_filter()`: `butter(..., btype='low')` → `butter(..., [bp_low/nyq, bp_high/nyq], btype='band')`
- HR range constants: min 25→30, max 300→260, search_min 22→27, search_max 303→263
- UI: spin `_spin_lp_cutoff` reemplazado por `_spin_bp_low` + `_spin_bp_high`
- Export: comentario `lp_cutoff=...` → `bp=0.4-15.0 Hz`

**Razón:** la FFT y HPS de HR3TEST ahora filtran correctamente las frecuencias por debajo de 0.4 Hz, alineándose con el filtro BP del firmware.

**Ficheros modificados:**
- `pulsenest_lab.py` — clase `HR3TestCalc` y ventana `HR3TestWindow`

## Sesión 2026-05-05a — HR3TEST: fix velocidad p_hr + refactorización calc

### Problema
El plot `p_hr` en HR3TestWindow avanzaba más lento que el eje X. Causa raíz: `HR3TestCalc.update()` se llamaba dentro de `update_plots()`, que está throttled a 10 Hz de display. El cálculo FFT/HPS perdía muestras cuando había retraso en el hilo UI.

### Causa raíz identificada
Misma causa documentada en `project_hr3test_calc_fix.md`: `_calc.update()` throttled junto con el render. En contraste, HR1TEST ya tenía el patrón correcto: `hr1test_calc.update()` se llama a 500 Hz en `PPGMonitor.update_data()`, fuera del throttle.

### Fix aplicado — patrón HR1TEST
1. **PPGMonitor:** añadido `self.hr3test_calc = HR3TestCalc()` y llamada per-sample en `update_data()` (50 Hz, antes del bloque throttle):
   ```python
   if self.hr3test_window is not None:
       self.hr3test_calc.update(p[7], SPO2_RECEIVED_FS)
   ```
2. **HR3TestWindow:** refactorización de `_calc`:
   - `self._calc` → `self._offline_calc` (solo modo offline)
   - Añadidos `_get_live_calc()` → `main_monitor.hr3test_calc` y `_active_calc()` → selecciona offline o live
   - `update_plots()`: eliminada llamada `_calc.update()`, usa `_get_live_calc()` para leer resultados
   - `_on_param_changed()`, `_reset_to_defaults()`, `_update_status_indicator()`: usan `_active_calc()`
   - `_load_csv()`: usa `self._offline_calc` explícitamente
   - `_clear_offline()`: resetea `_get_live_calc()`
   - `_refresh_fft_plot()`, `_refresh_filt_plot()`, `_export_csv()`: usan `_active_calc()`

### Otras mejoras de la sesión (pre-sesión, completadas en sesión anterior)
- `HR3TestCalc`: LP 10 Hz → BP 0.4–15 Hz (alineado con firmware)
- HR range: min 25→30, max 300→260 BPM
- Export comment: `lp_cutoff=` → `bp=0.4-15.0 Hz`

**Ficheros modificados:**
- `pulsenest_lab.py` — HR3TestWindow y PPGMonitor.update_data()

---

## Sesión 2026-05-06

### Tema: HR3TEST — spin controls + FFT/HPS display below 0.4 Hz

**Preguntas:**
1. ¿Los spin controls de HR3TEST son editables o de solo lectura?
2. La FFT y HPS ploteados muestran contenido por debajo de 0.4 Hz.

**Decisiones:**
1. Los spin controls son completamente editables — `valueChanged` → `_on_param_changed()` actualiza `HR3TestCalc` y hace reset. Botón "RESET TO DEFAULTS" los restaura a valores firmware.
2. Bug de display: `last_spectrum` y `last_hps` almacenaban el espectro completo (0–25 Hz). El buffer sí está BP-filtrado pero los bins fuera de banda eran visibles. Fix: zerear bins fuera de `[bp_low_hz, bp_high_hz]` antes de guardar para display (puramente cosmético, el algoritmo ya usa solo la HR search range).

**Ficheros modificados:**
- `pulsenest_lab.py` — `HR3TestCalc.update()`: zereo de bins fuera de BP en `disp_spec` y `disp_hps`

### Addendum 2026-05-06b

**Cambio revertido:** Se deshizo el zereo de bins fuera de BP en `HR3TestCalc.update()`. `last_spectrum` y `last_hps` vuelven a almacenar el espectro completo sin enmascarar.

## Sesión 2026-05-11 — Fix HR3TEST plot 2: desincronización eje X / curva

### Problema
En HR3TestWindow, el eje X del plot 2 (BP filtered signal) avanzaba más rápido que la curva de datos.

### Causa raíz
`last_filtered_buf` solo se actualizaba dentro del bloque FFT, que se ejecuta cada `update_n = 25` muestras (0.5 s). Sin embargo, `_refresh_filt_plot()` usa `t_hr[-1]` (timestamp más reciente) como `t_end` en cada render:

```python
filt_t = t_end - (len(filt) - 1 - np.arange(len(filt))) / fs
```

Resultado: `filt_t` se desplazaba a la derecha en cada render (50 Hz), pero `filt` (los datos) permanecía congelado entre ciclos FFT (2 Hz) → desincronización visible entre eje X y curva.

### Fix
`last_filtered_buf` movido fuera del bloque FFT para actualizarse en cada muestra. El coste es mínimo (`np.roll` + reutilización del array). Dentro del bloque FFT, `seg_raw` reutiliza `last_filtered_buf` ya calculado.

**Ficheros modificados:**
- `pulsenest_lab.py` — `HR3TestCalc.update()`: `last_filtered_buf` actualizado por muestra, no por ciclo FFT

## Sesión 2026-05-11b — Fix sample drops al abrir ventanas secundarias

### Problema
Al abrir cualquier ventana secundaria (PPGPLOTS, HR3TEST, etc.) los plots mostraban huecos en la señal. Al cerrarla la señal volvía a ser correcta.

### Causa raíz
`update_data()` (QTimer 20ms) hacía dos cosas en el mismo slot:
1. Drenar la cola serie → actualizar deques (rápido)
2. Llamar a todos los `update_plots()` de las ventanas abiertas (lento — pyqtgraph rendering)

Cuando el rendering tardaba más de 20ms, el timer no podía dispararse a tiempo, la cola acumulaba muestras y los plots mostraban saltos al drenar en ráfagas.

### Fix: separación drain / render en dos timers
- `self.timer` (20ms) → `update_data()`: solo drena la cola + per-sample calcs + consola. Nunca bloqueado por rendering.
- `self._render_timer` (50ms) → `_render_update()`: todos los `update_plots()`. Puede tardar sin afectar la ingesta de datos.
- `self._render_pending`: flag booleano que comunica si hay datos nuevos desde el drain al render.
- Throttle counters adaptados a la nueva base de 50ms: `_PPGPLOTS_REFRESH_EVERY=1` (20Hz), `_SUBWIN_REFRESH_EVERY=2` (10Hz).

**Ficheros modificados:**
- `pulsenest_lab.py` — nuevo `_render_timer` + `_render_update()`, `update_data()` sin rendering, throttle constants actualizados

---

## Sesión 2026-05-11c — Fix rendimiento: OpenGL + downsampling en TEST windows

### Problema
La separación drain/render (sesión b) no fue suficiente: el slot `_render_update()` seguía siendo demasiado lento porque pyqtgraph renderizaba todas las curvas con antialiasing por software (2–5× más lento que GPU). Las ventanas TEST acumulan hasta 3000 puntos por curva → hasta 72.000 puntos antialiased por tick de render.

### Causa raíz
1. `pg.setConfigOptions(antialias=True)` en `HRLabWindow.__init__()` → antialiasing CPU-only en todas las curvas.
2. TEST windows (HR1TEST, HR2TEST, HR3TEST, SpO2TEST) usan `_HR_BUF = SPO2_CAL_BUFSIZE = 3000` → buffers enormes renderizados en bruto cada 50ms.

### Fix aplicado
1. **`pg.setConfigOptions(antialias=True, useOpenGL=True)`** añadido en `__main__` justo después de `app = QtWidgets.QApplication(sys.argv)`, antes de crear cualquier widget. El flag `useOpenGL=True` delega el rasterizado de curvas a la GPU.
2. **Eliminado** el `pg.setConfigOptions(antialias=True)` duplicado de `HRLabWindow.__init__()` (estaba sobreescribiendo con modo CPU-only).
3. **`setDownsampling(auto=True, method='peak')` + `setClipToView(True)`** aplicados a todas las curvas de forma de onda en TEST windows con buffers de 3000 puntos:
   - HR1TEST: `curve_dc_removed`, `curve_ma_filtered`, `curve_running_max`, `curve_threshold`
   - HR2TEST: `curve_acorr`, `curve_filt`
   - HR3TEST: `curve_filt`
   - SpO2TEST: `curve_dc_ir`, `curve_dc_red`, `curve_rms_ir`, `curve_rms_red`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-11d — Diagnóstico timing render/drain

### Problema
El fix de OpenGL + downsampling (sesión c) no resolvió la distorsión temporal. Se necesita medir cuánto tarda realmente `_render_update()` y `update_data()` para identificar el cuello de botella.

### Cambios
Añadidas trazas de diagnóstico condicionales (>15 ms):
- `[RENDER] Xms` — imprime si `_render_update()` tarda más de 15 ms
- `[DRAIN] Xms` — imprime si `update_data()` tarda más de 15 ms

Uso: lanzar con `python pulsenest_lab.py` (no `pythonw`) para ver salida por consola, abrir ventanas secundarias y observar qué slot es el lento.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12 — FREEZE DISPLAY: solo parar render, no algoritmos

### Contexto
Se aclaró que cuando render bloquea el hilo Qt, todo se para temporalmente (drain + algoritmos). Los datos no se pierden del buffer serie, pero los algoritmos se congelan hasta que render termina. El firmware ESP32 no se ve afectado.

### Cambio
`FREEZE DISPLAY` anteriormente descartaba todos los datos en cola y salía de `update_data()` sin ejecutar algoritmos.

Nuevo comportamiento:
- `update_data()` sigue corriendo normalmente (drain completo + todos los algoritmos)
- Solo se suprime `_render_pending = True` cuando `is_paused`
- Los plots quedan congelados pero HR/SpO2 siguen calculándose

Objetivo diagnóstico: activar FREEZE DISPLAY y observar si desaparecen los `[DRAIN]` >15ms. Si sí → rendering es el cuello de botella confirmado.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12b — Análisis exhaustivo + render timer 50ms→200ms

### Análisis
Investigación completa de `update_data()` y `_render_update()`. Hallazgos clave:

**Cálculos de algoritmos dentro de `_render_update()` (incorrecto):**
- `SpO2LabWindow.update_plots()` línea 1465: `_local_calc.update()` por muestra — SpO2 completo en render
- `SpO2TestWindow.update_plots()` línea 2124: `_calc.update()` por muestra — SpO2 completo en render
- `HR2TestWindow.update_plots()` línea 3396: `_calc.update()` por muestra — HR2 autocorrelación en render

**Trabajo Python pesado en render por tick:**
- Backward scan O(n) en hasta 9 ventanas para encontrar muestras nuevas
- `np.array(deque)` múltiples veces por ventana y por tick
- `setTitle()` HTML + múltiples `curve.setData()` × ventanas abiertas

### Fix aplicado (Opción 1 — inmediata)
`_render_timer.start(50)` → `_render_timer.start(200)` — render a 5 Hz en lugar de 20 Hz.
El render ocupa el hilo Qt 4× menos; drain y algoritmos corren sin interferencia.

### Pendiente (Opción 2)
Mover `SpO2LabWindow._local_calc`, `SpO2TestWindow._calc`, `HR2TestWindow._calc` a `update_data()`, igual que `hr3test_calc`. Los `update_plots()` solo leerían resultados ya calculados.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12c — Renombrado TIMING → ESP32 TIMING

Renombrados los textos visibles al usuario en la ventana de timing del ESP32:
- Título de ventana: `"TIMING — CPU Budget & Load"` → `"ESP32 TIMING — CPU Budget & Load"`
- Botón sidebar: `"TIMING"` → `"ESP32\nTIMING"`
- Tooltip: actualizado con prefijo "ESP32"

Nombres internos (`TimingWindow`, `timing_window`) sin cambios.
Pendiente: crear ventana similar "PYTHON TIMING" para medir tiempos del script Python.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12d — Renombrado completo de identificadores internos de la ventana TIMING

Renombrados todos los identificadores internos para reflejar la asociación con el ESP32:

| Antes | Después |
|---|---|
| `class TimingWindow` | `class Esp32TimingWindow` |
| `self.timing_window` | `self.esp32_timing_window` |
| `self.btn_timing` | `self.btn_esp32_timing` |
| `self.toggle_timing` / `def toggle_timing` | `self.toggle_esp32_timing` / `def toggle_esp32_timing` |
| `self._open_timing_default` / `def _open_timing_default` | `self._open_esp32_timing_default` / `def _open_esp32_timing_default` |
| `def update_timing` / `.update_timing(` | `def esp32_update_timing` / `.esp32_update_timing(` |
| `def update_tasks` / `.update_tasks(` | `def esp32_update_tasks` / `.esp32_update_tasks(` |
| `"TimingWindow/geometry"` (QSettings) | `"Esp32TimingWindow/geometry"` |
| `"PPGMonitor/timing_open"` (QSettings) | `"PPGMonitor/esp32_timing_open"` |

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12e — Opción 2: mover algoritmos fuera de _render_update()

### Problema
Los algoritmos de SpO2LabWindow, SpO2TestWindow y HR2TestWindow se ejecutaban dentro de `_render_update()`, bloqueando el render y causando distorsión temporal cuando las ventanas secundarias estaban abiertas.

### Decisión
Separar el cálculo del render siguiendo el mismo patrón que `hr3test_calc`:
- **`update_algorithms(data...)`** — ejecutado desde `PPGMonitor.update_data()` (timer 20 ms): itera muestras nuevas, llama al `_calc.update()`, rellena los deques de buffer.
- **`update_plots()`** — ejecutado desde `PPGMonitor._render_update()` (timer 200 ms): solo convierte buffers a arrays y llama a `setData()`. Sin algoritmos.

### Cambios
- `SpO2LabWindow.update_plots(data...)` → `update_algorithms(data...)` + `update_plots()` (sin args)
- `SpO2TestWindow.update_plots(data...)` → `update_algorithms(data...)` + `update_plots()` (sin args); añadido `self._last_r` para pasar el último resultado del calc al render
- `HR2TestWindow.update_plots(data...)` → `update_algorithms(data...)` + `update_plots()` (sin args)
- `PPGMonitor.update_data()`: llama a `spo2lab_window.update_algorithms()`, `spo2test_window.update_algorithms()`, `hr2test_window.update_algorithms()` cuando `_new_data`
- `PPGMonitor._render_update()`: llama a las tres `update_plots()` sin argumentos

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12f — Fix: toggle_timing → toggle_esp32_timing

**Bug:** `AttributeError: 'PPGMonitor' object has no attribute 'toggle_esp32_timing'` al arrancar el script. El renombrado de identificadores ESP32 TIMING de la sesión anterior había omitido renombrar la definición del método `toggle_timing` a `toggle_esp32_timing`.

**Fix:** renombrado `def toggle_timing(self):` → `def toggle_esp32_timing(self):` en `pulsenest_lab.py`.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12g — PYTHON TIMING window

### Objetivo
Crear ventana de diagnóstico de rendimiento del script Python, simétrica a ESP32 TIMING.

### Implementación
- Nueva clase `PythonTimingWindow` con tabla de 3 secciones:
  - **Loop timers**: `update_data()` drain (budget 20ms) y `_render_update()` total (budget 200ms)
  - **Algorithms**: tiempo de `update_algorithms()` para SpO2Lab, SpO2Test, HR2Test
  - **Render**: tiempo de `update_plots()` para cada ventana (PPGPlots, Signals, Results, HRLab, SpO2Lab, HR3Lab, SpO2Test, HR1Test, HR2Test, HR3Test)
- Columnas: Component | Mean (ms) | Max (ms) | % Budget
- Status bar OK/TIGHT/OVERLOAD basado en drain_max vs 20ms
- Color: blanco < 75%, naranja 75-100%, rojo > 100%
- Rolling buffer de 50 mediciones por componente (`deque(maxlen=50)`) en `PPGMonitor._py_timing`
- Se actualiza cada ~1s (5 render ticks a 200ms)

### Instrumentación añadida
- `update_data()`: wrap con `time.perf_counter()` de cada `update_algorithms()` + append `_drain_ms` a `_py_timing['drain']`
- `_render_update()`: wrap de cada `update_plots()` + append `_render_ms` a `_py_timing['render']`

### Botón / persistencia
- Botón `PYTHON TIMING` en sidebar, debajo de `ESP32 TIMING`
- QSettings: `"PythonTimingWindow/geometry"`, `"PPGMonitor/python_timing_open"`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12h — PYTHON TIMING: fix valores al cerrar ventana

**Bug:** al cerrar una ventana secundaria, sus filas en PYTHON TIMING mantenían el último valor en lugar de volver a "—".

**Causa:** los deques `_py_timing` conservaban los datos históricos aunque la ventana estuviera cerrada.

**Fix:**
- En el bloque de refresh de `_pytiming_refresh_counter` (`_render_update()`): limpiar los deques de las ventanas que estén a `None` antes de calcular las stats. Los deques vacíos producen `None` en el dict de stats.
- En `PythonTimingWindow.update_timing()`: manejar `None` → mostrar "—" en gris (#888888) para las filas sin datos.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12i — PYTHON TIMING: nombre de botón en cada fila

**Cambio:** prefijo con el nombre del botón de UI en cada fila de `_ALGO_ROWS` y `_PLOT_ROWS`:
- `SPO2LAB`, `SPO2TEST`, `HR2TEST` en sección Algorithms
- `PPGPLOTS`, `SIGNALS`, `RESULTS`, `HR2LAB`, `SPO2LAB`, `HR3LAB`, `SPO2TEST`, `HR1TEST *`, `HR2TEST`, `HR3TEST` en sección Render

Los nombres de botón coinciden exactamente con los textos visibles en la sidebar.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12j — PYTHON TIMING: añadir identificador de código a cada fila

**Cambio:** cada fila muestra ahora TANTO el nombre del botón como el identificador de código:
- Formato: `"BTNNAME  |  ClassName.method()"`
- Ejemplos: `"SPO2LAB  |  SpO2LabWindow.update_algorithms()"`, `"HR2TEST  |  HR2TestWindow.update_plots()"`
- Loop timers sin botón se mantienen como estaban: `"update_data() drain"`, `"_render_update() total"`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-12k — PYTHON TIMING: budget visible en sección Loop timers

**Cambio:** el header de la sección "Loop timers" ahora indica los budgets de ambas filas:
`"Loop timers  —  drain budget 20 ms  |  render budget 200 ms"`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13 — Rename: update_data/_render_update y constantes PYTHON TIMING

### Métodos renombrados (replace_all)
- `update_data()` → `_process_serial_queue_tick()`
- `_render_update()` → `_refresh_plots_tick()`

### Constantes renombradas en PythonTimingWindow (replace_all)
- `_DRAIN_BUDGET_MS` → `_SERIAL_TICK_BUDGET_MS`
- `_RENDER_BUDGET_MS` → `_PLOTS_TICK_BUDGET_MS`
- `_ALGO_ROWS` → `_SERIAL_TICK_ALGO_ROWS`
- `_PLOT_ROWS` → `_PLOTS_TICK_ROWS`

**Motivación:** nombres más descriptivos para facilitar el diagnóstico de los ticks del timer (investigación de tiempos de ejecución).

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13b — Rename _SERIAL_TICK_ALGO_ROWS + cross-reference comments

### Cambios
- `_SERIAL_TICK_ALGO_ROWS` → `_SERIAL_TICK_ROWS` (simetría con `_PLOTS_TICK_ROWS`)
- Comentarios en constantes de `PythonTimingWindow`:
  - `_SERIAL_TICK_BUDGET_MS` → `# ms — timer period → _process_serial_queue_tick()`
  - `_PLOTS_TICK_BUDGET_MS` → `# ms — timer period → _refresh_plots_tick()`
  - `_SERIAL_TICK_ROWS` → `# algorithms timed inside _process_serial_queue_tick()`
  - `_PLOTS_TICK_ROWS` → `# renderers timed inside _refresh_plots_tick()`
- Docstrings en métodos de `PPGMonitor` citando las constantes asociadas:
  - `_process_serial_queue_tick()`: cita `_SERIAL_TICK_BUDGET_MS` y `_SERIAL_TICK_ROWS`
  - `_refresh_plots_tick()`: cita `_PLOTS_TICK_BUDGET_MS` y `_PLOTS_TICK_ROWS`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13c — PYTHON TIMING: interval rows para los dos ticks

### Motivación
Los rows existentes miden duración de cada tick. Los nuevos miden el intervalo real entre llamadas consecutivas, permitiendo detectar jitter del timer Qt.

### Cambios
- `_LOOP_ROWS`: 2 filas nuevas:
  - `("drain_interval",  "_process_serial_queue_tick() interval", _SERIAL_TICK_BUDGET_MS)`
  - `("render_interval", "_refresh_plots_tick() interval",        _PLOTS_TICK_BUDGET_MS)`
- `_pt_keys`: añadidas claves `'drain_interval'` y `'render_interval'`
- `_last_drain_t = None` y `_last_render_t = None` inicializados junto a `_py_timing`
- `_process_serial_queue_tick()`: mide intervalo desde `_last_drain_t` al inicio del tick
- `_refresh_plots_tick()`: mide intervalo desde `_last_render_t`, después del guard `_render_pending` (intervalo real de render ~200 ms, igual al budget)

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13d — PYTHON TIMING: rename "total" → "render" en Loop timers

**Cambio:** `_refresh_plots_tick() total` → `_refresh_plots_tick() render` para consistencia con `_process_serial_queue_tick() drain`. Ambas filas de duración quedan nombradas por la operación que realizan.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13e — PYTHON TIMING: budget 2× para interval rows

**Problema:** las filas `drain_interval` y `render_interval` aparecían en rojo porque el intervalo nominal ≈ budget → 100% → umbral crítico.

**Fix:** budget de las interval rows = 2× el período nominal:
- `drain_interval`  → `_SERIAL_TICK_BUDGET_MS * 2` = 40 ms
- `render_interval` → `_PLOTS_TICK_BUDGET_MS * 2`  = 400 ms

Verde = timer puntual, amarillo = jitter moderado, rojo = retraso severo.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13f — PYTHON TIMING: lbl_status global (peor fila de la tabla)

### Motivación
El `lbl_status` anterior solo monitorizaba el drain, dando una falsa sensación de "OK" aunque otras filas estuvieran en rojo/amarillo.

### Cambios
- `update_timing()`: se rastrea `worst_pct` / `worst_label` a lo largo del loop de todas las filas
- Status bar muestra el estado de la **peor fila** de la tabla completa:
  - `ALL OK  [HH:MM:SS]` — gris neutro (`#E0E0E0`) cuando todo < 75% budget
  - `TIGHT  —  <label>  [HH:MM:SS]` — naranja cuando la peor fila está al 75–100%
  - `OVER BUDGET  —  <label>  [HH:MM:SS]` — rojo cuando alguna fila supera el budget
- Font size: 13px → 15px
- Color OK: verde brillante `#44FF44` → gris neutro `#E0E0E0` (consistente con tabla)
- Tooltip actualizado para reflejar el nuevo comportamiento global

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13g — PYTHON TIMING: rename "Loop timers" → "Tick timers" + _LOOP_ROWS → _TICK_ROWS

**Cambio:** "Loop timers" → "Tick timers" (header de sección y constante `_LOOP_ROWS` → `_TICK_ROWS`) para consistencia con los nombres de los métodos `_process_serial_queue_tick()` y `_refresh_plots_tick()`.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13h — PYTHON TIMING: columna Budget (ms) en la tabla

### Motivación
Las filas `interval` usaban un budget 2× interno (40 ms / 400 ms) invisible para el usuario, que veía "20 ms" en el header pero "102%" en el %. La columna Budget explicita el budget de cada fila individualmente.

### Cambios
- Tabla: 4 → 5 columnas (`Component | Budget (ms) | Mean (ms) | Max (ms) | % Budget`)
- `_add_data_rows`: muestra `budget_ms` en col 1 (gris, estático)
- `_add_section`: span 4 → 5
- `update_timing()`: columnas de datos 1,2,3 → 2,3,4
- Header sección "Tick timers": eliminado el texto redundante "drain budget X ms | render budget Y ms"
- Tooltip tabla actualizado

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13i — PYTHON TIMING: Budget column movida a posición 3

**Cambio:** orden de columnas `Component | Budget | Mean | Max | %` → `Component | Mean | Budget | Max | %`

Budget queda como referencia visual entre Mean y Max, y justo antes de `% Budget` (que resulta de Max÷Budget).

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13j — T1: pasar sample_counter a HR1TestCalc, HRFFTCalc, HR3TestCalc

### Contexto
Investigación de pérdida de muestras antes de llegar a los algoritmos. Pipeline de detección de huecos diseñado en 3 puntos:
- **Punto A**: tamaño de `_serial_queue` (cola ilimitada — no descarta, pero puede acumularse)
- **Punto B**: `_process_serial_queue_tick()` al ingestar en `data_sample_counter`
- **Punto C**: en cada consumidor individual

### T1 — preparar firmas para gap detection (T2)
3 calcs que solo recibían `(value, fs)` ahora aceptan `sample_counter=None` (opcional, sin romper otros callers):
- `HR1TestCalc.update(ir_sub, fs, sample_counter=None)` — pre-decimación 500 Hz; call site pasa `int(_p500[1])`
- `HRFFTCalc.update(led1_aled1, fs, sample_counter=None)` — post-decimación (hr3_calc); call site pasa `int(p[0])`
- `HR3TestCalc.update(ir_sub, fs, sample_counter=None)` — post-decimación; call site pasa `int(p[0])`

Los otros 3 consumidores (`SpO2LabWindow`, `SpO2TestWindow`, `HR2TestWindow`) ya recibían `data_sample_counter`.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13k — T2: detección de huecos en el pipeline de muestras

### Contexto
Investigación de pérdida de muestras antes de llegar a los algoritmos. Continuación de T1.

### Arquitectura de detección (3 puntos)
```
ESP32 → UART → _serial_reader → _serial_queue → _process_serial_queue_tick() → algoritmos
                                      ↑ Punto A          ↑ Punto B                ↑ Punto C
```
- **Punto A**: `_serial_queue` es ilimitada (no descarta); se monitoriza su tamaño instantáneo
- **Punto B**: primer punto de detección real en Python (al ingestar en `data_sample_counter`)
- **Punto C**: en cada consumidor individual (6 consumidores)

### Cambios

**Calcs (HR1TestCalc, HRFFTCalc, HR3TestCalc)**:
- `__init__`: añadidos `_last_counter=None`, `_nominal_step=None`, `gap_count=0`
- `update()`: detección de huecos con auto-detección del paso nominal (1 para HR1Test pre-decim, decim_factor para los demás)

**Window consumers (SpO2LabWindow, SpO2TestWindow, HR2TestWindow)**:
- `__init__`: añadidos `_nominal_step=None`, `gap_count=0`
- `update_algorithms()`: detección de huecos sobre `new_indices` (los índices de muestras nuevas ya calculados)

**PPGMonitor**:
- `__init__`: `_last_ingested_counter=None`, `_gaps_B=0`, `_last_queue_size=0`
- `_process_serial_queue_tick()`: captura `qsize()` al inicio (Punto A); gap detection tras append a `data_sample_counter` en M1 y M2 (Punto B)

**PythonTimingWindow**:
- `_GAP_ROWS`: 8 filas (queue_size, gap_B, hr1test, hr3lab, hr3test, spo2lab, spo2test, hr2test)
- Nueva sección `"Sample gaps"` en la tabla; columna `Max` repurposada como contador
- `update_timing(stats, gaps=None)`: nuevo parámetro `gaps`; verde si 0, rojo si >0; queue_size: naranja>10, rojo>50
- Call site en `_refresh_plots_tick()`: construye `_pt_gaps` y lo pasa a `update_timing()`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13l — PYTHON TIMING: sub-header de columnas en sección Sample gaps

**Cambio:** añadida fila de sub-header en negrita encima de "Queue size" en la sección Sample gaps, con las etiquetas "Component" y "Count" en las columnas relevantes. Aclara que la columna Max tiene significado distinto (contador entero) en esta sección.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13m — PYTHON TIMING: simplificar texto del section header de Sample gaps

**Cambios:**
- Section header: `"Sample gaps — 'Max' col = lost samples (queue: instantaneous | others: since connect)"` → `"Sample gaps — lost samples since connect"`
- Fila `gap_queue`: eliminado `[instantaneous]` del label (redundante con el sub-header)

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13n — PYTHON TIMING: Queue size con mean y max rolling

**Cambio:** la fila `Queue size (frames)` ahora muestra mean (col 1) y max (col 3) sobre ventana de 50 muestras, igual que las filas de timing. Antes mostraba solo el valor instantáneo.

- `_last_queue_size` (escalar) → `_queue_size_buf` (deque maxlen=50)
- `_process_serial_queue_tick()`: `append(qsize())` en cada tick
- Call site en `_refresh_plots_tick()`: pasa tupla `(mean, max)` en `_pt_gaps['gap_queue']`
- `update_timing()`: caso `gap_queue` muestra mean en col 1 y max en col 3; color según max (>10 naranja, >50 rojo)

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14i — Python: label DATA SOURCE (USB-CDC vs UDP WiFi)

**Cambio:** añadido `lbl_data_source` entre los botones de conexión y RESET ESP32. Muestra la fuente activa con color:
- Gris: `DATA SOURCE:  none` (sin conexión)
- Verde: `DATA SOURCE:  USB-CDC  (COM15)` (al conectar serial)
- Azul: `DATA SOURCE:  UDP WiFi  (:5005)` (al conectar UDP)

Actualizado en `_connect_serial()` y `_connect_udp()`.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14h — Python: receptor UDP en pulsenest_lab.py

**Cambios:**
- `UDP_DEFAULT_PORT = 5005` constante global (debe coincidir con `wifi_config.h`)
- UI sidebar: nueva fila UDP con `spin_udp_port` (1024-65535, default 5005) + botón `btn_udp_connect`
- `_connect_udp()`: para el reader activo, drena la cola, inicia `_udp_reader` thread, actualiza botón
- `_udp_reader()`: socket UDP con SO_RCVBUF=1MB, timeout=0.5s, cada datagrama = un frame completo → `_serial_queue.put(data)`. Incluye gap detection Punto B igual que `_serial_reader` (tag `[GAP B/UDP]`)
- `self._udp_port` añadido en `__init__`
- Fix: eliminada línea duplicada `_last_cnt = None` en `_serial_reader`
- Pipeline existente (parsing, algoritmos, plots) sin cambios — misma `_serial_queue`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14g — Firmware: WiFi STA + UDP emisor en paralelo a USB-CDC

**Cambios en main.cpp:**
- Includes: `<WiFi.h>`, `<WiFiUDP.h>`, `"wifi_config.h"`
- `g_udp` (WiFiUDP) + `g_wifi_ready` (bool) como globales
- `udp_send(buf)`: helper inline — envía el mismo `buf` que `Serial.print()`, no-op si WiFi no listo
- `setup()`: WiFi STA `WiFi.begin(WIFI_SSID, WIFI_PASSWORD)` con timeout 10s; si conecta → log IP + puerto; si falla → "USB-CDC only"
- `Incunest_Task`: `udp_send(buf)` tras cada `Serial.print(buf)` en M1 y M2
- Solo frames de datos (M1/M2) van por UDP; CFG/DIAG/etc. siguen siendo USB-CDC únicamente

**Resultado:** firmware compila y flashea OK. USB-CDC + UDP activos simultáneamente.
**Pendiente:** receptor UDP en Python (pulsenest_lab.py).

**Ficheros modificados:**
- `src/main.cpp`
- `include/wifi_config.h` (credenciales, NO en git)
- `.gitignore` (añadido wifi_config.h)
- `sdkconfig.defaults` (nuevo, opción D buffer USB-CDC)

---

## Sesión 2026-05-14f — WiFi/UDP: decisiones de diseño + wifi_config.h

**Contexto:** pérdida de muestras no resuelta con set_buffer_size ni sdkconfig.defaults. Se exploran alternativas de transporte. Decisión: añadir WiFi/UDP en paralelo a USB-CDC (ambos activos simultáneamente).

**Decisiones tomadas:**
- Transporte: WiFi modo STA (ESP32 conecta a red doméstica, PC mantiene internet)
- USB-CDC y UDP conviven — no se reemplaza pyserial
- Credenciales WiFi: hardcodeadas en `include/wifi_config.h` (separado, en .gitignore)
- IP del ESP32: pendiente decidir (fija via router vs. DHCP + display en log)

**Ficheros creados/modificados:**
- `include/wifi_config.h` — credenciales WiFi + IP target + puerto UDP (NO commitear)
- `.gitignore` — añadido `include/wifi_config.h`
- `sdkconfig.defaults` — creado con `CONFIG_TINYUSB_CDC_TX_BUFSIZE=4096` (opción D, impacto no confirmado)

---

## Sesión 2026-05-14e — Fix: botón $M2 no cambiaba modo en firmware

**Causa:** `_send_frame_cmd()` enviaba `b'1'` o `b'2'` sin `\n`. El firmware parsea comandos línea a línea → el byte quedaba en el buffer sin procesarse. Todos los demás comandos (`$CFG?\n`, `$DIAG?\n`, `$SET,...\n`) ya llevaban `\n`.

**Fix:** `'1'` → `'1\n'`, `'2'` → `'2\n'`.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14d — _gaps_B: ignorar gaps > 5000 (tramas corruptas)

**Causa de valores desorbitados:** tramas con checksum incorrecto llegan a `_serial_reader` con un campo contador corrupto que pasa `int()` pero contiene basura. El checksum se verifica en `_process_serial_queue_tick()` pero no en `_serial_reader`.

**Fix elegido:** threshold `0 < _gap <= 5000` (10 s a 500 Hz). Cualquier gap mayor se descarta silenciosamente como trama corrupta. Alternativa descartada: verificar checksum NMEA en `_serial_reader` (trabajo innecesario, ya hecho en el tick).

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14c — Revertido: tracking M1/M2 separado en _serial_reader

**Motivo:** la hipótesis de que los contadores M1/M2 eran independientes resultó incorrecta. Revertido a `_last_cnt` único para M1 y M2. La causa real de los valores desorbitados en `_gaps_B` está pendiente de investigación.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14b — Fix: Signal → pyqtSignal (PyQt5)

**Error:** `AttributeError: module 'PyQt5.QtCore' has no attribute 'Signal'` — `Signal` es sintaxis PySide2/PySide6; en PyQt5 la clase equivalente es `pyqtSignal`.

**Fix:** `QtCore.Signal(str)` → `QtCore.pyqtSignal(str)`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14a — Gap B: fix contadores M1/M2 separados + QueuedConnection

**Problema 1 — _gaps_B desorbitado:** `_last_cnt` mezclaba M1 y M2 en la misma variable. Si sus contadores no son consecutivos (modos distintos, reinicio), el salto entre el último M2 y el siguiente M1 generaba gaps falsos enormes.

**Fix:** tracking separado con `_last_cnt_m1` y `_last_cnt_m2`. Solo se comparan M1→M1 y M2→M2. El log indica el tipo: `[GAP B/M1]` o `[GAP B/M2]`.

**Problema 2 — log messages no aparecían:** `threading.Thread` no es `QThread`, PyQt5 entregaba la señal como `DirectConnection` en el hilo lector. Modificar widgets Qt desde hilo no-GUI → descartado silenciosamente.

**Fix:** `self._sig_log.connect(self.log, QtCore.Qt.QueuedConnection)` fuerza entrega en el hilo principal.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13t — Gap B log via _sig_log → self.log() (sin consola)

**Problema:** `print()` en `_serial_reader` es inútil porque el script se lanza con `pythonw` (sin consola).

**Cambio:** reemplazado `print()` por señal Qt `_sig_log` que entrega el mensaje al hilo principal → `self.log()` lo muestra en el panel de log de la UI.

- `PPGMonitor._sig_log = QtCore.Signal(str)` — señal de clase (thread-safe por diseño Qt)
- `__init__`: `self._sig_log.connect(self.log)`
- `_serial_reader`: `self._sig_log.emit(f"[GAP B] {_gap} samples lost (cnt {_last_cnt}→{_cnt})")`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13s — Ampliar buffer RX serial (mitigación pérdida de frames)

**Causa:** al abrir ventanas Qt, el hilo principal retiene el GIL durante decenas de ms (construcción de widgets Python). `_serial_reader` no puede re-adquirir el GIL para llamar a `readline()`, frames se acumulan en el buffer OS. Si el buffer por defecto (~4 KB ≈ 80 frames) se llena, el driver descarta bytes → gaps en Punto B.

**Fix provisional:** `self.ser.set_buffer_size(rx_size=65536)` justo después de abrir el puerto. Da ~1300 frames de margen en lugar de ~80, suficiente para absorber picos de contención de GIL.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13r — Gap detection Punto B movido a _serial_reader

**Cambio:** detección de gaps Punto B movida del tick `_process_serial_queue_tick()` al hilo `_serial_reader`. Ventaja: detección en el punto más temprano posible (instante de llegada del frame), con traza `print()` inmediata cuando se detecta un gap.

- `_serial_reader()`: añadido contador local `_last_cnt`; compara counter de cada frame `$M1`/`$M2` raw (bytes); si `gap > 0` incrementa `self._gaps_B` y emite `[GAP B] N samples lost (cnt X→Y)`
- `_process_serial_queue_tick()`: eliminado bloque Punto B (redundante)
- `__init__`: eliminado `_last_ingested_counter`; simplificado comentario de `_gaps_B`
- `self._gaps_B` es safe desde el hilo lector: CPython GIL protege `+= n` en int

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13q — PYTHON TIMING: variable names al inicio del label (fix visibilidad)

**Problema:** con col 0 en modo `Stretch`, los `[varname]` al final del texto quedaban cortados fuera del borde de la ventana. Solo era visible la variable de la fila más corta ("Ingestion [PPGMonitor._gaps_B]").

**Fix:** movido `[varname]` al inicio de cada label en `_TICK_ROWS`, `_SERIAL_TICK_ROWS`, `_PLOTS_TICK_ROWS` y `_GAP_ROWS`. Al estar al principio siempre es lo primero visible aunque la columna sea estrecha.

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13p — PYTHON TIMING: nombres de variable en todas las filas

**Cambio:** añadido el nombre de la variable Python entre corchetes `[varname]` al final de cada label en `_TICK_ROWS`, `_SERIAL_TICK_ROWS`, `_PLOTS_TICK_ROWS` y `_GAP_ROWS`. Objetivo: facilitar la búsqueda en el código fuente desde la ventana PYTHON TIMING.

- Tick timers: `[_py_timing['drain']]`, `[_last_drain_t]`, `[_py_timing['render']]`, `[_last_render_t]`
- Algo/Plot rows: `[_py_timing['key']]` con el key exacto de cada fila
- Gap rows: `[PPGMonitor._queue_size_buf]`, `[PPGMonitor._gaps_B]`, `[PPGMonitor.hr1test_calc.gap_count]`, `[PPGMonitor.hr3_calc.gap_count]`, `[PPGMonitor.hr3test_calc.gap_count]`, `[SpO2LabWindow.gap_count]`, `[SpO2TestWindow.gap_count]`, `[HR2TestWindow.gap_count]`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-13o — PYTHON TIMING: fix _gaps_B (Punto B movido a pre-decimation)

**Problema:** `_gaps_B` parecía un simple contador de tramas en lugar de medir gaps reales. Causa raíz: el bloque de detección Punto B estaba ubicado después del bloque de decimación (`if self._decim_counter % self.spin_decim.value() != 0: continue`), por lo que solo veía frames decimados. Entre dos frames decimados consecutivos el contador firmware salta `decim_factor` posiciones → `gap = decim_factor - 1` se acumulaba en cada frame aunque no hubiera pérdidas reales.

**Fix:** Punto B movido a antes del bloque de decimación, donde se ven todos los frames raw. Entre frames consecutivos el contador debe saltar exactamente 1; cualquier diferencia mayor indica una pérdida real.

**Cambios:**
- Añadido bloque Punto B antes de `if self._decim_counter % ...` en `_process_serial_queue_tick()`
- Eliminado bloque Punto B del interior del bloque M1 post-decimación
- Eliminado bloque Punto B del interior del bloque M2 post-decimación

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14k — UDP COM window + separación de colas serial/UDP

**Tema:** Separar transporte USB-CDC y WiFi/UDP en ventanas de consola independientes, y renombrar `_process_serial_queue_tick` → `_process_frames_tick`.

**Preguntas clave:**
- ¿La ventana SERIALCOM muestra datos de ambas fuentes (serial + UDP) o solo serial?
- ¿Crear una ventana UDP COM separada?
- ¿`_udp_reader` debe escribir en `_serial_queue` o en una nueva `_udp_queue`?
- ¿Cómo renombrar `_process_serial_queue_tick` dado que ahora procesa dos colas?

**Decisiones tomadas:**
1. **SERIALCOM** → solo USB-CDC; **UDP COM** → solo WiFi/UDP (separación limpia)
2. `_udp_reader` escribe en `_udp_queue` (nueva cola separada de `_serial_queue`)
3. `_process_serial_queue_tick` renombrado a `_process_frames_tick` (nombre elegido por el usuario)
4. `_process_frames_tick` drena ambas colas en un `for` loop sobre `(_serial_queue, serialcom_window)` y `(_udp_queue, udpcom_window)`
5. Variable `_src_com_win` dentro del loop para routing de mensajes inline (checksum errors, etc.)
6. `UdpComWindow`: ventana flotante azul (#44AAFF), misma estructura que `SerialComWindow` (amarilla)
7. Botón `btn_udpcom` en sidebar junto a `btn_serialcom`; geometría persistida en QSettings

**Cambios en pulsenest_lab.py:**
- Nueva clase `UdpComWindow` (después de `SerialComWindow`) — esquema de color azul
- `_udp_queue = queue.Queue()` junto a `_serial_queue`
- `udpcom_window = None` en `__init__`
- Botón `btn_udpcom` con `toggle_udpcom()` en sidebar
- `_connect_udp()`: drena ambas colas al reconectar
- `_udp_reader()`: escribe en `_udp_queue` (antes escribía en `_serial_queue`)
- `_process_frames_tick()`: loop `for _q, _src_com_win in (...)` sobre ambas colas
- `if _new_data:` movido fuera del for loop (aplica a datos de cualquier fuente)
- `saveGeometry` para `udpcom_window` en `closeEvent`
- Todos los comentarios/docstrings actualizados: `_process_serial_queue_tick` → `_process_frames_tick`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14l — Fix: serial reader no se mata al conectar UDP

**Problema:** Al activar recepción UDP, `_connect_udp()` detenía `_reader_thread` (que era `_serial_reader`), por lo que las respuestas a comandos ($CFG, $DIAG, $ERR, mensajes #) dejaban de procesarse.

**Causa raíz:** `_connect_udp()` usaba `_reader_stop`/`_reader_thread` (los mismos del reader serie) para gestionar el UDP reader, matando efectivamente `_serial_reader`.

**Decisión:** Dos pares independientes de thread/stop:
- `_reader_stop` / `_reader_thread` → exclusivo para `_serial_reader`
- `_udp_stop` / `_udp_thread` → exclusivo para `_udp_reader`

`_connect_udp()` solo gestiona `_udp_stop`/`_udp_thread`, sin tocar el reader serie. Ambos threads corren en paralelo.

**Cambios en pulsenest_lab.py:**
- `__init__`: añadidos `_udp_stop = threading.Event()` y `_udp_thread = None`
- `_connect_udp()`: usa `_udp_stop`/`_udp_thread`; solo drena `_udp_queue`; docstring actualizado
- `_udp_reader()`: usa `self._udp_stop` en lugar de `self._reader_stop`
- `closeEvent`: también detiene `_udp_stop`/`_udp_thread` al cerrar

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Sesión 2026-05-14m — Botón PAUSE en SERIALCOM y UDP COM

**Tema:** Añadir botón PAUSE/RESUME en las ventanas SERIALCOM y UDP COM para congelar el display sin afectar al pipeline de datos.

**Decisión:** El botón pausa solo el display (descarta nuevas líneas en `append_line`/`append_lines`). La cola sigue drenándose y los algoritmos siguen funcionando con normalidad. Los frames recibidos durante la pausa no se muestran al reanudar (ya pasaron).

**Cambios en pulsenest_lab.py:**
- `SerialComWindow`: añadido `self._paused = False`; cabecera convertida en `QHBoxLayout` (header_label + btn_pause); botón PAUSE checkable; `_toggle_pause()`; `append_line`/`append_lines` retornan inmediatamente si `_paused`
- `UdpComWindow`: mismos cambios
- Retoque visual (sesión 2026-05-14n): botón ampliado a 110px, gris neutro (#505050) en reposo, naranja (#CC6600) cuando pausado
- Sesión 2026-05-14o: mensaje de gap serial renombrado `[GAP B]` → `[GAP B/SERIAL]` para distinguirlo de `[GAP B/UDP]`

**Ficheros modificados:**
- `pulsenest_lab.py`

---

## Estado al cierre de sesión 2026-05-14 (noche)

**WiFi/UDP implementado y funcional** pero se observan pérdidas de frames por UDP que no ocurren por serial.

**Diagnóstico:** causa más probable = cola TX lwIP del ESP32 se satura a 500 Hz (un datagrama cada 2 ms). `udp.endPacket()` descarta silenciosamente si la cola está llena. Serial no pierde porque USB-CDC tiene buffer OS de 64 KB y enlace dedicado.

**Opciones pendientes de probar (próxima sesión):**
- B) Enviar UDP cada 2 frames (250 Hz) para confirmar si el cuello de botella es la cola TX del ESP32
- C) TCP en lugar de UDP
- D) Acumular varios frames en un solo datagrama UDP

---

## Sesión 2026-05-15 — UDP_BATCH_SIZE: acumulación de N frames por datagrama

### Motivación
Pérdidas de frames por UDP causadas por saturación de la cola TX lwIP del ESP32 a 500 Hz (un `udp.endPacket()` cada 2 ms). Se implementa la opción D extendida: parámetro configurable `UDP_BATCH_SIZE` (default 10) para acumular N frames por datagrama.

### Consecuencias del batching
- **TX queue pressure:** 500 datagramas/s → 50/s (×10 reducción)
- **Latencia añadida:** máx. N×2 ms = 20 ms — irrelevante para diagnóstico
- **Tamaño datagrama:** 10 × ~200 bytes = ~2000 bytes — dentro del MTU WiFi. Límite seguro: N≤12.
- **Python:** no necesita conocer UDP_BATCH_SIZE — divide el datagrama por `\n` y procesa cada frame independientemente.
- **Gap detection:** sin cambios — sigue operando frame a frame al desempaquetar.

### Cambios implementados

**`include/wifi_config.h`:**
- Añadido `#define UDP_BATCH_SIZE 10` con comentario de límite seguro (N≤12)

**`src/main.cpp`:**
- `udp_send()` reescrita con buffer estático `g_udp_batch_buf[UDP_BATCH_SIZE * 256]` (2560 bytes)
- `g_udp_batch_len` (uint16_t) y `g_udp_batch_count` (uint8_t) como globales estáticos
- Lógica: `memcpy` al buffer → si `g_udp_batch_count >= UDP_BATCH_SIZE` → `beginPacket` + `write` + `endPacket` + reset
- Safety flush si el buffer se llenaría (no debería ocurrir con N≤12)

**`pulsenest_lab.py`:**
- `_udp_reader()`: `recvfrom(1024)` → `recvfrom(4096)`
- Loop `for line in data.split(b'\n')` — desempaqueta frames del datagrama
- Gap detection por frame (igual que antes)
- Cada frame se pone en `_udp_queue` como `line + b'\r\n'` (compatible con el pipeline downstream)

**Build:** SUCCESS (RAM 18.5%, Flash 27.4%). Flasheado y verificado OK.

---

## Sesión 2026-05-15b — Refactor UI conexión: dos botones toggle

### Problema
La UI de conexión era confusa: `btn_port_connect` no desconectaba, `btn_udp_connect` no tenía estado OFF, la fila UDP era un `HBoxLayout` apretado con 3 widgets, y `lbl_data_source` duplicaba el estado de los botones.

### Cambios en `pulsenest_lab.py`

**Sidebar:** eliminados `btn_port_connect`, `btn_udp_connect`, fila `udp_row` con label, y `lbl_data_source`. Reemplazados por:
- `btn_serial` — toggle full-width: `"USB-CDC  ●  OFF"` (gris) / `"USB-CDC  ●  ON  (COM15)"` (verde)
- `btn_udp` — toggle full-width: `"UDP WiFi  ●  OFF"` (gris) / `"UDP WiFi  ●  ON  (:5005)"` (azul)
- `spin_udp_port` — spinbox pequeño (24px alto, discreto) debajo de `btn_udp`

**Nuevos métodos:**
- `_toggle_serial()` — if connected → `_disconnect_serial()`; else → `_connect_serial(port)`
- `_disconnect_serial()` — para el reader, cierra puerto, pone botón a OFF
- `_toggle_udp()` — if alive → `_disconnect_udp()`; else → `_connect_udp()`
- `_disconnect_udp()` — para el UDP thread, drena cola, pone botón a OFF

**`_connect_serial`:** actualizado para escribir en `btn_serial` (antes `btn_port_connect`); eliminadas referencias a `lbl_data_source`.

**`_connect_udp`:** actualizado para escribir en `btn_udp` (antes `btn_udp_connect`); eliminadas referencias a `lbl_data_source`.

---

## Sesión 2026-05-15c — Eliminado spin_udp_port + persistencia estado conexiones

`spin_udp_port` eliminado del sidebar (innecesario — el puerto siempre es `UDP_DEFAULT_PORT = 5005`). `_connect_udp()` usa directamente `UDP_DEFAULT_PORT`.

**Persistencia estado conexiones en `.ini`:**
- `_save_settings()`: guarda `PPGMonitor/serial_connected` y `PPGMonitor/udp_connected` (bool)
- `_restore_settings()`: al final, llama `_connect_serial()` si `serial_connected=True` (default True) y `_connect_udp()` si `udp_connected=True` (default False)
- Eliminada llamada incondicional `self._connect_serial(...)` tras `_restore_settings()` en `__init__` — ahora la conexión la decide `_restore_settings()` según el `.ini`

`spin_udp_port` eliminado del sidebar (innecesario — el puerto siempre es `UDP_DEFAULT_PORT = 5005`). `_connect_udp()` usa directamente `UDP_DEFAULT_PORT` en lugar de `self.spin_udp_port.value()`.

---

## Sesión 2026-05-18 — Botones sidebar de dos líneas a una línea

**Cambio cosmético en `pulsenest_lab.py`:** 5 botones del sidebar que usaban `\n` para partir el texto en dos líneas se han cambiado a una sola línea:

| Antes | Después |
|---|---|
| `FREEZE\nDISPLAY` | `FREEZE DISPLAY` |
| `SAVE\nDATA` | `SAVE DATA` |
| `CAPTURE\nLAB *` | `CAPTURE LAB *` |
| `ESP32\nTIMING` | `ESP32 TIMING` |
| `PYTHON\nTIMING` | `PYTHON TIMING` |

Los `setText()` de runtime (FREEZE DISPLAY y SAVE DATA) también fueron actualizados con `replace_all`.

---

## Sesión 2026-05-18b — RESUME DISPLAY a una línea

`RESUME\nDISPLAY` → `RESUME DISPLAY` en el `setText()` de `toggle_pause()` (línea 8246).

---

## Sesión 2026-05-18c — Active transport: solo un canal alimenta los algoritmos

**Bug identificado:** con USB-CDC y UDP conectados simultáneamente, ambas colas se drenaban al mismo pipeline → cada frame procesado dos veces por todos los algoritmos.

**Solución implementada (opción automática por estado):**
- `_active_transport`: nuevo atributo en `PPGMonitor.__init__`, valor inicial `"serial"`
- `_connect_udp()` → `_active_transport = "udp"` + log `"Data source: UDP WiFi"`
- `_disconnect_udp()` → `_active_transport = "serial"` + log `"Data source: USB-CDC"`
- Drain loop en `update_data()`: flag `_is_active` por iteración de cola
  - Guards añadidos en: lab capture (pre-decimación), HR1TEST (pre-decimación), y bloque `if not _is_active: continue` justo antes de decimación
  - Frames de comando (`$CFG`, `$DIAG`, `$ERR`, `#`, `$TIMING`, `$TASK`) se procesan siempre (no guardados) — solo vienen por serial de todos modos
- USB-CDC sigue siempre abierto para comandos; UDP es datos unidireccional

---

## Sesión 2026-05-19 — Renombrar USB-CDC → SERIAL en UI

"USB-CDC" es un detalle de implementación irrelevante para el usuario. Cambiado a "SERIAL" en todos los textos visibles:
- Botón sidebar: `SERIAL  ●  OFF` / `SERIAL  ●  ON  (COMx)`
- Tooltip del botón: título `"SERIAL"`
- Tooltip UDP: `"Runs in parallel with SERIAL — ..."`
- Tooltip SERIALCOM: `"Displays raw frames received via the serial port."`
- Log: `"UDP disconnected — data source: SERIAL"`

---

## Sesión 2026-05-19b — Tooltips HW CONFIG: nombres firmware y script

Añadida línea `Lib: ...  ·  Script: ...` al final del body de cada tooltip en `HWConfigWindow`:

| Control | Lib (AFE4490Config) | Script |
|---|---|---|
| LED1 | `afe_led1_current_mA` | `_spin_led1` |
| LED2 | `afe_led2_current_mA` | `_spin_led2` |
| Range | `afe_led_range_mA` | `_combo_ledrange` |
| RF Gain | `afe_tia_gain` | `_combo_tiagain` |
| CF | `afe_tia_cf` | `_combo_tiacf` |
| Stage 2 | `afe_stage2_gain` | `_combo_stg2` |
| AMBDAC | `afe_ambdac_uA` | `_spin_ambdac` |
| Sample rate | `afe_sample_rate_hz` | `_spin_sr` |
| Averages | `afe_adc_averages` | `_spin_numav` |
| t1–t28 | `AFE4490TimingConfig::tN` | `_timing_spins['tN']` |

Los 3 casos donde el $CFG key difiere del $SET key también se anotan: `ledrange`→`range`, `tiagain`→`tia`, `tiacf`→`cf`.

---

## Sesión 2026-05-19c — ENSEPGAIN: gestión separada de ganancia TIA por LED

### Problema
El AFE4490 tiene un bit ENSEPGAIN (D15 del registro TIAGAIN) que permite configurar ganancias TIA independientes para LED1 (IR) y LED2 (RED). La arquitectura anterior usaba parámetros compartidos.

### Cambios en librería `incunest_afe4490` (v0.24)
- `AFE4490Config`: sustituidos `afe_tia_gain`, `afe_tia_cf`, `afe_stage2_gain` por:
  - `afe_ensepgain` (bool)
  - `afe_tia_gain_led1/2`, `afe_tia_cf_led1/2`, `afe_stage2_gain_led1/2`
- API pública: `setEnSepGain()`, `setTIAGainLED1/2()`, `setTIACFLED1/2()`, `setStage2GainLED1/2()`
- `setTIAGain/CF/Stage2Gain()` (joint) siguen existiendo y configuran ambos canales
- Registros: `_build_tiagain_led1()` → TIAGAIN con ENSEPGAIN bit; `_build_tia_amb_gain_led2()` → TIA_AMB_GAIN

### Cambios en firmware `main.cpp`
- `send_cfg_frame()`: nuevo formato `ensepgain=%d,tia1=%s,cf1=%s,stg21=%s,tia2=%s,cf2=%s,stg22=%s`
- `apply_set_cmd()`: nuevos handlers `ensepgain`, `tiagain1/2`, `tiacf1/2`, `stg21/22`

### Cambios en `pulsenest_lab.py` — HW CONFIG window
- Sección TIA Gain rediseñada con 3 bloques:
  1. ENSEPGAIN checkbox + Set button (greyed LED1 controls when OFF)
  2. LED1 (IR) sub-sección: RF Gain (`_combo_tiagain1`), CF (`_combo_tiacf1`), Stage 2 (`_combo_stg21`)
  3. LED2 (RED) sub-sección — always active: RF Gain (`_combo_tiagain2`), CF (`_combo_tiacf2`), Stage 2 (`_combo_stg22`)
- `update_from_cfg()`: parsea `ensepgain`, `tia1`, `cf1`, `stg21`, `tia2`, `cf2`, `stg22`
- `_on_set_all()`, `_on_save_to_file()`, `_on_read_from_file()`: actualizados con nuevos keys
- `_mark_dirty/clean()`: soporte para QCheckBox
- `_on_ensepgain_changed()`: habilita/deshabilita controles LED1

---

## Sesión 2026-05-19d — Default ENSEPGAIN=true en librería

Cambiado el valor por defecto de `_afe_ensepgain` en el constructor de `INCUNEST_AFE4490` de `false` a `true`.

**Motivo:** con la nueva arquitectura separada (v0.24), el modo por defecto debe ser ganancia independiente por canal, que es el comportamiento más flexible y seguro para el lab.

**Valores por defecto recomendados y confirmados (sin cambio):**
- RF: 500 KΩ (ambos canales)
- CF: 5 pF (ambos canales) — más fácil de satisfacer requisito §8.3.1.1
- Stage 2: 0 dB (ambos canales)

Commit en `incunest_afe4490`: `8ec2b74`. Build y flash a COM15 correctos.

---

## Sesión 2026-05-19e — Fixes: botón RESET ESP32 + Timing Registers tras reset

### Fix 1: botón "RESET\nESP32" → "RESET ESP32"
Texto en dos líneas cambiado a una sola línea.

### Fix 2: Timing Registers a cero tras RESET ESP32
**Causa raíz:** el timer de 2500ms en `_reset_esp32()` disparaba `$CFG?` mientras el firmware aún estaba en `setup()` esperando WiFi (hasta 10 × 500ms = 10 s). `Cmd_Task` no había arrancado aún → `$CFG?` se perdía → `$TCFG` nunca llegaba → timing registers quedaban a cero.

**Fix:** sustituido el timer fijo por un flag reactivo `_post_reset_cfg_pending`:
- `_reset_esp32()`: pone `_post_reset_cfg_pending = True`
- Drain loop: cuando detecta `"# incunest_afe4490 started"` (mensaje emitido por `start_incunest()`, exactamente cuando `Cmd_Task` ya está corriendo), si el flag está activo lo limpia y dispara `_on_read_cfg()` con 300ms de margen.

---

## Sesión 2026-05-19f — Commits y cierre de sesión

### Commits realizados

**`incunest_afe4490`** → `7659d31`
- `docs: merge §11.1 timing tables into single temporal-order table`
- Las dos tablas de §11.1 (comparativa histórica + secuencia temporal) unificadas en una sola tabla ordenada por secuencia temporal con columnas: `# | Identifier | Default (counts) | Rationale | Constraints`
- Comparativas históricas movidas a notas al pie

**`PulseNest`** → `31196f6`
- `fix: RESET ESP32 button label + timing registers post-reset refresh`
- Commits de los fixes de sesión 19e

### Investigación ALED2STC / RED_Amb
Explicación del comportamiento:
- A 50 mA: el transitorio de apagado del LED contamina la ventana de muestra ambiental cuando t5=200. Al mover t5=1200 el transitorio ya ha decaído → RED_Amb baja (lectura más limpia, correcta).
- A 11.7 mA: el transitorio es despreciable, la posición de t5 no afecta.
- Base física: tiempo de asentamiento del TIA = τ = RF×CF; la ventana ambiental debe empezar ≥ 5τ tras el apagado del LED.

### Pendientes para próximas sesiones
- Verificar RF×CF < RxSampleTime/10 (§8.3.1.1) para config actual
- RSQM (PRIORIDAD MÁXIMA)
- HGAC (depende de RSQM)
- Probe presence detection
- HR artefact testing
- HR1 improvements (opción A y B)

---

## Sesión 2026-05-20 — Exploración reordenación timing registers (revertida)

### Explorado y revertido
Se intentó reordenar `_TIMING_REGS` en `HWConfigWindow` siguiendo el orden cronológico de `_apply_timing_regs()` de la librería:
- LED2 drive (t3,t4) → LED2 sample (t1,t2) → ALED2 sample (t5,t6)
- LED1 drive (t9,t10) → LED1 sample (t7,t8) → ALED1 sample (t11,t12)
- ADC resets t21–t28 → ADC conversions t13–t20

El usuario pidió deshacer el cambio → `_TIMING_REGS` queda en orden numérico t1→t28 (estado original).

---

## Sesión 2026-05-20b — Reordenación timing registers según §11.1 de la spec

### Cambio realizado
**`pulsenest_lab.py`** — `_TIMING_REGS` en `HWConfigWindow` reordenado siguiendo el orden temporal exacto de la tabla de §11.1 de `incunest_afe4490_spec.md`.

Orden resultante (28 entradas, por posición temporal dentro del ciclo):
t21, t22, t13, t5, t6, t14, t23, t9, t24, t15, t7, t8, t10, t16, t25, t26, t17, t11, t12, t18, t27, t3, t28, t19, t1, t2, t4, t20

### Decisiones
- Fuente canónica: tabla de §11.1 de `incunest_afe4490_spec.md` (columna "temporal sequence").
- Se actualizaron también las descripciones (tooltips) de cada registro para reflejar los constraints exactos de §11.1.

---

## Sesión 2026-05-20c — Short name en tooltips de Timing Registers + spec §11.1

### Cambios realizados

**`incunest_afe4490_spec.md`** — Columna Identifier de la tabla §11.1 ampliada con el nombre corto del datasheet (Fig. 83–110), formato `**tN** REGNAME — *short name*`. Ejemplo: `**t7** LED1STC — *Sample LED1 start count*`.

**`pulsenest_lab.py`** — `_TIMING_REGS` cambiado de tuplas de 3 a tuplas de 4 elementos `(key, reg_name, short_name, description)`. Tooltips de cada timing register actualizados con el formato:
```
tN — REGNAME
─────────────
short name (datasheet)

<constraints>

Sends $SET,tN,<value>.
Lib: AFE4490TimingConfig::tN  ·  Script: _timing_spins['tN']
```

### Decisiones
- Short names extraídos directamente de los títulos de campo del datasheet (Figs. 83–110, pp. 60–71).
- No columna nueva en la tabla de la spec; el nombre corto se añade dentro del Identifier con `—` como separador.
- En el script, `timing_info` dict (usado en save-to-file) actualizado para ignorar el nuevo campo (`_sn`).

---

## Sesión 2026-05-20d — Fix truncación de tooltips por carácter `<`

### Problema
Qt interpreta `<` en texto de tooltip como inicio de tag HTML → el texto se truncaba a partir del primer `<` (frecuente en constraints como `< t22`, `≥ t2+1`).

### Fix
**`pulsenest_lab.py`** — `_make_tooltip()`: añadida función interna `_esc()` que escapa `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;` y `\n` → `<br/>` antes de insertar `name` y `text` en el HTML. Fix global: afecta a todos los tooltips del script.

---

## Sesión 2026-05-20e — Fix línea nueva entre Lib y Script en tooltip timing registers

**`pulsenest_lab.py`** — En `_tip_body` de los timing registers, separado `Lib:` y `Script:` en líneas distintas (`\n` entre ambos). Antes aparecían en la misma línea separados por `·`.

---

## Sesión 2026-05-20f — Fix `\n` sobrante en tooltip timing registers

**`pulsenest_lab.py`** — Eliminados los `\n` iniciales en las líneas de `tip` y `Sends $SET` dentro de `_tip_body` (líneas 5397–5398). Producían líneas en blanco innecesarias en el tooltip.

---

## Sesión 2026-05-20g — Implementación STAGE2EN1 y STAGE2EN2 (v0.26)

### Pregunta clave
¿Por qué AMBDAC>0 fuerza STAGE2EN2 pero no STAGE2EN1?

### Respuesta correcta (tras dos correcciones del usuario)
- No existe un bit llamado "STAGE2EN" sin sufijo. Los bits son STAGE2EN1 (D14 de TIAGAIN) y STAGE2EN2 (D14 de TIA_AMB_GAIN).
- AMBDAC es un DAC único compartido por ambos canales. El hecho de que esté en TIA_AMB_GAIN es circunstancial.
- STAGE2EN1 no se fuerza porque el AMBDAC está físicamente conectado al Stage 2 del camino de TIA_AMB_GAIN. La corriente de cancelación nunca pasa por el Stage 2 de TIAGAIN.

### Decisiones de diseño (v0.26)
- STAGE2EN1 y STAGE2EN2 son parámetros explícitos e independientes del gain.
- `stg2_gain_code[]` contiene solo bits D[10:8] (sin D14). STAGE2EN es bit separado.
- `setStage2GainLED1/LED2()` solo cambia el gain, NO toca el enable.
- `setStage2En1(bool)` y `setStage2En2(bool)` controlan los enable bits.
- STAGE2EN2 sigue siendo forzado ON cuando AMBDAC>0.
- Default: STAGE2EN1=false, STAGE2EN2=false.

### Cambios
- **`incunest_afe4490.h`**: `AFE4490Config` gana `afe_stage2_en1/en2`; API pública gana `setStage2En1/En2()`; privados gana `_afe_stage2_en1/_en2`.
- **`incunest_afe4490.cpp`**: `stg2_code[]` → `stg2_gain_code[]` sin bit EN; constructor init; setters nuevos; build functions y `getConfig()` actualizados.
- **`main.cpp`**: `$CFG` añade `stage2en1/2=%d`; `$SET` añade handlers `stage2en1/2`.
- **`pulsenest_lab.py`**: HW CONFIG TIA section añade checkboxes STAGE2EN1/STAGE2EN2; `_on_ensepgain_changed`, dirty/clean tracking y $CFG parsing actualizados.
- **`incunest_afe4490_spec.md`**: §2.3a, §2.3b, tabla Stage 2 y §13 actualizados. Versión v0.26.

---

## Sesión 2026-05-20h — STAGE2EN1/2: QCheckBox → QComboBox FALSE/TRUE

**`pulsenest_lab.py`** — `_chk_stage2en1` y `_chk_stage2en2` reemplazados por `_combo_stage2en1` y `_combo_stage2en2` (QComboBox con items ["FALSE", "TRUE"]). Uso de `_make_row()` estándar. Actualizados: `_on_ensepgain_changed`, `_on_set_all`, `_on_save_to_file`, `_on_read_from_file`, `update_from_cfg`, dirty/clean tracking list.

---

## Sesión 2026-05-20i — STAGE2EN1/2 default ON + aviso puerto serie cerrado

### Cambios
- **`incunest_afe4490.cpp`**: `_afe_stage2_en1` y `_afe_stage2_en2` cambiados de `false` a `true` en el constructor (default ON).
- **`incunest_afe4490_spec.md`**: default de STAGE2EN1/2 cambiado a `true` en tabla Stage 2.
- **`pulsenest_lab.py`**: añadido `_warn_not_connected()` en `HWConfigWindow` — muestra `QMessageBox.warning()` + mensaje en status bar cuando se intenta enviar un comando con el puerto cerrado. Usado en `_send_set()`, `_on_read_cfg()` (HWConfigWindow) y `_on_run()` (DiagWindow).

---

## Sesión 2026-05-20j — $CFG? sin respuesta: diagnóstico + fixes

### Problema investigado
"Read from chip ($CFG?)" no muestra ninguna respuesta visible. Investigación del flujo completo:
- Firmware: `Cmd_Task` recibe `$CFG?` → llama `send_cfg_frame()` → emite `$CFG,...*XX\r\n`
- Python: serial reader verifica checksum NMEA XOR → si OK, llama `_on_cfg_frame_received()` → llama `update_from_cfg()`
- Checksum firmware y Python calculan XOR idéntico (bytes 1..n-1 tras `$`). No hay desbordamiento de buf[400] (~283 chars reales).
- **Causa raíz identificada**: problemas de UX, no de checksum. El `_on_read_cfg` no mostraba ningún mensaje de estado al enviar la solicitud, y no había timeout si no llegaba respuesta.

### Cambios — `pulsenest_lab.py`
1. **`HWConfigWindow.__init__`**: añade `_cfg_timer` (QTimer single-shot, 3 s) conectado a `_on_cfg_timeout`.
2. **`_on_cfg_timeout()`**: nuevo método — muestra `"⚠ No response from chip — check connection and firmware"` en statusbar cuando no llega respuesta en 3 s.
3. **`_on_read_cfg`**: muestra `"$CFG? sent — waiting for response…"` en statusbar + arranca `_cfg_timer`.
4. **`_send_set`**: también arranca `_cfg_timer` tras enviar `$SET`.
5. **`update_from_cfg`**: llama `_cfg_timer.stop()` cuando llega la respuesta (antes de "Config loaded from chip").
6. **`_on_cfg_frame_received`**: log y text actualizados — claves viejas (`tia`, `cf`, `stg2`) reemplazadas por `tia1/2`, `cf1/2`, `stg21/22`; añadidos `ensepgain`, `stage2en1/2`, `ambdac`.

---

## Sesión 2026-05-20k — Silenciar [GAP B/SERIAL] messages

**`pulsenest_lab.py`**: comentada la línea `self._sig_log.emit(f"[GAP B/SERIAL] ...")` en el serial reader thread. El contador `_gaps_B` sigue acumulando; solo suprimida la visualización en el log.

---

## Sesión 2026-05-20l — Serial mutex: fix frame interleaving entre tareas FreeRTOS

### Diagnóstico
Los frames $M1 llegaban fragmentados/corruptos (BAD CHK en COM window). Causa raíz: `Data_Task` (500 Hz, $M1/$M2) y `Cmd_Task` ($CFG, $DIAG, $ERR) escribían en Serial concurrentemente sin exclusión mutua. Los bytes se entrelazaban a nivel de carácter. Esto explica también por qué $CFG? no recibía respuesta: el frame $CFG llegaba partido por un $M1 y la primera mitad no empezaba con `$CFG,`.

El problema existía antes pero era invisible: la validación de checksum con reporte BAD CHK es infraestructura nueva — antes los frames corruptos se descartaban silenciosamente por el check `>= 20 partes`.

### Cambios — `src/main.cpp`
- `#include <freertos/semphr.h>` añadido
- `static SemaphoreHandle_t g_serial_mutex` declarado globalmente (creado en `setup()` antes de arrancar tareas)
- `Serial_printf()` actualizado para tomar/dar mutex (timeout 20 ms)
- `Serial_print_locked(const char*)` nuevo helper para buffers pre-construidos
- Todos los `Serial.print(buf)` en tareas ($M1, $M2, $CFG, $TCFG, $DIAG) → `Serial_print_locked(buf)`
- `Serial.println("# Frame mode...")` en Cmd_Task → `Serial_printf(...)`
- `Serial.println("# incunest_afe4490 started")` en `start_incunest()` → `Serial_printf(...)`
- Las llamadas `Serial.printf/println` en `setup()` (antes de crear tareas) no necesitan mutex y se mantienen directas.

### Estado
Compilado OK. Upload pendiente (COM15 ocupado por script Python).

---

## Sesión 2026-05-20m — Upload bloqueado: estado anómalo ESP32 + reinicio PC

### Estado al cerrar sesión

**Firmware compilado OK** (serial mutex, sesión 2026-05-20l) pero **upload fallido** en todos los intentos.

Cronología del problema:
1. `taskkill //F //IM pythonw.exe` mató el script sin liberar COM15 correctamente → upload fallaba con "Wrong boot mode (0x2b)"
2. Intento de limpieza con Python a 1200 baud + `dsrdtr=True` — posiblemente dejó el ESP32 en estado incorrecto
3. PowerShell `CloseMainWindow()` cerró el script Qt (lo que disparó `_reset_esp32()` internamente, manteniendo EN bajo)
4. Power cycle de la placa → COM15 vuelve a aparecer pero envía datos binarios (0xBF, 0xB7...) en lugar de frames ASCII — firmware en estado anómalo
5. Usuario reinicia PC para limpiar estado

**Próximos pasos al reabrir:**
1. Tras reinicio PC, verificar que `pio run -e incunest_V16 -t upload --upload-port COM15` funciona normalmente
2. Si funciona: el problema era estado del driver USB-CDC de Windows — resuelto con reinicio
3. Lanzar script y verificar ausencia de BAD CHK en COM window (confirmar fix del serial mutex)
4. Si $CFG? responde correctamente → cerrar bug

### Lección aprendida sobre el flujo de upload
El `taskkill //F //IM pythonw.exe` deja el puerto COM15 en estado inválido para el upload.
**Flujo correcto:** `PowerShell CloseMainWindow()` → esperar 2s → `pio run -t upload`.
Actualizar memory con este flujo corregido.

---

## Sesión 2026-05-21

### Tema: Verificación post-reinicio + LED current quantization (v0.25)

---

**Upload verificado tras reinicio de PC**

Primera secuencia BOOT+EN: el ESP32 conectó pero cayó mid-flash (`The chip stopped responding`).
Segunda secuencia BOOT+EN: upload completo exitoso. RAM 18.5%, Flash 27.5%.
Script lanzado → sin BAD CHK en COM window → fix del serial mutex confirmado.

---

**Conversión ADC → voltios (consulta)**

Fórmula confirmada para el AFE4490 (ADC 22-bit two's complement, VRef=1.2V):
- `V_ADC = count × 1.2 / 2²¹` (LSB ≈ 572 nV)
- `V_TIA = V_ADC / Gstg2`
- `I_PD = V_TIA / RF`

---

**SIGNAL STATS — intervalo de cálculo (consulta)**

El timer `_stats_timer` dispara cada `spin_stats_interval` segundos (por defecto 1 s, rango 1–60 s). En cada tick se calculan Last/Mean/Min/Max sobre las muestras acumuladas en `_stats_buf` desde el tick anterior, y luego se hace `.clear()`. A 50 Hz y decimación ×10: ~50 muestras por segundo por señal.

---

**LED current quantization — librería v0.25**

**Problema identificado:** `setLED1/2Current()` almacenaba el valor float solicitado. El chip programa un DAC de 8 bits → solo 256 valores posibles (step = range/256). `getConfig()` devolvía el valor solicitado, no el real programado.

**Decisión:** `setLED1/2Current()` y `setLEDRange()` almacenan siempre el valor cuantizado al grid DAC. `getConfig()` devuelve automáticamente el valor real.

**Implementación en `incunest_afe4490` (v0.25):**
- Nueva función privada `_quantize_led_mA(float mA) const`:
  ```cpp
  uint8_t code = round(mA / range * 256);  // 0–255
  return code / 256.0f * range;
  ```
- `setLED1Current()` / `setLED2Current()`: almacenan `_quantize_led_mA(constrain(mA, 0, range))`
- `setLEDRange()`: tras actualizar `_afe_led_range_mA`, re-cuantiza ambas corrientes al nuevo grid
- Constructor: cuantiza los valores iniciales (11.7 mA → **11.71875 mA** con range 150 mA)
- `_apply_analog_regs()`: sin cambios (el código ya era `round(mA/range*256)`, idempotente con valor pre-cuantizado)

**Spec:** `setLED1/2Current()` comentados con "stored as actual DAC-quantised value"; `setLEDRange()` con "re-quantises both LED currents"; `AFE4490Config::afe_led1/2_current_mA` con "actual DAC-quantised value". Changelog v0.25 añadido.

**Script (`pulsenest_lab.py`):** sin cambios necesarios. El valor que muestra HW CONFIG viene de `$CFG` → `getConfig()` → ya cuantizado.

**Build:** SUCCESS. RAM sin cambio, Flash +172 bytes.

**Commit:** `29b37c9` — `feat: quantise LED current to DAC grid in setters (v0.25)`. Push y flash exitosos.

---

## Sesión 2026-05-21d

### Tema: Hardware probe states + nomenclatura NO_TISSUE

**Estados hardware del AFE4490** documentados en spec §12.3 y absorbidos en RSQM (de project_limb_detection_task):

| Estado | led1/led2/aled1/aled2 | Causa física |
|---|---|---|
| CABLE_DISCONNECTED | ≈ −5000 todos | Fotodiodo en circuito abierto |
| NO_TISSUE | led1/led2 saturados | Sin atenuación de tejido |
| PROBE_ON_PATIENT | señal PPG normal | Operación normal |

**Nomenclatura decidida:** `NO_TISSUE` (no `PROBE_DETACHED`, no `PROBE_OFF`) — describe la realidad física inequívocamente: no hay tejido entre emisor y detector.

**DiagCode ampliado:**
- bit 6: `RSQM_NO_TISSUE`
- bit 7: `RSQM_CABLE_DISCONNECTED`

**HGAC:** no actúa en `NO_TISSUE` ni `CABLE_DISCONNECTED`. Solo actúa en `PROBE_ON_PATIENT`.

**project_limb_detection_task** absorbida en project_rsqm_task.

---

## Sesión 2026-05-21c

### Tema: Saturación AFE4490 + §12 spec (datasheet↔librería) + rename setPPGDispFilter

---

**Pregunta:** valor constante 2,096,921 en los 4 canales ADC al exponer la sonda a luz de ventana — ¿saturación de TIA o de ADC?

**Conclusión:** saturación de **TIA**, no del ADC.
- Máximo positivo 22-bit (signed): 2^21 − 1 = 2,097,151
- El valor observado (2,096,921 = 0x1FFD19) es 230 cuentas por debajo del máximo teórico → no es un clip digital limpio
- Saturación del ADC produciría exactamente 0x1FFFFF; saturación de TIA produce un valor "cerca del máximo pero no exactamente" porque la salida de la TIA ralla contra AVDD sin llegar exactamente al nivel de referencia del ADC
- Los 4 canales iguales confirman que la luz ambiente satura la TIA en las 4 fases del ciclo (LED1 on, LED2 on, ambient1, ambient2)
- Relevante para RSQM: umbral de detección ~95% del máximo (~1,992,294) en ALED1/ALED2

---

**Spec §12 nueva: "Datasheet-to-library identifier mapping"** (para referencia en diseño de HGAC/RSQM)

Añadida como §12 entre "AFE4490 chip register configuration" (§11) y "Bibliographic references" (→ renumerada §13). "Version history" → §14.

§12.1 — Analog gain parameters:

| Datasheet | Registro | AFE4490Config | Setter |
|---|---|---|---|
| RF_LED1 | TIAGAIN D[2:0] | afe_tia_gain_led1 | setTIAGain() |
| RF_LED2 | TIA_AMB_GAIN D[2:0] | afe_tia_gain_led2 | setTIAGain() (shared ENSEPGAIN=0) |
| STG2GAIN1 | TIAGAIN D[10:8] | afe_stage2_gain_led1 | setStage2GainLED1() |
| STG2GAIN2 | TIA_AMB_GAIN D[10:8] | afe_stage2_gain_led2 | setStage2GainLED2() |
| AMBDAC | TIA_AMB_GAIN D[19:16] | afe_ambdac_uA | setAmbDac() |
| LED1 (IR) | LEDCNTRL D[15:8] | afe_led1_current_mA | setLED1Current() |
| LED2 (RED) | LEDCNTRL D[7:0] | afe_led2_current_mA | setLED2Current() |

§12.2 — ADC data registers: LED2VAL→led2, ALED2VAL→aled2, LED1VAL→led1, ALED1VAL→aled1, LED2−ALED2VAL→led2_aled2, LED1−ALED1VAL→led1_aled1.

Nota: campos sin underscore inicial — referencian `AFE4490Config` (struct público), no los miembros privados de la clase.

---

**Rename: `setFilter()` → `setPPGDispFilter()`**

Razón: el nombre genérico no reflejaba que aplica exclusivamente al canal de display PPG (ppgdisp). Renombrado en:
- `incunest_afe4490.h` (declaración + comentario privado)
- `incunest_afe4490.cpp` (definición)
- `incunest_afe4490_spec.md` (todas las ocurrencias)
- `PulseNest/src/main.cpp` (llamada activa)
- `incunest_afe4490/examples/basic/main.cpp` y `PulseNest/examples/basic/main.cpp` (comentarios)
- `conversation_log.md` y `OLD_spec` no tocados (histórico)

---

**Decisiones de diseño HGAC (arquitectura, sin implementar aún):**
- HGAC vivirá **dentro de la librería** (mismo argumento que HR1/HR2/SpO2: acceso directo a datos por muestra, y los cambios de parámetro necesitan disparar resets internos)
- Velocidad de respuesta: **ventana de ~2 s** (cubre bradicardia hasta 30 bpm con margen; 40 bpm = límite inferior definido → ciclo 1.5 s)
- Lectura de parámetros actuales vía `getConfig()` (no acceso a miembros privados)
- Escritura vía setters públicos
- Sin buffer de muestras — acumuladores estadísticos ligeros (máx, mín, contador saturaciones) reseteados cada ventana

---

## Sesión 2026-05-21b

### Tema: Fix comentario GAIN_0DB en AFE4490Stage2Gain

**Problema:** `GAIN_0DB` tenía el comentario "Stage 2 disabled (default)" en `incunest_afe4490.h` y `incunest_afe4490_spec.md`. Incorrecto: `GAIN_0DB` = STG2GAIN bits = 0b000 → ganancia ×1 (0 dB), Stage 2 **activa**.

**Cómo se deshabilita Stage 2 realmente:** bit `STAGE2EN` (D14 del registro TIAGAIN), controlado por `_afe_stage2_en1` / `_afe_stage2_en2` y los setters `setEnStage2GainLED1/2(false)`. Completamente independiente del valor de ganancia.

**Fix:** comentario corregido en `incunest_afe4490.h` (línea 115) y `incunest_afe4490_spec.md` (línea 354) a `"0 dB (×1, unity gain) — Stage 2 active; disable via setEnStage2GainLED1/2(false)"`. Sin cambio de comportamiento, sin recompilación necesaria.

**Pendiente:** incluir en el próximo commit junto con otros cambios menores, o hacer commit independiente.

---

## Sesión 2026-05-23a

### Tema: Multi-WiFi fallback en wifi_config.h y main.cpp

**Contexto:** Alex trabaja en una ubicación diferente con una WiFi distinta (RAPTURE_5G) y necesita que el firmware conecte automáticamente a cualquiera de las dos redes disponibles.

**Cambios realizados:**

**`include/wifi_config.h`:**
- Eliminados `#define WIFI_SSID`, `#define WIFI_PASSWORD`, `#define UDP_TARGET_IP`
- Añadido struct `WifiNetwork { ssid, password, udp_target_ip }`
- Array `WIFI_NETWORKS[]` con dos entradas:
  - `{ "ACM-ASUS-RT-B50", "retuerta", "192.168.50.88" }` — Lab
  - `{ "RAPTURE_5G",      "retuerta", "192.168.50.88" }` — Remote site
- `WIFI_NETWORK_COUNT` calculado con sizeof
- `UDP_TARGET_PORT` y `UDP_BATCH_SIZE` conservados como defines

**`src/main.cpp`:**
- Nueva global `static const char* g_udp_target_ip = nullptr` — se asigna al conectar
- Bloque de conexión WiFi reemplazado por loop sobre `WIFI_NETWORKS[]`: prueba cada red 10 s (20 × 500 ms), `WiFi.disconnect()` si falla, continúa con la siguiente
- `UDP_TARGET_IP` reemplazado por `g_udp_target_ip` en `beginPacket()` y en el `Serial.printf` de confirmación
- Mensaje Serial por red: `"# WiFi trying [N/M] SSID..."` / `"# WiFi FAILED for SSID"` / `"# WiFi FAILED all networks"`

**Para añadir redes futuras:** una línea más en el array `WIFI_NETWORKS[]`, sin tocar main.cpp.

---

## Sesión 2026-05-23b

### Tema: Fix — mensajes WiFi no aparecían en el log principal del script

**Problema:** tras el reset del ESP32 con el botón "RESET ESP32", los mensajes `# WiFi trying...`, `# WiFi connected...` y `# WiFi FAILED...` no aparecían en el log principal de `pulsenest_lab.py`. Sí llegaban al COM window (raw), pero el bloque de procesamiento de líneas `#` solo loguea explícitamente:  `# ...incunest...`, `# ...frame mode...`, `# SYS:...`

**Fix (`pulsenest_lab.py` línea ~8839):** añadido `elif line.startswith('# WiFi'): self.log(line[2:].strip())` para que todos los mensajes WiFi del firmware aparezcan en el log principal.

---

## Sesión 2026-05-23c

### Tema: Diagnóstico fallo WiFi RAPTURE_5G — scan + razón de fallo

**Problema:** el ESP32 no conectaba a RAPTURE_5G. Hipótesis principal: el ESP32-S3 solo tiene radio 2.4 GHz — si RAPTURE_5G es una red de 5 GHz, el chip no puede verla.

**Cambios firmware (`src/main.cpp`):**
- Añadido escaneo de redes visibles (`WiFi.scanNetworks()`) antes del primer intento de conexión. Imprime SSID, RSSI y canal de cada red visible en el log.
- Añadido `switch(WiFi.status())` tras fallo de conexión con razones legibles: `SSID_NOT_FOUND`, `CONNECT_FAILED`, `CONNECTION_LOST`, `DISCONNECTED`, `UNKNOWN`.

**Cambios script (`pulsenest_lab.py`):**
- Extendida la condición de log para mostrar también las líneas `#   [N]` del scan de redes.

**Diagnóstico esperado:** si RAPTURE_5G no aparece en el scan → confirmado 5 GHz → solución: usar el SSID equivalente 2.4 GHz del router (buscar en config del router ASUS Rapture).

---

## Sesión 2026-05-23d

### Tema: Corrección SSID WiFi — RAPTURE_5G → RAPTURE

**Diagnóstico confirmado:** el escaneo del firmware reveló que RAPTURE_5G no aparecía en las redes 2.4 GHz visibles. El SSID correcto para 2.4 GHz es "RAPTURE".

**Cambio (`include/wifi_config.h`):** `"RAPTURE_5G"` → `"RAPTURE"` (con comentario `// Remote site (2.4 GHz)`).

**Flash:** build exitoso, upload fallido por COM15 ocupado (script abierto). Pendiente reflashear con puerto libre.

---

## Sesión 2026-05-25a

### Tema: HGAC — constantes TIA operating range en incunest_afe4490.cpp

**Contexto:**
Continuación de la sesión anterior (2026-05-21d). Análisis de arquitectura AFE4490 completado en sesión anterior: AMBDAC actúa en Stage 2 (después de TIA), no antes. TIA full-scale = ±1 V, ADC full-scale = ±1.2 V.

**Cambios firmware (`incunest_afe4490/incunest_afe4490.cpp`):**
- Añadidas dos constantes en el anonymous namespace (sección HGAC):
  - `hgac_tia_sat_adc = 1747626` — ADC count correspondiente a +1.0 V diferencial en salida TIA (saturación TIA, alarma)
  - `hgac_tia_ideal_adc = 1048576` — ADC count correspondiente a +0.6 V diferencial en salida TIA (Ideal Operating Point, Fig. 135 datasheet)
- Fórmula: `count = round(V / 1.2 × 2^21)`. Nota: 1048576 = 2²⁰ exacto (0.6/1.2 = 0.5).
- Referencia: AFE4490 datasheet Fig. 135 ("AGC Loop"), §9.2.2. Válido a Stage 2 gain = 0 dB.

**Decisiones:**
- Las constantes van en el anonymous namespace del .cpp (no en el .h), son internas al HGAC.
- AMBDAC no puede corregir saturación TIA — solo RF↓ y LEDmA↓ actúan antes de la TIA.
- Renombradas las constantes: `_counts` → `_adc` (`hgac_tia_sat_adc`, `hgac_tia_ideal_adc`).
- Renombradas de nuevo: `_adc` → `_volt` (`hgac_tia_sat_volt = 1.0f`, `hgac_tia_ideal_volt = 0.6f`). Las constantes `_adc` solo eran válidas con Stage2 gain=0dB y AMBDAC=0; las `_volt` son siempre válidas.
- Añadido comentario con fórmula completa de recuperación: `tia_volt = (adc * 1.2f / 2097152.0f) / rg_gain + ambdac_val * 0.2f`. Derivada de Eq.2 del datasheet. AMBDAC LSB = 1µA (valores 0–10), coeficiente 0.2V/step = 2 × Ri × 1µA = 2 × 100kΩ × 1µA. Cuando STAGE2EN=0: tia_volt = adc * 1.2f / 2097152.0f.
- Confirmado leyendo datasheet (Fig. 115, pág. 75): AMBDAC[3:0] = 0–10 µA en pasos de 1µA; valores 11–15 = "do not use".
- Confirmado leyendo datasheet (pág. 59, CONTROL0 bit D2): DIAG_EN se auto-limpia al terminar el diagnóstico (slow=16ms, fast=8ms) → tarea project_diag_en_poll_task resuelta.
- Añadida constante `hgac_tia_thr_volt = 0.9f` — threshold para reducir LEDmA/RF antes de llegar a saturación TIA (0.9V, entre _thr y _sat). Las tres constantes: sat=1.0V (hard limit), thr=0.9V (soft threshold LEDmA/RF), ideal=0.6V (operating point).

**Sesión 2026-05-25b — análisis Fig. 135 y dominio de hgac_tia_ideal_volt**

- Debate: ¿el "Ideal Operating Point" de +0.6V en Fig. 135 es V_TIA o V_ADC?
- §9.2.2 dice "target dc voltage at the ADC input to approximately 50% of full scale" → apuntaba a V_ADC.
- Decisión final: **mantener `hgac_tia_ideal_volt = 0.6f` como V_TIA**. Razones:
  - **Seguridad**: restricciones TIA (±1V) y target en el mismo dominio — sin conversiones propensas a error.
  - **Fidelidad**: la TIA es la primera etapa; el SNR se establece aquí. Mantener 0.6V en TIA maximiza señal en el punto crítico, independientemente de Stage 2.
  - **Linealidad**: la especificación de linealidad es referida a la salida TIA (±1V); operar al 60% garantiza linealidad. Con target V_ADC y Stage 2 gain=2, el TIA operaría al 30% — subóptimo.
- Fig. 135 mezcla dominios porque asume Stage 2 gain=1 (por defecto), donde V_ADC = V_TIA y la distinción desaparece. La figura es ambigua para Stage 2 activo.
- Las tres constantes `hgac_tia_*` son todas V_TIA y se comparan contra `tia_volt` (fórmula de recuperación). No mezclar con lecturas ADC directas.

---

## Sesión 2026-05-23e

### Tema: NVS last_net + quitar WiFi scan + last_wifi_ssid en ini

**Cambios firmware (`src/main.cpp`):**
- Añadido `#include <Preferences.h>`
- Eliminado bloque de scan WiFi (`WiFi.scanNetworks()`)
- Añadida lógica NVS con `Preferences` namespace "pulsenest", key "last_net" (int):
  - Al boot: lee `last_net` (default 0), el loop empieza por ese índice con `(last + i) % WIFI_NETWORK_COUNT`
  - Tras conexión exitosa: guarda el índice en NVS para el siguiente boot
- Mensaje "WiFi connected" ahora incluye SSID entre corchetes: `# WiFi connected [SSID] — IP ...`
- Flash pendiente (COM15 ocupado al intentar)

**Cambios script (`pulsenest_lab.py`):**
- En el handler de líneas `# WiFi`: detecta "WiFi connected [SSID]" con regex, guarda `PPGMonitor/last_wifi_ssid` en pulsenest_lab.ini

---

---

## Sesión 2026-05-25c

### Tema: Convención de nombres led1/led2 vs ir/red — formalización y aplicación

**Regla formalizada:**
- `_led1/_led2` = lecturas crudas del hardware (sin filtrar ni procesar). Se usan en: registros AFE4490, structs de datos hardware (`AFE4490Data`), parámetros de funciones que reciben valores directamente del ADC, HGAC (controlador hardware puro).
- `_ir/_red` = valores procesados/interpretados dentro de algoritmos fisiológicos (SpO2, HR). El nombre sigue al dato, no a la función.
- En la frontera hardware→algoritmo: el parámetro de la función usa el nombre hardware (`led1_aled1`); la primera línea dentro del algoritmo lo convierte a nombre funcional (`float ir = (float)led1_aled1`).

**Revisión de la librería:**
- `_spo2_dc_ir`, `_spo2_dc_red`, etc. — 100% coherentes, todos en dominio SpO2. Sin cambios.
- SpO2 ya hacía la conversión en la frontera: `float ir = ...; float red = ...;` en `_update_spo2()`.
- HR1/HR2/HR3: parámetros `led1_aled1` correctos (valor crudo), pero internamente no tenían conversión explícita.

**Cambios en `incunest_afe4490.cpp`:**
- `_update_hr1()`: `float s = (float)led1_aled1` → `float ir = (float)led1_aled1` (y sus usos `s` → `ir`)
- `_update_hr2_sample()`: añadido `float ir = (float)led1_aled1;`, sustituido inline cast
- `_update_hr3_sample()`: añadido `float ir = (float)led1_aled1;`, sustituido inline cast
- Wrappers `_update_hr2()` / `_update_hr3()`: sin cambios (reenvían el parámetro sin usarlo directamente)

**HGAC:** usa `_led1/_led2` en todo su dominio (incluyendo señales procesadas como `sig_led1_pct`, `tia_led1`) porque es un controlador de hardware puro, no un algoritmo fisiológico.

**Ficheros de memoria actualizados:** `MEMORY.md`, `project_naming_convention_task.md` (status: done), `project_agc_design.md` (HGACInput struct).

---

## Sesión 2026-05-26a

### Tema: Revisión convención nombres led1/led2 vs ir/red + diseño detallado HGAC

**Convención de nombres — regla formalizada:**
- `_led1/_led2` = lecturas crudas del hardware (sin filtrar ni procesar), incluyendo todo el dominio HGAC.
- `_ir/_red` = valores procesados/interpretados dentro de algoritmos fisiológicos (SpO2, HR).
- En la frontera hardware→algoritmo: parámetro de la función usa nombre hardware (`led1_aled1`);
  primera línea dentro del algoritmo convierte a nombre funcional (`float ir = (float)led1_aled1`).
- SpO2 ya lo hacía correctamente. HR1/HR2/HR3 corregidos en esta sesión.
- HGAC usa `_led1/_led2` en todo su dominio (es controlador hardware puro, no algoritmo fisiológico):
  `amb_led1_pct`, `amb_led2_pct`, `sig_led1_pct`, `sig_led2_pct`, `pi_led1`, `tia_led1`, `tia_led2`.

**Cambios en `incunest_afe4490.cpp`:**
- `_update_hr1()`: `float s = (float)led1_aled1` → `float ir = (float)led1_aled1` (y usos de `s` → `ir`)
- `_update_hr2_sample()`: añadido `float ir = (float)led1_aled1;`, sustituido inline cast
- `_update_hr3_sample()`: añadido `float ir = (float)led1_aled1;`, sustituido inline cast

**Diseño detallado HGAC (propuesta, no implementado):**

Arquitectura:
- Inline en `_process_sample()` (Task A). No es FreeRTOS task separada.
- Acumula ventana de 500 ms (250 muestras @ 500 Hz), evalúa al final, una acción por ventana.
- Depende de RSQM (prerrequisito).

Estructuras:
- `HGACWindowStats`: amb_led1/led2_pct, sig_led1/led2_pct, pi_led1, diag_accum, n_samples, n_invalid.
- Nuevos campos en `AFE4490Config`: hgac_enabled (default false) + 12 parámetros hgac_*.
- Nuevo campo en `AFE4490Data`: hgac_diag (HGAC_CANNOT_COMPENSATE | HGAC_SIGNAL_DEAD).
- Estimador mediana: algoritmo P² (5 marcadores, O(1)/muestra, ~160 bytes RAM total).

Prioridades de actuación:
- P1 AMB_SAT (>70%): AMBDAC++ → RF-- → HGAC_CANNOT_COMPENSATE
- P2 SIG_SAT (>85%): LED proporcional↓ (max ÷2/paso) → RF--
- P3 AMB_RECOVERY (<10%, persistencia 2s): AMBDAC--
- P4 SIG_WEAK (<20%): LED proporcional↑ (max ×2/paso) → RF++ → STG2++ → HGAC_SIGNAL_DEAD
- Guardianes: no actuar si artefacto (n_invalid > 50%), NO_TISSUE, CABLE_DISCONNECTED.
- Settling: AMBDAC/LED = 50 ms, RF/STG2 = 150 ms; durante settling → RSQM_HW_SETTLING activo.

Decisiones pendientes de confirmar:
- hgac_diag en AFE4490Data o getter separado.
- P² vs buffer+sort para mediana.
- Actuar sobre canal más problemático o ambos simultáneamente en P4.
- Helper _rf_step_up/down(channel) para operar sobre enum AFE4490TIAGain.

**Nueva tarea pendiente:** investigar leakage de LED2 en ALED2:
- ALED2 varía con ALED2STC y con LED2(mA) → hipótesis: cola de extinción del LED contamina
  la ventana de ambient si el dead-time t4(LED2LEDENDC)→t5(ALED2STC) es insuficiente.
- Implicación HGAC: amb_led2_pct podría estar contaminada → actuaciones P1/P3 incorrectas.
- Investigar: fall time típico LED IR, constraints de timing datasheet Table 2, gap mínimo t4→t5.

**Ficheros de memoria actualizados:**
- MEMORY.md, project_naming_convention_task.md (status:done), project_agc_design.md (HGACInput renombrado), project_led_leakage_task.md (nueva).

## Sesión 2026-05-26a

### Tema: Diseño ventana AFE Characterization Test

**Contexto:** Alex quiere una nueva ventana de test en pulsenest_lab.py que barre combinaciones de parámetros HW (LED_mA, RF, RG, AMBDAC) y guarda estadísticas de las señales en CSV para análisis offline en distintas condiciones (sonda desconectada, luz ambiental alta, etc.).

**Diseño acordado (pendiente implementación):**
- Sweep: 3 valores (min/mid/max) × 4 parámetros = 81 combinaciones por canal (LED1 y LED2)
- Estadísticas por señal (LED1, LED2, ALED1, ALED2): Mean, Min, Max, PP (Max-Min), StdDev
- CF se registra automáticamente (calculado por librería a partir de RF)
- Settle time configurable (default 200 ms) antes de cada medida
- N_samples: número real de muestras capturadas en el intervalo
- Condition/description: dropdown con presets + texto libre (primera columna del CSV)
- Progreso + ETA + botón Abort (81 × ~1.2 s ≈ ~2-3 min por canal)
- Columnas CSV (~33): description, timestamp, channel_tested, led_mA, rf_enum, rf_ohm, rg_enum, ambdac, cf_pF, fixed_other_channel_params, settle_ms, interval_ms, n_samples, + 5 stats × 4 señales

**Preguntas abiertas antes de implementar:**
1. Valores min/mid/max concretos para cada parámetro (LED_mA, RF, RG, AMBDAC)
2. ¿Sweep automático o manual combinación a combinación?
3. ¿Un CSV por sesión de test o uno por condición?

---

## Sesión 2026-05-26a

### Tema: Implementación AFECharTestWindow + multi-WiFi firmware

**Cambios en pulsenest_lab.py:**

- **AFECharTestWindow** (nueva clase, ~250 líneas):
  - Sweep paramétrico: 3 niveles (min/mid/max) × 4 parámetros (LED_mA, RF, RG, AMBDAC) × 2 canales (LED1, LED2) = 162 combos
  - 7 grupos de spins: led1, led2, rf1, rf2, rg1, rg2, ambdac (3 spins cada uno = 21 spins totales)
  - RF/RG: índices enteros (RF: 0-6 → TIA_GAINS, RG: 0-4 → STG2_GAINS); leyenda visible en ventana
  - Valores por defecto: LED mA=[5,20,50], RF=[2,4,6], RG=[0,2,4], AMBDAC=[0,3,6]
  - Settling time: configurable (100–30000 ms, default 1000 ms)
  - Samples/combo: configurable (10–10000, default 500)
  - CSV: append mode si ya existe, header solo en fichero nuevo; 39 columnas (9 meta + 5 stats × 6 señales)
  - Estado: IDLE → SETTLING → MEASURING → (siguiente combo o fin)
  - `feed_sample(red, ir, red_amb, ir_amb, red_sub, ir_sub)` llamado desde PPGMonitor por cada frame M1
  - `_send_set` solo envía si serial abierto (sin UDP — los $SET van por serial)
  - Deduplicación de valores con `sorted(set(...))` en `_build_combos` via itertools.product
  - Settings persistidos en INI: geometry, settle_ms, n_samples, csv_path, todos los spins
  - Botón sidebar: **AFE CHAR** (checkable), tooltip descriptivo

- **PPGMonitor** — hooks añadidos:
  - `self.afe_char_window = None` en __init__
  - `btn_afe_char` en sidebar (después de DIAGNOSTICS, antes de addStretch)
  - `toggle_afe_char()` + `_open_afe_char_default()` métodos
  - `feed_sample` call en `_process_frames_tick` (tras hr3test_calc.update)
  - Save/restore settings: `PPGMonitor/afe_char_open`, `AFECharTestWindow/geometry`
  - `_bring_all_to_front`: afe_char_window añadido
  - `closeEvent`: afe_char_window cerrada y limpiada

**Decisiones de diseño:**
- Sweep completamente automático (no manual combo a combo)
- Un solo CSV, append mode (no uno por condición)
- Sin columna "condition/description" (simplificado respecto al diseño previo)
- Valores fijos del otro canal durante el sweep = los que tenga el HW Config en ese momento (no se tocan)
- RF/RG como índices enteros (no strings) con leyenda en ventana
- 39 columnas CSV (no 33 ni 38 del diseño previo)

---

## Sesión 2026-05-26b

### Tema: AFECharTestWindow — columna FIX + tamaños de fuente

**Cambios en pulsenest_lab.py (AFECharTestWindow):**

- **Columna FIX añadida**: cada fila de parámetro pasa de 3 spins (min/mid/max) a 4 spins (FIX, VAR min, VAR mid, VAR max).
  - FIX = valor que se aplica a ese parámetro cuando se está barriendo el OTRO canal
  - VAR min/mid/max = los tres valores que se barren cuando ESTE canal es el activo
  - AMBDAC FIX deshabilitado (AMBDAC siempre se barre en ambos canales)
  - Cabeceras de columna: "", "FIX", "VAR min", "VAR mid", "VAR max"

- **`_PARAMS`**: defaults ampliados a 4 valores [fix_def, var_min_def, var_mid_def, var_max_def]:
  - LED mA: [20, 5, 20, 50]; RF: [4, 2, 4, 6]; RG: [2, 0, 2, 4]; AMBDAC: [3, 0, 3, 6]

- **`_build_combos`**: usa `spins[1:]` (VAR) — el FIX (índice 0) se excluye del producto cartesiano

- **`_apply_combo`**: ahora envía también los $SET del canal no barrido usando sus FIX spins:
  - LED1 sweep → envía led1/tiagain1/stg21 (VAR) + led2/tiagain2/stg22 (FIX)
  - LED2 sweep → envía led2/tiagain2/stg22 (VAR) + led1/tiagain1/stg21 (FIX)

- **Fuentes aumentadas**: ventana 14→18px, GroupBox 13→16px, leyenda índices 12→15px; spin width 68→82px; resize default 560→700px

---

## Sesión 2026-05-26c

### Tema: AFECharTestWindow — eliminar spin FIX desactivado de AMBDAC

**Pregunta:** ¿Por qué hay un control desactivado en la fila AMBDAC, columna FIX?

**Diagnóstico:** Se añadió para mantener uniformidad visual de la cuadrícula, pero un control desactivado implica "podría activarse", lo cual es confuso y no aporta nada.

**Solución:** Celda FIX de AMBDAC simplemente vacía (sin widget). AMBDAC pasa a tener 3 spins (VAR min/mid/max) en lugar de 4. Ajustes derivados:
- `_build_combos`: `amb_vals` usa `spins[:]` (todos, ya que no hay FIX)
- `_SS_SPIN_DIS` eliminada (sin uso)
- `_restore_settings` / `closeEvent` sin cambio (iteran `enumerate(spins)`, funciona con 3 o 4)

---

## Sesión 2026-05-26d

### Tema: AFECharTestWindow — fuente sigue siendo pequeña

**Diagnóstico:** Qt no hereda `font-size` del stylesheet del padre cuando el widget hijo tiene su propio `setStyleSheet` (incluso si sólo define colores). El `font-size: 18px` en el stylesheet del QMainWindow no cascadeaba a los QSpinBox, QLabel, QGroupBox con stylesheets propios.

**Solución:** `setFont()` en la ventana con `pixelSize=20` — este método sí propaga la fuente a todos los hijos independientemente de sus stylesheets. Eliminado `font-size` de todos los stylesheets individuales (GroupBoxes × 4, labels de leyenda) para que hereden del `setFont`.

---

## Sesión 2026-05-26e

### Tema: AFECharTestWindow — fuente sigue pequeña + ventana ancha por Index Reference

**Diagnóstico fuente:** `setFont()` y `setStyleSheet()` interfieren: cuando un widget hijo tiene su propio `setStyleSheet` (aunque sea solo colores), Qt no hereda el font del padre por ninguna vía. La única solución fiable es incluir `font-size` explícitamente en CADA widget que tenga `setStyleSheet` propio.

**Solución fuente:** Eliminar `setFont()` de `__init__`. Usar `font-size: 24px` en el stylesheet del QMainWindow y también en cada widget con stylesheet propio (`_SS`, `_spin_settle`, `_spin_samples`, `_edit_csv`, `btn_browse`).

**Solución anchura:** Eliminado el GroupBox "Index Reference". En su lugar, clase `_IndexSpin(QSpinBox)` que muestra `"idx  label"` (e.g. `"4  100K"` para RF, `"2  6dB"` para RG). `lineEdit().setReadOnly(True)` — solo flechas/scroll, sin edición manual. Anchos de spin: RF=115px, RG=110px, resto=85px.

---

## Sesión 2026-05-26f

### Tema: AFECharTestWindow — dropdown para RF/RG/AMBDAC + formato con índice entre paréntesis

**Cambios:**

- `_IndexSpin` eliminado; reemplazado por `_ComboSpin(QComboBox)` con API `.value()`/`.setValue()` idéntica a QSpinBox — el resto del código no cambia.
- RF1/RF2 → `_ComboSpin` con ítems `"10K (0)"`, `"25K (1)"`, …, `"1M (6)"` (magnitud física primero, índice de registro entre paréntesis). Ancho 160px.
- RG1/RG2 → `_ComboSpin` con ítems `"0dB (0)"`, `"3.5dB (1)"`, …, `"12dB (4)"`. Ancho 145px.
- AMBDAC → `_ComboSpin` con ítems `"0 µA"`, `"1 µA"`, …, `"10 µA"` (valor = índice de registro, sin redundancia). Ancho 130px.
- LED1/LED2 → siguen siendo `QSpinBox` (rango 0-150 no tiene sentido en dropdown).
- Stylesheet `_SS_COMBO` incluye `QComboBox QAbstractItemView` para el popup.

---

## Sesión 2026-05-26g

### Tema: AFECharTestWindow — eliminar índice de registro del combo RF/RG

**Observación:** El índice mostrado entre paréntesis (0-6 para RF, 0-4 para RG) no corresponde al valor real que escribe el AFE4490 en su registro (el firmware hace el mapeo internamente). Además es innecesario: el script envía `$SET,tiagain1,idx` con el índice 0-6 que el firmware mapea; el usuario solo necesita ver la magnitud física.

**Cambio:** `_RF_ITEMS = list(self.TIA_GAINS)` → ["10K","25K","50K","100K","250K","500K","1M"]. `_RG_ITEMS = list(self.STG2_GAINS)` → ["0dB","3.5dB","6dB","9.5dB","12dB"]. El `currentIndex()` interno sigue siendo 0-6/0-4 (lo que se envía por $SET).

---

## Sesión 2026-05-26h

### Tema: AFECharTestWindow — bug en _apply_combo: enviaba índice en lugar de string físico

**Diagnóstico:** El firmware (`parse_tia_gain`, `parse_stage2` en main.cpp) espera strings físicos como `"100K"`, `"6dB"`, etc. — no índices numéricos 0-6. `HWConfigWindow` usa `currentText()` para construir el $SET. `AFECharTestWindow._apply_combo` enviaba `str(currentIndex())` (e.g. `"3"`) → el firmware respondía `$ERR,tiagain1,invalid`.

**Fix en `_apply_combo`:**
- `tiagain1/2`: ahora envía `TIA_GAINS[rf]` (e.g. `"100K"`)
- `stg21/22`: ahora envía `STG2_GAINS[rg]` (e.g. `"6dB"`)
- FIX values: `rf_str(fix_rf("rf2"))` → `TIA_GAINS[param_spins["rf2"][0].currentIndex()]`
- `ambdac`: sigue enviando entero (correcto — firmware espera int 0-10)

---

## Sesión 2026-05-26v

### Tema: SIGNAL STATS — columna RMS → StdDev

- Header: `"RMS"` → `"StdDev"`.
- `_update_stats_table`: `rms = sqrt(Σv²/n)` → `std = sqrt(Σ(v−mean)²/n)`.

---

## Sesión 2026-05-26u

### Tema: Fix SIGNAL STATS vacía tras introducción de RMS

**Causa:** `math` no estaba en los imports globales. `_update_stats_table` usaba `math.sqrt()` → excepción silenciosa en el timer → tabla vacía.

**Fix:** `import math` añadido a los imports de nivel superior (junto a `sys`, `os`).

---

## Sesión 2026-05-26t

### Tema: SIGNAL STATS — intercambio columnas Mean y RMS

- Header: `Signal | RMS | Mean | …` → `Signal | Mean | RMS | …`
- `_update_stats_table`: `vals = [_fmt(rms), _fmt(mean), …]` → `[_fmt(mean), _fmt(rms), …]`
- `_STATS_MEAN_COL`: 2 → 1 (coloreado SQI de HR sigue apuntando a la columna Mean)

---

## Sesión 2026-05-26s

### Tema: SIGNAL STATS — columna "Last" → "RMS"

**Cambios en `pulsenest_lab.py` (`PPGMonitor`):**
- `stats_table` header: `"Last"` → `"RMS"`.
- `_update_stats_table`: sustituido `last = buf[-1]` por `rms = math.sqrt(sum(v*v for v in buf) / n)`. La columna RMS muestra el valor RMS del intervalo de stats (mismo período que Mean/Min/Max).

---

## Sesión 2026-05-26r

### Tema: AFECharTestWindow — AMBDAC cambia más lento en el sweep

`_build_combos`: `itertools.product(led_vals, rf_vals, rg_vals, amb_vals)` → `itertools.product(amb_vals, led_vals, rf_vals, rg_vals)`. Orden de ciclos: AMBDAC (más lento) → LED → RF → RG (más rápido).

---

## Sesión 2026-05-26q

### Tema: AFECharTestWindow — columnas CSV agrupadas por tipo de estadístico

**Cambios en `pulsenest_lab.py` (`AFECharTestWindow`):**

`_CSV_HEADER`: estadísticos reorganizados de "por canal" a "por tipo":
- Antes: `LED2_mean/min/max/pp/std`, `LED1_mean/min/max/pp/std`, …
- Después: `LED2_mean, LED1_mean, ALED2_mean, ALED1_mean, LED2_Sub_mean, LED1_Sub_mean`, luego misma secuencia para min, max, pp, std.

`_write_row`: reescrito para pre-computar `stats[sig]` por señal y luego emitir `stats[sig][stat_idx]` iterando primero por tipo de estadístico (5) y luego por señal (6). El orden de `_SIGNALS` = `[RED, IR, RED_Amb, IR_Amb, RED_Sub, IR_Sub]` = `[LED2, LED1, ALED2, ALED1, LED2_Sub, LED1_Sub]` coincide con el header.

---

## Sesión 2026-05-26p

### Tema: AFECharTestWindow — renombrado columnas CSV

`_CSV_HEADER`: `led1_mA`→`LED1mA`, `led2_mA`→`LED2mA`, `rf1_str`→`RF1`, `rf2_str`→`RF2`, `rg1_str`→`RG1`, `rg2_str`→`RG2`.

---

## Sesión 2026-05-26o

### Tema: AFECharTestWindow — reestructuración columnas CSV

**Cambios en `pulsenest_lab.py` (`AFECharTestWindow`):**

`_CSV_HEADER` (40 columnas, sin cambio de número):
- Eliminadas: `channel`, `rf_idx`, `rg_idx`
- `led_mA` → `led1_mA` + `led2_mA`
- `rf_str` → `rf1_str` + `rf2_str`
- `rg_str` → `rg1_str` + `rg2_str`
- Señales renombradas según nomenclatura AFE4490: `RED_*`→`LED2_*`, `IR_*`→`LED1_*`, `RED_Amb_*`→`ALED2_*`, `IR_Amb_*`→`ALED1_*`, `RED_Sub_*`→`LED2_Sub_*`, `IR_Sub_*`→`LED1_Sub_*`

`_write_row`:
- Reconstruye `led1/led2/rf1/rf2/rg1/rg2` desde el combo + FIX spins del canal no barrido.
- Fila construida con los valores separados por canal (sin `ch`, sin índices de registro).
- Buffers internos (`_buf["RED"]`, etc.) sin cambio — son claves internas, no afectan al CSV.

**Correspondencia confirmada** (del conversation_log sesión 2026-03-xx): LED1=IR, LED2=RED, ALED1=IR_Amb, ALED2=RED_Amb.

---

## Sesión 2026-05-26n

### Tema: AFECharTestWindow — campo Test label + columna label en CSV

**Cambios en `pulsenest_lab.py` (`AFECharTestWindow`):**
- `_CSV_HEADER`: añadida `"label"` como primera columna (39 → 40 columnas).
- UI: nuevo `QLineEdit _edit_label` en Sweep Settings (primera fila), con placeholder `"e.g. probe disconnected, finger on sensor…"` y tooltip descriptivo.
- `_write_row`: `label = self._edit_label.text().strip()` añadido al inicio de cada fila CSV.
- `_restore_settings` / `closeEvent`: persistencia de `AFECharTestWindow/label` en INI.

---

## Sesión 2026-05-26m

### Tema: AFECharTestWindow — correcciones menores

- `_PARAMS`: labels `"LED1 mA"` → `"LED1 mA (approx)"` y `"LED2 mA"` → `"LED2 mA (approx)"` — la corriente LED es aproximada (depende de TX_REF y LEDRANGE).
- INI: eliminada clave huérfana `ambdac_3` (residuo de cuando AMBDAC tenía spin FIX, eliminado en sesión 2026-05-26c). Inofensiva pero confusa.

---

## Sesión 2026-05-26l

### Tema: AFECharTestWindow — highlight ámbar del spin activo durante el sweep

**Cambios en `pulsenest_lab.py` (`AFECharTestWindow`):**

- Añadidas 4 constantes de clase: `_SS_SPIN`, `_SS_COMBO` (estilos normales, movidos desde `_setup_ui`), `_SS_SPIN_ACTIVE`, `_SS_COMBO_ACTIVE` (fondo `#2A2000`, texto `#FFD060`, borde `#FFB300`).
- `_setup_ui`: sustituidas las variables locales `_SS_SPIN`/`_SS_COMBO` por referencias a `self._SS_SPIN`/`self._SS_COMBO`.
- Nuevo método `_set_spin_style(spin, active)`: aplica estilo normal o ámbar según el tipo del widget (`_ComboSpin` o `QSpinBox`).
- Nuevo método `_clear_highlights()`: resetea todos los spins a estilo normal.
- Nuevo método `_highlight_active(idx)`: para el combo `idx`, llama `_clear_highlights()` y luego ilumina en ámbar:
  - Canal barrido (LED1 o LED2): el spin VAR (min/mid/max) cuyo valor coincide con el combo
  - Canal fijo (el otro): el spin FIX (índice 0)
  - AMBDAC: el spin cuyo valor coincide con el `amb` del combo
- `_apply_combo`: llama `_highlight_active(idx)` al final (tras enviar todos los $SET).
- `_stop_sweep`: llama `_clear_highlights()` al terminar o abortar el sweep.

---

## Sesión 2026-05-26k

### Tema: HWConfigWindow — actualización en tiempo real desde cualquier $CFG

**Motivación:** durante el AFE CHAR TEST, cada combo envía varios `$SET` y el firmware responde siempre con un `$CFG` completo (línea 548 de main.cpp). HWConfigWindow solo se actualizaba cuando el `$SET` lo enviaba ella misma (flag `_cfg_notify_hw_config`).

**Fix en `pulsenest_lab.py`:**
- Eliminado el flag `_cfg_notify_hw_config` por completo.
- `_on_cfg_frame_received`: `hw_config_window.update_from_cfg(kv)` se llama siempre que la ventana esté abierta, sin condición.
- `request_chip_config`: eliminado parámetro `notify_hw_config`; docstring actualizado.
- `HWConfigWindow._send_set`: eliminada línea `mm._cfg_notify_hw_config = True`.
- `HWConfigWindow._on_read_cfg`: eliminado `notify_hw_config=True` de la llamada.
- `_cfg_notify_lab_capture` sin cambios — LabCapture sigue protegido de $CFGs del sweep.

**Resultado:** HWConfigWindow se refresca en tiempo real durante el sweep (un $CFG por combo) y también con cualquier otro origen de $CFG.

---

## Sesión 2026-05-26j

### Tema: AFECharTestWindow — corrección defaults settling time y samples/combo

**Diagnóstico:**
- `feed_sample` se llama desde el parser M1 post-decimación (50 Hz). Con default 500 muestras → 10 segundos por combo, no 1 segundo como decía el tooltip.
- Settling time 1000 ms: valor arbitrario sin base técnica. TIA worst-case settling (RF=1M, CF=155p): 5τ ≈ 775 µs. Con margen para procesado $SET en firmware: 200 ms es suficiente.

**Cambios en `pulsenest_lab.py` (`AFECharTestWindow`):**
- `_spin_settle` default: 1000 ms → **200 ms**
- `_spin_samples` default: 500 → **50** (= 1 s a 50 Hz)
- Tooltips actualizados: settle explica el 5τ; samples explica los 50 Hz de decimación
- `_restore_settings`: defaults INI actualizados en consonancia (1000→200, 500→50)
- INI actualizado directamente para que surta efecto sin reiniciar desde cero

---

## Sesión 2026-05-27j

### Tema: SIGNAL STATS — reducir font del header "% SD/Mean"

- El stylesheet `font-size: 33px` en `QHeaderView::section` sobreescribía el font asignado vía `setFont()` en el item.
- Fix: eliminado `font-size` del stylesheet; fonts asignados programáticamente tras `setHorizontalHeaderLabels`: 9px para col 1 ("% SD/Mean"), 33px para el resto.

---

## Sesión 2026-05-27i

### Tema: SIGNAL STATS — columnas V_TIA y V_ADC

**Contexto (datasheet AFE4490):**
- ADC 22 bits, full-scale: **±1.2 V** (§7.5)
- Equation 2 (p.30): `V_DIFF = 2 × (I_PD × RF/RI − I_CANCEL) × RG`
  - RI = 100 kΩ (fijo interno)
  - RG en Ω según Table 1 (p.31): 0dB→100K, 3.5dB→150K, 6dB→200K, 9.5dB→300K, 12dB→400K
  - I_CANCEL = AMBDAC en A (leído de $CFG campo "ambdac" en µA)

**Fórmulas implementadas:**
- `V_ADC = count / 2^21 × 1.2`  (voltaje V_DIFF a la entrada del ADC)
- `V_TIA = (V_ADC / (2 × RG) + I_CANCEL) × RI`  (voltaje real a la salida de la TIA = I_PD × RF)
- IR/IR_Amb → stg21; RED/RED_Amb → stg22 (del último $CFG)
- Valores en **V con 2 decimales**

**Cambios en `pulsenest_lab.py`:**
- Tabla ampliada de 7 a 9 columnas; añadidas "V_TIA" y "V_ADC".
- Solo filas 0–3 (IR, RED, IR_Amb, RED_Amb). Resto: vacío.
- `self._last_cfg` almacena el último $CFG recibido.
- Constantes: `_STATS_RAW_ROWS`, `_ADC_FSR`, `_ADC_FS_COUNTS`, `_STG2_RG_OHM`, `_STG2_RI_OHM`.
- Error anterior corregido: se usaba RF×RG_lineal en vez de la Equation 2 del datasheet.

---

## Sesión 2026-05-27h

### Tema: PPGPLOTS y SIGNALS — sidebar IR antes que RED

**Cambios en `pulsenest_lab.py`:**
- `PPGPlotsWindow._setup_ui`: sidebar reordenado — IR (con sus 3 checkboxes) aparece primero, RED después.
- `PPGSignalsWindow._setup_ui`: ídem.
- Consistente con el reordenamiento de plots (sesión 2026-05-27g) y de la tabla SIGNAL STATS (sesión 2026-05-27f).

---

## Sesión 2026-05-27g

### Tema: PPGPLOTS y SIGNALS — IR antes que RED en los plots

**Cambios en `pulsenest_lab.py`:**
- `PPGPlotsWindow._setup_ui`: p1 pasa a ser IR (era RED), p2 pasa a ser RED (era IR).
- `PPGSignalsWindow._setup_ui`: ídem.
- Las curvas (`self.curve_red`, `self.curve_ir`, etc.) conservan sus nombres — solo cambia en qué panel están añadidas.
- Los checkboxes del sidebar no se modificaron (el usuario solo pidió reordenar los plots).

---

## Sesión 2026-05-27f

### Tema: SIGNAL STATS — reordenar filas para que IR preceda a RED

**Cambio en `pulsenest_lab.py` (`_STATS_SIGNALS`):**
- Intercambiadas las filas por pares: IR antes que RED, IR_Amb antes que RED_Amb, IR_Sub antes que RED_Sub.
- Nuevo orden filas 0–5: IR, RED, IR_Amb, RED_Amb, IR_Sub, RED_Sub.
- `_STATS_SUB_ROWS = {4, 5}` y `_STATS_HR_ROWS = {11, 13, 15}` siguen siendo correctos sin cambios.

---

## Sesión 2026-05-27e

### Tema: Renombrar AFE CHAR → AFE SWEEP

**Cambios en `pulsenest_lab.py`:**
- Clase `AFECharTestWindow` → `AFESweepTestWindow`
- Botón `"AFE CHAR"` → `"AFE SWEEP"`
- Título de ventana `"AFE CHAR TEST"` → `"AFE SWEEP TEST"`
- CSV por defecto `afe_char_test.csv` → `afe_sweep_test.csv`
- Atributos: `afe_char_window` → `afe_sweep_window`, `btn_afe_char` → `btn_afe_sweep`
- Métodos: `toggle_afe_char` → `toggle_afe_sweep`, `_open_afe_char_default` → `_open_afe_sweep_default`
- Claves INI: `AFECharTestWindow/...` → `AFESweepTestWindow/...`, `PPGMonitor/afe_char_open` → `PPGMonitor/afe_sweep_open`

---

## Sesión 2026-05-27d

### Tema: SIGNAL STATS — ajuste visual columna "% SD/Mean"

**Cambios en `pulsenest_lab.py`:**
- Header de la columna "% SD/Mean" con fuente reducida a 20px (el resto usa 33px) para que el texto entre.
- Valores de la columna "% SD/Mean" formateados siempre con 2 decimales (`f"{v:.2f}"`), independientemente del tipo de señal (rows < 6 usaban formato entero con `_fmt`).

---

## Sesión 2026-05-27c

### Tema: SIGNAL STATS — renombrar columnas y corregir cálculo CV

**Cambios en `pulsenest_lab.py`:**
- Columna "Mean/StdDev" renombrada a "% SD/Mean".
- Columna "StdDev" renombrada a "SD".
- Valor de la columna "% SD/Mean" corregido a `SD / Mean × 100` (coeficiente de variación en %). Solo se calcula para filas RED_Sub e IR_Sub.

---

## Sesión 2026-05-27b

### Tema: SIGNAL STATS — nueva columna Mean/StdDev para RED_Sub e IR_Sub

**Cambios en `pulsenest_lab.py` (`PPGMonitor`):**
- Tabla ampliada de 6 a 7 columnas.
- Nueva columna "Mean/StdDev" insertada en col 1 (entre "Signal" y "Mean").
- El cociente Mean/StdDev solo se calcula y muestra para las filas RED_Sub (fila 4) e IR_Sub (fila 5); el resto de filas queda en blanco.
- `_STATS_MEAN_COL` actualizado de 1 a 2 (la columna Mean se desplazó una posición).
- Nueva constante de clase `_STATS_SUB_ROWS = {4, 5}`.
- `_update_stats_table`: vals mapeados a cols 2–6; col 1 actualizada con el cociente o vacío.
- Bucles de inicialización y resize mode extendidos de `range(1,6)` a `range(1,7)`.

**Decisión de diseño:** Mean/StdDev es un indicador de SNR estático (relación señal/ruido de la componente DC del canal diferencial). Solo tiene sentido en RED_Sub e IR_Sub (señales diferenciadas del ambiente); para señales crudas o procesadas el ratio no tiene la misma interpretación fisiológica.

---

## Sesión 2026-05-27a

### Tema: Lección aprendida — CF no se descarga antes de la ventana ALED con sonda desconectada

**Observación experimental:** Con la sonda no aplicada, los LEDs cargan el condensador de realimentación de la TIA (CF) hasta niveles muy altos (sin fotodiodo que limite la corriente). CF no tiene tiempo suficiente para descargarse completamente antes de que comience la etapa de muestreo ALED (ambiente). Resultado: ALED1 y ALED2 quedan artificialmente elevados y no representan el ambiente óptico real.

**Distinción respecto al leakage óptico:**
- Leakage óptico: el LED sigue emitiendo luz durante la ventana ALED (cola de extinción del LED).
- CF no descargado: el LED ya ha dejado de emitir, pero la carga eléctrica residual en CF persiste y contamina la medida ALED.
Ambos mecanismos pueden coexistir; el de CF es dominante cuando la sonda no está aplicada.

**Implicación:** los valores de ALED con sonda no aplicada no son representativos del ambiente óptico real y no deben usarse para calibración ni como referencia.

**Documentado en:** `memory/project_led_leakage_task.md` (sección "Lección aprendida — 2026-05-27").

---

## Sesión 2026-05-27n

### Tema: SIGNAL STATS — colores de fondo V_TIA / V_ADC por voltaje (umbrales en V)

**Cambios en `pulsenest_lab.py`:**

Nuevas constantes de clase: `_VTG_GREEN/YELLOW/RED/DEFAULT` — colores de fondo oscuros para celdas cols 7-8.

Nuevos métodos:
- `_vtg_tia_color(row, v_tia)`: color para columna V_TIA según `abs(v_tia)` y tipo de fila
- `_vtg_adc_color(row, v_adc)`: color para columna V_ADC según `abs(v_adc)` y tipo de fila

Umbrales (filas LED = rows 0,1 = IR/RED; filas ALED = rows 2,3 = IR_Amb/RED_Amb):

| Col | Fila | Verde | Amarillo | Rojo |
|---|---|---|---|---|
| V_TIA | LED | 0.40–0.80 V | 0.15–0.40 o 0.80–0.95 V | <0.15 o >0.95 V |
| V_TIA | ALED | <0.30 V | 0.30–0.70 V | >0.70 V |
| V_ADC | LED | 0.45–0.95 V | 0.20–0.45 o 0.95–1.10 V | <0.20 o >1.10 V |
| V_ADC | ALED | <0.35 V | 0.35–0.80 V | >0.80 V |

`_update_stats_table`: calcula `vtia_bg`/`vadc_bg` por separado y aplica `setBackground` a cada celda. Sin datos → `_VTG_DEFAULT` (#121212).

---

## Sesión 2026-05-27m

### Tema: Revert — colores V_TIA/V_ADC (sesión 2026-05-27l deshecha)

Los cambios de la sesión 2026-05-27l fueron revertidos a petición del usuario. El código queda exactamente como estaba antes de esa sesión.

---

## Sesión 2026-05-27l

### Tema: SIGNAL STATS — colores de fondo V_TIA / V_ADC según rango de operación AFE4490

**Cambios en `pulsenest_lab.py`:**

Nuevas constantes de clase en `PPGMonitor`:
- `_VTG_GREEN/YELLOW/RED/DEFAULT` — colores de fondo para celdas V_TIA/V_ADC
- `_VTG_LED_RED_HI/YEL_HI/GRN_HI/YEL_LO` — umbrales LED_VAL (filas IR/RED, rows 0-1) en counts
- `_VTG_ALED_RED/YELLOW` — umbrales ALED_VAL (filas IR_Amb/RED_Amb, rows 2-3) en counts

Nuevo método `_vtg_bg(row, abs_counts)`:
- Filas 0,1 (LED_VAL): 5 zonas — RED (>1 922 000), YELLOW (>1 660 000), GREEN (≥840 000), YELLOW (≥315 000), RED (<315 000)
- Filas 2,3 (ALED_VAL): 3 zonas — RED (>1 223 000), YELLOW (≥524 000), GREEN (<524 000)

`_update_stats_table`: calcula `vtg_bg = _vtg_bg(row, abs(mean))` si hay datos, `_VTG_DEFAULT` si no; aplica `it.setBackground(vtg_bg)` a ambas celdas cols 7-8 (V_TIA, V_ADC).

Umbrales basados en especificación proporcionada (ADC FS = ±1.2V, TIA FS = ±1.0V, ADC counts FS = 2 097 151).

---

## Sesión 2026-05-27k

### Tema: AFE SWEEP — "None" primero en todos los spins + contador de combos en tiempo real

**Cambios en `pulsenest_lab.py`:**

- `_ComboSpin.value()` → devuelve `currentIndex() - 1` (None=-1, items reales empiezan en 0). `setValue(v)` → `setCurrentIndex(v+1)`. Preserva la semántica externa de índices sin tocar ningún otro código.
- Listas de items: "None" movida al primer lugar en todos los params (`_RF_ITEMS`, `_RG_ITEMS`, `_AMB_ITEMS`, `_LED_ITEMS`).
- `_build_combos`: filtro cambiado de `currentText() != "None"` a `s.value() >= 0`.
- `_apply_combo`: checks FIX también usan `spin.value() >= 0`.
- `_write_row._fix_text`: usa `spin.value() < 0` para detectar None.
- Nuevo método `_update_combo_count()`: calcula `len(_build_combos())`, actualiza `_progress` (max y formato) y `_lbl_status` con el número de combos. Si n=0 muestra "No combos — all VAR spins set to None".
- Cada spin conectado a `_update_combo_count` via `currentIndexChanged`.
- `_restore_settings` llama `_update_combo_count()` al final.
- Progress bar: `setRange(0,1)` inicial (actualizado dinámicamente).

---

## Sesión 2026-05-27i

### Tema: AFE SWEEP — análisis afe_sweep_test.csv para detección de estado de sonda (HGAC)

**Análisis del CSV (486 filas × 3 estados):**
Se analizó la capacidad de distinguir PROBE_DISCONNECTED / PROBE_NOT_APPLIED / PROBE_APPLIED sin usar el test de diagnóstico hardware del AFE4490.

**Conclusiones:**

- **DISCONNECTED:** 100% distinguible. Todos los canales raw (LED2, LED1, ALED2, ALED1) son negativos + Sub_std < 500 + ratio LED/ALED ≈ 1.0 (artefacto CF simétrico, diff < 5%). Ningún otro estado produce este patrón.
- **NOT_APPLIED:** algún canal raw > +10%FS (positivo). Cuando Sub_std > 1000 en NOT_APPLIED es siempre artefacto CF (LED saturado a +FS pero ALED no), distinguible porque el canal de alta std tiene su LED en saturación.
- **APPLIED:** Sub_std > 1000 en canal cuyo LED NO está saturado (señal PPG real). Con ambdac=0 aplica siempre.
- **Accuracy total del árbol de decisión propuesto: 95.3% (463/486).** Los 23 errores restantes son todos `ambdac=4µA + RF=100K` (offset = 400mV, oversubstracción patológica que HGAC nunca debe alcanzar). En el espacio operativo válido del HGAC, accuracy es 100%.

**Árbol de decisión para HGAC:**
```
IF all(LED2<0, LED1<0, ALED2<0, ALED1<0) AND Sub_std_max<500 AND |LED2/ALED2−1|<5%:
    → PROBE_DISCONNECTED
ELIF Sub_std_max>1000 AND LED_source NOT saturado:
    → PROBE_APPLIED
ELSE:
    → PROBE_NOT_APPLIED
```

---

## Sesión 2026-05-27h

### Tema: AFE SWEEP — LED1/LED2 a _ComboSpin (256 items) + opción "None" en todos los Sweep Parameters

**Cambios en `pulsenest_lab.py` (`AFESweepTestWindow._setup_ui`):**
- LED1/LED2 mA: cambiados de `QSpinBox` a `_ComboSpin` con 257 items (0–255 + "None"), width=90px. Se despliegan al seleccionarlos igual que RF/RG/AMBDAC.
- RF1/RF2, RG1/RG2, AMBDAC: añadido "None" al final de sus listas de items.
- Tooltips actualizados para mencionar que "None" excluye el valor del sweep (VAR) o salta el $SET (FIX).

**Cambios en `_build_combos`:**
- Todos los generadores de vals filtran `s.currentText() != "None"` → las combinaciones con "None" se excluyen del sweep.

**Cambios en `_apply_combo`:**
- Los spins FIX de LED/RF/RG comprueban `currentText() != "None"` antes de enviar `$SET`. Si es "None" se omite el comando (el hardware conserva su valor actual).

**Cambios en `_write_row`:**
- Los valores FIX se obtienen via `spin.currentText()` (`_fix_text` helper) — devuelve la cadena de display correcta ("20", "100K", "6dB") o "None" si aplica. Los valores VAR siguen usando índice + lookup en TIA_GAINS/STG2_GAINS.

---

## Sesión 2026-05-26i

### Tema: $SET intermitente desde HW CONFIG — saturación del serial por $M1 a 500 Hz

**Diagnóstico:** Cuando WiFi/UDP está activo, Python ignora el serial pero el firmware seguía enviando $M1/$M2 a 500 Hz por USB-CDC. El buffer TX del ESP32 se saturaba, y cuando el firmware intentaba enviar la respuesta $CFG al $SET, el write se descartaba.

**Fix en `src/main.cpp`:** `Serial_print_locked(buf)` para $M1 y $M2 condicionado a `!g_wifi_ready`. Cuando WiFi está activo, los frames de datos van solo por UDP; el serial queda libre para tráfico de control bidireccional ($SET/$CFG/$ERR/$DIAG). Los mensajes de diagnóstico periódicos (#STAT, #CHK, etc.) siguen yendo por serial siempre (volumen despreciable).

---

## Sesión 2026-05-27k

### Tema: AFE SWEEP — dropdown LED1/LED2 + opción "None" en todos los spins

**Cambios en AFESweepTestWindow:**
- LED1 y LED2 mA cambiados de QSpinBox a `_ComboSpin` con 256 items (0–255).
- Todos los parámetros de Sweep Parameters tienen ahora la opción "None" como primer item.
- "None" deshabilita ese parámetro de la combinación → menos combos a testear.
- `_ComboSpin.value()` = `currentIndex() - 1` (None=-1, items reales ≥ 0).
- `_build_combos()` filtra `value() >= 0`; `_apply_combo()` salta `send_set` si `value() < 0`.

---

## Sesión 2026-05-27l

### Tema: SIGNAL STATS — columnas V_TIA y V_ADC con color coding

**Contexto datasheet AFE4490:**
- ADC FS = ±1.2 V, 22-bit signed. VCMREF = 0.9 V (fijo interno, no AVDD/2).
- V_ADC = (mean_counts / 2²¹) × 1.2 V
- V_TIA = V_ADC × (RI / (2×RG)) donde RI=100kΩ fijo, RG de $CFG stg21/stg22.

**Color coding (abs value):**

| Filas | Rango V_TIA | Color |
|-------|-------------|-------|
| LED (0,1) | 0.40–0.80 V | Verde |
| LED (0,1) | 0.80–0.95 V o 0.15–0.40 V | Amarillo |
| LED (0,1) | >0.95 V o <0.15 V | Rojo |
| ALED (2,3) | <0.30 V | Verde |
| ALED (2,3) | 0.30–0.70 V | Amarillo |
| ALED (2,3) | >0.70 V | Rojo |

Misma lógica para V_ADC con thresholds diferentes (ver §6.3 del spec).

---

## Sesión 2026-05-27m

### Tema: actualización de pulsenest_lab_spec.md

**Decisión:** el spec estaba desactualizado desde v1.0 (2026-04-14).
**Acción:** spec reescrito a v1.3 documentando todos los cambios realizados desde entonces:
- Transport WiFi/UDP (§4.1, §4.7)
- Protocolo $SET/$CFG/$TCFG/$DIAG/$ERR (§4.3, §4.4)
- SIGNAL STATS 9 columnas, IR-first, V_TIA/V_ADC con colores (§6.3)
- Nuevas ventanas: PPGSignalsWindow, AlgoResultsWindow, UdpComWindow, HWConfigWindow, DiagnosticsWindow, AFESweepTestWindow, PythonTimingWindow (§7.2–7.18)
- _ComboSpin widget (§7.18)
- File outputs + settings persistence actualizados (§8, §9)
- Naming conventions (§11)

**Regla añadida a memoria:** spec debe actualizarse tras cambios importantes en pulsenest_lab.py, sin esperar que el usuario lo pida.

---

## Sesión 2026-05-27q

### Tema: SIGNAL STATS — SpO2_R col "% SD/Mean" muestra R estimado en cursiva

- Celda `SpO2_R` / `% SD/Mean` calcula `CV(RED_Sub) / CV(IR_Sub)` ≈ R.
- Justificación: `CV = SD/Mean ≈ AC/DC` por canal → cociente = `(AC_red/DC_red) / (AC_ir/DC_ir)` = R.
- Mostrado en **cursiva** porque no es un `% SD/Mean` genuino sino un ratio derivado.
- Tooltip específico añadido explicando fórmula y significado de la cursiva.
- Implementación en `_update_stats_table()`: vars `_ir_sub_cv`/`_red_sub_cv`, override `snr_str` + `setItalic(True)` para row 9. Tooltip override en `_setup_ui`.

---

## Sesión 2026-05-27p

### Tema: hr_min_bpm 30 → 40 BPM

**Pregunta:** justificación de rangos de trabajo de LEDmA, RF, AMBDAC, RG. Luego: cambiar hr_min_bpm a 40 BPM.

**Decisiones:**
- `hr_min_bpm` 30 → **40 BPM** (límite inferior válido reportado, ISO 80601-2-61)
- `hr_search_min_bpm` (guard band: hr_min − 3) 27 → **37 BPM**
- Spec bumpeada a **v0.25**

**Ficheros modificados:**
- `incunest_afe4490.cpp`: constexpr `hr_min_bpm` 30.0f → 40.0f
- `incunest_afe4490_spec.md`: v0.24→v0.25, tabla parámetros (×2) y tabla constants (×2), changelog v0.25
- `pulsenest_lab.py`: `HR_MIN_HZ` (HRFFTCalc), `FW_HR_MIN_BPM` (HR1TestCalc, HR2TestCalc, HR3TestCalc), `FW_HR_SEARCH_MIN` (HR2TestCalc, HR3TestCalc), defaults `hr_min=` en `_estimate_hr_xcorr_v1` y `_estimate_hr_autocorr_v2`

---

## Sesión 2026-05-27o

### Tema: SIGNAL STATS — tooltips V_TIA/V_ADC con color coding y "Units: V (volts)"

- Añadidos tooltips específicos para las celdas de las columnas V_TIA (col 7) y V_ADC (col 8) en las filas raw (rows 0-3).
- Los tooltips anteriores heredaban la descripción genérica de la señal (que decía "Units: ADC counts").
- Nuevos tooltips incluyen: fórmula de cálculo, "Units: V (volts)", y leyenda de colores (Green/Yellow/Red con rangos exactos).
- Tooltips diferentes para filas LED (IR, RED) y filas ALED (IR_Amb, RED_Amb) ya que los umbrales difieren.
- Los tooltips se sobreescriben tras el bucle de inicialización en `_setup_ui`.

---

## Sesión 2026-05-27o

### Tema: Análisis afe_sweep_test.csv — discriminación de estados de sonda para HGAC

**Objetivo:** determinar si es posible distinguir PROBE_DISCONNECTED / PROBE_NOT_APPLIED / PROBE_APPLIED mirando las medidas y la configuración del AFE, sin usar el test de diagnóstico hardware (que paraliza la campaña de medidas).

**Fichero analizado:** `afe_sweep_test.csv` — 487 filas, 3 labels: PROBE_APPLIED (163), PROBE_NOT_APPLIED (162), PROBE_DISCONNECTED (162). Sweep sistemático: RF1=(10K/100K/1M), RG1=(0/6/12dB), LED1mA=(5/10/50), ambdac=(0/1/2/4/5/10 µA). RF2=100K, RG2=6dB, LED2mA=20 fijos.

---

**Conclusión 1 — LED_Sub es ambdac-independiente**
LED_Sub = LED − ALED. El AMBDAC inyecta la misma corriente DC en fase LED y fase ALED → se cancela en la resta. LED_Sub es el discriminador más robusto porque no requiere corrección por ambdac.

**Conclusión 2 — PROBE_DISCONNECTED: firma inequívoca**
Sin fotodiodo, LED_Sub ≈ 0 en cualquier configuración. Peores casos observados en el CSV:
- `LED2_Sub_mean`: máx absoluto = 3 328 counts (ambdac=5, RG=12dB, n=1 muestra)
- `LED1_Sub_mean`: máx absoluto = 2 280 counts (ambdac=2, RG=6dB)
- `LED2_Sub_std`: máx = 163 counts
- `LED1_Sub_std`: máx = 213 counts

Cuando LED_mean satura negativamente (SAT−), los Sub_std caen a ~0 (ADC clavado en el rail) — DISCONNECTED sigue siendo detectable.

**Conclusión 3 — NOT_APPLIED vs APPLIED: métrica normalizada**
El ratio `LED1_Sub_mean / (LED1mA × RF1 × RG1_linear)` es una constante física del sistema (respuesta óptica normalizada):
- PROBE_APPLIED: ≈ 0.05 counts/(mA·Ω) — estable en todos los RF/RG/mA probados
- PROBE_NOT_APPLIED: ≈ 2.7 counts/(mA·Ω) — factor ×54 respecto a APPLIED
No requiere cambiar la configuración del AFE; se calcula con los datos del ciclo en curso.

**Conclusión 4 — Brecha de ganancia**
No existe ninguna configuración donde APPLIED y NOT_APPLIED den valores no saturados simultáneamente. Si el HGAC está en su punto de operación para APPLIED, NOT_APPLIED satura inmediatamente (×53 más señal). La detección de NOT_APPLIED se reduce a: señal saturada en el punto de operación actual, o métrica normalizada >> 0.5 en cualquier punto no saturado.

**Punto ciego identificado:** NOT_APPLIED con saturación positiva completa (ambas ventanas LED y ALED en +2096921) da Sub=0, std=0 → falso positivo para DISCONNECTED. Se resuelve añadiendo verificación de que ningún canal esté en saturación positiva.

---

**Criterio acordado para detectar PROBE_DISCONNECTED (sin test HW):**

```cpp
bool is_disconnected =
    abs(LED1_Sub_mean) < 5000   &&
    abs(LED2_Sub_mean) < 5000   &&
    LED1_Sub_std       < 500    &&
    LED2_Sub_std       < 500    &&
    LED1_mean          < 2000000 &&   // excluye saturación positiva canal IR
    LED2_mean          < 2000000;     // excluye saturación positiva canal RED
```

Márgenes: THRESH_SUB=5000 da ×1.5 sobre peor caso LED2_Sub_mean (3328) y ×2.2 sobre LED1_Sub_mean (2280). THRESH_STD=500 da ×2.3 sobre peor caso (213). Umbral SAT=2000000 separa DISCONNECTED (siempre << 2M) de NOT_APPLIED saturado (+2096921).

---

## Sesión 2026-05-27p

### Tema: Cálculo de los 6 valores del criterio PROBE_DISCONNECTED — Opción A vs B

**Pregunta:** ¿calcular LED1/LED2 Sub_mean, Sub_std, mean sobre un buffer de últimas N muestras (Opción A) o progresivamente con EMA/constante de tiempo (Opción B)?

**Decisión: Opción B (EMA).**

**Razones:**
- El HGAC ya calcula `LED_Sub_mean` para su lazo de control → la EMA extiende ese cálculo añadiendo solo el estimador de varianza, sin duplicar trabajo.
- Reset trivial al cambiar RF/RG/ambdac: reinicializar 3 floats vs. vaciar y rellenar un buffer (N muestras de latencia muerta con Opción A).
- Memoria y complejidad mínimas (6 floats por canal vs. buffer circular).
- El criterio no necesita precisión estadística: la distancia DISCONNECTED vs APPLIED es de varios órdenes de magnitud.

**Implementación acordada** (α = 1/τ, τ ≈ 50 muestras a 500 Hz → ventana efectiva ~100 ms):

```cpp
constexpr float ALPHA = 0.02f;

ema_mean += ALPHA * (x - ema_mean);
ema_var  += ALPHA * ((x - ema_mean) * (x - ema_mean) - ema_var);
ema_std   = sqrtf(ema_var);

// Reset obligatorio al cambiar RF/RG/ambdac:
ema_mean = x;  ema_var = 0.0f;
```

**Precaución:** inhibir el criterio de detección durante ~3τ = 150 ms tras cada reset (flag `estimator_ready`) para evitar falsos positivos transitorios.

---

## Sesión 2026-05-28c

### Tema: Máquina de estados ProbeState — decisiones completas + plan de implementación

**ISO 80601-2-61:2026 consultada.** Requisitos relevantes encontrados:
- §201.13.101: detectar probe fault (open/short wire) → technical alarm condition. Sin tiempo límite especificado.
- §201.12.4.102: indicador de signal inadequacy obligatorio. Factores: DC signal level y %mod.
- §201.12.4.101: data update period < 30s para monitorización neonatal continua. Nuestro settling = 1.5s → ✅
- Table GG.3: "probe is not connected" y "probe is not detected" son alarmas técnicas esperadas por la norma.
- Annex FF (informativo): conceptos de fidelidad y delay para SpO2 — no impone tiempos para detección de sonda.

**Nomenclatura actualizada en incunest_afe4490_spec.md:**
- `CABLE_DISCONNECTED` → `PROBE_DISCONNECTED`
- `NO_TISSUE` → `PROBE_NOT_APPLIED`
- `PROBE_ON_PATIENT` → `PROBE_APPLIED`

**Decisiones de la máquina de estados:**

1. **Prioridad:** PROBE_DISCONNECTED > PROBE_NOT_APPLIED > PROBE_APPLIED (evaluación por prioridad cada ciclo)

2. **Sin confirmación adicional.** Protección implícita en tres capas:
   - EMA τ_mean=100ms: suaviza transientes en OT
   - Histéresis OT (0.20/0.15): impide oscilación en zona intermedia
   - `estimator_ready` = 1500ms: bloquea detección tras reset/desconexión
   - NOT_APPLIED→APPLIED tarda ~324ms por convergencia natural de EMA (de 2.7 a cruzar 0.15)

3. **Responsabilidad: RSQM.** Razones: misma cadencia (500 Hz), acceso a datos crudos, naturaleza diagnóstica, coherencia con spec existente.

4. **Output por muestra (500 Hz).** `RSQMResult` incluye `ProbeState` junto a `RSQI` y `DiagCode`. Permite que cualquier consumidor futuro (SpO2, alarmas) use el estado sin retraso de ventana.

5. **Comportamiento HGAC por estado:**

| Estado | HGAC |
|---|---|
| `PROBE_APPLIED` | Operación normal (P1-P4) |
| `PROBE_NOT_APPLIED` | Inhibido. Mantiene configuración actual (preserva memoria del punto de operación para reacquisición rápida si el dedo vuelve) |
| `PROBE_DISCONNECTED` | Inhibido. Reset a ganancia mínima (RF min, RG=0dB, LED min) — punto de partida limpio para re-detección |

Asimetría intencional: NOT_APPLIED conserva la ganancia del último estado APPLIED; DISCONNECTED la resetea porque no hay continuidad (podría reconectarse cualquier sonda).

**Plan de implementación:**

| Prioridad | Tarea | Bloqueado por |
|---|---|---|
| 1 | Diseño RSQM completo ✅ | — |
| 2 | Implementar RSQM | Diseño completo |
| 3 | Terminar diseño HGAC | Decisión ProbeState ✅ |
| 4 | Implementar HGAC | RSQM implementado |
| 5 | Validación hardware | Todo implementado |

---

## Sesión 2026-05-28a

### Tema: Constantes de tiempo para los EMA estimators del criterio PROBE_DISCONNECTED

**Pregunta:** ¿qué α (o τ) usar para EMA mean y EMA variance a 500 Hz?

**Análisis:**

- **EMA mean**: en DISCONNECTED la señal es siempre ≈ 0; no hay AC que promediar. Solo necesita converger al nivel DC. α rápida es suficiente.
- **EMA variance**: la varianza en APPLIED está dominada por el PPG AC. Para estimar correctamente debe cubrir varios ciclos cardíacos. FC mínima clínicamente relevante: ~30 bpm neonatal = 0.5 Hz = período 1000 ms = 500 muestras @ 500 Hz. Por tanto τ_var debe ser comparable o mayor a ese período.
- **Margen disponible**: DISCONNECTED max std observado = 213; umbral = 500 → margen ×2.3. Suficiente para un estimador impreciso → τ_var no necesita ser tan largo como para una medida de SpO2.

**Decisión:**

| Estimator | α | τ | τ en ms @ 500 Hz |
|---|---|---|---|
| EMA mean (LED_Sub_mean) | 0.02 | 50 samples | 100 ms |
| EMA variance (LED_Sub_std) | 0.004 | 250 samples | 500 ms |
| `estimator_ready` delay | — | 3 × τ_var = 750 samples | 1500 ms |

**Razón de la asimetría mean/var:**
- Mean: detector de nivel DC → rápido (100 ms)
- Variance: detector estadístico, necesita integrar ≥ ½ ciclo cardíaco a 30 bpm → 500 ms es el mínimo razonable

**Código resultante:**

```cpp
constexpr float ALPHA_MEAN = 0.02f;   // τ = 100ms @ 500Hz
constexpr float ALPHA_VAR  = 0.004f;  // τ = 500ms @ 500Hz
constexpr int   ESTIMATOR_READY_SAMPLES = 750;  // 3 × τ_var = 1500ms

// Update por muestra:
ema_mean += ALPHA_MEAN * (x - ema_mean);
float diff = x - ema_mean;
ema_var  += ALPHA_VAR  * (diff * diff - ema_var);
ema_std   = sqrtf(ema_var);

// Reset al cambiar RF/RG/ambdac:
ema_mean = x;  ema_var = 0.0f;  sample_count = 0;
bool estimator_ready = (++sample_count >= ESTIMATOR_READY_SAMPLES);
```

**Alternativa simplificada aceptable:** α = 0.004 para ambos (mean y var). Mean tarda 1500 ms en establecerse — conservador pero seguro si la simplicidad es preferida.

---

## Sesión 2026-05-28b

### Tema: Criterio NOT_APPLIED vs APPLIED — optical_transmittance y limitación de tipo de sonda

**Decisión de nombre:** la métrica normalizada `LED_Sub_mean / (LED1mA × RF1_Ω × RG1_linear)` se denominará **`optical_transmittance`** en el código y la spec. Término físico estándar (transmitancia óptica), en inglés, sin abreviatura.

```
optical_transmittance = LED1_Sub_mean / (LED1mA × RF1_ohms × RG1_linear)
```

Valores observados en CSV:
- PROBE_APPLIED:     ≈ 0.05 (tejido absorbe ~95% de la luz)
- PROBE_NOT_APPLIED: ≈ 2.7  (camino óptico libre, factor ×54)

El valor >1 no es físicamente incorrecto: la normalización es relativa a la cadena de ganancia del sistema, no a una fuente de referencia absoluta.

**Decisión de detector:** Opción B — usar `optical_transmittance` como métrica unificada para NOT_APPLIED vs APPLIED, calculada siempre en el punto de operación actual. Cuando el canal está saturado, se asigna un valor de saturación ficticio alto (→ NOT_APPLIED). Sin cambio de configuración del AFE.

**Limitación — tipo de sonda (anotar en spec HGAC):**
El criterio NOT_APPLIED basado en `optical_transmittance` asume que cuando se retira el dedo, LED y fotodiodo quedan enfrentados con camino óptico libre (sondas tipo clip reutilizables). En sondas desechables adhesivas donde los elementos se separan físicamente al retirar el sensor, `optical_transmittance` en NOT_APPLIED puede ser comparable a APPLIED y la detección fallaría. El algoritmo no está validado para ese tipo de sonda.

**Umbrales NOT_APPLIED (con histéresis):**

```cpp
constexpr float optical_trans_not_applied_hi_thr = 0.20f;  // entrar NOT_APPLIED
constexpr float optical_trans_not_applied_lo_thr = 0.15f;  // salir NOT_APPLIED (volver a APPLIED)
```

Valores: APPLIED medido ≈ 0.05, NOT_APPLIED medido ≈ 2.7 (factor ×54).
- Hi_thr = 0.20: margen ×4 sobre APPLIED — sesgo hacia NOT_APPLIED (falso APPLIED es el error más peligroso: daría datos erróneos)
- Lo_thr = 0.15: margen ×3 sobre APPLIED — menos exigente que 0.10 (×2) para evitar que el sistema quede atascado en NOT_APPLIED con sondas o dedos con transmitancia APPLIED algo elevada (neonatal, dedo fino)

**Nota de alcance:** `optical_transmittance` se usará también en RSQM, detección de sonda aflojada y limb detection — no es exclusiva de este detector. Por eso los nombres de umbral incluyen `not_applied` como scope explícito.

**Valor de saturación cuando LED1_mean ≥ ADC_POSITIVE_SAT:**

Decisión: asignar `OPTICAL_TRANS_SATURATED = 100.0f`.

Razón de necesidad: cuando LED y ALED están ambos saturados, `LED1_Sub_mean ≈ 0` → OT ≈ 0 → falso APPLIED (el error más peligroso). El criterio DISCONNECTED no lo captura porque excluye expresamente `LED1_mean ≥ 2M`. Sin override, ese caso produce datos erróneos.

Razón de elección de 100.0f sobre NaN: en IEEE 754, cualquier comparación con NaN devuelve false — `NaN > 0.20f` es false, por lo que el detector NOT_APPLIED fallaría silenciosamente. Con `100.0f` la comparación funciona directamente sin casos especiales.

```cpp
constexpr float OPTICAL_TRANS_SATURATED = 100.0f;

float optical_transmittance;
if (LED1_mean >= ADC_POSITIVE_SAT) {
    optical_transmittance = OPTICAL_TRANS_SATURATED;
} else {
    optical_transmittance = LED1_Sub_mean / (LED1mA * RF1_ohms * Rg1_linear);
}

// Detector NOT_APPLIED:
bool is_not_applied = optical_transmittance > optical_trans_not_applied_hi_thr;
```

**Canales: OR logic (LED1 y LED2)**

Decisión: usar ambos canales con lógica OR.

```cpp
bool is_not_applied = (ot1 > optical_trans_not_applied_hi_thr) ||
                      (ot2 > optical_trans_not_applied_hi_thr);
```

Razón: el error peligroso es falso APPLIED. Con AND, si un canal da OT anómalo bajo (p.ej. artefacto de descarga CF que en el CSV produce OT negativo), NOT_APPLIED no se declara → falso APPLIED con datos erróneos. Con OR, basta que un canal detecte correctamente. El riesgo inverso (falso NOT_APPLIED por un canal subiendo a >0.20 estando APPLIED) es improbable dado que APPLIED da OT ≈ 0.05, ×4 por debajo del umbral.

**Cálculo de OT: valor crudo vs EMA**

- **Chequeo de saturación** (`LED1_raw >= ADC_POSITIVE_SAT`): valor crudo instantáneo. La saturación es un evento binario; si la muestra ya está en el rail, la información está disponible ahora mismo. Usar EMA introduciría latencia innecesaria.
- **Cálculo de OT** (`LED1_Sub_ema_mean / denominador`): EMA mean (α=0.02). Necesario para suprimir el PPG AC que montado sobre LED1_Sub haría que OT oscile muestra a muestra cruzando umbrales falsamente.

---

## Sesión 2026-05-28e

**Tema:** `diag_code` uint16_t → uint32_t

**Decisión:** Ampliar `diag_code` de `uint16_t` a `uint32_t` para tener 32 bits disponibles. Motivación: en el futuro podrían añadirse los 13 flags del registro DIAG del chip (`runDiagnostics()`), flags de HGAC, y otras condiciones.

**Cambios:**
- `incunest_afe4490.h`: constantes `RSQM_*` cambiadas a `constexpr uint32_t ... UL`; campo `diag_code` en `AFE4490Data` cambiado a `uint32_t`
- `incunest_afe4490.cpp`: variable local `diag` en `_update_rsqm()` cambiada a `uint32_t`
- `incunest_afe4490_spec.md`: mismos cambios reflejados; comentario "bits 3–31 reserved for future use" añadido

---

## Sesión 2026-05-28d

**Tema:** Implementación RSQM (v0.27)

**Trabajo realizado:**

RSQM implementado en `incunest_afe4490.h` y `incunest_afe4490.cpp`. Librería actualizada a v0.27. Spec actualizada a v0.27 con nueva sección §5.6.

**Cambios en incunest_afe4490.h:**
- `ProbeState` enum (PROBE_DISCONNECTED / PROBE_NOT_APPLIED / PROBE_APPLIED) añadido antes de `AFE4490Data`
- Constantes `RSQM_AMB_SAT = 0x0001`, `RSQM_SIGNAL_WEAK = 0x0002`, `RSQM_HW_SETTLING = 0x0004`
- `AFE4490Data` gana `rsqi` (uint8_t), `diag_code` (uint16_t), `probe_state` (ProbeState)
- Private struct `RsqmEmaChannel { float ema_mean; float ema_var; uint32_t count; }`
- 10 `static constexpr` RSQM constants (α_mean, α_var, ready_count, umbrales de detección)
- Private state: `_rsqm_led1_sub`, `_rsqm_led2_sub`, `_rsqm_probe_state`, `_rsqm_settling_countdown`
- Declaración de `_update_rsqm()`

**Cambios en incunest_afe4490.cpp:**
- `stg2_rg_linear[5] = {1.0f, 1.496f, 2.0f, 2.985f, 3.981f}` añadido al namespace anónimo
- `_update_rsqm()` implementado (~80 líneas): EMA update, PROBE_DISCONNECTED detection, optical_transmittance con histéresis, DiagCode (AMB_SAT + SIGNAL_WEAK + HW_SETTLING), RSQI
- Constructor y `_reset_algorithms()` actualizados con inicialización RSQM
- `_update_rsqm()` llamado al inicio de `_process_sample()`, antes de todos los demás algoritmos

**Decisiones de implementación:**
- `RSQM_HW_SETTLING` no se activa en v0.27 — se activará cuando HGAC esté implementado
- `rsqm_signal_weak_std = 2000.0f` es provisional — necesita calibración en hardware
- ENSEPGAIN=0 manejado: cuando `_afe_ensepgain=false`, se usan los settings LED2 para ambos canales en el cálculo de OT
- OT hysteresis: entrada con `ot_hi_thr=0.20`, salida con `ot_lo_thr=0.15`; OR logic en ambos canales

**Spec actualizada:**
- Título v0.25 → v0.27
- Section 2.1: nuevos campos en AFE4490Data
- Section 3: ProbeState enum y DiagCode constants añadidos
- Section 5.6 RSQM (nueva): EMA estimators, state machine, DiagCode table, RSQI rule
- Section 12.3: eliminados umbrales simplistas, referencia a §5.6
- Section 14: entrada v0.27 añadida

```cpp
float ot1;
if (LED1_raw >= ADC_POSITIVE_SAT) {
    ot1 = OPTICAL_TRANS_SATURATED;  // 100.0f
} else {
    ot1 = LED1_Sub_ema_mean / (LED1mA * RF1_ohms * RG1_linear);
}
```

---

## Sesión 2026-05-28f

**Tema:** Propagación de campos RSQM a consumidores de la librería

**Trabajo realizado:**

Actualización de los dos consumidores de `AFE4490Data` para incluir los tres campos nuevos (`rsqi`, `diag_code`, `probe_state`).

**`src/main.cpp` (PulseNest):**
- Frame `$M1` ampliado de 19 a 22 campos de datos
- Nuevos campos al final: `RSQI` (`%u`), `DiagCode` (`%lu` decimal), `ProbeState` (`%d` entero: 0=DISCONNECTED, 1=NOT_APPLIED, 2=APPLIED)
- Comentario de cabecera actualizado

**`examples/basic/main.cpp` (incunest_afe4490):**
- Añade al output Serial por muestra: estado de sonda (texto), RSQI, y DiagCode en hex si != 0
- Ejemplo: `Probe: APPLIED  RSQI: 1` o `Probe: NOT_APPLIED  RSQI: 0  DiagCode: 0x1`

**Build:** SUCCESS, sin warnings (RAM 18.5%, Flash 27.7%)

**Pendiente:** ~~actualizar parser de `pulsenest_lab.py`~~ — completado en sesión 2026-05-28g

---

## Sesión 2026-05-28g

**Tema:** Actualización `pulsenest_lab.py` — parseo campos RSQM del frame `$M1`

**Cambios en `pulsenest_lab.py`:**
- 3 deques nuevos: `data_rsqi`, `data_diag_code`, `data_probe_state` (inicializados a 0)
- **Parser M1** (backward compatible): cuando `len(parts) >= 23` extrae partes [20], [21], [22]; si no (firmware antiguo `len(parts) < 23`) rellena con 0
- **Parser M2:** añade 0 por defecto para los 3 nuevos buffers
- **`_STATS_SIGNALS`:** 3 filas nuevas — `RSQI`, `DiagCode`, `ProbeState` — visibles en la tabla de estadísticas con tooltips
- **`_COLS` (LabCaptureWindow):** índices 20/21/22 añadidos — incluidos en captura CSV
- **CSV headers** `SERIAL_HEADER` y `UDP_HEADER`: añadidos `RSQI,DiagCode,ProbeState` al final

**Verificación:** `ast.parse()` → syntax OK. Script relanzado.

---

## Sesión 2026-05-28h — Nomenclatura HGAC: "sig" → ppg_dc / dc_

### Contexto
Consulta ISO 80601-2-61:2026 §201.3 (Terms and Definitions) para proponer mejor nombre para "sig" (señal diferencial LED−ALED en %FS), considerado demasiado ambiguo.

### Decisiones tomadas

**Renaming de "sig":**
- ISO §201.3.245 (%mod): *"DC refers to the baseline (non-modulated) signal portion"*
- `sig_led1_pct` = mediana(LED1−ALED1)/FS×100 = componente DC de la señal PPG
- **Nombre conceptual (spec/docs):** `ppg_dc` — trazable a ISO §201.3.245
- **Nombre en código (variables):** prefijo `dc_` → `dc_led1_pct`, `dc_led2_pct`
- `ppg_dc` solo útil como nombre genérico; en código siempre lleva sufijo `_led1/_led2` y `ppg_` sería redundante
- Zonas de diseño (no en código aún): `DC_WEAK`, `DC_SAT`, `DC_NOMINAL`, `DC_DEAD`
- HGACConfig: `hgac_dc_target_pct`, `hgac_dc_nominal_lo/hi`, etc.

**"amb" se mantiene** — la ISO no define término mejor para el componente ambiental (ALED).

**Corrección:** nombres correctos de probe states son `PROBE_DISCONNECTED / PROBE_NOT_APPLIED / PROBE_APPLIED` (ya correctos en `project_probe_state_detector.md`).

### Fix pulsenest_lab.py
- `SyntaxWarning: invalid escape sequence '\$'` en líneas 8493 y 8502 (tooltips V_TIA)
- Corregido: `\$` → `\\$`

### Ficheros modificados
- `pulsenest_lab.py`: fix `\$` → `\\$` (líneas 8493/8502)
- `memory/project_agc_design.md`: `sig_*` → `ppg_dc_*`; nota que nombres de zona son diseño, no código

---


## Sesión 2026-05-28i

**Tema:** Upload firmware v0.27 + ProbeState background color en SIGNAL STATS

### Cambios realizados

**`incunest_afe4490/library.json`:**
- Versión corregida: `0.20.0` → `0.27.0` (estaba desactualizada respecto al código)

**`pulsenest_lab.py`:**
- Tabla SIGNAL STATS, fila "ProbeState", columna "Signal" (col 0): fondo cambia dinámicamente con el valor instantáneo de `data_probe_state`
  - Verde oscuro `#004A00` → `APPLIED` (2)
  - Ámbar oscuro `#4A3A00` → `NOT_APPLIED` (1)
  - Rojo oscuro  `#4A0000` → `DISCONNECTED` (0)
- 3 constantes de clase nuevas: `_PROBE_APPLIED_BG`, `_PROBE_NOT_APPLIED_BG`, `_PROBE_DISCONNECTED_BG`
- Lógica añadida al final de `_update_stats_table()` (dentro del loop, cuando `name == "ProbeState"`)
- Usa `self.data_probe_state[-1]` (valor instantáneo), no la media del buffer de stats

### Build / upload
- `pio run -e incunest_V16 -t upload --upload-port COM15` → SUCCESS (RAM 18.5%, Flash 27.7%)
- Script relanzado: `start pythonw pulsenest_lab.py`


## Sesión 2026-05-28j

**Tema:** ProbeState background — actualización instantánea (200 ms) en lugar de esperar al intervalo de stats

### Cambios en `pulsenest_lab.py`

- Eliminado el bloque `if name == "ProbeState"` de `_update_stats_table()` (donde se actualizaba solo al final de cada intervalo de stats)
- Añadido bloque equivalente al inicio del `try` en `_refresh_plots_tick()` (corre cada 200 ms cuando hay datos nuevos):
  - Lee `self.data_probe_state[-1]` (valor instantáneo)
  - Aplica `_PROBE_APPLIED_BG` / `_PROBE_NOT_APPLIED_BG` / `_PROBE_DISCONNECTED_BG` / `_VTG_DEFAULT`
  - Actualiza `stats_table.item(len(_STATS_SIGNALS)-1, 0).setBackground(...)`
- Las constantes de color (`_PROBE_*_BG`) añadidas en sesión 2026-05-28i se mantienen sin cambios

### Decisión de diseño
- Velocidad de refresco: 200 ms (cada render tick con datos nuevos) — suficiente para el usuario
- No se pone en `_process_frames_tick()` (20 ms) porque 200 ms es percibido como instantáneo


## Sesión 2026-05-28k

**Tema:** ProbeState background — colores más intensos

### Cambios en `pulsenest_lab.py`

Constantes de color actualizadas (más luminosas):

| Constante | Antes | Ahora |
|---|---|---|
| `_PROBE_APPLIED_BG` | `#004A00` | `#1A7A1A` (verde) |
| `_PROBE_NOT_APPLIED_BG` | `#4A3A00` | `#7A6400` (ámbar) |
| `_PROBE_DISCONNECTED_BG` | `#4A0000` | `#7A0000` (rojo) |


## Sesión 2026-05-28l

**Tema:** ProbeState cell — verde más intenso + font blanco cuando APPLIED

### Cambios en `pulsenest_lab.py`

- `_PROBE_APPLIED_BG`: `#1A7A1A` → `#00A000` (verde más intenso)
- En `_refresh_plots_tick()`: añadido `setForeground` en la celda ProbeState col-0:
  - `#FFFFFF` (blanco) cuando `_ps == 2` (APPLIED)
  - `#AAAAAA` (gris claro) para el resto de estados


## Sesión 2026-05-28m

**Tema:** Fix RSQM — falso PROBE_APPLIED al desconectar desde NOT_APPLIED

### Causa raíz

Al desconectar el cable desde NOT_APPLIED:
1. `led1_aled1` cae inmediatamente a ~0 o negativo (ruido)
2. La EMA `m1` decae lentamente (τ≈100ms) desde valor alto positivo hacia cero
3. Al cruzar `m1` por cero → `ot1 = m1/(mA×RF×RG) < 0` → ambos OT < `lo_thr` (0.15)
4. La condición OR de NOT_APPLIED falla → estado cae falsamente a **PROBE_APPLIED**
5. Tras ~100ms más, EMA < 5000 → DISCONNECTED

### Fix en `incunest_afe4490.cpp` — `_update_rsqm()`

Añadido "disconnect guard": cuando el estado anterior es NOT_APPLIED y cualquiera de las EMA es ≤ 0, se bloquea la transición a APPLIED. Una EMA negativa indica cruce por cero durante desconexión, no contacto genuino (el contacto real siempre produce LED_Sub positivo pequeño).

```cpp
const bool ot_not_applied  = (ot1 > thr) || (ot2 > thr);
const bool ema_negative    = prev_not_applied && (m1 <= 0.0f || m2 <= 0.0f);
_rsqm_probe_state = (ot_not_applied || ema_negative)
                        ? ProbeState::PROBE_NOT_APPLIED
                        : ProbeState::PROBE_APPLIED;
```

### Spec actualizada (`incunest_afe4490_spec.md`)

Añadido párrafo "Disconnect guard" en §5.6.2 documentando la condición.

### Build / upload
- SUCCESS (RAM 18.5%, Flash 27.7%)
- incunest_afe4490 @ 0.27.0 confirmado por PlatformIO


## Sesión 2026-05-28n

**Tema:** Fix RSQM ProbeState — falso APPLIED en transiciones (v2)

### Causa raíz real (análisis más profundo)

El fix anterior (ema_negative guard) era insuficiente. El problema ocurre en AMBAS direcciones:

- **DISCONNECTED → NOT_APPLIED:** EMA arranca en ~0, sube lentamente. Cuando `disconnected=false` pero EMA aún pequeña → `ot = m/normalization` muy bajo → falso APPLIED antes de llegar a > 0.20.
- **NOT_APPLIED → DISCONNECTED:** EMA decae lentamente. Cuando EMA pasa por la zona ~10000..0 → `ot < 0.15` → falso APPLIED antes de llegar a DISCONNECTED.

El patrón común: la EMA (τ≈100ms) tarda ~300ms en settlear tras una transición rápida. Durante ese tiempo, el OT derivado de la EMA pasa por la zona APPLIED (0–0.20), causando el estado falso.

### Fix — `incunest_afe4490.cpp`

**OT calculado con valores instantáneos (`s1`/`s2`) en lugar de EMA (`m1`/`m2`):**

```cpp
const float ot1 = (led1 >= rsqm_adc_positive_sat)
                    ? rsqm_ot_saturated
                    : s1 / (_afe_led1_current_mA * rf1 * rg1);  // s1 = led1_aled1 instantáneo
```

- Responde en 1 muestra (vs ~300ms con EMA)
- Falsos positivos por ruido PPG negligibles: APPLIED OT ≈ 0.05 vs NOT_APPLIED OT ≈ 2.8 (factor ×54); modulación PPG 2% → ±0.001 OT
- Revert del guard `ema_negative` (ya no necesario — era parche insuficiente)

### Spec actualizada (`incunest_afe4490_spec.md`)

§5.6.2: sustituida nota "Disconnect guard" por nota sobre OT instantáneo con justificación.


## Sesión 2026-05-28o

**Tema:** Análisis ProbeState + OT columns en CSV + fix DISCONNECTED instantáneo

### Análisis datos afe_sweep_test.csv

Tablas resumen para DISCONNECTED y NOT_APPLIED:

**DISCONNECTED (N=279):**
- LED1/LED2/ALED1/ALED2_mean: −2096919 a −3469 (todos NEGATIVOS — cerca del rail negativo ADC)
- LED1_Sub_mean / LED2_Sub_mean: ≈0 (±3000) — los 4 canales se van juntos al rail negativo, la resta se cancela

**NOT_APPLIED (N=174):**
- LED1_mean: −2096919 a +2096921 (rango completo — sweep cubre configuraciones que saturan en ambos sentidos)
- LED1_Sub_mean: −1.86M a +1.85M

**Conclusión:** No existe umbral fijo en `led1` raw que separe limpiamente DISCONNECTED de NOT_APPLIED — NOT_APPLIED también puede tener valores negativos. El criterio correcto sigue siendo `LED1_Sub_mean ≈ 0` (que es lo que ya hace el RSQM). Los flashes verdes son probablemente bounce del conector físico durante la transición.

### Fix DISCONNECTED en `incunest_afe4490` (sesión anterior, completado)

- `rsqm_disconn_raw_mean = 8000`: nueva constante en header
- `instant_disconnected = led1 < 8000 && led2 < 8000` (OR con slow path EMA)
- Nota posterior: esta detección instantánea puede ser insuficiente porque NOT_APPLIED también tiene led1 negativo (< 8000) para ciertas configs del sweep

### Cambio `pulsenest_lab.py` — OT1/OT2 en CSV del sweep

- `_CSV_HEADER`: añadidas columnas `OT1` y `OT2` al final (42 columnas total)
- `_write_row()`: calcula `OT = LED_Sub_mean / (LED_mA × RF_Ω × RG_linear)` usando dicts `_rf_ohm` y `_rg_lin` locales
- Permite analizar el OT calculado directamente desde el CSV para calibrar umbrales RSQM


## Sesión 2026-05-28p — Cambio de estrategia ProbeState detector

### Estrategia anterior (archivada — no usar)

**DISCONNECTED** (EMA-based, varios intentos de fix):
- Criterio original: `|m1| < 5000 AND |m2| < 5000 AND st1 < 500 AND st2 < 500 AND led1 < 2M AND led2 < 2M`
- Problema: la varianza EMA (τ≈500ms) tarda hasta 1500ms en settlear → ventana de falso APPLIED muy larga
- Fix 1: añadir `ema_negative` guard → insuficiente (solo cubre cruce por cero, no el tramo positivo)
- Fix 2: OT instantáneo (s1/s2 en vez de m1/m2) → peor aún: OT ≈ 0 desde el primer frame al desconectar
- Fix 3: `instant_disconnected = led1 < 8000 AND led2 < 8000` OR slow EMA → no funciona porque NOT_APPLIED también tiene led1 negativo (< 8000) en configs de alta ganancia del sweep

**Conclusión:** no existe un umbral fijo en valores raw que separe limpiamente DISCONNECTED de NOT_APPLIED en todos los rangos del sweep. La estrategia EMA es correcta en diseño pero demasiado lenta.

### Nueva estrategia (2026-05-28p)

**DISCONNECTED** — basada en física del circuito:
- Cuando el cable está desconectado, la entrada del TIA flota → la corriente de offset de entrada mueve los 4 canales al mismo valor negativo
- Criterio: `led1 < 0 AND aled1 < 0 AND led2 < 0 AND aled2 < 0 AND |s1| < umbral AND |s2| < umbral`
- Instantáneo (1 frame = 2ms), sin EMA
- Confirmado por CSV: DISCONNECTED LED1_Sub_mean ≈ −592, rango −3117..+65; todos los canales negativos

**NOT_APPLIED vs APPLIED** — basado en OT instantáneo con condiciones de saturación (igual que antes)


---

## Sesión 2026-05-28q — Implementación nueva estrategia PROBE_DISCONNECTED

**Tema:** Implementar la nueva estrategia de detección PROBE_DISCONNECTED diseñada en sesión 2026-05-28p

### Cambios implementados

**`incunest_afe4490.cpp` — `_update_rsqm()`:**
- Eliminado bloque `if (!ready) { DISCONNECTED }` — ya no necesario (detección instantánea)
- Eliminada lógica `instant_disconnected` y `stable_disconnected`
- Nuevo criterio instantáneo:
  ```cpp
  const bool disconnected =
      led1 < 0 && aled1 < 0 && led2 < 0 && aled2 < 0 &&
      fabsf(s1) < rsqm_disconn_sub_mean &&
      fabsf(s2) < rsqm_disconn_sub_mean;
  ```
- OT/NOT_APPLIED/APPLIED sin cambios

**`incunest_afe4490.h`:**
- Eliminados constantes obsoletas: `rsqm_disconn_sub_std`, `rsqm_disconn_raw_sat`, `rsqm_disconn_raw_mean`
- Conservado `rsqm_disconn_sub_mean = 5000.0f` (reutilizado para |LED_Sub| threshold)

**`incunest_afe4490_spec.md` §5.6.2:**
- Actualizado criterio DISCONNECTED (4 canales negativos + |LED_Sub| < 5000)
- Añadida validación con afe_sweep_test.csv
- OT: corregida fórmula (LED_Sub instantáneo, no EMA_mean)

### Decisiones tomadas
- Sin warmup EMA para ProbeState: detección puramente instantánea desde el primer sample
- EMA sigue calculándose (necesaria para RSQM_SIGNAL_WEAK)

### Estado
- Build: OK (incunest_V16)
- Upload: pendiente (COM15 no disponible al hacer commit)
- Commit: `0d12680` en repo incunest_afe4490

---

## Sesión 2026-05-28r — Simplificación OT: eliminar chequeo ENSEPGAIN

**Tema:** Simplificación de las líneas 1008-1010 en `_update_rsqm()`

### Decisión
El chequeo `_afe_ensepgain ? _afe_tia_gain_led1 : _afe_tia_gain_led2` es innecesario porque `_afe_tia_gain_led1` etc. son siempre válidos independientemente del valor de ENSEPGAIN. Se simplifica usando directamente los miembros LED1/LED2.

### Cambios
- `incunest_afe4490.cpp`: eliminadas líneas `gain1_enum`, `rg1_enum`, `en1` con ternario ENSEPGAIN; rf1/rg1 usan `_afe_tia_gain_led1`/`_afe_stage2_gain_led1`/`_afe_stage2_en1` directamente
- `incunest_afe4490_spec.md`: eliminada nota "RF/RG selection for OT: when ENSEPGAIN=0..."

### Estado
- Build: OK. Upload pendiente (COM15 no disponible).

---

## Sesión 2026-05-28s — RSQM_SIGNAL_WEAK: añadir chequeo LED2

**Tema:** Extender RSQM_SIGNAL_WEAK para comprobar ambos canales

### Decisión
SpO2 necesita IR y RED simultáneamente. RSQM_SIGNAL_WEAK debe dispararse si cualquiera de los dos canales tiene amplitud insuficiente. Se añade `sqrtf(_rsqm_led2_sub.ema_var) < rsqm_signal_weak_std` en condición OR.

EMA mean sigue siendo necesaria para calcular ema_var (d = s - ema_mean). No se elimina nada del bloque EMA.

### Cambios
- `incunest_afe4490.cpp`: condición RSQM_SIGNAL_WEAK ampliada con OR sobre LED2_Sub_std
- `incunest_afe4490_spec.md`: tabla DiagCode §5.6.3 actualizada

### Estado
- Build: OK. Upload pendiente.

---

## Sesión 2026-05-28t — _set_probe_state(): debounce de transiciones ProbeState

**Tema:** Eliminar parpadeo verde falso en transición DISCONNECTED→NOT_APPLIED mediante debounce centralizado

### Análisis del parpadeo
Tramas reales durante el transitorio de conexión: los 4 canales ADC pasan de negativo grande (~-4600) a positivo grande (~1M) en un frame. Durante ~5 frames, LED_Sub es pequeño (los canales suben juntos) → OT < threshold → falso PROBE_APPLIED.

### Decisión de diseño
Crear `_set_probe_state(ProbeState requested)` como función centralizada para cambios de estado. Implementa debounce: exige N muestras consecutivas con el mismo estado antes de hacer efectivo el cambio. Extensible para futuros usos.

N = 50 muestras = 100ms @ 500Hz. Fiabilidad > velocidad (dispositivo médico).

La hiperesis OT usa `_rsqm_probe_state` (estado comprometido, no pendiente) → correcto.

### Cambios
**`incunest_afe4490.h`:**
- Nuevo constante: `rsqm_probe_state_min_count = 50`
- Nuevos miembros: `_rsqm_probe_state_pending`, `_rsqm_probe_state_count`
- Declaración: `void _set_probe_state(ProbeState requested)`

**`incunest_afe4490.cpp`:**
- Implementación de `_set_probe_state()` justo antes de `_update_rsqm()`
- Las dos asignaciones directas a `_rsqm_probe_state` en `_update_rsqm()` sustituidas por `_set_probe_state(...)`

**`incunest_afe4490_spec.md`:**
- §5.6.2: añadido párrafo sobre debounce

### Estado
- Build y upload: OK. Pendiente test en hardware.

---

## Sesión 2026-05-28u — Renombrar ot1/ot2 → optical_transmittance_ir/red

**Tema:** Mejorar legibilidad de variables ot1/ot2 en _update_rsqm()

### Cambios
- `incunest_afe4490.cpp`: `ot1` → `optical_transmittance_ir`, `ot2` → `optical_transmittance_red`
- Comentario expandido explicando significado físico, valores típicos (APPLIED≈0.05, NOT_APPLIED≈2.8) y razón del sentinel (NaN)

---

## Sesión 2026-05-28v — Nomenclatura optical_transmittance: ir/red → led1/led2

**Tema:** Corrección de nomenclatura en variables optical_transmittance

### Decisión
`_update_rsqm()` es "Raw" Signal Quality Monitor — todavía en territorio hardware, no fisiológico. El optical transmittance aquí detecta una condición física (¿hay tejido bloqueando la luz?), no interpreta hemoglobina. La frontera ir/red se cruza al entrar en algoritmos fisiológicos (_compute_spo2, _compute_hr1, etc.), no en RSQM.

### Cambios
- `incunest_afe4490.cpp`: `optical_transmittance_ir` → `optical_transmittance_led1`, `optical_transmittance_red` → `optical_transmittance_led2`

---

## Sesión 2026-05-28w — OT_LED1/OT_LED2 en SIGNAL STATS (calculado en script)

**Tema:** Visualizar optical_transmittance en tiempo real para investigar la transición NOT_APPLIED/APPLIED

### Decisión
OT calculado en el script Python desde los datos $M1 + parámetros del último $CFG recibido. No se añade a la trama $M1 del firmware (innecesario).

### Cambios (`pulsenest_lab.py`)
- Nuevas constantes de clase: `_STG2_RG_LINEAR` (gains lineales = firmware), `_TIA_RF_OHM` (RF en Ω)
- Nuevas deques: `data_ot_led1`, `data_ot_led2`
- Nuevo método: `_compute_ot(led_sub, led_ma_str, tia_str, stg2_str, stage2en_str)` — devuelve 0.0 si faltan parámetros
- Parser $M1: calcula y añade OT_LED1/OT_LED2 tras cada muestra usando `_last_cfg`
- Parser $M2: añade 0.0 a ambas deques
- `_STATS_SIGNALS`: dos nuevas filas `OT_LED1` y `OT_LED2` antes de `ProbeState`

### Fórmula
`OT = LED_Sub / (LED_mA × RF_Ω × RG_linear)`
- APPLIED ≈ 0.05, NOT_APPLIED ≈ 2.8, DISCONNECTED ≈ 0

---

## Sesión 2026-05-28x — DiagCode: integración AFE DIAG register + RSQM flags

**Tema:** Extender diag_code para incluir los 13 bits del registro DIAG del AFE4490

### Diseño acordado
- Bits 0–12: AFE hardware DIAG register (set por runAfeDiagnostics(), persiste hasta próxima llamada)
- Bits 13+: RSQM flags (actualizados a 500 Hz por _update_rsqm())
- Variable interna `_diag_code`: mantiene estado combinado completo en todo momento
  - runAfeDiagnostics() escribe bits 0-12: `_diag_code = (_diag_code & ~AFE_DIAG_MASK) | (result & AFE_DIAG_MASK)`
  - _update_rsqm() escribe bits 13+: `_diag_code = (_diag_code & AFE_DIAG_MASK) | rsqm_flags`
- Renombrado runDiagnostics() → runAfeDiagnostics() en toda la base de código

### Cambios

**`incunest_afe4490.h`:**
- 13 constantes `AFE_DIAG_*` (bits 0-12) + `AFE_DIAG_MASK = 0x1FFF`
- RSQM_AMB_SAT=0x2000, RSQM_SIGNAL_WEAK=0x4000, RSQM_HW_SETTLING=0x8000 (desplazados a bits 13-15)
- Nueva variable miembro: `uint32_t _diag_code { 0 }`
- `runDiagnostics()` → `runAfeDiagnostics()`

**`incunest_afe4490.cpp`:**
- `runAfeDiagnostics()`: actualiza bits 0-12 de `_diag_code` tras leer REG_DIAG
- `_update_rsqm()`: actualiza bits 13+ de `_diag_code`; `_current_data.diag_code = _diag_code`
- RSQI chequea `_diag_code == 0` (todos los bits, incluyendo AFE)

**`PulseNest/src/main.cpp`:**
- `afe.runDiagnostics()` → `afe.runAfeDiagnostics()`

**`incunest_afe4490_spec.md`:**
- §3 struct: actualizado; §5.6.3: tabla DiagCode expandida con 13 bits AFE + 3 bits RSQM
- Todas las referencias a runDiagnostics renombradas

**`pulsenest_lab.py`:**
- Tooltip de DiagCode actualizado con nuevo layout de bits

---

## Sesión 2026-05-28y — _diag_task_body(): diagnósticos AFE autónomos

**Tema:** Ejecutar runAfeDiagnostics() automáticamente en cambios de estado y periódicamente

### Decisión de diseño
runAfeDiagnostics() NO puede llamarse desde el task DRDY (deadlock + 10ms block).
Solución: segundo task interno `incunest_diag` de baja prioridad.

### Comportamiento
- Cambio de estado: _set_probe_state() envía xTaskNotify → tarea despierta inmediatamente → runAfeDiagnostics()
- Periódico: timeout cada rsqm_diag_period_ms=5000ms → runAfeDiagnostics() solo si probe_state ≠ PROBE_APPLIED (evita blackout en medición activa)
- runAfeDiagnostics() sigue siendo pública para llamadas externas ($DIAG?). _spi_mutex serializa ambos callers.

### Cambios (`incunest_afe4490.h`)
- Nuevas defines: INCUNEST_AFE4490_DIAG_TASK_STACK=2048, INCUNEST_AFE4490_DIAG_TASK_PRIORITY=(main-2)
- Nueva constante: rsqm_diag_period_ms=5000
- Nueva declaración: _diag_task_trampoline(), _diag_task_body()
- Nuevo miembro: _diag_task_handle

### Cambios (`incunest_afe4490.cpp`)
- Constructor: _diag_task_handle(nullptr)
- begin(): xTaskCreatePinnedToCore para incunest_diag
- stop(): vTaskDelete(_diag_task_handle)
- _set_probe_state(): xTaskNotify(_diag_task_handle) cuando nuevo estado != anterior
- _diag_task_body() + _diag_task_trampoline() implementados

### Cambios (`incunest_afe4490_spec.md`)
- §2.6b: callers de runAfeDiagnostics() documentados
- §5.7: nueva sección documenta _diag_task_body

---

## Sesión 2026-05-28z — OT hysteresis removal + debounce 200 ms

### Contexto
Continuación de sesiones 2026-05-28q/s/t/x/y. El header ya tenía `rsqm_ot_thr=0.20` (single threshold) pero el .cpp aún usaba la lógica de histéresis antigua con dos umbrales.

### Decisiones
- **Eliminación de histéresis OT:** `rsqm_ot_hi_thr` + `rsqm_ot_lo_thr` → `rsqm_ot_thr=0.20` (único umbral). El debounce de `_set_probe_state()` reemplaza la histéresis como mecanismo anti-oscilación.
- **Debounce aumentado a 200 ms:** `rsqm_probe_state_min_count` 50 → 100 muestras (100 ms → 200 ms @ 500 Hz). Rationale: 100 ms considerado insuficiente para transitorios de conexión/desconexión.

### Cambios (`incunest_afe4490.cpp`)
- `_update_rsqm()`: eliminadas variables `prev_not_applied` y `thr`; `_set_probe_state()` usa directamente `rsqm_ot_thr`
- Comentario actualizado: "Debounce (N=100 samples) in _set_probe_state() replaces the former dual-threshold hysteresis."

### Cambios (`incunest_afe4490.h`)
- `rsqm_probe_state_min_count`: 50 → 100 (200 ms @ 500 Hz)

### Cambios (`incunest_afe4490_spec.md`)
- §5.6.2: "Entry/Exit threshold" → "Threshold" único (0.20), nota sobre debounce como sustituto de histéresis
- §1285 tabla: nota de detección actualizada (instantáneo + OT single threshold + debounce)
- Changelog v0.27: mención hysteresis hi=0.20/lo=0.15 → single threshold 0.20 + 50-sample debounce (ahora 100)

---

## Sesión 2026-05-28aa — OT threshold 0.20 → 0.30

### Decisión
`rsqm_ot_thr` subido de 0.20 a 0.30. Margen resultante: ×6 sobre APPLIED medido (0.05), ×9 bajo NOT_APPLIED medido (2.7). Justificación: 0.20 demasiado cerca de APPLIED para sondas con mayor opacidad.

### Cambios
- `incunest_afe4490.h`: `rsqm_ot_thr = 0.20f` → `0.30f`
- `incunest_afe4490_spec.md`: threshold actualizado a 0.30 en §5.6.2 y changelog v0.27


---

## Sesión 2026-05-29a — PAUSE button en HR3TestWindow + memoria PDFs

### Contexto
Sesión de preguntas conceptuales y una modificación de pulsenest_lab.py.

### Preguntas conceptuales respondidas
- **hr2_sqi / hr3_sqi:** HR2_SQI = autocorrelación normalizada no sesgada en el lag dominante (corrección (N−τ)/N). HR3_SQI = concentración espectral HPS normalizada (P[peak]/ΣP[k] − 1/N) / (1 − 1/N). Ambos vienen del firmware en el frame $M1.
- **Slow path (incunest_afe4490.cpp):** Comentario en cabecera de `_compute_hr2()` (l.1809) y `_compute_hr3()` (l.1913). Significa el cálculo pesado que no corre en el tick de muestra (500 Hz / Task A), sino en Task B o C cuando el buffer está lleno (~0.5 s HR2, ~2.5 s HR3). Contraste con "fast path" = Task A a 500 Hz.

### Correcciones de memoria
- Frecuencia de muestreo: confirmada a 500 Hz (no 250 Hz — error verbal de Claude, no estaba en memoria)
- Paths de PDFs actualizados: `C:\PRJ\MOW\Misc\AFE4490\afe4490.pdf` y `C:\PRJ\MOW\PulseNest\ISO_80601-2-61-2026.pdf` → ambos a `C:\PRJ\MOW\PulseNest\docs\`
- `afe4490_datasheet_toc.md` separado en dos ficheros: `afe4490_toc.md` e `iso_80601-2-61-2026_toc.md`
- TOC completo de ISO 80601-2-61:2026 añadido a `iso_80601-2-61-2026_toc.md`

### Cambios (`pulsenest_lab.py`)
- **PAUSE button en HR3TestWindow:** botón checkable en toolbar (entre EXPORT CSV y el stretch). `_paused = False` en `__init__`. `_toggle_pause()` actualiza flag y texto PAUSE/RESUME. Guard `if self._offline_mode or self._paused: return` en `update_plots()`. Comportamiento idéntico al patrón de otras ventanas: datos y algoritmos siguen corriendo, solo se congela el rendering.

---

## Sesión 2026-05-29b — Documentación _compute_hr3() + tarea pendiente HR3 rate

### Contexto
Análisis del cálculo de SQI en `_compute_hr3()` y comparación con el mirror Python en `HR3TestCalc`.

### Aclaraciones conceptuales
- **Formato interleaved de `_hr3_fft`:** `_hr3_fft[2*k]` = parte real del bin k, `_hr3_fft[2*k+1]` = parte imaginaria. Son la parte real e imaginaria de UN solo bin espectral, no dos bins distintos. `P[k] = re[k]² + im[k]²` = potencia del bin k.
- **Diferencia Python vs firmware en HPS:** Python usa magnitudes (`np.abs(rfft)`), firmware usa potencias (`re² + im²`). El peak dominante es el mismo, la escala es distinta (potencia = magnitud²).
- **SQI Python vs firmware:** firmware aplica interpolación parabólica sobre HPS para `hps_interp` (numerador del SQI); Python usa directamente `hps[peak_global]` sin interpolar — divergencia conocida.

### Tarea apuntada
- Investigar cada cuánto se ejecuta `_compute_hr3()` — ver `project_hr3_execution_rate_task.md`

### Cambios (`incunest_afe4490.cpp`)
- Comentario en cabecera del bucle HPS (~l.1931): añadida explicación del formato interleaved de `_hr3_fft` y etiquetas `P[k]`, `P[2k]`, `P[3k]` en las tres líneas de cálculo de potencia.

---

## Sesión 2026-05-29c — HR3 SQI: combined global + local prominence (v0.28)

### Problema
HR3 SQI fallaba con ruido de baja frecuencia (movimiento de sonda). El SQI global mide fracción de energía HPS sobre todo el rango de búsqueda: un artefacto de movimiento puede crear una joroba ancha (8–15 bins) que sea globalmente dominante → SQI alto incorrecto. Un pico fisiológico real es ~2–4 bins de ancho.

### Decisión de diseño
SQI combinado = media geométrica de:
- **SQI_global**: fracción de energía HPS en el pico interpolado vs. suma total (métrica anterior)
- **SQI_local**: prominencia del pico sobre el floor local (ventana ±W bins alrededor del pico)

`SQI = √(SQI_global × SQI_local)` — ambas métricas deben ser altas simultáneamente.

### Parámetros nuevos (constexpr, no expuestos en $SET por ahora)
- `hr3_sqi_local_w = 5` bins (±0.49 Hz a 50 Hz/512 bins)
- `hr3_sqi_local_ratio = 10.0` (ratio pico/floor que mapea a SQI_local = 1)

### Corrección de memoria
Rango HR actualizado en project_mow_afe4490_spec.md: 25–300 BPM → **40–260 BPM** (guard band 37–263 BPM). El valor 25–300 estaba desactualizado.

### Cambios (`incunest_afe4490.cpp`)
- 2 nuevas constexpr en namespace anónimo: `hr3_sqi_local_w`, `hr3_sqi_local_ratio`
- `_compute_hr3()`: bloque SQI reemplazado — `sqi_global` (anterior) + `sqi_local` (nuevo bucle ±W bins) → `sqrtf(sqi_global * sqi_local)`

### Cambios (`incunest_afe4490_spec.md`)
- §5.4 SQI: reescrito con Global SQI + Local SQI + Combined SQI documentados
- Changelog: v0.28 añadido

---

## Sesión 2026-05-29d — HR3 true-peak validation (v0.28 fix)

### Problema identificado por Alex
El algoritmo HR3 fallaba con artefactos de movimiento / sin dedo porque:
- La energía real estaba en bajas frecuencias (por debajo del rango de búsqueda)
- La cola de ese lóbulo entraba en el rango de búsqueda con máximo en `search_min`
- El algoritmo lo aceptaba como "pico" → HR y SQI incorrectamente altos

Error fundamental: el código buscaba el máximo dentro del rango pero no verificaba que fuera un máximo local real. Un máximo en el borde del rango es la rampa de entrada de un lóbulo externo, no un pico.

### Problema secundario identificado (pendiente fix)
La media geométrica `sqrt(sqi_global * sqi_local)` hace que el SQI persista más alto que antes al quitar el dedo: `sqi_local` se mantiene en 1.0 (el pico antiguo sigue siendo localmente afilado frente al ruido) mientras `sqi_global` baja → `sqrt(0.4 × 1.0) = 0.63 > 0.4`. Pendiente cambiar a `min(sqi_global, sqi_local)`.

### Fix implementado
Validación de pico real antes de la interpolación parabólica: se evalúan `hps_at(peak_bin-1)` y `hps_at(peak_bin+1)` **sin restricción de rango de búsqueda**. Si cualquier vecino supera al pico → SQI=0, HR sin actualizar, return inmediato.

### Cambios (`incunest_afe4490.cpp`)
- Bloque "True-peak validation" insertado tras la detección del peak_bin y antes de la interpolación parabólica (~l.1949)

### Cambios (`incunest_afe4490_spec.md`)
- §5.4: párrafo de validación de pico real añadido antes de la descripción de SQI
- Changelog v0.28: líneas adicionales documentando el fix

---

## Sesión 2026-05-29e — HR3 true-peak validation fix de compilación

### Contexto
El bloque de validación de pico real de la sesión 2026-05-29d fallaba a compilar porque usaba `hps_at`, un lambda definido más adelante (dentro del bloque `if (hr3 >= _hr_min_bpm...)`).

### Fix
Lambda renombrado a `hps_neighbor` e inlineado directamente en el bloque de validación, antes de la interpolación parabólica. Funcionalmente idéntico.

### Cambios (`incunest_afe4490.cpp`)
- Bloque true-peak validation: `hps_at` → lambda local `hps_neighbor` inlineado

---

## Sesión 2026-05-29f — HR3 refactor: hps_at único

### Contexto
El código tenía el cálculo HPS duplicado tres veces: en el bucle de búsqueda (inlineado), en `hps_neighbor` (validación) y en `hps_at` (SQI). Alex lo señaló correctamente.

### Fix
Lambda `hps_at` definido una sola vez antes del bucle, reutilizado en:
1. Bucle de búsqueda del pico (reemplaza las tres líneas p1/p2/p3 inlineadas)
2. Validación true-peak (`hps_at(peak_bin-1)` y `hps_at(peak_bin+1)`)
3. Interpolación parabólica HPS (ya usaba `hps_at`)

### Cambios (`incunest_afe4490.cpp`)
- Lambda `hps_at` movido antes del bucle HPS (antes era dentro del bloque `if hr3 >= _hr_min_bpm`)
- Bucle de búsqueda simplificado: `float hps = hps_at(k)`
- Bloque de validación simplificado: dos llamadas directas a `hps_at`
- Lambda `hps_at` duplicado dentro del bloque SQI eliminado

---

## Sesión 2026-05-29g — HR3 SQI simplificado: solo prominencia local

### Decisión
Eliminar el SQI global (fracción sobre el rango de búsqueda completo) y dejar únicamente la prominencia local. Razones:
- El SQI global era la métrica que ya fallaba antes de v0.28
- La media geométrica hacía que sqi_local=1 mantuviera el SQI alto cuando sqi_global bajaba
- La combinación añadía complejidad sin resolver el problema raíz

### Cambios (`incunest_afe4490.cpp`)
- `hps_sum` eliminado del bucle de búsqueda
- Bloque "Global SQI" eliminado completamente
- Bloque "Local SQI" es ahora el único SQI:
  - Ventana ±hr3_sqi_local_w bins alrededor del pico
  - Restricción `j < search_min` eliminada — bins fuera del rango de búsqueda cuentan en el floor (un hump de baja frecuencia justo debajo del rango sube el floor y baja el SQI correctamente)
  - Fallback `local_floor=0` → `sqi=0` (conservador, antes era 1.0)
- `sqrtf(sqi_global * sqi_local)` → `_hr3_sqi_result` directo desde local

### Pendiente
Actualizar spec §5.4 y HR3TestCalc en pulsenest_lab.py para reflejar el nuevo SQI.

---

## Sesión 2026-05-29h — HR3: eliminación guarda redundante

### Decisión
Eliminar el bloque de guarda en líneas 1951-1954 de `_compute_hr3()`:
```cpp
if (peak_bin < 1 || peak_bin >= nyquist - 1 || peak_hps <= 0.0f) {
    _hr3_sqi_result = 0.0f;
    return;
}
```
Análisis de redundancia:
- `peak_bin < 1`: imposible — `search_min >= 1` garantizado
- `peak_bin >= nyquist - 1`: imposible — `search_max <= nyquist/3`
- `peak_hps <= 0.0f`: ya cubierto implícitamente por la validación true-peak que le sigue

### Cambios (`incunest_afe4490.cpp`)
- Bloque if (4 líneas) eliminado; comentario de sección true-peak queda inmediatamente después del bucle HPS.

### Estado
Upload pendiente (COM15 no disponible en el momento).

---

## Sesión 2026-05-29i — HR3 true-peak validation ampliada a ±W bins (v0.29)

### Decisión
Ampliar la validación true-peak de ±1 bin a ±`hr3_peak_valid_w` bins (valor inicial 5, igual a `hr3_sqi_local_w` pero constante separada). Razones:
- ±1 solo garantiza un máximo local matemático mínimo (1 muestra)
- Una rampa ascendente puede pasar el check ±1 si el pico está en la cima de la pendiente
- Con ±5 bins (±0.49 Hz, ±29 BPM), la pendiente de un hump de baja frecuencia será rechazada

### Ventajas/inconvenientes evaluados
- **Ventaja:** detecta pendientes y boundary maxima más robustamente
- **Ventaja:** consistente con la ventana SQI (mismo ancho)
- **Inconveniente:** si dos HR están muy próximas en frecuencia, podría rechazar un pico válido (aceptado como riesgo menor dada la resolución 0.098 Hz/bin)
- **Decisión:** constante separada `hr3_peak_valid_w` para poder tunar independientemente de `hr3_sqi_local_w`

### Cambios (`incunest_afe4490.cpp`)
- Nueva constexpr `hr3_peak_valid_w = 5`
- True-peak validation reemplazada: loop sobre `[peak_bin−W, peak_bin+W]`, skipa `peak_bin` y bins fuera de `[1, nyquist)`. Si cualquier bin ≥ `peak_hps` → `_hr3_sqi_result = 0.0f; return`

### Cambios (`incunest_afe4490_spec.md`)
- Header bumpeado a v0.29
- §5.4 true-peak validation reescrita con semántica ±W
- §5.4 SQI: global SQI y geometric mean eliminados (ya eliminados en código en sesión g, spec no se había actualizado); solo local prominence documenta
- Changelog v0.29 añadido

---

## Sesión 2026-05-29j — HR3TestWindow: botón PY PLOTS

### Decisión
Añadir botón toggle "PY PLOTS" en el toolbar de HR3TestWindow para mostrar/ocultar las curvas calculadas por el script Python (HR3 py, SQI py — amarillas) en las gráficas 3 y 4. Permite ver solo las curvas del firmware (verdes) para comparación directa.

### Cambios (`pulsenest_lab.py`)
- Botón checkable `_btn_py_plots` añadido en toolbar entre PAUSE y addStretch
- Activo por defecto (PY PLOTS visibles al arrancar)
- Estilo: amarillo cuando activo, gris apagado cuando inactivo
- Método `_toggle_py_plots()`: llama `setVisible()` en `curve_hr_py` y `curve_sqi_py`
- Tooltip con `_make_tooltip()`

---

## Sesión 2026-05-29k — SIGNAL STATS: par de celdas hermanas en gris

### Decisión
Marcar con el mismo color de fondo gris (#3C3C3C) dos celdas conceptualmente equivalentes en la tabla SIGNAL STATS:
- (fila IR_Sub=4, col % SD/Mean=1)
- (fila PI=10, col Mean=2)
Razón: IR_Sub % SD/Mean ≈ AC/DC ratio ≈ PI. Son la misma magnitud física expresada de formas distintas.

### Cambios (`pulsenest_lab.py`)
- Dos llamadas `setBackground(_GRAY_PAIR)` añadidas tras el bucle de inicialización de `stats_table`
- Constante local `_GRAY_PAIR = QtGui.QColor("#3C3C3C")`

---

## Sesión 2026-05-29l — HR3 SQI v0.30: P[k] en vez de HPS para prominencia local

### Diagnóstico
El SQI siempre daba 1 o 0 (binario). Causa: HPS = P[k]·P[2k]·P[3k] amplifica diferencias cúbicamente. Un pico que es 10× sus vecinos en P[k] es 10³× en HPS, saturando el ratio >> hr3_sqi_local_ratio=10 para cualquier señal real → SQI=1 siempre. La validación true-peak filtraba el SQI=0. Sin rango intermedio posible.

### Decisión
Usar P[k] (espectro de potencia del bin fundamental) en vez de HPS para el cálculo de prominencia local del SQI. P[k] tiene rango dinámico lineal y da valores intermedios útiles para señales débiles o ruidosas.

### Cambios (`incunest_afe4490.cpp`)
- `hr3_sqi_local_ratio`: 10.0 → 100.0
- Bloque SQI: HPS parabolic interp (hps_p, hps_n, hps_denom, hps_interp) eliminado
- `p_interp` = interpolación parabólica de P[k] usando yp/y0/yn/denom ya calculados → coste extra cero
- Loop floor: `hps_at(j)` → inline `_hr3_fft[2j]²+_hr3_fft[2j+1]²`

### Cambios (`incunest_afe4490_spec.md`)
- Header bumpeado a v0.30
- §5.4 SQI reescrito: formula P[k], p_interp, hr3_sqi_local_ratio=100
- Justificación "por qué P[k] y no HPS" documentada
- Changelog v0.30 añadido

## Sesión 2026-05-29m — HR3 SQI v0.31: two-bin HPS fraction

### Contexto
Continuación de sesión anterior (compactada). El SQI v0.30 (P[k] local prominence) llegaba como máximo a 0.19 porque la ventana Hann distribuye la energía en 3 bins con pesos 0.5, 0.25, 0.25, dando P[k]/P[k±1] ≈ 4, no los 10³ asumidos inicialmente. La métrica seguía siendo esencialmente binaria.

### Decisiones tomadas

**HR3 SQI v0.31 — two-bin HPS fraction:**
- La señal PPG fuera de bin exacto reparte energía HPS entre dos bins adyacentes (b1=peak_bin, b2=b_other en dirección de delta).
- Solución: `hps_num = hps(peak_bin) + hps(b_other)` — ambos bins escalan igual ante variación de alineación → ratio independiente de posición fraccionaria.
- Denominador: suma de HPS en ventana local `[min(b1,b2)-W, max(b1,b2)+W]` con W=hr3_sqi_local_w=5 bins (~±0.49 Hz). Excluye armónicos lejanos.
- `baseline = 2/n_win` → SQI=0 si distribución uniforme, SQI=1 si toda energía en los dos bins pico.
- `SQI = clamp((fraction-baseline)/(1-baseline), 0, 1)`
- Eliminado `hr3_sqi_local_ratio`.

**Por qué HPS y no P[k] para este ratio:**
- HPS suprime armónicos de subarmónicos (artefactos de movimiento a 0.5×, 0.33× la frecuencia PPG).
- La amplificación cúbica se controla con el denominador de ventana local, no se satura.

**Independencia de bin:** off-bin split cancela en el ratio num/den porque ambos escalan igual.

### Cambios (`incunest_afe4490.cpp`)
- Bloque SQI reescrito: eliminada lógica P[k] (p_interp, local_floor, ratio, hr3_sqi_local_ratio)
- Nuevo bloque: b_other, hps_b_other, hps_num, ventana [b_lo,b_hi], hps_win, n_win, fraction, baseline
- `hr3_sqi_local_ratio` eliminado de constexpr en sesión anterior; ya no referenciado en código

### Cambios (`incunest_afe4490_spec.md`)
- Header bumpeado a v0.31
- §5.4 SQI reescrito: fórmula two-bin HPS fraction, explicación de bin-independence, por qué HPS, por qué ventana local
- Changelog v0.31 añadido

## Sesión 2026-05-29n — HR3TEST: color por SQI en plot HR3 fw

### Contexto
En el tercer gráfico de HR3TestWindow, el plot "HR3 fw" tiene un único color verde (#00CC66). Se quiere distinguir visualmente los puntos de baja calidad (SQI < 0.9) con un verde más oscuro, sin perder la continuidad de la curva.

### Decisión técnica
Dos curvas superpuestas sobre el mismo plot, con enmascaramiento por NaN:
- `curve_hr_fw` (verde normal #00CC66): puntos donde SQI ≥ 0.9
- `curve_hr_fw_lo` (verde oscuro #2D6E47): puntos donde SQI < 0.9
- En cada curva, los puntos que no le corresponden se sustituyen por `np.nan` → pyqtgraph no dibuja ese segmento → la línea se interrumpe y el color cambia sin artefactos visuales.
- Umbral en constante de clase: `_SQI_ALERT = 0.9`

### Cambios (`pulsenest_lab.py`)
- `FW_LO_PEN = pg.mkPen('#2D6E47', width=2)` añadido en `HR3TestWindow.__init__`
- `self.curve_hr_fw_lo` creado tras `curve_hr_fw`, antes de `curve_hr_py`, con nombre "HR3 fw (SQI<0.9)"
- `_reset_plots`: `curve_hr_fw_lo` añadido a la lista de curvas a limpiar
- `_SQI_ALERT = 0.9` definido como atributo de clase
- `_refresh_hr_plots`: `hi_mask = sqi_fw >= _SQI_ALERT`; `curve_hr_fw` recibe `np.where(hi_mask, hr_fw, nan)`; `curve_hr_fw_lo` recibe `np.where(~hi_mask, hr_fw, nan)`

## Sesión 2026-05-29o — incunest_afe4490: renombrado b1/b2 en SQI _compute_hr3()

### Contexto
El bloque SQI de v0.31 usaba `peak_bin` y `b_other` en vez de `b1`/`b2` como el usuario había propuesto. Corrección de nomenclatura.

### Cambios (`incunest_afe4490.cpp`)
- `b_other` → `b2`, `hps_b_other` → `hps_b2`
- `b1 = peak_bin` definido explícitamente para claridad
- Comentarios del bloque SQI actualizados para usar b1/b2 consistentemente
- Sin cambio de comportamiento — puramente cosmético

## Sesión 2026-05-29p — incunest_afe4490: fix b1/b2 con floor/ceil

### Contexto
La sesión anterior usaba `b2 = b1 + (delta >= 0 ? 1 : -1)`, lo que podía dar b2 < b1 cuando delta < 0 — nomenclatura confusa y contraria a la propuesta original del usuario.

### Decisión
- `b1 = floor(peak_bin + delta)` — bin inferior de la fracción, siempre ≤ b2
- `b2 = b1 + 1` — bin superior, siempre b1 < b2
- Ventana `[b1-W, b2+W]` siempre bien definida
- `hps_b1`/`hps_b2` reutilizan `peak_hps` cuando coinciden con `peak_bin`

### Cambios (`incunest_afe4490.cpp`)
- Bloque SQI en `_compute_hr3()`: redefinición de b1/b2 con `floorf()`
- Comentarios actualizados: "b1=floor, b2=ceil of fractional peak bin"

## Sesión 2026-05-29q — incunest_afe4490: fix comentario b1/b2 en SQI

### Cambios (`incunest_afe4490.cpp`)
- Líneas 1979-1981: comentario corregido de "b1=peak_bin, b2=adjacent in delta direction" a "b1=floor(peak_bin+delta), b2=b1+1" — coherente con la implementación actual

## Sesión 2026-05-30a — AGC literatura + PPG-PI + versión librería v0.31

### Búsqueda AGC literatura
- Confirmado: TI no provee AGC para AFE4490/AFE4404 — el usuario lo implementa en software.
- App Note SBAA401 (TI): AGC para TLV320ADCx140 (audio ADC con PGA hardware). No aplica directamente pero los patrones son transferibles: attack/release asimétrico, debounce, histéresis, noise threshold.
- IEEE ICASSP 2020: AGC con SQM multidimensional para PPG de muñeca → >50% ahorro LED. Confirma que gate por fracción de muestras inválidas es la práctica correcta (ya en nuestro diseño).
- Conclusión: diseño HGAC acordado en 2026-05-21 está alineado con estado del arte. Brecha identificada: no distingue velocidad de respuesta asimétrica (attack rápido vs release lento).

### Nueva tarea: PPG-PI espectral
- Definición: `PPG-PI = AC_pulsatile / DC × 100%` donde `AC_pulsatile` = energía en armónicos f_HR únicamente.
- La señal PPG pulsatil se define formalmente como un tren de pulsos periódico con energía concentrada en f_HR y armónicos — análogo a pitch detection en voz/música.
- Concepto análogo en voz: HNR (Harmonic-to-Noise Ratio, Boersma 1993). Diferencia: PPG-PI usa DC como denominador para mantener escala física de perfusión.
- HPS de HR3 ya localiza los picos armónicos — reutilizable para PPG-PI sin coste adicional significativo.
- No existe definición publicada con exactamente esta forma. Archivado en `project_spectral_pi_task.md`.

### Propuesta implementación PPG-PI en pulsenest_lab.py
- Cambio mínimo en `HRFFTCalc`: añadir `last_signal_power_abs` y `last_buf_len`.
- Nueva clase `PPGPICalc` (~60 líneas): DC IIR tracker + energía armónica de FFT → `ppg_pi` y `pi_std`.
- Display recomendado: `SpO2TestWindow` (fila adicional + plot PPG-PI vs PI_std).
- Pendiente de implementar.

### Versión librería actualizada a v0.31
- `incunest_afe4490.cpp` línea 2: v0.20 → v0.31
- `incunest_afe4490.h` comentario: v0.25 → v0.31
- `incunest_afe4490.h` define: `INCUNEST_AFE4490_VERSION "0.27"` → `"0.31"`

## Sesión 2026-05-30b — Sincronización versión librería + preguntas Claude Code

### Sincronización versión v0.31 en GitHub
- `incunest_afe4490` repo local tenía v0.31 pero GitHub mostraba v0.20 (no se había pusheado).
- Push realizado desde `C:\PRJ\MOW\incunest_afe4490` (repo separado de PulseNest).
- Detectado que `incunest_afe4490_platform_stub.h` aún tenía v0.18 → actualizado a v0.31 y pusheado.
- `examples/basic/main.cpp` dejado en v0.18 intencionadamente: indica la versión con la que se escribió el ejemplo, no la versión actual de la librería.

### Ficheros con número de versión en incunest_afe4490
| Fichero | Línea | Rol |
|---------|-------|-----|
| `incunest_afe4490.cpp` | 2 | comentario cabecera |
| `incunest_afe4490.h` | 4 | comentario cabecera |
| `incunest_afe4490.h` | 9 | `#define INCUNEST_AFE4490_VERSION` (usado en código) |
| `incunest_afe4490_platform_stub.h` | 3 | comentario cabecera stub offline |

### Preguntas sobre Claude Code (sin impacto en código)
- Rewind: rebobina la conversación (árbol de mensajes por parentUuid en el .jsonl), no deshace cambios en ficheros/git.
- Historial conversación: `C:\Users\alexc\.claude\projects\C--PRJ-MOW-PulseNest\<uuid>.jsonl` — formato JSON Lines, una entrada por mensaje.

## Sesión 2026-05-30c — Política de versioning librería formalizada

### Decisiones de diseño
- `incunest_afe4490_platform_stub.h` y `examples/basic/main.cpp` son ficheros auxiliares, no API pública, pero reflejan la versión fija de la librería en su comentario de cabecera.
- Descartado el enfoque "compatible con >= vX.XX" por difícil de mantener honestamente.
- `examples/basic/main.cpp` actualizado de v0.18 → v0.31 y pusheado (commit `d831a20`).

### Política formalizada (guardada en memory/project_library_versioning.md)
- La versión sube solo ante cambio funcional (algoritmo, API, comportamiento, bug fix, spec significativa).
- El bump es un commit atómico que incluye: `.cpp`, `.h`, `platform_stub.h`, `examples/basic/main.cpp`, `incunest_afe4490_spec.md` (cabecera + changelog), y ficheros de memoria relevantes.
- El análisis de `platform_stub.h` y `examples/basic/main.cpp` se lanza en el momento del version bump, antes de cerrar el commit — automático, sin preguntar al usuario.

## Sesión 2026-05-30d — Fix lint errors pulsenest_lab.py

### Cambios en código
- `pulsenest_lab.py`: eliminadas 4 variables asignadas pero nunca usadas (pyflakes):
  - `DLT_PEN` — pen HR2 plot definido pero no usado
  - `ir` — lectura `data_ir_sub[i]` en bucle HR3 update no consumida
  - `_hdr_style` ×2 — string CSS preparado pero styling aplicado directamente via `setBackground`/`setForeground`

### C++ cppcheck (pio check, exit 0, sin cambios en código)
- V15: 3 warnings reales (`cstyleCast` ×2 en main.cpp:40/52, `constVariablePointer` en main.cpp:596) + 2 falsos positivos Arduino (`setup`/`loop` never used — cppcheck no conoce el framework)
- V16: sin warnings
- Pendiente: decidir si corregir los 3 warnings reales de main.cpp

## Sesión 2026-05-30e — AFESweepTestWindow: probe_state check + RSQM en CSV

### Cambios en código (`pulsenest_lab.py`)

#### CSV — 51 columnas (antes 42)
- Columnas 1–2 (nuevas, al inicio): `probe_state_expected`, `probe_state_check`
- Columnas 3–44: sin cambios (label, datetime, LED1mA…, OT1, OT2)
- Columnas 45–51 (nuevas, al final): `rsqi_ok_pct`, `diag_code_mean`, `diag_code_min`, `diag_code_max`, `probe_state_fw_mean`, `probe_state_fw_min`, `probe_state_fw_max`

#### UI — Sweep Settings
- Nuevo `QComboBox` "Expected probe_state": `PROBE_DISCONNECTED (0)`, `PROBE_NOT_APPLIED (1)`, `PROBE_APPLIED (2)`. Valores del enum `ProbeState` en `incunest_afe4490.h`. Persistido en QSettings con default `PROBE_APPLIED`.

#### UI — Control
- Banner visual (`QLabel` grande) encima de la barra de progreso:
  - Idle: gris neutro
  - Sweep OK: verde `✓ PROBE STATE OK (N combos checked)`
  - Sweep NOT OK: rojo `⚠ PROBE MISMATCH — N combos`
  - Al finalizar: texto definitivo con resultado global, color persistente

#### Lógica check
- Por combo: si **algún** sample tiene `probe_state_fw ≠ expected` → `"NOT OK"`, si todos coinciden → `"OK"`
- Contador `_probe_mismatch_count` (reset en `_start_sweep`), incrementado por cada combo NOT OK
- Banner actualizado tras cada `_write_row()`

#### `feed_sample()`
- Firma ampliada: `feed_sample(red, ir, red_amb, ir_amb, red_sub, ir_sub, rsqi, diag_code, probe_state_fw)`
- Buffer `_buf` ampliado con claves `"RSQI"`, `"DIAG_CODE"`, `"PROBE_STATE_FW"`

#### PPGMonitor
- Llamada a `feed_sample()` pasa `data_rsqi[-1]`, `data_diag_code[-1]`, `data_probe_state[-1]` (ya disponibles tras el parseo del frame `$M1`)

### Decisiones de diseño
- El check es estricto: basta 1 muestra discrepante para marcar el combo como NOT OK
- `probe_state_expected` default = `PROBE_APPLIED` (caso de uso más habitual)
- Para diag_code y probe_state_fw: mean/min/max (no moda) por petición del usuario

---

## Sesión 2026-05-31a — SIGNAL STATS: reordenación de columnas + sub-header ADZ

### Ficheros modificados
- `pulsenest_lab.py`

### Cambios realizados

#### 1. Reordenación de columnas en la tabla SIGNAL STATS
Las columnas V_TIA y V_ADC se han movido de las posiciones 7-8 (últimas) a las posiciones 1-2 (justo después de Signal).

Nuevo orden de columnas (0-indexed):
- 0: Signal
- 1: V_TIA (era 7)
- 2: V_ADC (era 8)
- 3: % SD/Mean (era 1)
- 4: Mean (era 2)
- 5: SD (era 3)
- 6: Max-Min (era 4)
- 7: Min (era 5)
- 8: Max (era 6)

Actualizaciones asociadas:
- Header labels reordenados
- Font pequeña del header: col 1 → col 3 (% SD/Mean)
- `_STATS_MEAN_COL` (clase) y `_MEAN_COL` (local init): 2 → 4
- `_update_stats_table`: snr col 1→3, `enumerate(start=2)`→`start=4`, V_TIA/V_ADC cols `(7,8)`→`(1,2)`
- Gray pair backgrounds: `(4,1)→(4,3)` (IR_Sub/% SD/Mean), `(10,2)→(11,4)` (PI/Mean, con offset sub-header)
- Tooltips V_TIA/V_ADC: cols 7,8 → 1,2
- SpO2_R tooltip override: `(9,1)→(10,3)` (con offset sub-header)

#### 2. Fila sub-header entre IR_Sub y RED_Sub
Se inserta una fila visualmente similar al header de la tabla en la posición tbl_row=5 (entre IR_Sub y RED_Sub).

Contenido:
`Signal | ADZ | % ADZ/Mean | % SD/Mean | Mean | SD | Max-Min | Min | Max`

Donde ADZ = Average Distance from Zero. Las columnas ADZ y % ADZ/Mean sustituyen V_TIA y V_ADC en esta sub-cabecera, anticipando métricas específicas para las señales inferiores.

Implementación:
- Tabla: `len(_STATS_SIGNALS)` → `len(_STATS_SIGNALS) + 1` filas (22 → 23 filas total)
- Constante `_SUBHDR_ROW = 5`
- Señales con sig_idx ≥ 5 usan `tbl_row = sig_idx + 1` (offset por el sub-header)
- Señales con sig_idx < 5 usan `tbl_row = sig_idx` (sin offset)
- Variable de loop: `row` → `sig_idx` + `tbl_row` para separar índice de señal de índice de fila tabla
- ProbeState (sig_idx=21, tbl_row=22): `len(_STATS_SIGNALS) - 1` → `len(_STATS_SIGNALS)`
- Estilo sub-header: fondo `#1E1E2E`, foreground `#AAAAAA`, bold, alineación izquierda en col 0

### Decisiones de diseño
- V_TIA/V_ADC al inicio porque son los parámetros de calidad HW más relevantes visualmente
- Sub-header como separador visual y adelanto semántico de las métricas ADZ que se añadirán para las señales procesadas (RED_Sub, PPGdisp, etc.) en sesiones posteriores
- La sub-header row (tbl_row=5) no es tocada por `_update_stats_table` — es puramente estática

---

## Sesión 2026-05-31b — SIGNAL STATS: fix tamaño fuente sub-header row (2 iteraciones)

### Ficheros modificados
- `pulsenest_lab.py`

### Contexto
El PC se reinició durante la sesión anterior. Al recuperar el estado, se detectó que la fila sub-header usaba `_hdr_font_normal` (pixelSize=33) y `_hdr_font_small` (pixelSize=9) — fuentes diseñadas para el header horizontal de la tabla, no para filas de contenido.

### Cambio realizado
Sub-header row: fuente cambiada de `_hdr_font_normal`/`_hdr_font_small` a `QFont()` por defecto con bold.

Antes:
```python
_subhdr_fn_norm = QtGui.QFont(_hdr_font_normal)   # pixelSize=33
_subhdr_fn_norm.setBold(True)
_subhdr_fn_small = QtGui.QFont(_hdr_font_small)   # pixelSize=9
_subhdr_fn_small.setBold(True)
it.setFont(_subhdr_fn_small if col == 3 else _subhdr_fn_norm)
```

Después:
```python
_subhdr_fn = QtGui.QFont()   # tamaño por defecto del widget
_subhdr_fn.setBold(True)
it.setFont(_subhdr_fn)
```

### Decisión de diseño (iteración 1 — incorrecta)
`QFont()` usa la fuente por defecto de la aplicación, que puede diferir de la fuente heredada por la tabla desde su stylesheet. El resultado visual seguía siendo diferente al de las filas normales.

### Iteración 2 — fix correcto
```python
_subhdr_fn = QtGui.QFont(self.stats_table.font())
_subhdr_fn.setBold(True)
```
`self.stats_table.font()` devuelve la fuente exacta que usa la tabla (incluyendo family y size del stylesheet), garantizando que el sub-header tenga el mismo tamaño que cualquier otra fila.

### Decisión de diseño
- Siempre usar `widget.font()` como base cuando se necesite la misma fuente que el widget, no `QFont()` bare

### Iteración 3 — fix correcto definitivo
Causa raíz identificada: `pixelSize=33` en el horizontal header se renderiza recortado por la altura de la sección del header (~24-30px). En las filas de datos (40px), ese mismo font renderiza a tamaño completo y aparece más grande.

Solución: usar la fuente del `horizontalHeaderItem(col)` + igualar la altura de la fila sub-header a la del header horizontal con un `QTimer.singleShot(0, ...)`:

```python
QtCore.QTimer.singleShot(
    0, lambda r=_SUBHDR_ROW: self.stats_table.setRowHeight(
        r, self.stats_table.horizontalHeader().height()))
```

El `singleShot(0)` se ejecuta tras el primer ciclo del event loop, cuando la altura del header ya está calculada por el layout.

### Iteración 4 — causa raíz identificada definitivamente
A 150% DPI en Windows, `setPixelSize(33)` son 33 píxeles físicos = 22 píxeles lógicos, menor que los 28px CSS del stylesheet de datos. En el horizontal header, el font se renderiza con esa altura física. En la fila de datos (40px), el stylesheet `QTableWidget { font-size: 28px }` prevalece sobre el Qt::FontRole cuando el font físico "cabe" menos que el stylesheet.

Solución aplicada:
1. Usar `_hdr_font_normal`/`_hdr_font_small` directamente (mismas instancias, sin copias intermedias que puedan perder el pixelSize)
2. Fijar la altura de la fila sub-header con `horizontalHeader().sizeHint().height()` (evaluado síncronamente, no en timer), de forma que el text físico tenga la misma altura disponible que en el header

```python
it.setFont(_hdr_font_small if col == 3 else _hdr_font_normal)
...
_hdr_h = self.stats_table.horizontalHeader().sizeHint().height()
self.stats_table.setRowHeight(_SUBHDR_ROW, _hdr_h if _hdr_h > 0 else 36)
```

### Iteración 3 — fix correcto definitivo
El usuario aclaró que "primera fila" significa la **fila de títulos de columna** (horizontal header), que es visualmente más pequeña que las filas de datos. La solución correcta es copiar la fuente directamente de cada `horizontalHeaderItem`:

```python
for col, lbl in enumerate(_subhdr_labels):
    it = QtWidgets.QTableWidgetItem(lbl)
    it.setBackground(_subhdr_bg)
    it.setForeground(_subhdr_fg)
    hdr_item = self.stats_table.horizontalHeaderItem(col)
    it.setFont(hdr_item.font() if hdr_item else self.stats_table.horizontalHeader().font())
    it.setTextAlignment(QtCore.Qt.AlignCenter)
```

Cada celda del sub-header usa exactamente la fuente del `horizontalHeaderItem` correspondiente (family + size + weight), garantizando que visualmente sea idéntica al header de columnas.

---

## Sesión 2026-06-01a — SIGNAL STATS: fix fuente sub-header row via delegate

### Ficheros modificados
- `pulsenest_lab.py`

### Problema
La fila sub-header (row 4) de `stats_table` se renderizaba con `font-size: 28px` del stylesheet de `QTableWidget`, ignorando el `setFont()` aplicado a los items. El stylesheet prevalece sobre el `Qt::FontRole` para items en el body de la tabla, por lo que intentos previos con `setFont(_hdr_font_normal/_hdr_font_small)` no tenían efecto visual.

### Causa raíz definitiva
`QStyledItemDelegate::paint()` llama internamente a `initStyleOption()`, que rellena `option.font` desde el widget (stylesheet CSS `font-size: 28px`), sobreescribiendo el FontRole del item. No hay forma de bypasear esto solo con `item.setFont()`.

### Solución implementada
Sobrescribir `initStyleOption()` en `_StatsHighlightDelegate` para inyectar el font del `horizontalHeaderItem(col)` cuando `index.row() == subhdr_row`, después de que el base class lo rellene con el font del stylesheet:

```python
def initStyleOption(self, option, index):
    super().initStyleOption(option, index)
    if index.row() == self._subhdr_row:
        hdr_item = self._tbl.horizontalHeaderItem(index.column())
        if hdr_item:
            option.font = hdr_item.font()
            option.fontMetrics = QtGui.QFontMetrics(option.font)
```

`_StatsHighlightDelegate.__init__` extendido con `tbl` y `subhdr_row`. Instanciación actualizada en `PPGMonitor.__init__` para pasar `self.stats_table` y `_SUBHDR_ROW`.

### Decisión de diseño
- `initStyleOption` es el punto correcto de intercepción: se ejecuta dentro del ciclo de pintado, después del stylesheet y antes del rendering final
- El font inyectado es exactamente `horizontalHeaderItem(col).font()` — mismo objeto que usa el header, garantizando identidad visual

---

## Sesión 2026-06-01b — SIGNAL STATS: fix fuente sub-header row (iteración 2)

### Ficheros modificados
- `pulsenest_lab.py`

### Problema con iteración anterior
El approach de sobrescribir `initStyleOption` no funcionó: `style->drawControl(CE_ItemViewItem)` con stylesheet activo re-deriva el font del widget (`QTableWidget { font-size: 28px }`) ignorando `option.font`.

### Solución implementada
Pintar la fila sub-header manualmente en `paint()`, evitando `drawControl` para esa fila:
- `painter.fillRect` con el color de fondo del item
- `painter.setFont(horizontalHeaderItem(col).font())` — font exacto del header
- `painter.setPen` con el color de foreground del item
- `painter.drawText` con el texto y alineación del item

Las demás filas siguen el camino normal (`super().paint()`). El método `initStyleOption` fue eliminado (no era efectivo).

### Decisión de diseño
- `painter.setFont()` directo es el único mecanismo garantizado para bypasear el stylesheet de Qt cuando se necesita un font específico en una celda concreta

---

## Sesión 2026-06-01c — SIGNAL STATS: eliminar it.setFont() muerto en sub-header

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
Eliminada línea `it.setFont(_hdr_font_small if col == 3 else _hdr_font_normal)` en el bucle de creación de items del sub-header (era código muerto de iteraciones anteriores). El delegate pinta la fila 4 manualmente usando `horizontalHeaderItem(col).font()` directamente sobre el painter, por lo que el FontRole del item nunca se lee.

---

## Sesión 2026-06-01d — SIGNAL STATS: fix fuente sub-header row (iteración 3)

### Ficheros modificados
- `pulsenest_lab.py`

### Causa raíz real
El font efectivo del header horizontal NO es `pixelSize(33)` de los items, sino `font-size: 28px` heredado del stylesheet `QTableWidget` (el `QHeaderView::section` no especifica `font-size`, por lo que hereda del padre). El bold viene de `font-weight: bold` en `QHeaderView::section`. Los `setPixelSize(33)` de los items son ignorados por el stylesheet.

Las celdas de datos también usan `font-size: 28px`. Ambos header y celdas tienen el mismo tamaño; la única diferencia visual del header es el bold.

### Por qué fallaban las iteraciones anteriores
- `it.setFont(pixelSize=33)`: tamaño incorrecto (stylesheet prevalece con 28px)
- `initStyleOption` override: `drawControl(CE_ItemViewItem)` re-aplica el stylesheet igualmente
- `painter.setFont(horizontalHeaderItem(col).font())`: el font del item (pixelSize=33) es el font programático ignorado por el stylesheet, no el font efectivo visual

### Solución implementada
En `paint()` del delegate, para la fila sub-header:
```python
font = QtGui.QFont(self._tbl.horizontalHeader().font())
font.setBold(True)
painter.setFont(font)
```
`horizontalHeader().font()` devuelve el font efectivo del widget QHeaderView (28px, resultado de la herencia del stylesheet). Con bold añadido, coincide exactamente con el rendering visual del header horizontal.

### Decisión de diseño
- Usar siempre `widget.font()` (font efectivo post-stylesheet) como referencia, no `item.font()` (font programático pre-stylesheet)

---

## Sesión 2026-06-01e — SIGNAL STATS: fix fuente sub-header row (iteración 4)

### Ficheros modificados
- `pulsenest_lab.py`

### Análisis definitivo de fonts
- **Header horizontal (secciones):** usa el font de los items (`pixelSize=33`, que QHeaderView sí respeta para pintar secciones) + `font-weight: bold` del stylesheet `QHeaderView::section`
- **Celdas de datos:** `font-size: 28px` del stylesheet `QTableWidget` (28 logical px = 42 physical px a 150% DPI)
- **`horizontalHeader().font()`** devuelve el font del widget QHeaderView (heredado 28px del stylesheet), NO el font de las secciones → incorrecto como referencia

### Confirmación: manual painting funciona
La iteración anterior (28px bold) fue visible para el usuario (sub-header más grande que el header), confirmando que el `paint()` manual bypasea el stylesheet correctamente.

### Solución aplicada
```python
hdr_item = self._tbl.horizontalHeaderItem(index.column())
font = QtGui.QFont(hdr_item.font() if hdr_item else self._tbl.horizontalHeader().font())
font.setBold(True)
painter.setFont(font)
```
`hdr_item.font()` = pixelSize=33 (mismo que usan las secciones del header horizontal) + bold añadido para coincidir con `font-weight: bold` del stylesheet del header.

---

## Sesión 2026-06-01f — SIGNAL STATS: sub-header font forzado a 22px bold

### Ficheros modificados
- `pulsenest_lab.py`

### Problema iteración anterior
`hdr_item.font()` en col 3 devuelve `pixelSize=9` (_hdr_font_small), haciendo la celda (3,4) enana.

### Solución
Font hardcodeado a 22px bold para toda la fila sub-header en el delegate:
```python
font = QtGui.QFont()
font.setPixelSize(22)
font.setBold(True)
painter.setFont(font)
```

---

## Sesión 2026-06-02a — ppg_disp, corrección spec hr_max_bpm, hotspot WiFi

### Ficheros modificados
- `incunest_afe4490/incunest_afe4490_spec.md`
- `include/wifi_config.h`

### Decisiones de diseño

**1. Nueva señal `ppg_disp` en AFE4490Data**
- Propósito: señal PPG exclusivamente para visualización/display
- Normalizada [0..1], PI-weighted: cuando PI está por debajo de un umbral crítico, el rango de normalización se reduce proporcionalmente
- Distinción explícita: `led1_aled1`/`led2_aled2` = señales de cálculo (SpO2, HR, HGAC); `ppg_disp` = display únicamente
- Añadida al diccionario de nomenclatura (`project_nomenclature_dictionary.md`) y a la spec

**2. Corrección grave en spec: hr_max_bpm**
- El código siempre tuvo `hr_max_bpm = 260 BPM` pero la spec decía 300 BPM
- Causa: Claude modificó la constante en `.cpp` en una sesión anterior sin actualizar la spec
- Correcciones aplicadas: hr_max_bpm 300→260, hr_search_max_bpm 303→263, hr1_refractory_s 0.2→0.185 s, textos narrativos y tablas en §5.2, §10, §13
- Regla formalizada en memoria: cambio de constante en código = spec actualizada en el mismo paso (son una sola tarea)
- Commit + push a GitHub: `987978d`

**3. WiFi hotspot**
- Añadida entrada `ALEXLAPTOP` / `192.168.137.1` en `wifi_config.h` para uso sin router
- IP `192.168.137.1` es el default del hotspot Windows; verificar con `ipconfig` si no conecta

---

## Sesión 2026-06-02b — WiFi hotspot, reordenación redes, label SSID en UI

### Ficheros modificados
- `include/wifi_config.h`
- `pulsenest_lab.py`

### Cambios

**wifi_config.h — reordenación de redes**
- ALEXLAPTOP movido al primer puesto (antes era el tercero)
- El firmware prueba las redes en orden → conectará al hotspot del portátil primero
- Útil para medidas en campo sin router

**pulsenest_lab.py — label WiFi SSID**
- Añadido `_lbl_wifi` en el sidebar, justo debajo de `btn_udp`
- Al arrancar: carga el último SSID conocido de QSettings como "WiFi: SSID (last)" en gris azulado
- Cuando llega `# WiFi connected [SSID]` por serial: actualiza a "WiFi: SSID" en azul (#44AAFF)
- El SSID se sigue guardando en QSettings para persistir entre sesiones

### Pendiente
- Upload firmware fallido (ESP32 no respondía en COM15 — problema de puerto, no de código)
- Pendiente compilar y flashear en próxima sesión

---

## Sesión 2026-06-03a — Rename variables RSQM en incunest_afe4490

### Ficheros modificados
- `incunest_afe4490.cpp`
- `incunest_afe4490.h`

### Cambios

**Cambio 1 — Eliminar aliases `s1`/`s2`**
- Eliminadas las variables locales `const float s1 = (float)led1_aled1` y `const float s2 = (float)led2_aled2` en `_update_rsqm()`
- Sustituidas en todos sus usos por `(float)led1_aled1` y `(float)led2_aled2` directamente (EMA, disconnected criterion, optical transmittance)

**Cambio 2 — Renombrar miembros EMA**
- `_rsqm_led1_sub` → `_rsqm_led1_aled1` (`.cpp` + `.h`)
- `_rsqm_led2_sub` → `_rsqm_led2_aled2` (`.cpp` + `.h`)
- Comentarios en `.h` y comentarios internos de `_update_rsqm()` actualizados en consecuencia

### Motivación
- `s1`/`s2` eran crípticos y ocultaban el origen del dato
- `_sub` no transmitía que la diferencia era LED−ALED; `_aled1`/`_aled2` lo hace explícito y simétrico con los nombres de parámetro de la función

---

## Sesión 2026-06-04c — Corrección credenciales WiFi hotspot

### Ficheros modificados
- `include/wifi_config.h`

### Cambio
SSID del hotspot del portátil corregido: `"ALEXLAPTOP"/"retuerta"` → `"in3wifi"/"12345678"`. IP target sin cambio (`192.168.137.1`).

---

## Sesión 2026-06-04b — WiFi modo completo: OTA flash + canal de comandos UDP

### Ficheros modificados
- `include/wifi_config.h` — añadido `UDP_CMD_PORT 5006`
- `src/main.cpp` — OTA web server + UDP command channel + refactor Cmd_Task
- `pulsenest_lab.py` — `send_cmd()`, `_is_cmd_ready()`, captura de ESP32 IP, reemplazo de `ser.write()`

### Motivación
Quitar el cable USB por completo. Con solo WiFi se necesitan dos cosas:
1. **OTA flash** — flashear sin cable
2. **Canal de comandos por UDP** — `$SET`, `$CFG?`, `$DIAG?` actualmente iban solo por Serial

El problema era que sin cable serial, `pulsenest_lab.py` no podía enviar comandos aunque los datos llegasen por UDP.

### Diseño de la solución

**Firmware (main.cpp):**
- `WebServer g_ota_server(80)` — página HTML de carga de `.bin`, activa tras WiFi. Sin dependencias CDN (autocontenido).
- `WiFiUDP g_cmd_udp` — escucha en `UDP_CMD_PORT=5006`, recibe comandos del PC.
- `WiFiUDP g_resp_udp` — envía respuestas ($CFG, $DIAG, $ERR, # comments) al PC en `UDP_TARGET_PORT=5005` (mismo canal que los datos).
- `g_resp_udp_mutex` — protege `g_resp_udp` ante acceso concurrente de `Incunest_Task` y `Cmd_Task`.
- `process_command()` — función extraída de `Cmd_Task`, usada por ambos caminos (Serial y UDP).
- `Serial_print_locked()` y `Serial_printf()` modificadas para también llamar `udp_send_line()` → las respuestas llegan a Python tanto por Serial como por UDP.
- `Cmd_Task` ampliada: sondea `g_cmd_udp.parsePacket()` y `g_ota_server.handleClient()` cada 50 ms.

**Python (pulsenest_lab.py):**
- `send_cmd(data: bytes)` — enruta a serial o UDP según `_active_transport`.
- `_is_cmd_ready()` — devuelve True si serial abierto **o** UDP activo con IP conocida.
- `_esp32_ip` — aprendida del primer paquete UDP recibido (sin configuración manual).
- `_cmd_udp_sock` — socket UDP para enviar comandos, creado lazy, cerrado en disconnect/closeEvent.
- 5 ocurrencias de `ser.write()` reemplazadas por `send_cmd()`, guards actualizados a `_is_cmd_ready()`.

### Decisiones de diseño
- **Separación de sockets:** `g_udp` (datos, batched, solo `Incunest_Task`) vs `g_resp_udp` (respuestas, unbatched, mutex, cualquier task). Sin interferencia entre ambos.
- **Respuestas también por UDP:** `Serial_print_locked`/`Serial_printf` añaden `udp_send_line()`. Python ya acepta todos los frames en el lector UDP, no solo `$M1`/`$M2`.
- **IP del ESP32 se aprende sola:** Python extrae `addr[0]` del primer paquete recibido. No requiere configuración adicional en `wifi_config.h`.
- **OTA y UDP coexisten:** WebServer usa TCP/80, streaming usa UDP/5005, comandos usan UDP/5006.
- **Compatibilidad total con modo serial:** cuando `_active_transport == "serial"`, todo funciona exactamente igual que antes.

---

## Sesión 2026-06-04a — Análisis rsqm_disconn_sub_mean con datos reales

### Ficheros modificados
- `incunest_afe4490.h` (solo comentario)

### Análisis
Revisión del umbral `rsqm_disconn_sub_mean = 5000.0f` contra datos reales del CSV `afe_sweep_test_2025-05-28.csv` (279 filas PROBE_DISCONNECTED):

| Canal | Peor caso muestra individual | Umbral | Margen |
|---|---|---|---|
| LED1_Sub | 3756 | 5000 | ×1.33 |
| LED2_Sub | 4013 | 5000 | ×1.25 |

### Decisión
- Umbral **mantenido en 5000** — el peor caso medido es 4013, margen ×1.25. Reducirlo sería arriesgado ante variación de unidad/temperatura del offset del TIA.
- Comentario en `.h` corregido: eliminado el engañoso `LED_Sub≈0`, reemplazado por peor caso real y margen efectivo.

---

## Sesión 2026-06-04d — Arquitectura IncuNest, librería compartida, V17, defaults librería

### Ficheros modificados
- `C:\PRJ\MOW\IncuNest\Firmware\motherBoard\platformio.ini`
- `C:\PRJ\MOW\IncuNest\Firmware\motherBoard\lib\incunest_afe4490` (symlink nuevo)
- `C:\PRJ\MOW\PulseNest\platformio.ini`
- `C:\PRJ\MOW\incunest_afe4490\incunest_afe4490.cpp`
- `C:\PRJ\MOW\incunest_afe4490\incunest_afe4490_spec.md`

### Trabajo realizado

**Arquitectura IncuNest documentada:**
- 2 MCUs: motherBoard (ESP32-S3, control/sensores/PID/SPO2) + Display_HMI (ESP32-S3 CrowPanel 7", LVGL/SquareLine)
- Comunicados vía carpeta `shared/` (alarm_ids, control_types, protocol)
- Display_HMI NO usa incunest_afe4490

**Librería compartida (tarea completada):**
- motherBoard usaba `incunest_afe4490.git#master` (GitHub). Migrado a symlink local igual que PulseNest.
- Symlink: `motherBoard/lib/incunest_afe4490` → `C:\PRJ\MOW\incunest_afe4490`
- Eliminada entrada GitHub de `lib_deps` en motherBoard/platformio.ini
- Commit `4f7c641` en IncuNest (rama `photo_vs_afe_tests`)

**Entorno V17 en PulseNest:**
- Añadido `[env:incunest_V17]` en platformio.ini (DRDY_PIN=17, igual que V16)
- Build OK: `.pio/build/incunest_V17/firmware.bin`
- Flash OTA sobre IncuNest motherBoard en 192.168.137.84 (login in3admin/savinglives, POST /update)
- Commit `4d0599e` en PulseNest

**Canal UDP de comandos verificado:**
- PulseNest V17 flasheado por OTA, recibe datos y acepta comandos por UDP sin cable serie

**Defaults librería incunest_afe4490 (pendiente commit/versión):**
- LED1/LED2 current: 11.7 mA → 20.0 mA (cuantiza a ~19.9 mA, código 34/256×150 mA)
- RF1/RF2 (TIA gain): RF_500K → RF_100K
- Spec actualizada: tabla de defaults, enum RF, tabla parámetros TX/RX, tabla de decisiones de registros

### Decisiones de diseño
- **OTA de IncuNest:** servidor HTTP en puerto 80, login puramente client-side (JS), `/update` accesible directamente con curl multipart.
- **V17 vs V16 en PulseNest:** pin DRDY idéntico (pin 17), mismos pines SPI/CS. Solo difiere `BOARD_VERSION` string.
- **Defaults 20 mA / RF_100K:** valor de test con sonda Medle. RF más bajo reduce ganancia pero evita saturación con LEDs más brillantes.

### Versión librería bumped a v0.32
- `incunest_afe4490.h`: v0.31 → v0.32 (`INCUNEST_AFE4490_VERSION`)
- `library.json`: 0.27.0 → 0.32.0
- `incunest_afe4490_spec.md`: título + entrada changelog v0.32
- Commit `65ef0d8` en incunest_afe4490 (rama master)

### Columna probe_state_calculated en AFESweepTestWindow CSV
- Nueva columna `probe_state_calculated` insertada en 2ª posición (tras `probe_state_expected`, antes de `probe_state_check`)
- Valor: moda de `PROBE_STATE_FW` durante la medición, convertida a string (`PROBE_DISCONNECTED`/`PROBE_NOT_APPLIED`/`PROBE_APPLIED`)
- Conteo de columnas actualizado: 51 → 52

---

## Sesión 2026-06-05a

### Tema: Corrección array stg2_rg_linear en incunest_afe4490

### Pregunta planteada
Relación entre RG (ohmios) y la amplificación asociada (ganancia lineal / dB) en la librería incunest_afe4490.

### Análisis
- El datasheet (Tabla 1, pág. 31) especifica los 5 ajustes de RG como resistencias físicas exactas: 100/150/200/300/400 kΩ.
- La ganancia lineal de Stage 2 = RG / Ri, donde Ri = 100 kΩ (fijo interno).
- Los valores exactos son: ×1, ×1.5, ×2, ×3, ×4.
- El array `stg2_rg_linear` en `incunest_afe4490.cpp` usaba valores calculados desde las etiquetas dB (10^(dB/20)), introduciendo un error innecesario:
  - 3.5 dB: 1.496 en lugar de 1.5
  - 9.5 dB: 2.985 en lugar de 3.0
  - 12 dB: 3.981 en lugar de 4.0

### Decisión
Corregir el array con los valores exactos del ratio RG/Ri según la Tabla 1 del datasheet.

### Cambios
- `incunest_afe4490.cpp:201`: `{ 1.0f, 1.496f, 2.0f, 2.985f, 3.981f }` → `{ 1.0f, 1.5f, 2.0f, 3.0f, 4.0f }`
- Comentario actualizado para referenciar la fuente: datasheet Tabla 1, RG/Ri.

---

## Sesión 2026-06-05b

### Tema: Derivación I_pleth desde ADC — corrección denominador ADC full-scale

### Preguntas planteadas
- Verificación de derivación de I_pleth desde la Equation 2 del datasheet (Steps 1-5).
- Denominador correcto para convertir counts ADC a voltaje: 2²¹ o 2²¹−1.

### Análisis / derivación validada
- Step 1: LED1 = 2×((I_pleth+I_amb)×RF/Ri − I_cancel)×RG ✓
- Step 2: ALED1 = 2×(I_amb×RF/Ri − I_cancel)×RG ✓
- Step 3: LED1_ALED1 = 2×I_pleth×(RF/Ri)×RG ✓ (I_amb e I_cancel se cancelan)
- Step 4: I_pleth = LED1_ALED1 × (Ri/(RF×RG×2)) ✓
- Step 5: I_pleth (mA) = LED1_ALED1 × (Ri/(RF×RG×2)) × 1.2/(2²¹−1), con RF/RG en kΩ ✓

### Decisión
- Claude inicialmente propuso corregir 2²¹−1 → 2²¹ (convención teórica de ADC).
- Alex corrigió: la Tabla 7 del datasheet especifica explícitamente que el código de fondo de escala positivo corresponde a +1.2 V → denominador correcto es **2²¹−1 = 2097151**.
- El datasheet manda sobre la convención teórica.

### Cambios
- `incunest_afe4490.cpp:73,76`: comentarios `2097152.0f` (= 2²¹) → `2097151.0f` (= 2²¹−1).
- Añadida nota en comentario: *"per datasheet Table 7, positive full-scale code maps to +1.2 V"*.

---

## Sesión 2026-06-06a

### Tema: Corrección _rg_lin en pulsenest_lab.py (OT1/OT2)

### Análisis
- OT1/OT2 en SIGNAL STATS: `OT = LED_Sub_mean / (LED_mA × RF_Ω × RG_linear)`
- `pulsenest_lab.py:7471` usaba los mismos valores aproximados de `_rg_lin` que ya se habían corregido en la librería (sesión 2026-06-05a).

### Cambios
- `pulsenest_lab.py:7471`: `_rg_lin` corregido con ratios exactos RG/Ri: `{1.496→1.5, 2.985→3.0, 3.981→4.0}`

---

## Sesión 2026-06-05a

### Ficheros modificados
- `src/main.cpp`
- `pulsenest_lab.py`

### RESET ESP32 por UDP
- Firmware: añadido `$RESET` en `process_command()` → llama `ESP.restart()` tras 50 ms
- Firmware: comentario del bloque Cmd_Task actualizado con `$RESET`
- Python: `_reset_esp32()` ampliado para enrutar por UDP (`send_cmd(b"$RESET\n")`) cuando `_active_transport == "udp"`, y por RTS/DTR (hard reset) cuando está en modo serial
- Log diferenciado: "soft-reset" (UDP) vs "hard-reset" (serial)

### Diferencias hard reset vs soft reset
- Hard (RTS/DTR): baja línea EN físicamente, limpia RAM completamente, requiere cable
- Soft ($RESET/ESP.restart()): reinicio software, RTC memory puede persistir, funciona sin cable
- Para uso normal son equivalentes; hard reset es más fiable ante bloqueos profundos del scheduler

### Color celdas destacadas en SIGNAL STATS
- `_GRAY_PAIR` (`#3C3C3C`) → `_ACCENT_PAIR` (`#5A1A4A`) — violeta rosáceo oscuro
- Celdas afectadas: IR_Sub/% SD/Mean (fila 5, col 3) y PI/Mean (fila 11, col 4)
- Estas dos celdas son conceptualmente equivalentes (IR_Sub % SD/Mean ≈ AC/DC ≈ PI)

---

## Sesión 2026-06-05c — Traza sweep en log_panel

### Ficheros modificados
- `pulsenest_lab.py`

### Contexto
- Alex investigando un fallo en el AFE Sweep Test (la librería funciona bien, el fallo está en el script)
- Localizado el flujo: `_start_sweep()` → `_apply_combo()` → `_send_set()` → `mm.send_cmd()`

### Cambio
- Añadida traza en `_apply_combo()` (tras el último `_send_set`) que escribe una línea al `log_panel` por cada combo aplicado
- Formato: `[SWEEP] {idx+1}/{total}  ch={ch}  led1=XmA  rf1=Y  rg1=Z  ...  ambdac=WµA`
- Solo muestra los parámetros del canal fijo que realmente se envían (valor ≥ 0), coherente con la lógica existente
- Usa `mm.log()` → aparece en el log_panel con timestamp y color "info" (#44AAFF)
- Sirve para verificar qué se envía exactamente al ESP32 en cada paso del sweep

---

## Sesión 2026-06-05d — CFG log en una línea + traza sweep

### Ficheros modificados
- `pulsenest_lab.py`

### _on_cfg_frame_received: log en una línea
- Sustituidas las 11 llamadas `self.log()` del bloque `log_lines` por una sola línea compacta
- Formato: `$CFG  board=X  sr=XHz  numav=X  led1=XmA  tia1=X  stg21=X  led2=XmA  tia2=X  stg22=X  ambdac=XµA  ch=X`
- Campos eliminados del log_panel (siguen en la ventana CFG): mac, range, ensepgain, cf, stage2en, flt, hr2/hr3, spo2 a/b

### Traza sweep en log_panel (sesión anterior, pendiente de verificar)
- Añadida traza en `_apply_combo()` → `mm.log(f"[SWEEP] {idx+1}/{total}  ch={ch}  ...")` 
- No aparece en el log_panel — causa no identificada aún. Pendiente investigar.

---

## Sesión 2026-06-05e — Fix: ts eliminado por error en _on_cfg_frame_received

### Ficheros modificados
- `pulsenest_lab.py`

### Bug introducido en sesión anterior
- Al condensar `log_lines` en una sola línea se eliminó `ts = datetime.datetime.now().strftime(...)` 
- `ts` seguía siendo referenciada en la variable `text` → `NameError` → `hw_config_window.update_from_cfg(kv)` nunca se ejecutaba → ventana HW CONFIG dejaba de actualizarse

### Fix
- Restaurada la línea `ts = ...` justo antes del nuevo `self.log(...)` compacto

---

## Sesión 2026-06-05f — Fix _ADC_FS_COUNTS

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
- `_ADC_FS_COUNTS = 2**21` → `2**21 - 1` (= 2097151)
- Motivo: la Tabla 7 del datasheet AFE4490 especifica que el código de fondo de escala positivo corresponde a +1.2 V → denominador correcto es 2²¹−1, no 2²¹
- Afecta al cálculo de V_ADC y V_TIA en SIGNAL STATS (filas IR, RED, IR_Amb, RED_Amb)
- Diferencia numérica mínima (~0.005%) pero es el valor correcto

---

## Sesión 2026-06-05g — Fix bug AMBDAC sweep test (UDP single-packet polling)

### Ficheros modificados
- `src/main.cpp`

### Bug
- `Cmd_Task` procesaba UN SOLO datagrama UDP por ciclo de 50 ms (`if (pkt > 0)`)
- `_apply_combo` envía 7 datagramas UDP en ráfaga (<1 ms): led1, tiagain1, stg21, led2, tiagain2, stg22, ambdac
- Con settle_ms=200ms (default), solo se procesaban 4 comandos antes de que empezara la medición
- AMBDAC es el 7º comando → llegaba tarde (t≈300ms) o se perdía si el buffer lwIP (<7 datagramas) se llenaba
- Por serial no había problema: `while (Serial.available())` drena todos los bytes en un ciclo

### Fix
- Cambiado `int pkt = ...; if (pkt > 0)` por `int pkt; while ((pkt = ...) > 0)` en el bloque UDP de Cmd_Task
- Ahora todos los datagramas acumulados se procesan en un único ciclo, igual que el path serie
- Requiere compilar y flashear firmware

---

## Sesión 2026-06-05h — Fix AMBDAC sweep test (lwIP UDP buffer overflow)

### Ficheros modificados
- `src/main.cpp`
- `pulsenest_lab.py`

### Análisis del bug
- El sweep envía 7 datagramas UDP en ráfaga (<10ms): led1, tiagain1, stg21, led2, tiagain2, stg22, **ambdac**
- El buffer lwIP del ESP32 tiene capacidad por defecto de 6 paquetes UDP
- Los 7 datagramas llegan antes de que Cmd_Task (ciclo 50ms) pueda consumir ninguno
- El 7º paquete (ambdac) se descarta por overflow → AMBDAC nunca cambia
- Por serial no hay problema: `while (Serial.available())` drena todos los bytes en un ciclo

### Fix 1 — firmware (main.cpp)
- Cambiado `if (pkt > 0)` por `while ((pkt = g_cmd_udp.parsePacket()) > 0)` en Cmd_Task
- Drena todos los datagramas acumulados en un solo ciclo (ayuda cuando los paquetes llegan espaciados)
- Flasheado por OTA (HTTP POST) a 192.168.137.135

### Fix 2 — script (pulsenest_lab.py)
- Añadido `time.sleep(0.060)` antes de `_send_set("ambdac", ...)` en `_apply_combo`, solo en UDP
- Da tiempo a Cmd_Task para drenar los 6 paquetes anteriores antes de que llegue AMBDAC
- 60ms por combo: negligible frente al ciclo settle(200ms) + medición(1000ms)

---

## Sesión 2026-06-05i — Settle time por defecto 200ms → 500ms

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
- Settle time default: 200ms → 500ms
- Razonamiento: con el sleep de 60ms (UDP) + latencia Cmd_Task (50ms), AMBDAC se aplica ~110ms después de `_apply_combo`. Con 500ms settle, quedan ~390ms de estabilización limpia tras AMBDAC.
- Tooltip actualizado explicando el timing UDP

---

## Sesión 2026-06-05j — Columnas V_TIA / V_ADC en CSV del sweep test

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
- Añadidas 8 columnas al CSV del sweep test: `V_TIA_mean`, `V_TIA_std`, `V_TIA_min`, `V_TIA_max`, `V_ADC_mean`, `V_ADC_std`, `V_ADC_min`, `V_ADC_max`
- Calculadas en `_write_row` a partir del buffer de samples crudos del canal barrido (`_buf["IR"]` para LED1, `_buf["RED"]` para LED2)
- Fórmula: `V_ADC = sample / (2²¹−1) × 1.2V` ; `V_TIA = (V_ADC / (2×RG) + amb_µA×1e-6) × 100kΩ`
- Parámetros: RG del combo activo (STG2_GAINS[rg] → STG2_RG_OHM), AMBDAC del combo
- `_CSV_HEADER` actualizado: 52 → 60 columnas

---

## Sesión 2026-06-05k — Multiplicar columnas V_TIA/V_ADC × 4 señales

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
- Las 8 columnas V_TIA/V_ADC del CSV del sweep test se han expandido a 32 (4 señales × 8 estadísticos)
- Prefijos: `LED1_`, `LED2_`, `ALED1_`, `ALED2_`
- Señal → buffer → RG usado:
  - `LED1_` → `_buf["IR"]` → `rg1_ohm` (rg1_str de la UI/combo)
  - `LED2_` → `_buf["RED"]` → `rg2_ohm` (rg2_str de la UI/combo)
  - `ALED1_` → `_buf["IR_Amb"]` → `rg1_ohm` (mismo TIA que LED1)
  - `ALED2_` → `_buf["RED_Amb"]` → `rg2_ohm` (mismo TIA que LED2)
- `_write_row`: bucle sobre 4 pares (buf_key, rg_ohm); si el buffer está vacío → 8 strings vacíos
- `_CSV_HEADER` actualizado: 60 → 84 columnas

---

## Sesión 2026-06-06a — SIGNAL STATS: V_TIA y V_ADC a 3 decimales

### Ficheros modificados
- `pulsenest_lab.py`

### Cambio
- Columnas V_TIA y V_ADC en la tabla SIGNAL STATS: formato `:.2f` → `:.3f` (L9849-9850)

---

## Sesión 2026-06-06b — CSV sweep: columnas diferenciales V_TIA + 6 decimales

### Ficheros modificados
- `pulsenest_lab.py`

### Cambios
- `_CSV_HEADER`: 84 → 92 columnas. Añadidas 8 columnas diferenciales:
  `LED1_ALED1_V_TIA_mean/std/min/max` y `LED2_ALED2_V_TIA_mean/std/min/max`
- `_write_row`: `_vstats` dividida en `_vstats_tia` (6 decimales) y `_vstats_adc` (4 decimales)
- Las 24 columnas V_TIA (16 individuales + 8 diferenciales) usan `:.6f`
- Las 16 columnas V_ADC mantienen `:.4f`
- Diferencial: `v_tia[IR][i] − v_tia[IR_Amb][i]` (LED1−ALED1) y `v_tia[RED][i] − v_tia[RED_Amb][i]` (LED2−ALED2), stats sobre la serie muestra a muestra

---

## Sesión 2026-06-06c — WiFi: eliminar persistencia last_net en NVS

### Ficheros modificados
- `src/main.cpp`

### Cambio
- Eliminado el mecanismo de guardar/leer `last_net` en NVS (namespace `pulsenest`)
- El ESP32 ahora siempre prueba las redes WiFi desde el índice 0 de `WIFI_NETWORKS[]`
- Eliminado `#include <Preferences.h>` (ya no se usa)
- Variable de bucle renombrada de `n` a `i` (simplificación al quitar el offset)

### Motivación
El ESP32 se conectaba a la última WiFi conocida (WiFi de casa) en lugar del hotspot Windows (índice 0), porque NVS persistía el índice de la última conexión exitosa. Con este cambio siempre intenta primero la red en posición 0 de `WIFI_NETWORKS`.

### Estado
Build OK. Flash pendiente (ESP32 no accesible por OTA ni COM15 en este momento).

---

## Sesión 2026-06-06d — Auditoría y refactoring de nomenclatura de magnitudes

### Motivación
Preocupación por inconsistencia de nombres para las mismas magnitudes físicas/matemáticas a través de 4 capas: datasheet AFE4490, firmware (librería), script Python y documentación. El problema central no era las unidades sino que el nombre no comunicaba qué magnitud representaba ni a qué dominio pertenecía.

### Auditoría — problemas identificados
1. **La señal ambient-corrected tenía 6 nombres distintos** según la capa: `led1_aled1` (struct), `IR_Sub` (frame), `ir_sub` (Python), `LED1_Sub` (dict), `ir_corr` (parámetro `_update_spo2`), `ir` (variable local interna)
2. **Frame usaba `IR`/`RED` para señales hardware** — violaba la regla de dominio (IR/RED = fisiológico, no ADC crudo)
3. **`pi` colisionaba con π** — `constexpr float pi = 3.14159...` y `float pi` (Perfusion Index) en el mismo fichero `.cpp`
4. **`pmod_ir` en el diccionario ≠ `pi` en el código** — misma magnitud, dos nombres en el proyecto
5. **`R` tenía 4 nombres**: `R` (Python/dict), `spo2_r` (struct), `SpO2_R` (frame), `R_fw` (calibración Python)
6. **`ppg`/`PPGdisp`/`ppg_disp`** — 3 nombres para la señal de visualización
7. **Spec `pulsenest_lab_spec.md` §4.2 desactualizada**: incluía `<LibID>` inexistente, faltaban `<RSQI>/<DiagCode>/<ProbeState>`

### Decisión — 6 reglas de nomenclatura formalizadas
- **Regla 1:** Fuente de autoridad por dominio (datasheet → hardware, ISO 80601-2-61 → clínico)
- **Regla 2:** Sin mezcla de dominios — señales ADC crudas nunca se nombran con terminología fisiológica
- **Regla 3:** Sin colisión semántica — un nombre, un único significado en el mismo ámbito
- **Regla 4:** Sufijos de operación para señales derivadas: `_sub` (sustracción ambiental), `_disp` (solo display)
- **Regla 5:** Un único nombre canónico por magnitud, documentado en el diccionario
- **Regla 6:** Consistencia de case entre capas: `snake_case` en C++/Python, `UPPER_SNAKE` en frame $M1

### Nombres canónicos adoptados

| Magnitud | Antes | Después |
|---|---|---|
| Señal IR ambient-corrected | `led1_aled1` / `IR_Sub` / `ir_sub` / `ir_corr` | `led1_sub` / `LED1_SUB` / `led1_sub` |
| Señal RED ambient-corrected | `led2_aled2` / `RED_Sub` / `red_sub` / `red_corr` | `led2_sub` / `LED2_SUB` / `led2_sub` |
| ADC raw en frame | `IR` / `RED` / `IR_Amb` / `RED_Amb` | `LED1` / `LED2` / `ALED1` / `ALED2` |
| PPG visualización | `ppg` (struct) / `PPGdisp` (spec) | `ppg_disp` / `PPG_DISP` |
| Perfusion Index | `pmod_ir` (dict) / `pi` (código) | `pi` unificado (dict actualizado) |
| Constante matemática π | `pi` (.cpp anon namespace) | `kPi` |
| SpO2 ratio en frame | `SpO2_R` | `R` |

### Preservados deliberadamente
- `REG_LED1_ALED1VAL` / `REG_LED2_ALED2VAL` — nombres de registro del datasheet (Regla 1)
- `spo2_r` en struct C++ — prefijo de namespace aceptable; `R` sigue siendo el nombre canónico (Regla 5)
- Variables locales `ir`/`red` dentro de algoritmos fisiológicos — cruce de dominio intencional y correcto
- Texto de UI visible al usuario ("Ambient IR", "IR (clean)") — legibilidad humana prioritaria

### Ficheros modificados
- `incunest_afe4490/incunest_afe4490.h` — struct `AFE4490Data`, enums, parámetros, members privados
- `incunest_afe4490/incunest_afe4490.cpp` — implementación completa + `kPi`
- `incunest_afe4490/examples/basic/main.cpp` — referencias al struct
- `PulseNest/src/main.cpp` — frame comment y referencias al struct
- `PulseNest/pulsenest_lab.py` — variables, parámetros, widgets, QSettings keys, comentarios
- `PulseNest/pulsenest_lab_spec.md` — frame $M1 corregido y completado (RSQI/DiagCode/ProbeState añadidos, LibID eliminado)
- `memory/project_nomenclature_dictionary.md` — reescrito con las 6 reglas y tablas canónicas

### Commits
- `incunest_afe4490` master `5431b83` — refactor nomenclatura librería
- `PulseNest` master `5c32a45` — refactor nomenclatura firmware + script + spec

### Estado
Build OK (RAM 18.7%, Flash 29.7%). Upload OK (COM15, incunest_V16). Firmware en la placa.

---

## Sesión 2026-06-06e — Refactor nomenclatura: eliminar "IR"/"RED" de UI y código Python

### Contexto
Continuación de la sesión 2026-06-06d. Tras renombrar las señales en firmware y librería (LED1/LED2/led1_sub/led2_sub), quedaban ocurrencias de "IR" y "RED" como etiquetas de datos en pulsenest_lab.py.

### Cambios implementados

**pulsenest_lab.py** — Commit `10d1a41`:

#### Atributos de instancia
- `self.data_ir` → `self.data_led1`, `self.data_red` → `self.data_led2`
- `self.curve_ir` → `self.curve_led1`, `self.curve_red` → `self.curve_led2`
- `self.curve_dc_ir/red` → `self.curve_dc_led1/led2`, `self.curve_rms_ir/red` → `self.curve_rms_led1/led2`
- `self.check_ir_raw` → `self.check_led1_raw`, `self.check_red_raw` → `self.check_led2_raw`
- QSettings keys actualizadas en consecuencia

#### Claves internas de buffers
- `_SIGNALS = ["RED","IR",...]` → `["LED2","LED1",...]`
- `self._buf["IR"]` → `self._buf["LED1"]`, `self._buf["RED"]` → `self._buf["LED2"]`
- Loop tuples en sweep CSV writer: `("IR",rg1_ohm)` → `("LED1",rg1_ohm)`, etc.

#### _COLS (replay CSV)
- Display label: `"RED"` → `"LED2 (RED)"`, `"IR"` → `"LED1 (IR)"`
- CSV column name: `"RED"` → `"LED2"`, `"IR"` → `"LED1"`

#### _STATS_SIGNALS (SIGNAL STATS table)
- `("IR", "data_ir", ...)` → `("LED1 (IR)", "data_led1", ...)`
- `("RED", "data_red", ...)` → `("LED2 (RED)", "data_led2", ...)`

#### UI display strings
- Plot titles HTML: `>IR<` → `>LED1 (IR)<`, `>RED<` → `>LED2 (RED)<`
- `QLabel("IR")` → `QLabel("LED1 (IR)")`, `QLabel("RED")` → `QLabel("LED2 (RED)")`
- Curve names: `name="IR (Raw)"` → `"LED1 (IR)"`, `name="RED (Raw)"` → `"LED2 (RED)"`, etc.
- Checkbox labels: `"IR (raw)"` → `"LED1 (IR)"`, `"Ambient IR"` → `"Ambient LED1"`, etc.
- Tooltip titles: actualizados en ambas clases PPGPlotsWindow y PPGSignalsWindow
- Ejes de grupo: `"DC  (IR, RED)"` → `"DC  (LED1, LED2)"`, `"RMS AC  (IR, RED)"` → `"RMS AC  (LED1, LED2)"`
- `_val_rows`: `"DC IR"` → `"DC LED1 (IR)"`, etc.
- `is_ir` local var → `is_led1`

#### Cabeceras CSV de exportación
- `RED,IR,ALED2` → `LED2,LED1,ALED2` en todas las cabeceras de fichero de exportación

#### Comentarios y docstrings
- Todos los comentarios de layout de frame M1/M2 actualizados: `[3]=RED [4]=IR` → `[3]=LED2 [4]=LED1`
- Docstrings de ventanas, tooltips de botones PPGPLOTS/SIGNALS, comentarios internos

### Decisiones
- Formato "LED1 (IR)" / "LED2 (RED)" aprobado por el usuario para displays (con espacio antes del paréntesis)
- Texto descriptivo largo en tooltips que usa "IR LED" / "RED LED" como adjetivos de hardware: conservado (no es etiqueta de variable)
- Etiquetas cortas como identificadores: todas actualizadas

### Estado
`PulseNest` master `10d1a41`. Script no relanzado aún (relanzar manualmente).

---

## Sesión 2026-06-06f — Refactor LUTs físicas y codecs de string en librería

### Contexto
Análisis del problema de nomenclatura y traducción de dominios para parámetros hardware AFE4490 (LED current, RF, CF, RG, AMBDAC). Se decidió abordar la librería en primera fase.

### Problema identificado
Triple duplicación de LUTs físicas:
- `tia_rf_ohm[]`, `tia_cf_pF[]`, `stg2_rg_linear[]` en anonymous namespace del .cpp (fuente de verdad, inaccesible)
- `tia_gain_str()`, `tia_cf_str()`, `stage2_str()` en main.cpp (copia parcial como strings)
- Dicts `_STG2_RG_OHM` etc. en pulsenest_lab.py (tercera copia)

### Cambios implementados

**incunest_afe4490.h** — Commit `661ff32` (librería):
- `AFE4490Stage2Gain`: comentarios dB → ×N → RG (kΩ) en cada enumerador
- Tablas `constexpr` públicas (fuente de verdad única):
  - `kAFE_RF_OHM[7]` — AFE4490TIAGain → Ω
  - `kAFE_CF_PF[6]` — AFE4490TIACF → pF
  - `kAFE_STG2_RG_OHM[5]` — AFE4490Stage2Gain → RG (Ω)
  - `kAFE_STG2_LINEAR[5]` — AFE4490Stage2Gain → ganancia lineal (×)
  - `kAFE_STG2_RI_OHM` — Ri fijo = 100 kΩ
- Inline string codecs (afeRFToStr/afeStrToRF, afeCFToStr/afeStrToCF, afeStg2ToStr/afeStrToStg2)

**incunest_afe4490.cpp**:
- Eliminados `tia_rf_ohm[]`, `tia_cf_pF[]`, `stg2_rg_linear[]` del anonymous namespace
- Todos los usos reemplazados con `kAFE_RF_OHM`, `kAFE_CF_PF`, `kAFE_STG2_LINEAR`
- `rf_code[]`, `cf_code[]`, `stg2_gain_code[]` conservados (puramente internos — códigos de registro)

**main.cpp** — Commit `344a27e`:
- Eliminadas 6 funciones locales (3 to-string + 3 parse)
- Sustituidas por las inline del header

### Decisiones de diseño
- Sufijo de dominio en nombre: `kAFE_RF_OHM` (Ω), `kAFE_CF_PF` (pF), `kAFE_STG2_LINEAR` (×)
- `AFE4490Stage2Gain` mantiene nombre en dB (convención del datasheet) + comentario con ×N y kΩ
- AMBDAC: valor en µA = valor de registro (1:1, sin LUT) — ningún cambio necesario
- LED current: float en mA, conversión a DAC solo en `_apply_analog_regs()` — ningún cambio necesario
- Fase 2 (Python): reemplazar dicts locales `_STG2_RG_OHM` etc. con valores del $CFG frame extendido o con constantes documentadas en la spec

### Estado
Build OK (RAM 18.7%, Flash 29.7%). librería `incunest_afe4490` master `661ff32`. PulseNest master `344a27e`.

---

## Sesión 2026-06-06 (continuación) — Fase 2: Python LUTs eliminadas

### Tema
Fase 2 del plan de nomenclatura/dominios de parámetros AFE4490: eliminar las copias locales de tablas físicas en `pulsenest_lab.py` haciendo al firmware la única fuente de verdad.

### Cambios implementados

**main.cpp** — Commit `15c70b2`:
- `buf[400]` → `buf[600]` (frame más largo)
- `$CFG` extendido con valores físicos: `rf1_ohm`, `cf1_pF`, `rg1_ohm`, `rg1_x`, `rf2_ohm`, `cf2_pF`, `rg2_ohm`, `rg2_x`, `ri_ohm`
- Valores tomados directamente de `kAFE_RF_OHM[]`, `kAFE_CF_PF[]`, `kAFE_STG2_RG_OHM[]`, `kAFE_STG2_LINEAR[]`, `kAFE_STG2_RI_OHM` (constexpr en header)

**pulsenest_lab.py** — Commit `15c70b2`:
- Eliminados 4 class-level dicts de `PPGMonitor`: `_STG2_RG_OHM`, `_STG2_RI_OHM`, `_STG2_RG_LINEAR`, `_TIA_RF_OHM`
- `_compute_ot()`: nueva firma `(led_sub, led_ma_str, rf_ohm, rg_x)` — floats directos desde `_last_cfg`
- SIGNAL STATS V_TIA: usa `_last_cfg.get("rg1_ohm"/"rg2_ohm"/"ri_ohm")`
- `AFESweepTestWindow._write_row()`: OT y V_TIA usan `self.parent()._last_cfg` — eliminados inline dicts `_rf_ohm`, `_rg_lin`, `_STG2_RG_OHM`

### Decisiones de diseño
- Opción elegida: extender $CFG frame (vs. módulo constantes Python separado) — Python lee valores físicos del firmware directamente
- `AFESweepTestWindow` accede a `_last_cfg` via `self.parent()` (PPGMonitor), válido porque se instancia como `AFESweepTestWindow(self)` donde `self` es PPGMonitor
- Defaults seguros: si `_last_cfg` vacío (antes del primer $CFG), se usan defaults `rf_ohm=100e3`, `ri_ohm=100e3`, `rg_ohm=100e3`, `rg_x=1.0`
- `_STG2_RG_LINEAR` tenía precisión incorrecta en Python (1.496, 2.985) — corregido implícitamente al eliminar los dicts: ahora los valores vienen del firmware (`kAFE_STG2_LINEAR[] = {1.0, 1.5, 2.0, 3.0, 4.0}`)

### Estado
Firmware build OK (RAM 18.7%, Flash 29.7%). Python syntax OK. Commit `15c70b2` en master.

---

## Sesión 2026-06-06 (continuación 2) — Fix SW subtraction led1_sub/led2_sub

### Tema
Corrección del desbordamiento 22-bit en los registros HW de resta ambiental del AFE4490.

### Problema
`REG_LED1_ALED1VAL` y `REG_LED2_ALED2VAL` realizan la resta LED−ALED internamente en 22 bits. Cuando los operandos tienen signos opuestos cerca del rail (e.g. led1 ≈ +2 097 151, aled1 ≈ −2 097 152), el resultado correcto (~+4 194 303) excede el rango 22-bit (~2 097 151) y el chip entrega un valor incorrecto.

### Solución adoptada
Eliminar las dos lecturas SPI de los registros de resta HW y sustituirlas por resta SW en int32_t, en el único punto donde se decide qué valor entra al sistema (antes del call a `_process_sample()`).

**incunest_afe4490.cpp** — Commit `63b34c2`:
- `led2_diff = led2 - aled2` (int32_t) en lugar de `_sign_extend_22(_read_spi_raw(REG_LED2_ALED2VAL))`
- `led1_diff = led1 - aled1` (int32_t) en lugar de `_sign_extend_22(_read_spi_raw(REG_LED1_ALED1VAL))`
- Líneas originales conservadas comentadas con explicación del desbordamiento
- 2 lecturas SPI menos por ciclo (ganancia menor)

**incunest_afe4490_spec.md** — Commit `63b34c2`:
- §12.2: tabla de registros ADC actualizada — 4 leídos, 2 retirados; rationale del overflow documentado
- cycle_mean/max: descripción actualizada (4 channels + SW subtraction)

**main.cpp** — Commit `9982ab7`:
- Bloque `CHK_AMB_SUB` marcado como obsoleto (siempre devolvería 0 mismatches)

### Análisis de consecuencias
- `_diag_last_led1_sub`: se asigna desde `led1_diff` (ahora SW) → holdoff diagnóstico usa valor correcto sin cambios
- `_process_sample()`, RSQM, SpO2, HR1/2/3: sin cambios de código — consumen `led1_sub` sin saber cómo se calculó
- Desincronización temporal: NO es un problema — ambos operandos vienen del mismo ciclo PRF; la ventana temporal entre LED y ALED es idéntica con resta HW o SW

### Decisiones de diseño
- Opción elegida: corrección en el punto de lectura SPI (antes de que ningún código vea el valor HW), no en `_process_sample()` ni en `AFE4490Data`
- Ventaja frente a otras opciones: cubre automáticamente ambos call sites de `_process_sample()` (path normal + holdoff diagnóstico), sin cambios en cascada

### Estado
Build OK. Librería `incunest_afe4490` master `63b34c2` publicado en GitHub. PulseNest master `9982ab7`.

---

## Sesión 2026-06-06 (continuación 3) — Renombrado AFE4490Config/miembros privados

### Tema
Refactorización de nombres de miembros privados y campos públicos de AFE4490Config para reflejar el parámetro físico en lugar del nombre del registro del datasheet.

### Cambios (commits 588ae42 librería + 7bb3d1b PulseNest)

| Anterior | Nuevo | Motivo |
|---|---|---|
| `afe_ensepgain` | `afe_sep_tia_en` | Nombre de bit registro crudo → semántica clara |
| `afe_tia_gain_led1/2` | `afe_tia_rf_led1/2` | Es una resistencia RF, no una "ganancia" |
| `afe_stage2_gain_led1/2` | `afe_stg2_rg_led1/2` | Es la resistencia RG de Stage2 |
| `afe_stage2_en1/2` | `afe_stg2_en_led1/2` | Sufijo canal consistente `_led1/_led2` |

### Scope
- `incunest_afe4490.h` — struct público AFE4490Config + miembros privados + comentarios
- `incunest_afe4490.cpp` — todos los usos internos
- `incunest_afe4490_spec.md` — spec actualizada
- `main.cpp` — accesos vía AFE4490Config
- `pulsenest_lab.py` — tooltips con referencias a nombres de campo

### Invariantes
- Wire protocol keys ($SET/$CFG: `ensepgain`, `stage2en1`, `stage2en2`) sin cambio
- Tipos de enum (`AFE4490TIAGain`, `AFE4490Stage2Gain`) sin cambio — fricción aceptada
- Pendiente: resolver fricción entre nombre del campo (Ω) y tipo del enum (dB/labels)

### Estado
Build OK. librería master `588ae42` publicado en GitHub. PulseNest master `7bb3d1b`.

---

## Sesión 2026-06-06 (continuación 4) — Renombrado enums AFE4490RF/AFE4490RG

### Cambios (commits ae3e07f librería + 7b5f698 PulseNest)

| Anterior | Nuevo |
|---|---|
| `AFE4490TIAGain` | `AFE4490RF` |
| `AFE4490Stage2Gain` | `AFE4490RG` |
| `GAIN_0DB…GAIN_12DB` | `RG_100K…RG_400K` |
| `afeStg2ToStr` / `afeStrToStg2` | `afeRGToStr` / `afeStrToRG` |

### Resultado final — cadena de nombres consistente end-to-end
`AFE4490RF::RF_100K` → `kAFE_RF_OHM[(int)val]` → `_afe_tia_rf_led1`
`AFE4490RG::RG_100K` → `kAFE_STG2_RG_OHM[(int)val]` → `_afe_stg2_rg_led1`

Wire protocol ($SET/$CFG) sin cambio. Build OK.

---

## Sesión 2026-06-06b

### Tema: Fix cierre de UdpComWindow al cerrar ventana principal

### Problema
Al cerrar la ventana principal de pulsenest_lab.py, `UdpComWindow` quedaba abierta. La ventana se creó en su momento pero se omitió añadirla al `closeEvent` de `PPGMonitor`.

### Causa
`udpcom_window` no estaba en el bloque de cierre de `closeEvent` (`pulsenest_lab.py:10458`), a diferencia de todas las demás ventanas secundarias.

### Cambio
- `pulsenest_lab.py`: añadidas 3 líneas en `closeEvent` para cerrar `udpcom_window` junto a `serialcom_window`.

---

## Sesión 2026-06-06c

### Tema: struct AFE4490AnalogState — reconstrucción analógica física desde ADC

### Decisiones de diseño

**Arquitectura Option B:** struct `AFE4490AnalogState` efímero, calculado en `_process_sample()` y pasado por referencia a `_update_rsqm()` (y futuro HGAC). No se almacena en `AFE4490Data`.

**Fórmulas (datasheet Eq.2 p.30):**
```
V_ADC = code / kAFE_ADC_FS_COUNTS × kAFE_ADC_FSR
V_TIA = (V_ADC / (2 × RG_ohm) + I_CANCEL_A) × Ri   [= I_PD × RF]
I_PD  = V_TIA / RF_ohm
OT    = (I_PD_LED − I_PD_ALED) / I_LED_A
```
- Cuando `STAGE2EN=0`: `RG_ohm = kAFE_RI_OHM` (ganancia unidad)
- Sentinel OT = 100.0 cuando `led >= rsqm_adc_positive_sat`

**Escala OT:** el OT anterior era heurístico (counts / (mA·Ω·rg_linear)), no físico. El nuevo es [A/A] dimensionless, escala ~3495× menor. Por tanto `rsqm_ot_thr` cambia de 0.30 a 8.5e-5.

Valores esperados nuevos (estimados, pendiente calibración empírica):
- APPLIED: ot ≈ 1.4e-5
- NOT_APPLIED: ot ≈ 8e-4
- Sentinel (saturado): 100.0

### Cambios de código

**`incunest_afe4490.h`:**
- Añadidas constantes `kAFE_ADC_FS_COUNTS = 2097151.0f` y `kAFE_ADC_FSR = 1.2f`
- Añadido `struct AFE4490AnalogState` con campos `v_adc_*`, `v_tia_*`, `i_pd_*`, `ot_led1/2`
- Añadida declaración `_compute_analog_state(led1,led2,aled1,aled2) const`
- `_update_rsqm()` recibe nuevo parámetro `const AFE4490AnalogState& as`
- `rsqm_ot_thr` cambia de 0.30 a 8.5e-5 con comentario de calibración pendiente

**`incunest_afe4490.cpp`:**
- Implementado `_compute_analog_state()` con las fórmulas del datasheet
- `_process_sample()` llama primero a `_compute_analog_state()`, pasa `as` a `_update_rsqm()`
- `_update_rsqm()` usa `as.ot_led1/2` en lugar de calcular OT localmente (eliminados rf1/rg1/rf2/rg2 locales)

### Pendiente
- Calibrar `rsqm_ot_thr = 8.5e-5f` con hardware real (APPLIED vs NOT_APPLIED medidos)
- HGAC consumirá `as.v_tia_*` e `i_pd_*` para monitorizar zonas de saturación

---

## Sesión 2026-06-06d

### Tema: fix cosmético en _compute_analog_state()

Variables locales `rf1`/`rf2` renombradas a `rf1_ohm`/`rf2_ohm` para consistencia con `rg1_ohm`/`rg2_ohm`. Comentario interno actualizado. Sin cambio funcional.

---

## Sesión 2026-06-06e

### Tema: revert sufijo _ohm en variables locales de _compute_analog_state()

Se revirtió el cambio de `rf1_ohm`/`rf2_ohm` → `rf1`/`rf2` (y `rg1_ohm`/`rg2_ohm` → `rg1`/`rg2`). El usuario prefiere sin sufijo para variables locales cortas dentro de una función. La convención `_ohm` aplica a campos públicos (structs, API), no a variables locales de contexto obvio.

---

## Sesión 2026-06-06f

### Tema: legibilidad de _compute_analog_state()

Eliminadas variables intermedias de optimización `inv2rg1`/`inv2rg2` e `inv_rf1`/`inv_rf2`. Las expresiones se escriben ahora directamente como las ecuaciones del datasheet (`/ (2.0f * rg1)`, `/ rf1`). El compilador con -O2 genera el mismo código.

---

## Sesión 2026-06-06g

### Tema: legibilidad de _compute_analog_state() — añadido ri

Añadida variable local `const float ri = kAFE_RI_OHM` para que las líneas de `v_tia` se lean igual que la ecuación del datasheet (`× ri` en lugar de `× kAFE_RI_OHM`). Sin cambio funcional.

---

## Sesión 2026-06-06h

### Tema: documentación inline de _compute_analog_state()

Añadidos comentarios con referencias al datasheet en cada bloque de la función:
- V_ADC: datasheet p.26 (ADC 22-bit, ±1.2 V)
- RF/RG/Ri/I_CANCEL: registros TIAGAIN, TIA_AMB_GAIN, p.27-28-30
- V_TIA: Eq.2 p.30 (inversión), definición física V_TIA = I_PD × RF
- I_PD: definición transimpedancia V_TIA = I_PD × RF
- OT: definición física, LEDCNTRL p.28, sentinel ADC saturado

---

## Sesión 2026-06-06i

### Tema: OT movido de AFE4490AnalogState a _update_rsqm()

**Decisión:** `ot_led1`/`ot_led2` eliminados del struct. OT es un concepto de RSQM, no de reconstrucción analógica.

**Argumento principal:** `_compute_analog_state()` referenciaba `rsqm_adc_positive_sat` y `rsqm_ot_saturated` — acoplamiento incorrecto entre capa física y módulo de calidad de señal.

**Resultado:**
- `AFE4490AnalogState` queda como tabla simétrica pura: v_adc/v_tia/i_pd × 4 canales
- `_compute_analog_state()` sin dependencias de RSQM
- `_update_rsqm()` calcula OT desde `as.i_pd_*` (fórmula + sentinel en el sitio correcto)
- Spec §3c y §5.6 actualizadas con justificación arquitectónica

---

## Sesión 2026-06-06j

### Tema: actualizar _compute_ot() en pulsenest_lab.py a fórmula física

`_compute_ot()` usaba la fórmula heurística antigua: `LED_Sub / (LED_mA × RF × RG_linear)`.
Actualizada a la fórmula física coherente con la librería (datasheet Eq.2 inversión):

```
OT = led_sub × ADC_FSR × Ri / (ADC_FS_COUNTS × 2 × RG_ohm × RF_ohm × I_LED_A)
```

I_CANCEL se cancela en la resta LED-ALED, por lo que no aparece en la fórmula.

Cambios:
- `_compute_ot(led_sub, led_ma_str, rf_ohm, rg_ohm)` — parámetro `rg_x` → `rg_ohm`
- Call sites: `rg1_x`/`rg2_x` → `rg1_ohm`/`rg2_ohm`; fallback 100e3 cuando STAGE2EN=0
- Tooltips OT_LED1/OT_LED2 actualizados con nueva fórmula, escala y threshold

---

## Sesión 2026-06-06k

### Tema: notación científica para OT_LED1/OT_LED2 en SIGNAL STATS

Filas OT_LED1 (sig_idx=18) y OT_LED2 (sig_idx=19) formateadas con `f"{v:.2e}"` en lugar de `f"{v:.2f}"`. Los valores físicos (~1e-5 APPLIED, ~8e-4 NOT_APPLIED) son ilegibles con formato fijo de 2 decimales.

---

## Sesión 2026-06-06l

### Tema: fix índice científica OT en SIGNAL STATS

Corrección de índice: OT_LED1=19, OT_LED2=20 (no 18/19 como se había puesto). DiagCode ocupa el índice 18. El error aplicaba notación científica a DiagCode y OT_LED1 en lugar de OT_LED1 y OT_LED2.

---

## Sesión 2026-06-06m

### Tema: formato DiagCode en SIGNAL STATS

DiagCode (sig_idx=18) es un bitmask — sin decimales en todas las columnas excepto SD (que puede ser fraccionario si el valor varía). Construido con vals explícito: `[:.0f, :.2f, :.0f, :.0f, :.0f]` para [Mean, SD, Max-Min, Min, Max].

---

## Sesión 2026-06-06n

### Tema: corrección semántica de OT — ratio electro-óptico, no transmitancia de tejido

OT = I_PD_sub / I_LED es el ratio electro-óptico del sistema completo (eficiencia LED × transmitancia tejido × responsividad fotodiodo), no la transmitancia óptica del tejido sola. El comentario "tissue absorbs ~95% of light" era incorrecto.

Cambios:
- `incunest_afe4490.cpp` (_update_rsqm): comentario corregido, añadida nota "full electro-optical system ratio"
- `incunest_afe4490_spec.md` §3c: fórmula OT anotada como "electro-optical system ratio"
- `incunest_afe4490_spec.md` §5.6.2: párrafo añadido explicando que OT no es transmitancia del tejido solo

El nombre OT se mantiene como convención interna.

---

## Sesión 2026-06-07a

### Tema: PROBE_DISCONNECTED — sustituir check de signo ADC por |i_pd| < umbral

Criterio anterior: `led1 < 0 && aled1 < 0 && led2 < 0 && aled2 < 0`
Criterio nuevo: `|i_pd_led1| < 50nA && |i_pd_led2| < 50nA && |i_pd_aled1| < 50nA && |i_pd_aled2| < 50nA`

Razonamiento: cuando el sensor está desconectado, el fotodiodo no está conectado → i_pd refleja solo la corriente de bias del TIA (~14 nA worst case, medido como LED2_Sub=4013 @ ADC ≈ -5000 counts). Umbral 50 nA da margen ×3.5.

i_pd es independiente del AMBDAC (la fórmula invierte correctamente la cadena del circuito, cancelando I_CANCEL).

Nuevo constexpr: `rsqm_disconn_i_pd_thr = 50e-9f`
Check `|led_sub| < rsqm_disconn_sub_mean` se mantiene como criterio complementario.

---

## Sesión 2026-06-07a

### Tema: Simetría _diag_active vs _diag_holdoff en _task_body

### Problema detectado
El bloque `_diag_active` (línea 1448) empujaba `_current_data` directamente a la cola (bypass de `_process_sample()`), mientras que el bloque `_diag_holdoff` (línea 1462) llamaba a `_process_sample()` con valores congelados. Asimetría con tres problemas:
1. Filtros IIR/BPF/LP no avanzan durante `_diag_active` → hueco en el estado de los filtros al arrancar el holdoff.
2. Cualquier campo nuevo en `_process_sample()` no se aplica durante `_diag_active` (trampa silenciosa de mantenimiento).
3. Patrón drop-oldest duplicado innecesariamente (en el bloque 1448 y en `_process_sample()`).

### Decisión
Hacer los dos bloques simétricos: `_diag_active` también llama a `_process_sample()` con los mismos valores congelados `_diag_last_*`. Los valores están siempre disponibles porque se guardan en cada ciclo normal antes de que `_diag_active` sea visible.

### Cambio
- `incunest_afe4490.cpp`: bloque `_diag_active` reemplazado — eliminado push directo + drop-oldest explícito; sustituido por `_process_sample(_diag_last_led1, _diag_last_led2, _diag_last_aled1, _diag_last_aled2, _diag_last_led1_sub, _diag_last_led2_sub)`.
- Nota: el comentario `// Push to queue; if full, drop oldest...` añadido minutos antes en ese bloque queda obsoleto y se elimina con el refactor.

---

## Sesión 2026-06-07b

### Tema: Fusión de bloques _diag_active y _diag_holdoff en _task_body

### Razonamiento
Tras la sesión 2026-06-07a, los dos bloques hacían exactamente lo mismo. No había motivo para mantenerlos separados.

### Cambio
- `incunest_afe4490.cpp`: los dos bloques `if (_diag_active)` e `if (_diag_holdoff_samples > 0)` fusionados en uno: `if (_diag_active || _diag_holdoff_samples > 0)`. El decremento de `_diag_holdoff_samples` se protege con su propia condición interna. Los dos estados son mutuamente excluyentes.

---

## Sesión 2026-06-08a

### Tema: Corrección de diag_holdoff_ms — referencia al datasheet; constante FLTRCNRSEL

### Contexto
El valor por defecto `diag_holdoff_ms = 10` en `runAfeDiagnostics()` estaba justificado por el tiempo de settling del TIA (RF_1M + CF_155P: 5τ ≈ 775 µs → ~1 ms). Sin embargo, el dominante real es el filtro low-pass interno del AFE4490, cuyo tiempo de settling tras el modo diagnóstico está especificado en la tabla Electrical Characteristics (datasheet p.11):
- Filter corner 500 Hz → **28 ms**
- Filter corner 1000 Hz → **16 ms**

El filter corner está controlado por el bit FLTRCNRSEL (D15) del registro TIA_AMB_GAIN (0x21), datasheet p.75. La librería no escribía ese bit explícitamente — lo dejaba al valor de reset (0 = 500 Hz).

### Decisiones
1. Añadir `kAFE_FLTRCNRSEL = false` como constexpr de librería (fuente de verdad única para el filter corner).
2. Añadir `kAFE_DIAG_HOLDOFF_MS` derivado de `kAFE_FLTRCNRSEL` (500 Hz → 28, 1000 Hz → 16).
3. `_build_tia_amb_gain_led2()` siempre escribe D15 explícitamente desde `kAFE_FLTRCNRSEL`.
4. `runAfeDiagnostics()` default cambia de `= 10` a `= kAFE_DIAG_HOLDOFF_MS`.

### Cambios
- `incunest_afe4490.h`: añadidas constantes `kAFE_FLTRCNRSEL` y `kAFE_DIAG_HOLDOFF_MS` tras `kAFE_ADC_FSR`; comentario de `runAfeDiagnostics()` actualizado; default `= 10` → `= kAFE_DIAG_HOLDOFF_MS`.
- `incunest_afe4490.cpp`: `_build_tia_amb_gain_led2()` — añadida línea `if (kAFE_FLTRCNRSEL) reg |= 0x008000UL;`; comentario del registro actualizado para incluir FLTRCNRSEL.

### Pendiente
- Actualizar spec y hacer commit/push.

---

## Sesión 2026-06-08b

### Tema: kAFE_FLTRCNRSEL — tipo cambiado de bool a uint8_t

### Decisión
`kAFE_FLTRCNRSEL` declarado como `constexpr uint8_t` (valores 0/1) en lugar de `constexpr bool` (false/true). Razón: 0/1 refleja directamente el valor del bit del registro hardware, más coherente con el resto de constantes de la librería.

### Cambio
- `incunest_afe4490.h`: `constexpr bool kAFE_FLTRCNRSEL = false` → `constexpr uint8_t kAFE_FLTRCNRSEL = 0`. Comentario actualizado.

---

## Sesión 2026-06-08c

### Tema: AFE4490DebugData — getter de debug para señales internas no publicadas en AFE4490Data

### Contexto
Se analizaron las alternativas para exponer `AFE4490AnalogState` externamente (getData embedding, getDebugData separado, getDataEx, recompute). Dado que el propósito es debug/test (no producción), y que en el futuro habrá más señales de este tipo, se eligió el patrón `AFE4490DebugData` + overload de `getData()`.

### Decisiones
1. `AFE4490DebugData` — nuevo struct público que agrupa señales de debug. Actualmente contiene `AFE4490AnalogState analog`. Las señales de debug futuras se añaden aquí.
2. Overload `getData(AFE4490Data& data, AFE4490DebugData& dbg)` — una sola llamada que minimiza el skew entre data (queue) y debug snapshot. No es 100% atómico (queue vs snapshot son mecanismos distintos), pero en PulseNest la queue está típicamente vacía → skew ≈ 0. Aceptable para debug.
3. `_debug_data` — miembro privado `AFE4490DebugData`, actualizado en `_process_sample()` bajo `_state_mutex` antes del push a la queue.
4. IncuNest sigue usando `getData(data)` sin cambios.

### Cambios
- `incunest_afe4490.h`: añadido `struct AFE4490DebugData`; overload `getData(data, dbg)`; miembro privado `_debug_data`.
- `incunest_afe4490.cpp`: `_process_sample()` actualiza `_debug_data.analog = as` bajo `_state_mutex` antes del queue push; implementación del overload `getData(data, dbg)`.

### Pendiente
- Compilar y verificar.
- Consumir `dbg` en PulseNest (pulsenest_lab.py — frame $M1 o similar).
- Actualizar spec y hacer commit/push.

---

## Sesión 2026-06-08d

### Tema: Bug crítico — deadlock por mutex reentrante en _process_sample()

### Problema
El nuevo código añadido en la sesión 2026-06-08c hacía `xSemaphoreTake(_state_mutex)` dentro de `_process_sample()`. Sin embargo, `_task_body()` ya llama a `_process_sample()` **dentro de `_state_mutex`** (líneas ~1468 y ~1510 del .cpp). El mutex FreeRTOS no es recursivo → deadlock inmediato → el firmware arrancaba pero no generaba ningún dato ni salida serial.

### Síntomas
- Boot log completo visible por serial
- Cero output serial después de "# incunest_afe4490 started"
- Cero UDP recibido en PC
- Ping al ESP32 funcionaba (red OK)

### Solución
Eliminar el `xSemaphoreTake/_Give` de `_process_sample()`. La protección ya está garantizada: `_task_body()` toma `_state_mutex` antes de llamar a `_process_sample()`, así que `_debug_data.analog = as` está correctamente protegido por el mutex del caller.

### Cambio
- `incunest_afe4490.cpp`: eliminado `xSemaphoreTake(_state_mutex)` / `xSemaphoreGive(_state_mutex)` alrededor de `_debug_data.analog = as`. Sustituido por comentario explicativo.

### Pendiente
- Confirmar recepción de datos en PulseNest con el script
- Implementar la parte de `begin(debug=true)` / queue combinada (diseño acordado pero no implementado)
- Spec y commit/push

---

## Sesión 2026-06-08e

### Tema: begin(debug=true) + queue combinada para atomicidad total en getData(data,dbg)

### Diseño implementado
- `begin(pin_cs, pin_drdy, bool debug=false)` — nuevo parámetro. Cuando debug=true la queue almacena `DebugQueueItem {AFE4490Data + AFE4490DebugData}` en vez de solo `AFE4490Data`. Zero overhead cuando debug=false (IncuNest no cambia nada).
- `DebugQueueItem` — struct interno en anonymous namespace del .cpp. No expuesto en la API pública.
- `getData(data)` — si debug=true, recibe `DebugQueueItem` y extrae solo `data`. Si debug=false, comportamiento idéntico al anterior.
- `getData(data, dbg)` — si debug=false, retorna false inmediatamente. Si debug=true, recibe `DebugQueueItem` atómicamente → `data` y `dbg` siempre del mismo sample.
- `_process_sample()` — push condicional: `DebugQueueItem` si debug, `AFE4490Data` si no.
- `_debug_enabled` — miembro privado, inicializado a false en constructor.

### Cambios
- `incunest_afe4490.h`: `begin()` con `bool debug=false`; `_debug_enabled` miembro privado.
- `incunest_afe4490.cpp`: `DebugQueueItem` en anonymous namespace; `begin()` actualizado; constructor inicializa `_debug_enabled(false)`; `_process_sample()` push condicional; `getData()` overloads actualizados.
- `PulseNest/src/main.cpp`: `afe.begin(AFE4490_CS_PIN, AFE4490_DRDY_PIN, true)`.

### Estado
Compilado OK. Pendiente: flash, verificar, spec, commit/push.

---

## Sesión 2026-06-08f

### Tema: getData() — unificación en un solo método con puntero opcional

### Decisión
Sustituir los dos overloads `getData(data)` / `getData(data, dbg&)` por un único método `getData(data, dbg* = nullptr)`. Razones: (1) con `_debug_enabled` la condicionalidad ya está gestionada en `begin()`, (2) el overload con referencia retornaba `false` si `_debug_enabled=false`, comportamiento confuso, (3) un solo método es más simple de mantener.

### Cambios
- `incunest_afe4490.h`: un solo `getData(AFE4490Data& data, AFE4490DebugData* dbg = nullptr)`.
- `incunest_afe4490.cpp`: implementación unificada — si `_debug_enabled`, recibe `DebugQueueItem` y rellena `*dbg` si no es null; si no, comportamiento original.
- `PulseNest/src/main.cpp`: `afe.getData(data, &dbg)` con `AFE4490DebugData dbg` declarado en el loop.

### Estado
Compilado OK. Pendiente: flash, verificar, spec, commit/push.

---

## Sesión 2026-06-09a

### Tema: Cierre y documentación — AFE4490DebugData completo

### Resumen de lo implementado en las sesiones 2026-06-08c a 2026-06-08f
Funcionalidad completa de debug data:

1. `struct AFE4490DebugData { AFE4490AnalogState analog; }` — struct público para señales de debug
2. `begin(pin_cs, pin_drdy, bool debug=false)` — nuevo parámetro. debug=true crea queue con `DebugQueueItem{AFE4490Data+AFE4490DebugData}` por slot → atomicidad total
3. `getData(AFE4490Data& data, AFE4490DebugData* dbg=nullptr)` — método único. dbg rellenado atómicamente si debug=true y dbg≠null
4. `DebugQueueItem` — struct interno en anonymous namespace del .cpp
5. PulseNest: `begin(..., true)` + `getData(data, &dbg)` en `Incunest_Task`
6. Bug corregido: NO tomar `_state_mutex` dentro de `_process_sample()` (deadlock reentrante — `_task_body()` ya lo tiene tomado)
7. Spec §2.2, §2.6 y nuevo §3d documentados
8. Commits: 80c7e67 (DebugData struct), 6a61b25 (begin+getData), b8d0c64 (PulseNest)

### Pendiente
- Consumir `dbg` en PulseNest: exponer `i_pd_*` / `v_tia_*` en frame serial/UDP y visualizar en pulsenest_lab.py

---

## Sesión 2026-06-09b

### Tema: Tramas seleccionables M1/M2/M3/M4 + consumo de AFE4490DebugData en $M4

### Decisión principal — diseño de tramas
Sustituir el esquema anterior (M1=full, M2=raw ADC) por 4 modos seleccionables:

| Trama | Campos de datos | Uso |
|-------|----------------|-----|
| `$M1` | SmpCnt, Ts_us, PPG_DISP | Serial — mínimo ancho de banda |
| `$M2` | +SpO2, SpO2_SQI, HR3, HR3_SQI, RSQI, DiagCode, ProbeState | Serial — monitorización básica |
| `$M3` | Todo AFE4490Data (23 campos) | UDP — default |
| `$M4` | M3 + V_TIA_LED1/2/ALED1/2 + I_PD_LED1/2/ALED1/2 (31 campos) | UDP — debug analógico |

Default: `$M3` (igual contenido que la antigua `$M1` → sin rotura de compatibilidad).

### Decisión — comando de cambio de trama
Sustituir comandos de un carácter (`'1'`/`'2'`) por `$MODE,Mx` (sin checksum, estilo `$CFG?`/`$RESET`).

### Razón de diseño — sincronización temporal
El usuario requería que señales de debug (V_TIA, I_PD) y señales de producción sean del mismo sample. Colocarlas en una trama separada ($M2) haría necesaria resincronización compleja. La solución: incluirlas en $M4 aprovechando la queue atómica `DebugQueueItem`.

### Cambios — main.cpp
- `IncunestFrameMode`: enum extendido a `{M1, M2, M3, M4}`, default `M3`
- `g_udp_batch_buf`: ampliado a `UDP_BATCH_SIZE * 512` (M4 ≈ 310 chars)
- `Incunest_Task`: 4 casos de frame con buffers adecuados (128/192/384/512)
- `process_command()`: `$MODE,M1/M2/M3/M4` sustituye `'1'`/`'2'`
- Comentario Cmd_Task actualizado

### Cambios — pulsenest_lab.py
- `frame_mode` default: `"M3"`
- 8 nuevos deques: `data_v_tia_led1/2/aled1/2`, `data_i_pd_led1/2/aled1/2`
- 8 nuevas entradas en `_STATS_SIGNALS` (V_TIA y I_PD por canal)
- 4 botones FRAME MODE: `$M1 PPG` / `$M2 BASIC` / `$M3 FULL` / `$M4 DEBUG`
- `_update_frame_button()`: resalta botón activo entre los 4
- `_send_frame_cmd()`: envía `$MODE,{mode}\n`
- Parser principal: detecta lib_id `M3`/`M4` (≥23 partes), `M2` (≥11), `M1` (≥4)
- Parsers M1/M2: rellenan con 0/-1 los campos no disponibles
- Compatibilidad CSV: acepta `M1`/`M3`/`$M1`/`$M3` como LibID válido en ventanas de análisis
- CSV headers: adaptados al modo activo al abrir el fichero de grabación
- `is_data_frame`: detecta `$M1,`/`$M2,`/`$M3,`/`$M4,`
- Reconexión ESP32: resetea `frame_mode` a `"M3"`

### Estado
Verificado OK. Flash OTA vía WiFi (192.168.137.63). Commit 9d91a31, push master.

---

## Sesión 2026-06-09c

### Tema: Reemplazar botones FRAME MODE por combo box

### Cambio
Los 4 botones `$M1 PPG` / `$M2 BASIC` / `$M3 FULL` / `$M4 DEBUG` y el label "FRAME MODE" sustituidos por un único `QComboBox` con las opciones `$M1 PPG MODE` / `$M2 BASIC MODE` / `$M3 FULL MODE` / `$M4 DEBUG MODE`.

### Detalles
- `frame_mode_combo`: QComboBox con estilo azul coherente con el resto de la UI. Default index 2 (M3).
- `_update_frame_button()`: actualiza el índice del combo (blockSignals para evitar bucle).
- `_on_frame_mode_combo_changed(idx)`: conectado a `currentIndexChanged`, llama a `_send_frame_cmd()`.
- `_FRAME_MODES = ["M1","M2","M3","M4"]`: constante de clase para mapear índice ↔ modo.
- Tooltip en el combo con descripción de los 4 modos.

### Estado
Lanzado y verificado visualmente. Pendiente: commit.

---

## Sesión 2026-06-09d

### Tema: Pulido UI y correcciones SIGNAL STATS

### Cambios — pulsenest_lab.py (commit a1f7fed)

1. **Frame-mode combo — font size**: `14px` → `18px` (igual que los botones que sustituye).

2. **SIGNAL STATS — ProbeState color**: el código coloreaba `stats_table.item(len(self._STATS_SIGNALS), 0)`, que apuntaba correctamente a ProbeState cuando era el último elemento. Al añadir las 8 filas V_TIA/I_PD, dejó de ser el último y el color se aplicaba a otra fila. Corrección: calcular `_ps_tbl_row` dinámicamente buscando el índice de "ProbeState" en `_STATS_SIGNALS`.

3. **SIGNAL STATS — I_PD_* en µA**: las 4 filas I_PD (sig_idx 26-29) se muestran en microamperios (×1e6) con 3 decimales (`:.3f`) en lugar de notación científica en amperios.

4. **SIGNAL STATS — V_TIA_* formato**: mantiene 6 decimales en volts (`:.6f`).

---

## Sesión 2026-06-09e

### Tema: Frame mode default M4 + persistencia en ini + correcciones UI

### Cambios — pulsenest_lab.py (commit 86d6dd3)

1. **Frame mode default M4**: `frame_mode` inicializado desde `QSettings("PPGMonitor/frame_mode", "M4")`. Si no hay valor guardado, arranca en `$M4 DEBUG MODE`.
2. **Persistencia en ini**: `_send_frame_cmd()` guarda el modo seleccionado con `setValue("PPGMonitor/frame_mode", mode)`. Se recupera en el siguiente arranque.
3. **Combo index dinámico**: `setCurrentIndex` calculado desde `frame_mode` cargado (`{"M1":0,"M2":1,"M3":2,"M4":3}.get(..., 3)`).
4. **Reconnect reset**: cambiado de "M3" a "M4" para coherencia con el nuevo default.
5. **I_PD tooltips**: `[A]` → `[µA]` en las 4 filas I_PD de SIGNAL STATS.
6. **ProbeState color**: calculado dinámicamente por nombre en lugar de `len(_STATS_SIGNALS)`.

### También en esta sesión (commits anteriores)
- `a1f7fed`: frame-mode combo 18px font; ProbeState color fix; I_PD en µA 3dp.
- `69bd0e8`: 4 botones → QComboBox.

---

## Sesión 2026-06-09f

### Tema: Fix frame-mode combo — bug reconexión + trazas

### Bug
Al reconectar (ESP32 arranca), Python cargaba frame_mode="M4" desde ini y actualizaba el combo, pero **nunca enviaba `$MODE,M4`** al ESP32. El ESP32 siempre arranca en M3 (su default firmware). Resultado: Python esperaba tramas M4 pero recibía M3 — los campos V_TIA/I_PD nunca llegaban.

### Fix — pulsenest_lab.py (commit c7fd14f)
1. **Reconnect**: al recibir `# incunest_afe4490 started`, enviar `$MODE,{frame_mode}` con `QTimer.singleShot(500ms)` (tras el $CFG a 300ms).
2. **Traza petición**: `_send_frame_cmd` loguea `[FRAME] → $MODE,Mx sent` al enviar, y `[FRAME] $MODE,Mx — not sent (no connection)` si no hay conexión.
3. **Traza confirmación**: handler `# Frame mode:` loguea `[FRAME] ✓ Frame mode: $M4 (debug)` cuando el ESP32 confirma.

---

## Sesión 2026-06-09 (continuación) — Fix trazas frame mode + patch_lab.py

### Contexto
Sesión continuada tras compresión de contexto. Pendiente ejecutar patch_lab.py con 3 fixes.

### Fixes aplicados — patch_lab.py → pulsenest_lab.py

1. **Duplicate log `# Frame mode:`**: añadido `if _is_active:` guard al handler. El mismo mensaje llegaba por Serial Y por UDP; sin el guard se logueaba dos veces.
2. **Traza combo**: añadido `self.log(f"[FRAME] combo → {mode}")` en `_on_frame_mode_combo_changed` antes de `_send_frame_cmd`, para ver inmediatamente que el combo fue activado (incluso si no hay conexión).
3. **Guard reconnect**: añadido `and _is_active` en el handler `if 'incunest' in line.lower() and 'frame' not in line.lower()` para evitar que el transporte inactivo dispare el reconect handler.

### Flujo de trazas esperado (post-fix)
- Cambiar combo → `[FRAME] combo → Mx` inmediatamente
- Si conectado → `[FRAME] → $MODE,Mx sent`
- ESP32 confirma → `[FRAME] ✓ Frame mode: $M... (...)` **una sola vez**

### Estado
- patch_lab.py ejecutado y eliminado
- pulsenest_lab.py relanzado
- Pendiente: verificar en HW y hacer commit

---

## Sesión 2026-06-09 (cont. 2) — Stage 2 gain combo: mostrar resistencia y ganancia lineal

### Cambio
Los combos "Stage 2 gain" en HW CONFIG solo mostraban el valor en dB. Ahora muestran también la resistencia RG y la ganancia lineal.

### Formato display
`STG2_GAINS_DISPLAY` en HWConfigWindow:
- "0dB  ×1  100 kΩ"
- "3.5dB  ×1.5  150 kΩ"
- "6dB  ×2  200 kΩ"
- "9.5dB  ×3  300 kΩ"
- "12dB  ×4  400 kΩ"

### Diseño
- `STG2_GAINS` (sin cambio): strings enviados al firmware ("0dB", "3.5dB", etc.)
- `STG2_GAINS_DISPLAY`: strings mostrados en el combo
- `addItems` usa `STG2_GAINS_DISPLAY`
- Send lambdas usan `STG2_GAINS[currentIndex()]` (no `currentText()`)
- `_collect_all_values` y `_save_config` también usan `STG2_GAINS[currentIndex()]`
- `set_combo` (en `_load_config` y `update_from_cfg`): fallback `MatchStartsWith` cuando exact match falla — permite cargar configs antiguas con "0dB" y encontrar "0dB  ×1  100 kΩ"

### Valores físicos (fuente: incunest_afe4490.h)
- RG_100K → 100 kΩ, ×1, 0 dB (Ri=100 kΩ fijo)
- RG_150K → 150 kΩ, ×1.5, 3.5 dB
- RG_200K → 200 kΩ, ×2, 6 dB
- RG_300K → 300 kΩ, ×3, 9.5 dB
- RG_400K → 400 kΩ, ×4, 12 dB

### Estado
- pulsenest_lab.py modificado, pendiente verificación visual + commit

---

## Sesión 2026-06-09 (cont. 3) — AFE SWEEP CSV: columnas $M4 recibidas + Stage 2 gain display

### 1. Stage 2 gain combo — HW CONFIG

Los combos "Stage 2 gain" ahora muestran resistencia y ganancia lineal junto al dB:
- "0dB  ×1  100 kΩ", "3.5dB  ×1.5  150 kΩ", "6dB  ×2  200 kΩ", "9.5dB  ×3  300 kΩ", "12dB  ×4  400 kΩ"

Diseño:
- `STG2_GAINS_DISPLAY` (nueva lista paralela para display)
- `STG2_GAINS` sin cambio (strings enviados al firmware)
- Send lambdas, _collect_all_values y _save_config usan `STG2_GAINS[currentIndex()]`
- set_combo usa `MatchStartsWith` como fallback para cargar configs antiguas ("0dB" → "0dB  ×1  100 kΩ")

### 2. AFE SWEEP CSV — columnas desde LED1_V_TIA_mean

Decisión: las columnas calculadas por Python (V_TIA, V_ADC desde raw ADC codes) se eliminan y se sustituyen por estadísticos de los valores **recibidos directamente del $M4 frame**.

Nuevas columnas (en lugar de las 40 columnas calculadas):
- V_TIA_LED1/2/ALED1/ALED2 mean/std/min/max [V, 6 dec] — recibidos del $M4
- I_PD_LED1/2/ALED1/ALED2 mean/std/min/max [µA, 3 dec] — recibidos del $M4 × 1e6
- V_TIA_LED1-ALED1 y LED2-ALED2 diff mean/std/min/max [V, 6 dec] — calculado desde V_TIA recibidos

Implementación:
- `feed_sample()` ampliado con 8 params opcionales (v_tia_*, i_pd_*)
- Caller en PPGMonitor: pasa `parts[23:31]` cuando `lib_id == "M4" and len(parts) >= 31`
- _write_row: nueva función `_fstats(vals, fmt)` reemplaza el bloque calculado
- Todos los bloques de reset de `_buf` actualizados (3 lugares)
- Si el sweep corre en $M3: columnas V_TIA/I_PD quedan vacías en el CSV

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente verificación HW + commit/push

---

## Sesión 2026-06-09 (cont. 4) — AFE SWEEP CSV: corrección columnas finales

### Corrección sobre sesión anterior
Las columnas diferenciales de V_TIA (LED-ALED) fueron eliminadas porque son variables calculadas, no recibidas del $M4.

En su lugar se añaden diferenciales de **I_PD** (LED-ALED), que tienen sentido fisiológico (corriente pulsada neta):
- `I_PD_LED1_ALED1_diff_uA_mean/std/min/max` [µA]
- `I_PD_LED2_ALED2_diff_uA_mean/std/min/max` [µA]

### Estructura final de columnas últimas del CSV (92 total)
1. V_TIA_LED1/2/ALED1/ALED2 × 4 stats [V, 6 dec] — recibidos de $M4
2. I_PD_LED1/2/ALED1/ALED2 × 4 stats [µA, 3 dec] — recibidos de $M4
3. I_PD_LED1-ALED1 y I_PD_LED2-ALED2 × 4 stats [µA, 3 dec] — calculado

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente verificación HW + commit/push

---

## Sesión 2026-06-09 (cont. 5) — Eliminar trazas verbosas de FRAME mode

Eliminadas dos trazas del log panel que resultaban innecesarias:
- `[FRAME] combo → Mx` — eliminada de `_on_frame_mode_combo_changed`
- `[FRAME] → $MODE,Mx sent` — eliminada de `_send_frame_cmd`
- `[FRAME] $MODE,Mx — not sent (no connection)` — también eliminada (silencioso si no hay conexión)

Solo queda: `[FRAME] ✓ Frame mode: $M... (...)` cuando el ESP32 confirma el cambio.

### Estado
- pulsenest_lab.py modificado, pendiente commit/push (acumulado con cambios previos de sesión)

---

## Sesión 2026-06-09 (cont. 6) — SIGNAL STATS: nuevas filas OT_LED1/OT_LED2 por ratio I_PD

### Cambio
Añadidas dos nuevas filas al final de SIGNAL STATS (índices 30 y 31):
- **OT_LED1** = `I_PD_LED1 / I_PD_ALED1` (dimensionless)
- **OT_LED2** = `I_PD_LED2 / I_PD_ALED2` (dimensionless)

Estas conviven temporalmente con las OT_LED1/OT_LED2 existentes (índices 19/20, basadas en la fórmula del datasheet con $CFG). Objetivo: comparar ambas y eliminar la que resulte redundante.

### Implementación
- `data_ot2_led1` / `data_ot2_led2`: nuevos deques
- `_STATS_SIGNALS`: dos entradas nuevas al final con `data_ot2_led1/2`
- Cálculo per-sample en bloque M4: `_ipd1/_iamb1` (con guard div/0 → 0.0)
- Bloque M3/else y bloque M2/else: append 0.0 (replace_all para los dos bloques idénticos)
- Formato display: notación científica (sig_idx in {19, 20, 30, 31})
- Solo disponibles en modo $M4

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente verificación HW + commit/push

---

## Sesión 2026-06-09 (cont. 7) — Corrección fórmula OT_LED1/OT_LED2 nuevas filas

### Corrección
La fórmula de las dos nuevas filas OT al final de SIGNAL STATS se corrigió de:
- ~~`I_PD_LED1 / I_PD_ALED1`~~ (ratio simple — incorrecto)

A:
- `(I_PD_LED1 − I_PD_ALED1) / I_LED1` (misma fórmula OT del datasheet)
- `(I_PD_LED2 − I_PD_ALED2) / I_LED2`

Donde I_PD proviene de los valores recibidos en $M4 (firmware-computed), e I_LED1/I_LED2 provienen de `_last_cfg` (en mA → A).

Diferencia con OT_LED1/OT_LED2 existentes (índices 19/20): las existentes calculan I_PD desde raw ADC codes + $CFG; las nuevas usan I_PD directamente del $M4. Objetivo: verificar que coinciden, luego eliminar las antiguas.

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente verificación HW + commit/push (acumulado)

---

## Sesión 2026-06-09 (cont. 8) — Fix "---" en filas OT_M4: conflicto de nombre en _stats_buf

### Bug encontrado
Las nuevas filas OT_LED1/OT_LED2 (índices 30/31) mostraban "---" porque compartían nombre con las existentes (índices 19/20). El bug: en `_update_stats_table`, tras mostrar cada fila se llama `self._stats_buf[name].clear()`. Cuando sig_idx=19 procesa "OT_LED1" limpia el buffer; cuando llega sig_idx=30 con el mismo nombre "OT_LED1", el buffer ya está vacío → "---".

### Fix
Las nuevas filas renombradas a `OT_M4_LED1` y `OT_M4_LED2` en `_STATS_SIGNALS` (nombres únicos → entradas propias en `_stats_buf`). El display en la tabla muestra "OT_M4_LED1" / "OT_M4_LED2".

### Regla aprendida
En `_STATS_SIGNALS`, el primer elemento del tuple es TANTO el display name COMO la clave del dict `_stats_buf`. Nombres duplicados causan colisión de buffer y "---" en las filas posteriores.

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente verificación HW + commit/push (acumulado)

---

## Sesión 2026-06-09 (cont. 9) — Eliminar OT_LED1/OT_LED2 (calculadas por script)

### Decisión
OT_LED1 y OT_LED2 (calculadas por script desde raw ADC codes + $CFG) coinciden con OT_M4_LED1/OT_M4_LED2 (basadas en valores $M4). Se eliminan las antiguas.

### Cambios
- `data_ot_led1` / `data_ot_led2`: deques eliminados
- `_STATS_SIGNALS`: entradas OT_LED1/OT_LED2 eliminadas (índices 19/20 liberados)
- `_compute_ot()`: método eliminado
- Parser M3/M4: llamadas `_compute_ot` eliminadas; ramas else: `append(0.0)` eliminados
- Índices de formato en `_update_stats_table` actualizados:
  - V_TIA: `{22,23,24,25}` → `{20,21,22,23}`
  - I_PD: `{26,27,28,29}` → `{24,25,26,27}`
  - OT_M4: `{19,20,30,31}` → `{28,29}`

### Índices finales de _STATS_SIGNALS (30 filas)
0-3: LED1/2/ALED1/2, 4-5: SUB, 6: PPG_DISP, 7-10: SpO2/R/PI,
11-16: HR1-3+SQI, 17: RSQI, 18: DiagCode, 19: ProbeState,
20-23: V_TIA×4, 24-27: I_PD×4, 28-29: OT_M4_LED1/2

### Estado
- pulsenest_lab.py modificado, syntax OK, pendiente commit/push (acumulado)

---

## Sesión 2026-06-09 (cont. 10) — Fix: cerrar todas las ventanas al cerrar la principal

### Bug
Al cerrar la ventana principal, las ventanas secundarias (con parent=None) permanecían abiertas. El closeEvent ya llamaba `.close()` en todas ellas, pero Qt no salía del event loop porque las ventanas con parent=None no son destruidas automáticamente.

### Fix
Añadido `QtWidgets.QApplication.quit()` al final del closeEvent de PPGMonitor, tras `event.accept()`. Fuerza la salida del event loop independientemente del estado de las ventanas.

### Estado
- pulsenest_lab.py modificado, pendiente verificación + commit

---

## Sesión 2026-06-09 (cont. 11) — Renombrar OT_M4_LED1/2 → OT_LED1/2

Renombradas las dos últimas filas de SIGNAL STATS de OT_M4_LED1/OT_M4_LED2 a OT_LED1/OT_LED2.
Sin colisión de nombres ahora que las antiguas filas basadas en ADC codes fueron eliminadas.

### Estado
- pulsenest_lab.py modificado, pendiente commit

---

## Sesión 2026-06-09c

### Tema
Análisis del CSV `afe_sweep_test_2026-06-06_NORMAL_SWEEP.csv` para validar los umbrales del detector `PROBE_DISCONNECTED` en `incunest_afe4490.cpp:1116-1122`.

### Pregunta clave
¿Son correctos los umbrales `rsqm_disconn_i_pd_thr` y `rsqm_disconn_sub_mean`?

### Análisis (126 filas, 3 estados esperados)

**`rsqm_disconn_sub_mean = 5000` → CORRECTO**
- Peor caso con sonda desconectada: 1526 ADC (ambdac=2 µA) → margen 3.3×
- Sin fallos en ninguna combinación de RF/RG.

**`rsqm_disconn_i_pd_thr = 50 nA → DEMASIADO AJUSTADO**
- 2 filas de falso negativo (rows 8 y 17 del CSV): sonda físicamente desconectada pero clasificada como PROBE_APPLIED.
- Causa: con ambdac=2 µA y RF=50 kΩ, el AMBDAC inyecta corriente en la TIA flotante, empujando i_pd hasta 52 nA (row 8: i_pd_aled1=51 nA; row 17: i_pd_led2=52 nA).
- Peores casos medidos: ambdac=0 → 24 nA; ambdac=1 → 16 nA; ambdac=2 → 52 nA.

### Decisión tomada
Subir `rsqm_disconn_i_pd_thr` de **50 nA a 150 nA**:
- Margen sobre peor caso desconectado: 150/52 = 2.9×
- Margen bajo mínimo conectado (canal LED en PROBE_APPLIED): 218/150 = 1.45×
- El criterio sub (38K ADC en PROBE_APPLIED vs 1526 en DISCONNECTED) actúa de guarda adicional.
- El criterio es AND de 4 canales: los canales LED siempre superan 218 nA con sonda presente → sin riesgo de falsos positivos aunque los canales ALED sean pequeños.
- Pendiente: implementar el cambio en `incunest_afe4490.h:560` y actualizar el comentario.

### Estado
- Análisis completado, cambio pendiente de implementar

### Implementación (misma sesión)
- `incunest_afe4490.h:560`: `rsqm_disconn_i_pd_thr` cambiado de `50e-9f` a `150e-9f`
- Comentario actualizado con peor caso real (52 nA, ambdac=2 µA, RF=50K) y márgenes medidos
- Pendiente: commit en repo incunest_afe4490

## Sesión 2026-06-09 (cont. 12) — Renombrar campo "LibID" → "FrameMode" en headers

### Cambio
Renombrado el tercer campo de los headers de trama de `LibID` a `FrameMode` en `pulsenest_lab.py`.

### Archivos modificados
- `pulsenest_lab.py`: reemplazo global de `LibID` → `FrameMode` en:
  - `UdpComWindow.UDP_HEADER` (label del widget de la ventana UDP COM)
  - `SerialComWindow.SERIAL_HEADER`
  - Cabeceras CSV de grabación live (M1/M2/M3/M4) y snapshot
  - Comentarios de layout de trama (`# [0]=FrameMode`, `# $M3/$M4: 0:FrameMode`, etc.)
  - Variable interna `lib_id` y deque `data_lib_id` NO modificados (son variables Python, no labels de usuario)

### Decisión
El campo contiene el identificador del modo de trama (`M1`/`M2`/`M3`/`M4`), por lo que `FrameMode` es más descriptivo que `LibID` (que era un residuo histórico).

## Sesión 2026-06-09 (cont. 13) — Fix: UDP $M4 truncation cada SmpCnt%10==7

### Problema
Con frame_mode $M4, se observaban errores `BAD CHK (no checksum field)` de forma determinista en todas las tramas donde SmpCnt%10==7 (cada 10 tramas, la octava). Las tramas defectuosas llegaban cortadas a ~70 bytes dentro del frame, sin el campo `*XX`.

### Diagnóstico
- `UDP_BATCH_SIZE=10` y cada frame $M4 ≈ 224 bytes → batch total ≈ 2240 bytes
- `WiFiUDP.write()` del stack Arduino ESP32/lwIP trunca silenciosamente por encima de ~1640 bytes (no verifica el retorno de `write()`)
- El frame de índice 7 (0-based) empieza en byte ~1561 del batch → la frontera de truncado cae ~70 bytes dentro de ese frame → trama sin checksum
- Es 100% determinista porque todos los frames M4 tienen longitud casi idéntica (~223-225 bytes)
- Para modos M1/M2/M3 (≤ ~200 bytes/frame × 10 = 2000 bytes) el problema también existe pero estaba justo en el límite

### Decisión
Reducir `UDP_BATCH_SIZE` de 10 a 5: 5 × 224 = ~1120 bytes por datagrama, bien por debajo del límite.

### Archivos modificados
- `include/wifi_config.h`: `UDP_BATCH_SIZE` 10 → 5; comentario actualizado
- `src/main.cpp`:
  - Buffer `g_udp_batch_buf` reducido a `UDP_BATCH_SIZE * 256` (256 bytes por slot; $M4 ≤ 230 chars)
  - Comentario del buffer actualizado
  - Safety flush corregido: antes **descartaba** el batch al overflow; ahora lo **envía** primero
- `pulsenest_lab.py`: comentario `recvfrom(4096)` actualizado con tamaño real (~1120 bytes para M4)

## Sesión 2026-06-10o — Fix UDP_Task: mover a core 1 para evitar starvation

### Problema con core 0
UDP_Task (prioridad 1) en core 0 competía con Incunest_Task (prioridad 3) y no obtenía suficiente CPU. La queue se llenaba → drops masivos (~1-2 muestras cada 2-3 frames). GAP B/UDP continuo.

### Fix
`UDP_Task` movida de core 0 a **core 1** (loop() vacío en core 1 → CPU libre). `WiFiUDP.endPacket()` es thread-safe entre cores en ESP-IDF → llamada desde core 1 funciona correctamente.

### Archivos modificados
- `src/main.cpp`

### Estado
Compilado OK. Flasheado a COM15. Pendiente confirmar desaparición de GAP B/UDP.

## Sesión 2026-06-10n — UDP_Task: desacoplar endPacket() del hot path de adquisición

### Problema diagnosticado
Con no-batching y SERIAL_DOWNSAMPLING_RATIO=1, `endPacket()` se llamaba 500 veces/s desde `Incunest_Task`. El bloqueo de `endPacket()` (~1.3 ms/llamada con RATIO=1, ~16 ms/llamada con RATIO=10) alargaba el periodo efectivo de muestreo de 2 ms a ~3.3 ms, reduciendo la tasa real de datos al script de 500 Hz a ~303 Hz. Como `SPO2_RECEIVED_FS=50.0` asume 50 Hz (= 500/RATIO con RATIO=10), el error en HR era ~50/30 ≈ ×1.65 ("bug ×2").

Causa raíz histórica: el no-batching (sesión 2026-06-10) se diseñó asumiendo SERIAL_DOWNSAMPLING_RATIO=10 (50 endPackets/s). Con RATIO=1 (500 Hz para HR1TEST y Lab Capture), la condición ya no se cumple.

RATIO=10 no es viable porque HR1TEST y Lab Capture necesitan datos a 500 Hz.

### Solución: UDP_Task dedicada
- `g_udp_data_queue`: `QueueHandle_t` con `UDP_QUEUE_DEPTH=32` slots de `UDP_QUEUE_FRAME_SIZE=256` bytes
- `udp_send()`: copia el frame al queue con `strlcpy` + `xQueueSend(..., 0)` (no bloquea nunca)
- `UDP_Task`: prioridad 1, core 0 (co-localizado con stack WiFi). Llama `xQueueReceive` (bloquea hasta que haya frame), luego `beginPacket` + `write` + `endPacket`. El bloqueo queda aislado aquí, sin afectar Incunest_Task.
- `setup()`: crea la queue y lanza `UDP_Task` antes de `start_incunest()`

### Archivos modificados
- `src/main.cpp`

### Estado
Compilado OK (RAM 18.0%, Flash 29.8%). Flasheado a COM15. Pendiente verificar Ts_us ≈ 2000 µs en consola UDP.

## Sesión 2026-06-10m — Revert SERIAL_DOWNSAMPLING_RATIO: 10 → 1

El usuario indicó que el firmware era correcto y que el bug es ×2, no ×10. Se revirtió `SERIAL_DOWNSAMPLING_RATIO` de 10 a 1. Firmware compilado y flasheado a COM15 (V16, SUCCESS). El bug ×2 en el script queda pendiente de diagnosticar.

### Archivos modificados
- `src/main.cpp`

## Sesión 2026-06-10l — Fix SERIAL_DOWNSAMPLING_RATIO: 1 → 10 (pendiente confirmar)

### Contexto
Al inicio de sesión la summary indicaba que `SERIAL_DOWNSAMPLING_RATIO = 1` en `src/main.cpp` causaba que el firmware enviara 500 Hz en lugar de los 50 Hz que espera el script (`SPO2_RECEIVED_FS=50.0`). La summary identificó esto como causa del bug de "doble frecuencia" observado en todas las ventanas del script.

### Cambio realizado
- `src/main.cpp` línea 5: `#define SERIAL_DOWNSAMPLING_RATIO 1` → `#define SERIAL_DOWNSAMPLING_RATIO 10`
- Firmware compilado y flasheado a COM15.

### Controversia — pendiente resolver
El usuario afirma que: (1) el firmware estaba bien, (2) el factor del bug era ×2, no ×10. Esto sugiere que quizás el firmware tenía ratio=5 en la versión flasheada anterior (500/5=100 Hz; script espera 50 Hz → ×2), aunque en el repo el valor era 1. Hipótesis alternativa: el bug era en el script (algún parámetro de frecuencia a ×2), no en el firmware. **Pendiente confirmar con el usuario qué valor era el correcto y si hay que revertir.**

### Archivos modificados
- `src/main.cpp`

## Sesión 2026-06-10k — Fix compilación: quitar default member initializers de EmaChannel

### Problema
Los default member initializers (`{ 0.0f }`, `{ 0 }`) en `EmaChannel` impedían la inicialización agregada con llaves en C++11 (GCC ESP32 Arduino). Error: "no matching function for call to EmaChannel(<brace-enclosed initializer list>)".

### Fix
Eliminados los default member initializers de `mean`, `var`, `count`. Los campos se inicializan siempre explícitamente en constructor y reset, por lo que los defaults eran redundantes. Restaurada la inicialización agregada en constructor y `_reset_algorithms()`.

### Build
Compiló OK (RAM 18.0%, Flash 29.8%). Upload fallido — COM15 no disponible (placa desconectada).

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`

## Sesión 2026-06-10j — Corregir rsqm_ema_mean/var_alpha y rsqm_ready_count

### Problema con valores anteriores
- `rsqm_ema_mean_alpha = 0.02` (τ=100ms, f_c=1.6Hz): demasiado rápido — seguía parcialmente el pulso PPG, sesgando d=x−mean a la baja y subestimando la varianza → posibles falsos RSQM_SIGNAL_WEAK
- `rsqm_ema_var_alpha = 0.004` (τ=500ms): cubría solo ¼ ciclo a 30 bpm (no ½ como se afirmaba en el diseño original)
- `rsqm_ready_count = 750` (1.5s): insuficiente para los nuevos τ

### Valores nuevos
- `rsqm_ema_mean_alpha = 0.001f` — τ=2000ms, f_c=0.08Hz. f_c << 0.5Hz → no sigue el pulso. Responde a cambios hardware (HGAC) en ~6s (3τ), aceptable por RSQM_HW_SETTLING.
- `rsqm_ema_var_alpha = 0.0005f` — τ=4000ms, f_c=0.04Hz. Cubre 4 ciclos @ 60bpm, 2 ciclos @ 30bpm. Asimetría con mean intencionada: requisitos físicos distintos.
- `rsqm_ready_count = 6000` — 3 × τ_var = 12s @ 500Hz.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`

## Sesión 2026-06-10i — Mover BiquadFilter junto a BiquadState en Private types

`BiquadFilter` estaba separado de `BiquadState` por ~35 líneas de constantes RSQM. Movido a la sección `Private types` inmediatamente después de `BiquadState` (que embebe). Orden final: `BiquadState` → `BiquadFilter` → `EmaChannel`.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`

## Sesión 2026-06-10h — Comentario EmaChannel: añadir definición de EMA y fórmula τ

Añadidas tres líneas encima de `struct EmaChannel` explicando qué es EMA, la fórmula equivalente y la relación entre α, τ y fs.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`

## Sesión 2026-06-10g — Comentario R ratio: añadir referencia ISO 80601-2-61:2026

Añadido al comentario del R ratio: "ISO 80601-2-61:2026 calls this the 'modulation ratio' or 'ratio of ratios'."

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-10f — Fix comentario: quitar "Beer-Lambert" del R ratio

"Beer-Lambert" es impreciso — la expresión AC/DC es una aproximación de primer orden, no la ley de Beer-Lambert estricta. Comentario simplificado a "── R ratio ──".

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-10e — SpO2: R ratio con DC/AC explícitos y alternativas documentadas

### Contexto
La línea `R = (rms_ac_red / dc_red) / (rms_ac_ir / dc_ir)` es el núcleo del algoritmo SpO2 (Beer-Lambert). Se quería que DC, AC y R fueran variables explícitas y nombradas, con comentarios que dejen claro el método elegido y las alternativas futuras.

### Cambios en `_update_spo2()`
- `rms_ac_ir/red` → `ac_ir/red` (variables explícitas de AC)
- `_spo2_ch_*_ema.mean` extraído a `dc_ir/dc_red` (variables explícitas de DC)
- Comentarios por sección:
  - **DC:** método actual = IIR low-pass (EmaChannel.mean, τ=1.6s). Alternativa futura: mediana sobre ventana deslizante.
  - **AC:** método actual = sqrt(EMA de (x−DC)²) = sqrt(EmaChannel.var). Alternativa A: BPF 0.5–5 Hz + RMS. Alternativa B: peak-to-peak/2 (estilo Masimo).
  - **R:** `R = (AC_red / DC_red) / (AC_ir / DC_ir)`. Cada término AC/DC es el PI del canal.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-10d — Refactor SpO2: _spo2_dc/ac2 → EmaChannel (_spo2_ch_ir/red_ema)

### Contexto
El PI (Perfusion Index) en `_update_spo2()` usaba 4 floats sueltos (`_spo2_dc_ir/red`, `_spo2_ac2_ir/red`) + 2 alphas separados (`_spo2_dc_iir_alpha`, `_spo2_ac_ema_beta`). Son matemáticamente idénticos a `EmaChannel`: mean=DC, var=AC².

### Decisión
Sustituir los 6 miembros por `EmaChannel _spo2_ch_ir_ema` y `EmaChannel _spo2_ch_red_ema`.

### Diferencia de convención (importante)
El IIR SpO2 anterior usaba peso de *decay* (`dc = alpha*dc + (1-alpha)*x`, alpha cercano a 1).
`EmaChannel.update()` usa peso de *update* (`mean += alpha*(x-mean)`, alpha pequeño).
Conversión: `alpha_mean = 1 − exp(−1/(τ_dc·fs))` — mismo cálculo que `_spo2_ac_ema_beta`.
Los dos alphas quedan simétricamente como `1 − exp(−1/(τ·fs))`.

### Documentación añadida
- `.h`: comentario en los miembros explicando mean=DC, var=AC², PI=sqrt(var)/mean×100, count=unused, y las dos alternativas futuras (BPF para DC, BPF para AC²)
- `.cpp` `_update_spo2()`: bloque de comentarios con pasos DC→AC→AC² y señales de alternativas futuras

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-10c — Rename: _rsqm_led*_sub → _rsqm_led*_sub_ema + rsqm_ema_*_alpha

### Cambios
- `_rsqm_led1_sub` / `_rsqm_led2_sub` → `_rsqm_led1_sub_ema` / `_rsqm_led2_sub_ema`
- `rsqm_ema_alpha_mean` → `rsqm_ema_mean_alpha`
- `rsqm_ema_alpha_var` → `rsqm_ema_var_alpha`

### Decisión de naming
Sufijo `_ema` en los miembros: distingue el estimador de futuros objetos relacionados con `led_sub` (buffers, acumuladores HGAC). El tipo `EmaChannel` ya lo implica pero el nombre lo hace explícito en el call site.
Orden `mean_alpha` / `var_alpha`: dominio antes que parámetro, coherente entre constantes.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-10b — Refactor: RsqmEmaChannel → EmaChannel con alpha y update()

### Contexto
Discusión sobre el diseño del struct `RsqmEmaChannel` en `incunest_afe4490`.

### Decisiones
1. **Renombrar `RsqmEmaChannel` → `EmaChannel`**: el prefijo `Rsqm` no es correcto, EMA es un concepto genérico reutilizable (HGAC también lo usará).
2. **`ema_mean/ema_var` → `mean/var`**: redundante dentro de `EmaChannel`; el contexto ya lo implica.
3. **Alpha dentro del struct**: `alpha_mean` y `alpha_var` como campos de instancia. Permite instancias con τ distintos. Coste: +8 bytes por instancia (negligible).
4. **Método `inline update(float x)`**: encapsula la lógica EMA (mean + variance). El call site pasa de 4 líneas duplicadas a una por canal.
5. **Constantes** `rsqm_alpha_mean/var` renombradas a `rsqm_ema_alpha_mean/var` y conservadas como valores por defecto para inicializar las instancias.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`: struct rediseñado, tipos de miembros actualizados
- `incunest_afe4490/incunest_afe4490.cpp`: constructor, reset y `_update_rsqm()` actualizados

## Sesión 2026-06-10 — Fix UDP: eliminar batching (WiFiUDP.write() trunca a ~446 bytes)

### Problema adicional descubierto
Con `UDP_BATCH_SIZE=5` ($M4 ≈ 224 bytes × 5 = 1120 bytes), los frames seguían llegando en grupos de 2 en lugar de 5. Análisis de timestamps UDP COM:
- (57740, 57750) separadas por 0.6ms → mismo paquete
- (57750 → 57760) separadas por 32ms → paquetes distintos

Conclusión: `WiFiUDP.write()` trunca silenciosamente a ~446 bytes (~2 frames), no ~1640 bytes como se había estimado en la sesión anterior.

### Decisión
Eliminar el batching completamente. La salida del AFE ya está decimada a ~50 Hz → 50 `endPacket()`/segundo es manejable por lwIP sin necesidad de agrupar frames.

### Cambios
- `src/main.cpp`: `udp_send()` reescrita — sin buffer de acumulación, cada frame se envía inmediatamente con `beginPacket` + `write` + `endPacket`. Eliminadas variables `g_udp_batch_buf/len/count`.
- `include/wifi_config.h`: `#define UDP_BATCH_SIZE` eliminado, sustituido por comentario explicativo.
- `pulsenest_lab.py`: comentario `recvfrom(4096)` actualizado → "1 frame per datagram (~224 bytes for $M4)".

### Nota
Firmware compilado OK (RAM 17.9%, Flash 29.8%). Upload pendiente — COM15 bloqueado por proceso externo al terminar la sesión.

## Sesión 2026-06-10p — UDP_Task: raw lwIP socket + batching (5 frames/datagrama)

### Problema diagnosticado
UDP_Task con WiFiUDP (core 1) seguía generando GAP B/UDP masivos. Causa raíz: aunque `endPacket()` ya no bloqueaba `Incunest_Task`, la tasa de 500 paquetes/s sobrepasaba el buffer TX de lwIP (~6 slots). UDP_Task se bloqueaba esperando espacio en el buffer, la queue FreeRTOS se llenaba y `xQueueSend(..., 0)` descartaba frames continuamente.

### Solución: raw lwIP socket + batching 5 frames/datagrama
Reemplazar `WiFiUDP g_udp` por socket raw `lwip/sockets.h`:
- `socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)` → sin overhead de WiFiUDP, sin `beginPacket`/`endPacket`
- `g_udp_dest` pre-rellenado en WiFi connect → `sendto()` en cada batch sin lookups
- UDP_Task acumula greedily hasta 5 frames con `xQueueReceive(..., 0)` y envía en un solo `sendto()`
- Tasa de paquetes: 500 Hz / 5 = ~100 datagramas/s → dentro del límite lwIP
- Tamaño datagrama: 5 × ~230 bytes = ~1150 bytes < MTU 1472 bytes
- `UDP_QUEUE_DEPTH` aumentado de 32 a 64 slots (~128 ms de headroom)
- `g_cmd_udp` y `g_resp_udp` mantienen WiFiUDP (baja frecuencia, no hot path)

### Cambios en `src/main.cpp`
- Añadidos `#include <lwip/sockets.h>` y `#include <lwip/inet.h>`
- `static WiFiUDP g_udp` → `static int g_udp_sock = -1; static struct sockaddr_in g_udp_dest`
- `#define UDP_BATCH_SIZE 5` añadido; `UDP_QUEUE_DEPTH` 32 → 64
- `udp_send()`: guard adicional `g_udp_sock < 0`
- `UDP_Task`: batch greedy + `sendto()` con batch buffer estático 1280 bytes
- `setup()` WiFi connect: `g_udp.begin()` → `socket()+inet_aton()+htons()` para inicializar raw socket
- Compilado OK (RAM 18.3%, Flash 29.8%). Flasheado a COM15 y script relanzado.

### Pendiente
Confirmar desaparición de GAP B/UDP y normalización de Ts_us (~20000 µs cada 10 muestras con decim=10).

## Sesión 2026-06-10q — UDP_Task: batching opción B (timeout 12ms por frame)

### Problema con opción A (greedy timeout=0)
Con `xQueueReceive(..., 0)` en el bucle de acumulación, UDP_Task procesaba frames más rápido de lo que Incunest_Task los producía → batch siempre de 1 frame → 500 paquetes/s → igual que antes. La opción A (delay fijo) también descartada: batch inconsistente si el ritmo de producción varía.

### Solución: opción B — timeout 12ms por frame adicional
Cambio mínimo: `xQueueReceive(..., 0)` → `xQueueReceive(..., pdMS_TO_TICKS(12))` en el bucle interno.
- A 500 Hz (1 frame/2ms), UDP_Task espera el frame siguiente hasta 12ms → siempre llega en ~2ms → batch de 5 frames en ~10ms
- Tasa resultante: ~100 datagramas/s → dentro del límite lwIP
- Si no llega frame en 12ms (pausa/dropout), envía batch parcial y continúa — robusto
- Batch size máximo: 5 × ~230 bytes = ~1150 bytes < 1472 bytes MTU → sin fragmentación

### Archivos modificados
- `src/main.cpp`: comentario + `pdMS_TO_TICKS(12)` en bucle acumulación de UDP_Task

### Estado
Compilado OK (RAM 18.3%, Flash 29.8%). Flasheado a COM15. Script relanzado. **Verificado: cero GAP B/UDP, Ts_us ~20000 µs.** Problema resuelto.

## Sesión 2026-06-11c — Ajuste valores spo2_ema_mean/var_tau_s + warmup

### Motivación
Análisis crítico de los valores anteriores (1.6 s / 1.0 s):
- `spo2_ema_mean_tau_s = 1.6s` vs `rsqm_ema_mean_tau_s = 2.0s`: misma señal, mismo requisito físico (f_c << HR_min) → no hay justificación para que difieran
- `spo2_ema_var_tau_s = 1.0s`: ISO 80601-2-61:2026 Annex JJ.2 d) exige averaging time ≥ 6 s para un transfer standard (dispositivo de referencia) → 1.0 s es muy inferior al mínimo normativo

### Cambios en `incunest_afe4490.cpp`
- `spo2_ema_mean_tau_s`: 1.6 s → **2.0 s** (igual que rsqm_ema_mean_tau_s)
- `spo2_ema_var_tau_s`: 1.0 s → **6.0 s** (mínimo ISO JJ.2 d))
- `spo2_warmup_s`: 5.0 s → **18.0 s** (3 × τ_var = 18 s para convergencia del estimador)
- Comentarios de rationale actualizados con referencia normativa

### Estado
Compilado OK. Pendiente flash y commit.

## Sesión 2026-06-11b — Rationale para spo2_ema_mean/var_tau_s

Añadidos comentarios de justificación para los valores por defecto de SpO2 EMA en el bloque constexpr del cpp, siguiendo el estilo de los comentarios RSQM:
- `spo2_ema_mean_tau_s = 1.6s`: f_c ≈ 0.1 Hz < 0.5 Hz (30 bpm mín) → DC no sigue la componente pulsátil; rápido para adaptarse a reposicionamiento de sonda (~5s settle)
- `spo2_ema_var_tau_s = 1.0s`: cubre 2–2.7 ciclos cardíacos a HR neonatal 120–160 bpm; a 60 bpm ~1 ciclo; marginal a 30 bpm pero warmup de 5s lo mitiga

Compilado OK. Pendiente flash y commit.

## Sesión 2026-06-11a — Rename spo2_dc_iir_tau_s / spo2_ac_ema_tau_s

### Motivación
Tras el refactor de EmaChannel a τ, los nombres `spo2_dc_iir_tau_s` y `spo2_ac_ema_tau_s` seguían exponiendo detalles de implementación ("iir", "ema"). Siguiendo el patrón `{dominio}_ema_{componente}_tau_s` de las constantes RSQM:

### Renombrados
- `spo2_dc_iir_tau_s` → `spo2_ema_mean_tau_s` (config, privados, constexpr local, spec)
- `spo2_ac_ema_tau_s` → `spo2_ema_var_tau_s` (ídem)
- `setSpO2DcIirTauS()` → `setSpO2EmaMeanTauS()`
- `setSpO2AcEmaTauS()` → `setSpO2EmaVarTauS()`
- Comentarios descriptivos actualizados ("DC removal IIR" → "EMA mean (DC)", "AC² EMA" → "EMA variance (AC²)")

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`
- `incunest_afe4490/incunest_afe4490_spec.md`

### Estado
Compilado OK. Pendiente flash y commit.

## Sesión 2026-06-10t — EmaChannel: configuración por τ en lugar de α

### Motivación
Configurar `EmaChannel` con α es frágil: si `fs` cambia, todos los α en `AFE4490Config` hay que recalcularlos a mano. Con τ (segundos), el código calcula α internamente usando el fs real → la respuesta temporal del filtro se mantiene correcta automáticamente.

### Cambios en `incunest_afe4490.h`
- `EmaChannel`: `alpha_mean`/`alpha_var` públicos → privados `_alpha_mean`/`_alpha_var`
- Nuevo método `init(tau_mean_s, tau_var_s, fs)`: calcula α = 1 − exp(−1/(τ·fs)) internamente
- Nuevo método `reset()`: pone a cero mean/var/count sin tocar α (no necesita re-init)
- `update()` sin cambios (usa `_alpha_mean`/`_alpha_var` privados)
- `rsqm_ema_mean_alpha = 0.001f` → `rsqm_ema_mean_tau_s = 2.0f` [s]
- `rsqm_ema_var_alpha  = 0.0005f` → `rsqm_ema_var_tau_s  = 4.0f` [s]

### Cambios en `incunest_afe4490.cpp`
- Constructor: `_rsqm_led*_sub_ema{..., rsqm_ema_mean_alpha, rsqm_ema_var_alpha}` → `_rsqm_led*_sub_ema{}` (α se calcula en `_recalc_rate_params()`)
- `_recalc_rate_params()`: sustituidos los 4 bloques de asignación manual de alpha por llamadas `init()`:
  - `_spo2_ch_ir_ema.init(_spo2_dc_iir_tau_s, _spo2_ac_ema_tau_s, fs)`
  - `_spo2_ch_red_ema.init(...)` (ídem)
  - `_rsqm_led1_sub_ema.init(rsqm_ema_mean_tau_s, rsqm_ema_var_tau_s, fs)`
  - `_rsqm_led2_sub_ema.init(...)` (ídem)
- `_reset_algorithms()`: manual `mean=0/var=0/count=0` → `reset()` en los 4 canales

### Estado
Compilado OK (RAM 18.3%, Flash 29.8%). Pendiente flash y commit.

## Sesión 2026-06-10s — UDP: chequeos de seguridad MTU

### Motivación
Si en el futuro crece el tamaño de trama (nuevos campos en $M4) o se modifican las constantes de batch, el sistema podría superar el MTU sin ningún aviso.

### Cambios en `src/main.cpp`
1. **`#define UDP_MTU 1472`** — constante explícita para el payload máximo UDP sin fragmentación (Ethernet/WiFi)
2. **`static_assert`** — falla en build si `UDP_QUEUE_FRAME_SIZE × UDP_BATCH_SIZE > UDP_MTU`; protege contra cambios en constantes
3. **Warning runtime** — en UDP_Task, antes de `sendto()`: si `batch_len > UDP_MTU` → `# WARN UDP batch N bytes > MTU 1472`; detecta crecimiento real de tramas
4. **Check `sendto()` return** — si devuelve < 0 → `# ERR UDP sendto failed errno=N`

Compilado OK. Pendiente flash.

## Sesión 2026-06-10r — Fix comentario recvfrom en pulsenest_lab.py

Comentario en `_udp_reader` actualizado: "1 frame per datagram" → "up to UDP_BATCH_SIZE frames per datagram (~1150 bytes for 5×$M4)" para reflejar el batching actual. Commit `af7fcc1`.

## Sesión 2026-06-11a — SpO2 EMA tau: corrección por ISO 80601-2-61:2026 JJ.2 d)

### Problema detectado
Los valores anteriores de SpO2 EMA tau no tenían justificación sólida y estaban por debajo de los mínimos de la norma:
- `spo2_ema_mean_tau_s = 1.6 s` — incoherente con `rsqm_ema_mean_tau_s = 2.0 s` (misma señal, mismo requisito físico)
- `spo2_ema_var_tau_s = 1.0 s` — muy por debajo del mínimo de 6 s de la norma

### ISO 80601-2-61:2026 Annex JJ.2 d)
La norma exige que el transfer standard tenga un tiempo de averaging mínimo de **6 s** y máximo de **10 s** para la determinación de SpO2. Un valor de 1.0 s estaba muy por debajo de este mínimo.

### Cambios en `incunest_afe4490.cpp`
- `spo2_ema_mean_tau_s`: 1.6 → **2.0 s** (igual a `rsqm_ema_mean_tau_s` — misma señal, mismo requisito de tracking DC)
- `spo2_ema_var_tau_s`: 1.0 → **6.0 s** (mínimo ISO JJ.2 d) para averaging SpO2)
- `spo2_warmup_s`: 5.0 → **18.0 s** (3 × τ_var = 3 × 6 s, para convergencia del estimador EMA)

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

### Commit
`c35e1dc` en repo incunest_afe4490. Push a GitHub OK.

## Sesión 2026-06-11b — Flash OTA: error de placa + corrección

### Error cometido
Al hacer el flash OTA con `arp -a`, se identificaron 3 IPs en la subred 192.168.137.x.
Se probaron las IPs .253 y .140 con curl y ambas respondieron "Not found: /status".
Se flasheó .253 asumiendo que era la placa de PulseNest — **error**: .253 es "esp32s3-147560 IncuNest 17.A", no la placa de trabajo.
La placa correcta (IncuNest 16.A, MAC 10:51:DB:50:48:F8) está en **192.168.137.92**.

### Regla establecida
**Antes de cualquier flash OTA, verificar la MAC de la IP objetivo** y contrastarla con la MAC conocida de la placa de trabajo (10:51:DB:50:48:F8 para IncuNest 16.A).
Nunca flashear sin confirmación del usuario cuando hay ambigüedad de placa.

### Correcciones realizadas
1. Flash V16 firmware a la placa correcta: `curl POST http://192.168.137.92/update` → OK
2. Flash IncuNest V17 firmware (de `C:\PRJ\MOW\IncuNest\Firmware\motherBoard\.pio\build\IncuNest_V17\firmware.bin`) a la 17.A (.253) → OK

### IPs conocidas en la red (2026-06-11)
- 192.168.137.92  → MAC 10:51:db:50:48:f8 → **IncuNest 16.A** (placa PulseNest)
- 192.168.137.253 → MAC 10:20:ba:14:75:60 → IncuNest 17.A (otra placa, firmware IncuNest)

## Sesión 2026-06-11c — Análisis logging + eliminación filtro MOVING_AVERAGE

### Preguntas y aclaraciones de diseño
- **ESP_LOG vs Serial_printf:** `ESP_LOG*` van a UART0 (pines físicos), no a USB-CDC (COM15). En ESP32-S3 son puertos distintos. El script pulsenest_lab.py nunca los recibe. `Serial_printf` sí llega al script (serial + UDP). Los `ESP_LOG` de la librería están correctamente diseñados para IncuNest (donde `logI()` también usa `ESP_LOGI`).
- **Destinatario final de la librería:** IncuNest motherBoard (`C:\PRJ\MOW\IncuNest\Firmware\motherBoard`). PulseNest es solo plataforma de desarrollo/test.
- **Serial fallback cuando UDP desactivado:** bug identificado — cuando el usuario desactiva UDP desde el script, el ESP32 mantiene `g_wifi_ready=true` y sigue suprimiendo `$M*` en serial. Las tramas `# STAT` y `$TIMING` sí llegan porque usan `Serial_printf` sin esa guarda. Pendiente decidir solución (opción A: `$SET,udp,0`; opción B: duplicar siempre por serial).

### Eliminación filtro MOVING_AVERAGE
- Filtro MA de 8 muestras en `ppg_disp` sin utilidad real: fc ≈ 62 Hz a 500 Hz fs — no atenúa nada fisiológico.
- EMA descartado como sustituto: EMA es paso-bajo (rastrea DC), no paso-banda; inadecuado para display PPG. `EmaChannel` está diseñado para τ lentos (2–6 s) con media+varianza para RSQM/SpO2.
- Decisión: eliminar `MOVING_AVERAGE` del enum `AFE4490Filter`. Solo quedan `NONE` y `BUTTERWORTH`.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h` — eliminado `MOVING_AVERAGE` del enum, bloque miembros `_ppgdisp_ma_buf/idx/sum`, comentario actualizado
- `incunest_afe4490/incunest_afe4490.cpp` — eliminados inicialización, 4 resets y case `MOVING_AVERAGE` del switch
- `incunest_afe4490/incunest_afe4490_spec.md` — enum actualizado
- `PulseNest/src/main.cpp` — case `MOVING_AVERAGE` en `filter_str()` eliminado

## Sesión 2026-06-11d — Eliminación AFE4490Filter + simplificación setPPGDispFilter

### Decisión
Con solo `NONE` y `BUTTERWORTH` en el enum, `AFE4490Filter` era esencialmente un booleano sin utilidad real. `NONE` no tiene sentido para display PPG (señal con deriva DC) y los valores crudos ya están disponibles en `AFE4490Data` (`led1_sub`/`led2_sub`). El filtro Butterworth es siempre el correcto para `ppg_disp`.

### Cambios
- Eliminado `enum class AFE4490Filter` completamente
- `setPPGDispFilter(AFE4490Filter type, float f_low_hz, float f_high_hz)` → `setPPGDispFilter(float f_low_hz, float f_high_hz)` — Butterworth siempre activo
- Eliminado `ppgdisp_filter_type` de `AFE4490Config`
- Eliminado `_ppgdisp_filter_type` de miembros privados
- Switch en `_process_sample()` reemplazado por llamada directa a `_biquad_process()`
- Frame `$CFG`: eliminado campo `flt=`; pulsenest_lab.py muestra literal `BW`

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`
- `incunest_afe4490/incunest_afe4490_spec.md`
- `PulseNest/src/main.cpp`
- `PulseNest/pulsenest_lab.py`
- `incunest_afe4490/examples/basic/main.cpp`
- `PulseNest/examples/basic/main.cpp`

## Sesión 2026-06-11e — BiquadFilter autocontenida (estilo EmaChannel)

### Motivación
HGAC necesitará filtros para suavizar señales de control. Con la API antigua (`_recalc_biquad`, `_biquad_process` como métodos privados de la clase) el código de HGAC quedaría acoplado a INCUNEST_AFE4490. Se refactoriza `BiquadFilter` para que sea autocontenida como `EmaChannel`.

### Cambios de diseño
- `BiquadState` eliminado — `_v1`, `_v2` absorbidos en `BiquadFilter`
- `BiquadFilter` pasa a tener métodos propios: `init_bp(f_low, f_high, fs)`, `init_lp(f_high, fs)`, `process(x)`, `reset()`
- Coeficientes y estado son miembros privados de la struct
- Eliminados `_recalc_biquad()`, `_recalc_biquad_lp()`, `_biquad_process()` de INCUNEST_AFE4490
- Call sites actualizados: `_ppgdisp_bpf.process(x)`, `_hr2_bpf.reset()`, etc.
- Test helpers `test_recalc_biquad` / `test_biquad_process` eliminados (métodos ya son públicos en la struct)
- Constructor: defaults f_low/f_high fijados explícitamente antes de `_recalc_rate_params()`

### Uso en HGAC (ejemplo futuro)
```cpp
BiquadFilter _led_smooth_lp;
_led_smooth_lp.init_lp(0.5f, fs);
float smoothed = _led_smooth_lp.process(raw_value);
```

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-11f — Fix build: aggregate init BiquadFilter + flash OTA

### Bug
`_hr2_bpf` y `_hr3_bpf` aún tenían aggregate init antigua en el initializer list del constructor. Al hacer privados los miembros de `BiquadFilter` (sesión anterior), el aggregate init dejó de compilar. Corregido a `_hr2_bpf()` / `_hr3_bpf()` con defaults explícitos en el constructor body. Build y flash OTA OK.

### IP placa IncuNest 16.A actualizada
Era 192.168.137.92, ahora **192.168.137.209** (MAC 10:51:db:50:48:f8).

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-11g — Agrupación métodos BiquadFilter en .cpp

`init_lp` había quedado separado de `init_bp`/`process` por los métodos `_compute_settle_margin`/`_recalc_afe_tia_cf_led1/2`. Movido para que los tres métodos queden en un único bloque `// ── BiquadFilter methods ──` en orden: `init_bp`, `init_lp`, `process`.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-11h — BiquadFilter::process() inline

Comparación `BiquadFilter` vs `EmaChannel`: `EmaChannel::update()` es `inline`; `BiquadFilter::process()` no lo era. `process()` es hotpath a 500 Hz (llamado en `_process_sample`, `_update_hr2`, `_update_hr3`). Movido al `.h` como `inline`, eliminado del `.cpp`.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490.h`
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-11i — Spec SpO2 τ + fix comentarios desactualizados

### Spec actualizada (§5.1 y §10.3)
La spec tenía valores desactualizados (τ_mean=1.6 s, τ_var=1.0 s, warmup=5 s) y no documentaba la justificación de los dos τ distintos ni la referencia ISO.
- §5.1: añadida sección completa sobre EmaChannel — justificación de τ_mean=2.0 s y τ_var=6.0 s, referencia ISO 80601-2-61:2026 JJ.2 d), fórmula PI, warmup=18 s
- §10.3: tabla actualizada con valores correctos y columna de justificación
- §10.2: nombre de constante y valor corregidos

### Comentarios desactualizados en .cpp
Líneas 1700/1704 tenían `τ = 1.6 s` y `τ = 1.0 s`. Corregidos a 2.0 s y 6.0 s con referencia ISO en τ_var.

### Archivos modificados
- `incunest_afe4490/incunest_afe4490_spec.md`
- `incunest_afe4490/incunest_afe4490.cpp`

## Sesión 2026-06-12a — HR3 local SNR gate

### Contexto
Investigación del algoritmo HR3 en firmware y script: ¿se busca un pico real o simplemente el máximo del rango?

### Hallazgos
- **Firmware:** argmax en [search_min, search_max] + true-peak validation ±5 bins. La validación extiende fuera del rango (protege ante artefactos en el borde), pero no protege ante artefactos anchos **dentro** del rango de búsqueda.
- **HR3TestCalc (py):** `np.argmax(hps_hr)` puro — sin ninguna validación. Peor que firmware.
- **HRFFTCalc (py):** `signal.find_peaks` con prominence 5% → muy permisivo. Fallback a argmax.
- **Diagnóstico:** un hump de movimiento que pique dentro del rango de búsqueda → gana el argmax → validación ±5 bins lo confirma como máximo local → resultado incorrecto.

### Decisión de diseño: local SNR gate
Extensión del bloque "true-peak validation" existente:
- Acumular suma de vecinos en el **mismo bucle** ±`hr3_peak_valid_w=5` bins → coste cero adicional.
- Gate: `peak_hps < hr3_local_snr_k × mean_neighbours` → `sqi=0, return`.
- Independiente del rango de búsqueda (ventana fija ±0.49 Hz).
- Un pico cardíaco HPS es estrecho (Hann + refuerzo armónico) → peak/mean_nb alto (>5×).
- Un artefacto hump ancho → todos sus vecinos también son altos → peak/mean_nb ≈ 1.2–2× → rechazado.

### Cambios implementados
**`incunest_afe4490.cpp`:**
- Nueva constante `hr3_local_snr_k = 3.0f` (documentada con justificación física)
- Inicialización `_hr3_local_snr_k` en constructor
- `getConfig()`: `cfg.hr3_local_snr_k = _hr3_local_snr_k`
- `_compute_hr3()`: true-peak validation extendida — acumula `sum_neighbors/n_neighbors` en bucle existente, gate al final
- Nuevo setter `setHR3LocalSnrK(float k)`

**`incunest_afe4490.h`:**
- `AFE4490Config`: nuevo campo `hr3_local_snr_k`
- Declaración `setHR3LocalSnrK(float k)`
- Miembro privado `_hr3_local_snr_k`

**`PulseNest/src/main.cpp`:**
- `$SET,hr3_snrk,X` → `afe.setHR3LocalSnrK(X)`, rango 1.0–20.0
- `$CFG`: nuevo campo `,hr3_snrk=%.2f`

**`pulsenest_lab.py`:**
- `HR3TestCalc`: nuevas constantes `FW_PEAK_VALID_W=5`, `FW_LOCAL_SNR_K=3.0`; instancia `snr_k`; true-peak validation + local SNR gate (mirror exacto del firmware)
- `HRFFTCalc`: prominence 5%→20%; local SNR gate ±5 bins post-argmax
- `$CFG` display: muestra `HR3 SNR-k`

### Build
Compila OK. RAM 18.3%, Flash 29.9% (sin cambio).
Pendiente: flash OTA + validar con señal real.

---

## Sesión 2026-06-12b — HR3 SQI refactoring: eliminar SNR gate, SQI = local SNR normalizado

### Contexto
Después de implementar el local SNR gate en la sesión anterior, discusión profunda sobre la diferencia conceptual entre "validez" (gate binario) y "bondad" (métrica continua). Conclusión: SQI y SNR gate miden lo mismo — la prominencia espectral del pico HPS. El gate es redundante.

### Análisis de diseño
- **True-peak validation** (local max ±W): rechaza artefactos en bordes del rango donde existe un máximo real fuera del rango. Con un pico cardíaco limpio dentro del rango siempre pasará.
- **Local SNR gate** (`peak_hps ≥ k × mean_nb`): rechaza humps anchos. Pero si el hump pasa el gate, SQI también sería alto → gate y SQI dan información redundante.
- **Conclusión**: eliminar ambos (true-peak + SNR gate). SQI solo captura la calidad: hump ancho → hps_win grande → snr≈baseline → SQI=0; pico cardíaco → hps_num domina → SQI→1.

### Algoritmo HR3 definitivo (5 pasos)
1. `argmax(HPS)` en [search_min, search_max] → `peak_bin`, `peak_hps`
2. Interpolación parabólica sobre FFT² (no HPS) alrededor de `peak_bin` → `delta` → `peak_freq`
3. `b1 = floor(peak_bin + delta)`, `b2 = b1 + 1`; `hps_num = hps[b1] + hps[b2]`; `hps_win = Σhps[k]` para k∈[b1-W, b2+W]
4. `snr = hps_num / hps_win`; `baseline = 2 / n_win`
5. `SQI = clamp((snr - baseline) / (1 - baseline), 0, 1)`

**Nota clave sobre b1:** delta∈[-0.5, 0.5] → b1 = peak_bin o peak_bin-1 → peak_bin siempre está en {b1, b2} → hps_num ≥ peak_hps siempre.

### Cambios implementados

**`incunest_afe4490.cpp`:**
- Eliminado bloque true-peak validation + SNR gate de `_compute_hr3()`
- Constructor: eliminada inicialización `_hr3_local_snr_k`
- `getConfig()`: eliminado `cfg.hr3_local_snr_k`
- Eliminado `setHR3LocalSnrK()`
- SQI: renombrado constante `hr3_sqi_local_w` → `hr3_snr_local_w`; variable `fraction` → `snr`; comentario actualizado para reflejar diseño definitivo

**`incunest_afe4490.h`:**
- Eliminado campo `hr3_local_snr_k` de `AFE4490Config`
- Eliminada declaración `setHR3LocalSnrK(float k)`
- Eliminado miembro privado `_hr3_local_snr_k`

**`PulseNest/src/main.cpp`:**
- Eliminado handler `$SET,hr3_snrk`
- Eliminado `,hr3_snrk=%.2f` de frame `$CFG`

**`pulsenest_lab.py`:**
- `HR3TestCalc`: eliminados `FW_PEAK_VALID_W`, `FW_LOCAL_SNR_K`, `self.snr_k`; añadido `FW_SNR_LOCAL_W=5`; eliminado bloque true-peak + SNR gate; SQI actualizado a fórmula de dos bins en ventana local (espejo exacto del firmware); docstring actualizado
- `HRFFTCalc`: eliminado `find_peaks` con prominencia y SNR gate → argmax puro como firmware
- `$CFG` display: eliminada referencia `HR3 SNR-k`

### Pendiente
Flash OTA + validar con señal real.

---

## Sesión 2026-06-12c — Rename _hr{2,3}_sqi_result → _hr{2,3}_result_sqi

### Motivación
Coherencia de nomenclatura: `_hr3_result` es el HR (bpm), `_hr3_result_sqi` es la calidad de ese resultado. El orden `result_sqi` agrupa los dos campos de output de HR3 juntos conceptualmente y alfabéticamente. El nombre anterior `_hr3_sqi_result` invertía la jerarquía. Se renombran ambos (hr2 y hr3) para mantener consistencia.

### Cambios
**`incunest_afe4490.h`:** `_hr2_sqi_result` → `_hr2_result_sqi`, `_hr3_sqi_result` → `_hr3_result_sqi`; comentarios `_compute_hr2()`/`_compute_hr3()` actualizados.

**`incunest_afe4490.cpp`:** todos los usos renombrados con replace_all.

### Build
OK. RAM/Flash sin cambio.

---

## Sesión 2026-06-12c — HR3TEST: fw encima de py en plots 3 y 4

### Cambio
En `HR3TestWindow`, el trazo verde (firmware) ahora se superpone por encima del trazo amarillo (script Python) en las gráficas 3 (HR3 fw/py) y 4 (SQI fw/py).

### Causa
En pyqtgraph el z-order de las curvas sigue el orden de creación: la última añadida queda encima. Anteriormente `curve_hr_py` y `curve_sqi_py` se añadían después de las fw, quedando el amarillo encima.

### Solución
Reordenación del orden de `.plot()` en `_setup_plots()` de `HR3TestWindow`:
- Plot 3: `curve_hr_py` primero → `curve_hr_fw` → `curve_hr_fw_lo` encima
- Plot 4: `curve_sqi_py` primero → `curve_sqi_fw` encima

**Fichero modificado:** `pulsenest_lab.py` (líneas 3992–3998).

---

## Sesión 2026-06-12e — Diagnóstico Ts_us: instrumentación timing snprintf M3 vs M4

### Problema investigado
`Ts_us` (delta entre muestras consecutivas) da ~2100 µs en modo $M4 y ~2000 µs en $M3.

### Análisis
- `getData()` usa `xQueueReceive(..., 0)` — **no bloqueante**. `Incunest_Task` es un bucle de polling.
- Con polling: si la iteración completa tarda > 2000 µs, el siguiente `getData()` encuentra el dato ya en la queue → retorna inmediatamente → `micros()` se lee tarde → delta > 2000 µs.
- Causa probable: `snprintf` de $M4 (8 floats extra en `%.4e`) supera el budget de 2000 µs.
- Fix real: necesita confirmación empírica del coste de snprintf antes de decidir solución (separar formateo a tarea separada vs. otro enfoque).

### Instrumentación implementada (`main.cpp`)
- Flag `#define SNPRINTF_TIMING` al inicio del fichero — **comentar para eliminar toda la instrumentación**.
- `struct SnprintfStats` con métodos `record(dt)` y `report(label)` — stats min/avg/max sobre ventana de 500 muestras (1 segundo a 500 Hz).
- Instancias estáticas `_snp_m3` y `_snp_m4` antes de `Incunest_Task`.
- En rama M3: `micros()` antes/después del `snprintf` principal → `_snp_m3.record()` → report cada 500 muestras por serial.
- En rama M4: ídem con `_snp_m4`.
- Todo el código de timing envuelto en `#ifdef SNPRINTF_TIMING`.

### Build
OK. RAM/Flash sin cambio significativo.

## Sesión 2026-06-12f — Fix Ts_us: vTaskDelay al else de getData()

### Problema
`Ts_us` reportaba ~2100 µs en modo $M4 en lugar de 2000 µs. Con $M3 daba ~2000 µs.

### Diagnóstico (con SNPRINTF_TIMING)
- snprintf M4: avg ~1073 µs, max hasta 4049 µs
- snprintf M3: avg ~735 µs, max hasta 3381 µs

El `vTaskDelay(pdMS_TO_TICKS(1))` corría **incondicionalmente** después de cada frame procesado. Resultado: ~1073 µs (snprintf M4) + ~1000 µs (delay) ≈ 2073 µs por iteración → Ts_us promedio ~2100 µs. Con M3: ~735 + ~1000 = ~1735 µs < 2000 µs → el bucle esperaba al siguiente DRDY → Ts_us ~2000 µs.

### Fix (`main.cpp`)
`vTaskDelay(pdMS_TO_TICKS(1))` movido al `else` de `getData()`: solo se ejecuta cuando no hay dato disponible (para no quemar CPU en polling). Cuando hay dato, se procesa y se vuelve al bucle inmediatamente sin delay artificial.

### Build
OK. Pendiente: flash OTA + verificar Ts_us ~2000 µs en M4.

## Sesión 2026-06-12d — HR3TEST: leyenda truncada "HR3 fw (SQI<0.9)" → "SQI<0.9"

### Cambio
`curve_hr_fw_lo` renombrada de `"HR3 fw (SQI<0.9)"` a `"SQI<0.9"` — el texto anterior se truncaba en el carácter `<` en la leyenda del plot 3.

**Fichero modificado:** `pulsenest_lab.py` (línea 3994).

---

## Sesión 2026-06-12e — HR3TEST: escape HTML en leyenda SQI<0.9

### Problema
pyqtgraph renderiza las leyendas con HTML. El carácter `<` en `"SQI<0.9"` era interpretado como inicio de etiqueta HTML, truncando el texto visible.

### Solución
Sustituido `<` por la entidad HTML `&lt;` → `name="SQI&lt;0.9"`. pyqtgraph lo muestra como `SQI<0.9`.

**Fichero modificado:** `pulsenest_lab.py` (línea 4007).

---

## Sesión 2026-06-13b — UDP worker: log IP origen primera trama + detección cambio IP

En `_udp_worker()`, añadida variable local `_known_ip`:
- **Primera trama recibida:** log `[UDP] First datagram from <ip>` + asigna `self._esp32_ip`
- **Tramas siguientes:** si la IP de origen cambia, log `[UDP] Source IP changed: <old> → <new>` + actualiza `_known_ip` y `self._esp32_ip`

Sustituye la comprobación anterior `if self._esp32_ip is None` (que solo cubría la primera trama).

**Fichero modificado:** `pulsenest_lab.py` (~línea 9742).

---

## Sesión 2026-06-13a — Fix docstring HR3TestCalc.update()

Corregido docstring de `HR3TestCalc.update()` (línea 3710): `"Process one 50 Hz sample"` → `"Process one sample at the given fs"`. El método acepta `fs` como parámetro dinámico y no está atado a ninguna frecuencia concreta.

**Fichero modificado:** `pulsenest_lab.py` (línea 3710).

---

## Sesión 2026-06-12g — Eliminar SNPRINTF_TIMING

Instrumentación temporal eliminada de `main.cpp` tras confirmar el fix de Ts_us:
- `#define SNPRINTF_TIMING` y bloque de comentario
- `struct SnprintfStats` + instancias `_snp_m3`/`_snp_m4`
- Bloques `#ifdef SNPRINTF_TIMING` en ramas M3 y M4

Build OK.

---

## Sesión 2026-06-12h — HR3: estimador de Jacobsen para sub-bin interpolación

### Problema observado
Con simulador a 60/65/70/75 BPM, HR3 daba 59.38/64.72/70.15/75.51 — error sistemático de hasta ±0.62 BPM. HR1 y HR2 < 0.1 BPM.

### Análisis
La interpolación parabólica sobre `|FFT[k]|²` (potencia, escala lineal) subestima el desplazamiento fraccional del bin en ~50% para una ventana Hann. La ventana Hann no tiene un lóbulo principal parabólico en escala lineal — es más ancho en la base, lo que reduce el "curvature" aparente y encoge la delta estimada. Datos confirman ratio estimada/real ≈ 0.52–0.57 consistentemente.

### Fix: estimador de Jacobsen
Exacto para un tono puro con ventana Hann. Usa los valores complejos del FFT:
`delta = Re{ (X[k+1] - X[k-1]) / (2·X[k] - X[k+1] - X[k-1]) }`
Los valores complejos ya están disponibles en `_hr3_fft` (formato interleaved re/im de `_fft_r2`).

### Cambios
**`incunest_afe4490.cpp`:** interpolación parabólica reemplazada por estimador de Jacobsen.

**`pulsenest_lab.py`:** `HR3TestCalc` y `HRFFTCalc` actualizados — `fft_cplx` guardado de `np.fft.rfft`; interpolación parabólica reemplazada por Jacobsen.

### Pendiente
Verificar con simulador a 60/65/70/75 BPM que el error baja a < 0.1 BPM.


---

## Sesión 2026-06-12i — HR3: estimador Gaussiano en sustitución de Jacobsen

### Problema
Los resultados con el estimador de Jacobsen implementado en la sesión anterior eran **peores** que la interpolación parabólica original:
- Simulador 60/65/70/75 BPM → HR3: 57.90/64.18/70.47/76.76 (errores hasta ±2.1 BPM)
- Con parabólico anterior: 59.38/64.72/70.15/75.51 (errores hasta ±0.62 BPM)

### Diagnóstico
Análisis analítico de la DFT de una señal Hann-windowed real:

Para un tono a bin N₀+ε (ε=0.24 para 60 BPM):
- `X[N₀]   ∝ +e^(jπε) × 0.482`
- `X[N₀+1] ∝ -e^(jπε) × 0.341`  ← signo NEGATIVO (factor e^(-jπ) = -1)
- `X[N₀-1] ∝ -e^(jπε) × 0.163`  ← signo NEGATIVO (factor e^(+jπ) = -1)

El numerador de Jacobsen: `X[k+1] - X[k-1] = e^(jπε)×(-0.341) - e^(jπε)×(-0.163) = e^(jπε)×(-0.178)`

El signo del numerador se **invierte** porque los bins adyacentes al pico llevan el factor de fase `e^{±jπ} = -1` en la DFT de una señal Hann-windowed real. Esto hace que el estimador de Jacobsen dé `δ ≈ −0.5×δ_true` en lugar de `+δ_true`.

Verificación numérica:
- Jacobsen: δ = Re{-0.178/1.468} = -0.121 (vs δ_true=+0.24 → ratio -0.5) ✓
- Parabólico en |X|²: δ ≈ 0.139 (vs δ_true=0.24 → ratio 0.58) ✓

### Fix: interpolación Gaussiana
La interpolación Gaussiana (parábola en log|X|²) esquiva completamente el problema de fase: trabaja sólo en amplitudes. Para ventana Hann da `δ ≈ 1.07×δ_true`:

```
δ = 0.5 × (log|X[k-1]|² - log|X[k+1]|²) / (log|X[k-1]|² - 2·log|X[k]|² + log|X[k+1]|²)
```

Verificación para ε=0.24: δ_Gauss = 0.258 (vs δ_true=0.24, error +7.5%) → error HR < 0.11 BPM. Mejora 6× respecto al parabólico, >20× respecto a Jacobsen.

### Cambios
**`incunest_afe4490.cpp`:** bloque Jacobsen (re/im) reemplazado por cómputo de `p_m/p_c/p_p` (potencias), `logf()` y fórmula Gaussiana. `delta = 0.5f*(lm-lp)/denom`.

**`pulsenest_lab.py`:** Jacobsen reemplazado en `HR3TestCalc.update()` y `HRFFTCalc.update()` por la misma fórmula con `np.log`.

### Build
OK (incunest_V16). OTA pendiente (ESP32 no visible en red al final de sesión).

---

## Sesión 2026-06-12j — Incidente OTA + comentario baseline SQI + estrategias SQI HR3

### Incidente OTA (placa incorrecta)

Se flasheó firmware PulseNest a `192.168.137.246` (MAC `10:20:BA:14:75:60` = IncuNest 17.A) en lugar de IncuNest 16.A. Consecuencia: lecturas LED saturadas en esa placa (pin mapping incorrecto para V17).

**Causa:** no se cruzó la MAC antes de flashear. El procedimiento correcto:
1. `arp -a | grep 192.168.137` → anotar IP candidata
2. Verificar que la MAC sea `10:51:DB:50:48:F8` (IncuNest 16.A = target de PulseNest)
3. Solo entonces flashear

Dispositivos conocidos memorizados en `hardware_mac_addresses.md`.

Flash correcto hecho a continuación a `192.168.137.212` (IncuNest 16.A).

### Resultados Gaussiana con simulador

- 60 BPM → 60.07 (+0.07)
- 65 BPM → 65.03 (+0.03)
- 70 BPM → 69.97 (−0.03)
- 75 BPM → 74.90 (−0.10)

Error máximo 0.10 BPM. Commits pusheados a ambos repos.

### Comentario baseline SQI (incunest_afe4490.cpp)

Añadido comentario en línea 2069 explicando por qué `baseline = 2.0f / n_win`:
el numerador `hps_num = hps[b1] + hps[b2]` abarca exactamente 2 bins, por lo que en un espectro HPS plano (ruido puro) la fracción esperada es `2/n_win`. Con ese ancla: SQI=0 si el pico no destaca sobre el ruido, SQI=1 si toda la energía está en b1+b2.

### Discusión estrategias SQI HR3 (pendiente de implementar)

Problema: `hr3_result_sqi > 0.9` con sonda no aplicada (picos espurios en FFT/HPS).

Estrategias discutidas:
- **A. Gate por amplitud absoluta (RMS del buffer en tiempo):** más directo para sonda no aplicada. Umbral a calibrar.
- **B. Gate por ProbeState:** forzar SQI=0 si `probe_state != APPLIED`. Simple pero introduce acoplamiento HR3↔RSQM y tiene latencia EMA.
- **C. Verificación de armónicos independiente:** exigir que P[k], P[2k] y P[3k] superen individualmente el nivel de ruido (no solo su producto HPS). Más robusto.
- **D. Denominador global:** usar suma total del HPS en todo el rango de búsqueda como denominador (en vez de ventana local ±W).
- **E. Consistencia temporal:** detectar saltos bruscos entre estimaciones consecutivas.

Recomendación acordada: implementar A + C en ese orden. Pendiente.

---

## Sesión 2026-06-14a — Retrofit tooltips: parámetro src

### Cambio aplicado en `pulsenest_lab.py`

**Nueva regla:** todo tooltip debe incluir el nombre del elemento de código fuente del que depende.

**Implementación:**
- `_make_tooltip(name, text, src="")` — nuevo parámetro opcional `src`. Se renderiza al pie del tooltip en monospace azul claro con icono 📎.
- Retrofitados ~60 tooltips con `src`. Controles actualizados:
  - SpO2Lab calibration, SpO2Test params (spo2_a/b, spo2_ema_mean/var_tau_s, spo2_warmup_s, spo2_min_dc)
  - HR1Test params (hr1_dc_iir_tau_s … hr1_refractory_s)
  - HR2Test params (hr2_bpf_low/high_hz, hr2_buf_len, hr2_max_lag, hr2_update_n, hr2_min_lag_s, hr2_min_corr)
  - HR3Test params (hr3_bp_low/high_hz, hr3_buf_len, hr3_update_n, hr3_hps_harmonics)
  - PILab (PICalc.step1/2/3, tau_sub/ac/norm_s, bpf_lo/hi_hz, win_s, hr_bpm, n_harm, lpf_fc_hz, win_norm_s)
  - PPG checkboxes ×2 (AFE4490Data::led1_raw/aled1/led1_sub/led2_raw/aled2/led2_sub)
  - HW Config: migrado `\nLib: ... · Script: ...` embebido → `src="AFE4490Config::..."` / `src="AFE4490TimingConfig::..."`
  - Sidebar: combo_port, spin_decim, frame_mode_combo ($MODE,M{1-4}), spin_stats_interval
  - Sweep/Capture: _spin_settle, _spin_samples

---

## Sesión 2026-06-13b — Renombrado convención EmaChannel

### Cambio aplicado en `incunest_afe4490.h`

Decisión de nomenclatura: adoptar patrón `<calificador>_<concepto>` de forma consistente en `EmaChannel`.

| Antes | Después |
|---|---|
| `_alpha_mean` | `_mean_alpha` |
| `_alpha_var` | `_var_alpha` |
| `tau_mean_s` (param `init()`) | `mean_tau_s` |
| `tau_var_s` (param `init()`) | `var_tau_s` |

Los callers de `.init()` usan args posicionales → no requieren cambios.

---

## Sesión 2026-06-13a — Análisis comparativo SQI firmware vs HR3TestCalc

### Hallazgo: HR3TestCalc tiene un bug de fs

`SPO2_RECEIVED_FS = 50.0` (línea 208) tiene el comentario "SERIAL_DOWNSAMPLING_RATIO=10", pero actualmente los frames M3/M4 llegan a **500 Hz** (SERIAL_DOWNSAMPLING_RATIO=1). HR3TestCalc recibe datos a 500 Hz pero usa `fs=50.0`, con estas consecuencias:

| Aspecto | Firmware HR3 | HR3TestCalc (Python, buggeado) |
|---|---|---|
| Filtro | LP biquad 10 Hz @ 500 Hz | BP Butterworth 0.4–15 Hz diseñado @ 50 Hz, aplicado @ 500 Hz → cutoffs reales **4–150 Hz** |
| Ventana | 512 @ 50 Hz = 10.24 s | 512 @ 500 Hz = **1.024 s** |
| Rango búsqueda | 0.617–4.383 Hz reales ✓ | Etiquetado 0.617–4.383 Hz pero frecuencias reales **5.86–43.9 Hz** (= 350–2630 BPM) |
| Actualización | cada 0.5 s | cada **50 ms** |
| Fórmula SQI | — | idéntica |

### Por qué HR3TestCalc da menos falsos positivos

HR3TestCalc busca casualmente en el rango 5.86–43.9 Hz (fuera de cualquier HR fisiológico), donde el ruido es más plano → SQI naturalmente bajo. No es un diseño superior sino un efecto colateral del bug.

### Conclusión para el diseño del SQI

El firmware SQI es vulnerable a **ruido de baja frecuencia estructurado** (EMI, deriva, movimiento de cables) en 0.6–4.4 Hz que aparece dominante localmente → SQI > 0.9 con sonda no aplicada.

Las estrategias correctas siguen siendo **A (gate por amplitud RMS)** + **C (verificación de armónicos independiente)** según lo decidido en sesión 2026-06-12j.

### Pendiente

1. **Corregir el bug de SPO2_RECEIVED_FS en HR3TestCalc** — pasar el `fs` correcto (500 Hz) para que el mirror sea fiel al firmware.
2. **Implementar Estrategia A** en firmware: gate por RMS del buffer `_hr3_buf`. Si RMS < umbral → `_hr3_result_sqi = 0`.
3. **Implementar Estrategia C** en firmware: verificar que P[k], P[2k], P[3k] superan individualmente el nivel de ruido (mediana del espectro × factor).

## Sesión 2026-06-14e — PILAB: fix cuelgue por bucle layout Qt (columnas demasiado estrechas)

### Causa raíz

Con `stretch=1` el panel derecho recibía ~350px divididos entre dos columnas = **~175px cada una**. Cada columna contiene un `QScrollArea` con `setWidgetResizable(True)` y un `QFormLayout` con ~15 filas. El ancho mínimo del contenido (~200px) superaba el ancho disponible (175px), por lo que Qt añadía scrollbar horizontal → viewport más estrecho → resize del contenido → scrollbar → bucle infinito → UI completamente bloqueada.

### Fix aplicado

- `root.addWidget(gv, stretch=3→2)` y `root.addLayout(right, stretch=1→2)`: el panel derecho ahora recibe ~50% del ancho (~400px por columna)
- `setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` en cada `QScrollArea` de columna: elimina el bucle de redimensionado incluso si el contenido sobrepasa el ancho
- `self.resize(1400→1800, 900)` como tamaño por defecto
- Borrada la geometría guardada en `pulsenest_lab.ini` `[PILabWindow]` para que no restaure la ventana antigua de 1400px

## Sesión 2026-06-14d — PILAB: fix cuelgue por stylesheet con border-radius

`border: 1px solid {color}; border-radius: 4px` aplicado a `tab_widget` (QWidget padre de QScrollArea) causaba repintado indefinido en PyQt5 — el estilo se propagaba a todos los widgets hijo. Fix: eliminar el `setStyleSheet` del QWidget contenedor y también quitar el `border-bottom` del header label. Solo se conserva el color y font del header para identificar la columna.

## Sesión 2026-06-14c — PILAB: layout columnas A/B + números más grandes

### Cambios en PILabWindow (_build_ui + _make_config_tab)

- Eliminado `QTabWidget`: Instance A e Instance B ahora son **dos columnas siempre visibles** en un `QHBoxLayout`
- Cada columna tiene un encabezado de color (`border: 1px solid color`, label "Instance A/B" en 16px bold) para identificarlas sin pestañas
- Tabla de valores: `font-size` subido de 14px → **20px** (valores PI_ir, PI_red, R, AC_r_ir); encabezados de 13px → 16px; `setMinimumHeight(200)` + `setMaximumHeight(240)`

## Sesión 2026-06-14b — PILAB: mover botón al grupo LAB

Botón PILAB movido en el sidebar de PPGMonitor: estaba junto a HR3TEST (grupo TEST); ahora está justo debajo de SPO2LAB (grupo LAB). Razón: PILAB no compara contra el firmware, es un laboratorio de investigación puro → pertenece al grupo LAB junto a HR2LAB, HR3LAB, SPO2LAB.

## Sesión 2026-06-14a — Implementación PILAB (PICalc + PILabWindow)

### Objetivo

Ventana de investigación para comparar distintas definiciones de Perfusion Index (PI).
Diseñada como pipeline de 3 pasos independientes, con dos instancias en paralelo (A vs B).

### Clases nuevas en pulsenest_lab.py

**`PICalc`** — pipeline configurable:
- STEP1 (DC subtraction): S1_EMA (τ_sub), S1_BPF (Butterworth BP), S1_NONE
- STEP2 (AC estimator): S2_EMA_RMS (τ_ac), S2_WIN_RMS, S2_PEAKPK, S2_SPECTRAL (FFT), S2_HARMONICS (FFT armónicos)
- STEP3 (DC denominator): S3_EMA (τ_norm), S3_LPF (Butterworth LP), S3_WIN_MEAN
- Outputs: `pi_ir`, `pi_red`, `R`, `ac_r_ir`, `ac_r_red`, `dc_r_ir`, `dc_r_red`, `dc_sub_ir`, `dc_sub_red`
- Instancia A arranca con defaults del firmware M1: S1=EMA τ=2s, S2=EMA-RMS τ=6s, S3=EMA τ=2s

**`PILabWindow`** — ventana de investigación:
- 4 gráficas apiladas: señal IR + DC_sub, AC_r, PI_ir, R ratio
- Panel derecho con tabs A (naranja) y B (azul): configuración de los 3 pasos + botón APPLY
- Tabla de valores actuales: PI_ir, PI_red, R, AC_r_ir
- Modos: live (feed_sample() por muestra desde drain loop) + offline (LOAD CSV)
- Botones: LOAD CSV, LIVE, PAUSE

### Integración en PPGMonitor

- `pilab_window = None` en `__init__`, `_pilab_refresh_counter`, `_PILAB_REFRESH_EVERY=2`
- Timing key `plot_pilab` añadida al dict `_py_timing`
- Drain loop: `pilab_window.feed_sample(led1_sub, led2_sub, SPO2_RECEIVED_FS, ts_us)`
- Render tick: `pilab_window.update_plots()` cada 2 ticks (~10 Hz)
- Sidebar: botón **PILAB** debajo de HR3TEST
- `toggle_pilab()` + `_open_pilab_default()`
- `_save_settings`/`showEvent`/`closeEvent`/`_bring_all_to_front` actualizados

### Decisiones de diseño

- La frontera hardware→fisiológico ocurre dentro de los algoritmos (p[7]=led1_sub → ir, p[6]=led2_sub → red)
- M5 (optical transmittance) descartado: los factores de normalización se cancelan en el ratio PI_red/PI_ir = R, no aporta nada nuevo
- `_apply_config()` limpia buffers de plot para que la comparación empiece desde cero tras cada APPLY
- STEP1=NONE solo tiene sentido con métodos espectrales (2.4/2.5) — el usuario es responsable de combinar correctamente
- `reconfigure()` se llama automáticamente en `update()` cuando `fs` cambia (lazy reconfigure)

## Sesión 2026-06-14b — Tooltip src: botones de ventana + filas SIGNAL STATS

### Cambios en `pulsenest_lab.py`

**Botones de ventana (sidebar):** se añadió `src="ClassName"` a los 17 botones que abren ventanas secundarias (más `btn_ppgplots` añadido en sesión anterior), de forma que el tooltip de cada botón muestra el nombre de la clase Python correspondiente:

| Botón | src |
|---|---|
| PPGPLOTS | `PPGPlotsWindow` |
| SIGNALS | `PPGSignalsWindow` |
| RESULTS | `AlgoResultsWindow` |
| SERIALCOM | `SerialComWindow` |
| UDP COM | `UdpComWindow` |
| HR2LAB | `HRLabWindow` |
| HR3LAB | `HR3LabWindow` |
| SPO2LAB | `SpO2LabWindow` |
| SPO2TEST | `SpO2TestWindow` |
| HR1TEST | `HR1TestWindow` |
| HR2TEST | `HR2TestWindow` |
| HR3TEST | `HR3TestWindow` |
| PILAB | `PILabWindow` |
| ESP32 TIMING | `Esp32TimingWindow` |
| PYTHON TIMING | `PythonTimingWindow` |
| HW CONFIG | `HWConfigWindow` |
| DIAGNOSTICS | `DiagnosticsWindow` |
| AFE SWEEP | `AFESweepTestWindow` |

**SIGNAL STATS — `_STATS_SIGNALS`:** refactorizado de 3-tuplas a 4-tuplas `(display_name, data_attr, tooltip_description, src)`. Cada fila de la tabla muestra ahora en su tooltip el campo de firmware del que procede el dato:

- Señales PPG crudas → `AFE4490Data::led1_raw`, `::led2_raw`, `::aled1`, `::aled2`, `::led1_sub`, `::led2_sub`, `::ppg_disp`
- SpO2/HR → `AFE4490Data::spo2`, `::spo2_sqi`, `::spo2_r`, `::pi`, `::hr1..hr3`, `::hr1_sqi..hr3_sqi`, `::rsqi`, `::diag_code`, `::probe_state`
- Debug analog ($M4) → `AFE4490DebugData::v_tia_led1/led2/aled1/aled2`, `::i_pd_led1/led2/aled1/aled2`
- OT calculado en script → `PPGMonitor.data_ot2_led1`, `PPGMonitor.data_ot2_led2`

Todos los sitios de desempaquetado de `_STATS_SIGNALS` actualizados para 4-tuplas (líneas 9163, 9671, 10702, 11105, 11138, 11169, 11234).

### Decisión

Regla establecida (ya en memoria): todo tooltip incluye el `src` del elemento de código fuente del que depende. Los botones de acción pura (sin ventana asociada) no llevan `src`.

## Sesión 2026-06-14f — Fix OT_LED1/2 a cero hasta abrir HW CONFIG

### Bug

OT_LED1 y OT_LED2 en SIGNAL STATS permanecían a cero hasta abrir la ventana HW CONFIG. La causa: el cálculo de OT usa `cfg.get("led1","0")` de `_last_cfg`, pero `_last_cfg` solo se poblaba al recibir un `$CFG` frame, que solo se solicitaba si HW CONFIG estaba abierta.

### Dos rutas afectadas en `pulsenest_lab.py`

**1. Al conectar serial** (`_connect_serial`):
- Antes: `QTimer.singleShot(2500, lambda: hw_config_window._on_read_cfg() if hw_config_window is not None else None)` → no-op si HW CONFIG cerrada.
- Después: `QTimer.singleShot(2500, lambda: self.request_chip_config(notify_lab_capture=False))` → siempre envía `$CFG?`.

**2. Al detectar `# incunest_afe4490 started`** (firmware boot):
- Antes: `$CFG?` solo si `_post_reset_cfg_pending` (reset manual) y `hw_config_window` abierta.
- Después: siempre `request_chip_config(notify_lab_capture=False)`. `_post_reset_cfg_pending` se limpia incondicionalmente. HW CONFIG sigue actualizándose automáticamente vía `_on_cfg_frame_received → update_from_cfg(kv)`.

### Resultado

`_last_cfg` se popula 2.5 s después de conectar, sin necesidad de abrir HW CONFIG. OT_LED1/2 muestran valores reales desde el inicio.

## Sesión 2026-06-14e — Negrita en tooltip ProbeState + soporte <b> en _make_tooltip

### Cambios en `pulsenest_lab.py`

**`_make_tooltip` — soporte de negrita inline:** `_esc()` ahora restaura `<b>`/`</b>` tras escapar el resto del HTML. Permite usar `<b>texto</b>` en cualquier parámetro `text` de `_make_tooltip` sin modificar la firma. Ningún tooltip existente se ve afectado.

**ProbeState tooltip:** la línea "Not DISCONNECTED AND OT ≤ 8.5×10⁻⁵ on both channels" ahora aparece en negrita, resaltando el criterio de APPLIED respecto a los otros estados.

## Sesión 2026-06-14d — ProbeState tooltip algoritmo completo + unidades I_PD en tabla

### Cambios en `pulsenest_lab.py`

**Display names I_PD en `_STATS_SIGNALS`:** renombrados para mostrar la unidad en la columna Signal:
- `"I_PD_LED1"` → `"I_PD_LED1 [µA]"`
- `"I_PD_LED2"` → `"I_PD_LED2 [µA]"`
- `"I_PD_ALED1"` → `"I_PD_ALED1 [µA]"`
- `"I_PD_ALED2"` → `"I_PD_ALED2 [µA]"`

Motivación: el tooltip de ProbeState referencia estas filas con umbral en µA (0.15 µA), así el lector puede correlacionar directamente valor de tabla con umbral.

**Tooltip ProbeState:** ampliado de una línea legend a descripción completa del algoritmo RSQM:
- **DISCONNECTED** (AND de 6): |I_PD_*| < 0.15 µA (4 canales) AND |LED1/2_SUB| < 5000 ADC. Nota redundancia intencional led_sub vs i_pd (guarda AMBDAC).
- **NOT_APPLIED** (OR): OT_LED1 > 8.5×10⁻⁵ OR OT_LED2 > 8.5×10⁻⁵; saturación ADC (≥2 096 921) fuerza OT=100.
- **APPLIED**: no disconnected AND OT ≤ 8.5×10⁻⁵ en ambos canales.
- Debounce: 100 muestras consecutivas (200 ms a 500 Hz) en todas las transiciones.

## Sesión 2026-06-14c — Renombrar rsqm_disconn_sub_mean → rsqm_disconn_led_sub_thr

### Cambio

`incunest_afe4490.h` y `incunest_afe4490.cpp`: renombrado `rsqm_disconn_sub_mean` → `rsqm_disconn_led_sub_thr`.

### Motivación

- `_mean` era incorrecto semánticamente: es un **umbral** (threshold), no una media.
- `rsqm_disconn_led_sub_thr` es más explícito sobre la señal (`led_sub`) y simétrico con el parámetro vecino `rsqm_disconn_i_pd_thr`.
- El comentario también se corrigió: `|led_aled|` → `|led_sub|`.

## Sesión 2026-06-13c — Sincronización τ SpO2 Python mirror con firmware

### Diagnóstico

`SpO2TestCalc` en `pulsenest_lab.py` tenía τ desactualizados respecto al firmware tras el refactoring de `EmaChannel` (sesión 2026-06-11c).

| Constante | Python (antes) | Firmware |
|---|---|---|
| `FW_DC_IIR_TAU_S` | 1.6 | **2.0** (`spo2_ema_mean_tau_s`) |
| `FW_AC_EMA_TAU_S` | 1.0 | **6.0** (`spo2_ema_var_tau_s`, ISO 80601-2-61:2026 JJ.2 d) |
| `FW_WARMUP_S` | 5.0 | **18.0** (3 × τ_var) |
| `FW_SPO2_MIN_DC` | 1000.0 | 1000.0 ✓ |

### Decisión

Actualizar las tres constantes en `SpO2TestCalc` para que el mirror Python calcule PI y SQI con los mismos parámetros que el firmware. Las fórmulas ya eran equivalentes (ambas usan `1 - exp(-1/(τ×fs))` como peso sobre la muestra nueva).

### Cambio aplicado

`pulsenest_lab.py` — constantes clase `SpO2TestCalc`:
```python
FW_DC_IIR_TAU_S = 2.0   # spo2_ema_mean_tau_s (EmaChannel τ_mean)
FW_AC_EMA_TAU_S = 6.0   # spo2_ema_var_tau_s  (EmaChannel τ_var, ISO 80601-2-61:2026 JJ.2 d ≥ 6 s)
FW_WARMUP_S     = 18.0  # spo2_warmup_s = 3 × τ_var
```

## Sesión 2026-06-14f — Diagnóstico de hang al arrancar pulsenest_lab.py

### Problema

El script `pulsenest_lab.py` se bloqueaba al arrancar tras los cambios de la sesión 14e (layout PILAB en columnas + fix INI).

### Investigación

Se creó `diag_hang.py` para aislar el problema. Hallazgos:

1. **Sintaxis OK** — `ast.parse()` con UTF-8 sin errores.
2. **El código no bloquea** — `diag_hang.py` replicó exactamente el bloque `if __name__ == '__main__':` (QApplication, setStyle, setStyleSheet, PPGMonitor, show, event loop) y funcionó 30s sin problema.
3. **Drain/render/bring_all_to_front** — todos completan sin bloqueo.
4. **INI correcta** — todas las claves `key=value` (sin espacios), `pilab_open=false`.

### Estado al final de sesión

El diagnóstico muestra que el código es correcto. El script se relanzó al final de la sesión para verificar con el usuario si el problema persiste. Resultado pendiente de confirmar.

### Fichero diagnóstico creado

`diag_hang.py` — script temporal de diagnóstico (no producción).

## Sesión 2026-06-14g — PILAB: fuentes más grandes en config panel y tabla

### Cambio

`pulsenest_lab.py` — `PILabWindow._make_config_tab` + tabla de valores:

| Elemento | Antes | Después |
|---|---|---|
| SpinBox / ComboBox (`_ss_spin`, `_ss_cb`) | 14px | 17px |
| Labels STEP1/2/3 (`_lbl_sty`) | 14px | 17px |
| Labels de fila del form ("Method:", "τ_sub:", etc.) | sin estilo | 17px (via `inner.setStyleSheet QLabel`) |
| Tabla datos (`QTableWidget`) | 20px | 24px |
| Tabla cabeceras (`QHeaderView::section`) | 16px | 20px |
| Tabla `setMinimumHeight` / `setMaximumHeight` | 200/240 | 240/300 |

## Sesión 2026-06-14h — PILAB: botón de ayuda con explicación de las cuatro gráficas

### Cambio

`pulsenest_lab.py` — `PILabWindow`:

- Añadido botón `?` en la toolbar (derecha, separado por stretch).
- Nuevo método `_show_help()`: abre `QDialog` no-modal con texto HTML que explica las 4 gráficas y el pipeline de 3 pasos (DC tracking, AC estimator, PI_ir, ratio R para SpO2).

## Sesión 2026-06-14i — pulsenest_lab_spec.md actualizada a v1.4

### Cambios en la spec

- Versión: 1.3 → 1.4
- §5.6 PICalc: nueva entrada (remite a §7.11 para detalle completo)
- §6.1 Sidebar: grupos LAB y TEST ahora etiquetados explícitamente; PILAB añadido al LAB group
- §6.6 Throttle rates: añadido `_PILAB_REFRESH_EVERY = 2` (10 Hz)
- §7.11 PILabWindow (nueva): descripción completa — PICalc pipeline 3-step, layout, 4 plots, config columns A/B, value table, help dialog, feed architecture, offline mode
- §9 Settings: añadido `PILabWindow/geometry` y `PPGMonitor/pilab_open`
- §10 Tooltip convention: `_make_tooltip(name, text, src="")` — documenta parámetro `src` opcional
- §12 Changelog: entrada v1.4 añadida

### Aclaración al usuario

La spec **no se actualiza automáticamente** — hay que actualizarla manualmente en la misma sesión en que se modifica el código.

## Sesión 2026-06-14j — PILAB: aumento de fuentes en controles y tabla

### Cambio

`pulsenest_lab.py` — `PILabWindow._make_config_tab()` y `_build_ui()`:

Aumentados todos los tamaños de fuente del panel de configuración y la tabla inferior derecha:

| Elemento | Antes | Ahora |
|---|---|---|
| Spinboxes / ComboBoxes (`_ss_spin`, `_ss_cb`) | 17px | 20px |
| Títulos STEP1/2/3 (`_lbl_sty`) | 17px | 20px |
| Labels de fila del form (QLabel inner) | 17px | 20px |
| Header "Instance A / B" | 16px | 20px |
| Celdas de la tabla (`QTableWidget`) | 24px | 28px |
| Cabeceras de fila/columna (`QHeaderView::section`) | 20px | 24px |

## Sesión 2026-06-14k — Fix: UDP first-packet activation

### Problema

La app se "bloqueaba" (aparecía congelada) al arrancar si no recibía tramas. El problema se correlacionó con la introducción de PILabWindow pero era independiente de ella.

### Diagnóstico

Causa raíz en dos capas:

1. **`_render_pending = False`** suprime TODO el render tick cuando no hay datos nuevos — incluyendo updates que deberían ser independientes de los datos.

2. **UDP se activaba como transporte antes de recibir ningún datagrama.** En `_connect_udp()` se ejecutaba `self._active_transport = "udp"` inmediatamente al arrancar el thread. Si el ESP32 sólo era alcanzable por USB (serial) y no por WiFi, las tramas serial llegaban al `_serial_queue` pero el drain tick las ignoraba (`if not _is_active: continue`). Resultado: `_new_data = False` → `_render_pending = False` → la app aparecía completamente congelada aunque el serial reader recibía 500 tramas/segundo.

La conexión con PILabWindow fue coincidencial: el commit de PILabWindow incluyó `pilab_open=true` en el INI, haciendo que el problema (pre-existente desde la introducción de UDP en `af7fcc1`) se manifestara de forma más obvia.

### Fix implementado — first-packet UDP activation

`pulsenest_lab.py`:

- **`_sig_udp_active = QtCore.pyqtSignal()`** — nueva señal emitida por `_udp_reader` al recibir el primer datagrama.
- **`_connect_udp()`** — ya NO pone `_active_transport = "udp"` inmediatamente. Botón muestra `UDP WiFi ● LISTEN (:{port})` (azul tenue) mientras espera el primer datagrama. Serial sigue activo.
- **`_udp_reader()`** — cuando `_known_ip is None` (primer datagrama): `self._sig_udp_active.emit()`.
- **`_on_udp_active()`** — nuevo slot (main thread): pone `_active_transport = "udp"`, actualiza botón a `UDP WiFi ● ON`, loguea el cambio.

### Comportamiento nuevo

| Estado | Transporte activo | Botón UDP |
|---|---|---|
| UDP no conectado | serial | `UDP WiFi ● OFF` |
| UDP conectado, sin datagramas | serial | `UDP WiFi ● LISTEN (:7788)` |
| UDP recibe primer datagrama | udp | `UDP WiFi ● ON (:7788)` |
| UDP desconectado | serial | `UDP WiFi ● OFF` |

## Sesión 2026-06-14l — Continuación: verificación fix UDP first-packet

Sesión de continuación tras compactación de contexto. Sin cambios adicionales de código.
Fix de sesión 2026-06-14k deployado y script relanzado. Pendiente confirmación del usuario de que el bloqueo está resuelto.

## Sesión 2026-06-15a — Regresión freeze: investigación + debug logging

### Problema

Tras el fix UDP first-packet (sesión k), el usuario reporta freeze peor que antes: se cuelga incluso cuando el firmware está enviando tramas.

### Diagnóstico

**Debug logging añadido a `_process_frames_tick`** (temporal, para diagnóstico):
- Fichero `C:\PRJ\MOW\PulseNest\debug_drain.log`
- Registra cada ~1 segundo si no llegan datos: `[T{n}] NO_DATA streak=...`
- Captura excepciones con traceback

**Resultado del log al reproducir freeze:**
```
[T1] NO_DATA streak=1 transport=serial serial_q=0 udp_q=0 paused=False pilab=False
```
Solo una entrada → el QTimer del drain **deja de disparar después del primer tick** (~20ms). El main thread Qt se bloquea.

**Pista clave del usuario:** el freeze solo ocurre con **"PPG Signals" + "HW CONFIG" ambas abiertas**. Ninguna por separado lo produce.

### Root cause identificado

Cadena exacta:
1. `showEvent` → `singleShot(0ms, _open_hw_config_default)`
2. `toggle_hw_config` → `singleShot(200ms, hw_config_window._on_read_cfg)`
3. A los 200ms: serial aún conectando → `request_chip_config` falla → `_warn_not_connected()` → **`QMessageBox.warning()` modal**
4. El event loop Qt entra en el exec del modal → QTimers dejan de disparar → freeze total

Con PPGSignals también abierta, pyqtgraph tarda más en inicializar → más probable que el serial no esté listo a los 200ms.

El bug existía antes de PILabWindow (la combinación HWConfig+PPGSignals ya activaba el QMessageBox), pero se hizo más evidente porque el commit de PILabWindow guardó en el INI `hw_config_open=true` + `signals_open=true`.

### Fix aplicado

Nuevo método `_auto_read_cfg` en `HWConfigWindow`: igual que `_on_read_cfg` pero sin `QMessageBox.warning()` — solo actualiza el statusbar si el serial no está listo.

`toggle_hw_config` cambiado de `singleShot(200, _on_read_cfg)` → `singleShot(200, _auto_read_cfg)`.

El botón "Read" manual sigue usando `_on_read_cfg` (con modal) — correcto para acción explícita del usuario.

### Fix anterior incorrecto → root cause real

El fix de `_auto_read_cfg` (sin QMessageBox) no resolvió el freeze. El log de debug reveló el root cause real:

```
[BRING] complete       ← _bring_all_to_front termina OK
(silencio total)       ← drain timer deja de disparar
```

**Root cause real:** `AttachThreadInput(my_tid, fg_tid, True)` + múltiples `SetForegroundWindow()` en secuencia rápida → Windows encola WM_ACTIVATE/WM_DEACTIVATE para cada ventana → Qt queda bloqueado procesando esos mensajes de activación cuando hay ≥2 ventanas con intercambio de foco.

Con solo una ventana (HWConfig o PPGSignals): un solo SetForegroundWindow → un solo WM_ACTIVATE → Qt lo procesa sin problema.
Con dos ventanas: signals → hw_config → Qt recibe WM_DEACTIVATE(signals) + WM_ACTIVATE(hw_config) en el mismo ciclo → bloqueo.

### Fix final aplicado

`_bring_all_to_front` simplificado: **eliminados `AttachThreadInput` y `SetForegroundWindow`**. Solo `show()` + `raise_()` + `activateWindow()` para cada ventana. Suficiente para restaurar ventanas al primer plano. Sin llamadas Win32 de bajo nivel que puedan corromper la cola de mensajes de Qt.

### Código de debug temporal: eliminado

- `_dbg_log()`, `_dbg_tick_n`, `_dbg_no_data_streak` — eliminados de `PPGMonitor`
- Instrumentación en `_process_frames_tick` y `_bring_all_to_front` — eliminada
- `debug_drain.log` puede borrarse del directorio del proyecto

### Investigación continúa — nuevas pistas

- **Fix `AttachThreadInput` tampoco resuelve** el freeze (confirmado por usuario)
- **Freeze es intermitente** — no siempre ocurre con PPGSignals+HWConfig
- **Clave:** cuando hace freeze, aparece "Connecting to COM11..." pero NO "UDP listening on port..." → el main thread se bloquea entre `_connect_serial` (singleShot 50ms) y `_connect_udp` (singleShot 150ms)

### Trazas `[DBG]` añadidas (temporal)

Para acotar exactamente dónde se bloquea:
- `[DBG] joining reader thread...` / `[DBG] join done` — en `_connect_serial` si `_reader_thread` no es None
- `[DBG] _connect_serial: bg thread started, returning to event loop` — final de `_connect_serial`
- `[DBG] _connect_udp: entered` — inicio de `_connect_udp`
- `[DBG] _connect_udp: joining udp thread...` / `join done` — si `_udp_thread` no es None

Pendiente: reproducir freeze y reportar qué trazas aparecen.

## Sesión 2026-06-15b — Acotación freeze 130ms→150ms + logging a fichero

### Hallazgo

Con las trazas `self.log("[DBG] probe Xms")` el usuario confirma: **70ms, 100ms y 130ms aparecen en el log UI, pero 200ms no**. El bloqueo ocurre entre **130ms y 150ms** (el singleShot(150) de `_connect_udp` tampoco dispara).

### Problema con self.log()

Al congelarse la UI, los mensajes pendientes quedan en cola y no son legibles. `debug_probe.log` no existía porque era código de la sesión anterior ya limpiado.

### Fix: _flog() con escritura a fichero

Reemplazadas las lambdas por `_flog()` local en `showEvent`:
- Escribe inmediatamente a `debug_probe.log` con `open/write/flush` (funciona aunque UI esté congelada)
- Incluye tiempo **real** desde `_t0` (`perf_counter`) para detectar si los probes llegan tarde por bloqueo previo en singleShot(0)
- Probes: 0ms, 70ms, 100ms, 130ms, 200ms

También añadida traza al inicio de `_on_serial_result`: `[DBG] _on_serial_result: entered success=...`

### Pendiente

Reproducir freeze → leer `debug_probe.log` con `! type C:\PRJ\MOW\PulseNest\debug_probe.log`.

## Sesión 2026-06-15b — Nuevas trazas de diagnóstico para acotar freeze

### Estado anterior

- Confirmado: `_connect_serial` (singleShot 50ms) sí dispara → aparece "Connecting to COM11..."
- Confirmado: `_connect_udp` (singleShot 150ms) NUNCA dispara → "[DBG] _connect_udp: entered" no aparece
- `_reader_thread` es None en primer arranque → no hay join blocking en `_connect_serial`
- El bloqueo ocurre entre t=50ms y t=150ms (ventana de 100ms)

### Hipótesis principal

Pyqtgraph initial render de `PPGSignalsWindow` (muchos PlotWidgets) puede tomar 100-200ms en el main thread procesando paint events. Si ese render ocurre entre t=50ms y t=150ms, el singleShot(150) no dispara.

Alternativa: `_on_serial_result` (emitido por bg thread via QueuedConnection) podría ejecutarse en esa ventana y hacer algo bloqueante.

### Trazas nuevas añadidas

1. **`_on_serial_result`**: `[DBG] _on_serial_result: entered success=True/False` al inicio
2. **Probes de timing en `showEvent`**:
   - `[DBG] probe 70ms`
   - `[DBG] probe 100ms`
   - `[DBG] probe 130ms`
   - `[DBG] probe 200ms`

Objetivo: ver cuál probe aparece o no para acotar exactamente cuándo se bloquea el event loop.

### Pendiente

Reproducir freeze con las nuevas trazas y analizar output del log.

## Sesión 2026-06-15c — Root cause encontrado y fix aplicado

### Metodología: diagnóstico autónomo (sin interacción del usuario)

- **Heartbeat autónomo**: QTimer 500ms → fichero. Si valor deja de avanzar = event loop congelado.
- **Bisect git**: `64960ea` (pre-PILab) no congela; `d327669` (PILab) congela.
- **Tests aislados con ini**: signals sola / hw_config solo / ambas / ninguna / `_bring_all_to_front` desactivada.

### Tabla de resultados

| Configuración | Resultado |
|---|---|
| signals=false, hw_config=false | OK |
| signals=true, hw_config=false | OK |
| signals=false, hw_config=true | OK |
| signals=true, hw_config=true | FREEZE |
| signals=true, hw_config=true, `_bring_all_to_front` desactivada | OK |
| signals=true, hw_config=true, fix aplicado | OK |

### Root cause

`_bring_all_to_front` llamaba `raise_()` sobre todas las subventanas. Con PPGSignalsWindow (pyqtgraph) + HWConfigWindow juntas: el cambio de foco entre ellas al ejecutar `raise_()` genera mensajes WM_PAINT diferidos que el event loop Qt procesa 2-3 segundos después, bloqueando el event loop indefinidamente cuando pyqtgraph intenta re-renderizar en cascada.

El commit PILab eliminó `AttachThreadInput` de `_bring_all_to_front`. Con AttachThreadInput los threads compartían cola de mensajes y WM_PAINT se procesaba de forma ordenada. Sin él, el desorden de mensajes causa el hang.

### Fix

`_bring_all_to_front` simplificado: solo levanta la ventana principal. Las subventanas ya son visibles desde `toggle_xxx()`.

```python
def _bring_all_to_front(self):
    # raise_() on pyqtgraph windows enqueues deferred WM_PAINT messages that
    # block the event loop seconds later when multiple windows are open.
    self.show()
    self.raise_()
```

### Limpieza

Todo el código de debug temporal eliminado: heartbeat timer, _dbgfile, _flog, probes, [DBG] traces en serial/UDP.

---

## Sesión 2026-06-15d — Freeze continúa: investigación profunda

### Estado heredado

- Fix 15c ("raise solo ventana principal") fue confirmado insuficiente: usuario reportó "se sigue congelando".
- Debug actual: `_bring_all_to_front = pass` (no-op completo), heartbeat QTimer 500ms → `debug_hb.log`, drain/render escriben a `debug_last.log`.

### Evidencia acumulada

| Configuración | Resultado |
|---|---|
| signals=false, hw_config=false | OK |
| signals=true, hw_config=false | OK |
| signals=false, hw_config=true | OK |
| signals=true, hw_config=true | FREEZE ~30s |
| `_bring_all_to_front` = no-op + ambas ventanas | FREEZE ~30s |

- `debug_last.log`: `render_skip 49652.469` (render_pending=False, render saltado)
- `debug_hb.log`: `49652.647` — heartbeat disparó 178ms después de render_skip, luego PARA
- Drain anterior fue T1294 × 20ms ≈ 26s desde inicio

### Hallazgo: diff entre commits 64960ea y d327669

`git diff 64960ea d327669` reveló que `_bring_all_to_front` NO cambió entre commits — es exactamente la misma función en ambos. La versión pre-PILab tenía: `AttachThreadInput + raise_() + activateWindow() + SetForegroundWindow()` para CADA ventana.

El diff solo añade: PICalc class, PILabWindow class, tooltip `src=` param, SpO2 constants (tau 2/6s, warmup 18s), _pilab_refresh_counter.

### Nueva hipótesis (WM_PAINT diferidos)

Windows difiere WM_PAINT hasta ~26-30s cuando las ventanas no han respondido activamente a sus paints. Con `AttachThreadInput + SetForegroundWindow` (versión pre-PILab), cada `SetForegroundWindow(winId)` forzaba WM_PAINT inmediato — las ventanas se pintaban una a una a t=300ms de forma segura.

Sin `SetForegroundWindow`, los WM_PAINT se acumulan hasta que Windows los fuerza todos a ~26s simultáneamente. Con PPGSignalsWindow (pyqtgraph) + HWConfigWindow juntas, este paint concurrente diferido crea el deadlock.

Fixes previos con solo `raise_()` (Fix 3) también fallaron porque `raise_()` encola WM_PAINT pero no los despacha síncronamente. Solo `SetForegroundWindow` o `repaint()` fuerza dispatch síncrono.

### Fix aplicado (misma sesión)

**`_bring_all_to_front`** — sustituido no-op por `repaint()` síncrono en todas las ventanas abiertas:

```python
def _bring_all_to_front(self):
    self.show()
    self.raise_()
    for w in [self.ppgplots_window, self.signals_window,
              self.hr3lab_window, self.serialcom_window,
              self.results_window, self.hw_config_window]:
        if w is not None:
            w.repaint()
```

**`PPGSignalsWindow._setup_ui`** — `disableAutoRange()` en los 3 ViewBoxes (p1, p2, p3) tras su creación.

**Limpieza debug temporal:** eliminados heartbeat timer `_hb`, write a `debug_last.log` en inicio y fin de drain tick, write a `debug_last.log` en render tick.

### Pendiente

Confirmar que el freeze está resuelto (test ≥60 s con signals + hw_config ambas abiertas).

---

## Sesión 2026-06-15j

### Tema: Diagnóstico definitivo y fix del freeze — causa raíz: puerto Bluetooth

### Diagnóstico

Continuando la sesión anterior, el freeze persistía con `serial_connected=true` + `signals_open=true` incluso con `_bring_all_to_front = pass` y sin debug writes.

**Investigación sistemática (tests autónomos con `freeze_test.py`):**

| Configuración | Resultado |
|---|---|
| `serial=false`, `signals=true` | 2/2 PASS |
| `serial=true`, `signals=true` (COM99 → fallback COM11) | 2/2 FREEZE @~33s |
| `serial=true`, `signals=false` (COM99 → fallback COM11) | 2/2 FREEZE @~33s |
| `serial=true`, `signals=true` (COM99 → blank, con fix) | 3/3 PASS |
| `serial=true`, `signals=true`, `hw_config=true`, COM15 | 3/3 PASS |

**Causa raíz identificada:**

`_populate_ports()` usaba `idx if idx >= 0 else 0` — si el puerto guardado en el ini (`COM99`) no estaba disponible, hacía fallback al primer puerto del combo en orden alfabético: **COM11 = "Standard Serial over Bluetooth link"** (driver Microsoft Bluetooth).

Abrir un puerto Bluetooth serie a 921600 baud causa que el driver Bluetooth de Windows inicie un intento de conexión. Después de ~30 s (timeout Bluetooth), el driver envía un evento/mensaje al loop de Windows, que interfiere con el message pump de Qt → freeze.

El "freeze" con `signals=true` de sesiones anteriores era **el mismo bug**: el combo caía en COM11 en todos los tests porque `combo_port=COM99` no estaba en la lista.

### Fix aplicado

**`_populate_ports()` en `pulsenest_lab.py`:** eliminado el fallback `else 0`. Ahora usa `setCurrentIndex(idx)` — si la porta no está en la lista, el combo queda sin selección (index -1, texto vacío). `_connect_serial("")` detecta el puerto vacío y retorna `"No port selected"` sin intentar conectar.

```python
self.combo_port.setCurrentIndex(idx)  # -1 si no encontrado → sin auto-connect
```

**Heartbeat timer `_hb`:** mantenido en producción para permitir tests de regresión con `freeze_test.py`.

**`freeze_test.py`:** `STARTUP` reducido de 30 a 10 s.

### Resultado final

3/3 PASS con scenario de producción completo: `combo_port=COM15` (FTDI USB real) + `serial_connected=true` + `signals_open=true` + `hw_config_open=true`, con heartbeat real.

---

## Sesión 2026-06-15k

### Tema: Fix PICalc — dc_sub cero para S1_BPF y S1_NONE

### Bug

Al cambiar el "Method:" de PILAB a "1.2 BPF" o "1.3 None", la primera gráfica (dc_sub A/B) se ponía a cero.

### Causa

En `PICalc.update()`, los casos `S1_BPF` y `S1_NONE` asignaban `dc_sub_ir = dc_sub_red = 0.0` explícitamente.

### Fix

- **S1_BPF:** `dc_sub = ir − ac_bpf` → muestra el componente de baja frecuencia que el BPF elimina
- **S1_NONE:** `dc_sub = ir` → señal raw como referencia (nada se resta, paso directo)

---

## Sesión 2026-06-15l

### Tema: PILab Help — font al doble

- Título: 20px → 40px
- Body: 15px → 30px
- h3: 16px → 32px
- Ventana: 640×560 → 900×800

---

## Sesión 2026-06-15m

### Tema: PPG Signals — separador de miles en eje Y

Añadida clase `_ThousandsAxisItem(pg.AxisItem)` que sobreescribe `tickStrings()` para formatear los valores del eje Y con espacio fino (U+2009) como separador de miles. Aplicada a los 3 plots de PPGSignalsWindow (p1, p2, p3) via `axisItems={'left': ...}`.

---

## Sesión 2026-06-15n

### Tema: PPGSignalsWindow Y-axis — fix etiquetas desaparecidas

La primera implementación de `_ThousandsAxisItem` no multiplicaba por `scale` (parámetro de pyqtgraph para prefijos SI) y no manejaba excepciones. Esto causaba que algunos ticks devolvieran strings vacíos.

Fix: `tickStrings()` ahora multiplica por `scale`, usa `round()` en lugar de `int()`, aplica formato decimal cuando `spacing * scale < 1.0`, y captura cualquier excepción devolviendo `""` en lugar de crashar.

---

## Sesión 2026-06-15o

### Tema: PPGSignalsWindow Y-axis — tercera iteración + estrategia de versioning

### Fix `_ThousandsAxisItem` (3ª iteración)

Causa raíz: pyqtgraph aplica auto-prefijos SI (µ, m, k, M) que cambian `scale` a valores distintos de 1, provocando formateo incorrecto.

Solución definitiva:
- `enableAutoSIPrefix(False)` en `__init__` — desactiva el mecanismo SI, `scale` siempre vale 1
- `tickStrings()` usa los valores `v` directamente (sin multiplicar por `scale`)
- Separador: espacio fino U+2009 vía `.replace(",", "\u2009")`
- Decimales: `abs(spacing) >= 1.0` → entero; caso contrario → `int(-log10(abs(spacing)))+1` decimales
- Pendiente confirmar por el usuario.

### Estrategia de versioning propuesta

Para revertir a estados conocidos-buenos, se propone usar **git tags** semánticos:
- Convención: `v{APP_VERSION}-{slug}` (e.g., `v1.6.3-yaxis-thousands`)
- Tag preventivo antes de cambio arriesgado: `v1.6.3-pre-yaxis`
- Revertir un fichero: `git checkout <tag> -- pulsenest_lab.py`
- Pendiente: acordar con el usuario y crear primer tag.

---

## Sesión 2026-06-15p

### Tema: PPGSignalsWindow Y-axis — diagnóstico del bug + fix con U+202F

### Diagnóstico

Investigación del código fuente de pyqtgraph (`AxisItem.py`) para encontrar la causa de las etiquetas desaparecidas. Hallazgos:
- `tickStrings()` recibe `spacing` en coordenadas raw de datos
- `textFillRatio` para eje izquierdo usa suma de **alturas** (no anchuras) → ancho del string no afecta al crowding
- `p.boundingRect(QRectF(0,0,100,100), AlignCenter, s)` — sin flag `TextWordWrap`

Hipótesis confirmada: `\u2009` (THIN SPACE, U+2009) tiene `Line_Break = Breaking_Space (BA)` en Unicode — es un punto de corte de línea válido. El motor de texto DirectWrite/Qt en Windows puede word-wrappear strings como "200 000" dentro del rect 100×100 aunque no se pida explícitamente, doblando la altura medida del bounding rect. Esto dispara `textFillLimits` prematuramente y suprime etiquetas de niveles secundarios.

### Fix (4ª iteración)

Sustitución de `\u2009` por `\u202f` (NARROW NO-BREAK SPACE, U+202F):
- Visualmente idéntico al thin space
- `Line_Break = Glue (GL)` — **no es un punto de corte de línea**, no causa word-wrap
- `enableAutoSIPrefix(False)` mantenido
- `axisItems={'left': _ThousandsAxisItem(...)}` en p1, p2, p3 de PPGSignalsWindow
- **NO funcionó** — mismo efecto colateral (etiquetas desaparecidas).

---

## Sesión 2026-06-15q

### Tema: PPGSignalsWindow Y-axis — 5ª iteración con coma como separador

Descartado `\u202f` (también falla). Prueba con coma `","` estándar (sin reemplazar nada), manteniendo `enableAutoSIPrefix(False)`.
**NO funcionó** — mismo efecto colateral.

### Conclusión

Todas las variantes del separador fallan (`\u2009`, `\u202f`, `,`). El problema no está en el carácter separador sino en la subclase `_ThousandsAxisItem` o en `enableAutoSIPrefix(False)`. Funcionalidad descartada — revertido a `da9ab98` (sin separador de miles).

---

## Sesión 2026-06-15r

### Tema: SIGNAL STATS — OT_LED1/OT_LED2 formato 6 decimales

Cambiado el formato de las columnas Mean/Min/Max para las filas OT_LED1 y OT_LED2 de notación científica (`:.2e`) a 6 decimales (`:.6f`). Línea ~10873 de `pulsenest_lab.py`.

---

## Sesión 2026-06-15s

### Tema: Bug — `data_ot_led1`/`data_ot_led2` no inicializados en M1 path

### Bug

En el path M1 (`lib_id == "M1"`), línea ~11313, se referenciaban `self.data_ot_led1` y `self.data_ot_led2` (sin "2") que nunca fueron inicializados como atributos de instancia. El atributo correcto es `data_ot2_led1`/`data_ot2_led2` (con "2"), que sí se inicializa como deque en `__init__` y se appende correctamente dos líneas más abajo.

### Causa del cierre automático (hipótesis)

El M1 path se usa cuando el frame mode es `$M1`. Si el ESP32 enviaba algún frame M1, el `AttributeError` propagaba fuera del `except ValueError: pass`, llegaba al slot del timer Qt y podía abortar el event loop — explicando el cierre inesperado tras tiempo de funcionamiento.

### Fix

Eliminada la línea con `data_ot_led1`/`data_ot_led2`. El `data_ot2_led1`/`data_ot2_led2` ya se appende correctamente en la línea siguiente.

---

## Sesión 2026-06-15r

### Tema: SIGNAL STATS — OT_LED1/OT_LED2 formato 6 decimales

Cambiado el formato de las columnas Mean/Min/Max para las filas OT_LED1 y OT_LED2 de notación científica (`:.2e`) a 6 decimales (`:.6f`). Línea ~10873 de `pulsenest_lab.py`.

---

## Sesión 2026-06-15t

### Tema: PILabWindow — colores en cabeceras de tabla + persistencia de configuración en ini

### Colores cabeceras tabla

Problema: ambas cabeceras ("A (orange)" y "B (blue)") se mostraban en gris porque el stylesheet `QHeaderView::section { color: #AAAAAA }` sobreescribe el `ForegroundRole` de cada item.

Fix: eliminado `color` del stylesheet de `QHeaderView::section` (añadido `font-weight: bold`). Tras `setHorizontalHeaderLabels()`, se llama `horizontalHeaderItem(0).setForeground(QColor(CLR_A))` y `horizontalHeaderItem(1).setForeground(QColor(CLR_B))`.

### Persistencia de configuración en ini

`closeEvent` guarda todos los parámetros A/B en `PILabWindow/A/*` y `PILabWindow/B/*` (13 valores por instancia: s1/s2/s3 indices, tau_sub, bpf_lo/hi, tau_ac, win_s, hr_bpm, n_harm, tau_norm, lpf_fc, win_norm).

`__init__` reordenado: `_build_ui()` → restaurar geometría → restaurar config desde ini → `_apply_config()`.

---

## Sesión 2026-06-15u

### Tema: PILabWindow Plot 1 — DC_sub → AC_t (onda pulsátil STEP1)

### Motivación

`dc_sub` mostraba el componente de baja frecuencia eliminado por STEP1 — poca utilidad diagnóstica. `ac_t` es la onda pulsátil real que sale de STEP1 y que STEP2 intenta medir en amplitud. Ver A vs B en `ac_t` permite comparar directamente cómo cada método filtra la señal cardíaca.

### Cambios

**PICalc:**
- Añadido `self.ac_t_ir = 0.0; self.ac_t_red = 0.0` como outputs en `__init__` y `reset()`
- Al final del bloque STEP1 (tras if/elif/else): `self.ac_t_ir = ac_ir; self.ac_t_red = ac_red`

**PILabWindow:**
- Plot 1: label `"IR signal [ADC]"` → `"AC_t [ADC] — STEP1 output"`
- `curve_dc_a/b` → `curve_act_a/b`, names `"DC_sub A/B"` → `"AC_t A/B"`
- `feed_sample` y offline path: `_dc_sub_a/b` ahora almacena `calc.ac_t_ir` (no `dc_sub_ir`)
- `update_plots`: usa `curve_act_a/b`

---

## Sesión 2026-06-15v

### Tema: Crash logger global (sys.excepthook → crash.log)

El script se cerraba inesperadamente sin dejar traza alguna (pythonw suprime stderr).

Añadido al inicio de `pulsenest_lab.py` (tras imports):
```python
sys.excepthook = _crash_handler  # escribe traceback en crash.log
```

Cualquier excepción no capturada en el hilo principal queda registrada en `crash.log` con timestamp. Permite diagnosticar cierres inesperados futuros.

---

## Sesión 2026-06-15w

### Tema: Commit final — crash logger + PICalc AC_t + PILabWindow Plot1

Commit `9ab9b27`: agrupa los cambios pendientes de las sesiones 15u y 15v:
- `sys.excepthook → crash.log` (crash logger global)
- `PICalc.ac_t_ir/ac_t_red` como outputs del STEP1
- PILabWindow Plot 1 muestra `AC_t` (onda pulsátil STEP1) en lugar de `DC_sub`

---

## Sesión 2026-06-15x

### Tema: PILabWindow — desactivar parámetros irrelevantes según combo STEP

Nuevo método `_refresh_param_state(cfg)` en `PILabWindow`. Al cambiar cualquier combo STEP1/2/3, los spinboxes que no aplican al método seleccionado se desactivan (`setEnabled(False)`) junto con su label (`form.labelForField(widget).setEnabled(False)`).

**Mapeo activo:**
- STEP1: EMA→tau_sub; BPF→bpf_lo+bpf_hi; None→ninguno
- STEP2: EMA_RMS→tau_ac; WIN_RMS/PEAKPK→win_s; SPECTRAL/HARMONICS→hr_bpm; HARMONICS→n_harm
- STEP3: EMA→tau_norm; LPF→lpf_fc; WIN_MEAN→win_norm

**Implementación:**
- `_ss_spin` extendido con `QDoubleSpinBox:disabled` / `QSpinBox:disabled` → color #505050, bg #1A1A1A
- `inner.setStyleSheet` extendido con `QLabel:disabled { color: #454545 }`
- `cfg` dict incluye `'form': form` para acceder a `labelForField`
- Combos conectados a `_refresh_param_state` vía `currentIndexChanged`
- Llamado también en `__init__` tras `_apply_config` para estado inicial correcto

---

## Sesión 2026-06-15y

### Tema: PILabWindow — tabla expandida a 8 filas con desglose completo del pipeline

Tabla ampliada de 4 → 8 filas para mostrar el desglose completo del pipeline PI por instancia A y B.

**Nuevas filas (en orden):**
- `AC_r_red` — STEP2 output: amplitud pulsátil rojo [ADC counts] (fmt: .1f)
- `DC_r_red` — STEP3 output: denominador DC rojo [ADC counts] (fmt: .1f)
- `AC_r_ir`  — STEP2 output: amplitud pulsátil IR [ADC counts] (fmt: .1f)
- `DC_r_ir`  — STEP3 output: denominador DC IR [ADC counts] (fmt: .1f)
- `PI_red [%]` — AC_r_red / DC_r_red × 100 (fmt: .3f)
- `PI_ir [%]`  — AC_r_ir / DC_r_ir × 100 (fmt: .3f)
- `R`         — PI_red / PI_ir (fmt: .4f)
- `SpO2 [%]`  — 110 − 25×R, provisional, no calibrada (fmt: .1f)

**PICalc:** añadido `self.spo2` como output. Calculado al final de `update()`: `max(0, min(100, 110 − 25×R))` si R > 0, else 0.

**Tooltips:** cada cabecera de fila tiene tooltip explicando fórmula y unidades. Tooltip general de tabla actualizado.

**Nota:** SpO2 usa la fórmula lineal estándar provisional (misma que firmware). No está calibrada.

---

## Sesión 2026-06-15z

### Tema: PILabWindow — aumentar altura de tabla

`setMinimumHeight(320→480)` y `setMaximumHeight(480→700)` para que las 8 filas sean visibles sin scroll.

---

## Sesión 2026-06-15aa

### Tema: PILabWindow — añadir gráfica SpO2

Añadido 5º plot `p_spo2` (row=4) en PILabWindow con curvas `curve_spo2_a/b`.
- Buffers `_spo2_a/b` alimentados con `calc.spo2` en feed loop
- `setXLink(p_sig)` para sincronización temporal con el resto de plots
- Label: `"SpO2 [%]"`, eje X: `"Time [s]"`

---

## Sesión 2026-06-15ab

### Tema: PILabWindow — renombrar ejes Plot1 y Plot2

- Plot1: `"AC_t [ADC] — STEP1 output"` → `"AC_t_ir [ADC]"`
- Plot2: `"AC_r [ADC]"` → `"AC_r_ir [ADC]"`

Más conciso y consistente con la convención `_ir` del proyecto.

---

## Sesión 2026-06-15ac

### Tema: PILabWindow — renombrar STEP1 "DC subtraction" → "AC extraction"

"DC subtraction" era method-specific (solo correcto para EMA). "AC extraction" describe el resultado independientemente del método (EMA/BPF/None producen todos la componente AC pulsátil).

Cambios en todas las ocurrencias: docstring PICalc, comentario `update()`, label UI, help text, tooltip botón PILAB.

---

## Sesión 2026-06-16a

### Tema: PICalc — SpO2 sincronizado desde $CFG del firmware

**Problema:** PICalc usaba fórmula hardcoded `110 − 25×R`, diferente a la librería (`114.9208 − 30.5547×R`).

**Solución:** PICalc ahora usa `spo2_a`/`spo2_b` como parámetros de instancia, sincronizados desde el firmware en tiempo real.

**Cambios:**
- `PICalc`: añadido `DEFAULT_SPO2_A=114.9208`, `DEFAULT_SPO2_B=30.5547` como class constants. Nuevos atributos `self.spo2_a`/`self.spo2_b` (inicializados a los defaults). `update()` usa `spo2_a - spo2_b * R`.
- `PILabWindow._sync_spo2_coeffs(kv)`: lee `spo2a`/`spo2b` del dict `$CFG` y los aplica a `calc_a` y `calc_b`. Fallback a defaults si ausentes.
- `toggle_pilab`: llama `_sync_spo2_coeffs(self._last_cfg)` justo después de crear la ventana.
- `_on_cfg_frame_received`: llama `pilab_window._sync_spo2_coeffs(kv)` si la ventana está abierta → actualización en vivo.

Las claves en `$CFG` son `spo2a` y `spo2b` (confirmado en main.cpp).

---

## Sesión 2026-06-16b

### Tema: PILabWindow — botón "FIRMWARE PRESET"

Añadido botón "FIRMWARE PRESET" debajo de "APPLY A/B" en cada instancia.

Al pulsarlo carga los parámetros del algoritmo SpO2 del firmware:
- STEP1: EMA, τ_sub = 2.0 s
- STEP2: EMA-RMS, τ_ac = 6.0 s
- STEP3: EMA, τ_norm = 2.0 s
- spo2_a/b leídos de `main_monitor._last_cfg` (valores activos del firmware)

Implementación: `_apply_firmware_preset(cfg, calc)` — actualiza widgets, llama `_refresh_param_state`, `_apply_config` y `_sync_spo2_coeffs`.

---

## Sesión 2026-06-16c

### Tema: PILabWindow — fix crash por mismatch de arrays en pyqtgraph

**Causa raíz:** `_spo2_a` y `_spo2_b` no estaban en la lista de clear de `_apply_config`. Al pulsar APPLY o FIRMWARE PRESET, `_t_buf` se vaciaba y empezaba con N muestras nuevas, pero `_spo2_a/b` conservaban 3000 puntos viejos. Cuando `setXRange` disparaba `viewRangeChanged`, pyqtgraph intentaba re-renderizar `curve_spo2_a` con x=(N,) e y=(3000,) → crash.

**Fix:** añadido `self._spo2_a.clear(); self._spo2_b.clear()` en `_apply_config` junto al resto de buffers.

---

## Sesión 2026-06-16d

### Tema: PILabWindow — tooltip lpf_fc con equivalencia τ/fc

Tooltip de `lpf_fc` extendido con indicación orientativa de equivalencia entre fc y τ EMA:
- τ_equiv ≈ 1/(2π·fc) ≈ 0.16/fc
- Ejemplo: fc=0.08 Hz ≈ τ=2 s; fc=0.4 Hz ≈ τ=0.4 s

---

## Sesión 2026-06-17a

### Tema: PILabWindow — tooltip STEP2 method extendido con descripción de 2.4 Spectral band

Tooltip del combo STEP2 extendido con descripción detallada del método 2.4:
- FFT sobre win_s segundos de señal cruda (resta de media, no STEP1)
- Extrae energía en banda [HR ± 0.3 Hz]; ac_r = √(energy/N)
- Warning: HR debe coincidir con el HR real del paciente
- Nota: STEP1 no tiene efecto en este método
- 2.5 Harmonics: igual pero sumando N armónicos de f_HR

---

## Sesión 2026-06-17b

### Tema: PILabWindow — tooltips bpf_lo y STEP2 method actualizados

**bpf_lo tooltip:** análisis completo de roll-off (-12 dB/oct, -3 dB en cutoff), rechazo real de respiración adulto para 0.3/0.4/0.5 Hz, y nota crítica sobre neonatos (respiración 0.5–1.0 Hz cae dentro del band → BPF no ayuda → usar métodos espectrales).

**STEP2 tooltip:** descripción detallada de 2.4 Spectral band y 2.5 Harmonics con warnings sobre HR param y que STEP1 no tiene efecto en estos métodos.

---

## Sesión 2026-06-17c

### Tema: PILabWindow — tooltip STEP2 actualizado con explicación de 2.5 Harmonics

Tooltip del combo STEP2 extendido con descripción completa de 2.5 Harmonics:
- Misma FFT que 2.4 pero suma energía en N bandas centradas en armónicos f0, 2·f0, ... N·f0
- Justificación: la onda PPG no es sinusoide pura — pico sistólico y onda dicrota tienen energía en 2º y 3er armónico
- n_harm=3 conservador; valores altos capturan ruido a bajo SNR
- Mismos warnings que 2.4: HR debe ser exacta, STEP1 sin efecto

---

## Sesión 2026-06-17d

### Tema: PILabWindow — eliminar referencias incorrectas a "M1" en tooltips

"firmware M1" era incorrecto — M1 es un modo de trama ($M1=PPG), no un nombre de algoritmo. Sustituido por "firmware method" / "firmware default" en todos los tooltips de PILAB (STEP1/2/3 combos y spinboxes τ_sub, τ_ac, τ_norm). Las menciones de M1 en CSV parsing y campos de frame se mantienen (correctas).

## Sesión 2026-06-23a

### Tema: LIB CONFIG — ventana de parámetros RSQM configurables en runtime

**Contexto:** `rsqm_ot_thr` (umbral OT para PROBE_NOT_APPLIED vs PROBE_APPLIED) era `static constexpr` en la librería — no modificable sin reflashear.

**Decisiones:**
- Convertir de `static constexpr` a miembros de instancia en `INCUNEST_AFE4490` (privados): `rsqm_ema_mean_tau_s`, `rsqm_ema_var_tau_s`, `rsqm_ot_thr`, `rsqm_disconn_led_sub_thr`, `rsqm_disconn_i_pd_thr`, `rsqm_signal_weak_std`. Mantener como constexpr: `rsqm_ready_count`, `rsqm_ot_saturated`, `rsqm_adc_positive_sat`, `rsqm_diag_period_ms`.
- Renombrar `rsqm_probe_state_min_count` (uint8_t, samples) → `rsqm_probe_state_min_s` (float, segundos), para independencia de la frecuencia de muestreo. Convertido a `_rsqm_probe_state_min_samples` (uint32_t) en `_recalc_rate_params()`. `_rsqm_probe_state_count` subido a uint32_t.
- Añadir 7 campos RSQM a `AFE4490Config` (struct pública) y copiarlos en `getConfig()`.
- Añadir 6 setters públicos: `setRsqmOtThr`, `setRsqmSignalWeakStd`, `setRsqmDisconnLedSubThr`, `setRsqmDisconnIPdThr`, `setRsqmProbeStateMinS`, `setRsqmEmaTau`.
- Nuevo frame `$LCFG` (análogo a `$CFG` pero para parámetros software) + comando `$LCFG?` en main.cpp.
- Casos RSQM añadidos a `apply_set_cmd()` en main.cpp (emiten `$LCFG` como confirmación).
- Nueva clase `LIBConfigWindow` en `pulsenest_lab.py`: botón "LIB CONFIG" en sidebar, 7 spinboxes con escala (I_PD en nA), Set individual + Set all, parse `$LCFG`, dirty/clean state.
- `rsqm_disconn_i_pd_thr` se muestra en nA (×1e9) en la UI; se envía en A al firmware.

**Specs actualizadas:** `incunest_afe4490_spec.md` → v0.33, `pulsenest_lab_spec.md` → v1.7.

## Sesión 2026-06-24a

### Tema 1: Verificación timing real librería vs datasheet (análisis fototerapia)

**Contexto:** el análisis previo de interferencia de fototerapia usaba T_s=487 µs del datasheet Table 2 (ejemplo). El usuario preguntó si el timing real de la librería coincide.

**Resultado de la verificación (`_apply_timing_regs()`):**
- `phase = 4 000 000 / 500 = 8000` counts (2000 µs PRP) — igual al datasheet
- `q = 2000` counts = 500 µs — igual al datasheet
- `tia_margin = floor(2000 × 0.10) = 200` counts = 50 µs → T_s real = **449.5 µs** (datasheet usaba ~487 µs)
- `ambient_margin = 200` counts = 50 µs
- Ventanas reales: LED1 STC=550 µs ENDC=999.5 µs; ALED1 STC=1050 µs ENDC=1499.5 µs

**Conclusión:** Δt (separación centros LED↔ALED) = 500 µs en ambos canales — igual al datasheet. La diferencia solo afecta T_s (longitud de ventana), no la condición de cancelación de fototerapia. Conclusiones siguen válidas: 5 kHz problemático (anti-fase, dobla interferencia); 10/20/50 kHz cancelación perfecta por sustracción digital.

### Tema 2: PPGSignalsWindow — PAUSE/CONTINUE + Window duration

**Cambios en `pulsenest_lab.py`:**
- `_setup_ui()`: añadido spinbox "Window (s)" (rango 1–10 s, persistido en `.ini`) y botón "PAUSE" (checkable, naranja cuando activo).
- `_on_pause_clicked()`: nuevo método — toglea `_paused` y cambia texto del botón.
- `update_plots()`: retorna inmediatamente si `_paused`; aplica `[-n:]` con `n = window_s × SPO2_RECEIVED_FS` a todas las curvas.
- `closeEvent()`: persiste `PPGSignalsWindow/window_s`.
- `__init__()`: inicializa `_paused = False`; restaura `window_s` desde `.ini`.

## Sesión 2026-06-25a

### Tema: PPGSignalsWindow — ampliar duración máxima a 60 s (Opción B: acumulador interno)

**Problema:** el spinbox "Window (s)" estaba limitado a 10 s porque los deques principales de PPGMonitor tienen `maxlen=WINDOW_SIZE=500`.

**Decisión — Opción B (acumulador interno en PPGSignalsWindow):**
- No se tocan los deques de PPGMonitor ni el drain loop.
- `PPGSignalsWindow` mantiene 7 deques internos (`_sig_led2`, `_sig_led1`, etc.) con `maxlen = SIG_MAX_S × SPO2_RECEIVED_FS = 3000` muestras (60 s @ 50 Hz).
- `update_plots()` recibe adicionalmente `data_sample_counter`; detecta muestras nuevas contando entradas con `sc > _sig_last_sc`; acumula en buffers internos en cada llamada (incluso durante PAUSE).
- Detección de reinicio de firmware: si `last_sc < _sig_last_sc`, limpia todos los buffers internos.
- Render usa `[-n:]` sobre los buffers internos (no sobre los deques de PPGMonitor).
- Spinbox rango ampliado a 1–60 s; default sigue siendo 10 s (guardado/restaurado en `.ini`).
- Nueva constante de módulo: `SIG_MAX_S = 60`.

## Sesión 2026-06-26a

### Tema 1: Conversión ficheros CSV existentes de UTF-8-BOM a cp1252

Todos los `.csv` en `captures/` que tenían BOM (`\xef\xbb\xbf`) fueron convertidos a `cp1252` (Windows ANSI). 2 ficheros contenían el símbolo `Ω` (no encodable en cp1252) — se sustituyó por `Ohm`. Total: 14 ficheros convertidos.

### Tema 2: pulsenest_lab.py — todos los CSV generados cambiados a cp1252

**Motivo:** LibreOffice no abría correctamente los `.csv` porque el BOM (`utf-8-sig`) hacía que las líneas de comentario iniciales se interpretasen como datos.

**Cambios:** 8 puntos de apertura de fichero CSV actualizados a `encoding="cp1252", errors="replace"`:
- Lab Capture stream (`utf-8-sig` → `cp1252`)
- Lab Capture snapshot
- CHK file
- SpO2 Cal export
- SPO2TEST / HR1TEST / HR2TEST / HR3TEST exports

`errors="replace"` previene crashes si las notas contienen caracteres fuera de cp1252 (e.g. `Ω` → `?`).

## Sesión 2026-07-06a

### Tema: Tooltips — duración indefinida (event filter global)

**Problema:** los tooltips se cerraban automáticamente después de ~10 s (comportamiento por defecto de Qt).

**Solución implementada:** event filter `_TooltipDurationFilter` instalado en la `QApplication`. Intercepta `QEvent.ToolTipChange` (disparado cada vez que se llama `setToolTip()` sobre cualquier widget) y fija la duración con `setToolTipDuration(2_147_483_647)` (INT_MAX ms ≈ 24 días). Cero cambios en los 178 call sites existentes; cubre automáticamente cualquier tooltip futuro.

**Ficheros modificados:**
- `pulsenest_lab.py` — bloque de configuración de tooltips en `main()`, tras `app.setStyle(_FastTipStyle(...))`

---

## Sesión 2026-07-06c

### Tema: HW CONFIG — tooltips Stage 2 gain mencionan RG

**Pregunta:** en la ventana HW CONFIG, el label "RF Gain" menciona RF pero "Stage 2 gain" no menciona RG. ¿Debería mencionarlo?

**Decisión:** Opción A — añadir explicación de RG en el tooltip (no cambiar el label). El label "Stage 2 gain" es más descriptivo funcionalmente; RG es un detalle de implementación que pertenece al tooltip.

**Cambio implementado:** ambos tooltips de "Stage 2 gain" (LED1 IR y LED2 RED) en `HWConfigWindow` ahora incluyen: "Stage 2 inverting amplifier gain [...]. Implemented via feedback resistance RG — the kΩ values shown in the dropdown are the RG values (100 kΩ = ×1, 150 kΩ = ×1.5, etc.)."

**Ficheros modificados:**
- `pulsenest_lab.py` — tooltips `_combo_stg21` y `_combo_stg22` en `HWConfigWindow._setup_ui()`

---

## Sesión 2026-07-06b

### Tema: Planning — inventario de tareas pendientes y propuesta de orden

Revisión completa del backlog. Tareas agrupadas en 5 categorías y propuesta de planificación para los próximos días. Guardado en `memory/project_planning.md` (fichero vivo, se actualiza conforme se cierran tareas).

**Orden propuesto:**
- Día 1: limpieza rápida (HR3TestCalc bug SPO2_RECEIVED_FS, ADZ tooltip, LED default 20 mA, unit tests HR3, shared lib build check)
- Día 2: calidad de señal firmware (HR3 SQI false positive estrategia A, RSQM HR2/HR3 invalid count, DIAG_EN poll)
- Día 3: SpO2 DC split, serial fallback, Format_Task
- Día 4: validación empírica (HR artefact test, PI stability, HR3 execution rate)
- Backlog: HGAC (bloqueante: RSQM validado en HW), Spectral PI, Metrological uncertainty, HR1 improvements, refactor modular

---

## Sesión 2026-07-07/08 — Rediseño HGAC (revisión profunda, pendiente validación)

### Tema: revisión en profundidad de la propuesta de diseño HGAC y sus objetivos

**Contexto:** debate P1-P4. Críticas del usuario: P1 sube AMBDAC sin mirar RF/RG; estrategia P1-P4 poco fundamentada → re-fundamentar objetivos desde cero.

**Trabajo previo de la sesión:** setters de actuadores verificados (todos existen); nomenclatura HGACInput renombrada (aled_pct/led_sub_pct); nomenclatura actuadores acordada (LED1Current, LED2Current, RF1, RF2, AMBDAC, RG1, RG2 — Opción B); análisis profundo de los 7 actuadores desde datasheet; fórmula V_TIA corregida en project_agc_design.md: `v_tia = (V_ADC/(2×RG_ohm) + ambdac×1e-6) × Ri` (verificada contra .cpp líneas 1113-1116; coef AMBDAC = 0.1 V/µA); ventana híbrida acordada (mediana 2s + persistencia 500ms/2000ms).

**7 fallos estructurales identificados (F1-F7):**
- F1: la saturación debe evaluarse sobre canales crudos (LED/ALED), no sobre led_sub (resta digital, no satura; LED clippeado → led_sub bajo → HGAC subiría LED agravando el problema)
- F2: saturación negativa (sobre-cancelación AMBDAC) no contemplada
- F3: decidir en %FS confunde causa óptica con configuración → medir en dominio físico (i_pd_*, OT), decidir configuración; %FS solo como verificación
- F4: acoplamiento AMBDAC↔RF (rango de cancelación efectivo depende de RF: con RF=1M solo ~1 µA) → decidir conjuntamente
- F5: cada actuación puede costar 18 s de warmup SpO2 → minimizar actuaciones + posible compensación analítica de estados de filtros (mean×k, var×k²)
- F6: R es invariante a ganancia → target 40%FS no es objetivo real, solo proxy de región lineal + AC resoluble
- F7: umbrales 70%/85% no derivados del datasheet (Stage 2 ±0.9 V vs ADC ±1.2 V → región lineal ~75%FS; pendiente verificar §9.2.2/Fig.135)

**Física de actuadores → orden de preferencia:** LED (mejora SNR ∝√I_LED, shot noise) > RF (mejora parcial, Friis) > RG (casi neutro); AMBDAC neutro para SNR (solo libera rango dinámico). LED con coste térmico neonatal (ISO 80601-2-61) → suficiente, no máximo.

**Objetivos re-fundamentados (orden lexicográfico):** G0 gating (APPLIED, sin settling, n_invalid≤0.5) · O1 sin saturación ADC en 4 canales crudos, ambos signos (prioritario por OBSERVABILIDAD: si ADC clippea, V_TIA/i_pd inestimables) · O2 sin saturación TIA (|v_tia|<0.9 V, solo evaluable si O1) · O3 AC resoluble (AC_counts > k×ruido) · O4 margen · O5 LED mínimo · O6 RF alto/RG mínimo · O7 AMBDAC mínimo · O8 mínimas actuaciones · O9 estabilidad/histéresis · O10 factibilidad conjunta IR+RED.

**Arquitectura propuesta (PENDIENTE VALIDACIÓN DEL USUARIO):** FASE A medir en dominio físico (mediana P², 2 s) → FASE B solver feed-forward (enumerar 7RF×5RG×11AMBDAC=385 combos por canal + LED, elegir por orden lexicográfico O1→O10) → FASE C aplicar en una sola tanda + RSQM_HW_SETTLING + compensación de estados → FASE D trim fino solo con LED. P1-P4 relegado a capa de emergencia.

**5 preguntas abiertas:** (1) ¿solver feed-forward + trim, o P1-P4 incremental corregido? (2) ¿verificación post-aplicación por error de modelo (tolerancias RF/AMBDAC)? (3) ¿leer §9.2.2/Fig.135 (p.85+) para derivar umbral región lineal? (4) ¿compensación analítica de estados: parte de HGAC o tarea separada? (5) ¿suelo de ruido para O3: analítico (datasheet) o empírico (LED off/sonda tapada)?

**Nueva tarea apuntada:** `memory/project_ipd_aled_estimator_task.md` — usar i_pd_aled1 (corriente por luz ambiente, ya calculada en `_compute_analog_state()`, dominio físico) como estimador de "sonda mal colocada"/"excesiva luz ambiente". Válido solo sin saturación TIA/ADC/DAC. Preferir ALED1 (ALED2 posible leakage LED2).

**Próximo paso (siguiente sesión):** validar arquitectura + responder las 5 preguntas → reescribir project_agc_design.md completo con la nueva fundamentación.

---

## Sesión 2026-07-08 — Fig. 57 (TIA), rangos de saturación y validación O1→O2 del HGAC

**Tema:** formación sobre el front-end analógico (Fig. 57 del datasheet) y consolidación de los dos primeros objetivos del HGAC.

**Preguntas clave y respuestas:**
- **Fig. 57 explicada** (amplificadores operacionales, nivel básico): TIA = conversor I→V (ganancia = RF en Ω); la fotocorriente no puede entrar al op-amp y atraviesa RF forzosamente (V = I_PD×RF); CF = estabilidad + antialiasing; I_CANCEL resta ambiente en analógico antes de la etapa 2 (RG/RI, ×1–×4); Eq. 2 p.30.
- **Fotodiodo a 0 V no es un problema, es el objetivo**: es fuente de corriente (no de tensión); a polarización nula → linealidad máxima, dark current mínima, capacidad parásita sin cargar. Modo común interno 0.9 V; la DIFERENCIA entre terminales es ~0 V.
- **La corriente de RF** se cierra por la etapa de salida del op-amp (push-pull) hacia los rieles de alimentación.
- **Convención V_TIA aclarada**: `v_tia_*` de la librería = POR RAMA (= I_PD×RF, FS 0.5 V). Diferencial entre salidas = 2×I_PD×RF (FS 1 V = V_OD(fs) p.11). Nodos físicos: 0.9 V ± 0.5 V (0.4–1.4 V). Verificación cruzada: tabla I_IN_FS p.10 cumple I_FS×RF = 0.5 V para los 7 RF.
- **§9.2.2 dice ±1 V** porque: (1) es tensión DIFERENCIAL (puede ser negativa sin que ningún nodo baje de 0 V); (2) orientación del fotodiodo libre (invertido → códigos negativos, two's complement); (3) aguas abajo la señal sí es bipolar (sobrecancelación AMBDAC). Fig. 135 íntegramente en dominio diferencial (ideal 0.6 V diff = 0.3 V por rama). p.89: TI recomienda ADC ≤ ±1 V (~80% FS).

**Decisiones tomadas:**
1. **Usuario valida O1 → O2** (primero no saturar ADC, después no saturar TIA) por observabilidad: con ADC clipado no se puede estimar V_TIA; con ADC lineal la fórmula de recuperación hace la TIA observable. "TIA sat + ADC no sat" es caso real (RG=×1, AMBDAC cancelando ambiente grande) → O2 no es subcaso de O1. Registrado en `memory/project_agc_design.md`.
2. **⚠️ Inconsistencia de unidades detectada** en las constantes TIA del diseño HGAC: `hgac_tia_sat/thr/ideal = 1.0/0.9/0.6 V` están en dominio DIFERENCIAL pero `v_tia_*` es por rama (FS 0.5 V) → comparar v_tia contra 0.9 V no dispararía nunca. Pendiente: redefinir por rama (sat=0.5, thr≈0.45, ideal≈0.3). También afecta a O2 tal como quedó redactado en la sesión anterior (|v_tia|<0.9 V).
3. HGAC debe comparar **|v_tia|** (valor absoluto), no asumir signo → cubre fotodiodo invertido y sobrecancelación (enlaza con F2, saturación negativa).

**Pendiente (próxima sesión):** validar O3–O10 y la arquitectura solver feed-forward; responder las 4 preguntas abiertas restantes (la nº 3 —leer §9.2.2/Fig.135— quedó resuelta hoy); corregir constantes TIA a convención por rama; reescribir project_agc_design.md completo tras validación.

**Sin cambios de código** en esta sesión (solo documentación y memoria).

---

## Sesión 2026-07-08b — Nomenclatura de señales y V_TIA con STAGE2EN=0

**Tema:** tabla de nomenclatura digital/analógica y explicación del cálculo de v_tia.

**Tabla de nomenclatura verificada contra `incunest_afe4490.h`:**
- Digital (counts, `AFE4490Data`): `led1`, `led2`, `aled1`, `aled2` + restas HW **`led1_sub`, `led2_sub`**
- Analógico (`AFE4490AnalogState`): `v_adc_*`, `v_tia_*` (V), `i_pd_*` (A) para los 4 canales — nombres exactos en código
- Cadena de reconstrucción: counts → v_adc (`×1.2/2097152`) → v_tia (`(v_adc/(2×RG_ohm) + ambdac×1e-6)×Ri`) → i_pd (`v_tia/RF`)
- **Corrección de memoria:** las restas HW se llaman `led1_sub`/`led2_sub` en `AFE4490Data` (no `led1_aled1`/`led2_aled2`, nombre antiguo que persistía en algunas memorias)

**V_TIA con STAGE2EN=0:** ganancia stage 2 = ×1 → RG_ohm = Ri = 100 kΩ → `v_tia = V_ADC/2 + ambdac_µA × 0.1 V`. El factor ÷2 deshace la conversión a diferencial (Eq. 2); el término AMBDAC suma de vuelta la corriente cancelada post-TIA (0.1 V/µA). Con AMBDAC=0: v_tia = V_ADC/2 → ADC FS (±1.2 V) ↔ v_tia ±0.6 V por rama. Nota: según la convención por rama consolidada en la sesión 2026-07-08 (FS v_tia = 0.5 V), con esta configuración el TIA satura ANTES de que el ADC llegue a FS — coherente con la inconsistencia de unidades detectada.

**Sin cambios de código** (solo documentación y memoria).

---

## Cierre coordinado de sesiones (2026-07-08)

El usuario cierra todas las sesiones Claude abiertas. Estado consolidado del rediseño HGAC:
- Validado: O1→O2 (observabilidad ADC antes que TIA); pregunta 3 resuelta (§9.2.2/Fig.135, convención por rama)
- Pendiente: validar O3-O10 + arquitectura solver feed-forward; preguntas 1, 2, 4, 5; corregir constantes TIA a convención por rama (0.5/0.45/0.3); reescribir `memory/project_agc_design.md` completo
- Punto de entrada para la próxima sesión: sección "REVISIÓN PROFUNDA — PENDIENTE VALIDACIÓN" en `memory/project_agc_design.md`

---

## Sesión 2026-07-08c — Convención V_TIA (por rama vs diferencial) + experimento de linealidad TIA

**Limpieza:** eliminada del log la sesión "2026-07-08 (bis)" a petición del usuario (revisión paralela duplicada). Se conservó su tarea `project_vtia_gray_task.md` y se anotó en `project_agc_design.md` el dato verificado: target AGC = 50%FS = 0.6 V (§9.2.2 p.87), no 40%.

**Decisión inicial (en suspenso):** usuario eligió Opción B — pasar la librería a convención V_TIA diferencial. Análisis de impacto completado: `_compute_analog_state()` ×2 + `i_pd = v_tia/(2×RF)`; RSQM sin impacto (usa solo i_pd); constantes HGAC de main.cpp (1.0/0.9/0.6) pasarían a ser correctas sin tocarlas; umbrales `_vtg_tia_color` y tooltips de pulsenest_lab.py ya estaban en diferencial. **Implementación EN PAUSA** hasta resolver la duda experimental siguiente.

**Debate experimental (clave de la sesión):** el usuario cuestionó la convención por rama con medidas reales:
- Con AMBDAC=5..8 µA y luz constante, `v_tia` reconstruido queda fijo en 0.974–0.979 V mientras V_ADC baja 0.197 V/µA (teórico 0.2 = 2×RG×1µA → **valida el factor ×2 de la Eq. 2**).
- Duplicar LED (20→40 mA) no mueve `v_tia` (0.979 V) → **saturación dura real en ~0.98 V** (en unidades de la columna).
- Barrido manual con HW CONFIG: `v_tia` proporcional hasta detenerse bruscamente en 0.976 V, sin codo aparente en 0.5 V.

**Conflicto identificado entre hipótesis:**
- *Usuario (diferencial):* techo 0.976 ≈ V_OD(fs)=1 V → el valor reconstruido sería el diferencial. Contra: descuadra la tabla I_IN_FS (5 µA×100 kΩ=0.5 V) y la topología Fig. 57 (misma corriente por ambas RF → diff = 2×I_PD×RF).
- *Reconciliadora (por rama):* 0.5 V = límite de linealidad especificado (V_OD(fs)); ~0.98 V = clip duro físico del nodo de salida contra el raíl (exige CM de salida ≈1.0 V, no especificado; el de entrada es 0.9 V).
- Verificado que la columna V_TIA de SIGNAL STATS calcula la inversión exacta de Eq.2 (`(V_ADC/(2×RG)+I_CANCEL)×RI` = I_PD×RF), idéntica a la librería. **Incoherencia documental detectada:** el comentario del código dice por rama y el tooltip dice "differential".

**Nuevo fichero: `tia_linearity_sweep.py`** — script standalone UDP (puerto datos 5005 / comandos 5006, checksum XOR) que rampea LED1 (2–150 mA, paso 2) × AMBDAC {0,3,5,8} µA × RF {50K,100K}, mediana de V_TIA_LED1 por paso, descarta ADC clipado, CSV cp1252 + PNG + análisis de pendiente por bins de 0.1 V vs baseline 0.10–0.40 V. Discriminador: codo en ~0.5 V → por rama; sin codo hasta ~0.9 V → diferencial. Doble RF separa droop del LED (función de mA) de compresión TIA (función de V_TIA). Restricción del usuario: NO modificar la ventana AFE SWEEP TEST. Requiere cerrar pulsenest_lab.py (mismo puerto 5005). Pendiente: ejecutar y decidir convención con el resultado.

**Bugfix "NO DATA":** primera ejecución del sweep falló (todos los pasos sin datos). Causa raíz: el script envolvía `$MODE,M4` con checksum (`$MODE,M4*68`), pero el firmware (`process_command()`, main.cpp) hace `strcmp` exacto sobre el argumento de `$MODE` — solo `$SET` acepta/exige checksum. El modo nunca cambiaba a M4 y `collect()` no veía frames `$M4,`. Fix: método `send_raw()` (sin checksum) para `$MODE,M4`; los `$SET` siguen con checksum. Igual que hace pulsenest_lab.py (línea ~10473).

**Segunda ejecución del sweep — descubrimiento de reset esporádico del ESP32:**
- Pasos 1-8 (RF=50K, AMBDAC=0) OK: V_TIA lineal 0.089→0.51 V **cruzando 0.5 V sin codo** (pero con AMBDAC=0 el ADC satura a 1.2 V y limita V_TIA a 0.6 V — las ventanas AMBDAC>0 son las decisivas).
- Desde el paso 9 (transición AMBDAC 0→3): NO DATA permanente. Diagnóstico en vivo: ESP32 con uptime 118 s emitiendo `$M3` → **el ESP32 se reseteó durante el sweep** y arrancó en modo default `$M3` (main.cpp:177), por lo que `collect()` (solo `$M4`) no ve nada.
- El usuario confirma que los cambios en HW CONFIG provocan reset del ESP32 ~1 de cada 3-4 veces (bug conocido por él, causa desconocida).
- crash.log solo contiene excepciones Python del lab (Qt), nada del ESP32.

**Instrumentación de reset (implementada y flasheada por OTA):**
- `reset_reason_str()` + `esp_reset_reason()` en main.cpp: línea `# SYS: Reset reason: X` en el banner de arranque + datagrama UDP único `# RESET_REASON: X` tras conectar WiFi (`udp_send_line`).
- Verificado en vivo: `$RESET` → `# RESET_REASON: SW_RESET` recibido por UDP.
- Interpretación: PANIC=crash de código (posible carrera Cmd_Task/Incunest_Task), TASK_WDT/INT_WDT=deadlock/bloqueo, BROWNOUT=alimentación (LED/AMBDAC cambian el consumo).
- El backtrace de un PANIC solo sale por UART0 (el panic handler no puede usar WiFi/lwIP) → paso 2 si es PANIC: `pio device monitor -p COM15 --filter esp32_exception_decoder`.
- Pendiente: reproducir el reset con HW CONFIG y leer `# RESET_REASON`; hacer el sweep robusto a reboots (detectar reinicio de SmpCnt / ausencia de $M4 y re-aplicar `$MODE,M4` + config).

**Reproducción del reset por el usuario + fix de visualización en el lab:**
- El usuario reprodujo el reset con HW CONFIG (ambdac 8: sin respuesta $CFG dos veces → reboot → `ambdac=0µA` de fábrica) pero `# RESET_REASON:` no aparecía en el log del lab.
- Causa: el handler de líneas `#` (pulsenest_lab.py ~11526) solo muestra patrones concretos (`incunest`, `frame mode`, `# SYS:`, `# WiFi`); el resto cae al `continue` silenciosamente.
- Fix: nueva rama `# RESET_REASON:` → `[RESET] ESP32 rebooted — reason: X`. Spec actualizada a v1.8 (§4.4 + changelog; añadida también entrada v1.7 LIB CONFIG que faltaba).

**CAUSA RAÍZ DEL RESET ENCONTRADA Y CORREGIDA (misma sesión):**
- Con el lab relanzado, el usuario reprodujo el reset → `[RESET] ESP32 rebooted — reason: PANIC (exception/abort)`.
- Paso 2: monitor UART con `esp32_exception_decoder` (puerto real: **COM25**, USB-CDC nativo del S3, SER=10:51:DB:50:48:F8 — no COM15). Captura en `uart_panic_capture.log`.
- Backtrace: `Guru Meditation Error: Core 0 panic'ed — Stack canary watchpoint triggered (CMD)` → **stack overflow de Cmd_Task** (4096 bytes).
- Cadena culpable: `$SET` → `apply_set_cmd()` → `Serial_printf` (buf 128) + `send_cfg_frame()` (buf[600]) + `send_tcfg_frame()` (buf[512]) + internos vsnprintf con floats + lwIP/WiFiUDP + OTA `handleClient()` — todo en el mismo stack. Esporádico porque depende del camino/anidamiento exacto.
- Fix: stack de Cmd_Task 4096 → 8192 (main.cpp, con comentario explicativo). Build OK, flasheado por OTA (MAC verificada). Pendiente: prueba de estrés del usuario (15-20 cambios en HW CONFIG sin reset) y luego reanudar `tia_linearity_sweep.py`.

**Sweep completado — FÍSICA RESUELTA (2026-07-08, tarde):**
- Con el fix de stack, `tia_linearity_sweep.py` completó las 8 ventanas (RF {50K,100K} × AMBDAC {0,3,5,8} µA, LED 2–150 mA). CSV `tia_linearity_sweep_2026-07-08_1913.csv` + PNG.
- **Sin codo en 0.5 V:** V_TIA reconstruido lineal hasta ~0.90 V (pendiente 103% del baseline en 0.9 V). El patrón alternante 113%/86% en pasos de 2 mA es cuantización del DAC de LED (promedia 100%), no compresión.
- **Clip duro en ~0.97 V** (0.968 @50K/AMBDAC5, 0.973 @8µA, 0.974 @100K): independiente de AMBDAC → el clip está DENTRO de la TIA, antes de la resta de ambiente; casi independiente de RF → límite de tensión del nodo de salida contra el raíl.
- **Interpretación final:** el valor reconstruido `(V_ADC/(2×RG)+I_CANCEL)×RI` = I_PD×RF es algebraicamente POR RAMA (Eq.2 ×2 validada: pendiente AMBDAC medida −0.197 V/µA vs −0.2 teórica). 0.5 V/rama es el fondo de escala LINEAL especificado por TI, no un límite físico. El clip físico ~0.97 V/rama = 1.94 V diferencial (la rama baja toca el raíl ~0 V). La coincidencia 0.97 ≈ V_OD(fs)=1 V fue el origen de la confusión.
- Tabla empírica: **rama** — ideal 0.3 / spec TI 0.5 / lineal medido ~0.90 / clip ~0.97 V. **Diferencial** — 0.6 / 1.0 / ~1.8 / ~1.94 V (los valores diff coinciden literalmente con el datasheet: target §9.2.2 = 0.6 V, V_OD(fs) = 1.0 V).

**Reflexión sobre la respuesta de otra sesión de Claude (pro-Opción B, diferencial):**
- Sus argumentos 3-4 ("el clip 0.976 es diferencial", "las medidas apuntan a diferencial") son factualmente erróneos post-sweep: el clip es magnitud por-rama pre-resta; el diferencial clipa en ~1.94 V.
- Su argumento 2 (alineación literal con los números del datasheet §9.2.2 y V_OD(fs)) es el único motivo fuerte a favor de B. Argumento 1 (intuición STAGE2-bypassed) es neutro.

**REGLA 4b FORMALIZADA (decisión del usuario):** el nombre desnudo `v_tia` queda PROHIBIDO en librería, firmware, Python y specs. Todo identificador de tensión de salida TIA debe llevar sufijo de dominio: `_branch` (= I_PD×RF) o `_diff` (= 2×I_PD×RF); relación `v_tia_diff = 2 × v_tia_branch`. Aplica también a constantes de umbral (e.g. `hgac_tia_thr_diff_volt`). Motivo: la ambigüedad de `v_tia` causó la incoherencia código/tooltip/constantes HGAC de esta sesión. Registrada en `project_nomenclature_dictionary.md` (Regla 4b) y `project_agc_design.md`.
- **Dilema A/B sigue abierto** (puramente convencional, la física ya está resuelta): A = librería almacena por-rama (sin cambio de código, renombrar a `*_branch`); B = librería pasa a diferencial (×2 en `_compute_analog_state`, datasheet-literal, rompe CSVs históricos). Pendiente decidir en la próxima discusión.

**DECISIÓN A/B RESUELTA + REGLA 4b APLICADA (2026-07-08, noche):**
- El usuario eligió **Opción B (diferencial)**, preliminarmente (reversible gracias a la Regla 4b: B→A sería mecánico).
- Aplicada la pasada completa de renombrado + cambio de dominio:
  - **Librería v0.34** (spec+code alineados; antes había desalineación 0.32/0.33): `AFE4490AnalogState.v_tia_*` → `v_tia_diff_*`; `_compute_analog_state()` con ×2 (`v_tia_diff = 2×(V_ADC/(2×RG)+I_CANCEL)×RI`); `i_pd = v_tia_diff/(2×RF)` (i_pd no cambia de valor → RSQM intacto); constantes HGAC → `hgac_tia_{sat,thr,ideal}_diff_volt` (valores 1.0/0.9/0.6 sin cambio, ya eran diferenciales); límites empíricos documentados en comentarios y spec.
  - **main.cpp:** `dbg.analog.v_tia_diff_*` en frame $M4 + comentarios `V_TIA_DIFF`.
  - **pulsenest_lab.py (spec v1.9):** renombrado global (75 ocurrencias); cálculo local de SIGNAL STATS ahora con ×2 y término I_CANCEL (antes omitido — la columna ignoraba el AMBDAC); umbrales `_vtg_tia_color` sin cambio (ya diferenciales); tooltips corregidos con fórmula diff + límites empíricos; columnas CSV `V_TIA_DIFF_*`. La incoherencia código/tooltip de 2026-07-08 queda resuelta.
  - **tia_linearity_sweep.py:** adaptado a dominio diff (baseline 0.20–0.80 V, bins hasta 2.2 V, líneas de referencia 1.0/1.94 V, columnas CSV `V_TIA_DIFF_*`); docstring documenta el resultado del experimento y avisa de que los CSVs pre-2026-07-09 son por-rama (×0.5).
- Compilación Python OK (ambos scripts), build firmware OK, **flasheado por OTA** (MAC 10:51:DB:50:48:F8 verificada en ARP).
- Verificación pendiente: relanzar el lab y comprobar que V_TIA_DIFF muestra ~2× los valores antiguos y que la columna de SIGNAL STATS coincide con el valor $M4 del firmware.

**Refinamiento de nombres HGAC (propuesta del usuario, misma sesión):** las constantes `hgac_tia_{sat,thr,ideal}_diff_volt` pasan a `hgac_v_tia_diff_{sat,thr,ideal}`. Patrón formalizado: `<dominio>_v_tia_<sufijo>_<calificador>` — el nombre canónico completo de la magnitud (`v_tia_diff`) queda intacto y grepeable, el calificador al final, y se omite `_volt` (el prefijo `v_` ya implica la unidad). Solo definiciones (sin usos aún) → build OK, sin necesidad de reflashear. Regla 4b actualizada en el diccionario de nomenclatura.

---

## Sesión 2026-07-08 (sesión paralela) — Eq.2 con STAGE2 anulada, dilema A/B, V_OD(fs)

**Preguntas del usuario:**
1. ¿Cómo queda la Eq.2 (p.30 datasheet) si se anula STAGE2? → Con bypass desaparecen RG/RI e I_CANCEL (el DAC de cancelación actúa en la etapa 2): `V_DIFF = 2 × (I_PLETH + I_AMB) × RF`. Coherencia: Eq.2 con RG=100kΩ (0 dB) e I_CANCEL=0 da la misma expresión.
2. Con STAGE2 anulada, ¿qué es más intuitivo: A (V_ADC = 2×V_TIA por rama) o B (V_ADC = V_TIA diferencial)? → Esta sesión respondió pro-B con 4 argumentos. **CORRECCIÓN post-hoc:** según el sweep de la sesión principal, los argumentos 3-4 ("el clip ~0.976 V es diferencial / las medidas apuntan a diferencial") eran factualmente erróneos — el clip ~0.97 V es magnitud POR RAMA pre-resta; el diferencial clipa en ~1.94 V. El único argumento fuerte pro-B es la alineación literal con el datasheet (§9.2.2, V_OD(fs)). La decisión final (Opción B + Regla 4b) ya está registrada arriba.
3. ¿Qué significa V_OD(fs)? → Tensión de salida diferencial a fondo de escala del front-end: ±1 V nominal; el ADC de 22 bits mapea ±2097151 counts ↔ ±1 V. Nota: la afirmación de esta sesión "el clip ~0.976 ≈ V_OD(fs)" repetía la confusión rama/diferencial ya resuelta por el sweep.

**Sin cambios de código en esta sesión** (solo lanzamientos de pulsenest_lab.py y consultas al datasheet).

**Renombrado `_sat` → `_fs` + constante `_clip` reservada (pregunta del usuario, misma sesión):** el usuario detectó que `hgac_v_tia_diff_sat` (1.0 V) no es la saturación dura sino V_OD(fs), el límite hasta el que TI garantiza linealidad. Renombrada a `hgac_v_tia_diff_fs`; comentario del `_thr` actualizado ("before reaching fs"). Añadida comentada `hgac_v_tia_diff_clip = 1.94f` (clip duro físico empírico, sweep 2026-07-08) con documentación del final de linealidad medida (~1.8 V diff). Convención de calificadores añadida a la Regla 4b: `_fs` = límite especificado/garantía de linealidad, `_clip` = clip físico empírico; `_sat` prohibido por ambiguo. Build OK; sin usos → no requiere reflashear.

**Corrección V_OD(fs) (sesión paralela):** verificado en la tabla de características eléctricas (p.11 datasheet): V_OD(fs)=1 V es spec de la **TIA** (full-scale differential output voltage, sección I-V TRANSIMPEDANCE AMPLIFIER, medida con stage 2 disabled), NO del ADC. El ADC tiene su propia spec: **ADC full-scale voltage = ±1.2 V**. Cuadro correcto: 1 V = límite lineal especificado TIA (diff) · ~1.94 V diff = clip físico medido · ±1.2 V = rango de digitalización ADC. Pendiente menor: verificar qué FS usa `_compute_analog_state()` para code→V_ADC (la pendiente AMBDAC del sweep −0.197 vs −0.2 V/µA sugiere que ya es correcta).

**Verificación `v_tia_branch` (sesión paralela):** 0 ocurrencias en código (PulseNest + incunest_afe4490); solo en documentación (Regla 4b en conversation_log y memoria). Coherente con Opción B.

**BUG FIX — ventanas secundarias no se cerraban al cerrar el main window (lab v1.10, sesión paralela):**
- Síntoma: al cerrar la ventana principal, las secundarias quedaban abiertas y el proceso vivo.
- Causa (crash.log, repetida en cada cierre): `closeEvent` — `hasattr(self, 'ser') and self.ser.is_open` lanza `AttributeError` cuando `self.ser is None` (sesión solo-UDP). La excepción abortaba `closeEvent` antes del bloque que cierra las secundarias (todas con `parent=None` por la regla Alt-TAB → Qt no las cierra en cascada) y antes de `QApplication.quit()`.
- Fix 1: guarda cambiada a `getattr(self, 'ser', None) is not None and self.ser.is_open`.
- Fix 2 (encontrado de paso): `lib_config_window` (LIB CONFIG) faltaba en la lista de cierres de `closeEvent` — única ventana ausente desde v1.7. Añadida.
- Compilación OK. Spec actualizada a v1.10 (§12 changelog).

---

## Sesión 2026-07-09 — AFE SWEEP TEST: OT1/OT2 → OT_LED1/OT_LED2 (lab v1.11)

**Pregunta:** condición de PROBE_DISCONNECTED → criterio instantáneo AND de 6 condiciones en `_update_rsqm()`: |i_pd| de los 4 canales < `rsqm_disconn_i_pd_thr` (150 nA) Y |led1_sub|,|led2_sub| < `rsqm_disconn_led_sub_thr` (5000 counts). Sin fotodiodo, i_pd solo refleja bias de TIA (~nA); led_sub≈0 confirma entrada flotante. Pasa por debounce de `_set_probe_state()`.

**Cambio pedido:** columnas OT1/OT2 del CSV del AFE SWEEP TEST salían vacías; renombrar a OT_LED1/OT_LED2 y mover al final.
- Causa raíz del vacío: el bloque legado usaba `_mon = self.parent()`, pero la ventana se crea con `parent=None` (regla Alt-TAB) → `_cfg={}` → siempre "". Además fórmula legado sin sentido físico (LED_Sub_mean/(mA·Ω·RG)).
- Implementación: `OT_LED1/OT_LED2` al final del header (92 columnas, sin cambio de total); cálculo `(mean(I_PD_LED) − mean(I_PD_ALED)) / I_LED` [A/A] desde los buffers I_PD del $M4 — misma fórmula que `_update_rsqm()` del firmware y que las columnas OT_LED del main window. Formato `{:.3e}`; vacío si buffers vacíos (modo no-$M4) o LED mA no numérico.
- Spec v1.11: changelog + §7.18 reescrita (describía 40 columnas, el CSV real tiene 92).
- Nota: el header solo se escribe si el fichero no existe → usar fichero CSV nuevo para no desalinear columnas con capturas antiguas.

---

## Sesión 2026-07-08d — Consolidación del diseño HGAC en un único fichero

**Tema:** el usuario detectó que el diseño HGAC estaba repartido en 3 sitios (`project_agc_design.md`, `project_hgac_task.md` y el detalle de las sesiones 2026-07-07/08 de este log) y pidió consolidarlo ("validar los objetivos y la arquitectura probablemente nos lleve muchísimo tiempo" → mejor consolidar ahora, no después de la validación).

**Trabajo realizado (solo memoria/documentación, sin cambios de código):**
- `memory/project_agc_design.md` **reescrito completo como documento ÚNICO del diseño HGAC**. Estructura: §0 estado (validado/pendiente), §1 base conceptual absorbida de project_hgac_task.md (ubicación en librería, ventana 2 s / mediana P², separación RSQM/HGAC, diag bits 4/5, control proporcional + histéresis, no reaccionar a artefactos), §2 física V_TIA resuelta (convención diferencial, Regla 4b, límites empíricos del sweep, constantes en código, ausencia deliberada de límites inferiores), §3 actuadores (nomenclatura, efectos, física LED>RF>RG/AMBDAC-neutro, acoplamiento F4), §4 fallos F1-F7 detallados (absorbidos del log 2026-07-07/08), §5 objetivos G0/O1-O10 con validaciones del usuario (O1→O2, target 50%FS), §6 arquitectura solver FASE A-D + preguntas abiertas 1/2/4/5, §7 diseño legado P1-P4 completo marcado como cuestionado/capa de emergencia (con avisos explícitos: target 40%FS invalidado → 50%; F1/F2/F3/F7), §8 decisiones misceláneas confirmadas.
- `memory/project_hgac_task.md` **borrado** (contenido íntegramente absorbido — política de ficheros de memoria: borrar los absorbidos).
- `memory/MEMORY.md`: eliminada la entrada de project_hgac_task; entrada de project_agc_design reescrita señalándolo como documento único.

**Próximo paso (sesiones futuras):** validar O3-O10 y la arquitectura solver feed-forward; responder preguntas abiertas 1, 2, 4, 5. Punto de entrada: `memory/project_agc_design.md` §0.

---

## Sesión 2026-07-10 — AFE4490AnalogState: OT + estrategia de invalidez por saturación (lib v0.35)

**Contexto:** continuación de la sesión de diseño HGAC. Antes de retomar la lista de problemas prioritarios, Alex pidió añadir `ot_led1`/`ot_led2` a `AFE4490AnalogState`, pero exigió diseñar primero la estrategia de gestión de invalidez cuando la saturación de un valor invalida los que dependen de él.

**Preguntas clave del diálogo de diseño:**
- ¿NaN o valor calculado cuando la cadena está saturada? → 3 casos donde el valor es útil (TIA off-spec = valor correcto; ADC clip = cota accionable; visualización de trazas) → **valor-siempre + máscaras de validez** (sin NaN, sin sentinels).
- ¿Flags por etapa o por canal? → **Opción A (por etapa)**, con helpers inline obligatorios para poder migrar a opción B sin tocar consumidores.
- Semántica de estados: **CH_CLEAN** (medida fiable) / **CH_OFF_SPEC** (v_tia_diff en 1.0–1.8 V: fuera de garantía TI pero empíricamente lineal — el valor es probablemente correcto, solo cambia el respaldo) / **CH_CLIPPED** (ADC saturado o TIA > 1.8 V: el valor es COTA, no medida). Precedencia CLIPPED > OFF_SPEC > CLEAN. Nombres BOUND/DEGRADED rechazados.
- ¿Umbrales en la struct? → Desafío de Alex: ¿hay razón real para configurarlos en runtime? No (fs=datasheet, sat=silicio, lin=caracterización offline por placa) → **`static constexpr` en la struct**. Física → struct; política HGAC (`hgac_v_tia_diff_thr`=0.9, `ideal`=0.6) → controlador.

**Implementación (incunest_afe4490 v0.35, build OK V15/V16/V17):**
- `incunest_afe4490.h`: enums `AFE4490Ch` (bit index) y `AFE4490ChState`; struct con `ot_led1/ot_led2`, 4 máscaras (`adc_sat_pos/neg`, `tia_over_fs/lin`, bit=canal), constantes `kVTiaDiffFs=1.0/kVTiaDiffLin=1.8/kAdcSatPos/Neg=±2096921`, helpers (`chState`, `chClean`, `otLedxValid` estricto solo-CLEAN, `anyAdcSat` O1, `anyTiaOverFs` O2, `allClean`). Eliminados `rsqm_ot_saturated` y `rsqm_adc_positive_sat`.
- `incunest_afe4490.cpp`: `_compute_analog_state()` calcula OT + máscaras (sin límite inferior TIA: fotocorriente unipolar); `_update_rsqm()` consume `as.ot_ledx` + `otLedxValid()` — política de saturación ahora EXPLÍCITA (antes escondida en el sentinel 100.0) y más estricta que pre-v0.35 (ambos raíles, ALED incluido, linealidad TIA); `RSQM_AMB_SAT` via `adcSatPos(ALEDx)`; `hgac_v_tia_diff_fs` sustituida por `kVTiaDiffFs`.
- `incunest_afe4490_spec.md` v0.35: §3c reescrito (struct + política valor-siempre + racional de umbrales), §5.6.2, §5.6.3, historial v0.35. `library.json` 0.35.0.
- Detectado: faltan las entradas v0.33/v0.34 en el historial de versiones de la spec (pendiente).

**Fallos de test nativos preexistentes** (`pio test -e native`: no encuentra `incunest_afe4490.h` — infraestructura, no relacionado con este cambio; ya recogido en project_unit_tests_task).

**Pendiente de retomar:** lista de problemas prioritarios HGAC (P1-P8 propuestos, sin validar); exponer ot/máscaras en $M4 (enlaza project_vtia_gray_task); calibración empírica de rsqm_ot_thr.

### Adenda 2026-07-10 — Caracterización empírica de raíles ADC (corrige kAdcSatPos/Neg)

Alex midió empíricamente los raíles del ADC (via AMBDAC): **positivo = +2096921** (constante e igual en los 4 canales; NO coincide con 2^21−1 = 2097151); **negativo = −2096919** (constante en led1/led2; aled1/aled2 NO clavan el rail — oscilan aprox. entre −2096912 y −2096810, mecanismo: el ADC averaging mezcla conversiones clipadas y no clipadas en la ventana).

**Bug destapado:** el supuesto de simetría `kAdcSatNeg = −2096921` hacía la comparación `code <= kAdcSatNeg` imposible de cumplir (rail real 2 counts por encima) → `adc_sat_neg` era un flag muerto.

**Decisión:** banda de guarda de ~220 counts (×2 la peor distancia ALED-rail observada, 109 counts) hacia dentro del rail, aplicada a AMBAS polaridades (el mecanismo del averaging no depende del signo) → `kAdcSatPos = +2096700`, `kAdcSatNeg = −2096700`. Falso positivo impracticable: un código legítimo a <220 counts del rail (0.01% del rango) está funcionalmente saturado. Corregido también el comentario heredado "≈95% of FS" (era falso). Spec §3c: nueva sección "ADC rail characterization". Build V16 OK.

### Adenda 2026-07-10b — Cita de datasheet errónea en la escala ADC→V (comentario)

Pregunta de Alex: ¿dónde indica el datasheet la escala de `incunest_afe4490.cpp:1096` (`scale = kAFE_ADC_FSR / kAFE_ADC_FS_COUNTS`)? Rastreo completo del PDF: **el datasheet no da la fórmula explícita en ningún sitio** — se deriva de dos lugares: **p.11** (Electrical Characteristics, ADC: Resolution 22 bits, ADC full-scale voltage ±1.2 V) + **p.43 §8.4.1** ("ADC output format is in 22-bit twos complement; the two MSB bits of the 24-bit data can be ignored") → 1 LSB = 1.2 V / (2²¹−1) ≈ 0.572 µV.

El comentario del código citaba "Datasheet p.26" (incorrecto — p.26 son Typical Characteristics). Corregido a p.11 + p.43 en 3 sitios: `incunest_afe4490.cpp` (~1094), `incunest_afe4490.h` (~206, constantes kAFE_ADC_*) e `incunest_afe4490_spec.md` (bloque de constantes + fórmula V_ADC). Cambio solo de documentación — sin bump de versión.

Además, a petición de Alex: el comentario de `kAdcSatPos/Neg` en `incunest_afe4490.h` no decía que el raíl +2096921 procede de un test empírico realizado por él — ahora indica explícitamente "rails measured empirically via an AMBDAC sweep test on IncuNest 16.A hardware (2026-07-10)". Mirroreado en la spec (§3c, bloque de constantes). Retoque posterior (también a petición): "positive rail" / "negative rail" → "empirical positive rail" / "empirical negative rail" en el mismo comentario (+ reflow del párrafo). Cambios solo de comentarios — sin bump de versión.

---

## Sesión 2026-07-11 — Auditoría de consumidores de flags RSQM + rename RSQM_DIAG_* (lib v0.36, lab spec v1.12)

**Pregunta de Alex:** preocupación por chequeos de la librería sin consumidor que los valide — ¿quién consume los flags `RSQM_AMB_SAT`/`RSQM_SIGNAL_WEAK`/`RSQM_HW_SETTLING`?

**Auditoría de consumidores (resultado):**
- Único consumo FUNCIONAL: gate agregado `rsqi = (diag_code == 0)` (cpp) — nadie lee los bits individuales para actuar.
- Resto = transporte/display: PulseNest main.cpp serializa `diag_code` en $M2/$M3/$M4; pulsenest_lab lo muestra (tabla + tooltip + CSV); IncuNest motherBoard (CommTask.cpp:838) solo lo imprime.
- **`RSQM_HW_SETTLING` es inalcanzable:** nadie pone `_rsqm_settling_countdown > 0` (productor previsto: HGAC, no implementado).

**Decisión de Alex:** (1) documentar como CÓDIGO ADELANTADO que puede no usarse nunca (HGAC podría hacer sus propios chequeos internos sin leer estos flags); (2) renombrar prefijo `RSQM_` → `RSQM_DIAG_` (simétrico con `AFE_DIAG_*`, evita colisión conceptual con los params operativos `rsqm_*`).

**Implementación (lib v0.36, build V16 OK):**
- `incunest_afe4490.h/.cpp/spec`: rename `RSQM_DIAG_AMB_SAT`/`RSQM_DIAG_SIGNAL_WEAK`/`RSQM_DIAG_HW_SETTLING`; bloque "ANTICIPATORY CODE" en header (junto a las constantes) y spec §5.6.3 (validarlos = parte del definition-of-done de HGAC); entrada histórica v0.27 preservada con nota "(renamed RSQM_DIAG_* in v0.36)". `library.json` 0.36.0.
- `pulsenest_lab.py` (sin cambios funcionales): tooltips DiagCode (SIGNAL STATS) y `rsqm_signal_weak_std` (LIB CONFIG) actualizados con nuevos nombres + nota anticipatory. `pulsenest_lab_spec.md` v1.12 con changelog.
