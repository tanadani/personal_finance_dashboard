# Personal Finance Dashboard

A local Streamlit app for tracking personal investments, income, expenses, travel
costs, retirement projections, and IBKR brokerage performance — all backed by a
local SQLite database.

## Setup

Requires Python 3.10+.

```bash
pip install streamlit pandas numpy plotly
```

## Running

```bash
streamlit run personal_finance_dashboard.py
```

Open the URL it prints (default `http://localhost:8501`). The app uses
`pages/dashboard_memory.db` as its database — it's created automatically on first
run via the **Data Insert** page.

> If you've just edited `utils.py` or `ibkr_analytics.py`, restart the Streamlit
> process — these are plain Python modules imported by the pages, and Streamlit's
> file-watcher reload only re-runs the page script, not already-imported modules.

## Pages

### Personal Finances Dashboard (home)
Landing page with a global **"Randomize data"** toggle — when enabled, every page
scales its figures by a random factor so the dashboard can be shared/demoed without
exposing real numbers.

### Analytics
Overview of savings, capital gains, and expenses over time:
- **Cumulative Savings and Returns** — stacked area chart of cumulative capital
  gains + savings, with a total line.
- **Monthly Savings and Returns** — diverging bar chart of monthly capital gain and
  savings, with a total income line.
- **Monthly Expenses** — bar chart with an OLS linear trendline.
- **Monthly Returns** — bar chart of monthly investment return %.
- **Current / Previous Fiscal Year** — dynamic Jan–Jan summaries (total savings,
  income vs. capital gains, time-weighted return).

### Investments
Per-account breakdown of the investment portfolio:
- **Investment Value by Account** — stacked bar chart of month-end value by account.
- **Capital Gains by Account** — diverging bar chart of monthly capital gain by account.
- **Capital Gain % by Account** — line chart of monthly return % by account.

### Projections
Forward-looking net-worth projection based on current savings rate, salary growth
(with annual bonus), and expected investment returns. Includes a configurable
horizon (1–30 years), a retirement estimation (years until passive income covers
expenses), and an optional detailed monthly projection table.

### Travels
Trip cost tracking:
- **Cost by Trip** — stacked bar chart (flights / accommodation / living).
- **Daily Cost by Trip** — bar chart of average daily spend per trip.
- **Annual Travel Spend** — bar chart of total travel cost per year.
- Forms to add, edit, and delete trips.

### IBKR Direct Sleeve — Analytics
Brokerage performance analytics from IBKR Flex Query CSV exports
(`ibkr_analytics.py`):
- Upload a yearly Flex Query CSV; each upload is archived (content-hashed, in
  `ibkr_exports/`, gitignored) and merged with prior exports, de-duplicating
  overlapping date ranges so history accumulates beyond IBKR's 1-year export cap.
- **KPI strip** — Current NAV, Capital Committed, Cumulative TWR, Unrealised P&L,
  Realised P&L.
- **Performance & Risk panel** — CAGR, best/worst day, win rate, Sharpe/Sortino/Calmar,
  volatility, max drawdown (with recovery), drawdown episode stats.
- **NAV vs Capital Deployed**, **Capital-Adjusted Return** (Modified-Dietz TWR, with
  optional benchmark overlay), **30-Day Rolling Volatility**, **Drawdown from Peak**.
- **Contribution analysis** — unrealised P&L by position over time, weight vs.
  contribution efficiency scatter, realised P&L by symbol.
- **Open Positions table** and **Trade & Cash event logs**.

### Data Insert
Admin page for entering and editing the underlying data: monthly account balances
(inflows/outflows/end value) and monthly income. Record dates are restricted to the
1st of the month via month/year pickers, since all monthly records are keyed that way.

## Data & privacy

`*.csv`, `*.db`, and `*.ipynb` files are gitignored — all real financial data stays
local and is never committed. CSV exports (`*_export.csv`) are regenerated
automatically whenever data is inserted or edited.
