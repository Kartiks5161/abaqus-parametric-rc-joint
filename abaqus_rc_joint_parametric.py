"""Nonlinear RC beam-column joint model for Abaqus/CAE.

Run inside Abaqus/CAE or with:
    abaqus cae script=abaqus_rc_joint_parametric.py

The script creates a reinforced-concrete exterior beam-column joint, embeds
longitudinal bars and stirrups, assigns nonlinear concrete and steel materials,
applies axial column load plus monotonic or cyclic beam-end displacement, creates
analysis jobs, and can optionally submit jobs and extract result summaries. It
also defines a disabled-by-default parameterized case set for later comparison.
"""

from __future__ import print_function

import csv
import math
import os
import re

from abaqus import mdb, session
from abaqusConstants import *
import assembly
import interaction
import job
import load
import material
import mesh
import part
import regionToolset
import section
import sketch
import step
import visualization
from odbAccess import openOdb


def locate_project_directory():
    if "__file__" in globals():
        return os.path.dirname(os.path.abspath(__file__))

    configured_directory = os.environ.get("RC_JOINT_PROJECT_DIR", "")
    candidates = (
        configured_directory,
        os.path.join(os.path.expanduser("~"), "Desktop", "Placements", "Project_2"),
        os.getcwd(),
    )
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "abaqus_rc_joint_parametric.py")):
            return os.path.abspath(candidate)
    return os.getcwd()


SCRIPT_DIR = locate_project_directory()


# ----------------------------- Study Controls ----------------------------- #

BASE = {
    "model_name": "RC_Joint_Base",
    "beam_length": 2400.0,
    "beam_depth": 450.0,
    "beam_width": 300.0,
    "column_height": 3000.0,
    "column_depth": 450.0,
    "column_width": 450.0,
    "cover": 40.0,
    "main_bar_dia": 20.0,
    "stirrup_dia": 8.0,
    "beam_top_bars": 3,
    "beam_bottom_bars": 3,
    "column_bars_each_face": 3,
    "stirrup_spacing": 100.0,
    "concrete_fc": 35.0,
    "steel_fy": 500.0,
    "axial_load_ratio": 0.10,
    "beam_drift_ratio": 0.035,
    "damage_onset_threshold": 0.01,
    "load_protocol": "monotonic",  # "monotonic" or "cyclic"
    "mesh_size": 90.0,
    "joint_mesh_size": 45.0,
    "cpus": 4,
}

PARAMETRIC_CASES = [
    {"case": "S75_FC35", "stirrup_spacing": 75.0, "concrete_fc": 35.0},
    {"case": "S100_FC35", "stirrup_spacing": 100.0, "concrete_fc": 35.0},
    {"case": "S150_FC35", "stirrup_spacing": 150.0, "concrete_fc": 35.0},
    {"case": "S100_FC45", "stirrup_spacing": 100.0, "concrete_fc": 45.0},
]

RUN_SETTINGS = {
    # Validate one baseline analysis before enabling the full parametric batch.
    "clear_previous_generated_models": True,
    "build_all_parametric_cases": False,
    "submit_jobs": True,
    "extract_results": True,
    "save_cae": True,
    "cae_file": "rc_joint_parametric_models.cae",
}


# ------------------------------ Utilities --------------------------------- #

def bar_area(diameter):
    return math.pi * diameter ** 2.0 / 4.0


def update_case(base, overrides):
    data = dict(base)
    data.update(overrides)
    return data


def safe_mkdir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def open_csv_for_write(path):
    try:
        return open(path, "w", newline="")
    except TypeError:
        return open(path, "wb")


def delete_model_if_present(model_name):
    try:
        if model_name in list(mdb.models.keys()):
            del mdb.models[model_name]
            return True
    except Exception as err:
        print("Could not delete model %s: %s" % (model_name, err))
    return False


def delete_job_if_present(job_name):
    try:
        if job_name in list(mdb.jobs.keys()):
            del mdb.jobs[job_name]
            return True
    except Exception as err:
        print("Could not delete job %s: %s" % (job_name, err))
    return False


def abaqus_name(text):
    """Create an Abaqus-safe repository name from parameter text."""
    name = str(text).replace(".", "p").replace("-", "m")
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name)
    name = name.strip("_")
    if not name or not name[0].isalpha():
        name = "N_" + name
    return name[:80]


def linear_positions(start, end, count):
    if count <= 1:
        return [(start + end) / 2.0]
    step = (end - start) / float(count - 1)
    return [start + i * step for i in range(count)]


def concrete_elastic_modulus(fc_mpa):
    # ACI-style estimate in MPa for normal-weight concrete.
    return 4700.0 * math.sqrt(fc_mpa)


