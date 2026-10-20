# CONTEC MS100 SpO2 simulator — operating notes

Role in the project: regression and stability reference for the electronic chain (AFE4490 → R-METHOD).
It never validates accuracy (ISO 80601-2-61 EE.4: no simulator does). Session config: `docs/session_configs/subj90_MS100.toml` (not committed, like every session config).

## Controls (observed behaviour, 2026-10-19, Alex; not from the manual)

| Control | Observed effect | Interpretation |
|---|---|---|
| **TLC** (Trans Level Ctrl) | Scales the whole optical signal. %mod / PI and R unchanged. | Global gain: DC and AC scale together. Emulates tissue transmittance (thick vs thin site). |
| **Pulse Amp %** | Signal **maximum stays fixed**; only the minimum drops as the setting rises. R unchanged. | AC amplitude defined as (max − min) / max, i.e. relative to the diastolic peak, not to the mean. Consistent with transmission physics: diastole = most light, the pulse subtracts light. |
| **SpO2** | Changes the red modulation relative to the IR one according to the selected R-curve ("R-Curve Nellcor"). | The only control that moves R. |

Consequences:
- Library PI (peak-to-peak / mean DC) would read PI ≈ A / (1 − A/2) for Pulse Amp = A if the definition above
  held. **Measured 2026-10-19 (SUBJ90 sweep): PI = 4.3-4.5 % for Pulse Amp 3 %, ratio 1.47, constant over the
  sweep** — so the definition is still open. Quick test pending: Pulse Amp 1 / 3 / 10 % at one setpoint.
- Same definition for red and IR → R is independent of Pulse Amp and TLC (matches observation).
- SpO2 sweep sessions: keep TLC and Pulse Amp fixed, sweep SpO2 only. Film the screen with VideoNest: the
  simulator switches instantly, so the OCR delimits the plateaus; a keyboard REF_SPO2 is only a label.

## Sweep 2026-10-19 (SUBJ90, `captures/sessions/SUBJ90/Analysis/findings.md`)
Nellcor table with R-METHOD-2: setpoint = 121.06 − 39.11·R (rms 1.0, concave below 80 %). R independent of
heart rate (75/140/160 bpm, ±0.003), no hysteresis; chain noise sd(R) 0.002-0.008 (< 0.3 pt). The lib's
neonatal curve has the same slope and sits +2.9 pt above. At 100 % the lib's SpO2 goes invalid (R 0.48-0.53).

## Calibration lineage
`R-CURVE-U401D-MS100-20260323` (114.9208 − 30.5547·R, R-METHOD-0) was fitted against this simulator with the
UpnMed U401-D probe. The simulator's "Nellcor" R-curve assumes Nellcor-class LED wavelengths; with the Medle
ST-S0163 (665 / 905 nm) that assumption is unverified.
