#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>
#include <unordered_map>
#include <cmath>
#include <limits>

using namespace std;

struct Node { int id; double x,y,z; };
struct Elem { int id; string type; vector<int> conn; };

static vector<string> split_ws(const string& s){
    string tmp; vector<string> out; stringstream ss(s);
    while (ss >> tmp) out.push_back(tmp);
    return out;
}

static void trim_cr(string& s){ if(!s.empty() && s.back()=='\r') s.pop_back(); }

int vtkCellType(const string& t){
    if(t=="tet" || t=="C3D4") return 10;      // VTK_TETRA
    if(t=="hex" || t=="C3D8") return 12;      // VTK_HEXAHEDRON
    if(t=="wedge"|| t=="C3D6") return 13;     // VTK_WEDGE
    if(t=="pyr" || t=="C3D5") return 14;      // VTK_PYRAMID
    return -1;
}

int main(int argc, char** argv){
    // Args: nodes.csv elements.csv stress.csv [out.vtk] [elem_stress.csv]
    if (argc < 4){
        cerr << "Usage: " << argv[0] << " <nodes.csv> <elements.csv> <stress.csv> [out.vtk] [elem_stress.csv]\n";
        return 1;
    }
    string nodes_path  = argv[1];
    string elems_path  = argv[2];
    string stress_path = argv[3];
    string out_vtk     = (argc >= 5) ? argv[4] : "mesh.vtk";
    string map_csv     = (argc >= 6) ? argv[5] : "element_stress_map.csv";

    // ---- read nodes.csv ----
    vector<Node> nodes;
    {
        ifstream f(nodes_path);
        if(!f){ cerr << "ERROR: cannot open " << nodes_path << "\n"; return 2; }
        string line;
        if(!getline(f,line)){ cerr << "ERROR: empty " << nodes_path << "\n"; return 2; } // header
        while(getline(f,line)){
            trim_cr(line);
            if(line.empty()) continue;
            vector<string> parts; {
                string p; stringstream ss(line);
                while(getline(ss,p,',')) parts.push_back(p);
            }
            if(parts.size() < 4) continue;
            int n = parts.size();
            try{
                int nid = stoi(parts[n-4]);
                double x = stod(parts[n-3]), y = stod(parts[n-2]), z = stod(parts[n-1]);
                nodes.push_back({nid,x,y,z});
            }catch(...){}
        }
        cerr << "Read " << nodes.size() << " nodes\n";
    }

    // ---- read elements.csv ----
    vector<Elem> elems;
    {
        ifstream f(elems_path);
        if(!f){ cerr << "ERROR: cannot open " << elems_path << "\n"; return 3; }
        string line;
        if(!getline(f,line)){ cerr << "ERROR: empty " << elems_path << "\n"; return 3; } // header
        while(getline(f,line)){
            trim_cr(line);
            if(line.empty()) continue;
            vector<string> parts; {
                string p; stringstream ss(line);
                while(getline(ss,p,',')) parts.push_back(p);
            }
            try{
                if(parts.size()>=3 && parts[2].find(' ')!=string::npos){
                    int eid = stoi(parts[1]);
                    vector<string> ws = split_ws(parts[2]);
                    vector<int> conn; conn.reserve(ws.size());
                    for(auto& s: ws) conn.push_back(stoi(s));
                    elems.push_back({eid, "C3D8", conn});
                } else if(parts.size()>=3){
                    int eid = stoi(parts[0]);
                    string type = parts[1];
                    vector<int> conn;
                    for(size_t i=2;i<parts.size();++i)
                        if(!parts[i].empty()) conn.push_back(stoi(parts[i]));
                    elems.push_back({eid, type, conn});
                }
            }catch(...){}
        }
        cerr << "Read " << elems.size() << " elements\n";
    }

    // ---- read stress.csv ----
    unordered_map<int,double> elem_to_vm;
    {
        ifstream f(stress_path);
        if(!f){ cerr << "WARN: cannot open " << stress_path << "\n"; }
        else {
            string header;
            if(getline(f,header)){
                vector<string> heads; {
                    string p; stringstream ss(header);
                    while(getline(ss,p,',')) heads.push_back(p);
                }
                int idx_eid=-1, idx_vm=-1;
                for(int i=0;i<(int)heads.size();++i){
                    if(heads[i]=="element_id" || heads[i]=="elem_id") idx_eid=i;
                    if(heads[i]=="MISES" || heads[i]=="VonMises" || heads[i]=="von_mises") idx_vm=i;
                }
                string line;
                while(getline(f,line)){
                    trim_cr(line);
                    if(line.empty()) continue;
                    vector<string> parts; {
                        string p; stringstream ss(line);
                        while(getline(ss,p,',')) parts.push_back(p);
                    }
                    if((int)parts.size()<=max(idx_eid,idx_vm)) continue;
                    try{
                        int eid = stoi(parts[idx_eid]);
                        double vm = stod(parts[idx_vm]);
                        elem_to_vm[eid] = vm;
                    }catch(...){}
                }
                cerr << "Read " << elem_to_vm.size() << " stress rows\n";
            }
        }
    }

    if(nodes.empty() || elems.empty()){
        cerr << "ERROR: missing nodes or elements\n";
        return 4;
    }

    // ---- node index map ----
    unordered_map<int,int> nid2idx; nid2idx.reserve(nodes.size());
    sort(nodes.begin(), nodes.end(), [](const Node&a,const Node&b){return a.id<b.id;});
    for(int i=0;i<(int)nodes.size();++i) nid2idx[nodes[i].id]=i;

    // ---- write VTK ----
    ofstream out(out_vtk);
    if(!out){ cerr<<"ERROR: cannot write "<<out_vtk<<"\n"; return 5; }
    out << "# vtk DataFile Version 3.0\nmesh\nASCII\nDATASET UNSTRUCTURED_GRID\n";
    out << "POINTS " << nodes.size() << " float\n";
    for(const auto& p: nodes) out << p.x << " " << p.y << " " << p.z << "\n";
    size_t list_size = 0;
    for(const auto& e: elems) list_size += 1 + e.conn.size();
    out << "CELLS " << elems.size() << " " << list_size << "\n";
    for(const auto& e: elems){
        out << e.conn.size();
        for(int nid: e.conn){
            auto it = nid2idx.find(nid);
            out << " " << (it==nid2idx.end()?0:it->second);
        }
        out << "\n";
    }
    out << "CELL_TYPES " << elems.size() << "\n";
    for(const auto& e: elems){
        int ct = vtkCellType(e.type);
        if(ct<0){
            if(e.conn.size()==4) ct=10;
            else if(e.conn.size()==8) ct=12;
            else if(e.conn.size()==6) ct=13;
            else if(e.conn.size()==5) ct=14;
            else ct=0;
        }
        out << ct << "\n";
    }
    out << "CELL_DATA " << elems.size() << "\n";
    out << "SCALARS von_mises float 1\nLOOKUP_TABLE default\n";
    for(const auto& e: elems){
        auto it = elem_to_vm.find(e.id);
        float v = (it==elem_to_vm.end()) ? std::numeric_limits<float>::quiet_NaN()
                                         : static_cast<float>(it->second);
        out << v << "\n";
    }
    out.close();

    // ---- write element→stress mapping to CSV ----
    {
        ofstream ms(map_csv);
        if(!ms){
            cerr << "WARN: cannot write " << map_csv << "\n";
        } else {
            ms << "element_id,MISES\n";
            for (const auto& e : elems) {
                auto it = elem_to_vm.find(e.id);
                if (it != elem_to_vm.end())
                    ms << e.id << "," << it->second << "\n";
                else
                    ms << e.id << ",\n";
            }
            ms.close();
            cerr << "Wrote element→stress CSV: " << map_csv << "\n";
        }
    }

    cerr << "Wrote " << out_vtk << " with " << nodes.size() << " points and "
         << elems.size() << " cells. Map size=" << elem_to_vm.size() << "\n";

    return 0;
}