def make_cdp_tables(fc_mpa):
    """Return simplified CDP compression, tension, and damage tables.

    The values are intentionally transparent and easy to calibrate for a
    specific test program. Strains are total inelastic/cracking quantities as
    expected by Abaqus CDP material suboptions.
    """
    ft = 0.33 * math.sqrt(fc_mpa)
    compression = (
        (0.40 * fc_mpa, 0.0000),
        (0.75 * fc_mpa, 0.0005),
        (1.00 * fc_mpa, 0.0015),
        (0.85 * fc_mpa, 0.0035),
        (0.55 * fc_mpa, 0.0080),
    )
    tension = (
        (ft, 0.00000),
        (0.45 * ft, 0.00025),
        (0.15 * ft, 0.00150),
        (0.02 * ft, 0.00600),
    )
    compression_damage = (
        (0.00, 0.0000),
        (0.15, 0.0005),
        (0.35, 0.0015),
        (0.65, 0.0035),
        (0.90, 0.0080),
    )
    tension_damage = (
        (0.00, 0.00000),
        (0.40, 0.00025),
        (0.75, 0.00150),
        (0.95, 0.00600),
    )
    return compression, tension, compression_damage, tension_damage


# ------------------------------- Geometry --------------------------------- #

def create_concrete_parts(model, p):
    beam = model.Part(name="Concrete_Beam", dimensionality=THREE_D, type=DEFORMABLE_BODY)
    sketch = model.ConstrainedSketch(name="beam_profile", sheetSize=5000.0)
    beam_x0 = p["column_depth"] / 2.0
    beam_x1 = beam_x0 + p["beam_length"]
    sketch.rectangle(
        point1=(beam_x0, -p["beam_depth"] / 2.0),
        point2=(beam_x1, p["beam_depth"] / 2.0),
    )
    beam.BaseSolidExtrude(sketch=sketch, depth=p["beam_width"])
    del model.sketches["beam_profile"]

    column = model.Part(name="Concrete_Column", dimensionality=THREE_D, type=DEFORMABLE_BODY)
    sketch = model.ConstrainedSketch(name="column_profile", sheetSize=5000.0)
    sketch.rectangle(
        point1=(-p["column_depth"] / 2.0, -p["column_height"] / 2.0),
        point2=(p["column_depth"] / 2.0, p["column_height"] / 2.0),
    )
    column.BaseSolidExtrude(sketch=sketch, depth=p["column_width"])
    del model.sketches["column_profile"]
    return beam, column


def create_wire_polyline(model, name, points):
    part = model.Part(name=name, dimensionality=THREE_D, type=DEFORMABLE_BODY)
    for start, end in zip(points[:-1], points[1:]):
        part.WirePolyLine(points=((start, end),), mergeType=IMPRINT, meshable=ON)
    return part


def create_rebar_parts(model, p):
    cover = p["cover"]
    bw = p["beam_width"]
    bd = p["beam_depth"]
    cd = p["column_depth"]
    cw = p["column_width"]
    ch = p["column_height"]
    bl = p["beam_length"]
    beam_x0 = cd / 2.0
    beam_x1 = beam_x0 + bl
    beam_z0 = (cw - bw) / 2.0

    z_left = beam_z0 + cover
    z_right = beam_z0 + bw - cover
    top_y = bd / 2.0 - cover
    bottom_y = -bd / 2.0 + cover
    bar_x_start = -cd / 2.0 + cover
    bar_x_end = beam_x1 - cover

    rebar_parts = []

    top_zs = linear_positions(z_left, z_right, p["beam_top_bars"])
    bottom_zs = linear_positions(z_left, z_right, p["beam_bottom_bars"])

    for i, z in enumerate(top_zs):
        rebar_parts.append(create_wire_polyline(
            model, "Beam_Top_Bar_%d" % (i + 1), [(bar_x_start, top_y, z), (bar_x_end, top_y, z)]
        ))
    for i, z in enumerate(bottom_zs):
        rebar_parts.append(create_wire_polyline(
            model, "Beam_Bottom_Bar_%d" % (i + 1), [(bar_x_start, bottom_y, z), (bar_x_end, bottom_y, z)]
        ))

    col_y0 = -ch / 2.0 + cover
    col_y1 = ch / 2.0 - cover
    x_left = -cd / 2.0 + cover
    x_right = cd / 2.0 - cover
    col_zs = linear_positions(cover, cw - cover, p["column_bars_each_face"])

    for i, z in enumerate(col_zs):
        rebar_parts.append(create_wire_polyline(
            model, "Column_Left_Bar_%d" % (i + 1), [(x_left, col_y0, z), (x_left, col_y1, z)]
        ))
        rebar_parts.append(create_wire_polyline(
            model, "Column_Right_Bar_%d" % (i + 1), [(x_right, col_y0, z), (x_right, col_y1, z)]
        ))

    return rebar_parts


