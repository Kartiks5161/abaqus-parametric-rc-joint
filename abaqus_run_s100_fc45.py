"""Run only the S100_FC45 RC joint case in Abaqus/CAE noGUI mode."""

import abaqus_rc_joint_parametric as study


study.PARAMETRIC_CASES[:] = [
    {"case": "S100_FC45", "stirrup_spacing": 100.0, "concrete_fc": 45.0},
]
study.RUN_SETTINGS["build_all_parametric_cases"] = True
study.RUN_SETTINGS["clear_previous_generated_models"] = False
study.RUN_SETTINGS["submit_jobs"] = True
study.RUN_SETTINGS["extract_results"] = True
study.RUN_SETTINGS["save_cae"] = True

study.run_study()
