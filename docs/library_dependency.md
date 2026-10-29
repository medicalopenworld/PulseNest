# How PulseNest gets the incunest_afe4490 library

Decided 2026-10-29 (Alex), conversation_log.md session of that date. Recorded so that a later move to
another option starts from what was already weighed.

## The requirement

PulseNest is public. A clone must build, and every PulseNest commit must say which version of the
library it was built with (MOW rule: dependencies pinned to a tag). Until 2026-10-29
`lib/incunest_afe4490` was a junction to `C:\PRJ\MOW\incunest_afe4490`, ignored by git: it worked on
the development machine, but a clone got an empty folder and no version.

How the library is developed (the constraint every option has to respect): **always from PulseNest
sessions**, never from a session opened in the library's folder. Sessions read and edit it as
`lib/incunest_afe4490`; it is committed, tagged and pushed in its own repo.

## Option C: junction + pinned tag in a file (CURRENT)

- `lib/incunest_afe4490` stays a junction to `C:\PRJ\MOW\incunest_afe4490` on the development
  machine, gitignored, exactly as before.
- `lib/incunest_afe4490.version` (versioned) holds the tag, e.g. `v0.111`.
- `scripts/get_lib.py`, run by `scripts/build.ps1` and `test_lib/runner/run_host_tests.py` (which then
  runs the library's own tests, `lib/incunest_afe4490/test/`, since 2026-10-30): a link is
  left alone (it only prints where the working copy stands against the pin); a missing folder gets a
  shallow clone of the tag; a clone it made earlier follows the pin when the pin moves.
- Moving the pin: edit the tag in `lib/incunest_afe4490.version` and commit it, in the same PulseNest
  commit as the code that needs that library version.

Pros: nothing changes in the daily work, paths, sessions' rules or memories; pinned to a tag.
Cons: not a standard git mechanism (a small script of ours); the first build of a clone needs the
network; the pin is moved by hand (as in IncuNest's `platformio.ini`), and a PulseNest commit that
needs a newer library than the pin builds here but not in a clone.

## Option A: submodule pinned to a tag + override by environment variable

- `lib/incunest_afe4490` is a git submodule at a tag (a clone of its own, not edited).
- The working copy stays in `C:\PRJ\MOW\incunest_afe4490`; the environment variable
  `INCUNEST_AFE4490_DIR` makes every build compile it instead of the submodule
  (`cmake/incunest_afe4490_dir.cmake`, plus a reconfigure when the variable changes).

Rejected because sessions work through `lib/incunest_afe4490`: they would read and edit the pinned
clone (in detached HEAD) while the build compiles the other copy, and the working copy would sit
outside the project folder. Implemented and tested on 2026-10-29, never pushed: local branch
`option-a-submodule-override` (commits `554df4e`, `e43a4a7`) in this repo.

## Option B: develop inside the submodule

- `lib/incunest_afe4490` is a submodule and also the only working copy of the library: it is edited,
  committed and pushed there. `C:\PRJ\MOW\incunest_afe4490` goes away.
- The pin moves almost by itself: after a library commit, `git add lib/incunest_afe4490` in the next
  PulseNest commit.

Not chosen for now. Costs: detached HEAD (a clone or `git submodule update` leaves the submodule
outside any branch; `git switch master` before working, a CLAUDE.md rule and a warning in
`build.ps1`); `git config push.recurseSubmodules on-demand` so PulseNest never points at an unpushed
library commit; the pin follows commits rather than tags between releases; the library's MOW git
identity set again in the new clone; every reference to `C:\PRJ\MOW\incunest_afe4490` (README,
CLAUDE.md, the sessions' memories, the IncuNest sessions' rule) moved.

Not workable: keeping a junction at the submodule path (git would take the library's own repo as the
submodule, `git submodule update` would detach it, and some submodule commands move its `.git` into
`PulseNest/.git/modules`), or a junction the other way round (a submodule's `.git` file is a relative
path, wrong when reached through the junction).

## IncuNest, for comparison

IncuNest consumes the library through PlatformIO, `lib_deps = …incunest_afe4490.git#<tag or commit>`
in `Firmware/motherBoard/platformio.ini` (`#4e0dd91` on master, `#v0.94` on dev). Same idea as
option C: the version in one line of text, moved by hand as a deliberate step.
