"""Check Good and Excellent soybean-condition CSVs without changing data.

Requires inspect_yield_csv.py in the same src folder. Reports whether each
year has the common pre-cutoff survey date and exact 28-day comparison needed
for this project's predictors. Does not import SQLite or estimate a model.
"""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path

import pandas as pd

from inspect_yield_csv import STATE_NAMES, compact, find_column, normalized_column

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["state", "year", "week_ending"]


def parse_week_ending(value):
    # Explicit source-date formats; never infer a date from a week number.
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%y"):
        try:
            return pd.Timestamp(datetime.strptime(value, pattern).date())
        except ValueError:
            continue
    raise ValueError(f"Missing or unsupported Week Ending date: {value!r}")


def read_condition(path, category, config):
    path = Path(path)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if frame.empty:
        raise ValueError(f"{path.name}: no observations.")
    frame.columns = [normalized_column(name) for name in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError(f"{path.name}: duplicated column names after normalization.")
    for column in frame.columns:
        frame[column] = frame[column].str.strip()

    state_column = find_column(frame, "state_alpha", "state", "state_name")
    year_column = find_column(frame, "year")
    date_column = find_column(frame, "week_ending", "weekending")
    item_column = find_column(frame, "short_desc", "data_item")
    value_column = find_column(frame, "value")
    expected_item = f"SOYBEANS - CONDITION, MEASURED IN PCT {category}"
    if not frame[item_column].map(compact).eq(compact(expected_item)).all():
        actual = "; ".join(frame[item_column].drop_duplicates().head(6))
        raise ValueError(f"{path.name}: expected '{expected_item}'; found: {actual}")

    checked_fields = []
    for aliases, expected in [
        (("source_desc", "program", "source"), "SURVEY"),
        (("agg_level_desc", "geo_level", "geographic_level"), "STATE"),
        (("freq_desc", "frequency", "freq"), "WEEKLY"),
        (("domain_desc", "domain"), "TOTAL"),
        (("prodn_practice_desc", "production_practice"), "ALL PRODUCTION PRACTICES"),
        (("unit_desc", "unit", "units"), f"PCT {category}"),
    ]:
        column = find_column(frame, *aliases, required=False)
        if column is not None:
            if not frame[column].map(compact).eq(compact(expected)).all():
                actual = ", ".join(frame[column].drop_duplicates().head(6))
                raise ValueError(f"{path.name}: expected {column}={expected}; found: {actual}")
            checked_fields.append(column)

    states = frame[state_column].str.upper().replace(STATE_NAMES)
    unexpected_states = sorted(set(states) - set(config["states"]))
    if unexpected_states:
        raise ValueError(f"{path.name}: unexpected states: {unexpected_states}")
    years = pd.to_numeric(frame[year_column], errors="coerce")
    if years.isna().any() or years.isin([float("inf"), -float("inf")]).any():
        raise ValueError(f"{path.name}: missing or invalid years.")
    if (years % 1 != 0).any():
        raise ValueError(f"{path.name}: years must be whole numbers.")
    years = years.astype(int)
    first_year = int(config["target_start_year"])
    last_year = int(config["target_end_year"])
    if not years.between(first_year, last_year).all():
        raise ValueError(f"{path.name}: years outside {first_year}-{last_year}.")

    dates = pd.to_datetime(frame[date_column].map(parse_week_ending))
    if not dates.dt.year.eq(years).all():
        raise ValueError(f"{path.name}: Year disagrees with the Week Ending date.")
    raw = frame[value_column]
    numbers = pd.to_numeric(raw.str.replace(",", "", regex=False), errors="coerce")
    missing_marker = (
        raw.str.upper().isin(["", "NA", "N/A", "--"])
        | raw.str.upper().str.match(r"^\([A-Z]+\)$")
    )
    invalid = numbers.isna() & ~missing_marker
    if invalid.any():
        raise ValueError(f"{path.name}: unrecognized values: {raw[invalid].unique()[:6]}")
    if not numbers.dropna().map(lambda value: math.isfinite(float(value))).all():
        raise ValueError(f"{path.name}: non-finite percentages.")
    if not numbers.dropna().between(0, 100).all():
        raise ValueError(f"{path.name}: percentages must be between 0 and 100.")

    value_name = category.lower() + "_pct"
    tidy = pd.DataFrame({
        "state": states, "year": years, "week_ending": dates, value_name: numbers,
    })
    duplicate = tidy.duplicated(KEYS, keep=False)
    if duplicate.any():
        examples = tidy.loc[duplicate, KEYS].drop_duplicates().head(6)
        raise ValueError(
            f"{path.name}: duplicate state-year-week records; review export filters.\n"
            + examples.to_string(index=False)
        )
    print(f"{category}: {len(tidy)} rows; {int(numbers.isna().sum())} missing/suppressed values; 0 duplicate keys")
    print(f"  File: {path.name}")
    if checked_fields:
        print("  Additional fields validated:", ", ".join(checked_fields))
    print("  Week Ending weekdays:", ", ".join(sorted(dates.dt.day_name().unique())))
    return tidy


def survey_coverage(merged, config):
    states = set(config["states"])
    valid = merged.dropna(subset=["good_pct", "excellent_pct"])
    first_year = int(config["target_start_year"])
    last_year = int(config["target_end_year"])
    cutoff_month_day = config["survey_cutoff_month_day"]
    days = int(config["four_week_change_days"])
    records = []
    for year in range(first_year, last_year + 1):
        cutoff = pd.Timestamp(f"{year}-{cutoff_month_day}")
        before_cutoff = valid.loc[
            (valid["year"] == year) & (valid["week_ending"] <= cutoff)
        ]
        counts = before_cutoff.groupby("week_ending")["state"].nunique()
        common_dates = counts.loc[counts.eq(len(states))].index
        if not len(common_dates):
            records.append({
                "year": year, "survey_week": "-", "comparison_week": "-",
                "eligible": False, "reason": "no complete common week before cutoff",
            })
            continue
        selected = common_dates.max()
        comparison = selected - pd.Timedelta(days=days)
        earlier_states = set(before_cutoff.loc[
            before_cutoff["week_ending"] == comparison, "state"
        ])
        missing_states = sorted(states - earlier_states)
        records.append({
            "year": year,
            "survey_week": selected.strftime("%Y-%m-%d"),
            "comparison_week": comparison.strftime("%Y-%m-%d"),
            "eligible": not missing_states,
            "reason": "OK" if not missing_states else "comparison missing: " + ",".join(missing_states),
        })
    return pd.DataFrame(records)


def inspect_conditions(good_path, excellent_path, config):
    good = read_condition(good_path, "GOOD", config)
    excellent = read_condition(excellent_path, "EXCELLENT", config)
    merged = good.merge(excellent, on=KEYS, how="outer", validate="one_to_one", indicator=True)
    counts = merged["_merge"].value_counts()
    good_only = int(counts.get("left_only", 0))
    excellent_only = int(counts.get("right_only", 0))
    print("Matched state-year-week records:", int(counts.get("both", 0)))
    print("Records found only in Good:", good_only)
    print("Records found only in Excellent:", excellent_only)
    if good_only or excellent_only:
        print("WARNING: file coverage differs; unmatched observations have not been dropped.")

    merged["ge"] = merged["good_pct"] + merged["excellent_pct"]
    if merged["ge"].dropna().gt(100 + 1e-8).any():
        examples = merged.loc[merged["ge"].gt(100 + 1e-8), KEYS + ["ge"]].head(6)
        raise ValueError("Good + Excellent exceeds 100:\n" + examples.to_string(index=False))

    state_records = []
    for state in config["states"]:
        subset = merged.loc[merged["state"] == state]
        state_records.append({
            "state": state,
            "years_present": int(subset["year"].nunique()),
            "good_rows": int((good["state"] == state).sum()),
            "excellent_rows": int((excellent["state"] == state).sum()),
            "usable_GE_rows": int(subset["ge"].notna().sum()),
        })
    print("\nWeekly coverage by state:")
    print(pd.DataFrame(state_records).to_string(index=False))
    eligibility = survey_coverage(merged, config)
    print(f"\nSurvey dates for the {config['forecast_month_day']} forecast "
          f"(survey cutoff {config['survey_cutoff_month_day']}):")
    print(eligibility.to_string(index=False))
    eligible_years = int(eligibility["eligible"].sum())
    print(f"Years with both required survey dates: {eligible_years} / {len(eligibility)}")
    if eligible_years < len(eligibility):
        print("WARNING: review ineligible years before building the modeling sample.")
    print("CONDITION CHECK COMPLETE")
    print("Original CSVs unchanged. No database rows imported and no model estimated.")
    return merged.drop(columns="_merge"), eligibility


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("good_csv", type=Path)
    parser.add_argument("excellent_csv", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads((ROOT / "config" / "project.json").read_text(encoding="utf-8"))
        inspect_conditions(args.good_csv, args.excellent_csv, config)
    except (ValueError, OSError, OverflowError) as exc:
        parser.exit(1, f"CONDITION CHECK FAILED: {exc}\n")


if __name__ == "__main__":
    main()
