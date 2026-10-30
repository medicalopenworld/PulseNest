# Publishing a sub-product of a large repository without the consumer downloading the whole repository

Global study of the alternatives, 2026-10-30. Written by an analysis session; decided by Alex the
same day (§0 *Decision*). Companion of `library_dependency.md`, which covers the producer's inner
loop (how PulseNest builds the library it develops); this document covers where the library's
source lives and through which channel a consumer receives it.

## 0. Decision (Alex, 2026-10-30)

Applied:

- **Topology:** `incunest_afe4490` stays in its own repository (T3, §3). No monorepo, no mirror.
- **Base channel unchanged:** git URL + tag (D1, §4), plus the rule **a tag never moves**
  (library spec §9.10; GitHub's immutable-releases setting where available).
- **Zip + SHA-256 as assets of every GitHub Release** (D4, §4): the `release-assets` job of the
  library's CI, from v0.114.
- **PulseNest is not split.** Policy: heavy raw data goes outside git from now on (release asset of
  the corresponding report, a data repository, or Zenodo when it must be cited); `docs/rf_taps/raw/`
  is in `.gitignore` because `experiments/rf_tap_bench.py` writes there by default. The CSVs already
  tracked stay tracked (removing them would not shrink a clone and would cost the report its
  reproducibility inside the repository; rewriting history was rejected).

Deferred, with the condition that reopens them:

- **Espressif component registry** (D5a): when the migration of IncuNest to ESP-IDF is decided, or
  when `get_lib.py` is to be replaced by `override_path` (verify first what it does without the
  local path).
- **PlatformIO registry** (D5b): only if IncuNest's maintainer asks for it.
- **Firmware `.bin` per board as PulseNest release assets:** when there is a firmware worth
  freezing; `docs/boards.md` already records what each board runs.

Rejected: Arduino Library Manager (D5c), removing `docs/rf_taps/raw` from the tree, rewriting
history.

## 1. Conclusions (executive summary)

1. **The question mixes two independent decisions.** (a) *Where the product's source lives*
   (monorepo, own repository, hybrid) and (b) *through which channel the consumer receives it* (git,
   release archive, package registry, copy). The consumer downloads "the whole repository" only when
   the channel is git and the source is in a monorepo. **A package registry decouples (a) from
   (b):** with the product published in a registry, the consumer never sees the repository, wherever
   the source lives. The one exception is the Arduino Library Manager, which requires the library to
   be the root of its own repository.
2. **For a library of medical use, the own repository (polyrepo) beats the monorepo** for three
   reasons that have nothing to do with download size: a hard confidentiality boundary (a test-bench
   repository contains or will contain data of people and third-party documents; the public library
   must not inherit them, not even by accident), its own version and release line (what a regulated
   consumer needs to identify, IEC 62304 §8), and the possibility of someone else maintaining it
   without dragging the test bench along. The cost is the loss of the atomic library+firmware
   commit; already mitigated (pin file + `check_version.py` + CI).
3. **The monorepo with a read-only mirror (the Symfony pattern)** is the only alternative that
   recovers the atomic commit without losing the repository root for consumers. It is viable, but
   adds a robot (deterministic split + tag replication) and turns the library into a derivative:
   issues and PRs go to the monorepo, and an external maintainer inherits the test bench. Not worth
   it with two repositories and two people.
4. **What is missing are channels, not topology:** the library already has `library.json`
   (PlatformIO registry) and the `CMakeLists.txt` of an IDF component; it lacks `idf_component.yml`
   (Espressif component registry) and a CI step publishing to the registries on a tag. With that,
   IncuNest (PlatformIO) and any ESP-IDF project install 2 MB without git, with an immutable version.
   A zip + SHA-256 per release as a GitHub asset covers the auditor and the build without network.
5. **Implication for PulseNest's structure:** no further splitting is needed. The only structural
   change the figures justify is a **data policy**: 68 of the 87 MB of the tree are raw CSVs of one
   experiment (`docs/rf_taps/raw`, since 2026-10-08) and are in the history for good; future heavy
   data must go outside git (release asset, data repository, or Zenodo if it must be cited).
   Optionally, publish the firmware `.bin` per board as release assets, which is "the product" the
   boards consume.

## 2. Setting out the problem

### 2.1 Three questions, not one

| Question | What it is about | Who bears it |
|---|---|---|
| **T** Topology | In which repository(ies) the source of the product and of everything else lives | Producer (history, CI, atomicity, confidentiality) |
| **D** Distribution | How the consumer obtains one specific version of the product | Consumer (size, tooling, immutability) |
| **I** Inner loop | How the producer builds its own product while developing it | Producer (iteration speed) |

The three are usually confused. For example, "submodule" answers D (or I), not T; "monorepo" answers
T and says nothing by itself about D.

### 2.2 Consumers to keep in mind (in general, not only IncuNest)

| Consumer | Tool | What it needs |
|---|---|---|
| C1 Native ESP-IDF firmware | IDF component manager (`idf_component.yml`) or `EXTRA_COMPONENT_DIRS` | A directory with a component `CMakeLists.txt` |
| C2 Arduino-ESP32 firmware via PlatformIO | `lib_deps` (git URL, archive or registry) | `library.json` |
| C3 Arduino IDE | Library Manager | `library.properties`, library at the root of its repository |
| C4 Host builds (tests, offline runner, bindings) | CMake, `FetchContent`, copy | Sources + host HAL |
| C5 Auditor / reviewer / regulator | None; wants an identifiable, frozen artefact | Zip with version, checksum, release notes |
| C6 The producer itself (PulseNest) | Local build | Editable working copy, iteration without push |

C3 and C5 constrain the most: C3 fixes the topology (repository root) and C5 fixes immutability.

## 3. Reference figures (measured on 2026-10-30)

| | PulseNest (producer) | incunest_afe4490 (product) |
|---|---|---|
| Versioned files | 143 | 35 |
| Versioned tree | 87 MB | 1.3 MB |
| … of which raw CSVs `docs/rf_taps/raw` | 68 MB (78 %) | — |
| Download of a full clone (pack) | 33 MB | 2 MB |
| Commits | 597 | 192 |

A consumer of the library who had to clone PulseNest would download 16 times more and, since the
CSVs are in the current tree, a shallow clone (`--depth 1`) does not help. 78 % of the weight is one
single-day experiment: PulseNest's size problem is a problem of **data in git**, not of having the
library inside or outside. (Note of the development session: the local pack of PulseNest measured
8.4 MiB with `git count-objects`, since CSV compresses well; the clone figure above deserves a
re-measurement before any decision rests on it.)

## 4. Topologies (where the source lives)

### T1. Monorepo: the product is a subdirectory

Everything in one repository; the product in `lib/x/` with its `CMakeLists.txt` and `library.json`.

- Pros: one history, one PR for a change touching library + firmware + tests + spec; trivial
  integration CI; zero version synchronisation between repositories.
- Cons: any git-based channel (URL in `lib_deps`, submodule, `git:` of the IDF manager) downloads
  the whole repository; Arduino Library Manager impossible; tagging needs per-product prefixes
  (`lib-v0.114`) and `git describe` by path; the product's CI needs path filters; **no
  confidentiality boundary**: whatever enters the repository (captures, third-party PDFs) is public
  by the same act; an external maintainer of the product inherits everything else.
- Embedded precedent: `espressif/esp-protocols` (several components in one repository, tags
  `mdns-v1.x`, published to the component registry from subfolders). It works *because* the channel
  is the registry, not git.

### T2. Monorepo + read-only mirror (automatic split)

The source lives in the monorepo (T1); a robot (`git subtree split` or `splitsh-lite`, in GitHub
Actions) regenerates on every push a derived repository holding only the subdirectory's history,
and replicates the tags. Consumers point at the mirror.

- Pros: everything of T1 for the producer and, for the consumer, a clean repository at the root
  (good for Arduino Library Manager, submodules, git URL, `git:` + `path:`). The split is
  deterministic (same input commits → same output SHAs), so the mirror is not rewritten.
- Cons: the mirror is a **derivative**: external issues and PRs must be redirected; tags are
  replicated in a second step; if the subdirectory moves or is renamed, the split's history breaks;
  the product's CI runs in the monorepo (path filters) or is duplicated in the mirror; the
  confidentiality boundary exists only for what lies under the subdirectory (a wrong file under
  `lib/x/` goes out to the mirror); a write token to the mirror lives in the CI. With two people and
  two repositories, disproportionate automation.
- Precedent: Symfony (`symfony/symfony` → `symfony/console`…), Laravel (`illuminate/*`). Projects
  with dozens of components and hundreds of contributors: the robot pays for itself.

### T3. Polyrepo: the product in its own repository (the situation of incunest_afe4490)

The product is a repository with its CI, its tags, its releases and its spec; the producer consumes
it as one more dependency (see §6 for the inner loop).

- Pros: **hard boundary** (what is not in the library's repository cannot be published with it);
  own identity (README, issues, citations, stars, package registry without tricks); own version
  line, independent of the test bench's; another maintainer can work without knowing PulseNest; it
  is exactly what every package manager expects.
- Cons: **no atomic commit** between library and consumer (two commits, two pushes, moving the pin);
  spec ↔ code ↔ version coherence is discipline + scripts (`check_version.py`); integration tests
  live in the consumer and must say which tag they pass with; the first build of a clone of the
  producer needs network.
- Precedent: almost every Arduino/ESP library; Nordic/Zephyr (each module in its repository).

### T4. Polyrepo + manifest (Zephyr `west`, Android `repo`)

A "manifest" repository lists N repositories and the SHA of each; the tool clones only the ones the
user asks for. It is T3 scaled to dozens of repositories, with the pin centralised.

- Pros: pin of everything in one file; selective clone; update in one command.
- Cons: an own tool (west) the consumer has to install; for two repositories,
  `lib/incunest_afe4490.version` already is that one-line manifest. Adds nothing at this scale.

### T5. Orphan branch or bidirectional `git subtree` in the same repository

Mentioned to be discarded: an orphan `lib` branch in the same repository (clonable with
`--single-branch --depth 1`) breaks every tool and every intuition; `git subtree push/pull` between
the monorepo and a product repository is slow, litters the history with merges and fails as soon as
two people use it at once.

## 5. Distribution channels (how the consumer receives it)

| Channel | Download | Needs git | Immutable | C1 IDF | C2 PIO | C3 Arduino IDE | C4 host | C5 auditor |
|---|---|---|---|---|---|---|---|---|
| D1 Git clone of a tag | whole repository | yes | no (a tag can be moved) | `git:` | URL `#tag` | no | FetchContent GIT_TAG | fair |
| D2 Partial/sparse clone (`--filter=blob:none --sparse`) | the subdirectory only | yes | no | manual | no | no | manual | no |
| D3 Submodule in the consumer | whole repository (of the product) | yes | **yes** (pin to SHA) | `components/` | `lib/` | no | yes | good |
| D4 Release asset (zip + SHA-256) | the product only | **no** | yes if the release is immutable | not directly (script) | URL of the zip | "Add .ZIP Library" | FetchContent URL_HASH | **ideal** |
| D5a IDF component registry | the product only | no | **yes** (a version is never overwritten) | `idf_component.yml` | no | no | no | good (SBOM) |
| D5b PlatformIO registry | the product only | no | **yes** | no | `owner/name@^x.y.z` | no | partial | good |
| D5c Arduino Library Manager | the product only | no | yes (index by tag) | no | yes (PIO reads it) | **yes** | no | fair |
| D6 Vendored copy in the consumer | nothing (already there) | no | yes (it is a commit) | yes | yes | yes | yes | good, if the origin version is recorded |

Observations:

- **D1 is the channel that motivates the question.** It is the only one in which topology T1
  punishes the consumer. In T3 the download is 2 MB and the problem does not exist.
- **D2 exists but is no use to tools:** no manager (IDF, PIO, Arduino) knows how to do a sparse
  clone. It is for humans who want to read a folder.
- **D3 pins to a SHA, not to a tag:** stronger than D1 for traceability, but forces the consumer to
  know git (detached HEAD, `--recurse-submodules`). What IncuNest does today (`lib_deps = …git#v0.112`)
  is D1 with a tag; PlatformIO allows `#<sha>`, which is then equivalent to D3.
- **D4 is the auditor's channel and the channel of the build without network.** It costs one CI
  step (`zip` + `sha256sum` + `gh release upload`). GitHub offers immutable releases since 2025
  (repository setting; check that it is available to the organisation): with it, tag and assets are
  frozen.
- **D5 is the channel that removes git and the producer's size at once.** All three registries
  publish from a folder: `compote component upload` (Espressif) and `pio pkg publish <dir>`
  (PlatformIO) accept a subdirectory of any repository; only the Arduino Library Manager demands a
  repository root. Published versions are immutable by registry policy. For IDF, the consumer writes
  `idf.py add-dependency "medicalopenworld/incunest_afe4490^0.113.0"` and the manager downloads only
  the component into `managed_components/`.
- **D6 (copy) is the temptation of the consumer in a hurry** and the classic source of drift: the
  copy gets patched in place and stops matching any published version. Acceptable only with a file
  stating which version it comes from and a ban on editing it.

A versioning detail that affects D5: the library's tags are `vX.Y` and the registries demand
`X.Y.Z`; `library.json` already says `0.113.0`, so the correspondence `v0.113 → 0.113.0` is a detail
of the CI step (and `check_version.py` already checks that they agree).

## 6. The producer's inner loop (how it builds its own product)

Analysed for PulseNest in `library_dependency.md` (options A, B and C; C in force: junction +
`lib/incunest_afe4490.version` + `scripts/get_lib.py`). Added here is what was missing for the
picture to be global:

| Mechanism | Standard | Pin | Iteration without push | Notes |
|---|---|---|---|---|
| Junction + pin file + script (C) | no (own script) | tag | yes | In force. Works; home-made |
| Pinned submodule + environment variable (A) | yes | SHA | yes | Rejected: two copies, sessions edit the wrong one |
| Developing inside the submodule (B) | yes | SHA | yes | Rejected: detached HEAD, two-step push |
| `symlink://path` in `lib_deps` (PlatformIO) | yes | none | yes | PlatformIO only; IncuNest already uses it for `shared/` |
| `override_path` in `idf_component.yml` (IDF manager) | yes | registry version + local path | yes | Made for this: on one machine the local path builds, on another the registry version. Verify what it does when the path does not exist before adopting it |
| Subdirectory of the monorepo (T1/T2) | yes | the commit | yes | The simplest possible inner loop; the great advantage of the monorepo |

If the library enters Espressif's registry (D5a), `override_path` is the natural candidate to
replace `get_lib.py` with a standard mechanism: the option D that `library_dependency.md` lacked.

## 7. Evaluation matrix

Criteria (what matters to an open medical-device project with two people):

1. Size and friction for the consumer (including "without git").
2. Compatibility with the tools of C1–C4.
3. Immutability and traceability of the version (C5).
4. Confidentiality boundary (health data, third-party documents).
5. Atomic commit product + consumer + spec.
6. External maintainers of the product.
7. Automation to be maintained.

| | T1 monorepo + git | T1 monorepo + registry | T2 mirror | T3 own repository (today) | T3 + registries + zip |
|---|---|---|---|---|---|
| 1 Consumer | ✗ 33 MB and growing | ✓ 2 MB without git | ✓ 2 MB | ✓ 2 MB with git | ✓ 2 MB without git |
| 2 Tools | IDF yes, PIO yes, Arduino IDE no | IDF and PIO yes, Arduino IDE no | all | all (Arduino IDE if registered) | all |
| 3 Immutability | tag (movable) | ✓ registry | replicated tag | tag (movable); SHA if pinned | ✓ registry + release |
| 4 Confidentiality | ✗ none | ✗ none | ~ only under `lib/` | ✓ hard | ✓ hard |
| 5 Atomicity | ✓ | ✓ | ✓ | ✗ (pin by hand) | ✗ (pin by hand) |
| 6 External maintainer | ✗ inherits everything | ✗ | ~ contributes to the monorepo | ✓ | ✓ |
| 7 Automation | CI filters, prefixed tags | + publishing | + split robot + tag replication + token | `get_lib.py`, `check_version.py` (exist) | + one CI step per registry |

Reading: the monorepo wins only on atomicity; it loses on confidentiality, which for this project is
not negotiable (`.gitignore` rule: no capture of a human subject ever enters). The own repository
loses atomicity, and that cost is already paid with the pin and the version check. What adds real
value is the last column: channels without git and immutable, without touching the topology.

## 8. What the medical-device context demands

- IEC 62304 §8 (configuration management) asks to identify every software item with a unique
  version and to be able to rebuild the configuration that was validated. For IncuNest the library
  is an own item (developed under its process); for a third party it would be SOUP (software of
  unknown provenance) and would need title, manufacturer, version and list of known anomalies. The
  release per tag with *What changes / Breaking / When upgrading* (spec §9.10) and the §14 changelog
  already cover this; a registry and an immutable release turn "the validated 0.113.0 is the one
  that gets compiled" from a convention into a mechanical guarantee.
- A git tag is movable (`git tag -f`). If the pin is by tag, a written rule "a tag never moves" is
  needed and, better, the CI comparing the tag's SHA with the release's. A pin by SHA (submodule,
  `#<sha>` in PlatformIO) or by registry does not have this problem.
- Build reproducibility: the regulated consumer prefers an artefact with a checksum (D4/D5) to a
  repository, and prefers not to depend on GitHub being available on the day of the audit (local
  copy of the zip with its SHA-256 in the file).

## 9. Real precedents, summarised

| Project | Topology | Channel | Lesson |
|---|---|---|---|
| Symfony, Laravel | T2 | Packagist (registry) + mirrors | The mirror only pays off with many components and contributors |
| espressif/esp-protocols | T1 | IDF component registry | A monorepo is harmless to the consumer if the channel is the registry |
| Zephyr / nRF Connect | T4 | `west` + manifest | Centralised manifest; own tool; scale of dozens of repositories |
| Arduino libraries (Adafruit, etc.) | T3 | Library Manager + PlatformIO registry | One repository per library because Arduino's index demands it |
| IncuNest motherBoard today | consumer | `lib_deps` git `#v0.112` | D1 over T3: 2 MB, pin by hand, movable tag |

## 10. Recommendation (revised the same day for IncuNest's situation)

IncuNest builds today with Arduino-ESP32 via PlatformIO and may migrate to ESP-IDF (it has been
tried and is costly). The migration does not touch the library (its HAL is already dual
Arduino/IDF/host; channels 0 and 1 below hold in both worlds); what costs is the rest of the
firmware (Arduino-only libraries: TFT_eSPI, the ThingsBoard client).

**Topology:** keep incunest_afe4490 in its repository (T3). No return to a monorepo, no mirror: the
confidentiality boundary and the own release line are worth more than the atomic commit, and the
pin is already solved.

**Channels, in order of value/cost:**

0. **Do not touch the base channel:** git URL + tag (`lib_deps = …git#vX.Y` in PlatformIO; `git:` +
   `version:` in the IDF component manager). Valid in both worlds, 2 MB, ties nobody down. Add only
   the rule "a tag never moves" (or pin by SHA).
1. **Zip + SHA-256 as an asset of every GitHub Release.** Framework-agnostic, one CI step; covers
   the auditor and the build without network, before and after any migration.
2. **`idf_component.yml` + Espressif component registry.** The registry with a future: native IDF,
   PlatformIO with the `espidf` framework, and the intermediate migration path (an IDF project with
   the Arduino core as a component, which lives in that same registry and keeps IncuNest's Arduino
   libraries). PulseNest is already an IDF consumer. The library already has the component
   `CMakeLists.txt`; the yml is about ten lines. Opens option D (`override_path`) to replace
   `get_lib.py`, after verifying what it does without the local path.
3. **PlatformIO registry:** drops to third place. It covers IncuNest as it is but adds little over
   the base channel (immutability, `^` ranges), and PlatformIO's support of the new Arduino-ESP32
   cores has depended since 2024 on the community fork pioarduino. Listed only because it costs one
   CI step.
4. **Arduino Library Manager:** only for reach to Arduino IDE users.

**PulseNest's structure:** no topology change. Two policy decisions that do follow from the figures:

- **Heavy data outside git from now on.** The 68 MB of `docs/rf_taps/raw` are already in the history
  (rewriting it does not pay unless the size comes to hurt); the next raw bench data go to a release
  asset of the corresponding report, to a separate data repository, or to Zenodo if they must be
  cited with a DOI. The repository keeps the report, the figures and the analysis code, as it
  already does with the captures.
- **The firmware `.bin` per board as PulseNest release assets** (optional): the only "product" of
  PulseNest consumed by someone who is not a developer (the boards, via OTA), and today it exists
  only in the build directory of one machine.

Not needed: packaging `pulsenest_lab.py` (nobody installs it outside the clone), splitting `tools/`
or `pulsenest/`, or moving the specs (each already lives with its product).
