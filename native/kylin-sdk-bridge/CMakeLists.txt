cmake_minimum_required(VERSION 3.16)

project(wanwei-kylin-sdk-bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
find_package(nlohmann_json REQUIRED)

# These package names are provided by the official Kylin SDK development
# packages, not by the project's Debian-based Docker image.
pkg_check_modules(KYLIN_COREAI_EMBEDDING REQUIRED IMPORTED_TARGET kysdk-coreai-embedding)
pkg_check_modules(KYLIN_VECTOR_ENGINE REQUIRED IMPORTED_TARGET kysdk-vector-engine-client)

add_executable(wanwei-kylin-sdk-bridge src/main.cpp)
target_link_libraries(
    wanwei-kylin-sdk-bridge
    PRIVATE
        nlohmann_json::nlohmann_json
        PkgConfig::KYLIN_COREAI_EMBEDDING
        PkgConfig::KYLIN_VECTOR_ENGINE
)

install(TARGETS wanwei-kylin-sdk-bridge RUNTIME DESTINATION bin)
