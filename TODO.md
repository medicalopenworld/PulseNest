# TODO — Pulsioximeter Test (AFE4490)

> Mantenido de forma incremental. Añadir items al final de cada sección; marcar como `[x]` cuando se completen.

---

## Bugs activos

- [ ] **Bug hot-swap:** ESP32, a veces, deja de enviar datos al cambiar de librería con `'m'`/`'p'`. Siguiente paso: reproducir y leer consola Python buscando `Guru Meditation Error`, `DRDY timeout` o corte silencioso de tramas.

---

## Pendientes firmware (mow_afe4490 / main.cpp)

- [ ] **HR1 — derivada antes de buscar picos** — aplicar derivada a la señal filtrada antes del detector de picos para mejorar la precisión en la localización del frente de subida.
- [ ] **Flash y validar HR2** con simulador y/o hardware real (compilación OK, pendiente de subir a placa).
- [ ] **Calibrar coeficientes SpO2** (`setSpO2Coefficients`) con sensor real.
- [ ] **Validación general con hardware real** (la mayoría de pruebas se han hecho con simulador).
- [ ] **Validar algoritmo HR en condiciones adversas:** (1) baja perfusión, (2) luz ambiental, (3) artefactos por movimiento.

---

## Pendientes ppg_plotter.py

- [ ] **HRLab2Window** — layout creado (3×3 grid, proporciones 2:1:1) pero uso pendiente de definir.

---

## Backlog funcionalidades avanzadas (mow_afe4490)

> No implementar hasta que el usuario lo pida explícitamente.

- [ ] **HRV** — variabilidad de la frecuencia cardíaca a partir de intervalos RR del PPG.
- [ ] **Detección de arritmias** — taquicardia, bradicardia, FA, extrasístoles.
- [ ] **Frecuencia respiratoria** — modulación de amplitud/baseline del PPG (RSA).
- [ ] **Detector de apneas** — ausencia o irregularidad prolongada del patrón respiratorio derivado del PPG.
- [ ] **Detector de artefactos / PMAF** — movimiento del sensor, cambios de luz ambiental.
- [ ] **Cambios vasculares agudos** — PTT, amplitud, área bajo la curva, tiempo de subida, perfusión periférica.
- [ ] **Coeficientes biquad dinámicos** — ya implementados (`_recalc_biquad`). Pendiente: exposición de API pública para adaptación en runtime desde la aplicación.
- [ ] **Elasticidad arterial** — estimación basada en el tiempo de subida (rise time) del pulso PPG como indicador indirecto de rigidez vascular.
