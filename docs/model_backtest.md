# Soybean yield models and annual backtest

Research question: Do USDA crop-condition surveys improve an August 1
state-level soybean yield forecast over a simple trend model?

## Run this step

Keep using the existing soybean-yield-forecast project and its existing .venv.
Copy these two files into the matching folders in that project:

- src/run_backtest.py
- docs/model_backtest.md (this guide)

The existing data/processed/model_panel.csv and config/project.json are inputs.
No new packages, SQL tables, or data downloads are needed.

From the project folder in the VS Code terminal, with .venv active, run:

```bash
python src/run_backtest.py
```

The script reads the panel, validates it, fits both models for each test year,
and saves the results under outputs/tables. It does not modify the panel,
the raw CSVs, or the SQLite database. Re-running refreshes the result files.

After a successful run, save the code and documentation in Git:

```bash
git add src/run_backtest.py docs/model_backtest.md
git commit -m "Add soybean yield models and annual backtest"
git status
```

Generated result files remain excluded by the existing .gitignore. Git records
the instructions that reproduce them.

## The two models

Let i denote state and t denote harvest year.

- y_it is the final reported annual soybean yield, measured in bushels per acre.
- T_t = t - 2000 is the fixed time variable already in trend_year.
- GE_it is Good + Excellent condition, on a 0-100 percentage scale.
- DeltaGE_it is GE_it minus the value exactly 28 days earlier, in percentage points.
- The survey week is the latest common valid week on or before July 25, as
  selected in Step 4. Both models are evaluated as August 1 forecasts.

Trend-only model M0:

    y_it = alpha_i + delta_i * T_t + error_it

Trend plus conditions model M1:

    y_it = alpha_i + delta_i * T_t + beta_GE * GE_it
           + beta_change * DeltaGE_it + error_it

The alpha and delta coefficients are specific to each state. The two condition
coefficients are shared across the five states. M0 has 10 coefficients; M1 has
12. All coefficients are estimated afresh, jointly by ordinary least squares,
for each model and forecast year. M1 estimates its own trends; it does not hold
the M0 trends fixed.

The implemented design matrix has one indicator and one indicator-times-trend
column per state. M1 adds ge and ge_change_4w. scikit-learn LinearRegression
uses fit_intercept=False because the five state intercept columns already
provide the intercepts. No extra global intercept is needed.

ge_4w_ago is kept in the panel for checking and interpretation. It is not also
included as a predictor: it is exactly ge - ge_change_4w and would be redundant.
The date fields and annual outcome are not predictors either.

With GE on a 0-100 scale, beta_GE measures the fitted yield difference in
bushels per acre for a one-percentage-point increase in GE, holding the other
predictors fixed. These are predictive associations, not causal estimates.
The script saves coefficients but does not calculate statistical significance.

## Expanding-window evaluation

Each test set contains all five states in one complete year.

| Training years | Held-out year | Training rows | Test rows per model |
| --- | --- | --- | --- |
| 2000-2014 | 2015 | 75 | 5 |
| 2000-2015 | 2016 | 80 | 5 |
| ... | ... | ... | ... |
| 2000-2024 | 2025 | 125 | 5 |

This produces 55 state-year forecasts for each model over 11 test years.
For the forecast of year t, only records from years less than t enter fitting.
That year's yield is used afterward to score the forecasts. When the window
advances to t+1, year t may then enter training.

The script does not randomly split rows, detrend using the full sample, scale
the features, or tune model choices against the test years. Subtracting the
fixed starting year to define trend_year does not estimate anything from
the sample. Predictions omit the unknown error term; it is not an input.

The CSV contains historical data downloaded later, which may include revisions.
This is a historical backtest with seasonal information cutoffs, not a
reconstruction of the exact data vintages available on each historical August 1.
The July 25 rule is a conservative survey-date cutoff, not a report-by-report
release-date reconstruction.

## Reading the results

For an actual yield y and forecast yhat:

    error = yhat - y
    MAE = mean(abs(error))
    RMSE = sqrt(mean(error**2))

Both metrics are in bushels per acre; smaller values indicate better accuracy.
RMSE gives more weight to large misses. Positive mean error means average
overprediction; negative mean error means average underprediction.

Each held-out state-year has equal weight. The metrics are not weighted by
harvested area and are not measurements of national production accuracy.

The terminal reports:

    percentage reduction = 100 * (error_metric_M0 - error_metric_M1) / error_metric_M0

A positive reduction favors M1; a negative reduction means M1 performed worse
on that metric. A near-zero M0 metric makes the percentage undefined. There
is no guarantee that adding condition data will improve accuracy.

| Output in outputs/tables | Contents |
| --- | --- |
| metrics_overall.csv | Two rows: held-out MAE, RMSE, and mean error for M0 and M1. Start here. |
| metrics_by_state.csv | Ten rows: both models evaluated separately for each state. |
| metrics_by_year.csv | Twenty-two rows: both models evaluated separately for each test year. |
| backtest_predictions.csv | Fifty-five rows: actual yield, both forecasts, signed errors, absolute errors, and training dates. |
| fold_coefficients.csv | Coefficients fitted using earlier years for each model and forecast year. |
| backtest_metadata.json | Model specifications, timing assumptions, versions, and input/output fingerprints. |

In backtest_predictions.csv, abs_error_reduction is abs_error_M0 minus
abs_error_M1. Positive values mean M1 improved that individual forecast;
negative values mean it worsened it. The columns forecast_M0 and forecast_M1
are raw OLS point predictions and have no imposed clipping.

First compare overall MAE and RMSE. Then inspect the state and year results
to understand where the improvement or deterioration occurs. Do not treat
these 55 observations as 55 independent years of evidence: states in the
same year can share weather and other shocks. Formal uncertainty assessment
would need to account for that dependence.

## Scope and troubleshooting

This completes Step 5 (model fitting) and Step 6 (annual backtesting).
It evaluates historical forecasts through 2025. It does not forecast 2026,
predict harvested acreage or production, or estimate exports to China.
Charts and a concise interpretation of the actual results come next.

- Panel not found: run python src/build_model_panel.py in the existing project.
- Missing values or inconsistent dates: fix the upstream data and rebuild the
  panel; the backtest does not fill missing values or silently drop records.
- Rank-deficient training design: the predictor columns do not identify all
  coefficients in a training window. Share the error rather than removing rows.
- All validation and model fits must pass before result files are written.
  An input or fitting error leaves previous result files unchanged.

The code was checked with synthetic data for known coefficients, independently
fitted state trends, metric calculations, and separation of training from test
information. Those checks do not establish accuracy on the actual USDA data;
that is what running the script on the downloaded panel will measure.
