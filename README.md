# In Season Soybean Yield and Production Forecasting

Can USDA crop-condition surveys improve an August 1 soybean yield forecast
relative to a trend-only model?

This starter contains a working environment check and database initializer.
USDA observations, fitted yield models, and forecast results have not yet been
added. The setup check uses clearly labeled synthetic numbers only.

## Project scope

- States: Iowa, Illinois, Indiana, Minnesota, and Nebraska.
- Target annual sample: 2000-2025, subject to common data availability.
- Forecast date: August 1 in each historical year.
- Conservative survey cutoff: week ending no later than July 25.
- Targets: final state yield in bushels per acre, then five-state production.
- First planned test year: 2015, subject to historical coverage.

The survey buffer is a practical approximation to report availability. It is
not a reconstruction of every original release date. Downloaded historical
data may include revisions, so describe the results as historical backtests
with seasonal information cutoffs, rather than exact real-time forecasts.

## Workflow

| Stage | Work | Deliverable |
| --- | --- | --- |
| 1 | Create a local Python environment and initialize the project | Passing setup check and empty database |
| 2 | Export annual yield, harvested area, production, and weekly condition data from USDA NASS Quick Stats | Original CSV files plus download notes |
| 3 | Clean values and units, check coverage and duplicate keys, and load SQLite tables | Validated annual and weekly tables |
| 4 | Use SQL and Python to select a common survey week for each year and construct predictors | One observation per state and year |
| 5 | Fit trend-only and trend-plus-condition regressions | Two comparable yield models |
| 6 | Refit on earlier years and predict all five states in each held-out year | MAE, RMSE, and errors by state and year |
| 7 | Multiply predicted yield by prior-year harvested area and sum the five states | Five-state production estimates |
| 8 | Write figures, a model comparison, and a short English research memo | Reproducible portfolio project |

## Models

M0 contains a separate intercept and a separate linear time trend for each
state. M1 contains the same terms plus a common coefficient on Good + Excellent
condition ratings and a common coefficient on their four-week change.

Good + Excellent (GE) is measured in percent from 0 to 100. Its four-week
change is measured in percentage points. For each year, use the latest survey
week on or before July 25 that has both ratings for every included state.
Match the four-week comparison by the date exactly 28 days earlier. Missing
weeks must not silently become a four-row lag or be filled using later data.

Each training fold estimates all regression coefficients from its own data.
If features are centered, use state-specific means from the training fold.
Construct state indicators and state-specific trends explicitly in the design
matrix. Do not detrend using the entire sample before backtesting.

Hold out a complete year for every test fold. For example, train through 2014
to predict all five states in 2015, then train through 2015 to predict 2016.
Model selection must not use the final test years to choose a winning variant.

For the production extension, use the previous year's harvested area for both
models. Compare against final reported production and explain that errors
include both yield prediction error and the area assumption. These are
five-state totals, not national totals or exports to China.

## Mac setup

Use Python 3.13 for the project. An older Python installation can remain on
your Mac. Obtain a Python 3.13 macOS universal2 installer from the official
Python macOS downloads page: https://www.python.org/downloads/macos/ .

After installation, open a new Terminal and check:

```bash
python3.13 --version
```

Extract the ZIP, move the soybean-yield-forecast folder to a convenient
location such as Documents, then open that folder using VS Code's File >
Open Folder. Open Terminal > New Terminal inside VS Code. Its working
directory should be this project folder.

Run these commands in order:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python src/check_setup.py
```

The final command checks the actual interpreter, package imports, a SQLite
join and window function, a small linear regression, error metrics, and figure
rendering. The synthetic arithmetic example is only an installation check.
Success ends with SETUP CHECK PASSED. The command is also compatible with
Python 3.12, but this project's recommended interpreter is Python 3.13.

In VS Code press Command-Shift-P, select Python: Select Interpreter, and choose
the interpreter in .venv/bin/python. In a notebook, also use Select Kernel to
choose that same environment. Python's standard sqlite3 module supplies the
database interface; do not add a package named sqlite3 to requirements.txt.

After a successful install, record the installed package versions:

```bash
python -m pip freeze > requirements-lock.txt
```

requirements.txt gives initial version ranges. requirements-lock.txt will
record the versions actually installed on your Mac. The .venv directory is
local and excluded from Git; the two requirements files can be tracked.

Create the empty database after the setup check passes:

```bash
python src/init_db.py
```

This creates data/soybeans.sqlite with annual_soybean and weekly_condition
tables. They contain zero rows until we import USDA data. The initializer
does not replace or delete existing tables or rows.

## Git checkpoint

Check availability with git --version. If macOS offers Apple's Command Line
Tools, install them. Once Git is available, initialize this folder:

```bash
git init
git status
```

We will configure your commit identity and make the first commit together
after confirming the setup. A GitHub account does not automatically connect
this folder to a remote repository. We will handle that separately. No remote
repository or public upload is created by any starter command.

## Folder guide

- config/project.json: fixed project scope and timing assumptions.
- data/raw: untouched USDA exports, excluded from Git.
- data/processed: generated modeling data, excluded from Git.
- data/soybeans.sqlite: generated local database, excluded from Git.
- docs/data_collection.md: planned data exports and data-quality checks.
- notebooks/00_environment_check.ipynb: a familiar notebook entry point.
- src/check_setup.py: runnable setup verification.
- src/init_db.py: empty database creation.
- sql/01_create_tables.sql: table definitions.
- outputs/figures and outputs/tables: generated research outputs.
- requirements.txt and requirements-lock.txt: package specifications.
- README.md: project purpose, assumptions, and reproducible instructions.
- .gitignore: exclusions for local environments and generated files.

## Data source

USDA NASS Quick Stats: https://www.nass.usda.gov/Quick_Stats/

Manual CSV exports are sufficient for the first version; an API key is not
required for this approach. See docs/data_collection.md after setup succeeds.
