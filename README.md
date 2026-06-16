# Personal Finance Dashboard

A local, private Streamlit app for tracking your **savings, investments, expenses,
travel costs, and retirement outlook**. Everything is stored in a local SQLite
database on your own machine — no accounts, no cloud, no data leaves your computer.

The app starts **completely empty**. You enter your own data through the **Data
Insert** page and every chart populates automatically.

## Features

- **Analytics** — cumulative savings & returns, monthly savings/returns, monthly
  expenses (with trendline), monthly return %, and current/previous fiscal-year
  summaries with time-weighted return.
- **Investments** — per-account value, capital gains, and return % over time.
- **Projections** — forward net-worth projection from your current savings rate,
  salary growth, optional annual bonus, and expected returns; plus a retirement
  estimate (when passive income covers your expenses).
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
streamlit run app.py
```

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

## How the numbers work

For each month the app derives:

- `capital_gain = end_value − start_value − inflows + outflows`
- `expenses = income − inflows + outflows`
- `savings = income − expenses`

Records are keyed to the **1st of each month** (the Data Insert page enforces this
with a month/year picker). If the same account is entered twice for the same month,
the values are summed.

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
│   ├── Analytics.py
│   ├── Investments.py
│   ├── Projections.py
│   ├── Travels.py
│   └── IBKR_Direct_Sleeve.py   # only shown when IBKR is enabled
└── data/                       # SQLite DB, CSV exports, settings.json, IBKR
                                #   archives (all gitignored — your data)
```

## Data & privacy

Everything you enter lives under `data/` — the SQLite database
(`data/dashboard.db`), CSV mirrors, your feature settings (`data/settings.json`),
and any IBKR exports. The whole `data/` folder is **gitignored**, so your financial
data and personal settings (including whether IBKR is enabled) are never committed.
This is what keeps one codebase serving both a personal install and a shareable,
empty clone. CSV mirrors of each table are regenerated whenever you insert or edit.
