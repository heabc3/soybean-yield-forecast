"""Validate saved backtest outputs and create figures and a results report.

Run after run_backtest.py: python src/report_results.py
No models are refitted and no source data or backtest results are changed.
"""

import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # Save figures without opening a separate plotting window.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from run_backtest import summarize

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"IA": "Iowa", "IL": "Illinois", "IN": "Indiana", "MN": "Minnesota", "NE": "Nebraska"}
COLORS = {"M0": "#778293", "M1": "#087F8C", "Actual": "#222B38"}
INPUTS = ("backtest_predictions.csv", "metrics_overall.csv", "metrics_by_state.csv", "metrics_by_year.csv", "fold_coefficients.csv")


def load_results(tables_dir, config):
    """Check that the result files belong to the same successful backtest run."""
    tables_dir = Path(tables_dir)
    hint = "Run python src/run_backtest.py first, then retry."
    try:
        metadata = json.loads((tables_dir / "backtest_metadata.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Backtest metadata not found. {hint}") from exc
    for key in ["states", "first_test_year", "forecast_month_day", "survey_cutoff_month_day"]:
        if metadata.get(key) != config[key]:
            raise ValueError(f"Saved backtest {key} differs from the current configuration. {hint}")
    if metadata.get("last_test_year") != config["target_end_year"] or metadata.get("training_start_year") != config["target_start_year"]:
        raise ValueError(f"Saved backtest years differ from the current configuration. {hint}")
    frames = {}
    for name in INPUTS:
        path = tables_dir / name
        if not path.is_file():
            raise ValueError(f"Missing result file {name}. {hint}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != metadata["output_sha256"].get(name):
            raise ValueError(f"Result file changed after the backtest: {name}. {hint}")
        frames[name] = pd.read_csv(BytesIO(payload), dtype={"state": str})
    p = frames["backtest_predictions.csv"]
    numeric = ["year", "yield_bu_acre", "train_start_year", "train_end_year", "training_rows", "abs_error_reduction"]
    numeric += [f"{prefix}_{model}" for model in ["M0", "M1"] for prefix in ["forecast", "error", "abs_error"]]
    if not {"state", *numeric}.issubset(p.columns):
        raise ValueError(f"Prediction file has missing required columns. {hint}")
    if p[["state", *numeric]].isna().any().any() or not np.isfinite(p[numeric].to_numpy(dtype=float)).all():
        raise ValueError("Missing or non-finite prediction results.")
    if not p["year"].eq(np.floor(p["year"])).all():
        raise ValueError("Prediction years must be integers.")
    p["year"] = p["year"].astype(int)
    years = range(config["first_test_year"], config["target_end_year"] + 1)
    expected = {(state, year) for state in config["states"] for year in years}
    if p.duplicated(["state", "year"]).any() or set(zip(p["state"], p["year"])) != expected:
        raise ValueError("Backtest does not contain the expected held-out state-year pairs.")
    if not p["train_end_year"].eq(p["year"] - 1).all() or not p["train_start_year"].eq(config["target_start_year"]).all():
        raise ValueError("Training windows disagree with the expanding-window design.")
    expected_training_rows = (p["year"] - config["target_start_year"]) * len(config["states"])
    if not p["training_rows"].eq(expected_training_rows).all():
        raise ValueError("Unexpected training-row counts.")
    for model in ["M0", "M1"]:
        error = p[f"forecast_{model}"] - p["yield_bu_acre"]
        if not np.allclose(error, p[f"error_{model}"], atol=1e-9, rtol=0):
            raise ValueError(f"Inconsistent signed errors for {model}.")
        if not np.allclose(error.abs(), p[f"abs_error_{model}"], atol=1e-9, rtol=0):
            raise ValueError(f"Inconsistent absolute errors for {model}.")
    if not np.allclose(p["abs_error_reduction"], p["abs_error_M0"] - p["abs_error_M1"], atol=1e-9, rtol=0):
        raise ValueError("Inconsistent absolute-error reductions.")
    for by, name in [(None, "metrics_overall.csv"), ("state", "metrics_by_state.csv"), ("year", "metrics_by_year.csv")]:
        recalculated = summarize(p, by)
        keys = ["model"] if by is None else [by, "model"]
        stored = frames[name].sort_values(keys).reset_index(drop=True)
        recalculated = recalculated.sort_values(keys).reset_index(drop=True)
        if len(stored) != len(recalculated) or not stored[keys].equals(recalculated[keys]):
            raise ValueError(f"Unexpected metric groups in {name}.")
        values = ["n_forecasts", "mae_bu_acre", "rmse_bu_acre", "mean_error_bu_acre"]
        if not np.allclose(stored[values], recalculated[values], atol=1e-9, rtol=0):
            raise ValueError(f"Saved metrics disagree with individual forecasts in {name}.")
    return p.sort_values(["year", "state"]).reset_index(drop=True), metadata


def comparisons(metrics, group):
    """Positive percentage reductions favor M1; zero baseline gives undefined %."""
    left = metrics.loc[metrics["model"].eq("M0")].drop(columns="model")
    right = metrics.loc[metrics["model"].eq("M1")].drop(columns="model")
    result = left.merge(right, on=group, suffixes=("_M0", "_M1"), validate="one_to_one")
    for metric in ["mae", "rmse"]:
        baseline = result[f"{metric}_bu_acre_M0"]
        difference = baseline - result[f"{metric}_bu_acre_M1"]
        result[f"{metric}_reduction_bu_acre"] = difference
        result[f"{metric}_reduction_pct"] = 100 * difference / baseline.where(baseline.gt(1e-12))
    return result.sort_values(group).reset_index(drop=True)


def make_figures(p, by_state, by_year, config):
    """Return PNG and PDF bytes so all rendering finishes before files are written."""
    rendered = {}

    def export(fig, stem):
        try:
            for extension in ["png", "pdf"]:
                buffer = BytesIO()
                fig.savefig(buffer, format=extension, dpi=180, facecolor="white")
                rendered[f"{stem}.{extension}"] = buffer.getvalue()
        finally:
            plt.close(fig)

    style = {"font.size": 10, "axes.titlesize": 12, "axes.spines.top": False,
             "axes.spines.right": False, "axes.titleweight": "bold", "pdf.fonttype": 42}
    with plt.rc_context(style):
        states = config["states"]
        state_table = by_state.set_index("state").loc[states]
        fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")
        positions = np.arange(len(states))
        for offset, model in [(-0.18, "M0"), (0.18, "M1")]:
            bars = ax.barh(positions + offset, state_table[f"mae_bu_acre_{model}"], height=0.32,
                           color=COLORS[model], label=f"{model}: " + ("trend" if model == "M0" else "trend + conditions"))
            ax.bar_label(bars, fmt="%.2f", padding=5, fontsize=9)
        ax.set_yticks(positions, [NAMES.get(state, state) for state in states])
        ax.invert_yaxis()
        upper = state_table[["mae_bu_acre_M0", "mae_bu_acre_M1"]].to_numpy().max()
        ax.set_xlim(0, max(1, upper * 1.2))
        ax.set_xlabel("Mean absolute error (bushels per acre); lower is better")
        ax.set_title("Soybean forecast errors by state", loc="left", pad=38)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2, frameon=False)
        ax.set_axisbelow(True)
        ax.grid(axis="x", alpha=0.18)
        export(fig, "mae_by_state")

        fig, ax = plt.subplots(figsize=(10, 4.7), layout="constrained")
        for model, linestyle in [("M0", "--"), ("M1", "-")]:
            ax.plot(by_year["year"], by_year[f"mae_bu_acre_{model}"], marker="o", markersize=4,
                    linewidth=2, linestyle=linestyle, color=COLORS[model], label=model)
        ax.set_title("Forecast errors by harvest year", loc="left")
        ax.set_xlabel("Held-out harvest year")
        ax.set_ylabel("MAE across five states (bu/acre)")
        ax.set_xticks(by_year["year"])
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False)
        ax.grid(alpha=0.18)
        export(fig, "mae_by_year")

        fig, axes = plt.subplots(2, 3, figsize=(12, 7.3), sharex=True, sharey=True, layout="constrained")
        handles = []
        for index, state in enumerate(states):
            ax = axes.flat[index]
            group = p.loc[p["state"].eq(state)].sort_values("year")
            for label, column, style_line in [("Actual", "yield_bu_acre", "-"), ("M0", "forecast_M0", "--"), ("M1", "forecast_M1", "-")]:
                line, = ax.plot(group["year"], group[column], label=label, color=COLORS[label],
                                linestyle=style_line, linewidth=1.8, marker="o", markersize=3)
                if index == 0:
                    handles.append(line)
            ax.set_title(NAMES.get(state, state), loc="left")
            first, last = config["first_test_year"], config["target_end_year"]
            ax.set_xticks(sorted({first, (first + last) // 2, last}))
            ax.tick_params(labelbottom=True)
            ax.grid(alpha=0.18)
        for ax in list(axes.flat)[len(states):]:
            ax.set_axis_off()
        key = axes.flat[-1]
        key.legend(handles=handles, loc="upper left", frameon=False, fontsize=11)
        key.text(0.04, 0.44, "M0: state trends\nM1: trends + crop conditions\n\nAll forecasts use earlier years\nfor model estimation.",
                 transform=key.transAxes, fontsize=10, va="top", linespacing=1.6)
        fig.suptitle("Actual annual yields and August 1 forecasts", fontsize=15, fontweight="bold")
        fig.supxlabel("Harvest year")
        fig.supylabel("Soybean yield (bushels per acre)")
        export(fig, "yield_forecasts_by_state")
    return rendered


def format_number(value, decimals=2):
    return f"{value:.{decimals}f}" if pd.notna(value) else "undefined"


def format_percentage(value):
    return f"{value:.2f}%" if pd.notna(value) else "undefined"


def make_report(p, overall, by_state, by_year, config, figure_links):
    overall = overall.set_index("model")
    rows = []
    for model in ["M0", "M1"]:
        m = overall.loc[model]
        rows.append(f"| {model} | {int(m['n_forecasts'])} | {m['mae_bu_acre']:.4f} | {m['rmse_bu_acre']:.4f} | {m['mean_error_bu_acre']:.4f} |")
    state_rows = [
        f"| {NAMES.get(r.state, r.state)} | {r.mae_bu_acre_M0:.4f} | {r.mae_bu_acre_M1:.4f} | {format_percentage(r.mae_reduction_pct)} | {format_percentage(r.rmse_reduction_pct)} |"
        for r in by_state.itertuples()
    ]
    baseline = overall.loc["M0"]
    augmented = overall.loc["M1"]
    changes = {}
    for metric in ["mae", "rmse"]:
        m0, m1 = baseline[f"{metric}_bu_acre"], augmented[f"{metric}_bu_acre"]
        changes[metric] = format_number(100 * (m0-m1) / m0) + "%" if m0 > 1e-12 else "undefined"
    mae_wins = int(by_state["mae_reduction_bu_acre"].gt(0).sum())
    rmse_wins = int(by_state["rmse_reduction_bu_acre"].gt(0).sum())
    year_wins = int(by_year["mae_reduction_bu_acre"].gt(0).sum())
    worse = by_state.loc[by_state["mae_reduction_bu_acre"].lt(0), "state"]
    worse_names = ", ".join(NAMES.get(state, state) for state in worse) or "none"
    year_lines = []
    for title, subset in [("Largest annual MAE reductions", by_year.nlargest(3, "mae_reduction_bu_acre")),
                          ("Smallest annual MAE reductions", by_year.nsmallest(3, "mae_reduction_bu_acre"))]:
        items = "; ".join(f"{int(r.year)}: {r.mae_reduction_bu_acre:+.3f} bu/acre" for r in subset.itertuples())
        year_lines.append(f"- {title}: {items}.")
    misses = p.nlargest(5, "abs_error_M1")
    miss_rows = [f"| {r.state} | {r.year} | {r.yield_bu_acre:.2f} | {r.forecast_M0:.2f} | {r.forecast_M1:.2f} | {r.error_M1:+.2f} |" for r in misses.itertuples()]
    start, first, end = config["target_start_year"], config["first_test_year"], config["target_end_year"]
    return f"""# Do crop-condition surveys improve August soybean yield forecasts?

This project compares state-specific linear trends (M0) with trends plus USDA
Good + Excellent condition and its four-week change (M1). The evaluation covers
{len(p)} held-out state-year observations in {len(config['states'])} states from {first} through {end}.

M1's overall MAE reduction relative to M0 is **{changes['mae']}**; its RMSE reduction
is **{changes['rmse']}**. Positive reductions indicate improvement; negative values
indicate deterioration. These results apply to this historical evaluation sample.

## Data and forecast design

- States: {', '.join(NAMES.get(state, state) for state in config['states'])}.
- Training data begin in {start}. One observation per state and harvest year.
- Target: final annual soybean yield, in bushels per acre.
- Condition inputs: the latest common valid survey week on or before July 25,
  plus the change from exactly 28 days earlier. GE uses a 0-100 percentage scale.
- Forecast date: August 1. Both models are re-estimated using only earlier years.
- First test: train {start}-{first-1}, predict {first}; last test: train {start}-{end-1}, predict {end}.
- M0 estimates five intercepts and five state trends. M1 jointly estimates its own
  state intercepts/trends and two condition coefficients shared across states.
- Metrics give equal weight to each held-out state-year. Detailed methodology:
  [model_backtest.md](model_backtest.md).

## Overall accuracy

| Model | Forecasts | MAE | RMSE | Mean signed error |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

All errors are in bushels per acre. Signed error is forecast minus actual:
negative mean error indicates average underprediction. Lower MAE/RMSE is better;
mean error measures the direction of bias and should be assessed separately.

## Differences across states

| State | M0 MAE | M1 MAE | MAE reduction | RMSE reduction |
| --- | ---: | ---: | ---: | ---: |
{chr(10).join(state_rows)}

M1 has lower MAE in {mae_wins}/{len(by_state)} states and lower RMSE in
{rmse_wins}/{len(by_state)} states. States where MAE worsened: {worse_names}.

![Mean absolute error by state]({figure_links['mae_by_state.png']})

## Differences across years

M1 has lower average absolute error across states in {year_wins}/{len(by_year)}
test years. The following reductions are M0 MAE minus M1 MAE; positive is better for M1.

{chr(10).join(year_lines)}

![Mean absolute error by year]({figure_links['mae_by_year.png']})

## Yield paths and largest M1 misses

![Actual yields and historical forecasts]({figure_links['yield_forecasts_by_state.png']})

The table lists the five largest absolute M1 misses. Differences alone do not
identify their causes; attributing a miss to weather or survey error needs further evidence.

| State | Year | Actual yield | M0 forecast | M1 forecast | M1 signed error |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(miss_rows)}

## Interpretation and limits

- The comparison measures predictive value in this sample, not causal effects.
- Downloaded historical records may contain revisions. The exercise applies
  seasonal survey-date cutoffs rather than reconstructing original release vintages.
- The sample contains {len(by_year)} test years; states within a year can share shocks.
  These descriptive comparisons do not establish statistical significance.
- The target is state-level yield. Production also requires harvested area;
  this project does not estimate national output or exports to China.

## Reproduce the report

Run from the existing project with its virtual environment active:

```bash
python src/run_backtest.py
python src/report_results.py
```

The report script validates the saved backtest files and recalculates their
metrics before producing this document. It does not refit models or change data.
All three figures are saved as PNG and PDF under outputs/figures. State and year
comparison tables are saved under outputs/tables. Data collection details are
documented in [data_collection.md](data_collection.md).

This document is generated; keep additional personal notes in a separate file.
"""


def report_results(tables_dir, figures_dir, report_path, config):
    tables_dir, figures_dir, report_path = map(Path, (tables_dir, figures_dir, report_path))
    p, metadata = load_results(tables_dir, config)
    overall = summarize(p)
    by_state = comparisons(summarize(p, "state"), "state")
    by_year = comparisons(summarize(p, "year"), "year")
    rendered = make_figures(p, by_state, by_year, config)
    links = {name: Path(os.path.relpath(figures_dir / name, report_path.parent)).as_posix() for name in rendered}
    report = make_report(p, overall, by_state, by_year, config, links)
    files = {figures_dir / name: value for name, value in rendered.items()}
    files[report_path] = report.encode("utf-8")
    for name, frame in [("state_comparison.csv", by_state), ("year_comparison.csv", by_year)]:
        files[tables_dir / name] = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    sources = {(tables_dir / name).resolve() for name in [*INPUTS, "backtest_metadata.json"]}
    if any(path.resolve() in sources for path in files):
        raise ValueError("An output would overwrite a saved backtest input. Choose another output path.")
    for path, payload in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    print("Backtest results validation: passed")
    print("Existing models and saved forecasts were not changed.")
    print("\nAnnual comparison (positive percentage reductions favor M1):")
    print(by_year[["year", "mae_bu_acre_M0", "mae_bu_acre_M1", "mae_reduction_pct"]].to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\nResults report:", report_path.resolve())
    print("Figures:", figures_dir.resolve())
    print("REPORTING COMPLETE: three PNG/PDF figures, two comparison tables, and a results report.")
    return p, overall, by_state, by_year, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=Path, default=ROOT / "outputs/tables")
    parser.add_argument("--figures", type=Path, default=ROOT / "outputs/figures")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/results_summary.md")
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config/project.json").read_text(encoding="utf-8"))
        report_results(args.tables, args.figures, args.report, config)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"RESULTS REPORT FAILED: {exc}\n")


if __name__ == "__main__":
    main()
