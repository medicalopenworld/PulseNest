#!/usr/bin/env python3
"""Build and run the incunest_afe4490 host unit tests from PulseNest.

    python test_lib/runner/run_host_tests.py            # configure + build + run every suite
    python test_lib/runner/run_host_tests.py hr1 spo2   # only suites whose name contains a filter
    python test_lib/runner/run_host_tests.py --clean    # wipe test_lib/runner/build first

Since 2026-10-30 the suites, Unity and the CMake project live in the library's repo
(lib/incunest_afe4490/test/, spec §9.10), where GitHub Actions runs them on every push and tag.
This wrapper keeps the PulseNest command: it makes sure lib/incunest_afe4490 is there
(scripts/get_lib.py: the developer's junction, or the pinned tag cloned from GitHub) and runs the
library's test/run_host_tests.py with the build directory here, out of the library's tree.

Needs cmake, ninja and a host g++ on PATH (MinGW-w64 on Windows). Exit code = number of failing
suites.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BUILD = os.path.join(HERE, "build")
LIB_TESTS = os.path.join(ROOT, "lib", "incunest_afe4490", "test")


def run(cmd):
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main(argv):
    if run([sys.executable, os.path.join(ROOT, "scripts", "get_lib.py")]):
        return 1
    runner = os.path.join(LIB_TESTS, "run_host_tests.py")
    if not os.path.isfile(runner):
        print(f"error: {runner} not found: the pinned library predates the tests in its repo "
              f"(they moved there after v0.111); move the pin in lib/incunest_afe4490.version", file=sys.stderr)
        return 1
    # A build directory configured from another CMake project (the pre-2026-10-30 one in this
    # folder) cannot be rebuilt: start it again.
    cache = os.path.join(BUILD, "CMakeCache.txt")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8", errors="replace") as f:
            home = next((l.split("=", 1)[1].strip() for l in f if l.startswith("CMAKE_HOME_DIRECTORY:")), "")
        if os.path.normcase(os.path.realpath(home)) != os.path.normcase(os.path.realpath(LIB_TESTS)):
            shutil.rmtree(BUILD)
    return run([sys.executable, runner, "--build", BUILD, *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