def create_stirrups(model, p):
    stirrups = []
    cover = p["cover"]
    beam_z0 = (p["column_width"] - p["beam_width"]) / 2.0
    stirrup_x0 = p["column_depth"] / 2.0 + cover
    stirrup_x1 = p["column_depth"] / 2.0 + p["beam_length"] - cover
    x = stirrup_x0
    index = 1
    while x <= stirrup_x1 + 1.0:
        y0 = -p["beam_depth"] / 2.0 + cover
        y1 = p["beam_depth"] / 2.0 - cover
        z0 = beam_z0 + cover
        z1 = beam_z0 + p["beam_width"] - cover
        pts = [(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1), (x, y0, z0)]
        stirrups.append(create_wire_polyline(model, "Beam_Stirrup_%03d" % index, pts))
        x += p["stirrup_spacing"]
        index += 1

    y = -p["column_height"] / 2.0 + cover
    index = 1
    while y <= p["column_height"] / 2.0 - cover + 1.0:
        x0 = -p["column_depth"] / 2.0 + cover
        x1 = p["column_depth"] / 2.0 - cover
        z0 = cover
        z1 = p["column_width"] - cover
        pts = [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), (x0, y, z0)]
        stirrups.append(create_wire_polyline(model, "Column_Tie_%03d" % index, pts))
        y += p["stirrup_spacing"]
        index += 1

    return stirrups


# ------------------------------- Materials -------------------------------- #

def create_materials(model, p):
    concrete = model.Material(name=abaqus_name("Concrete_CDP_fc_%s" % p["concrete_fc"]))
    concrete.Elastic(table=((concrete_elastic_modulus(p["concrete_fc"]), 0.20),))
    concrete.ConcreteDamagedPlasticity(table=((36.0, 0.10, 1.16, 0.667, 0.0005),))
    comp, ten, comp_dmg, ten_dmg = make_cdp_tables(p["concrete_fc"])
    concrete.concreteDamagedPlasticity.ConcreteCompressionHardening(table=comp)
    concrete.concreteDamagedPlasticity.ConcreteTensionStiffening(table=ten)
    concrete.concreteDamagedPlasticity.ConcreteCompressionDamage(table=comp_dmg)
    concrete.concreteDamagedPlasticity.ConcreteTensionDamage(table=ten_dmg)

    steel = model.Material(name=abaqus_name("Rebar_Steel_fy_%s" % p["steel_fy"]))
    steel.Elastic(table=((200000.0, 0.30),))
    steel.Plastic(table=((p["steel_fy"], 0.0), (1.10 * p["steel_fy"], 0.02), (1.18 * p["steel_fy"], 0.08)))

    model.HomogeneousSolidSection(name="Concrete_Section", material=concrete.name)
    model.TrussSection(name="Main_Rebar_Section", material=steel.name, area=bar_area(p["main_bar_dia"]))
    model.TrussSection(name="Stirrup_Section", material=steel.name, area=bar_area(p["stirrup_dia"]))


def assign_sections(beam, column, rebar_parts, stirrup_parts):
    beam.SectionAssignment(
        region=regionToolset.Region(cells=beam.cells[:]),
        sectionName="Concrete_Section",
    )
    column.SectionAssignment(
        region=regionToolset.Region(cells=column.cells[:]),
        sectionName="Concrete_Section",
    )
    for part in rebar_parts:
        part.SectionAssignment(region=regionToolset.Region(edges=part.edges[:]), sectionName="Main_Rebar_Section")
    for part in stirrup_parts:
        part.SectionAssignment(region=regionToolset.Region(edges=part.edges[:]), sectionName="Stirrup_Section")


# ---------------------------- Assembly/Analysis --------------------------- #

def create_assembly(model, beam, column, rebar_parts, stirrup_parts, p):
    assembly = model.rootAssembly
    assembly.DatumCsysByDefault(CARTESIAN)
    beam_i = assembly.Instance(name="Concrete_Beam", part=beam, dependent=ON)
    column_i = assembly.Instance(name="Concrete_Column", part=column, dependent=ON)
    beam_z_offset = (p["column_width"] - p["beam_width"]) / 2.0
    assembly.translate(instanceList=(beam_i.name,), vector=(0.0, 0.0, beam_z_offset))
    concrete_i = assembly.InstanceFromBooleanMerge(
        name="Concrete_Joint",
        instances=(beam_i, column_i),
        keepIntersections=OFF,
        originalInstances=SUPPRESS,
        domain=GEOMETRY,
    )
    embedded = []
    for part in rebar_parts + stirrup_parts:
        embedded.append(assembly.Instance(name=part.name, part=part, dependent=ON))
    return assembly, concrete_i, embedded


