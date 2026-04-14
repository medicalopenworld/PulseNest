# pre_build_hash.py — PlatformIO pre-build script
# Extracts the git short hash of the incunest_afe4490 library from the PlatformIO
# libdeps cache and injects it as -DINCUNEST_GIT_HASH="xxxxxxx" into the build.
# If the hash cannot be determined, falls back to "unknown".

Import("env")  # noqa: F821 — injected by PlatformIO SConstruct

import subprocess
import os

def _get_lib_git_hash(env):
    libdeps_dir = os.path.join(
        ".pio", "libdeps", env["PIOENV"], "incunest_afe4490"
    )
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=libdeps_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        git_hash = result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        git_hash = "unknown"

    print(f"incunest_afe4490 git hash: {git_hash}")
    env.Append(CPPFLAGS=[f'-DINCUNEST_GIT_HASH=\\"{git_hash}\\"'])

_get_lib_git_hash(env)  # noqa: F821
