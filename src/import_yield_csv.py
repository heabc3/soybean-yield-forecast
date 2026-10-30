"""Validate and import annual USDA soybean yields without replacing other data.

Reuses inspect_yield_csv.py. Identical existing yields are left unchanged;
conflicting yields stop the import. The raw CSV is never modified.
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

from inspect_yield_csv import inspect

ROOT = Path(__file__).resolve().parents[1]

IMPORT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS yield_imports (
    file_sha256 TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    imported_at_utc TEXT NOT NULL,
    source_rows INTEGER NOT NULL CHECK (source_rows > 0)
);
"""


def import_yields(csv_path, db_path, config):
    csv_path = Path(csv_path)
    db_path = Path(db_path)
    source_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    with redirect_stdout(StringIO()):
        tidy = inspect(csv_path, config)
    if hashlib.sha256(csv_path.read_bytes()).hexdigest() != source_hash:
        raise ValueError("The source file changed during validation. Run the command again.")

    states = config["states"]
    first_year = int(config["target_start_year"])
    last_year = int(config["target_end_year"])
    expected_rows = len(states) * (last_year - first_year + 1)
    if len(tidy) != expected_rows or tidy["yield_bu_acre"].isna().any():
        raise ValueError(
            f"This import expects {expected_rows} unique state-year records with "
            "non-missing yields. Run inspect_yield_csv.py to review coverage."
        )

    rows = [
        (str(state), int(year), float(value))
        for state, year, value in tidy.itertuples(index=False, name=None)
    ]
    source_note = f"Yield source: {csv_path.name}; SHA256={source_hash}"
    imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    schema = (ROOT / "sql" / "01_create_tables.sql").read_text(encoding="utf-8")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(db_path)) as connection:
        # Schema initialization does not replace existing tables or records.
        connection.executescript(schema + "\n" + IMPORT_LOG_SCHEMA)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                (state, year): value
                for state, year, value in connection.execute(
                    "SELECT state, year, yield_bu_acre FROM annual_soybean"
                )
            }
            insert_rows = []
            fill_rows = []
            unchanged = 0
            conflicts = []
            for state, year, value in rows:
                key = (state, year)
                if key not in existing:
                    insert_rows.append((state, year, value, source_note))
                elif existing[key] is None:
                    fill_rows.append((value, source_note, source_note, state, year))
                elif float(existing[key]) == value:
                    unchanged += 1
                else:
                    conflicts.append((state, year, existing[key], value))
            if conflicts:
                examples = "; ".join(
                    f"{state} {year}: database={old}, CSV={new}"
                    for state, year, old, new in conflicts[:8]
                )
                raise ValueError(
                    "Existing yields differ from the CSV; no yield rows were changed. "
                    "Review possible revisions before updating. " + examples
                )

            connection.executemany(
                """INSERT INTO annual_soybean
                   (state, year, yield_bu_acre, source_notes)
                   VALUES (?, ?, ?, ?)""",
                insert_rows,
            )
            connection.executemany(
                """UPDATE annual_soybean
                   SET yield_bu_acre = ?,
                       source_notes = CASE
                           WHEN source_notes IS NULL OR source_notes = '' THEN ?
                           ELSE source_notes || char(10) || ?
                       END
                   WHERE state = ? AND year = ?""",
                fill_rows,
            )
            connection.execute(
                """INSERT INTO yield_imports
                   (file_sha256, source_filename, imported_at_utc, source_rows)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(file_sha256) DO NOTHING""",
                (source_hash, csv_path.name, imported_at, len(rows)),
            )

            placeholders = ",".join("?" for _ in states)
            summary = pd.read_sql_query(
                f"""SELECT state, COUNT(*) AS rows,
                           COUNT(yield_bu_acre) AS usable_yields,
                           MIN(year) AS first_year, MAX(year) AS last_year
                    FROM annual_soybean
                    WHERE state IN ({placeholders}) AND year BETWEEN ? AND ?
                    GROUP BY state ORDER BY state""",
                connection,
                params=[*states, first_year, last_year],
            )
            if int(summary["usable_yields"].sum()) != expected_rows:
                raise RuntimeError("Database row-count verification failed; import rolled back.")
            weekly_rows = connection.execute(
                "SELECT COUNT(*) FROM weekly_condition"
            ).fetchone()[0]

    print("CSV validation: passed")
    print("New annual rows inserted:", len(insert_rows))
    print("Existing annual rows with missing yield filled:", len(fill_rows))
    print("Matching annual rows left unchanged:", unchanged)
    print("Annual usable yields in project scope:", int(summary["usable_yields"].sum()))
    print(summary.to_string(index=False))
    print("Weekly condition rows:", weekly_rows)
    print("Database:", db_path.resolve())
    print("Source file and SHA256 recorded in yield_imports.")
    print("Raw CSV unchanged. Import time is not the original download date.")
    print("YIELD IMPORT COMPLETE")
    return {
        "inserted": len(insert_rows),
        "filled": len(fill_rows),
        "unchanged": unchanged,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Original annual yield CSV")
    parser.add_argument(
        "--db", type=Path, default=ROOT / "data" / "soybeans.sqlite",
        help="SQLite database; defaults to data/soybeans.sqlite",
    )
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config" / "project.json").read_text(encoding="utf-8"))
        import_yields(args.csv, args.db, config)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as exc:
        parser.exit(1, f"YIELD IMPORT FAILED: {exc}\n")


if __name__ == "__main__":
    main()