def partition_concrete_joint(concrete_part, p):
    """Partition the merged joint into sweepable brick-shaped regions."""
    beam_z0 = (p["column_width"] - p["beam_width"]) / 2.0
    beam_z1 = beam_z0 + p["beam_width"]
    beam_face_x = p["column_depth"] / 2.0
    joint_end_x = beam_face_x + p["column_depth"]

    planes = (
        ("Beam_Column_Interface", YZPLANE, beam_face_x),
        ("Joint_Refinement_End", YZPLANE, joint_end_x),
        ("Beam_Bottom", XZPLANE, -p["beam_depth"] / 2.0),
        ("Beam_Top", XZPLANE, p["beam_depth"] / 2.0),
        ("Beam_Side_1", XYPLANE, beam_z0),
        ("Beam_Side_2", XYPLANE, beam_z1),
    )

    for name, principal_plane, offset in planes:
        datum_feature = concrete_part.DatumPlaneByPrincipalPlane(
            principalPlane=principal_plane,
            offset=offset,
        )
        try:
            concrete_part.features.changeKey(fromName=datum_feature.name, toName=name)
        except Exception:
            pass
        concrete_part.PartitionCellByDatumPlane(
            datumPlane=concrete_part.datums[datum_feature.id],
            cells=concrete_part.cells[:],
        )

    print("Partitioned concrete joint into %d cells using datum planes." % len(concrete_part.cells))


def create_steps_and_outputs(model, p):
    model.StaticStep(
        name="Axial_Load",
        previous="Initial",
        nlgeom=ON,
        initialInc=0.02,
        minInc=1.0e-7,
        maxInc=0.05,
        maxNumInc=200,
    )
    model.StaticStep(
        name="Beam_Load",
        previous="Axial_Load",
        nlgeom=ON,
        initialInc=0.01,
        minInc=1.0e-7,
        maxInc=0.03,
        maxNumInc=600,
    )
    model.FieldOutputRequest(
        name="RC_Field_Output",
        createStepName="Axial_Load",
        variables=("S", "LE", "PE", "PEEQ", "U", "RF", "DAMAGET", "DAMAGEC"),
        frequency=1,
    )

    if p["load_protocol"].lower() == "cyclic":
        model.TabularAmplitude(
            name="Cyclic_Beam_Drift",
            timeSpan=STEP,
            smooth=SOLVER_DEFAULT,
            data=((0.0, 0.0), (0.15, 0.25), (0.30, -0.25), (0.45, 0.50),
                  (0.60, -0.50), (0.75, 0.75), (0.90, -0.75), (1.0, 1.0)),
        )
    else:
        model.SmoothStepAmplitude(name="Monotonic_Beam_Drift", timeSpan=STEP, data=((0.0, 0.0), (1.0, 1.0)))


def create_reference_points_and_constraints(model, assembly, concrete_instance_name, p):
    beam_tip_x = p["column_depth"] / 2.0 + p["beam_length"]
    beam_mid_z = p["column_width"] / 2.0
    beam_z0 = (p["column_width"] - p["beam_width"]) / 2.0
    beam_z1 = beam_z0 + p["beam_width"]
    tolerance = 1.0e-3
    beam_tip = assembly.ReferencePoint(point=(beam_tip_x, 0.0, beam_mid_z))
    col_top = assembly.ReferencePoint(point=(0.0, p["column_height"] / 2.0, p["column_width"] / 2.0))
    beam_rp = assembly.referencePoints[beam_tip.id]
    top_rp = assembly.referencePoints[col_top.id]
    assembly.Set(name="RP_BEAM_TIP", referencePoints=(beam_rp,))
    assembly.Set(name="RP_COLUMN_TOP", referencePoints=(top_rp,))

    concrete_inst = assembly.instances[concrete_instance_name]
    beam_face = concrete_inst.faces.getByBoundingBox(
        xMin=beam_tip_x - tolerance,
        xMax=beam_tip_x + tolerance,
        yMin=-p["beam_depth"] / 2.0 - tolerance,
        yMax=p["beam_depth"] / 2.0 + tolerance,
        zMin=beam_z0 - tolerance,
        zMax=beam_z1 + tolerance,
    )
    col_top_face = concrete_inst.faces.getByBoundingBox(
        xMin=-p["column_depth"] / 2.0 - tolerance,
        xMax=p["column_depth"] / 2.0 + tolerance,
        yMin=p["column_height"] / 2.0 - tolerance,
        yMax=p["column_height"] / 2.0 + tolerance,
        zMin=-tolerance,
        zMax=p["column_width"] + tolerance,
    )
    assembly.Set(name="BEAM_TIP_FACE", faces=beam_face)
    assembly.Set(name="COLUMN_TOP_FACE", faces=col_top_face)
    model.Coupling(
        name="Couple_Beam_Tip",
        controlPoint=assembly.sets["RP_BEAM_TIP"],
        surface=regionToolset.Region(side1Faces=beam_face),
        influenceRadius=WHOLE_SURFACE,
        couplingType=KINEMATIC,
        localCsys=None,
        u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON,
    )
    model.Coupling(
        name="Couple_Column_Top",
        controlPoint=assembly.sets["RP_COLUMN_TOP"],
        surface=regionToolset.Region(side1Faces=col_top_face),
        influenceRadius=WHOLE_SURFACE,
        couplingType=KINEMATIC,
        localCsys=None,
        u1=ON, u2=ON, u3=ON, ur1=ON, ur2=ON, ur3=ON,
    )
    model.HistoryOutputRequest(
        name="Beam_End_History",
        createStepName="Beam_Load",
        variables=("U2", "RF2"),
        region=assembly.sets["RP_BEAM_TIP"],
        frequency=1,
    )


