# PulseNest host unit tests — builds the incunest_afe4490 library for the host (hal_host, UNIT_TEST)
# and one executable per test/test_*/ directory, linked against Unity (vendored, MIT, ./unity).
# Replaces PlatformIO's [env:native] + `pio test -e native`. Run with tools/host_tests/run_host_tests.py.
cmake_minimum_required(VERSION 3.20)
project(pulsenest_host_tests C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(PULSENEST_ROOT "${CMAKE_CURRENT_LIST_DIR}/../..")
set(INCUNEST_LIB_DIR "${PULSENEST_ROOT}/lib/incunest_afe4490")
set(PULSENEST_TEST_DIR "${PULSENEST_ROOT}/test")

# Unity 2.6.0 (from ESP-IDF components/unity/unity, unmodified)
add_library(unity STATIC unity/unity.c)
target_include_directories(unity PUBLIC unity)
target_compile_definitions(unity PUBLIC UNITY_INCLUDE_DOUBLE)

# The library, host flavour: same sources the firmware compiles plus the host HAL (no-op GPIO/SPI,
# fake FreeRTOS/esp_log/esp_timer from incunest_afe4490_hal_host.h). UNIT_TEST opens the test_* accessors.
add_library(incunest_afe4490_host STATIC
    "${INCUNEST_LIB_DIR}/incunest_afe4490.cpp"
    "${INCUNEST_LIB_DIR}/incunest_afe4490_hal_host.cpp")
target_include_directories(incunest_afe4490_host PUBLIC "${INCUNEST_LIB_DIR}")
target_compile_definitions(incunest_afe4490_host PUBLIC UNIT_TEST)
target_compile_options(incunest_afe4490_host PRIVATE -Wall -Wextra -Werror)

# One executable per suite: test/test_<name>/*.cpp -> test_<name>
enable_testing()
file(GLOB PULSENEST_TEST_SUITES LIST_DIRECTORIES true "${PULSENEST_TEST_DIR}/test_*")
foreach(suite_dir IN LISTS PULSENEST_TEST_SUITES)
    if(NOT IS_DIRECTORY "${suite_dir}")
        continue()
    endif()
    get_filename_component(suite "${suite_dir}" NAME)
    file(GLOB suite_srcs "${suite_dir}/*.cpp" "${suite_dir}/*.c")
    add_executable(${suite} ${suite_srcs})
    target_link_libraries(${suite} PRIVATE incunest_afe4490_host unity)
    target_compile_options(${suite} PRIVATE -Wall -Wextra)
    if(MINGW)
        target_link_options(${suite} PRIVATE -static-libgcc -static-libstdc++)
    endif()
    add_test(NAME ${suite} COMMAND ${suite})
endforeach()
