# CONTEC MS100 SpO2 simulator — operating notes

Role in the project: regression and stability reference for the electronic chain (AFE4490 → R-METHOD).
It never validates accuracy (ISO 80601-2-61 EE.4: no simulator does). Session config: `docs/session_configs/MS100.toml`.

## Controls (observed behaviour, 2026-10-19, Alex; not from the manual)

| Control | Observed effect | Interpretation |
|---|---|---|
| **TLC** (Trans Level Ctrl) | Scales the whole optical signal. %mod / PI and R unchanged. | Global gain: DC and AC scale together. Emulates tissue transmittance (thick vs thin site). |
| **Pulse Amp %** | Signal **maximum stays fixed**; only the minimum drops as the setting rises. R unchanged. | AC amplitude defined as (max − min) / max, i.e. relative to the diastolic peak, not to the mean. Consistent with transmission physics: diastole = most light, the pulse subtracts light. |
| **SpO2** | Changes the red modulation relative to the IR one according to the selected R-curve ("R-Curve Nellcor"). | The only control that moves R. |

Consequences:
- Library PI (peak-to-peak / mean DC) reads slightly above the setting: PI ≈ A / (1 − A/2) for Pulse Amp = A
  (10 % → ~10.5 %, 20 % → ~22 %). Negligible at neonatal amplitudes (< 5 %).
- Same definition for red and IR → R is independent of Pulse Amp and TLC (matches observation).
- SpO2 sweep sessions (BACKLOG, 2026-10-16): keep TLC and Pulse Amp fixed, sweep SpO2 only, log the panel value.

## Calibration lineage
`R-CURVE-U401D-MS100-20260323` (114.9208 − 30.5547·R, R-METHOD-0) was fitted against this simulator with the
UpnMed U401-D probe. The simulator's "Nellcor" R-curve assumes Nellcor-class LED wavelengths; with the Medle
ST-S0163 (665 / 905 nm) that assumption is unverified.
