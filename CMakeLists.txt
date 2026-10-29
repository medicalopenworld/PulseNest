# PulseNest — ESP-IDF v6.0.1 project (esp32s3). Ported from Arduino/PlatformIO on 2026-09-15; the
# PlatformIO build was removed once this one reached parity on the bench (conversation_log.md,
# sessions 2026-09-15). Build with scripts/build.ps1 <Board>, or by hand as below.
#
# Board selection: Kconfig (main/Kconfig.projbuild, menu "PulseNest board"), preset per board in
# sdkconfig.board.V15 … V18. One build directory AND one sdkconfig per board (-DSDKCONFIG puts
# the generated sdkconfig inside the build dir; without it every board would fight over ./sdkconfig),
# as PlatformIO had one environment per board:
#   idf.py -B build_V18 -DSDKCONFIG=build_V18/sdkconfig \
#          -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.board.V18" set-target esp32s3 build
#
# The library is consumed as a component from lib/incunest_afe4490 — on the development machine a
# junction to the library's own repo (same arrangement PlatformIO used); elsewhere scripts/get_lib.py
# (run by scripts/build.ps1) clones https://github.com/medicalopenworld/incunest_afe4490 there at the
# tag in lib/incunest_afe4490.version. Why not a submodule: docs/library_dependency.md.
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/lib/incunest_afe4490")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(pulsenest)

# Per-algorithm timing instrumentation inside the library ($TIMING / $TASKS frames over the
# console). A project-wide definition because the library compiles it in, not only main. This is
# the instrument that measures the SPI cost per sample under ESP-IDF — one of the reasons for the
# port — so it stays on in every PulseNest build. The host tests set it too (test_lib/runner).
idf_build_set_property(COMPILE_DEFINITIONS "INCUNEST_TIMING_STATS=1" APPEND)
