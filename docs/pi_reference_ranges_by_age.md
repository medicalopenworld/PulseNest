# Perfusion Index (PI) reference ranges by age, and the levels the library uses

Date: 2026-11-05. Author: Alex Cuesta with Claude. Status: reference table, not a specification.

**Units.** All values are **peak-to-peak PI** in %: `(AC_pp / DC) × 100`, the units of Masimo, Nellcor
and every paper below, and the units `incunest_afe4490` publishes since v0.101 (`2√2 · RMS` of the
band-passed OT over the window mean, PI-METHOD-1, spec §5.1). An RMS-based PI would be 2.83 times
smaller; none of the numbers here is RMS.

## Levels

The same five levels apply at every age; only the thresholds change.

| Level | Meaning | Library parameter |
|---|---|---|
| Signal inadequate | PI below which SpO2 should not be published (ISO 80601-2-61:2026 201.12.4.102 NOTE 6) | `spo2_sqi_pi_lo` (SQI = 0 below it) |
| Low PI | below the 5th percentile of the healthy population of that age: clinical warning (vasoconstriction, hypovolaemia, cold, cold sepsis) | — (display / future alarm) |
| Normal | p5 – p95 | `spo2_sqi_pi_hi` marks "full quality" (SQI = 1 above it) |
| High PI | above p95 (vasodilation, warm sepsis, ductus, fever) | — |
| Impossible | above 20 %: artefact or DC transient, the top of every manufacturer's display range | `spo2_pi_max` (SpO2 withheld) |

## Table

| Population | Inadequate | Low PI | Normal (p5–p95, ≈ median) | High PI | Evidence |
|---|---|---|---|---|---|
| Adult, finger | < 0.3 | < 1.4 | 1.4 – 10 (≈ 4) | > 10 | Lima et al. 2002 (adult ICU: PI < 1.4 % = poor peripheral perfusion); display ranges 0.02/0.3 – 20 in Masimo, Mindray, Nellcor manuals |
| Child 1–12 y, finger or foot | < 0.3 | < 1.0 | 1.0 – 7 (≈ 2.5) | > 7 | Few published series (paediatric anaesthesia); **approximate** |
| Term newborn, foot, day 1–2 | < 0.25 | < 0.70 | 0.70 – 4.5 (≈ 1.7) | > 4.5 | Granelli & Östman-Smith 2007, 10 000 newborns: p1 0.50, p5 0.70, p95 4.50; Hakan et al. 2013: preductal 1.35 (1.02–1.91), postductal 0.88 |
| Late preterm 34–36 wk | < 0.25 | < 0.6 | 0.6 – 3.5 (≈ 1.2) | > 3.5 | Hakan 2013 (preterm: preductal 0.88, postductal 0.61); small series; **estimated** |
| Preterm 28–33 wk | < 0.25 | < 0.5 | 0.5 – 3 (≈ 1.0) | > 3 | Same sources, small n; **estimated**. HOSPNAV: SUBJ11 (30 wk) 2.6, SUBJ08 (27 wk) 0.7 |
| Extremely preterm < 28 wk | < 0.25 | < 0.5 | 0.5 – 3 (≈ 1.0) | > 3 | No published percentiles by gestational age; **estimated**. HOSPNAV: SUBJ09 (26 wk) 3.7 |
| Any age | | | | > 20: impossible | `spo2_pi_max` |

Masimo flags "low perfusion" below 0.25 %; Philips recommends PI "ideally > 1.0" for a reliable
reading. De Felice et al. 2002: high neonatal illness severity at PI ≤ 1.24 (0.86 vs 2.02 in healthy
newborns), so a clinically low PI in neonates starts above the population p5.

## Caveats

1. Only the term-newborn and adult rows rest on large series (Granelli, Hakan, Lima). The preterm
   rows are estimates built on two facts, PI falls with gestational age and at postductal sites, and
   there is no study with percentiles per week. Our four HOSPNAV babies (0.7 – 3.7 %) cannot
   separate ages.
2. PI is not comparable across brands (7.07 / 5.80 / 6.80 % on one subject with three devices,
   rationale §11); the thresholds above are Masimo-convention numbers applied to our PI-METHOD-1,
   whose agreement with Masimo has not been measured.
3. **Consequence for the library's SQI ramp** (`spo2_sqi_pi_lo` = 0.5, `spo2_sqi_pi_hi` = 2.0):
   0.5 coincides with Granelli's p1, reasonable as "do not publish"; 2.0 is above the neonatal
   median, so a normal newborn at PI 1.2 gets SQI ≈ 0.47. The provenance of the 0.5/2.0 pair is still
   open (memory: SQI joint analysis). This table is the input for that decision.

## References

- Granelli A, Östman-Smith I. Noninvasive peripheral perfusion index as a possible tool for screening
  for critical left heart obstruction. Acta Paediatr 2007;96:1455–9.
- Hakan N, et al. Reference values of perfusion indices in hemodynamically stable newborns during the
  early neonatal period. Eur J Pediatr 2013;172:1041–7.
- De Felice C, et al. The pulse oximeter perfusion index as a predictor for high illness severity in
  neonates. Eur J Pediatr 2002;161:561–2.
- Lima AP, Beelen P, Bakker J. Use of a peripheral perfusion index derived from the pulse oximetry
  signal as a noninvasive indicator of perfusion. Crit Care Med 2002;30:1210–3.
- Masimo, Mindray, Nellcor user manuals (display ranges); `docs/ppg_neonatal_manufacturer_references.md`.