def create_embedded_constraints(model, assembly, concrete_instance_name):
    concrete_inst = assembly.instances[concrete_instance_name]
    concrete_region = regionToolset.Region(cells=concrete_inst.cells[:])
    for inst_name, inst in assembly.instances.items():
        if inst_name.startswith("Beam_") or inst_name.startswith("Column_"):
            model.EmbeddedRegion(
                name="Embed_%s" % inst_name,
                embeddedRegion=regionToolset.Region(edges=inst.edges[:]),
                hostRegion=concrete_region,
                weightFactorTolerance=1.0e-6,
                absoluteTolerance=0.0,
                fractionalTolerance=0.05,
                toleranceMethod=BOTH,
            )


def create_loads_and_bcs(model, assembly, concrete_instance_name, p):
    concrete_inst = assembly.instances[concrete_instance_name]
    tolerance = 1.0e-3
    bottom_face = concrete_inst.faces.getByBoundingBox(
        xMin=-p["column_depth"] / 2.0 - tolerance,
        xMax=p["column_depth"] / 2.0 + tolerance,
        yMin=-p["column_height"] / 2.0 - tolerance,
        yMax=-p["column_height"] / 2.0 + tolerance,
        zMin=-tolerance,
        zMax=p["column_width"] + tolerance,
    )
    assembly.Set(name="COLUMN_BASE", faces=bottom_face)
    model.EncastreBC(name="Fixed_Column_Base", createStepName="Initial", region=assembly.sets["COLUMN_BASE"])

    area = p["column_depth"] * p["column_width"]
    axial_capacity = 0.85 * p["concrete_fc"] * area
    axial_load = -p["axial_load_ratio"] * axial_capacity
    model.ConcentratedForce(
        name="Column_Axial_Load",
        createStepName="Axial_Load",
        region=assembly.sets["RP_COLUMN_TOP"],
        cf2=axial_load,
    )
    model.DisplacementBC(
        name="Column_Top_Lateral_Restraint",
        createStepName="Initial",
        region=assembly.sets["RP_COLUMN_TOP"],
        u1=0.0,
        u3=0.0,
        ur1=0.0,
        ur2=0.0,
        ur3=0.0,
    )

    target_disp = p["beam_drift_ratio"] * p["beam_length"]
    amp = "Cyclic_Beam_Drift" if p["load_protocol"].lower() == "cyclic" else "Monotonic_Beam_Drift"
    model.DisplacementBC(
        name="Beam_Tip_Displacement",
        createStepName="Beam_Load",
        region=assembly.sets["RP_BEAM_TIP"],
        u1=UNSET,
        u2=target_disp,
        u3=0.0,
        ur1=UNSET,
        ur2=UNSET,
        ur3=UNSET,
        amplitude=amp,
    )
    print(
        "Applied loads: %.1f kN column axial load in Axial_Load; %.1f mm beam-tip displacement in Beam_Load."
        % (abs(axial_load) / 1000.0, target_disp)
    )


def mesh_parts(concrete_part, rebar_parts, stirrup_parts, p):
    concrete_part.seedPart(size=p["mesh_size"], deviationFactor=0.1, minSizeFactor=0.1)

    beam_z0 = (p["column_width"] - p["beam_width"]) / 2.0
    beam_z1 = beam_z0 + p["beam_width"]
    joint_edges = concrete_part.edges.getByBoundingBox(
        xMin=-p["column_depth"] / 2.0 - 1.0,
        xMax=p["column_depth"] / 2.0 + p["column_depth"] + 1.0,
        yMin=-p["beam_depth"] / 2.0 - 1.0,
        yMax=p["beam_depth"] / 2.0 + 1.0,
        zMin=beam_z0 - 1.0,
        zMax=beam_z1 + 1.0,
    )
    if len(joint_edges):
        concrete_part.seedEdgeBySize(
            edges=joint_edges,
            size=p["joint_mesh_size"],
            deviationFactor=0.1,
            minSizeFactor=0.1,
            constraint=FINER,
        )

    concrete_part.setMeshControls(
        regions=concrete_part.cells[:],
        elemShape=HEX,
        technique=STRUCTURED,
    )
    concrete_part.setElementType(
        regions=(concrete_part.cells[:],),
        elemTypes=(
            mesh.ElemType(elemCode=C3D8R, elemLibrary=STANDARD),
            mesh.ElemType(elemCode=C3D6, elemLibrary=STANDARD),
            mesh.ElemType(elemCode=C3D4, elemLibrary=STANDARD),
        ),
    )
    concrete_part.generateMesh()
    print(
        "Generated structured concrete mesh: %d nodes, %d elements; joint target size %.1f mm."
        % (len(concrete_part.nodes), len(concrete_part.elements), p["joint_mesh_size"])
    )

    for part in rebar_parts + stirrup_parts:
        part.seedPart(size=p["mesh_size"], deviationFactor=0.1, minSizeFactor=0.1)
        part.setElementType(regions=(part.edges[:],), elemTypes=(mesh.ElemType(elemCode=T3D2, elemLibrary=STANDARD),))
        part.generateMesh()


