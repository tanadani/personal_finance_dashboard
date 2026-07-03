# Personal Finance Dashboard

A local, private Streamlit app for tracking your **savings, investments, expenses,
travel costs, and retirement outlook**. Everything is stored in a local SQLite
database on your own machine — no accounts, no cloud, no data leaves your computer.

The app starts **completely empty**. You enter your own data through the **Data
Insert** page and every chart populates automatically.

## Features

- **Analytics** — liquid assets and locked pension at a glance (with
  month-over-month change on the liquid side), cumulative savings & returns,
  monthly savings/returns (with an outlier-clipping focus view), monthly
  expenses (with trendline), monthly return %, and current/previous
  fiscal-year summaries with time-weighted return.
- **Investments** — per-account value, capital gains, and return % over time,
  plus whole-portfolio risk statistics (CAGR, annualised volatility, max
  drawdown, Sharpe ratio).
- **Projections** — a Monte Carlo forward projection of your liquid assets
  (3,000 simulated paths shown as a median line with 10–90 and 25–75
  percentile bands) from your current savings rate, salary growth, optional
  annual bonus, and expected return/volatility — volatility defaults to your
  own realised history. Includes a retirement estimate (when passive income
  covers your expenses) and a "runway if you stopped today" figure.
- **Pension** — private/workplace pensions tracked separately from spendable
  money: sporadic pot snapshots per provider, a Monte Carlo projection to your
  access age (contributions grow in line with salary), and what the median pot
  means in practice (tax-free lump sum, 4%-rule monthly income).
- **Travels** — track trip costs (flights / accommodation / living) with per-trip,
  daily, and annual breakdowns.
- **Configurable currency** and an optional **"Randomize data"** demo mode that
  scales every figure by a random factor so you can share a screenshot safely.
- **Optional IBKR brokerage analytics** — an Interactive Brokers "Direct Sleeve"
  page (NAV, TWR, drawdown, contribution analysis from Flex Query CSV exports).
  **Off by default**; enable it under **⚙️ Settings** in the sidebar.

## Setup

Requires Python 3.10+.

```bash
cd finance-dashboard
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

## Running

```bash
python3 -m streamlit run app.py
```

(On macOS use `python3 -m streamlit ...` — the bare `streamlit` command is only
on your PATH if you activated the virtual environment from Setup.)

Open the URL it prints (default `http://localhost:8501`). Navigation is defined
explicitly in `app.py` via `st.navigation`, which also renders the shared sidebar
controls (currency, randomize, and the IBKR feature toggle) on every page.

> If you edit `utils.py` or `ibkr_analytics.py`, restart the Streamlit process —
> Streamlit's auto-reload re-runs page scripts but not already-imported modules.

## First steps

1. In the **sidebar**, pick your **currency** (and, if you use Interactive Brokers,
   enable IBKR analytics under **⚙️ Settings**).
2. Open **Data Insert** (left sidebar) and add:
   - your monthly **income**, and
   - your account **positions** (inflows, outflows, end-of-month value) — one row
     per account per month.
3. Visit **Analytics**, **Investments**, and **Projections** — they fill in
   automatically. Use **Travels** any time to log trips.
4. If you have a private/workplace pension, log a snapshot on the **Pension**
   page whenever you check your provider (pot value + current monthly
   contribution). It feeds the "Locked Pension" figure on Analytics and the
   retirement outlook, but is never mixed into spendable-money figures.

## Getting updates

Your data never lives in git (see **Data & privacy**), so updating the app never
touches it:

```bash
git pull
pip install -r requirements.txt   # only needed if dependencies changed
```

Then relaunch. If an update changes the database schema, the app migrates your
database automatically on the next launch — taking a timestamped safety snapshot
in `data/backups/` first.

**If you originally got the app as a zip/download** (not a git clone), switch to
a clone once and updates become one command forever:

```bash
git clone https://github.com/tanadani/personal_finance_dashboard.git
```

then copy your old `data/` folder into the new clone and delete the old copy.

## Backups & recovery

You never need to do anything — the app protects itself:

- **Timestamped snapshots** — before every insert, edit, or delete, the whole
  database is snapshotted to `data/backups/` (SQLite online backup API, so the
  copy is consistent even mid-write). The most recent 20 snapshots are kept.
- **Schema-migration snapshots** — an extra snapshot is taken automatically
  before any database schema upgrade.
