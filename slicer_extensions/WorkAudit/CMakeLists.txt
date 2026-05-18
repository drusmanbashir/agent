cmake_minimum_required(VERSION 3.13.0)

project(WorkAudit)

set(EXTENSION_HOMEPAGE "https://github.com/ub/WorkAudit")
set(EXTENSION_CATEGORY "Segmentation")
set(EXTENSION_CONTRIBUTORS "ub; OpenAI Codex")
set(EXTENSION_DESCRIPTION "Transparent, local-only case activity auditing for 3D Slicer segmentation work.")
set(EXTENSION_ICONURL "")
set(EXTENSION_SCREENSHOTURLS "")

find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

add_subdirectory(WorkAudit)

include(${Slicer_EXTENSION_CPACK})
