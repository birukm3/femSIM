# export_odb_to_csv_active_only.py
# Usage:
#   abaqus python export_odb_to_csv_active_only.py shotpeen4.odb STEP_NAME=equil FRAME=-1
#   abaqus python export_odb_to_csv_active_only.py shotpeen4.odb STEP_NAME=cut FRAME=0
#   abaqus python export_odb_to_csv_active_only.py shotpeen4.odb STEP_NAME=cut FRAME=-1

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
    print("Usage: abaqus python export_odb_to_csv_active_only.py FILE.odb STEP_NAME=equil FRAME=-1")
    sys.exit(1)

odb_path = sys.argv[1]
STEP_NAME = arg("STEP_NAME", "equil")
FRAME_IDX = arg("FRAME", -1, int)

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

# ✅ fixed line
STATUS = frame.fieldOutputs['STATUS'] if 'STATUS' in frame.fieldOutputs else None

active_eids_by_inst = {}
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    S_inst = S_sub.getSubset(region=inst)
    eids = set(v.elementLabel for v in S_inst.values)

    if STATUS is not None:
        ST_inst = STATUS.getSubset(region=inst)
        eids_status = {v.elementLabel for v in ST_inst.values if float(v.data) > 0.5}
        eids = eids.intersection(eids_status) if eids_status else eids

    active_eids_by_inst[iname] = eids

# --- active nodes per instance ---
active_nodes_by_inst = {}
for inst in odb.rootAssembly.instances.values():
    eids = active_eids_by_inst[inst.name]
    node_ids = set()
    elem_map = {e.label: e for e in inst.elements}
    for eid in eids:
        node_ids.update(elem_map[eid].connectivity)
    active_nodes_by_inst[inst.name] = node_ids

# --- write active nodes & elements ---
for inst in odb.rootAssembly.instances.values():
    iname = inst.name
    active_nodes = active_nodes_by_inst[iname]
    active_eids = active_eids_by_inst[iname]
    elem_map = {e.label: e for e in inst.elements}

    for n in inst.nodes:
        if n.label in active_nodes:
            nodes_f.write("{},{},{},{},{}\n".format(iname, n.label, *n.coordinates))

    for eid in sorted(active_eids):
        conn = elem_map[eid].connectivity
        elems_f.write("{},{},{}\n".format(iname, eid, " ".join(str(i) for i in conn)))

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
        acc[1] += S11; acc[2] += S22; acc[3] += S33
        acc[4] += S12; acc[5] += S13; acc[6] += S23
        acc[7] += 1

    for eid, acc in sorted(sums.items()):
        c = acc[7] if acc[7] else 1
        avg = [x / c for x in acc[:7]]
        stress_f.write("{},{},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g}\n".format(iname, eid, *avg))

# --- close everything ---
nodes_f.close()
elems_f.close()
stress_f.close()
odb.close()

print("Done. Wrote nodes_{}.csv, elements_{}.csv, stress_{}.csv".format(suffix, suffix, suffix))
