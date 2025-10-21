#include <iostream>
#include <string>
#include <CGAL/Simple_cartesian.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/IO/polygon_mesh_io.h>
#include <CGAL/Polygon_mesh_processing/repair.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/triangulate_faces.h>


namespace PMP = CGAL::Polygon_mesh_processing;

using Kernel = CGAL::Simple_cartesian<double>;
using Point  = Kernel::Point_3;
using Mesh   = CGAL::Surface_mesh<Point>;


int main(int argc, char**argv){
    if (argc < 2){
        std::cerr << "Usage: " << argv[0];
        return 1;
    }

    const std::string in_name = argv[1];

    std::string out_name = "cleaned.STL";
    if (argc >= 3){
        out_name = argv[2];
    }

    Mesh mesh;

    if(!CGAL::IO::read_polygon_mesh(in_name, mesh) || CGAL::is_empty(mesh)){
        std::cerr << "ERROR: failed to read mesh from" << in_name << "\n";
        return 2;
    }


    std::cout << "Loaded: " << in_name << "\n";

    std::cout  << "verticies:" << num_vertices(mesh)
                << "edges: " << num_edges(mesh)
                << "faces: " << num_faces(mesh) << "\n";

    //ensure trianges
    if(!CGAL::is_triangle_mesh(mesh)){
        std::cout << "Triangulating faces..\n";
        PMP::triangulate_faces(mesh);
        std::cout << "Faces after: "<<num_faces(mesh) << "\n";
    }

    //closing cracks in mesh
    std::size_t stiched = PMP::stitch_borders(mesh);
    if(stiched){
        std::cout << "Stiched " << stiched << "boarder edges.\n";
    }

    //check if closed
    bool closed = CGAL::is_closed(mesh);
    if(closed){
        std::cout << "It was closed before orientation";
    }else{
        std::cout <<"Was not closed before orientation";
    }

    //fixes orientation of normal
    if(!PMP::is_outward_oriented(mesh)){
        std::cout << "Reorienting to bound a volume..\n";
        PMP::orient_to_bound_a_volume(mesh);
    }

    //check if closed
    bool closed_after = CGAL::is_closed(mesh);
    bool outward_after = PMP::is_outward_oriented(mesh);
    std::cout << "Closed after orientation? "  << (closed_after ? "yes" : "no") << "\n";
    std::cout << "Outward oriented after? "    << (outward_after ? "yes" : "no") << "\n";

    //write to output file
    if (!CGAL::IO::write_polygon_mesh(out_name, mesh, CGAL::parameters::stream_precision(17))) {
        std::cerr << "ERROR: failed to write " << out_name << "\n";
        return 3;
    }

    std::cout << "Cleaned mesh: " << out_name << "\n";
    return 0;

}
