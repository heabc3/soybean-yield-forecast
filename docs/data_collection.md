# USDA data collection plan

Do this after the environment check succeeds. No USDA files are included in
the starter, and the requested sample coverage has not yet been verified.

Use USDA NASS Quick Stats at https://www.nass.usda.gov/Quick_Stats/ . Select
SURVEY, SOYBEANS, STATE, and Iowa, Illinois, Indiana, Minnesota, Nebraska.
Target 2000-2025. Use total-domain observations and all production practices,
avoiding separate irrigated/non-irrigated or subgroup observations.

## Annual exports

Export these annual statistics, preferably as separate files for easy checks:

| Statistic | Required units | Modeling role |
| --- | --- | --- |
| YIELD | BU / ACRE | Final annual label |
| AREA HARVESTED | ACRES | Lagged area input and final area for evaluation |
| PRODUCTION | BU | Final production for evaluation |

## Weekly exports

Export soybean CONDITION measured in PCT GOOD and PCT EXCELLENT. Keep the
week_ending column. Download enough weeks to cover both the late-July
observation and its comparison 28 days earlier.

Keep the raw export files unchanged in data/raw. Record the filters, original
filename, download date, and whether the data are final or subject to revision.
Final annual yield is a historical outcome label, not an input available in
the same year's August forecast. Do not use final current-year harvested area
as though it were known in August.

## Checks before loading SQLite

1. Verify which years and weeks are common to all five states.
2. Strip commas from numeric Value fields and convert suppression codes to
   missing values, never to zero.
3. Confirm units and statistic names before pivoting annual data.
4. Resolve duplicate state-year-statistic and state-week-category keys by
   examining the source/domain filters. Do not silently drop duplicates.
5. Check condition percentages are between 0 and 100 and GE is at most 100.
6. Confirm state codes and calendar years match the records.
7. Inspect missing weeks before matching observations exactly 28 days apart.
8. Keep training transformations restricted to earlier training years.

Quick Stats load_time is a loading timestamp; do not automatically treat it
as the date a number was first publicly available. We use a predeclared survey
buffer and disclose the absence of full vintage reconstruction.


## Annual soybean yield download

- Download date: 2026/10/30
- Source: USDA NASS Quick Stats
- Source URL: https://www.nass.usda.gov/Quick_Stats/
- Saved file: `data/raw/soybean_yield_annual.csv`
- Format: CSV

### Query filters

- Program: SURVEY
- Sector: CROPS
- Group: FIELD CROPS
- Commodity: SOYBEANS
- Category: YIELD
- Data item: SOYBEANS - YIELD, MEASURED IN BU / ACRE
- Geographic level: STATE
- States: IOWA, ILLINOIS, INDIANA, MINNESOTA, NEBRASKA
- Years: 2000–2025
- Frequency: ANNUAL
- Reference period: YEAR
- Domain: TOTAL

### Processing status

The downloaded CSV contents have not been edited. Coverage, missing values and duplicate records have not yet been checked.