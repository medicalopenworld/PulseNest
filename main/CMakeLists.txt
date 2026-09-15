idf_component_register(
    SRCS "pulsenest_main.cpp"
    INCLUDE_DIRS "." "${CMAKE_CURRENT_LIST_DIR}/../include"
    REQUIRES incunest_afe4490
             esp_driver_spi esp_driver_gpio esp_driver_uart
             esp_wifi esp_netif esp_event esp_http_server app_update
             esp_timer nvs_flash spi_flash esp_partition
)

# build_version.h — PulseNest and library git hashes (short, "-dirty" when the tree has local
# changes), regenerated on EVERY build so the $CFG frame identifies the binary exactly. The script
# only rewrites the header when the hashes change, so an unchanged tree does not recompile main.
# Replaces PlatformIO's scripts/pre_build_hash.py (which injected -D flags).
set(PULSENEST_BUILD_VERSION_H "${CMAKE_BINARY_DIR}/build_version.h")
add_custom_target(pulsenest_build_version ALL
    COMMAND ${PYTHON} "${CMAKE_CURRENT_LIST_DIR}/../scripts/gen_build_version.py"
            "${CMAKE_CURRENT_LIST_DIR}/.." "${CMAKE_CURRENT_LIST_DIR}/../lib/incunest_afe4490"
            "${PULSENEST_BUILD_VERSION_H}"
    BYPRODUCTS "${PULSENEST_BUILD_VERSION_H}"
    COMMENT "PulseNest: refreshing build_version.h"
    VERBATIM)
add_dependencies(${COMPONENT_LIB} pulsenest_build_version)
target_include_directories(${COMPONENT_LIB} PRIVATE "${CMAKE_BINARY_DIR}")

# Same policy as the library: this is a medical-device bench tool, warnings are errors.
target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
