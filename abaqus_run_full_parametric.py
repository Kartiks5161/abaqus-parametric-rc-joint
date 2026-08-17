"""Run all defined RC joint parametric cases in Abaqus/CAE noGUI mode."""

import abaqus_rc_joint_parametric as study


study.RUN_SETTINGS["build_all_parametric_cases"] = True
study.RUN_SETTINGS["submit_jobs"] = True
study.RUN_SETTINGS["extract_results"] = True
study.RUN_SETTINGS["save_cae"] = True

study.run_study()
