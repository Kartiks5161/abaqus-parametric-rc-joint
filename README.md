# Nonlinear RC Beam-Column Joint Modelling in Abaqus

This project presents an automated finite-element workflow for nonlinear analysis of a reinforced-concrete beam-column joint using the Abaqus Python API. The workflow generates the model, assigns nonlinear material behaviour, applies boundary conditions and loading, executes nonlinear analyses, and extracts engineering results. A selected four-case parameter study is included for stirrup spacing and concrete-strength comparison.

## Why This Project Matters

Reinforced-concrete beam-column joints are critical regions in moment-resisting frames because they transfer high shear, bond, and confinement demands between beams and columns. Manual nonlinear modelling in Abaqus is time-consuming and difficult to reproduce, so this project focuses on automation, selected parameter comparison, and engineering interpretation.

## What The Script Builds

The Abaqus script automatically creates:

- Concrete beam and column solid geometry
- Longitudinal beam reinforcement
- Longitudinal column reinforcement
- Beam stirrups and column ties
- Embedded reinforcement constraints
- Concrete damaged plasticity material model
- Steel elastic-plastic reinforcement model
- Column-base fixity
- Axial load on the column
- Monotonic or cyclic beam-tip displacement loading
- Datum-plane partitions around the joint
- Locally refined structured `C3D8R` concrete mesh and `T3D2` reinforcement mesh
- Job creation, submission, and completion monitoring
- Automated extraction of load-displacement and damage results

## Parameter Study

By default, the main script builds and runs **one baseline model** so its modelling assumptions and convergence can be validated safely. The repository also includes a full-batch runner used to execute the selected parameter cases.

The completed selected cases compare:

- Stirrup spacing: 75 mm, 100 mm, 150 mm
- Concrete compressive strength: 35 MPa and 45 MPa

The same framework can also be extended to vary:

- Reinforcement ratio
- Beam-column size ratio
- Column axial load ratio
- Joint confinement
- Loading protocol

## Extracted Outputs

After jobs are run and result extraction is enabled, the script exports:

- Beam-tip load-displacement curve
- Maximum load
- Maximum displacement
- Initial stiffness, calculated as the secant slope to the first response point reaching 10% of peak load
- Secant stiffness
- Tensile concrete damage
- Compressive concrete damage
- Maximum reinforcement stress in the final analysis frame
- First tensile-damage load, displacement, element, and approximate coordinates
- Rule-based response-mode indicator

Results are written to:

```text
rc_joint_results/
```

with one load-displacement CSV per case and a combined:

```text
parametric_summary.csv
```

The full parameter batch and `abaqus_extract_all_existing.py` write the combined four-case summary. Running the default baseline workflow writes a one-row baseline summary to the same filename, so rerun the all-existing-results extractor if you need to restore the combined four-case file afterward.

For GitHub, the repository is intended to contain the automation scripts, documentation, result summaries, and selected images. Large Abaqus files such as `.odb`, `.cae`, `.dat`, `.msg`, and `.sta` outputs should be kept locally or shared separately through release assets because they can become very large.

## How To Run

### Requirements And Units

- Abaqus/CAE with Abaqus/Standard and its bundled Python environment
- A consistent `N-mm-MPa` unit system throughout the model
- Sufficient local storage for Abaqus output databases, which can each require several hundred megabytes

The result files and contour images included here were generated with Abaqus/Standard 2026. The concrete damaged plasticity tables in the script are transparent baseline assumptions; they should be calibrated against appropriate experimental data before the model is used for design decisions or research conclusions.

The default workflow automatically builds, submits, and extracts results for one baseline model. This keeps ordinary reruns manageable and avoids accidentally launching all nonlinear cases.

Open a terminal in this folder and run the script through Abaqus/CAE:

```bash
abaqus cae script=abaqus_rc_joint_parametric.py
```

This creates the concrete joint, reinforcement, embedded constraints, material definitions, mesh, steps, loads, boundary conditions, and job definition. It then submits the baseline job, waits for completion, and extracts the available results.

The default review model is an exterior beam-column joint: the beam is attached at the column face, centered vertically at the joint, and centered through the column width.

The script also saves an Abaqus database:

```text
rc_joint_parametric_models.cae
```

You can use the Abaqus/CAE Job Monitor to follow the nonlinear analysis while it runs.

For unattended baseline execution without opening the full GUI, use:

```bash
abaqus cae noGUI=abaqus_rc_joint_parametric.py
```

To run the completed selected parameter batch directly, use:

```bash
abaqus cae noGUI=abaqus_run_full_parametric.py
```

The repository also includes:

```text
abaqus_run_s100_fc45.py
abaqus_extract_all_existing.py
```

