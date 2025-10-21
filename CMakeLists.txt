cmake_minimum_required(VERSION 3.12)
project(stl-cgal CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(CGAL REQUIRED)

add_executable(stl_to_cgal src/main.cpp) 
target_link_libraries(stl_to_cgal CGAL::CGAL)

add_executable(cv2 src/tetra_from_surface.cpp)

