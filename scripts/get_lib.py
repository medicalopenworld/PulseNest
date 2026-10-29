#!/usr/bin/env python3
"""Make sure lib/incunest_afe4490 is there before a build: the incunest_afe4490 library at the tag
written in lib/incunest_afe4490.version (option C of docs/library_dependency.md).

    python scripts/get_lib.py

- A junction or symlink is the developer's working copy (on the development machine
  lib/incunest_afe4490 -> C:\\PRJ\\MOW\\incunest_afe4490): it is never touched. The script only
  reports where that copy stands against the pinned tag, so a pin left behind is visible.
- Missing (a fresh clone of PulseNest): shallow clone of the pinned tag from GitHub.
- A clone made by this script at another tag (the pin was moved): fetch the new tag and check it out.
- Anything else (a plain directory that is not such a clone, or one with local changes): stop and
  say why. It never overwrites.

Called by scripts/build.ps1 and test_lib/runner/run_host_tests.py; run it by hand before building
tools/offline_runner. Exit code 0 when lib/incunest_afe4490 is ready.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "incunest_afe4490")
PIN_FILE = os.path.join(ROOT, "lib", "incunest_afe4490.version")
URL = "https://github.com/medicalopenworld/incunest_afe4490.git"


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def is_link(path):
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda _p: False)(path)


def main():
    with open(PIN_FILE, encoding="utf-8") as f:
        pin = f.read().strip()

    if is_link(LIB):
        if not os.path.isfile(os.path.join(LIB, "incunest_afe4490.h")):
            print(f"error: {LIB} is a link to {os.path.realpath(LIB)}, which has no incunest_afe4490.h",
                  file=sys.stderr)
            return 1
        here = git("-C", LIB, "describe", "--tags", "--always", "--dirty", check=False) or "unknown"
        print(f"incunest_afe4490: working copy {os.path.realpath(LIB)} at {here} (pinned: {pin})")
        return 0

    if not os.path.exists(LIB):
        print(f"incunest_afe4490: cloning {pin} from {URL}")
        git("-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", pin, URL, LIB)
        return 0

    if not os.path.isdir(os.path.join(LIB, ".git")):
        print(f"error: {LIB} exists but is neither a link nor a git clone; move it away and run again",
              file=sys.stderr)
        return 1
    here = git("-C", LIB, "describe", "--tags", "--exact-match", check=False)
    if here == pin:
        print(f"incunest_afe4490: {pin}")
        return 0
    if git("-C", LIB, "status", "--porcelain"):
        print(f"error: {LIB} has local changes and is not at {pin}; it is not overwritten", file=sys.stderr)
        return 1
    print(f"incunest_afe4490: {here or 'unknown'} -> {pin}")
    git("-C", LIB, "fetch", "--quiet", "--depth", "1", "origin", "tag", pin)
    git("-C", LIB, "-c", "advice.detachedHead=false", "checkout", "--quiet", pin)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
