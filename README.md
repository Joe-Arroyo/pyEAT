# pyEAT: a Python Electrolysis Analysis Tool
A Python GUI application for electrochemical characterization of electrolyzers. Unifies data from multiple instruments and measurement techniques into a single interactive analysis environment.

## Features

### EIS (Electrochemical Impedance Spectroscopy)
- Overlay mode: Nyquist + optional Bode plots for multiple datasets
- Grid mode: individual subplots per file
- Nyquist aspect ratio controls
- Frequency markers on the Nyquist plot
- Editable legend names per dataset
- Supports up to 20 simultaneous datasets

### Polarization Curves
- Automatically detects galvanostatic current steps from chronopotentiometry data
- Extracts steady-state voltages over a configurable trailing window
- Group management: compare different experimental conditions side by side
- Curve averaging with uncertainty (standard deviation)
- Interactive point selection with undo/redo
- Transient data view alongside the polarization curve
- CSV and plot export

### Chronopotentiometry Viewer
- Load and overlay multiple files
- Scatter plot of voltage and current vs. time
- Time unit selection (seconds, minutes, hours)
- Axis scale controls and data subsampling
- CSV and plot export

---

## Supported Instruments

| Instrument | EIS | Polarization | Chronopotentiometry |
|---|---|---|---|
| Gamry (.DTA) | ✓ | ✓ | ✓ |
| Autolab ASCII (.xlsx, .txt) | ✓ | ✓ | ✓ |
| Riden RD6006 (.xlsx) | — | ✓ | ✓ |
| Custom CSV | — | ✓ | ✓ |

## Installation

### Requirements

- Python 3.9 or higher
- The following Python packages:
  - PyQt5
  - matplotlib
  - numpy
  - pandas
  - openpyxl

### Option 1 — Conda (recommended for non-developers)

1. Install [Anaconda](https://www.anaconda.com/download) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html)
2. Open the **Anaconda Prompt** (Windows) or a terminal (Mac/Linux)
3. Clone this repository:

    ```bash
    git clone https://github.com/joe-arroyo/pyEAT.git
    cd pyEAT
    ```

4. Create the environment and install dependencies:

    ```bash
    conda create -n pyeat python=3.11
    conda activate pyeat
    pip install -r requirements.txt
    ```

5. Run the application:

    ```bash
    python main.py
    ```

> Next time you want to run it, open Anaconda Prompt, run `conda activate pyeat`, navigate to the folder, and run `python main.py`.

---

### Option 2 — pip (for developers)

```bash
git clone https://github.com/joe-arroyo/pyEAT.git
cd pyEAT
pip install -r requirements.txt
python main.py
```

---
# How to use it:
See [Tutorial](Tutorial.md) for a quick guide on how to use pyEAT.

---
# Cite
If you use pyEAT in your research, please cite it as:
> Arroyo-Gómez, José J. (2026). pyEAT. https://doi.org/10.5281/zenodo.21140508
---

## AI Disclosure

pyEAT was developed with the assistance of [Claude](https://claude.ai) (Anthropic), used for code generation, debugging, and documentation. All code has been reviewed and tested by the author.
