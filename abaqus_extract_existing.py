"""Re-extract baseline results from an existing ODB without rerunning the job."""

import os

import abaqus_rc_joint_parametric as study


job_name = "Job_Base_Review"
candidates = (
    study.SCRIPT_DIR,
    os.path.expanduser("~"),
)
odb_directory = None
for directory in candidates:
    if os.path.exists(os.path.join(directory, job_name + ".odb")):
        odb_directory = directory
        break

if odb_directory is None:
    raise RuntimeError("Could not find %s.odb in the project folder or user folder." % job_name)

os.chdir(odb_directory)
output_directory = os.path.join(odb_directory, "rc_joint_results")
study.safe_mkdir(output_directory)
parameters = study.update_case(study.BASE, {"case": "Base_Review"})
summary = study.extract_results(job_name, "Base_Review", output_directory, parameters)
if summary is not None:
    study.write_summary([summary], output_directory)
