# CRA Tax Helper

A free, open-source app that lets you fill in your Canadian federal and BC provincial tax forms right in your browser — with automatic calculations, cross-form linking, and your data saved privately on your own computer.

**Supported forms:** T1 General, BC 428, BC 479, Schedule 3, 5, 7, 8, 9, T777, T2209, Federal Worksheet

---

## Table of Contents

1. [What does this app do?](#what-does-this-app-do)
2. [Quick Start (local, no account needed)](#quick-start-local-no-account-needed)
   - [Windows](#windows)
   - [Mac](#mac)
   - [Linux](#linux)
3. [Using the App](#using-the-app)
4. [Your Data & Privacy](#your-data--privacy)
5. [Stopping and Restarting](#stopping-and-restarting)
6. [Backing Up Your Data](#backing-up-your-data)
7. [Troubleshooting](#troubleshooting)
8. [For Developers](#for-developers)

---

## What does this app do?

- **Fills in CRA tax forms** exactly as they look on paper, right in your web browser
- **Calculates automatically** — enter your income and deductions, and totals update instantly
- **Links forms together** — values flow between T1, BC 428, and schedules automatically
- **Saves your work** — your data is stored privately on your own computer (encrypted)
- **Works completely offline** — no internet connection needed after the first setup
- **No account required** — runs entirely on your machine

---

## Quick Start (local, no account needed)

You need **Docker Desktop** installed. Docker is free software that runs the app in an isolated container — you don't need to install Python, databases, or anything else.

### Step 1 — Install Docker Desktop

> If you already have Docker Desktop installed and it's running, skip to Step 2.

| Your computer | Download link |
|---|---|
| Windows | https://docs.docker.com/desktop/install/windows-install/ |
| Mac (Apple Silicon M1/M2/M3) | https://docs.docker.com/desktop/install/mac-install/ |
| Mac (Intel) | https://docs.docker.com/desktop/install/mac-install/ |
| Linux | https://docs.docker.com/desktop/install/linux-install/ |

After installing:
1. Open **Docker Desktop** from your Applications or Start Menu
2. Wait until the whale icon in the taskbar/menu bar turns **solid** (not animated) — this means Docker is ready
3. You don't need to sign in to Docker — just close the sign-in prompt if it appears

### Step 2 — Download this app

**Option A — If you know Git:**
```
git clone https://github.com/brianfong96/CRATaxHelper.git
cd CRATaxHelper
```

**Option B — Download as a ZIP (no Git needed):**
1. Go to https://github.com/brianfong96/CRATaxHelper
2. Click the green **"Code"** button
3. Click **"Download ZIP"**
4. Unzip the file somewhere easy to find (e.g. your Desktop or Documents folder)
5. Open the unzipped folder — it should contain files like `docker-compose.yml`, `README.md`, etc.

### Step 3 — Start the app

#### Windows

1. Open the `scripts` folder inside the app folder
2. Right-click **`start-local.ps1`** → **"Run with PowerShell"**
   - If you see a security warning, click **"Open"** or **"Run anyway"**
   - If PowerShell opens and immediately closes, see [Troubleshooting](#troubleshooting)
3. The script will:
   - Check Docker is running
   - Generate a private encryption key (first time only)
   - Build and start the app
   - Open your browser automatically

#### Mac

1. Open **Terminal** (search "Terminal" in Spotlight — press `⌘ Space` and type "Terminal")
2. Navigate to the app folder. For example, if you unzipped it to your Desktop:
   ```bash
   cd ~/Desktop/CRATaxHelper
   ```
3. Run the startup script:
   ```bash
   chmod +x scripts/start-local.sh
   ./scripts/start-local.sh
   ```
4. The script will set up everything and open your browser

#### Linux

Same as Mac — open a terminal, navigate to the app folder, and run:
```bash
chmod +x scripts/start-local.sh
./scripts/start-local.sh
```

### Step 4 — Open the app

Your browser should open automatically to **http://localhost:8080**

If it doesn't open automatically, open your browser and go to:
```
http://localhost:8080
```

That's it! You're running the CRA Tax Helper locally.

---

## Using the App

### Navigating between forms

Click the **year dropdown** in the top navigation bar to switch between:
- **T1 General** — the main federal return
- **BC 428** — British Columbia provincial tax
- **Schedules** (3, 5, 7, 8, 9) — capital gains, deductions, RRSP, CPP, donations
- **T777, T2209** — employment expenses, foreign tax credits
- **Federal Worksheet** — supplementary calculations

### How forms link together

When you fill in a sub-form (like Schedule 3 for capital gains), click **"Save & Return to T1"** and the value will automatically appear in the correct line of your T1. BC 428 automatically picks up your taxable income from T1.

### Saving your work

Your data saves automatically as you type (using your browser's local storage). It also saves to the local Archive service (the encrypted database on your computer) whenever you click **"Save"** or navigate between forms.

---

## Your Data & Privacy

- **All data stays on your computer** — nothing is sent to any server on the internet
- **Data is encrypted** at rest using AES-128 encryption with a key unique to your installation
- **Your encryption key** is stored in the `.env` file in the app folder — **back this up**
- The `.env` file is listed in `.gitignore` so it won't accidentally be uploaded if you use Git

---

## Stopping and Restarting

**To stop the app** (saves all your data first):
```
docker compose down
```

**To start again** (your data will still be there):

- Windows: run `scripts\start-local.ps1` again, **or**
- Mac/Linux: run `./scripts/start-local.sh` again, **or**
- From the app folder in a terminal:
  ```
  docker compose up -d
  ```

---

## Backing Up Your Data

Your tax data is stored in a Docker volume called `crataxhelper_archive_data`. To back it up:

**Mac / Linux:**
```bash
docker run --rm \
  -v crataxhelper_archive_data:/data \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/taxdata-backup.tar.gz /data
```

**Windows (PowerShell):**
```powershell
docker run --rm `
  -v crataxhelper_archive_data:/data `
  -v "${PWD}:/backup" `
  alpine tar czf /backup/taxdata-backup.tar.gz /data
```

This creates a `taxdata-backup.tar.gz` file in your app folder. Store it somewhere safe (external drive, cloud storage).

**Also back up your `.env` file** — without it, the backup cannot be decrypted.

---

## Troubleshooting

### "Docker is not installed" even after installing

- Make sure Docker Desktop is **open and fully started** (whale icon should be solid, not animated)
- Try restarting your computer after installing Docker Desktop

### PowerShell script closes immediately (Windows)

PowerShell may be blocking scripts. Run this command in PowerShell first:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
Then try running `start-local.ps1` again.

### "Port 8080 is already in use"

Another program is using port 8080. Either:
1. Stop the other program, or
2. Edit `docker-compose.yml`, change `"8080:8080"` to `"8181:8080"`, then go to `http://localhost:8181`

### The app opens but shows an error

Run this to see what went wrong:
```
docker compose logs taxhelper
```

### I lost my `.env` file

If you lose the `.env` file (and with it your encryption key), your previously saved data **cannot be recovered**. Start fresh by:
1. Running `docker compose down -v` (this deletes all saved data)
2. Running the startup script again (it will generate a new key)

---

## For Developers

### Running tests

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all unit and static analysis tests
python -m pytest tests/ -q --ignore=tests/test_e2e.py

# Run E2E browser tests (requires Playwright)
pip install playwright && playwright install chromium
python -m pytest tests/test_e2e.py -v
```

### Project structure

```
CRATaxHelper/
├── app/                    # FastAPI application
│   ├── main.py             # Routes and API endpoints
│   ├── config.py           # Environment variable settings
│   ├── calculator.py       # Tax calculation logic
│   ├── form_rules.py       # Cross-form data contract (rules engine)
│   ├── userdata.py         # Archive-backed persistence
│   ├── crypto.py           # Fernet encryption/decryption
│   └── templates/          # HTML form templates
├── archive-local/          # Local Archive sidecar (SQLite)
│   ├── main.py             # Archive API implementation
│   └── Dockerfile
├── tests/
│   ├── test_form_layout.py # Form coordinate / input placement tests
│   ├── test_cross_form.py  # Cross-form data contract tests (92 tests)
│   └── test_e2e.py         # Playwright browser E2E tests
├── scripts/
│   ├── start-local.ps1     # Windows one-click startup
│   └── start-local.sh      # Mac/Linux one-click startup
├── docker-compose.yml      # Local multi-service setup
├── Dockerfile              # Main app container
└── .env.example            # Environment variable template
```

### Deploying to Aether Atlas

```powershell
.\scripts\deploy.ps1
```

The app is also deployed as an Aether Atlas service. In that mode, `AUTH_ENABLED=true` and the real Aether Archive service is used instead of the local sidecar.
