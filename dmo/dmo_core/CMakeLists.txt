# DMO physical-layer decoding core (DSB sync, burst slicing, block decode)
add_library(dmo_core STATIC
  dmo_sync.c
  dmo_burst.c
  dmo_block.c
  dmo_find.c
  dmo_parse.c
)

set_target_properties(dmo_core PROPERTIES ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib")

target_include_directories(dmo_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(dmo_core PUBLIC osmo_leaf PRIVATE project_warnings)
