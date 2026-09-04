import sqlite3
import pandas as pd
import os
import json
import plotly
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import numpy as np
import datetime as dt

_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]

# All 'date' columns store the 1st of a month as ISO text (YYYY-MM-DD) — the
# only format SQLite's MIN/MAX/ORDER BY sort correctly as plain strings, and
# unambiguous unlike a two-digit year. Every page reads/writes dates through
# this constant so the whole app stays on one format.
DATE_FORMAT = "%Y-%m-%d"


def month_input(label, value=None, key=None):
    """Render a month/year picker and return the 1st of the selected month.

    Records in this app are always keyed to the 1st of a month, so this
    replaces st.date_input where a full calendar would let users pick
    other days.
    """
    if value is None:
        value = dt.date.today()
    value = value.replace(day=1)

    years = list(range(value.year - 5, value.year + 2))

    col1, col2 = st.columns(2)
    with col1:
        month = st.selectbox(f"{label} (month)", _MONTH_NAMES, index=value.month - 1,
                             key=f"{key}_month" if key else None)
    with col2:
        year = st.selectbox(f"{label} (year)", years, index=years.index(value.year),
                            key=f"{key}_year" if key else None)

    return dt.date(year, _MONTH_NAMES.index(month) + 1, 1)


# Application root (where utils.py lives). The database and any generated CSV
# exports live under data/, keeping all user data in one gitignored folder.
# Set the FINANCE_DATA_DIR environment variable to relocate the data folder,
# e.g. into a cloud-synced directory shared across devices (see README,
# "Syncing between devices").
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FINANCE_DATA_DIR") or os.path.join(_ROOT_DIR, "data")
_DB_PATH = os.path.join(DATA_DIR, "dashboard.db")
_SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
_BACKUP_DIR = os.path.join(DATA_DIR, "backups")
_BACKUP_KEEP = 20


