# TODO — Pulsioximeter Test (AFE4490)

> Mantenido de forma incremental. Añadir items al final de cada sección; marcar como `[x]` cuando se completen.

---

## Bugs activos

- [ ] **Bug hot-swap:** ESP32, a veces, deja de enviar datos al cambiar de librería con `'m'`/`'p'`. Siguiente paso: reproducir y leer consola Python buscando `Guru Meditation Error`, `DRDY timeout` o corte silencioso de tramas.
- [ ] **Bug HR1/HR2 a 30 BPM:** con el simulador MS100 a 30 BPM, HR1 y HR2 no funcionan correctamente. Detectado tras extender el rango a 30–250 BPM. Investigar si el problema es en `hr2_acorr_max_lag`, en el periodo refractario, en el warmup, o en la señal del simulador a esa frecuencia.

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

## Pendientes firmware (mow_afe4490 / main.cpp)

- [ ] **HR1 — derivada antes de buscar picos** — aplicar derivada a la señal filtrada antes del detector de picos para mejorar la precisión en la localización del frente de subida.
- [x] **Flash y validar HR2** con simulador — valores coherentes con HR1 confirmados (2026-03-31).
- [ ] **HR3 — FFT** — añadir un tercer algoritmo de HR basado en FFT como alternativa/complemento a HR1 y HR2.
- [ ] **HR4 — Peak detection** — detección del frente de subida mediante derivada de la señal filtrada (máximo de la derivada = pendiente máxima ascendente), como mejora de precisión sobre el threshold crossing de HR1.
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
- [ ] **Calibrar coeficientes SpO2** (`setSpO2Coefficients`) con sensor real.
- [ ] **Validación general con hardware real** (la mayoría de pruebas se han hecho con simulador).
- [ ] **Validar algoritmo HR en condiciones adversas:** (1) baja perfusión, (2) luz ambiental, (3) artefactos por movimiento.
- [ ] **Detección de luz ambiental excesiva** — chequear si ALED1/ALED2 superan un umbral que indique que el sensor no está bien colocado; emitir aviso (flag en `AFE4490Data` o log serie).

---

## Estrategia de test

- [x] **Tests unitarios de algoritmos en PC (env:native)** — 20/20 PASSED (2026-03-31): biquad (5), HR1 (4), HR2 (4), SpO2 (6). Infraestructura: lib/mow_afe4490/, test/stubs/, env:native.
- [ ] **Dataset de referencia con simulador MS100** — capturar CSVs con ppg_plotter.py a SpO2 y HR conocidas (p.ej. 98%, 90%, 80% / 60, 80, 100 bpm); usar como ground truth para regresión: si cambia el algoritmo, verificar que los valores no se desvían del golden dataset.

---

## Pendientes ppg_plotter.py

- [x] **HR3LabWindow** — renombrado de HRLab2Window; implementado con espectro FFT, señal filtrada, comparativa HR1/HR2/HR3 y barra de diagnóstico (2026-04-07).
- [x] **Control de decimación en ventana principal** — spinbox "1 de cada N tramas" (defecto 10); aplica a consola y gráficas (2026-03-31).
- [x] **Botón GUARDAR RAW (500 Hz)** — guarda todas las tramas antes del diezmado; GUARDAR DATOS guarda tramas decimadas (2026-03-31).

---

## Backlog funcionalidades avanzadas (mow_afe4490)

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
