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
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_ROOT_DIR, "data")
_DB_PATH = os.path.join(_DATA_DIR, "dashboard.db")
_SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")
_BACKUP_DIR = os.path.join(_DATA_DIR, "backups")
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
    os.makedirs(_DATA_DIR, exist_ok=True)
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
    conn.commit()


def get_db_connection():
    """Open (creating if needed) the app database under data/ and ensure its schema.

    Every page calls this instead of resolving paths itself, so the database
    location is defined in exactly one place.
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    init_db(conn)
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
    os.makedirs(_DATA_DIR, exist_ok=True)
    tables = {
        "monthly_logs": "monthly_logs_export.csv",
        "salary_logs":  "salary_logs_export.csv",
        "trips_logs":   "trips_logs_export.csv",
    }
    for table, filename in tables.items():
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df.to_csv(os.path.join(_DATA_DIR, filename), index=False)
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


_FULL_LOG_COLUMNS = ['income', 'inflows', 'outflows', 'end_value', 'start_value',
                     'capital_gain', 'expenses', 'savings', 'total_income',
                     'total_income_rolling', 'cumulative_capital_gains',
                     'cumulative_savings', 'date']


def generate_full_log(c, randomized=False):
    # loading monthly logs and salary logs from database and formatting
    monthly = c.execute(""" SELECT * from monthly_logs""").fetchall()
    monthly_df = pd.DataFrame(monthly, columns=['date', 'platform', 'inflows', 'outflows', 'end_value', 'index'])

    income = c.execute(""" SELECT * from salary_logs""").fetchall()
    income_df = pd.DataFrame(income, columns=['date', 'income', 'index'])

    # nothing to compute until both positions and income exist — return an empty
    # frame with the expected columns so callers can guard on .empty
    if monthly_df.empty or income_df.empty:
        return pd.DataFrame(columns=_FULL_LOG_COLUMNS)

    monthly_df['date'] = pd.to_datetime(monthly_df['date'], format='%d/%m/%y')
    income_df['date'] = pd.to_datetime(income_df['date'], format='%d/%m/%y')
    income_df.set_index('date', inplace=True)

    # creating a monthly dataframe
    total_df = monthly_df.groupby('date').sum()[['inflows', 'outflows', 'end_value']]

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
    # zero out first month — no prior start_value available, gain is not meaningful
    full_data.loc[total_df.index[0], 'expenses'] = 0
    full_data.loc[total_df.index[0], 'capital_gain'] = 0
    full_data['total_income'] = full_data['savings'] + full_data['capital_gain']
    full_data['total_income_rolling'] = full_data['total_income'].rolling(3).mean().fillna(0)

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


def generate_trip_data(c):
    trips = c.execute("SELECT rowid, * FROM trips_logs").fetchall()
    trips_df = pd.DataFrame(trips, columns=['rowid', 'place', 'days', 'flights', 'house', 'life', 'date', 'unique_index'])
    trips_df['date'] = pd.to_datetime(trips_df['date'], format='%d/%m/%y')
    trips_df['total'] = trips_df['flights'] + trips_df['house'] + trips_df['life']
    trips_df['daily'] = trips_df['total'] / trips_df['days']
    trips_df['unique_trip'] = trips_df['place'] + ' ' + trips_df['date'].dt.strftime('%b %Y')
    trips_df['label'] = trips_df['place'] + ' — ' + trips_df['date'].dt.strftime('%b %Y')
    trips_df.sort_values('date', ascending=True, inplace=True)
    return trips_df