def get_setting(key, default=None):
    """Read a persisted feature/preference flag from data/settings.json.

    The file is gitignored and absent by default, so a freshly cloned (generic)
    app gets the code defaults — e.g. IBKR off.
    """
    try:
        with open(_SETTINGS_PATH) as f:
            return json.load(f).get(key, default)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def set_setting(key, value):
    """Persist a single setting to data/settings.json (creating it if needed)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    data = {}
    try:
        with open(_SETTINGS_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    data[key] = value
    with open(_SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def init_db(conn):
    """Create all tables if they don't exist yet.

    Safe and cheap to call on every page load, so the app runs against a
    brand-new (empty) database without any manual setup.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_logs (
            date         TEXT,
            account      TEXT,
            inflows      INTEGER,
            outflows     INTEGER,
            end_value    INTEGER,
            unique_index INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS salary_logs (
            date         TEXT,
            income       INTEGER,
            unique_index INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trips_logs (
            place        TEXT,
            days         INTEGER,
            flights      INTEGER,
            home         INTEGER,
            life         INTEGER,
            date         TEXT,
            unique_index INTEGER
        )
    """)
    # Private pensions live in their own table because the money is locked
    # (illiquid until access age) and must never be summed into spendable
    # net-worth / runway figures. Snapshots are sporadic — one row each time
    # the user logs into a provider — so `value` is the pot value on `date`
    # and `contribution` is the gross monthly amount going in at that time.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pension_logs (
            date         TEXT,
            provider     TEXT,
            contribution INTEGER,
            value        INTEGER,
            unique_index INTEGER
        )
    """)
    # Money moving between two *tracked* accounts — a bond account paying its
    # coupon into a current account, a rebalance from cash into a broker.
    # monthly_logs' inflows/outflows are assumed to be external (savings is
    # defined as their net), so an internal move entered there would either
    # inflate savings or misattribute the return. Recording it here instead
    # keeps both legs tied to one amount: they are expanded into an outflow on
    # from_account and an inflow on to_account at read time, so they cancel in
    # the household totals while still crediting the return to the account that
    # actually earned it. See load_monthly_positions.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_flows (
            date         TEXT,
            from_account TEXT,
            to_account   TEXT,
            amount       INTEGER,
            kind         TEXT
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Schema versioning
#
# init_db's CREATE TABLE IF NOT EXISTS only handles brand-new databases; any
# change to *existing* tables must be a numbered migration in _migrate_db so
# that older databases in the wild (a friend's install, another device) upgrade
# themselves on the first launch after a code update.
#
# To change the schema: bump _SCHEMA_VERSION, add an `if version < N:` block
# at the marked spot in _migrate_db, and never edit or reorder earlier blocks —
# any copy of the app may be starting from any past version.
# ---------------------------------------------------------------------------
_SCHEMA_VERSION = 2


def _migrate_db(conn):
    """Bring an existing database up to _SCHEMA_VERSION, snapshotting it first.

    The database records its schema version in SQLite's built-in
    PRAGMA user_version (0 for databases created before versioning existed).
    Runs at most once per version bump — a no-op on every launch after that.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= _SCHEMA_VERSION:
        return

    backup_db(conn)  # last-known-good snapshot before touching the schema

    # v1: baseline schema (monthly_logs, salary_logs, trips_logs). Tables are
    # created by init_db, so pre-versioning databases only need stamping.

    if version < 2:
        # dates were stored as 'dd/mm/yy' text, which sorts and compares
        # wrong at the SQL level (lexical, not chronological) and carries an
        # ambiguous two-digit year. Rewrite every date column to ISO
        # (DATE_FORMAT) — the only text format SQLite orders correctly.
        for table in ("monthly_logs", "salary_logs", "trips_logs", "pension_logs"):
            rows = conn.execute(f"SELECT rowid, date FROM {table}").fetchall()
            for rowid, old_date in rows:
                new_date = dt.datetime.strptime(old_date, "%d/%m/%y").strftime(DATE_FORMAT)
                conn.execute(f"UPDATE {table} SET date = ? WHERE rowid = ?", (new_date, rowid))

    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    conn.commit()


def get_db_connection():
    """Open (creating if needed) the app database under data/ and ensure its schema.

    Every page calls this instead of resolving paths itself, so the database
    location is defined in exactly one place.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    init_db(conn)
    _migrate_db(conn)
    return conn


def get_currency():
    """Currency symbol used across the app.

    Set via the sidebar control (see render_controls) and persisted in session
    state; defaults to £ so pages render correctly even before it's been set.
    """
    return st.session_state.get("currency", "£")


def _persist_ibkr():
    set_setting("enable_ibkr", st.session_state["enable_ibkr"])


def render_controls():
    """Render shared settings in the sidebar and return whether IBKR is enabled.

    Called once per run by the navigation router (app.py). Rendering the widgets
    on every run is what makes their values persist across pages — Streamlit
    drops a widget's state once it stops being instantiated.

    The IBKR toggle is persisted to data/settings.json so it survives restarts
    and defaults to off for a freshly cloned app.
    """
    # seed the IBKR flag from the persisted setting on first load this session
    if "enable_ibkr" not in st.session_state:
        st.session_state["enable_ibkr"] = bool(get_setting("enable_ibkr", False))

    with st.sidebar:
        st.selectbox(
            "Currency",
            ["£", "€", "$", "¥", "CHF", "kr"],
            key="currency",
            help="Symbol used across all charts and figures.",
        )
        st.toggle(
            "Randomize data",
            key="randomize",
            help="Scale every figure by a random factor so the dashboard can be demoed without exposing real numbers.",
        )
        with st.expander("⚙️ Settings"):
            st.toggle(
                "Enable IBKR brokerage analytics",
                key="enable_ibkr",
                on_change=_persist_ibkr,
                help="Adds the IBKR Direct Sleeve page for analyzing Interactive Brokers Flex Query exports.",
            )

    return st.session_state["enable_ibkr"]


def backup_db(conn, keep=_BACKUP_KEEP):
    """Snapshot the database to data/backups/ before a mutation, keeping the last `keep`.

    Unlike export_db_to_csv (which overwrites the same flat CSV mirrors on every
    save), this keeps timestamped, point-in-time copies of the whole SQLite file,
    so an accidental edit or delete can be recovered. Call it *before* applying a
    mutation so the snapshot captures the last-known-good state.

    Uses the SQLite online backup API rather than a file copy, so the snapshot is
    transactionally consistent even if the source is mid-write. Failures are
    surfaced as a Streamlit warning rather than silently swallowed.
    """
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest_path = os.path.join(_BACKUP_DIR, f"dashboard_{stamp}.db")
    try:
        dest = sqlite3.connect(dest_path)
        try:
            conn.backup(dest)
        finally:
            dest.close()
    except Exception as e:
        # a missing backup must not block the user's save, but they should know
        st.warning(f"Could not write a database backup before this change: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)  # don't leave a truncated snapshot behind
        return

    # prune oldest snapshots beyond the retention limit (lexical sort == chronological)
    snapshots = sorted(
        f for f in os.listdir(_BACKUP_DIR)
        if f.startswith("dashboard_") and f.endswith(".db")
    )
    for stale in snapshots[:-keep]:
        try:
            os.remove(os.path.join(_BACKUP_DIR, stale))
        except OSError:
            pass


def export_db_to_csv(conn):
    """Export all database tables to CSV files under data/, overwriting previous exports."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tables = {
        "monthly_logs": "monthly_logs_export.csv",
        "salary_logs":  "salary_logs_export.csv",
        "trips_logs":   "trips_logs_export.csv",
        "pension_logs": "pension_logs_export.csv",
        "account_flows": "account_flows_export.csv",
    }
    for table, filename in tables.items():
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df.to_csv(os.path.join(DATA_DIR, filename), index=False)
        except Exception:
            pass  # table may not exist yet


def randomize(df):
    randomized_df = df.copy()
    for col in randomized_df.columns:
        # Generate uniform random values between 0 and 2 * original value
        randomized_df[col] = np.random.uniform(
            low=0,
            high=2 * randomized_df[col].values
        )
    return randomized_df


# ---------------------------------------------------------------------------
# Cross-account flows
#
# Both kinds expand to exactly the same pair of legs (an outflow on the payer,
# an inflow on the receiver) — the arithmetic is identical, and in both cases
# the payer's capital gain comes out right: a distribution leaves the payer's
# valuation untouched, so it books as gain, while a capital transfer takes the
# value with it, so it books as nothing. The kind records *why* the money moved,
# which is what lets the Investments page split an account's capital gain into
# the income it paid out and the price move underneath.
# ---------------------------------------------------------------------------
FLOW_DISTRIBUTION = "distribution"
FLOW_TRANSFER = "transfer"

FLOW_KIND_LABELS = {
    FLOW_DISTRIBUTION: "Distribution (interest / coupon / dividend)",
    FLOW_TRANSFER: "Transfer (moving capital)",
}

_FLOW_COLUMNS = ['rowid', 'date', 'from_account', 'to_account', 'amount', 'kind']


def load_account_flows(c):
    """Load cross-account flows as a dataframe, oldest first.

    Returns an empty frame with the expected columns when none are recorded,
    so callers can guard on `.empty` and still reference columns. `rowid` is
    included for edit/delete.
    """
    rows = c.execute(
        "SELECT rowid, date, from_account, to_account, amount, kind FROM account_flows"
    ).fetchall()
    df = pd.DataFrame(rows, columns=_FLOW_COLUMNS)
    if df.empty:
        return df

    df['date'] = pd.to_datetime(df['date'], format=DATE_FORMAT)
    df['amount'] = df['amount'].astype(float)
    return df.sort_values(['date', 'from_account']).reset_index(drop=True)


_POSITION_COLUMNS = ['date', 'account', 'inflows', 'outflows', 'end_value',
                     'flow_in', 'flow_out', 'dist_in', 'dist_out']


def load_monthly_positions(c, warn=True):
    """Monthly account positions, with cross-account flows folded in.

    The single source of truth for "what each account did each month", shared by
    Analytics (via generate_full_log) and Investments so the two can't drift.
    One row per (account, month), duplicate entries for the same pair summed.

    `inflows` and `outflows` come back with each account's leg of any recorded
    account_flows row already added in, so the usual
    `end_value − start_value − inflows + outflows` gives the right capital gain
    without the caller knowing flows exist. The legs are also returned
    separately (`flow_in`/`flow_out`, and the distribution-only `dist_in`/
    `dist_out`) for callers that need to break the figure back apart.

    Because a flow adds the same amount to one account's inflows and another's
    outflows, it cancels exactly when accounts are summed — household savings
    and expenses are untouched by construction. That guarantee only holds if
    both legs are applied, so a flow whose from- or to-account has no position
    row that month is skipped whole rather than half-applied, and reported when
    `warn` is set.
    """
    rows = c.execute(
        "SELECT date, account, inflows, outflows, end_value FROM monthly_logs"
    ).fetchall()
    positions = pd.DataFrame(rows, columns=['date', 'account', 'inflows', 'outflows', 'end_value'])
    if positions.empty:
        return pd.DataFrame(columns=_POSITION_COLUMNS)

    positions['date'] = pd.to_datetime(positions['date'], format=DATE_FORMAT)
    positions = (positions.groupby(['account', 'date'], as_index=False)
                 [['inflows', 'outflows', 'end_value']].sum())
    for col in ('flow_in', 'flow_out', 'dist_in', 'dist_out'):
        positions[col] = 0.0

    flows = load_account_flows(c)
    if not flows.empty:
        logged = set(zip(positions['account'], positions['date']))
        both_legs_logged = flows.apply(
            lambda f: (f['from_account'], f['date']) in logged
            and (f['to_account'], f['date']) in logged,
            axis=1,
        )
        applied = flows[both_legs_logged]
        skipped = flows[~both_legs_logged]

        if not skipped.empty and warn:
            months = ", ".join(sorted(skipped['date'].dt.strftime('%b %Y').unique()))
            st.warning(
                f"{len(skipped)} cross-account flow(s) ignored ({months}) — both the "
                "paying and the receiving account need a position row in that month. "
                "Add the missing account position on the Data Insert page."
            )

        if not applied.empty:
            positions = positions.set_index(['account', 'date'])
            distributions = applied[applied['kind'] == FLOW_DISTRIBUTION]
            for col, source, key in (
                ('flow_out', applied, 'from_account'),
                ('flow_in', applied, 'to_account'),
                ('dist_out', distributions, 'from_account'),
                ('dist_in', distributions, 'to_account'),
            ):
                legs = (source.groupby([key, 'date'])['amount'].sum()
                        .rename_axis(['account', 'date']))
                positions[col] = legs.reindex(positions.index).fillna(0.0)
            positions['inflows'] = positions['inflows'] + positions['flow_in']
            positions['outflows'] = positions['outflows'] + positions['flow_out']
            positions = positions.reset_index()

    return (positions[_POSITION_COLUMNS]
            .sort_values(['account', 'date'])
            .reset_index(drop=True))


_FULL_LOG_COLUMNS = ['income', 'inflows', 'outflows', 'end_value', 'start_value',
                     'capital_gain', 'expenses', 'savings', 'total_savings',
                     'total_savings_rolling', 'cumulative_capital_gains',
                     'cumulative_savings', 'date']


def generate_full_log(c, randomized=False):
    # loading monthly logs and salary logs from database and formatting.
    # positions come through the shared loader, so cross-account flows are
    # already in inflows/outflows — a no-op at this level, since summing the
    # accounts cancels both legs of every flow, which is exactly what keeps
    # savings and expenses free of internal transfers.
    monthly_df = load_monthly_positions(c)

    income = c.execute(""" SELECT * from salary_logs""").fetchall()
    income_df = pd.DataFrame(income, columns=['date', 'income', 'index'])

    # nothing to compute until both positions and income exist — return an empty
    # frame with the expected columns so callers can guard on .empty
    if monthly_df.empty or income_df.empty:
        return pd.DataFrame(columns=_FULL_LOG_COLUMNS)

    income_df['date'] = pd.to_datetime(income_df['date'], format=DATE_FORMAT)
    income_df.set_index('date', inplace=True)

    # creating a monthly dataframe
    total_df = monthly_df.groupby('date')[['inflows', 'outflows', 'end_value']].sum()

    # creating random option
    if randomized:
        total_df = randomize(total_df)
        income_df = randomize(income_df)

    # calculating capital gains, incomes and expenses and creating a merged dataframe
    total_df['start_value'] = total_df['end_value'].shift().fillna(0)
    total_df['capital_gain'] = total_df['end_value'] - total_df['start_value'] - total_df['inflows'] + total_df['outflows']
    full_data = income_df.merge(total_df, left_index=True, right_index=True, how='outer')
    full_data['expenses'] = full_data['income'] - full_data['inflows'] + full_data['outflows']
    full_data['savings'] = full_data['income'] - full_data['expenses']
    # first month: no prior start_value, so gain/expenses aren't meaningful and
    # are zeroed — but savings is kept (= net inflows), because it carries the
    # opening balances into the cumulative series. Monthly charts that would be
    # distorted by that opening amount exclude the first month at render time.
    full_data.loc[total_df.index[0], 'expenses'] = 0
    full_data.loc[total_df.index[0], 'capital_gain'] = 0
    # what the month actually added to liquid net worth: the part of income not
    # spent, plus what the investments did. Not "income" — it leaves out the
    # income that was spent, and counts gains that were never income at all.
    full_data['total_savings'] = full_data['savings'] + full_data['capital_gain']
    full_data['total_savings_rolling'] = full_data['total_savings'].rolling(3).mean().fillna(0)

    # drop months with missing income or position data and warn the user
    rows_before = len(full_data)
    full_data = full_data.dropna()
    dropped = rows_before - len(full_data)
    if dropped > 0:
        st.warning(f"{dropped} month(s) excluded — missing income or position data for those periods.")

    # creating cumulative capital gains and savings
    full_data.loc[:, 'cumulative_capital_gains'] = full_data['capital_gain'].cumsum()
    full_data.loc[:, 'cumulative_savings'] = full_data['savings'].cumsum()
    full_data.loc[:, 'date'] = full_data.index

    return full_data


def simulate_paths(start_value, contributions, expected_return, volatility, n_sims, seed=None):
    """Monte Carlo of an investment pot under geometric Brownian motion.

    Evolves `n_sims` parallel paths one month at a time:

        assets = assets * growth + contributions[t]

    where `growth` is a log-normal factor calibrated so the expected simple
    monthly return equals expected_return / 12. Only the market return is
    random — any deterministic cash flow (savings, salary growth, a fixed
    pension contribution) must already be baked into `contributions`, a
    per-month array whose length sets the number of months simulated.

    Shared by the liquid Projections page and the Pension page so both use
    identical return maths. Returns an (n_months, n_sims) array of asset
    values after each month.
    """
    contributions = np.asarray(contributions, dtype=float)
    months = len(contributions)
    mm = expected_return / 12                 # monthly expected simple return
    ms = volatility / np.sqrt(12)             # monthly volatility
    # drift chosen so E[growth] = 1 + mm (log-normal mean correction)
    drift = np.log1p(mm) - 0.5 * ms ** 2

    rng = np.random.default_rng(seed)
    assets = np.full(int(n_sims), float(start_value))
    history = np.empty((months, int(n_sims)))
    for t in range(months):
        growth = np.exp(drift + ms * rng.standard_normal(assets.shape))
        assets = assets * growth + contributions[t]
        history[t] = assets
    return history


def generate_pension_log(c, randomized=False):
    """Load pension snapshots as a cleaned, provider-sorted dataframe.

    Returns an empty frame (no columns guaranteed) when nothing is logged yet,
    so callers guard on `.empty`. `rowid` is included for edit/delete.
    """
    rows = c.execute(
        "SELECT rowid, date, provider, contribution, value FROM pension_logs"
    ).fetchall()
    df = pd.DataFrame(rows, columns=['rowid', 'date', 'provider', 'contribution', 'value'])
    if df.empty:
        return df

    df['date'] = pd.to_datetime(df['date'], format=DATE_FORMAT)
    if randomized:
        df[['contribution', 'value']] = randomize(df[['contribution', 'value']])
    df = df.sort_values(['provider', 'date']).reset_index(drop=True)
    return df


def generate_net_worth(c, full_data, randomized=False):
    """Monthly net worth series: liquid accounts plus locked pension pots.

    Stage-1 scope — no illiquid assets or liabilities yet. Both inputs are
    sporadic relative to each other, so the series runs on the union of their
    dates with each side's last known value carried forward — e.g. a pension
    snapshot newer than the last position month still counts, on top of the
    latest logged liquid value. Dates before the first position month are
    dropped (no liquid baseline to carry forward).

    Takes the already-computed full_data (from generate_full_log) rather than
    recomputing it, so its data-quality warnings aren't emitted twice.
    """
    if full_data.empty:
        return pd.DataFrame(columns=['date', 'liquid', 'pension', 'net_worth'])

    liquid = full_data['end_value']

    pension = pd.Series(0.0, index=liquid.index)
    pensions = generate_pension_log(c, randomized=randomized)
    if not pensions.empty:
        pivot = pensions.pivot_table(index='date', columns='provider',
                                     values='value', aggfunc='last').sort_index()
        idx = liquid.index.union(pivot.index)
        liquid = liquid.reindex(idx).ffill()
        pension = pivot.reindex(idx).ffill().fillna(0).sum(axis=1)
        keep = liquid.notna()
        liquid, pension = liquid[keep], pension[keep]

    nw = pd.DataFrame({'date': liquid.index,
                       'liquid': liquid.values,
                       'pension': pension.values})
    nw['net_worth'] = nw['liquid'] + nw['pension']
    return nw


def generate_trip_data(c):
    trips = c.execute("SELECT rowid, * FROM trips_logs").fetchall()
    trips_df = pd.DataFrame(trips, columns=['rowid', 'place', 'days', 'flights', 'house', 'life', 'date', 'unique_index'])
    trips_df['date'] = pd.to_datetime(trips_df['date'], format=DATE_FORMAT)
    trips_df['total'] = trips_df['flights'] + trips_df['house'] + trips_df['life']
    trips_df['daily'] = trips_df['total'] / trips_df['days']
    trips_df['unique_trip'] = trips_df['place'] + ' ' + trips_df['date'].dt.strftime('%b %Y')
    trips_df['label'] = trips_df['place'] + ' — ' + trips_df['date'].dt.strftime('%b %Y')
    trips_df.sort_values('date', ascending=True, inplace=True)
    return trips_df


def apply_monthly_xaxis(fig, n_points, max_ticks=36):
    """Label every month on a date x-axis, when there's room to fit them.

    Plotly's default tick spacing skips months even when a chart has plenty of
    horizontal room, which is the common case here (a year or two of monthly
    data). Forcing one tick per month only helps up to a point, though — on a
    multi-decade projection the labels would overlap into noise regardless of
    chart width, so those are left on Plotly's own (readable) spacing.
    """
    if n_points <= max_ticks:
        fig.update_xaxes(dtick="M1", tickformat="%b %Y", tickangle=-45)
