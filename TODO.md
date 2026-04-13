# TODO — Pulsioximeter Test (AFE4490)

> Mantenido de forma incremental. Añadir items al final de cada sección; marcar como `[x]` cuando se completen.

---

## Bugs activos

- [ ] **Bug hot-swap:** ESP32, a veces, deja de enviar datos al cambiar de librería con `'m'`/`'p'`. Siguiente paso: reproducir y leer consola Python buscando `Guru Meditation Error`, `DRDY timeout` o corte silencioso de tramas.
- [ ] **Bug HR1/HR2 a valores bajos de BPM:** con el simulador MS100 a 30 BPM, HR1 y HR2 no funcionan correctamente. El rango reportado es ahora 25–300 BPM (guard band interna 22–303 BPM). Investigar si el problema es en `hr2_acorr_max_lag`, en el periodo refractario, en el warmup, o en la señal del simulador a esa frecuencia.

---

## Investigación y requisitos

- [ ] **Requisitos metrológicos — normas** — revisar ISO/IEC 80601-2-61 (oxímetro de pulso) y normas relacionadas; extraer requisitos de precisión, rango, alarmas y condiciones de test aplicables a SpO2/HR.
- [ ] **Análisis de sensibilidad de parámetros AFE4490** — estudiar el impacto de:
  - Corriente de LEDs (`LEDxSTC` / `LEDxENDC`)
  - Ganancia del TIA (Rf interno)
  - Ganancia del ADC / etapa posterior
  - Temporización completa del ciclo (TIMING ENGINE)
- [ ] **Analizar uso de las 6 señales del AFE4490** — no limitarse a las diferencias `LEDx_ALEDx`; determinar si las señales individuales (`LED1`, `LED2`, `ALED1`, `ALED2`, `LED1-ALED1`, `LED2-ALED2`) aportan información adicional útil.

---

## Pendientes documentación

- [ ] **Actualizar `incunest_afe4490_spec.md` — arquitectura async FreeRTOS** — documentar en §6 la separación en 3 tareas (Task A muestreo prio 5, Task B HR2 prio 4, Task C HR3 prio 4) con semáforos binarios, mediciones de CPU% y stack.

---

## Pendientes firmware (incunest_afe4490 / main.cpp)

- [ ] **HR1 — derivada antes de buscar picos** — aplicar derivada a la señal filtrada antes del detector de picos para mejorar la precisión en la localización del frente de subida.
- [x] **Flash y validar HR2** con simulador — valores coherentes con HR1 confirmados (2026-03-31).
- [x] **HR3 — FFT** — algoritmo FFT + HPS implementado en firmware (2026-04-08): LP 10 Hz → decimate ×10 → buffer 512 → Hann → FFT radix-2 DIT → HPS (P[k]·P[2k]·P[3k]) → interpolación parabólica. Expuesto en trama M1 (campo 17). ppg_plotter.py actualizado.
- [ ] **HR4 — AMDF (Average Magnitude Difference Function)** — estimación de HR mediante AMDF normalizado: `AMDF_n[τ] = AMDF[τ] / (AMDF_mean + ε)` para invarianza ante cambios de amplitud. Ventana adaptativa: ajustar el tamaño de la ventana de análisis en función de la estimación de HR previa (al menos 2–3 ciclos). Threshold dinámico: el mínimo válido se acepta sólo si cae por debajo de una fracción configurable del valor medio de AMDF (p.ej. 0.6·mean), descartando mínimos espurios en señales ruidosas. Alternativa robusta a la autocorrelación, especialmente en señales con baja SNR o formas de onda asimétricas. Evaluar como método independiente y comparar con HR1/HR2/HR3.
- [ ] **HR5 — Peak detection** — detección del frente de subida mediante derivada de la señal filtrada (máximo de la derivada = pendiente máxima ascendente), como mejora de precisión sobre el threshold crossing de HR1.
- [ ] **Fiabilidad (confidence) de HR1, HR2, HR3** — calcular un valor porcentual de fiabilidad para cada algoritmo:
  - HR1: posible métrica basada en consistencia de los 5 intervalos RR (coeficiente de variación inverso)
  - HR2: `peak_val` de la autocorrelación ya disponible (0–1); expresar como porcentaje
  - HR3: `peak_power_ratio` ya disponible en `HRFFTCalc` (fracción de potencia en banda HR concentrada en el pico); expresar como porcentaje
  - Exponer como campo en `AFE4490Data` y en trama serie cuando esté definido
- [ ] **Grado de certidumbre SpO2** — añadir algún indicador de fiabilidad a la medida de SpO2; definir métrica y API.
- [ ] **PI — Perfusion Index** — implementar `PI = AC/DC * 100`:
  - AC: amplitud pico a pico o RMS de la ventana sin DC
  - DC: media móvil o filtro paso bajo
  - Recomendación: filtro paso-banda 0.5–4 Hz + amplitud latido a latido
  - Calcular `PI(IR)` y `PI(RED)` por separado y comparar (IR: mayor penetración, menos sensible a color de piel, luz ambiente y movimiento)
  - Evaluar si el LED IR es el más adecuado para PI