def build_model(p):
    model_name = abaqus_name(p["model_name"] + "_" + p["case"])
    delete_model_if_present(model_name)
    model = mdb.Model(name=model_name)

    create_materials(model, p)
    beam, column = create_concrete_parts(model, p)
    rebar_parts = create_rebar_parts(model, p)
    stirrup_parts = create_stirrups(model, p)
    assign_sections(beam, column, rebar_parts, stirrup_parts)
    assembly, concrete_i, embedded = create_assembly(model, beam, column, rebar_parts, stirrup_parts, p)
    concrete_part = model.parts["Concrete_Joint"]
    partition_concrete_joint(concrete_part, p)
    concrete_part.SectionAssignment(
        region=regionToolset.Region(cells=concrete_part.cells[:]),
        sectionName="Concrete_Section",
    )
    mesh_parts(concrete_part, rebar_parts, stirrup_parts, p)
    create_steps_and_outputs(model, p)
    create_reference_points_and_constraints(model, assembly, concrete_i.name, p)
    create_embedded_constraints(model, assembly, concrete_i.name)
    create_loads_and_bcs(model, assembly, concrete_i.name, p)
    return model


# ---------------------------- Result Extraction --------------------------- #

def xy_from_history(odb, set_name, step_name):
    step = odb.steps[step_name]
    rp_key = None
    for key in step.historyRegions.keys():
        if set_name in key:
            rp_key = key
            break
    if rp_key is None:
        for key, region in step.historyRegions.items():
            output_names = list(region.historyOutputs.keys())
            if "U2" in output_names and "RF2" in output_names:
                rp_key = key
                break
    if rp_key is None:
        return [], []
    region = step.historyRegions[rp_key]
    disp = region.historyOutputs["U2"].data
    force = region.historyOutputs["RF2"].data
    return disp, force


def max_field_value(frame, variable):
    if variable not in frame.fieldOutputs:
        return None
    values = frame.fieldOutputs[variable].values
    if not values:
        return None
    numeric_values = []
    for value in values:
        data = getattr(value, "mises", None)
        if data is None:
            data = value.data
        if data is None:
            continue
        if isinstance(data, (tuple, list)):
            numeric_values.extend([component for component in data if component is not None])
        else:
            numeric_values.append(data)
    if not numeric_values:
        return None
    return max(numeric_values)


def maximum_field_entry(frame, variable, include_instance=None, exclude_instance=None):
    if variable not in frame.fieldOutputs:
        return None, None
    best_value = None
    best_entry = None
    include_text = include_instance.upper() if include_instance else None
    exclude_text = exclude_instance.upper() if exclude_instance else None
    for entry in frame.fieldOutputs[variable].values:
        instance_name = getattr(getattr(entry, "instance", None), "name", "")
        upper_name = instance_name.upper()
        if include_text and include_text not in upper_name:
            continue
        if exclude_text and exclude_text in upper_name:
            continue
        data = getattr(entry, "mises", None)
        if data is None:
            data = entry.data
        if data is None:
            continue
        if isinstance(data, (tuple, list)):
            candidates = [abs(component) for component in data if component is not None]
            if not candidates:
                continue
            scalar = max(candidates)
        else:
            scalar = float(data)
        if best_value is None or scalar > best_value:
            best_value = scalar
            best_entry = entry
    return best_value, best_entry


def nearest_history_value(history, target_time):
    if not history:
        return None
    return min(history, key=lambda row: abs(row[0] - target_time))[1]


def field_entry_centroid(entry):
    try:
        instance = entry.instance
        if hasattr(instance, "getElementFromLabel"):
            element = instance.getElementFromLabel(entry.elementLabel)
        else:
            element = next(item for item in instance.elements if item.label == entry.elementLabel)
        node_lookup = dict((node.label, node) for node in instance.nodes)
        coordinates = [node_lookup[label].coordinates for label in element.connectivity]
        count = float(len(coordinates))
        return tuple(sum(point[i] for point in coordinates) / count for i in range(3))
    except Exception:
        return (None, None, None)


