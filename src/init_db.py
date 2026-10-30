"""Create empty project tables without replacing existing data."""

import argparse
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'data' / 'soybeans.sqlite')
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    schema = (ROOT / 'sql' / '01_create_tables.sql').read_text(encoding='utf-8')
    with sqlite3.connect(args.db) as connection:
        connection.executescript(schema)
        for table in ('annual_soybean', 'weekly_condition'):
            count = connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
            print(f'{table}: {count} rows')
    print(f'Database ready: {args.db.resolve()}')

if __name__ == '__main__':
    main()
