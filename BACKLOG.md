# BACKLOG — PulseNest

Quick inbox for ideas that pop up mid-session. Jot one line and move on — do not
stop to flesh it out here.

**How to use**
- Add a bullet under _Inbox_ the moment an idea appears: `- [ ] the idea`.
- Optional second line for context if the one-liner is not enough.
- Keep it raw. This is a capture buffer, not a spec.

**Triage (end of session)**
Claude reviews _Inbox_ at the end of each session and, for each item:
- Promotes survivors to a task memory (`project_*_task.md`) or a `conversation_log.md` decision.
- Deletes the ones that no longer make sense.
- Marks handled items done (`- [x]`) here, or removes them once promoted.

Anything already promoted lives in the memory system — this file only holds what
has not been triaged yet.

---

## Inbox

<!-- Add new ideas below. One line each; optional indented context line. -->
- Añadir a la nomenlatura del proyecto "adc_code" para salidas del ADC (y quizás LSB
  para variaciones/intervalos/errores/tolerancias de adc_code)
- Estudiar el solapamiento entre los estados PROBE_SATURATING y el resto
- Estudiar la posibilidad de cambiar tia_diff por tia (eliminar diff)
- Estudiar por qué para decidir PROBE_SATURATING usamos anyPositiveSaturation/tiaOverFs(FS_V) en vez de GUARD_V  
- Al igual que existe tia_axis, te propongo un adc_axis ( kAdcSatPos, kAdcSatNeg, kAFE_ADC_FS_CODE, kAFE_ADC_FSR, 2096921(actual max), -2096919(actual min)
- La saturación por clipado de las puntas de la señal PPG puede producirse durante un número de muestras inferior a _rsqm_probe_state_min_samples (100 muestras)
- Si RF pasa al valor mínimo (10K) comprobar que ALED1/2 no están saturados, ya que habría que generar una alarma por luz ambiental excesiva (en esta situación bajar ILED no resuelve el problema)
- Estudiar cada cuánto debe actual HGAC
- Estudiar búffer de 10 estadísticos de 1 s (si hace falta más resolución temporal se disminuye 1 s o se divide cada estadístico en otro búffer de 2,3,4,5,... estadísticos)
- En los ficheros de captura aparece "HR3 LPF: 15.00 Hz" en vez de BPF ¿por qué no se filtran las bajas frecuencias?
- Analizar por qué HIGH2 está en tia_axis y HIGH1/LOW1 no lo están
- Analizar la situación RF=10K y aled1/2 
- Propuesta: que la alarma RSQM_DIAG_AMBIENT_HIGH genere un mensaje en el log del script cuando se active o cuando se desactive
- Si la sonda no está aplicada es muy posible que led1/2 estén saturados pero aled1/2 no (si no hay mucha luz ambiental)
	Esta situación actualmente provoca PROBE_SATURATING pero quizás deberíamos etiquetarla como PROBE_NOT_APPLIED.
- la línea incunest_afe440.h:1127 induce a confusión (uint32_t       _rsqm_probe_state_min_samples { 100 }; )	
- Segun claude:  2. El filtro de 500 Hz post-stage2 (~1.6 ms de 5τ) y el acoplamiento CF↔RF en _hgac_change_rf() — ¿se recalcula C_F de forma atómica junto con el
  paso de RF, o queda una ventana desincronizada? Quedó fuera del alcance de hoy.
- Apunta como tarea pendiente: estudiar la posibilidad de anular STAGE2 ya que no la
  usamos (ventajas e inconvenientes)
- whatsapp de Pablo del 14-ago
- La trama $M4 a veces no se envía por defecto (se envía la $M3)
- _spo2_update() resetea constantemente ¿Merece la pena cambiar el código para que resetee sólo cuando es necesario? (ventajas y desventajas/inconvenientes/riesgos)
- Estudiar si la señal DC podría ser utilizada para alguno de los dos siguientes usos:
	1. El Anexo AA de la norma ISO explica que un %mod teóricamente aceptable puede ser clínicamente inútil si el nivel de DC es extremadamente bajo
	2. Detección de Desequilibrio por Pigmentación (Melanina) o Tejido Grueso. Si el DC del Rojo es excesivamente bajo en comparación con el del Infrarrojo debido a una piel oscura, el sistema sabrá que la señal roja es altamente vulnerable al ruido del detector

## Done / promoted

- [x] EMA de RSQM como código muerto tras SIGNAL_WEAK → RESUELTO v0.57 (eliminados EMA + `ready` + τ; ver conversation_log 2026-08-07)
- [x] `tia_settle_min` depende de PRF (y otras también) → PROMOVIDO a tarea de análisis 2026-08-22.
      Analizado: el suelo fijo en tiempo es la forma correcta (TI §8.3.1.3: el margen es para
      LED+cable, no depende de PRF); lo que no tiene base física es el 10 %, que además es el que
      gobierna por debajo de ~2,4 kHz. Hallazgo mayor de paso: `setSampleRate` acepta hasta 5000 Hz
      pero desde ~2500 Hz los registros ALED se **invierten** (`ambient_margin` = 400 counts fijo,
      sin guard) y desde 2000 Hz la ventana de ambiente ya baja del mínimo de 50 µs de TI.
      Pendiente: decidir el techo de PRF soportado. Ver memoria
      `project_prf_range_settle_windows_task` y conversation_log 2026-08-22.


<!-- Triaged items land here briefly before removal, or are deleted outright. -->