def first_tensile_damage_event(step, displacement_history, force_history, threshold):
    for frame in step.frames:
        damage, entry = maximum_field_entry(frame, "DAMAGET")
        if damage is None or damage < threshold:
            continue
        location = field_entry_centroid(entry)
        return {
            "time": frame.frameValue,
            "damage": damage,
            "displacement": nearest_history_value(displacement_history, frame.frameValue),
            "load": nearest_history_value(force_history, frame.frameValue),
            "instance": getattr(getattr(entry, "instance", None), "name", ""),
            "element": getattr(entry, "elementLabel", ""),
            "x": location[0],
            "y": location[1],
            "z": location[2],
        }
    return None


def extract_results(job_name, case_name, output_dir, p):
    odb_path = job_name + ".odb"
    if not os.path.exists(odb_path):
        print("ODB not found for %s; skipping extraction." % job_name)
        return None

    odb = openOdb(odb_path, readOnly=True)
    disp, force = xy_from_history(odb, "RP_BEAM_TIP", "Beam_Load")
    curve_path = os.path.join(output_dir, "%s_load_displacement.csv" % case_name)
    with open_csv_for_write(curve_path) as f:
        writer = csv.writer(f)
        writer.writerow(["time", "beam_tip_displacement_mm", "beam_reaction_n"])
        for (td, ud), (tf, rf) in zip(disp, force):
            writer.writerow([td, ud, rf])

    max_load = max([abs(row[1]) for row in force]) if force else 0.0
    max_disp = max([abs(row[1]) for row in disp]) if disp else 0.0
    initial_stiffness = ""
    secant_stiffness = ""
    initial_u = disp[0][1] if disp else 0.0
    initial_force = force[0][1] if force else 0.0
    for index in range(min(len(disp), len(force))):
        relative_u = disp[index][1] - initial_u
        relative_force = force[index][1] - initial_force
        if max_load > 0.0 and abs(relative_force) >= 0.10 * max_load and abs(relative_u) > 1.0e-9:
            initial_stiffness = abs(relative_force / relative_u)
            break
    if disp and force:
        final_relative_u = disp[-1][1] - initial_u
        final_relative_force = force[-1][1] - initial_force
        if abs(final_relative_u) > 1.0e-9:
            secant_stiffness = abs(final_relative_force / final_relative_u)

    beam_step = odb.steps["Beam_Load"]
    first_damage = first_tensile_damage_event(
        beam_step,
        disp,
        force,
        p["damage_onset_threshold"] if "damage_onset_threshold" in p else 0.01,
    )
    last_frame = beam_step.frames[-1]
    max_tension_damage = max_field_value(last_frame, "DAMAGET")
    max_compression_damage = max_field_value(last_frame, "DAMAGEC")
    max_steel_stress, max_steel_entry = maximum_field_entry(
        last_frame,
        "S",
        exclude_instance="CONCRETE_JOINT",
    )

    final_load = abs(force[-1][1]) if force else 0.0
    strength_retention = final_load / max_load if max_load > 1.0e-9 else 0.0
    failure_mode = "Flexural response with distributed cracking"
    if max_steel_stress is not None and max_steel_stress >= p["steel_fy"]:
        failure_mode = "Reinforcement yielding with distributed concrete damage"
    if max_tension_damage is not None and max_tension_damage > 0.85:
        failure_mode = "Reinforcement yielding with severe localized tensile damage"
    if max_compression_damage is not None and max_compression_damage > 0.70:
        if strength_retention >= 0.85:
            failure_mode = "Localized concrete crushing risk with global capacity retained"
        else:
            failure_mode = "Concrete crushing with significant global strength loss"

    if first_damage:
        print(
            "First tensile damage for %s: DAMAGET=%.4f at U2=%s mm, RF2=%s N, element %s, "
            "location=(%s, %s, %s) mm."
            % (
                case_name,
                first_damage["damage"],
                first_damage["displacement"],
                first_damage["load"],
                first_damage["element"],
                first_damage["x"],
                first_damage["y"],
                first_damage["z"],
            )
        )

    odb.close()
    return {
        "case": case_name,
        "max_load_n": max_load,
        "max_displacement_mm": max_disp,
        "initial_stiffness_n_per_mm": initial_stiffness,
        "secant_stiffness_n_per_mm": secant_stiffness,
        "max_tension_damage": max_tension_damage,
        "max_compression_damage": max_compression_damage,
        "max_rebar_stress_mpa": max_steel_stress,
        "first_damage_time": first_damage["time"] if first_damage else "",
        "first_damage_load_n": first_damage["load"] if first_damage else "",
        "first_damage_displacement_mm": first_damage["displacement"] if first_damage else "",
        "first_damage_value": first_damage["damage"] if first_damage else "",
        "first_damage_instance": first_damage["instance"] if first_damage else "",
        "first_damage_element": first_damage["element"] if first_damage else "",
        "first_damage_x_mm": first_damage["x"] if first_damage else "",
        "first_damage_y_mm": first_damage["y"] if first_damage else "",
        "first_damage_z_mm": first_damage["z"] if first_damage else "",
        "failure_mode": failure_mode,
        "curve_file": curve_path,
    }


