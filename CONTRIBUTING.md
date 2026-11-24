# Contributing

Use Python 3.13, Node 24 and desktop Chrome. For local development in the source workspace, use the `daily` Conda environment. Install the development requirements with `python -m pip install -r requirements-dev.txt` when needed. The lint script verifies and caches the pinned Oxlint executable on first use. Set `OXLINT_BIN` to use a local executable.

```sh
python -B -m ruff check --no-cache
python -B -m ruff format --check --no-cache
python -B scripts/lint_web.py
python -B -m pytest --basetemp=.checks/pytest
python -B scripts/build.py
python -B scripts/check_browser.py
```

Set `CHROME_BIN` to the executable if the browser test cannot find Chrome. The test starts a loopback server, waits for the page to cache, closes the server and checks the workflow offline. It uses browser-owned folders for the cached page and in-memory handles for the portable page. Run native folder-picker checks manually when changing permission prompts or OS folder access.

Run `python -B scripts/validate.py` for the same sequence as CI. It writes check logs, a JUnit file and a JSON summary to `.checks/reports/`.

For a dependency update, change the pin in `scripts/fetch_vendor.py`, obtain and verify the upstream package, update the checked-in assets and review their notices. Run the build, then verify output with no network. Add synthetic regressions for changes to file operations or preview decoding.
