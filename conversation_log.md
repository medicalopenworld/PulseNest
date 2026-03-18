# Log de conversaciones — Pulsioximeter Test (AFE4490)

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
