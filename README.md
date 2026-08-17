# Automated 2D RC Frame Analysis & Preliminary Design

A Python-based desktop tool for generating, analysing, visualising, and preliminarily checking a 2D multi-storey reinforced-concrete building frame.

The project demonstrates the matrix stiffness method, structural modelling, load application, member-force recovery, IS-code-aware preliminary checks, and automated reporting.

Technology used: Python, NumPy, Tkinter, Pillow (PIL), ReportLab, and OpenPyXL.

## Sample Outputs

Undeformed frame:

![Undeformed frame](docs/sample_undeformed_frame.png)

Deformed shape:

![Deformed shape](docs/sample_deformed_shape.png)

Beam shear force diagram:

![Beam SFD](docs/sample_beam_sfd.png)

Beam bending moment diagram:

![Beam BMD](docs/sample_beam_bmd.png)

## What The Tool Does

- Generates a 2D RC frame from user inputs
- Assembles the global stiffness matrix
- Applies gravity and lateral loads
- Solves nodal displacements
- Calculates support reactions
- Calculates beam shear forces and bending moments
- Calculates column axial forces
- Draws undeformed and deformed frame plots
- Produces paginated SFD and BMD plots
- Evaluates IS-style strength load combinations
- Reports governing design envelopes
- Performs preliminary member checks
- Estimates preliminary beam steel and column minimum steel
- Runs benchmark validation checks
- Creates PDF and Excel reports
- Stores every analysis in a separate dated run folder

## Inputs

- Number of storeys and bays
- Bay width and storey height
- Beam and column dimensions
- Concrete grade
- Steel grade
- Dead load and live load
- Seismic zone or manual lateral load
- Support condition

## How To Run

Install dependencies once:

```powershell
python -m pip install -r requirements.txt
```

Open the desktop GUI:

```powershell
python project_1.py --gui
```

Run the built-in demo:

```powershell
python project_1.py --demo
```

## Output Filing System

Each analysis creates its own folder inside `outputs/`, for example:

```text
outputs/
  20260809_163506_10storey_5bay_zoneIII_fixed/
    run_summary.txt
    plots/
      undeformed_frame.png
      deformed_shape.png
      beam_sfd_page_01.png
      beam_bmd_page_01.png
    reports/
      rc_frame_analysis_report.pdf
      rc_frame_analysis_report.xlsx
```

This makes it easy to compare multiple structural models without overwriting reports.

## Validation Checks

The report includes verification checks for:

- Horizontal force equilibrium
- Vertical force equilibrium
- Global moment equilibrium
- Free-joint stiffness equation residual
- Base shear distribution

The verification section reports applied loads, support reactions, residuals, and percentage error. Very small residuals, such as `1e-12`, are expected because of floating-point numerical precision.

## Load Combinations

The tool uses the service case `DL + LL + EQ` for frame visualisation and service-level displacement plots.

For preliminary strength checks, it creates a design envelope from:

- `1.5(DL + LL)`
- `1.2(DL + LL + EQ)`
- `1.2(DL + LL - EQ)`
- `1.5(DL + EQ)`
- `1.5(DL - EQ)`
- `0.9DL + 1.5EQ`
- `0.9DL - 1.5EQ`

The report identifies the governing combination for beam bending, beam shear, column axial force, and lateral displacement.

## Benchmark Checks

The generated report includes simple validation checks:

- Fixed-end beam under UDL compared with `V = wL/2` and `M = wL^2/12`
- Seismic storey forces summed back to base shear
- Stiffness trend check showing that larger columns reduce lateral displacement

## Engineering Notes

This is a preliminary academic and automation tool. It is not a substitute for full professional structural design.

The design checks use simplified IS-code-aware concepts. A real project must consider complete IS 456, IS 1893, IS 13920, detailed load combinations, ductile detailing, serviceability, reinforcement detailing, and professional review.

## Technical Concepts Demonstrated

- How a building frame is idealised as nodes and beam-column elements
- How local member stiffness matrices are transformed into global coordinates
- How the global stiffness matrix is assembled
- How support conditions are applied
- How loads are converted into equivalent nodal loads
- How nodal displacements are solved using matrix equations
- How support reactions and member forces are recovered
- How SFD and BMD diagrams are generated from analysis results
- How load combinations are used to create design envelopes
- How engineering calculations can be automated into reports
- Why validation and result interpretation matter as much as coding

## Main Files

- `project_1.py` - main application and analysis engine
- `requirements.txt` - Python packages required to run the project
- `README.md` - project explanation and usage guide
