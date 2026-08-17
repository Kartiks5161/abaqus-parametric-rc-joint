"""Extract summaries from all completed RC joint ODB files without rerunning jobs."""

import os

import abaqus_rc_joint_parametric as study


cases = [
    ("Job_S75_FC35", study.update_case(study.BASE, {"case": "S75_FC35", "stirrup_spacing": 75.0, "concrete_fc": 35.0})),
    ("Job_S100_FC35", study.update_case(study.BASE, {"case": "S100_FC35", "stirrup_spacing": 100.0, "concrete_fc": 35.0})),
    ("Job_S150_FC35", study.update_case(study.BASE, {"case": "S150_FC35", "stirrup_spacing": 150.0, "concrete_fc": 35.0})),
    ("Job_S100_FC45", study.update_case(study.BASE, {"case": "S100_FC45", "stirrup_spacing": 100.0, "concrete_fc": 45.0})),
]

odb_directory = study.SCRIPT_DIR
os.chdir(odb_directory)
output_directory = os.path.join(odb_directory, "rc_joint_results")
study.safe_mkdir(output_directory)

summaries = []
for job_name, parameters in cases:
    odb_path = os.path.join(odb_directory, job_name + ".odb")
    if not os.path.exists(odb_path):
        print("Skipping missing ODB: %s" % odb_path)
        continue
    summary = study.extract_results(job_name, parameters["case"], output_directory, parameters)
    if summary is not None:
        summaries.append(summary)

study.write_summary(summaries, output_directory)
print("Wrote combined summary for %d completed cases." % len(summaries))
