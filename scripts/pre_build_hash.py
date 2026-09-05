# pre_build_hash.py — PlatformIO pre-build script
#
# Injects the git provenance of the two repositories that make up this firmware:
#
#   -DPULSENEST_GIT_HASH="xxxxxxx"   this project (src/main.cpp and everything around it)
#   -DINCUNEST_GIT_HASH="xxxxxxx"    the incunest_afe4490 library
#
# Both travel in the $CFG frame and therefore into every capture header, which is what makes
# a capture's FW_* columns attributable to an exact build. Version numbers alone are not
# enough: during development most builds are uncommitted work on top of the same version.
#
# A "-dirty" suffix marks a working tree with uncommitted changes, i.e. a build that matches
# NO commit and cannot be reproduced from the hash alone. That is the normal case while
# developing, so silence about it would be misleading.
#
# The library used to be looked up only in .pio/libdeps/<env>/incunest_afe4490. That path
# does not exist when the library is consumed through the lib/ symlink (the usual local
# setup), so the hash silently fell back to "unknown" and every capture recorded
# "build unknown". Several candidate paths are tried now.

Import("env")  # noqa: F821 — injected by PlatformIO SConstruct

import os
import subprocess

# PlatformIO exec()s this script without setting __file__, so the project root comes from the
# build environment rather than from the script's own path.
PROJECT_DIR = env["PROJECT_DIR"]  # noqa: F821


def _git(args, cwd):
    """Run a git command, returning stripped stdout or None."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=5)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _describe(cwd, label):
    """Short hash of the working tree at cwd, with -dirty when it has local changes."""
    if not cwd or not os.path.isdir(cwd):
        print(f"{label} git hash: unknown (no such directory: {cwd})")
        return "unknown"
    h = _git(["rev-parse", "--short", "HEAD"], cwd)
    if not h:
        print(f"{label} git hash: unknown (not a git repository: {cwd})")
        return "unknown"
    # --porcelain prints one line per modified/untracked path; any output means dirty.
    status = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    if status:
        h += "-dirty"
    print(f"{label} git hash: {h}")
    return h


def _find_library_dir():
    """First existing candidate for the incunest_afe4490 source tree.

    lib/ comes first because that is where a local development checkout is symlinked, and it
    is the copy actually compiled when present.
    """
    candidates = [
        os.path.join(PROJECT_DIR, "lib", "incunest_afe4490"),
        os.path.join(PROJECT_DIR, ".pio", "libdeps", env["PIOENV"], "incunest_afe4490"),  # noqa: F821
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


lib_hash = _describe(_find_library_dir(), "incunest_afe4490")
fw_hash = _describe(PROJECT_DIR, "PulseNest")

env.Append(CPPFLAGS=[  # noqa: F821
    f'-DINCUNEST_GIT_HASH=\\"{lib_hash}\\"',
    f'-DPULSENEST_GIT_HASH=\\"{fw_hash}\\"',
])
