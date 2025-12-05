# export_odb_to_csv_active_only_with_boundary.py
# Usage:
#   abaqus python export_odb_to_csv_active_only_with_boundary.py shotpeen4.odb STEP_NAME=equil FRAME=-1
#   abaqus python export_odb_to_csv_active_only_with_boundary.py shotpeen4.odb STEP_NAME=cut FRAME=0
#   abaqus python export_odb_to_csv_active_only_with_boundary.py shotpeen4.odb STEP_NAME=cut FRAME=-1
# Optional:
#   abaqus python export_odb_to_csv_active_only_with_boundary.py shotpeen4.odb STEP_NAME=cut FRAME=-1 NODESET=CUT_NODES

import sys
from collections import defaultdict
from odbAccess import openOdb
from abaqusConstants import INTEGRATION_POINT, ELEMENT_NODAL


# --- arg parsing ---
def arg(name, default=None, cast=str):
    for a in sys.argv[2:]:
        if a.startswith(name + "="):
            return cast(a.split("=", 1)[1])
    return default


if len(sys.argv) < 2:
    print("Usage: abaqus python export_odb_to_csv_active_only_with_boundary.py FILE.odb STEP_NAME=equil FRAME=-1 [NODESET=Name]")
    sys.exit(1)

odb_path = sys.argv[1]
STEP_NAME = arg("STEP_NAME", "equil")
FRAME_IDX = arg("FRAME", -1, int)
BOUNDARY_NODESET = arg("NODESET", None)  # optional: use a named nodeset as boundary


print("Opening ODB:", odb_path)
odb = openOdb(odb_path, readOnly=True)

# --- get step/frame ---
if STEP_NAME not in odb.steps:
    raise ValueError("Step '{}' not found. Available: {}".format(STEP_NAME, list(odb.steps.keys())))

step = odb.steps[STEP_NAME]
frame = step.frames[FRAME_IDX] if FRAME_IDX >= 0 else step.frames[-1]

# --- open writers (suffix per frame) ---
suffix = "{}_f{}".format(STEP_NAME, FRAME_IDX if FRAME_IDX >= 0 else "last")

nodes_f = open("nodes_{}.csv".format(suffix), "w")
nodes_f.write("instance,node_id,x,y,z\n")

elems_f = open("elements_{}.csv".format(suffix), "w")
elems_f.write("instance,element_id,node_ids\n")

stress_f = open("stress_{}.csv".format(suffix), "w")
stress_f.write("instance,element_id,MISES,S11,S22,S33,S12,S13,S23\n")

boundary_nodes_f = open("boundary_nodes_{}.csv".format(suffix), "w")
boundary_nodes_f.write("instance,node_id,x,y,z\n")


# --- helper: get faces for common 3D elements ---
def element_faces(elem):
    """
    Return faces (tuples of node labels) for common 3D element types.
    Currently supports:
      - 4-node tets (C3D4)
      - 8-node bricks (C3D8)
    For other types, returns [] and they won't contribute to boundary detection.
    """
    conn = elem.connectivity
    etype = elem.type.upper()

    # Linear tet (4 nodes)
    if etype.startswith('C3D4') or len(conn) == 4:
        n0, n1, n2, n3 = conn
        return [
            (n0, n1, n2),
            (n0, n1, n3),
            (n0, n2, n3),
            (n1, n2, n3),
        ]

    # Linear hex (8 nodes)
    if etype.startswith('C3D8') or len(conn) == 8:
        n0, n1, n2, n3, n4, n5, n6, n7 = conn
        return [
            (n0, n1, n2, n3),  # bottom
            (n4, n5, n6, n7),  # top
            (n0, n1, n5, n4),  # side
            (n2, n3, n7, n6),  # side
            (n0, n3, n7, n4),  # side
            (n1, n2, n6, n5),  # side
        ]

    # Add more element types here if needed
    return []


# --- active elements via stress or STATUS field ---
S_full = frame.fieldOutputs['S']
S_sub = None
for pos in (INTEGRATION_POINT, ELEMENT_NODAL):
    try:
        S_sub = S_full.getSubset(position=pos)
        break
    except Exception:
        continue
if S_sub is None:
    raise RuntimeError("No stress field found at INTEGRATION_POINT or ELEMENT_NODAL")

STATUS = frame.fieldOutputs['STATUS'] if 'STATUS' in frame.fieldOutputs else None

