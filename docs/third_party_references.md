# Third-party reference documents

Some documents this project relies on are **deliberately not stored in this repository**.
`PulseNest` is a **public** repo, and these are copyrighted works owned by standards bodies or
companies — committing them would redistribute them publicly. They are listed here so the
reference is not lost, with where to obtain each one.

Keep local copies at the paths below (they are in `.gitignore`); the code and specs refer to
them by these paths.

| Local path (git-ignored) | Document | Where to obtain |
|---|---|---|
| `docs/ISO_80601-2-61-2026.pdf` | ISO 80601-2-61:2026 — *Medical electrical equipment: particular requirements for basic safety and essential performance of pulse oximeter equipment* | Purchase from [ISO](https://www.iso.org/standard/86747.html) or a national member body (AENOR in Spain). Not freely redistributable. |
| `docs/masimo_whitepapers/` | Masimo whitepapers, technical bulletins and algorithm comparison charts (perfusion index, SatSeconds, very low perfusion, APOD, Halo index, …) | Masimo's technical library / clinical evidence pages. Commercial documents — request from Masimo. |
| `docs/slaa655.pdf` | TI SLAA655 — application note | Free download from [TI](https://www.ti.com/lit/an/slaa655/slaa655.pdf). Kept out of the repo simply because linking is enough. |
| `docs/19061_WHO-UNICEF Technical specifications and guidance for oxygen therapy devices.pdf` | WHO / UNICEF — *Technical specifications and guidance for oxygen therapy devices*, WHO Medical Device Technical Series, 2019, ISBN 978-92-4-151691-4. **Chapter 6 (pulse oximetry) is the procurement specification IncuNest must meet**: §6.5 tabletop / §6.4 multiparameter — PR range 30–240 bpm, ±3 bpm, SpO2 ±2 %/±3 %, valid-data update ≤10 s. | Free download from [WHO IRIS](https://iris.who.int/server/api/core/bitstreams/5a996b5a-6803-486e-bccb-98efc398118d/content). CC BY-NC-SA 3.0 IGO — kept out of the repo because linking is enough. |

## Documents that ARE kept in the repo

TI permits reproduction of its datasheets and user guides, so the primary hardware references are
versioned for convenience and offline access:

| Path | Document |
|---|---|
| `docs/afe4490.pdf` | AFE4490 datasheet (SBAS602H) — the primary hardware reference |
| `docs/slau480c_AFE44x0SPO2EVM.pdf` | AFE44x0SPO2EVM user's guide |
| `docs/Medle_probe/` | Medle probe datasheet images (supplier documentation for the probe in use) |

## Rule of thumb

Before adding a PDF or any third-party document to `docs/`: this repository is public. If the
document is sold, licensed, or marked confidential, add it to `.gitignore` and record it in the
table above instead of committing it.
