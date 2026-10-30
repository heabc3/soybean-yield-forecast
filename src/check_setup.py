"""Check the analysis environment using synthetic arithmetic, not USDA data."""

from importlib import import_module, metadata
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    'pandas': 'pandas',
    'numpy': 'numpy',
    'scikit-learn': 'sklearn',
    'matplotlib': 'matplotlib',
    'seaborn': 'seaborn',
}

def main():
    print('Python:', sys.version.split()[0])
    print('Interpreter:', sys.executable)
    print('Virtual environment:', sys.prefix != sys.base_prefix)
    print('SQLite:', sqlite3.sqlite_version)
    if sys.version_info < (3, 12):
        raise SystemExit('Use Python 3.13 for this project; the check requires 3.12 or newer.')
    if sys.prefix == sys.base_prefix:
        print('NOTE: activate the project .venv before continuing on your Mac.')

    missing = []
    for distribution, module in PACKAGES.items():
        try:
            import_module(module)
            print(f'{distribution}: {metadata.version(distribution)}')
        except (ImportError, metadata.PackageNotFoundError) as exc:
            missing.append(f'{distribution}: {exc}')
    if missing:
        raise SystemExit('Install requirements.txt in the active environment.\n' + '\n'.join(missing))

    try:
        print('ipykernel:', metadata.version('ipykernel'))
    except metadata.PackageNotFoundError:
        print('NOTE: ipykernel is needed for VS Code notebooks; install requirements.txt.')

    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error, root_mean_squared_error
    from matplotlib.figure import Figure
    import seaborn as sns

    # Synthetic arithmetic only: these numbers are not crop observations.
    features = pd.DataFrame({'id': [1, 2, 3, 4], 'x': [1.0, 2.0, 3.0, 4.0]})
    labels = pd.DataFrame({'id': [1, 2, 3, 4], 'y': [5.0, 8.0, 11.0, 14.0]})
    with sqlite3.connect(':memory:') as connection:
        features.to_sql('demo_features', connection, index=False)
        labels.to_sql('demo_labels', connection, index=False)
        frame = pd.read_sql_query(
            """SELECT f.id, f.x, l.y,
                      LAG(f.x) OVER (ORDER BY f.id) AS previous_x
               FROM demo_features AS f
               JOIN demo_labels AS l ON f.id = l.id
               ORDER BY f.id""",
            connection,
        )
    np.testing.assert_allclose(frame['previous_x'].iloc[1:], [1.0, 2.0, 3.0])
    model = LinearRegression().fit(frame[['x']], frame['y'])
    predicted = model.predict(frame[['x']])
    np.testing.assert_allclose(predicted, frame['y'], atol=1e-10)
    print('Synthetic check MAE:', round(mean_absolute_error(frame['y'], predicted), 10))
    print('Synthetic check RMSE:', round(root_mean_squared_error(frame['y'], predicted), 10))

    # Render and discard a test figure so no research output is implied.
    figure = Figure(figsize=(4, 3))
    axis = figure.subplots()
    sns.scatterplot(data=frame, x='x', y='y', ax=axis)
    axis.plot(frame['x'], predicted)
    axis.set_title('Synthetic environment check')
    with TemporaryDirectory(prefix='setup-check-', dir=ROOT) as directory:
        path = Path(directory) / 'check.png'
        figure.savefig(path)
        if path.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise RuntimeError('Figure rendering failed.')

    print('SQLite join/window query, regression, metrics, and plotting: OK')
    print('SETUP CHECK PASSED')
    print('No USDA data have been downloaded and no yield forecast has been estimated.')

if __name__ == '__main__':
    main()