- [ ] **PI como índice de fiabilidad de SpO2** — estudiar si PI puede usarse para validar o ponderar la medida de SpO2.
- [ ] **PI — RMS vs pico a pico** — analizar la idoneidad del método actual (AC_rms / DC_ir × 100) frente al uso del valor AC pico a pico: cuál es más representativo fisiológicamente, más robusto ante ruido, y más coherente con la definición usada por los fabricantes de pulsioxímetros comerciales.
- [ ] **Calibrar coeficientes SpO2** (`setSpO2Coefficients`) con sensor real.
- [ ] **Validación general con hardware real** (la mayoría de pruebas se han hecho con simulador).
- [ ] **Validar algoritmo HR en condiciones adversas:** (1) baja perfusión, (2) luz ambiental, (3) artefactos por movimiento.
- [ ] **Probe presence detection** — diseñar estrategia y algoritmo explícito de detección de presencia del sensor. Actualmente es implícita (umbral DC en SpO2, PI en SQI); se necesita un módulo propio, genérico y configurable.
- [ ] **Verificación de consistencia `LED1_ALED1 == LED1 − ALED1`** — comprobar que el valor hardware del registro `LED1_ALED1VAL` (0x2F) coincide con la resta software `LED1 − ALED1` (y lo mismo para `LED2_ALED2`). Una discrepancia indicaría un problema de lectura SPI o de sincronización. Implementar tanto en firmware (assert/log) como opcionalmente en `ppg_plotter.py` (diagnóstico visual de la diferencia en tiempo real).
- [ ] **Registro DIAG (0x30)** — utilizar el registro de diagnóstico del AFE4490 (`DIAG`, address 0x30) para diagnosticar el estado del sistema, especialmente el estado de la sonda (LED abierto/cortocircuito, fotodiodo, etc.).
- [ ] **Detección de luz ambiental excesiva** — chequear si ALED1/ALED2 superan un umbral que indique que el sensor no está bien colocado; emitir aviso (flag en `AFE4490Data` o log serie).

---

## Estrategia de test

- [x] **Tests unitarios de algoritmos en PC (env:native)** — 20/20 PASSED (2026-03-31): biquad (5), HR1 (4), HR2 (4), SpO2 (6). Infraestructura: lib/incunest_afe4490/, test/stubs/, env:native.
- [ ] **Dataset de referencia con simulador MS100** — capturar CSVs con ppg_plotter.py a SpO2 y HR conocidas (p.ej. 98%, 90%, 80% / 60, 80, 100 bpm); usar como ground truth para regresión: si cambia el algoritmo, verificar que los valores no se desvían del golden dataset.
- [ ] **Dataset de referencia con sujetos reales** — capturar medidas simultáneas con el AFE4490 y equipos de referencia clínicos (pulsioxímetro de referencia, co-oxímetro si disponible) sobre voluntarios sanos; registrar SpO2 y HR de ambos sistemas para calcular sesgo, RMSE y límites de acuerdo (Bland-Altman). Condiciones a cubrir: reposo, tras ejercicio, distintas saturaciones si es posible.

---

## Pendientes ppg_plotter.py

- [x] **HR3LabWindow** — renombrado de HRLab2Window; implementado con espectro FFT, señal filtrada, comparativa HR1/HR2/HR3 y barra de diagnóstico (2026-04-07).
- [x] **Control de decimación en ventana principal** — spinbox "1 de cada N tramas" (defecto 10); aplica a consola y gráficas (2026-03-31).
- [x] **Botón GUARDAR RAW (500 Hz)** — guarda todas las tramas antes del diezmado; GUARDAR DATOS guarda tramas decimadas (2026-03-31).

---

## Backlog funcionalidades avanzadas (incunest_afe4490)

> No implementar hasta que el usuario lo pida explícitamente.

- [ ] **HRV** — variabilidad de la frecuencia cardíaca a partir de intervalos RR del PPG:
  - Dominio temporal: RMSSD, SDNN, NN50/pNN50, media RR
  - Dominio frecuencial: VLF (< 0.04 Hz), LF (0.04–0.15 Hz), HF (0.15–0.4 Hz), ratio LF/HF
  - Prerequisito: HR1 o HR4 con detección de pico real (no threshold crossing) para extraer intervalos RR precisos
  - Analizar validez del uso de PPG vs ECG para HRV: el PPG introduce retardo mecánico variable (PTT) y jitter adicional respecto al intervalo RR eléctrico; revisar literatura sobre concordancia PPG-HRV vs ECG-HRV y sus limitaciones
- [ ] **Detección de arritmias** — taquicardia, bradicardia, FA, extrasístoles.
- [ ] **Frecuencia respiratoria** — modulación de amplitud/baseline del PPG (RSA).
- [ ] **Detector de apneas** — ausencia o irregularidad prolongada del patrón respiratorio derivado del PPG.
- [ ] **Detector de artefactos / PMAF** — movimiento del sensor, cambios de luz ambiental.
- [ ] **Cambios vasculares agudos** — PTT, amplitud, área bajo la curva, tiempo de subida, perfusión periférica.
- [ ] **Coeficientes biquad dinámicos** — ya implementados (`_recalc_biquad`). Pendiente: exposición de API pública para adaptación en runtime desde la aplicación.
- [ ] **Elasticidad arterial** — estimación basada en el tiempo de subida (rise time) del pulso PPG como indicador indirecto de rigidez vascular.
- [ ] **Precisión temporal del muestreo (500 Hz)** — verificar que el jitter/deriva del timer de muestreo es despreciable respecto a la precisión requerida en HR; si no lo es, evaluar impacto y corrección.
