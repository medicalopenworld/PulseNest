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

## Done / promoted

- [x] EMA de RSQM como código muerto tras SIGNAL_WEAK → RESUELTO v0.57 (eliminados EMA + `ready` + τ; ver conversation_log 2026-08-07)


<!-- Triaged items land here briefly before removal, or are deleted outright. -->
