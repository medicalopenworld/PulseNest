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
- Analizar por qué setHR2UpdateInterval recibe omo parámetro un número de muestras en vez de un intervalo de tiempo. Parece que la librería no se autoconfigura con los cambios del sampling rate del AFE.
-HR1current: cómo se ha calculado el factor de decaimiento del máximo/umbral (parece que decae demasiado lengo)
-HR1SSF(Zong): falla a 250 BPM un latido dura 240 ms) la ventana fija de 128 ms (que convoluciona la derivada) no se adapta a valores de HR altos
-HR1TERMA: utiliza dos ventanas de promediado móviles de 0.111 y 0.667 que probablemente no sean adecuadas para HR altas 
- Analizar la posibilidad de que los algoritmos sean adaptativos (sus parámetros) en función de la estimación de HR prevista teniendo en cuenta los resultados previos:
	1. Del propio algoritmo
	2. Del conjunto de todos los algoritmos HR1,HR2,HR3 (sobre todo si coinciden entre ellos)
	3. Una tarea inicial es hacer una lista de los parámetros candidatos a ser adaptativos
	4. Claude comenta que en tecnología médica hay algún principio de independencia entre medidas, pero no sé si aplica en este caso porque siempre estamos hablando de HR
- Utilizar las señales ambientales ALED (por ejemplo su varianza) como de detector de MAs (movement artifacts) para un tratamiento similar al de sensores inerciales/acelerometros que se utiliza en el tratamiento de medidas PPG en wearables
- Creo que habría que subir rsqm_ot_thr (OT threshold para detectar PROBE_APPLIED) porque los dedos pueden llegar a ser muy finos. El inconveniente no sería con sondas tipo brida o pinza, sino con sondas abiertas donde el led y el fotodiodo no quedan enfrentados al quitar el dedo (por ejemplo las desechables)
- Creo que _diag_task_body() también debería incluir PROBE_AMB_SATURATING (quizás todavía se llame PROBE_SATURATING) o mejor aún que sea distinta a PROBE_APPLIED.
- Creo que pequeños movimientos de la sonda bajan el SQI de HR3 de forma innecesaria (pero no estoy seguro)



## Done / promoted

- [x] **`esp_wifi_set_ps(WIFI_PS_NONE)`** → APLICADO y MEDIDO 2026-09-10. PulseNest no lo configuraba (defecto Arduino `WIFI_PS_MIN_MODEM`); motherBoard sí, con el comentario *"Mobile hotspots often drop power-saving clients"*. Añadido `WiFi.setSleep(WIFI_PS_NONE)` en `src/main.cpp` tras `WiFi.mode(WIFI_STA)`, flasheado en 16.A y 17.A. **El efecto depende por completo de si la placa está emitiendo**, y se midieron los dos regímenes con `tools/udp_cmd_latency.py` (ida y vuelta de `$CFG?`, ruta de bajada):
	- **Emitiendo 100 datagramas/s, operación normal: no cuesta nada medible.** 16.A p50 19 ms sin el cambio, 16-22 ms con él. Una placa que transmite cada 10 ms casi nunca duerme de verdad y el suelo lo pone el ciclo de 50 ms de `Cmd_Task`.
	- **Radio en reposo** (build con `-DPULSENEST_NO_DATA_STREAM`, misma placa y sesión): modem sleep activo p50 **259 ms**, media 233, con la masa entre 200 y 280 ms, que es el ciclo DTIM del punto de acceso; desactivado p50 **55 ms**, media 38, nada por encima de 63 ms. **Penalización de 4,7× en la mediana.** Eso es lo que compra la llamada.
	- **Consecuencia para F4b:** cualquier placa con el stream apagado paga esos ~250 ms por comando, que es justo el caso de motherBoard cuando el stream PulseNest sea activable a demanda. motherBoard ya lo desactiva; ahora sabemos por qué importa.
	- **Advertencia metodológica:** la 17.A medía 44-47 ms en tres tiradas emitiendo y bajó a 15 ms justo tras flashearla con el cambio. Parecía la prueba y no lo era: flashear también reinicia y reasocia. Reflasheada **sin** el cambio siguió dando 21 ms, luego los 45 ms eran una **asociación degradada** (llevaba horas encendida y se había reasociado sola tras caerse del hotspot). **Una placa con muchas horas de asociación arrastra ~2,5× de latencia de comandos; reiniciarla lo cura.**
	- Segunda razón, no demostrada: estabilidad de asociación. Quita una variable de las caídas de la 17.A del 2026-09-09; juzgarlo pide una sesión larga.
	- Queda en el fuente la compuerta `#ifdef PULSENEST_NO_DATA_STREAM` (inerte por defecto, solo banco) que hizo posible medir el caso en reposo.

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