- **CSV mirrors** — every table is also re-exported to a flat CSV under
  `data/` on each save (`monthly_logs_export.csv`, `salary_logs_export.csv`,
  `trips_logs_export.csv`, `pension_logs_export.csv`), a human-readable
  last-resort copy you can open in any spreadsheet.

**To recover** from a bad edit or accidental delete: close the app, pick the
snapshot you want from `data/backups/` (filenames are
`dashboard_YYYYMMDD_HHMMSS_*.db`, newest = latest), and copy it over
`data/dashboard.db`. Relaunch — done.

Because the snapshots live inside `data/`, they travel with your data folder —
but they also share its fate. If the machine itself is the risk, keep `data/`
in a cloud-synced location (see below) or copy it elsewhere periodically.

## Syncing between devices

All of your state — database, settings, backups, IBKR exports — is the `data/`
folder. Two ways to share it across machines:

- **Automatic:** set the `FINANCE_DATA_DIR` environment variable to a
  cloud-synced folder (iCloud Drive, Dropbox, …) before launching, e.g.:

  ```bash
  export FINANCE_DATA_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/finance-data"
  python3 -m streamlit run app.py
  ```

  Add the `export` line to your `~/.zshrc` to make it permanent. **Run the app
  on one device at a time** — SQLite files can be corrupted if two machines
  write through a sync service simultaneously (the automatic backups in
  `data/backups/` are your safety net if that ever happens).

- **Manual:** copy the `data/` folder (or just `data/dashboard.db`) to the other
  machine — it is a complete, self-contained transfer.

## How the numbers work

For each month the app derives:

- `capital_gain = end_value − start_value − inflows + outflows`
- `expenses = income − inflows + outflows`
- `savings = income − expenses`

Records are keyed to the **1st of each month** (the Data Insert page enforces this
with a month/year picker). If the same account is entered twice for the same month,
the values are summed.

A few conventions to be aware of:

- **First month** — the earliest month has no prior `start_value`, so its
  capital gain and expenses are zeroed, but its savings (= net inflows) are
  kept: that's your opening balances entering the cumulative totals. The
  Monthly Savings and Returns chart hides that month so the opening amount
  doesn't dwarf the real monthly bars.
- **Liquid Assets / Locked Pension** (top of Analytics) — liquid accounts and
  the latest known pension pot per provider, shown side by side rather than
  summed. Each is carried forward from its last entry, so a fresh pension
  snapshot counts even before that month's positions are logged. The
  month-over-month delta only applies to Liquid Assets, because pension
  snapshots are sporadic and would otherwise show up as fake jumps.
- **Pension money is quarantined** — it's shown on Analytics and the Pension
  page, but is never counted in spendable assets, runway, or the liquid
  Projections.
- **Projections are distributions, not lines** — both the Projections and
  Pension forecasts simulate monthly market returns (geometric Brownian
  motion) and report percentile bands; only market returns are random, while
  income, savings, bonus, and contribution growth are deterministic inputs.

## Project structure

```
finance-dashboard/
├── app.py                      # navigation router + sidebar controls
├── utils.py                    # DB connection, schema, settings, shared transforms
├── ibkr_analytics.py           # IBKR parsing (dormant unless the page is enabled)
├── requirements.txt
├── pages/
│   ├── Home.py                 # getting-started / status
│   ├── Data_Insert.py          # add / edit income and positions
│   ├── Analytics.py            # net worth, savings, expenses, fiscal years
│   ├── Investments.py          # per-account charts + portfolio risk stats
│   ├── Projections.py          # Monte Carlo forecast + retirement estimate
│   ├── Pension.py              # pension snapshots + projection to access age
│   ├── Travels.py
│   └── IBKR_Direct_Sleeve.py   # only shown when IBKR is enabled
└── data/                       # SQLite DB, CSV mirrors, settings.json, IBKR
    └── backups/                #   archives, timestamped DB snapshots
                                #   (all gitignored — your data)
```

## Data & privacy

Everything you enter lives under `data/` — the SQLite database
(`data/dashboard.db`), CSV mirrors, your feature settings (`data/settings.json`),
and any IBKR exports. The whole `data/` folder is **gitignored**, so your financial
data and personal settings (including whether IBKR is enabled) are never committed.
This is what keeps one codebase serving both a personal install and a shareable,
empty clone. CSV mirrors of each table are regenerated whenever you insert or edit.
