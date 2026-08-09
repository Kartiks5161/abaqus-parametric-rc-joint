"""Build and mesh the baseline model without submitting an analysis job."""

import abaqus_rc_joint_parametric as study


study.RUN_SETTINGS["build_all_parametric_cases"] = False
study.RUN_SETTINGS["submit_jobs"] = False
study.RUN_SETTINGS["extract_results"] = False
study.RUN_SETTINGS["save_cae"] = False

study.run_study()
