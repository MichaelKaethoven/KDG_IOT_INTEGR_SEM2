# Running the Tests

All commands run from the project root (`GoogleFindMyTools/`).

## Setup (once)

The repo ships a virtualenv at `venv/`. If it's missing or you need the test
dependencies:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install -r test\requirements.txt
```

Test dependencies are just `pytest` and `pytest-mock` (see `test/requirements.txt`).

## Run unit tests (default — fast, no network)

```powershell
.\venv\Scripts\python.exe -m pytest -m "not integration" -q
```

This runs the pure unit tests and skips anything that touches Google Find Hub,
Supabase, or the network. Expected result: **10 passed, 3 deselected**.

## Run everything (including integration tests)

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

The integration tests (`test_list_devices.py`, `test_location.py`,
`test_supabase.py`) are marked `@pytest.mark.integration` and hit live services.
They require:

- `Auth/secrets.json` — Google Find Hub credentials
- `SUPABASE_URL` / `SUPABASE_KEY` — set in your environment (or `.env`)

Without these they will fail rather than skip, so only run the full suite when
those are configured.

## Run a single file or test

```powershell
# one file
.\venv\Scripts\python.exe -m pytest test\test_middleware_publish.py -q

# one test, with print output shown
.\venv\Scripts\python.exe -m pytest test\test_subscriber_upsert.py::test_upsert_row_shape -s
```

## Notes

- Pytest config lives in `pyproject.toml` under `[tool.pytest.ini_options]`:
  `testpaths = ["test"]`, `pythonpath = ["runtime"]`, and the `integration`
  marker. That's why no `PYTHONPATH` juggling or extra flags are needed.
- `test/conftest.py` sets `MIDDLEWARE_AUTOSTART=0` (plus placeholder MQTT env
  vars) before imports, so importing `middleware` in a test does **not** spin up
  the real polling thread or MQTT client.
- On macOS/Linux the Python path is `./venv/bin/python` instead of
  `.\venv\Scripts\python.exe`.
