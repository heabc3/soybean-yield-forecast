"""Fit two soybean yield models and evaluate expanding-window forecasts.

Run from the existing project: python src/run_backtest.py
This reads the step-4 panel and writes results, without changing the database.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("M0", "M1")
DATE_COLUMNS = ("forecast_date", "survey_cutoff", "feature_week", "comparison_week")
NUMERIC_COLUMNS = ("year", "trend_year", "ge", "ge_4w_ago", "ge_change_4w", "yield_bu_acre")


def validate_panel(panel, config):
    """Reject incomplete panels or inconsistent dates; never silently drop rows."""
    states = config["states"]
    start, end = int(config["target_start_year"]), int(config["target_end_year"])
    first_test = int(config["first_test_year"])
    if not states or len(states) != len(set(states)):
        raise ValueError("Configuration must contain distinct states.")
    if not start + 2 <= first_test <= end or int(config["four_week_change_days"]) != 28:
        raise ValueError("Check the training/test years and the required 28-day comparison.")
    required = ["state", *NUMERIC_COLUMNS, *DATE_COLUMNS]
    missing = sorted(set(required) - set(panel.columns))
    if missing:
        raise ValueError(f"Missing panel columns: {missing}. Run python src/build_model_panel.py.")
    panel = panel[required].copy()
    if panel.isna().any().any():
        raise ValueError("Missing panel values. Rebuild the panel; no imputation is performed.")
    panel["state"] = panel["state"].astype(str).str.strip()
    for column in NUMERIC_COLUMNS:
        panel[column] = pd.to_numeric(panel[column], errors="raise")
    if not np.isfinite(panel[list(NUMERIC_COLUMNS)].to_numpy(dtype=float)).all():
        raise ValueError("Panel contains non-finite numeric values.")
    if not panel["year"].eq(np.floor(panel["year"])).all():
        raise ValueError("Years must be integers.")
    panel["year"] = panel["year"].astype(int)
    expected = {(state, year) for state in states for year in range(start, end + 1)}
    if panel.duplicated(["state", "year"]).any() or set(zip(panel.state, panel.year)) != expected:
        raise ValueError("Expected exactly one row for every configured state and year.")
    if not panel["trend_year"].eq(panel["year"] - start).all():
        raise ValueError("trend_year must equal year minus the configured starting year.")
    if panel["yield_bu_acre"].lt(0).any():
        raise ValueError("Negative annual yields in panel.")
    if not panel[["ge", "ge_4w_ago"]].ge(0).all().all() or not panel[["ge", "ge_4w_ago"]].le(100).all().all():
        raise ValueError("GE values must be percentages between 0 and 100.")
    if not np.allclose(panel["ge_change_4w"], panel["ge"] - panel["ge_4w_ago"], atol=1e-10, rtol=0):
        raise ValueError("Four-week GE changes disagree with their source values.")
    parsed = {}
    for column in DATE_COLUMNS:
        dates = pd.to_datetime(panel[column], format="%Y-%m-%d", errors="raise")
        if not dates.dt.strftime("%Y-%m-%d").eq(panel[column]).all():
            raise ValueError(f"{column} must use YYYY-MM-DD dates.")
        if not dates.dt.year.eq(panel.year).all():
            raise ValueError(f"{column} disagrees with the observation year.")
        parsed[column] = dates
    for column, key in [("forecast_date", "forecast_month_day"), ("survey_cutoff", "survey_cutoff_month_day")]:
        expected_dates = panel.year.astype(str) + "-" + config[key]
        if not panel[column].eq(expected_dates).all():
            raise ValueError(f"{column} disagrees with the project configuration.")
    if not parsed["feature_week"].le(parsed["survey_cutoff"]).all():
        raise ValueError("A survey week occurs after the information cutoff.")
    if not parsed["survey_cutoff"].lt(parsed["forecast_date"]).all():
        raise ValueError("Survey cutoffs must precede forecast dates.")
    if not (parsed["feature_week"] - parsed["comparison_week"]).dt.days.eq(28).all():
        raise ValueError("The comparison must be exactly 28 calendar days earlier.")
    if not panel.groupby("year").feature_week.nunique().eq(1).all():
        raise ValueError("States must use the same survey week within each year.")
    return panel.sort_values(["year", "state"]).reset_index(drop=True)


def design_matrix(frame, states, model):
    """Fixed, explicit columns: state intercepts, state trends, then conditions."""
    if model not in MODELS:
        raise ValueError(f"Unknown model: {model}")
    columns = {}
    for state in states:
        indicator = frame["state"].eq(state).astype(float)
        columns[f"intercept_{state}"] = indicator
        columns[f"trend_{state}"] = indicator * frame["trend_year"]
    if model == "M1":
        # Do not add yield, GE four weeks ago, or any other panel columns.
        # ge_4w_ago is redundant given ge and ge_change_4w.
        columns["ge"] = frame["ge"]
        columns["ge_change_4w"] = frame["ge_change_4w"]
    return pd.DataFrame(columns, index=frame.index)


def expanding_forecasts(panel, config):
    """Fit on years strictly before each test year, then score all its states."""
    states = config["states"]
    predictions, coefficients = [], []
    first_test, end = int(config["first_test_year"]), int(config["target_end_year"])
    for test_year in range(first_test, end + 1):
        train = panel.loc[panel.year < test_year].copy()
        test = panel.loc[panel.year.eq(test_year)].copy()
        if train.empty or train.year.max() >= test_year or len(test) != len(states):
            raise ValueError(f"Invalid training/test split for {test_year}.")
        result = test.copy()
        result["train_start_year"] = int(train.year.min())
        result["train_end_year"] = int(train.year.max())
        result["training_rows"] = len(train)
        for model in MODELS:
            x_train = design_matrix(train, states, model)
            x_test = design_matrix(test, states, model)
            if len(x_train) <= x_train.shape[1]:
                raise ValueError(f"Too few training observations for {model} in {test_year}.")
            # All state intercept columns are already present: no extra intercept.
            estimator = LinearRegression(fit_intercept=False)
            estimator.fit(x_train, train["yield_bu_acre"])
            if estimator.rank_ != x_train.shape[1]:
                raise ValueError(f"Rank-deficient {model} training design in {test_year}.")
            # The prediction call receives predictor columns only, never test yields.
            result[f"forecast_{model}"] = estimator.predict(x_test)
            result[f"error_{model}"] = result[f"forecast_{model}"] - result["yield_bu_acre"]
            result[f"abs_error_{model}"] = result[f"error_{model}"].abs()
            for term, value in zip(x_train.columns, estimator.coef_):
                coefficients.append({
                    "forecast_year": test_year, "model": model,
                    "train_start_year": int(train.year.min()),
                    "train_end_year": int(train.year.max()), "training_rows": len(train),
                    "term": term, "coefficient": float(value),
                })
        result["abs_error_reduction"] = result["abs_error_M0"] - result["abs_error_M1"]
        predictions.append(result)
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(coefficients)


def summarize(predictions, by=None):
    """Each state-year receives equal weight; errors are in bushels per acre."""
    groups = [(None, predictions)] if by is None else predictions.groupby(by, sort=True)
    records = []
    for value, group in groups:
        for model in MODELS:
            record = {} if by is None else {by: value}
            record.update({
                "model": model, "n_forecasts": len(group),
                "mae_bu_acre": float(mean_absolute_error(group.yield_bu_acre, group[f"forecast_{model}"])),
                "rmse_bu_acre": float(root_mean_squared_error(group.yield_bu_acre, group[f"forecast_{model}"])),
                "mean_error_bu_acre": float(group[f"error_{model}"].mean()),
            })
            records.append(record)
    return pd.DataFrame(records)


def run_backtest(panel_path, output_dir, config):
    panel_path, output_dir = Path(panel_path), Path(output_dir)
    if not panel_path.is_file():
        raise ValueError(f"Panel not found: {panel_path}. Run python src/build_model_panel.py first.")
    source_bytes = panel_path.read_bytes()
    panel = validate_panel(pd.read_csv(BytesIO(source_bytes), dtype={"state": str}), config)
    predictions, coefficients = expanding_forecasts(panel, config)
    overall = summarize(predictions)
    by_state, by_year = summarize(predictions, "state"), summarize(predictions, "year")
    frames = {
        "backtest_predictions.csv": predictions,
        "metrics_overall.csv": overall,
        "metrics_by_state.csv": by_state,
        "metrics_by_year.csv": by_year,
        "fold_coefficients.csv": coefficients,
    }
    texts = {name: frame.to_csv(index=False, lineterminator="\n") for name, frame in frames.items()}
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_panel": panel_path.name,
        "input_panel_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "states": config["states"], "training_start_year": int(config["target_start_year"]),
        "first_test_year": int(config["first_test_year"]), "last_test_year": int(config["target_end_year"]),
        "forecast_month_day": config["forecast_month_day"],
        "survey_cutoff_month_day": config["survey_cutoff_month_day"],
        "test_state_years": len(predictions), "forecasts_per_model": len(predictions),
        "models": {
            "M0": "state intercepts + state-specific linear trends",
            "M1": "state intercepts + state-specific linear trends + common GE and GE-change coefficients",
        },
        "estimation": "OLS; separate joint refit of all coefficients for each model and test year",
        "time_variable": "year - target_start_year (a fixed definition, not fitted preprocessing)",
        "metric_weighting": "equal weight per held-out state-year, not acreage-weighted",
        "error_sign": "forecast minus actual; positive means overprediction",
        "abs_error_reduction": "absolute error M0 minus absolute error M1; positive favors M1",
        "output_sha256": {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in texts.items()},
        "python": platform.python_version(), "numpy": np.__version__,
        "pandas": pd.__version__, "scikit_learn": sklearn.__version__,
        "notes": [
            "Test-year yields are outcome labels used only for evaluation, never predictors or fitting that year's forecast.",
            "Both models use identical earlier years; no random split, full-sample detrending, scaling, or tuning.",
            "Historical backtest with seasonal cutoffs; downloaded data may include revisions and are not original release vintages.",
            "Raw OLS point predictions are not clipped. This script does not estimate prediction intervals or causal effects.",
        ],
    }
    texts["backtest_metadata.json"] = json.dumps(metadata, indent=2, allow_nan=False) + "\n"
    if panel_path.resolve() in {(output_dir / name).resolve() for name in texts}:
        raise ValueError("An output path would overwrite the input panel; choose another --out-dir.")
    # All validation and fits finish successfully before any results are written.
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in texts.items():
        (output_dir / name).write_text(value, encoding="utf-8")

    first, last = int(config["first_test_year"]), int(config["target_end_year"])
    start = int(config["target_start_year"])
    print("Panel validation: passed")
    print(f"First forecast: train {start}-{first - 1}; test {first}")
    print(f"Last forecast:  train {start}-{last - 1}; test {last}")
    print("Test years:", last - first + 1)
    print("State-year forecasts per model:", len(predictions))
    print("\nOverall out-of-sample metrics (bushels per acre; lower MAE/RMSE is better):")
    print(overall.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    indexed = overall.set_index("model")
    for metric, label in [("mae_bu_acre", "MAE"), ("rmse_bu_acre", "RMSE")]:
        baseline, augmented = indexed.loc["M0", metric], indexed.loc["M1", metric]
        improvement = f"{100 * (baseline - augmented) / baseline:.2f}%" if baseline > 1e-12 else "undefined (M0 error approximately zero)"
        print(f"{label} reduction from M0 to M1: {improvement}")
    print("\nMetrics by state:")
    print(by_state.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nSaved to:", output_dir.resolve())
    print("STEPS 5 AND 6 COMPLETE: models fitted and expanding-window backtest evaluated.")
    print("These are historical forecasts through the configured final year, not a current-season forecast.")
    return predictions, overall, by_state, by_year, coefficients, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=ROOT / "data/processed/model_panel.csv")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "outputs/tables")
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config/project.json").read_text(encoding="utf-8"))
        run_backtest(args.panel, args.out_dir, config)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"BACKTEST FAILED: {exc}\n")


if __name__ == "__main__":
    main()
