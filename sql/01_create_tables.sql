-- Empty normalized tables. These are not preloaded with USDA data.
CREATE TABLE IF NOT EXISTS annual_soybean (
    state TEXT NOT NULL CHECK (state IN ('IA', 'IL', 'IN', 'MN', 'NE')),
    year INTEGER NOT NULL CHECK (year BETWEEN 1900 AND 2100),
    yield_bu_acre REAL CHECK (yield_bu_acre >= 0),
    harvested_acres REAL CHECK (harvested_acres >= 0),
    production_bu REAL CHECK (production_bu >= 0),
    source_notes TEXT,
    downloaded_at TEXT,
    PRIMARY KEY (state, year)
);

CREATE TABLE IF NOT EXISTS weekly_condition (
    state TEXT NOT NULL CHECK (state IN ('IA', 'IL', 'IN', 'MN', 'NE')),
    year INTEGER NOT NULL CHECK (year BETWEEN 1900 AND 2100),
    week_ending TEXT NOT NULL,
    good_pct REAL CHECK (good_pct BETWEEN 0 AND 100),
    excellent_pct REAL CHECK (excellent_pct BETWEEN 0 AND 100),
    source_notes TEXT,
    downloaded_at TEXT,
    CHECK (good_pct + excellent_pct <= 100),
    PRIMARY KEY (state, year, week_ending)
);
