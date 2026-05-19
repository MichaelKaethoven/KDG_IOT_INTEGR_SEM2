# GoogleFindMyTools – Usage Guide

A tool to query the Google Find My API and list devices registered to your Google account.

---

## Prerequisites

- **Python 3.10+**
- **Google Chrome** installed on your system
- A Google account with Find My / Android Device Manager enabled

---

## Setup

### 1. Navigate to the project root

```powershell
cd GoogleFindMyTools
```

### 2. Create and activate a virtual environment

```powershell
# Windows
python -m venv venv
.\venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

> Key packages: `selenium`, `undetected-chromedriver`, `requests`, `cryptography`, `protobuf`, `gpsoauth`

---

## Running the tool

Activate the venv first, then run:

```powershell
# Windows
.\venv\Scripts\Activate.ps1
python setup\main.py
```

```bash
# macOS / Linux
source venv/bin/activate
python setup/main.py
```

---

## What happens on first run

1. **Chrome opens automatically** — the script launches an undetected Chrome instance and navigates to `accounts.google.com/EmbeddedSetup`.
2. **Log in to your Google account** in the browser window that appears.
3. Once login completes, the script captures the OAuth token from the browser cookie and closes Chrome.
4. **Tokens are cached** to `libs/Auth/secrets.json` — subsequent runs skip the login step entirely.
5. The tool calls the Google Nova API (`android.googleapis.com/nova/`) and prints all Find My devices associated with your account.

---

## Subsequent runs

As long as `libs/Auth/secrets.json` exists and the tokens are still valid, the tool runs without opening Chrome:

```powershell
python setup\main.py
```

If tokens expire, delete or clear `libs/Auth/secrets.json` and run again to re-authenticate.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ChromeDriver` version mismatch | The script uses `undetected-chromedriver` which auto-installs the correct driver. Make sure Chrome is up to date. |
| Login window never closes | Complete the full Google sign-in flow; the script waits up to 5 minutes for the OAuth cookie. |
| `401 Unauthorized` from API | Token has expired — delete `libs/Auth/secrets.json` and re-run. |
| macOS: Chrome won't open | Grant Python (or your terminal) permission to control Chrome when prompted by macOS. |

---

## Project structure (relevant parts)

```
GoogleFindMyTools/
├── setup/
│   └── main.py                  ← entry point
├── libs/
│   ├── Auth/
│   │   ├── auth_flow.py         ← opens Chrome, retrieves OAuth token
│   │   ├── token_cache.py       ← reads/writes secrets.json
│   │   └── secrets.json         ← created automatically on first run
│   └── NovaApi/
│       ├── nova_request.py      ← makes authenticated API calls
│       └── ListDevices/
│           └── nbe_list_devices.py  ← builds + decodes device list request
└── venv/                        ← created locally by you (gitignored)
```
