"""Inspect an annual soybean yield export from USDA NASS Quick Stats.

Reads the original CSV without modifying it. Supports the display labels in
Quick Stats CSV downloads and the equivalent API field names. Does not load
SQLite or fit a model.
"""

import argparse
import json
import math
from pathlib import Path
import re

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATE_NAMES = {
    "IOWA": "IA",
    "ILLINOIS": "IL",
    "INDIANA": "IN",
    "MINNESOTA": "MN",
    "NEBRASKA": "NE",
}
EXPECTED_ITEM = "SOYBEANS - YIELD, MEASURED IN BU / ACRE"


def normalized_column(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")


def find_column(frame, *names, required=True):
    for name in names:
        if name in frame.columns:
            return name
    if required:
        raise ValueError(
            f"Missing column: expected one of {names}. "
            f"Available columns: {', '.join(frame.columns)}"
        )
    return None


def compact(value):
    return re.sub(r"\s+", "", str(value)).upper()


def inspect(path, config):
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if frame.empty:
        raise ValueError("The CSV contains no observations.")
    frame.columns = [normalized_column(column) for column in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError("Column names become duplicated after normalization.")
    for column in frame.columns:
        frame[column] = frame[column].str.strip()

    year_column = find_column(frame, "year")
    state_column = find_column(frame, "state_alpha", "state", "state_name")
    item_column = find_column(frame, "short_desc", "data_item")
    value_column = find_column(frame, "value")

    items = frame[item_column].map(compact)
    wrong_items = frame.loc[items != compact(EXPECTED_ITEM), item_column].unique()
    if len(wrong_items):
        raise ValueError(
            f"Export only '{EXPECTED_ITEM}'. Other data items found: "
            + "; ".join(str(value) for value in wrong_items[:8])
        )

    # These fields are not present in every Quick Stats export format.
    checked_fields = []
    for names, expected in [
        (("source_desc", "program", "source"), "SURVEY"),
        (("agg_level_desc", "geo_level", "geographic_level"), "STATE"),
        (("freq_desc", "frequency", "freq"), "ANNUAL"),
        (("domain_desc", "domain"), "TOTAL"),
        (("prodn_practice_desc", "production_practice"), "ALL PRODUCTION PRACTICES"),
        (("unit_desc", "unit", "units"), "BU / ACRE"),
    ]:
        column = find_column(frame, *names, required=False)
        if column is not None:
            if not frame[column].map(compact).eq(compact(expected)).all():
                found = ", ".join(frame[column].drop_duplicates().head(8))
                raise ValueError(f"Expected {column}={expected}; found: {found}")
            checked_fields.append(column)

    expected_states = config["states"]
    first_year = int(config["target_start_year"])
    last_year = int(config["target_end_year"])
    expected_years = set(range(first_year, last_year + 1))

    states = frame[state_column].str.upper().replace(STATE_NAMES)
    wrong_states = sorted(set(states) - set(expected_states))
    if wrong_states:
        raise ValueError("Unexpected states: " + ", ".join(wrong_states))

    years = pd.to_numeric(frame[year_column], errors="coerce")
    if years.isna().any() or years.isin([float("inf"), -float("inf")]).any():
        raise ValueError("Some years are missing or non-numeric.")
    if (years % 1 != 0).any():
        raise ValueError("Years must be whole numbers.")
    years = years.astype(int)
    wrong_years = sorted(set(years) - expected_years)
    if wrong_years:
        raise ValueError(f"Years outside {first_year}-{last_year}: {wrong_years}")

    raw_values = frame[value_column]
    numeric = pd.to_numeric(raw_values.str.replace(",", "", regex=False), errors="coerce")
    # Bracketed non-numeric NASS markers remain missing, never zero.
    recognized_missing = (
        raw_values.str.upper().isin(["", "NA", "N/A", "--"])
        | raw_values.str.upper().str.match(r"^\([A-Z]+\)$")
    )
    invalid = numeric.isna() & ~recognized_missing
    if invalid.any():
        raise ValueError(
            "Unexpected non-numeric values: "
            + ", ".join(raw_values.loc[invalid].drop_duplicates().head(8))
        )
    if not numeric.dropna().map(lambda value: math.isfinite(float(value))).all():
        raise ValueError("Non-finite yield values found.")
    if (numeric.dropna() < 0).any():
        raise ValueError("Negative soybean yields found.")
    if numeric.notna().sum() == 0:
        raise ValueError("The export contains no usable yield values.")

    tidy = pd.DataFrame(
        {"state": states, "year": years, "yield_bu_acre": numeric}
    )
    duplicate_rows = tidy.duplicated(["state", "year"], keep=False)
    if duplicate_rows.any():
        examples = tidy.loc[duplicate_rows, ["state", "year"]].drop_duplicates().head(8)
        raise ValueError(
            "Duplicate state-year records. Check source/domain/practice filters; "
            "do not silently drop duplicates.\n" + examples.to_string(index=False)
        )

    records = []
    missing_pairs = []
    for state in expected_states:
        subset = tidy.loc[tidy["state"] == state]
        observed_years = set(subset["year"])
        missing_years = sorted(expected_years - observed_years)
        missing_pairs.extend((state, year) for year in missing_years)
        records.append(
            {
                "state": state,
                "years_present": len(observed_years),
                "usable_yields": int(subset["yield_bu_acre"].notna().sum()),
                "first_year": int(subset["year"].min()) if len(subset) else "-",
                "last_year": int(subset["year"].max()) if len(subset) else "-",
            }
        )

    print("CSV:", path.name)
    print("Data item:", EXPECTED_ITEM)
    print("Annual yield rows:", len(tidy))
    print("Expected rows if coverage is complete:", len(expected_states) * len(expected_years))
    print("Duplicate state-year records: 0")
    print("Missing/suppressed yield values:", int(numeric.isna().sum()))
    print("Missing state-year combinations:", len(missing_pairs))
    if checked_fields:
        print("Additional fields validated:", ", ".join(checked_fields))
    print(pd.DataFrame(records).to_string(index=False))
    if numeric.isna().any():
        print("Non-numeric markers retained as missing:", sorted(set(raw_values[numeric.isna()])))
    if missing_pairs:
        print("Coverage gaps:", missing_pairs)
    print("Review coverage gaps and missing values before modeling.")
    print("Inspection complete. Original CSV unchanged; no database rows imported.")
    return tidy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Path to the original annual yield CSV")
    args = parser.parse_args()
    config_path = ROOT / "config" / "project.json"
    if not config_path.exists():
        parser.exit(1, "Place this script in the project's src folder before running it.\n")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        inspect(args.csv, config)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"CSV CHECK FAILED: {exc}\n")


if __name__ == "__main__":
    main()
