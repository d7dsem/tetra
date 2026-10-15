cmake_minimum_required(VERSION 3.20)
project(TETRA LANGUAGES C CXX)

# --- Language standards
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Project warnings (apply per-target)
add_library(project_warnings INTERFACE)
target_compile_options(project_warnings INTERFACE
  $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wall -Wextra -Wpedantic>
)

# --- Outputs
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin/$<CONFIG>)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib/$<CONFIG>)

add_compile_definitions($<$<CONFIG:Debug>:_DEBUG>)

find_package(PkgConfig REQUIRED)
pkg_check_modules(OSMOCORE REQUIRED IMPORTED_TARGET libosmocore)

# Path to the osmo-tetra sources used by the decoder targets
set(OSMO_TETRA_DIR "$ENV{HOME}/Public/repos/osmo-tetra/src" CACHE PATH "osmo-tetra src directory")

# --- Targets
# Libraries: subdirectories with their own CMakeLists.txt (add_subdirectory).
# Executables: add_executable only in this file; entry files are <target>_entry.c.

add_subdirectory(dmo/osmo_leaf)
add_subdirectory(dmo/dmo_core)

add_executable(dmo_rx dmo/dmo_rx_entry.c)
target_link_libraries(dmo_rx PRIVATE dmo_core project_warnings)
