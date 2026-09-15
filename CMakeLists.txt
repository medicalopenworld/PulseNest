# PulseNest — ESP-IDF project (phase 1 of the Arduino → ESP-IDF port, branch feat/idf-port).
#
# The PlatformIO build (platformio.ini, src/main.cpp) stays intact and authoritative until this
# build reaches parity on the bench; then it is removed in its own commit. Until then the two
# builds coexist: `pio run -e incunest_V18` and `idf.py -B build_V18 build` from the same tree.
#
# Board selection: Kconfig (main/Kconfig.projbuild, menu "PulseNest board"), preset per board in
# sdkconfig.board.V15 … V18. One build directory AND one sdkconfig per board (-DSDKCONFIG puts
# the generated sdkconfig inside the build dir; without it every board would fight over ./sdkconfig),
# as PlatformIO had one environment per board:
#   idf.py -B build_V18 -DSDKCONFIG=build_V18/sdkconfig \
#          -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.board.V18" set-target esp32s3 build
#
# The library is consumed as a component from lib/incunest_afe4490 — on the development machine
# a symlink to the library's own repo (same arrangement PlatformIO used), elsewhere a git
# submodule of https://github.com/medicalopenworld/incunest_afe4490 at a tag.
cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/lib/incunest_afe4490")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(pulsenest)

# Per-algorithm timing instrumentation inside the library ($TIMING / $TASKS frames over the
# console). A project-wide definition because the library compiles it in, not only main. This is
# the instrument that measures the SPI cost per sample under ESP-IDF — one of the reasons for the
# port — so it stays on in every PulseNest build, as it did under PlatformIO.
idf_build_set_property(COMPILE_DEFINITIONS "INCUNEST_TIMING_STATS=1" APPEND)
