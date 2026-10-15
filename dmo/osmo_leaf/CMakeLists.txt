# osmo-tetra lower-MAC leaf sources compiled in place (foreign code, no project_warnings)
add_library(osmo_leaf STATIC
  ${OSMO_TETRA_DIR}/lower_mac/tetra_scramb.c
  ${OSMO_TETRA_DIR}/lower_mac/tetra_interleave.c
  ${OSMO_TETRA_DIR}/lower_mac/crc_simple.c
  ${OSMO_TETRA_DIR}/lower_mac/tetra_conv_enc.c
  ${OSMO_TETRA_DIR}/lower_mac/viterbi.c
  ${OSMO_TETRA_DIR}/lower_mac/viterbi_cch.c
)

set_target_properties(osmo_leaf PROPERTIES ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

# SYSTEM: osmo headers use GNU extensions that -Wpedantic flags in our files
target_include_directories(osmo_leaf SYSTEM PUBLIC ${OSMO_TETRA_DIR})
target_link_libraries(osmo_leaf PUBLIC PkgConfig::OSMOCORE)
