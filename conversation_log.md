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