active_eids_by_inst = {}
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    S_inst = S_sub.getSubset(region=inst)
    eids = set(v.elementLabel for v in S_inst.values)

    if STATUS is not None:
        ST_inst = STATUS.getSubset(region=inst)
        eids_status = {v.elementLabel for v in ST_inst.values if float(v.data) > 0.5}
        if eids_status:
            eids = eids.intersection(eids_status)

    active_eids_by_inst[iname] = eids

# --- active nodes per instance ---
active_nodes_by_inst = {}
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    eids = active_eids_by_inst[iname]
    node_ids = set()
    elem_map = {e.label: e for e in inst.elements}
    for eid in eids:
        if eid in elem_map:
            node_ids.update(elem_map[eid].connectivity)
    active_nodes_by_inst[iname] = node_ids

# --- boundary nodes per instance (topological + optional nodeset) ---
boundary_nodes_by_inst = {}

# 1) Topological boundary from element faces
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    eids = active_eids_by_inst[iname]
    elem_map = {e.label: e for e in inst.elements}

    face_counts = defaultdict(int)

    # Count how many elements share each face
    for eid in eids:
        elem = elem_map.get(eid, None)
        if elem is None:
            continue
        for face in element_faces(elem):
            face_key = tuple(sorted(face))
            face_counts[face_key] += 1

    # Faces that appear once are on the boundary
    bnd_nodes = set()
    for face, count in face_counts.items():
        if count == 1:
            bnd_nodes.update(face)

    # Restrict to active nodes in this instance
    bnd_nodes = bnd_nodes.intersection(active_nodes_by_inst[iname])
    boundary_nodes_by_inst[iname] = bnd_nodes

# 2) Optional: union with nodes from a named nodeset
if BOUNDARY_NODESET is not None:
    print("Using NODESET='{}' to augment boundary nodes (instance-level sets only).".format(BOUNDARY_NODESET))
    for inst in odb.rootAssembly.instances.values():
        iname = inst.name
        nsmap = inst.nodeSets
        if BOUNDARY_NODESET in nsmap:
            ns = nsmap[BOUNDARY_NODESET]
            for n in ns.nodes:
                if n.label in active_nodes_by_inst[iname]:
                    boundary_nodes_by_inst[iname].add(n.label)


# --- write active nodes & elements ---
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    active_nodes = active_nodes_by_inst[iname]
    active_eids = active_eids_by_inst[iname]
    elem_map = {e.label: e for e in inst.elements}

    # All active nodes
    for n in inst.nodes:
        if n.label in active_nodes:
            nodes_f.write("{},{},{},{},{}\n".format(
                iname, n.label, n.coordinates[0], n.coordinates[1], n.coordinates[2]
            ))

    # Active elements
    for eid in sorted(active_eids):
        elem = elem_map.get(eid, None)
        if elem is None:
            continue
        conn = elem.connectivity
        elems_f.write("{},{},{}\n".format(
            iname, eid, " ".join(str(i) for i in conn)
        ))


# --- write boundary nodes only ---
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    bnd_nodes = boundary_nodes_by_inst.get(iname, set())

    for n in inst.nodes:
        if n.label in bnd_nodes:
            boundary_nodes_f.write("{},{},{},{},{}\n".format(
                iname, n.label, n.coordinates[0], n.coordinates[1], n.coordinates[2]
            ))


# --- average stresses per active element ---
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    eids = active_eids_by_inst[iname]
    S_inst = S_sub.getSubset(region=inst)

    sums = defaultdict(lambda: [0.0] * 8)
    for v in S_inst.values:
        eid = v.elementLabel
        if eid not in eids:
            continue
        S11, S22, S33, S12, S13, S23 = v.data
        try:
            mises = float(v.mises)
        except Exception:
            mises = (((S11 - S22) ** 2 + (S22 - S33) ** 2 + (S33 - S11) ** 2 +
                     6.0 * (S12 ** 2 + S13 ** 2 + S23 ** 2)) / 2.0) ** 0.5
        acc = sums[eid]
        acc[0] += mises
        acc[1] += S11
        acc[2] += S22
        acc[3] += S33
        acc[4] += S12
        acc[5] += S13
        acc[6] += S23
        acc[7] += 1

    for eid, acc in sorted(sums.items()):
        c = acc[7] if acc[7] else 1
        avg = [x / c for x in acc[:7]]
        stress_f.write("{},{},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g}\n".format(
            iname, eid, *avg
        ))


# --- close everything ---
nodes_f.close()
elems_f.close()
stress_f.close()
boundary_nodes_f.close()
odb.close()

print("Done.")
print("Wrote nodes_{}.csv, elements_{}.csv, stress_{}.csv, boundary_nodes_{}.csv".format(
    suffix, suffix, suffix, suffix
))