These helper scripts were used to rerun the high-strength case after CDP table correction and regenerate the combined result summary from completed ODB files.

Alternatively, enable the full parameterized batch in the main script by changing `build_all_parametric_cases` to `True` near the top of the script:

```python
RUN_SETTINGS = {
    "clear_previous_generated_models": True,
    "build_all_parametric_cases": True,
    "submit_jobs": True,
    "extract_results": True,
    "save_cae": True,
    "cae_file": "rc_joint_parametric_models.cae",
}
```

The script is intended for the Abaqus/CAE Python environment because it imports Abaqus-specific modules such as `abaqus`, `abaqusConstants`, `mesh`, and `odbAccess`.

## Loads And Damage Review

The analysis uses two sequential nonlinear static steps:

- `Axial_Load` applies the column axial force at `RP_COLUMN_TOP` while the column base is fixed.
- `Beam_Load` retains the axial force and applies the prescribed vertical displacement at `RP_BEAM_TIP`.

To inspect analysis results, open `Job_Base_Review.odb` in the Visualization module. Do not select a boundary-condition variable from the `.cae` model database for a contour plot.

For concrete tensile damage, choose field output `DAMAGET` at the integration points. A value of `0` is undamaged and a value approaching `1` indicates severe tensile stiffness degradation. Animate the frames to see where damage starts and how it spreads. Use `DAMAGEC` for compressive stiffness degradation and `S, Mises` on the reinforcement display group for steel stress.

The generated `parametric_summary.csv` contains the completed selected cases. It reports the first frame where `DAMAGET` reaches the configured `damage_onset_threshold`, together with beam-tip reaction, displacement, element label, and approximate element-centroid coordinates.

The reported response mode is assigned automatically from reinforcement stress, final-frame concrete damage, and global strength-retention thresholds. It is an engineering screening indicator rather than a formally validated failure-mode classification.

## Baseline Damage Results

### Compressive Damage

![Final concrete compression damage](docs/images/damagec_final.png)

Compressive damage concentrates in the joint panel and at the beam-column interface. The maximum `DAMAGEC` value reaches `0.90`, indicating severe localized compressive stiffness degradation and possible concrete crushing risk at the final `3.5%` drift level. Confirmation of crushing requires review of the corresponding concrete stresses and strains. The model nevertheless retains approximately `99.5%` of its peak global resistance at the final frame.

### Tensile Damage

![Final concrete tensile damage](docs/images/damaget_final.png)

Tensile damage spreads from the joint panel into the beam. The maximum `DAMAGET` value reaches `0.95`, indicating severe localized cracking and substantial stiffness degradation. Damage near the column ends should be interpreted cautiously because local concentrations can be influenced by the coupling and support boundary conditions.

## Engineering Interpretation

The baseline model reached the prescribed `84 mm` beam-tip displacement (`3.5%` drift) and produced the following response:

- First tensile damage at approximately `8.56 kN` and `0.57 mm` beam-tip displacement
- Peak lateral resistance of `80.74 kN` at approximately `78.87 mm`
- Final resistance of `80.34 kN`, retaining approximately `99.5%` of peak load
- Maximum final-frame reinforcement stress of approximately `537 MPa`, exceeding the `500 MPa` yield strength
- Maximum tensile and compressive damage values of `0.95` and `0.90`, respectively

These baseline results indicate reinforcement yielding, substantial stiffness degradation, and localized concrete damage while the joint retains most of its peak global resistance at the target drift. The selected parameter cases show the following model trends:

- Reducing stirrup spacing from 150 mm to 75 mm slightly increases peak lateral resistance and secant stiffness in the generated model.
- Increasing concrete strength from 35 MPa to 45 MPa increases initial stiffness and peak lateral resistance in the generated model.
- Higher reinforcement stress near the beam-column interface is consistent with flexural yielding. Because the reinforcement is embedded in the concrete with a perfect-bond constraint, this model does not simulate bond slip or bond failure.
- Concentrated tensile damage in the joint panel is consistent with joint-region cracking, while high compressive damage near the compression zone suggests crushing risk. These interpretations should be confirmed using stress, strain, deformation, and damage histories and, where possible, experimental validation.

## Repository Contents

- `abaqus_rc_joint_parametric.py` - main Abaqus modelling, analysis, and result-extraction script
- `abaqus_run_full_parametric.py` - runner for the completed selected parameter cases
- `abaqus_extract_all_existing.py` - extracts summaries from completed Abaqus result databases
- `abaqus_run_s100_fc45.py` - helper runner used for the high-strength concrete case
- `abaqus_build_check.py` - quick model-build check script
- `rc_joint_results/parametric_summary.csv` - combined extracted result summary
- `docs/images/` - selected result images used in this README
- `README.md` - project explanation and usage guide
