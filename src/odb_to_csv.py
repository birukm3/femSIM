# export_odb_to_csv.py
# Usage:
#   abaqus python export_odb_to_csv.py BENDFINAL.odb STEP_NAME=CUT FRAME=-1
#
# Outputs (in the working folder):
#   nodes.csv    -> instance,node_id,x,y,z
#   elements.csv -> instance,element_id,node_ids (space-separated)
#   stress.csv   -> instance,element_id,MISES,S11,S22,S33,S12,S13,S23 (element-averaged)

import sys
from collections import defaultdict

# --- args ---
def arg(name, default=None, cast=str):
    for a in sys.argv[2:]:
        if a.startswith(name+"="):
            return cast(a.split("=",1)[1])
    return default

if len(sys.argv) < 2:
    print("Usage: abaqus python export_odb_to_csv.py FILE.odb STEP_NAME=equ FRAME=-1")
    sys.exit(1)

odb_path  = sys.argv[1]
STEP_NAME = arg("STEP_NAME", "equ")
FRAME_IDX = arg("FRAME", -1, int)

# --- Abaqus imports (must be Abaqus Python) ---
from odbAccess import openOdb
from abaqusConstants import INTEGRATION_POINT, ELEMENT_NODAL

print("Opening ODB:", odb_path)
odb = openOdb(odb_path, readOnly=True)

# --- get step/frame ---
if STEP_NAME not in odb.steps:
    raise ValueError("Step '{}' not found. Available: {}".format(STEP_NAME, list(odb.steps.keys())))
step  = odb.steps[STEP_NAME]
frame = step.frames[FRAME_IDX] if FRAME_IDX >= 0 else step.frames[-1]

# --- open writers ---
nodes_f    = open("nodes.csv", "w");    nodes_f.write("instance,node_id,x,y,z\n")
elems_f    = open("elements.csv","w");  elems_f.write("instance,element_id,node_ids\n")
stress_f   = open("stress.csv","w");    stress_f.write("instance,element_id,MISES,S11,S22,S33,S12,S13,S23\n")

#write nodes & elements for each instance
asmb = odb.rootAssembly
#gets instances
instances = list(asmb.instances.values())
if not instances:
    raise RuntimeError("No instances found in rootAssembly.")

for inst in instances:
    #stores instance name
    iname = inst.name

    # nodes
    for n in inst.nodes:
        nodes_f.write("{},{},{},{},{}\n".format(iname, n.label, n.coordinates[0], n.coordinates[1], n.coordinates[2]))
    # elements
    for e in inst.elements:
        node_str = " ".join(str(nid) for nid in e.connectivity)
        elems_f.write("{},{},{}\n".format(iname, e.label, node_str))

# stress extraction 
if 'S' not in frame.fieldOutputs:
    raise RuntimeError("Stress field 'S' not present in this frame.")

S_full = frame.fieldOutputs['S']
# try IP first
try_positions = [INTEGRATION_POINT, ELEMENT_NODAL]
S_sub = None
pos_used = None
for pos in try_positions:
    try:
        tmp = S_full.getSubset(position=pos)
        # restrict to all instances at once by passing region later per-instance
        S_sub = tmp
        pos_used = pos
        break
    except Exception:
        continue
if S_sub is None:
    raise RuntimeError("Could not get stress field at INTEGRATION_POINT or ELEMENT_NODAL.")

print("Stress position used:", "INTEGRATION_POINT" if pos_used==INTEGRATION_POINT else "ELEMENT_NODAL")

# Accumulate average per element, per instance
for inst in instances:
    iname = inst.name
    # subset to this instance region
    S_inst = S_sub.getSubset(region=inst)
    sum_by_e = defaultdict(lambda: [0.0]*8)  # [mises,S11,S22,S33,S12,S13,S23,count]
    for v in S_inst.values:
        eid = v.elementLabel
        # v.data = (S11,S22,S33,S12,S13,S23)
        S11,S22,S33,S12,S13,S23 = v.data[0],v.data[1],v.data[2],v.data[3],v.data[4],v.data[5]
        try:
            mises = float(v.mises)
        except Exception:
            # fallback compute (for safety)
            mises = (((S11-S22)**2 + (S22-S33)**2 + (S33-S11)**2 + 6.0*(S12**2+S13**2+S23**2))/2.0)**0.5
	#stress value for the current element
        acc = sum_by_e[eid]
        acc[0] += mises
        acc[1] += S11; acc[2] += S22; acc[3] += S33
        acc[4] += S12; acc[5] += S13; acc[6] += S23
        acc[7] += 1.0

    # write averages
    for eid, acc in sorted(sum_by_e.items()):
        c = acc[7] if acc[7] else 1.0
        avg = [x/c for x in acc[:7]]
        stress_f.write("{},{},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g},{:.6g}\n"
                       .format(iname, eid, *avg))

# close everything
nodes_f.close(); elems_f.close(); stress_f.close(); odb.close()
print("Done. Wrote nodes.csv, elements.csv, stress.csv")

