-- Read-only feature query. build_model_panel.py supplies requested_states
-- as a TEMP table and binds all colon-prefixed parameters.
-- Choose one common survey date per YEAR, not a different date per state.
WITH valid_weekly AS (
    SELECT w.state, w.year, w.week_ending,
           w.good_pct + w.excellent_pct AS ge
    FROM weekly_condition AS w
    JOIN requested_states AS s ON w.state = s.state
    WHERE w.year BETWEEN :start_year AND :end_year
      AND w.good_pct IS NOT NULL
      AND w.excellent_pct IS NOT NULL
      AND w.week_ending <= printf('%04d-%s', w.year, :cutoff_month_day)
),
common_weeks AS (
    SELECT year, week_ending
    FROM valid_weekly
    GROUP BY year, week_ending
    HAVING COUNT(DISTINCT state) = (SELECT COUNT(*) FROM requested_states)
),
chosen_weeks AS (
    SELECT year, MAX(week_ending) AS feature_week
    FROM common_weeks
    GROUP BY year
)
SELECT current.state,
       current.year,
       printf('%04d-%s', current.year, :forecast_month_day) AS forecast_date,
       printf('%04d-%s', current.year, :cutoff_month_day) AS survey_cutoff,
       current.week_ending AS feature_week,
       date(current.week_ending, :lag_modifier) AS comparison_week,
       current.ge,
       previous.ge AS ge_4w_ago,
       current.ge - previous.ge AS ge_change_4w,
       annual.yield_bu_acre
FROM chosen_weeks AS chosen
JOIN valid_weekly AS current
  ON current.year = chosen.year
 AND current.week_ending = chosen.feature_week
LEFT JOIN valid_weekly AS previous
  ON previous.state = current.state
 AND previous.year = current.year
 AND previous.week_ending = date(current.week_ending, :lag_modifier)
LEFT JOIN annual_soybean AS annual
  ON annual.state = current.state
 AND annual.year = current.year
ORDER BY current.year, current.state;
