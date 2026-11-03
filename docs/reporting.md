# Turn the completed backtest into a portfolio result

This step produces three figures, an English results report, and two comparison
tables using the saved forecasts. It does not refit M0/M1 or change the data.

## Install these files in the existing project

Copy these two files into the matching existing folders:

- src/report_results.py
- docs/reporting.md (this guide)

Keep using the existing project and .venv. All required packages are already
included in the project requirements.

Run this in the project terminal after the backtest has completed successfully:

```bash
python src/report_results.py
```

The script checks the saved file fingerprints and recalculates the accuracy
metrics from the individual forecasts before producing the report. A mismatch
gives an error rather than combining results from different runs. If an input
is missing or changed, rerun python src/run_backtest.py and then retry reporting.

## Generated outputs

| File | Purpose |
| --- | --- |
| docs/results_summary.md | English report with the actual metrics, state differences, important test years, largest forecast misses, and limits. |
| outputs/figures/mae_by_state.png | Paired bars compare M0/M1 absolute errors across states. |
| outputs/figures/mae_by_year.png | Shows whether improvements occur across several years or concentrate in a few. |
| outputs/figures/yield_forecasts_by_state.png | Five panels compare each state's actual yields with its historical forecasts. |
| outputs/figures/*.pdf | A PDF copy of each figure for sharing or using in documents. |
| outputs/tables/state_comparison.csv | Both models' errors and percentage reductions by state. |
| outputs/tables/year_comparison.csv | Both models' errors and percentage reductions by year. |

To read the report in VS Code, open docs/results_summary.md and press
Command-Shift-V to preview it. Figures can also be opened directly in the
file explorer.

Positive MAE/RMSE reductions favor M1. Negative reductions mean M1 performed
worse. Signed forecast error is forecast minus actual: negative mean error
indicates average underprediction. Accuracy and signed bias are different
properties; a model can improve MAE while having a larger average bias.

The report explains what happened in the errors. It does not attribute a miss
to weather, irrigation, or a survey problem without additional evidence.

## Save a reviewable version in Git

After the reporting script succeeds, add this link to the bottom of the
existing project README.md, preserving its other content:

```markdown
[Results and figures](docs/results_summary.md)
```

Then run:

```bash
git add src/report_results.py docs/reporting.md docs/results_summary.md README.md
git add -f outputs/figures/mae_by_state.png outputs/figures/mae_by_year.png outputs/figures/yield_forecasts_by_state.png
git commit -m "Report soybean yield forecast results"
git status
```

The existing .gitignore excludes generated figures. Here, -f deliberately adds
only the three selected PNGs so the images in the committed report will also
display when the repository is viewed on GitHub. The PDF copies and comparison
CSVs can remain generated files reproduced by the script.

These commands record a local version. They do not create a remote repository
or publish it to GitHub.

## Describe the conclusion accurately

Use the actual report values and distinguish:

- The overall error reduction from improvements in individual states and years.
- A reduction in absolute errors from a reduction in signed bias.
- This five-state yield evaluation from a forecast of national production or exports.

For the results already shown in the terminal, M1 reduced overall MAE by 13.01%
and RMSE by 15.15%. Both metrics improved in Illinois, Indiana, Minnesota, and
Nebraska; both worsened in Iowa. Mean error was -0.7867 bu/acre for M0 and
-1.0074 for M1, so M1's average underprediction was larger overall.

The report recalculates its figures and text from the saved CSVs rather than
copying these rounded terminal values. If the underlying data or model outputs
change, rerun the backtest and reporting, then review the changes before committing.

The evaluation has 11 held-out years, with correlated outcomes possible across
states in the same year. It supports a descriptive comparison in this sample;
it does not establish statistical significance. Historical data can include
revisions, and the date cutoff does not reconstruct the original release vintages.

This completes the core yield project's reporting stage. Harvested-area,
production, and export modeling remain separate possible extensions.
