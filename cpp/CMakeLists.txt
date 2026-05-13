cmake_minimum_required(VERSION 3.16)
project(kalshi_arbitrage_cpp CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# --- Help find Homebrew OpenSSL on macOS ---
if(APPLE AND NOT DEFINED OPENSSL_ROOT_DIR)
  foreach(_d /opt/homebrew/opt/openssl@3 /usr/local/opt/openssl@3
             /opt/homebrew/opt/openssl  /usr/local/opt/openssl)
    if(EXISTS "${_d}")
      set(OPENSSL_ROOT_DIR "${_d}")
      break()
    endif()
  endforeach()
endif()

find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(Boost 1.74 REQUIRED)            # Beast/Asio are header-only

# nlohmann_json: use a system install if present, otherwise fetch it.
find_package(nlohmann_json 3.2.0 QUIET)
if(NOT nlohmann_json_FOUND)
  include(FetchContent)
  FetchContent_Declare(nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz)
  FetchContent_MakeAvailable(nlohmann_json)
endif()

add_executable(intra_kalshi_arbitrage
  src/main.cpp
  src/logging.cpp
  src/crypto.cpp
  src/util.cpp
  src/config.cpp
  src/order_book.cpp
  src/position_manager.cpp
  src/kalshi_http_gateway.cpp
  src/kalshi_feed.cpp
  src/intra_kalshi_arbitrage.cpp
)

target_link_libraries(intra_kalshi_arbitrage PRIVATE
  Boost::boost
  OpenSSL::SSL
  OpenSSL::Crypto
  Threads::Threads
  nlohmann_json::nlohmann_json
)

if(WIN32)
  target_link_libraries(intra_kalshi_arbitrage PRIVATE ws2_32 mswsock)
endif()

if(MSVC)
  target_compile_options(intra_kalshi_arbitrage PRIVATE /W4 /bigobj)
else()
  target_compile_options(intra_kalshi_arbitrage PRIVATE -Wall -Wextra)
endif()
