cmake_minimum_required(VERSION 3.16)
project(mow_offline_runner CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Offline runner executable
add_executable(mow_offline_runner
    main.cpp
    ../../lib/incunest_afe4490/incunest_afe4490.cpp
)

target_compile_definitions(mow_offline_runner PRIVATE
    INCUNEST_OFFLINE=1
    INCUNEST_TIMING_STATS=0
)

# Include paths: library headers (mow_offline_platform.h lives alongside the library)
target_include_directories(mow_offline_runner PRIVATE
    ../../lib/incunest_afe4490
)

# Math library (needed on Linux/macOS; harmless on Windows/MSVC)
target_link_libraries(mow_offline_runner PRIVATE m)

if(MSVC)
    target_compile_options(mow_offline_runner PRIVATE /W3)
else()
    target_compile_options(mow_offline_runner PRIVATE -Wall -Wextra -Wno-unused-parameter)
    # Static link on MinGW to avoid runtime DLL dependencies
    if(WIN32)
        target_link_options(mow_offline_runner PRIVATE -static)
    endif()
endif()