def write_summary(results, output_dir):
    path = os.path.join(output_dir, "parametric_summary.csv")
    fields = [
        "case",
        "max_load_n",
        "max_displacement_mm",
        "initial_stiffness_n_per_mm",
        "secant_stiffness_n_per_mm",
        "max_tension_damage",
        "max_compression_damage",
        "max_rebar_stress_mpa",
        "first_damage_time",
        "first_damage_load_n",
        "first_damage_displacement_mm",
        "first_damage_value",
        "first_damage_instance",
        "first_damage_element",
        "first_damage_x_mm",
        "first_damage_y_mm",
        "first_damage_z_mm",
        "failure_mode",
        "curve_file",
    ]
    with open_csv_for_write(path) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print("Wrote summary: %s" % path)


# --------------------------------- Main ----------------------------------- #

def show_model_for_review(model, p):
    try:
        model.rootAssembly.regenerate()
        viewport_name = session.currentViewportName
        viewport = session.viewports[viewport_name]
        viewport.setValues(displayedObject=model.rootAssembly)
        try:
            viewport.view.setValues(session.views["Iso"])
            viewport.view.setProjection(projection=PARALLEL)
            viewport.view.fitView()
        except Exception as view_err:
            print("Automatic isometric view skipped: %s" % view_err)

        beam_z0 = (p["column_width"] - p["beam_width"]) / 2.0
        beam_z1 = beam_z0 + p["beam_width"]
        print(
            "Beam centering check: beam Z = %.1f to %.1f mm; column Z = 0.0 to %.1f mm; "
            "side offset = %.1f mm"
            % (beam_z0, beam_z1, p["column_width"], beam_z0)
        )
        print("Displayed model for review: %s" % model.name)
    except Exception as err:
        print("Viewport display skipped: %s" % err)


def run_study():
    os.chdir(SCRIPT_DIR)
    if os.environ.get("RC_JOINT_BUILD_ONLY", "").lower() in ("1", "true", "yes"):
        RUN_SETTINGS["submit_jobs"] = False
        RUN_SETTINGS["extract_results"] = False
        print("RC_JOINT_BUILD_ONLY enabled: model will be built without job submission.")
    output_dir = os.path.join(SCRIPT_DIR, "rc_joint_results")
    safe_mkdir(output_dir)
    summaries = []
    built_models = []
    existing_model_names = list(mdb.models.keys())
    if "Model-1" in existing_model_names:
        try:
            if len(mdb.models["Model-1"].parts) == 0:
                delete_model_if_present("Model-1")
        except Exception as err:
            print("Model-1 cleanup skipped: %s" % err)
    if RUN_SETTINGS["clear_previous_generated_models"]:
        for model_name in list(mdb.models.keys()):
            if model_name.startswith(abaqus_name(BASE["model_name"] + "_")):
                delete_model_if_present(model_name)
        for job_name in list(mdb.jobs.keys()):
            if job_name.startswith("Job_"):
                delete_job_if_present(job_name)

    cases = PARAMETRIC_CASES if RUN_SETTINGS["build_all_parametric_cases"] else [{"case": "Base_Review"}]

    for overrides in cases:
        p = update_case(BASE, overrides)
        model = build_model(p)
        built_models.append(model)
        job_name = abaqus_name("Job_%s" % p["case"])
        if job_name in mdb.jobs:
            del mdb.jobs[job_name]
        mdb.Job(
            name=job_name,
            model=model.name,
            description="Nonlinear RC beam-column joint model: %s" % p["case"],
            type=ANALYSIS,
            numCpus=p["cpus"],
            numDomains=p["cpus"],
            multiprocessingMode=DEFAULT,
        )
        print("Built model %s and created job %s" % (model.name, job_name))

        if RUN_SETTINGS["submit_jobs"]:
            print("Submitting %s" % job_name)
            mdb.jobs[job_name].submit(consistencyChecking=OFF)
            mdb.jobs[job_name].waitForCompletion()
            if RUN_SETTINGS["extract_results"]:
                summary = extract_results(job_name, p["case"], output_dir, p)
                if summary is not None:
                    summaries.append(summary)
        elif RUN_SETTINGS["extract_results"]:
            summary = extract_results(job_name, p["case"], output_dir, p)
            if summary is not None:
                summaries.append(summary)

    if summaries:
        write_summary(summaries, output_dir)
    else:
        print("No jobs were submitted or extracted. Models are ready for manual review.")

    if built_models:
        show_model_for_review(built_models[0], update_case(BASE, cases[0]))

    if RUN_SETTINGS["save_cae"]:
        cae_path = os.path.join(SCRIPT_DIR, RUN_SETTINGS["cae_file"])
        mdb.saveAs(pathName=cae_path)
        print("Saved Abaqus CAE database: %s" % cae_path)


if __name__ == "__main__":
    run_study()
