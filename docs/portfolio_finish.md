# Finish and publish the soybean yield portfolio project

The analysis is complete. This checklist packages the existing work so another
person can read the findings and reproduce the backtest.

## 1. Generate and review the final report

Use the existing soybean-yield-forecast folder and its existing .venv.
If reporting has not already succeeded, run:

```bash
python src/report_results.py
```

If this script is missing, first copy it and docs/reporting.md from the earlier
yield-results-report.zip into the matching project folders.

Open docs/results_summary.md in VS Code and press Command-Shift-V. Confirm
that the report opens and its three figures display. Its overall metrics should
match the successful backtest: M0 MAE 3.2156 and RMSE 4.1914; M1 MAE 2.7973 and
RMSE 3.5565, subject to display rounding.

## 2. Install the final README and update the notes

Replace the starter README.md in the project root with the README.md in this
package. The replacement describes the completed yield study, its actual
results, and reproducible commands. Preserve any personal notes from the old
README in a separate document before replacing it.

Copy this checklist to docs/portfolio_finish.md.

In config/project.json, change only the bookkeeping entry:

```json
"coverage_status": "verified"
```

The successful data checks established 130 usable annual yields and required
condition dates for all 26 years. This bookkeeping field does not change the models.

In docs/data_collection.md, preserve your actual download notes and update any
opening statement that still says coverage is unverified. A suitable status is:

> The core study uses annual soybean yield and weekly GOOD and EXCELLENT
> condition ratings for IA, IL, IN, MN, and NE, 2000-2025. Validation confirmed
> 130 usable annual yields and both required condition dates for all 26 years.

Check that the log has the actual download dates, source, filenames, and query
filters you used. Do not invent missing dates. Earlier references to harvested
area and production can be marked as optional extensions outside this study.

## 3. Save the reviewable project in Git

The existing .gitignore excludes generated data and figures. For this portfolio,
deliberately include the small 130-row modeling panel, its metadata, and three
selected PNG figures. This lets reviewers run the analysis and see the report
without obtaining the raw exports first. The raw CSVs, database, environment,
PDF copies, and intermediate output tables can remain local.

From the project terminal, run the following lines in order:

```bash
python -m pip freeze > requirements-lock.txt
git add .
git add -f data/processed/model_panel.csv data/processed/model_panel_metadata.json
git add -f outputs/figures/mae_by_state.png outputs/figures/mae_by_year.png outputs/figures/yield_forecasts_by_state.png
git diff --cached --stat
```

The last command previews the staged snapshot. The -f commands override the
ignore rules for those five named files only. They do not include all raw data
or the environment.

Once the intended files are staged, record the snapshot:

```bash
git commit -m "Finalize soybean yield forecasting portfolio"
git status
```

If Git reports nothing to commit and a clean working tree, that snapshot is
already saved. Do not reinitialize the repository or create another environment.

## 4. Publish from VS Code

If you have not connected this project to GitHub:

1. Press Command-Shift-P and run Publish to GitHub.
2. Complete the GitHub sign-in prompts.
3. Name the repository soybean-yield-forecast and choose Public when ready for portfolio sharing.
4. Open the resulting repository on GitHub.

VS Code creates the hosted repository and uploads the local commits. If this
project already has a GitHub remote, use Source Control > ... > Push instead.
The local branch can remain named master.

Official workflow: https://code.visualstudio.com/docs/sourcecontrol/repos-remotes

## 5. Verify the published result

On GitHub, confirm that:

- The README presents the actual results and its state-error chart displays.
- The Full results and figures link opens the report with all three images.
- src, sql, config, docs, and the requirements files are present.
- data/processed contains the 130-row model_panel.csv and its metadata.

For a final reproducibility check, obtain a fresh copy of the published repository
and follow its README. The included panel should reproduce the reported metrics,
up to numerical/display precision, without the raw CSV downloads.

This is the finished core portfolio project. Further models, harvested-area
estimates, production forecasts, or trade analysis would be separate extensions.
