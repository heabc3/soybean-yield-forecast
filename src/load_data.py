"""Validate and load the three core USDA exports into SQLite.

Requires inspect_yield_csv.py and inspect_condition_csvs.py in src. Does not
build the modeling table or estimate a model. Identical imports are safe to
repeat; conflicting existing observations stop the transaction.
"""

import argparse
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import sqlite3

import pandas as pd

from inspect_yield_csv import inspect as inspect_yields
from inspect_condition_csvs import inspect_conditions

ROOT = Path(__file__).resolve().parents[1]
LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_imports (
    dataset TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    source_rows INTEGER NOT NULL CHECK (source_rows > 0),
    PRIMARY KEY (dataset, file_sha256)
);
"""


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def change_sets(existing, incoming_rows, key_length, note, label):
    incoming = {tuple(row[:key_length]): tuple(row[key_length:]) for row in incoming_rows}
    extra = set(existing) - set(incoming)
    if extra:
        raise ValueError(
            f"{label}: database has in-scope records absent from the supplied export. "
            f"Review the source coverage. Examples: {sorted(extra)[:5]}"
        )
    inserts, updates, matched = [], [], 0
    for key, new_values in incoming.items():
        if key not in existing:
            inserts.append((*key, *new_values, note))
            continue
        old_values = existing[key]
        if any(old is not None and (new is None or old != new)
               for old, new in zip(old_values, new_values)):
            raise ValueError(
                f"{label}: conflicting existing values for {key}: "
                f"database={old_values}, CSV={new_values}. "
                "Review possible data revisions; existing observations were not overwritten."
            )
        combined = tuple(new if old is None else old for old, new in zip(old_values, new_values))
        if combined == old_values:
            matched += 1
        else:
            updates.append((*combined, note, note, *key))
    return inserts, updates, matched, incoming


def load_data(annual_path, good_path, excellent_path, db_path, config):
    paths = {
        "annual_yield": Path(annual_path),
        "condition_good": Path(good_path),
        "condition_excellent": Path(excellent_path),
    }
    hashes = {label: fingerprint(path) for label, path in paths.items()}
    source_counts = {
        label: len(pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig"))
        for label, path in paths.items()
    }
    with redirect_stdout(StringIO()):
        annual = inspect_yields(paths["annual_yield"], config)
        weekly, eligibility = inspect_conditions(
            paths["condition_good"], paths["condition_excellent"], config
        )
    if any(fingerprint(path) != hashes[label] for label, path in paths.items()):
        raise ValueError("A raw file changed during validation. Run the command again.")

    states = config["states"]
    first_year = int(config["target_start_year"])
    last_year = int(config["target_end_year"])
    expected_rows = len(states) * (last_year - first_year + 1)
    if len(annual) != expected_rows or annual["yield_bu_acre"].isna().any():
        raise ValueError(f"Expected {expected_rows} unique state-year records with usable yields.")
    if not eligibility["eligible"].all():
        raise ValueError("Some years lack the required survey dates. Review the weekly checker output.")

    annual_rows = [
        (str(state), int(year), float(value))
        for state, year, value in annual.itertuples(index=False, name=None)
    ]
    weekly_rows = [
        (
            str(state), int(year), date.strftime("%Y-%m-%d"),
            None if pd.isna(good) else float(good),
            None if pd.isna(excellent) else float(excellent),
        )
        for state, year, date, good, excellent in weekly[
            ["state", "year", "week_ending", "good_pct", "excellent_pct"]
        ].itertuples(index=False, name=None)
    ]
    annual_note = f"Yield source: {paths['annual_yield'].name}; SHA256={hashes['annual_yield']}"
    weekly_note = (
        f"Good source: {paths['condition_good'].name}; SHA256={hashes['condition_good']}; "
        f"Excellent source: {paths['condition_excellent'].name}; SHA256={hashes['condition_excellent']}"
    )
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / "sql/01_create_tables.sql").read_text(encoding="utf-8")
    placeholders = ",".join("?" for _ in states)
    scope = f"state IN ({placeholders}) AND year BETWEEN ? AND ?"
    params = [*states, first_year, last_year]
    annual_query = f"SELECT state, year, yield_bu_acre FROM annual_soybean WHERE {scope}"
    weekly_query = f"""SELECT state, year, week_ending, good_pct, excellent_pct
                       FROM weekly_condition WHERE {scope}"""
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(schema + "\n" + LOG_SCHEMA)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            old_annual = {
                (state, year): (value,)
                for state, year, value in connection.execute(annual_query, params)
            }
            old_weekly = {
                (state, year, date): (good, excellent)
                for state, year, date, good, excellent in connection.execute(weekly_query, params)
            }
            annual_plan = change_sets(old_annual, annual_rows, 2, annual_note, "Annual yield")
            weekly_plan = change_sets(old_weekly, weekly_rows, 3, weekly_note, "Weekly condition")
            connection.executemany(
                """INSERT INTO annual_soybean(state, year, yield_bu_acre, source_notes)
                   VALUES (?, ?, ?, ?)""", annual_plan[0],
            )
            connection.executemany(
                """UPDATE annual_soybean SET yield_bu_acre=?,
                   source_notes=CASE WHEN source_notes IS NULL OR source_notes=''
                                     THEN ? ELSE source_notes || char(10) || ? END
                   WHERE state=? AND year=?""", annual_plan[1],
            )
            connection.executemany(
                """INSERT INTO weekly_condition
                   (state, year, week_ending, good_pct, excellent_pct, source_notes)
                   VALUES (?, ?, ?, ?, ?, ?)""", weekly_plan[0],
            )
            connection.executemany(
                """UPDATE weekly_condition SET good_pct=?, excellent_pct=?,
                   source_notes=CASE WHEN source_notes IS NULL OR source_notes=''
                                     THEN ? ELSE source_notes || char(10) || ? END
                   WHERE state=? AND year=? AND week_ending=?""", weekly_plan[1],
            )
            for label, path in paths.items():
                connection.execute(
                    """INSERT INTO data_imports
                       (dataset, file_sha256, source_filename, imported_at_utc, source_rows)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(dataset, file_sha256) DO NOTHING""",
                    (label, hashes[label], path.name, imported_at, source_counts[label]),
                )

            # Check exact values as read back from SQLite before committing.
            stored_annual = {
                (state, year): (value,)
                for state, year, value in connection.execute(annual_query, params)
            }
            stored_weekly = {
                (state, year, date): (good, excellent)
                for state, year, date, good, excellent in connection.execute(weekly_query, params)
            }
            if stored_annual != annual_plan[3] or stored_weekly != weekly_plan[3]:
                raise RuntimeError("Database read-back differs from the validated CSVs; load rolled back.")
            annual_summary = pd.read_sql_query(
                f"""SELECT state, COUNT(*) AS rows, COUNT(yield_bu_acre) AS usable_yields,
                           MIN(year) AS first_year, MAX(year) AS last_year
                    FROM annual_soybean WHERE {scope} GROUP BY state ORDER BY state""",
                connection, params=params,
            )
            weekly_summary = pd.read_sql_query(
                f"""SELECT state, COUNT(*) AS weekly_rows,
                           SUM(CASE WHEN good_pct IS NOT NULL AND excellent_pct IS NOT NULL
                                    THEN 1 ELSE 0 END) AS usable_GE_rows
                    FROM weekly_condition WHERE {scope} GROUP BY state ORDER BY state""",
                connection, params=params,
            )

    print("Three CSVs validated. Source files unchanged.")
    for label, plan in [("Annual yield", annual_plan), ("Weekly condition", weekly_plan)]:
        print(f"{label}: {len(plan[0])} inserted; {len(plan[1])} filled; {plan[2]} already matched")
    print("\nAnnual yield table:")
    print(annual_summary.to_string(index=False))
    print("Annual usable yields:", int(annual_summary["usable_yields"].sum()))
    print("\nWeekly condition table:")
    print(weekly_summary.to_string(index=False))
    print("Weekly records in project scope:", len(stored_weekly))
    print("Missing ratings outside the required survey dates remain NULL, never zero-filled.")
    print(f"Years with both required survey dates: {int(eligibility['eligible'].sum())} / {len(eligibility)}")
    print("Source filenames, hashes, and import times recorded in data_imports.")
    print("Database:", db_path.resolve())
    print("STEP 3 COMPLETE: core yield-model data stored and verified.")
    print("STEP 4 NEXT: build the 130-row state-year modeling table.")
    return {"annual": annual_plan[:3], "weekly": weekly_plan[:3]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annual", type=Path, default=ROOT / "data/raw/soybean_yield_annual.csv")
    parser.add_argument("--good", type=Path, default=ROOT / "data/raw/soybean_condition_good.csv")
    parser.add_argument("--excellent", type=Path, default=ROOT / "data/raw/soybean_condition_excellent.csv")
    parser.add_argument("--db", type=Path, default=ROOT / "data/soybeans.sqlite")
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config/project.json").read_text(encoding="utf-8"))
        load_data(args.annual, args.good, args.excellent, args.db, config)
    except (ValueError, OSError, sqlite3.Error, RuntimeError, OverflowError) as exc:
        parser.exit(1, f"DATA LOAD FAILED: {exc}\n")


if __name__ == "__main__":
    main()
