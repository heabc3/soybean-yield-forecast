"""Build the state-year modeling CSV from SQLite using the step-4 SQL query.

Source tables are opened read-only. No regression is fitted and no features
are centered. Complete validation is required before output files are written.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NUMERIC = ["ge", "ge_4w_ago", "ge_change_4w", "yield_bu_acre"]
DATES = ["forecast_date", "survey_cutoff", "feature_week", "comparison_week"]
LOAD_HINT = "Run python src/load_data.py first, then retry this command."


def digest_frame(frame):
    records = frame.astype(object).where(frame.notna(), None).to_dict(orient="records")
    payload = json.dumps(records, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_sources(annual, weekly, states, start_year, end_year):
    expected = {(state, year) for state in states for year in range(start_year, end_year + 1)}
    annual_keys = set(zip(annual["state"], annual["year"]))
    if annual.duplicated(["state", "year"]).any() or annual_keys != expected:
        raise ValueError(f"The database does not contain the complete annual yield panel. {LOAD_HINT}")
    if annual["yield_bu_acre"].isna().any():
        raise ValueError(f"The database has missing annual yields. {LOAD_HINT}")
    if not np.isfinite(annual["yield_bu_acre"].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite annual yields in the database.")
    if annual["yield_bu_acre"].lt(0).any():
        raise ValueError("Negative annual yields in the database.")
    if weekly.empty:
        raise ValueError(f"The weekly_condition table has no project data. {LOAD_HINT}")
    if weekly.duplicated(["state", "year", "week_ending"]).any():
        raise ValueError("Duplicate weekly database records.")
    parsed = pd.to_datetime(weekly["week_ending"], format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any() or not parsed.dt.strftime("%Y-%m-%d").eq(weekly["week_ending"]).all():
        raise ValueError(f"Week-ending dates must be canonical YYYY-MM-DD strings. {LOAD_HINT}")
    if not parsed.dt.year.eq(weekly["year"]).all():
        raise ValueError("A weekly database date disagrees with its year.")
    for column in ["good_pct", "excellent_pct"]:
        values = weekly[column].dropna()
        if not np.isfinite(values.to_numpy(dtype=float)).all() or not values.between(0, 100).all():
            raise ValueError(f"Invalid database percentages in {column}.")
    if (weekly["good_pct"] + weekly["excellent_pct"]).dropna().gt(100 + 1e-8).any():
        raise ValueError("Database Good + Excellent percentages exceed 100.")


def validate_panel(panel, states, start_year, end_year):
    expected = {(state, year) for state in states for year in range(start_year, end_year + 1)}
    keys = set(zip(panel["state"], panel["year"]))
    if panel.duplicated(["state", "year"]).any() or keys != expected:
        missing = sorted(expected - keys)
        raise ValueError(
            f"Could not form the complete state-year panel. Missing examples: {missing[:8]}. "
            "Review the weekly checker and database load."
        )
    missing_columns = [column for column in NUMERIC + DATES if panel[column].isna().any()]
    if missing_columns:
        raise ValueError(
            f"Missing modeling values in {missing_columns}. "
            "An exact 28-day comparison or annual label may be absent; no rows were silently dropped."
        )
    if not np.isfinite(panel[NUMERIC].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite modeling values.")
    parsed = {column: pd.to_datetime(panel[column], format="%Y-%m-%d", errors="raise") for column in DATES}
    for column, dates in parsed.items():
        if not dates.dt.year.eq(panel["year"]).all():
            raise ValueError(f"The year in {column} differs from the observation year.")
    if not parsed["feature_week"].le(parsed["survey_cutoff"]).all():
        raise ValueError("A selected survey week is later than the information cutoff.")
    if not parsed["survey_cutoff"].lt(parsed["forecast_date"]).all():
        raise ValueError("The survey cutoff must precede the forecast date.")
    if not (parsed["feature_week"] - parsed["comparison_week"]).dt.days.eq(28).all():
        raise ValueError("Comparison dates are not exactly 28 days earlier.")
    if not panel.groupby("year")["feature_week"].nunique().eq(1).all():
        raise ValueError("Different survey dates selected for states in the same year.")
    if not panel[["ge", "ge_4w_ago"]].ge(0).all().all() or not panel[["ge", "ge_4w_ago"]].le(100 + 1e-8).all().all():
        raise ValueError("Invalid GE percentages in modeling data.")
    if not np.allclose(panel["ge_change_4w"], panel["ge"] - panel["ge_4w_ago"], atol=1e-10, rtol=0):
        raise ValueError("Four-week GE changes do not match their inputs.")


def build_panel(db_path, sql_path, output_path, config):
    db_path, sql_path, output_path = map(Path, (db_path, sql_path, output_path))
    if not db_path.is_file():
        raise ValueError(f"Database not found: {db_path}. {LOAD_HINT}")
    if not sql_path.is_file():
        raise ValueError(f"SQL file not found: {sql_path}. Copy it into the project's sql folder.")
    states = config["states"]
    if not states or len(states) != len(set(states)):
        raise ValueError("Configuration must specify distinct states.")
    start_year, end_year = int(config["target_start_year"]), int(config["target_end_year"])
    if start_year > end_year or int(config["four_week_change_days"]) != 28:
        raise ValueError("Check the year range and the required 28-day change interval.")
    params = {
        "start_year": start_year, "end_year": end_year,
        "cutoff_month_day": config["survey_cutoff_month_day"],
        "forecast_month_day": config["forecast_month_day"],
        "lag_modifier": "-28 days",
    }
    sql = sql_path.read_text(encoding="utf-8")
    placeholders = ",".join("?" for _ in states)
    scope = f"state IN ({placeholders}) AND year BETWEEN ? AND ?"
    scope_params = [*states, start_year, end_year]
    # Read-only URI prevents an incorrect path from creating an empty database.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"annual_soybean", "weekly_condition"}.issubset(tables):
            raise ValueError(f"Core database tables are missing. {LOAD_HINT}")
        annual = pd.read_sql_query(
            f"""SELECT state, year, yield_bu_acre FROM annual_soybean
                WHERE {scope} ORDER BY state, year""", connection, params=scope_params,
        )
        weekly = pd.read_sql_query(
            f"""SELECT state, year, week_ending, good_pct, excellent_pct
                FROM weekly_condition WHERE {scope} ORDER BY state, year, week_ending""",
            connection, params=scope_params,
        )
        validate_sources(annual, weekly, states, start_year, end_year)
        connection.execute("CREATE TEMP TABLE requested_states (state TEXT PRIMARY KEY)")
        connection.executemany("INSERT INTO requested_states(state) VALUES (?)", [(state,) for state in states])
        panel = pd.read_sql_query(sql, connection, params=params)
        import_records = (
            pd.read_sql_query(
                """SELECT dataset, file_sha256, source_filename, imported_at_utc, source_rows
                   FROM data_imports ORDER BY dataset, imported_at_utc, file_sha256""",
                connection,
            ).to_dict(orient="records")
            if "data_imports" in tables else []
        )

    validate_panel(panel, states, start_year, end_year)
    panel.insert(2, "trend_year", panel["year"] - start_year)
    csv_text = panel.to_csv(index=False, lineterminator="\n")
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(panel), "states": states, "start_year": start_year, "end_year": end_year,
        "forecast_month_day": config["forecast_month_day"],
        "survey_cutoff_month_day": config["survey_cutoff_month_day"],
        "comparison_days": 28,
        "source_database": db_path.name,
        "source_table_sha256": {"annual_yield": digest_frame(annual), "weekly_condition": digest_frame(weekly)},
        "available_import_records": import_records,
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "output_csv_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "notes": [
            "Historical seasonal-cutoff backtest inputs; not a reconstruction of original release vintages.",
            "GE is percent; GE change is percentage points.",
            "No centering, detrending, scaling, or regression was fitted using the full sample.",
            "Annual yield is the outcome label and is not used to select predictor dates or values.",
        ],
    }
    metadata_path = output_path.with_name(output_path.stem + "_metadata.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(csv_text, encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    print("Database input checks: passed")
    print("Model panel rows:", len(panel))
    print("Unique state-year records:", len(panel[["state", "year"]].drop_duplicates()))
    print("Missing modeling values:", int(panel[NUMERIC + DATES].isna().sum().sum()))
    print("All survey weeks on or before cutoff: True")
    print("All comparison dates exactly 28 days earlier: True")
    print("\nPanel preview:")
    print(panel.head(10).to_string(index=False))
    print("\nRows by state:")
    print(panel.groupby("state").size().rename("rows").to_string())
    print("\nSaved:", output_path.resolve())
    print("Metadata:", metadata_path.resolve())
    print("STEP 4 COMPLETE")
    print("No regression fitted. Training-period transformations belong in the next step.")
    return panel, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/soybeans.sqlite")
    parser.add_argument("--sql", type=Path, default=ROOT / "sql/02_build_model_panel.sql")
    parser.add_argument("--out", type=Path, default=ROOT / "data/processed/model_panel.csv")
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config/project.json").read_text(encoding="utf-8"))
        build_panel(args.db, args.sql, args.out, config)
    except (ValueError, OSError, sqlite3.Error, RuntimeError, KeyError) as exc:
        parser.exit(1, f"MODEL PANEL FAILED: {exc}\n")


if __name__ == "__main__":
    main()
