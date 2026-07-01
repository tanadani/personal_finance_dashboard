"""IBKR Flex Query analytics — parsing, NAV reconstruction, TWR and risk statistics.

This module is deliberately Streamlit-agnostic for the pure computation paths so it
can be unit-tested in isolation; the only Streamlit dependency is the cached
orchestrator `load_ibkr`, which keys on the set of archived export hashes so the
analysed history grows as overlapping yearly exports are added.

The input CSV is a concatenated multi-section IBKR Flex export: each daily block
contains an Open Positions section, a Trades section and a Cash Transactions
section, with the section headers repeating on every block.
"""

import csv
import io
import os
import hashlib

import numpy as np
import pandas as pd
import streamlit as st

# Archived exports accumulate here so the analysed history grows past IBKR's
# 1-year export cap. Filenames are the content hash, so re-adding the same export
# is a no-op and overlapping exports dedupe cleanly.
from utils import DATA_DIR
ARCHIVE_DIR = os.path.join(DATA_DIR, "ibkr_exports")


# --- section header signatures (matched on the leading columns) ---
POS_SIG  = ("CurrencyPrimary", "FXRateToBase", "Symbol", "Description", "ISIN", "ReportDate")
TRD_SIG  = ("CurrencyPrimary", "FXRateToBase", "AssetClass", "Symbol", "ISIN", "TradeDate")
CASH_HDR = ("CurrencyPrimary", "FXRateToBase", "Symbol", "Description", "ISIN",
            "Date/Time", "Amount", "Type", "Code")

# cash transaction Type buckets
CASH_CAPITAL_FLOW = {"Deposits/Withdrawals"}
CASH_INCOME       = {"Bond Interest Received", "Broker Interest Received",
                     "Dividends", "Payment In Lieu Of Dividends"}
CASH_COSTS        = {"Other Fees", "Broker Interest Paid", "Commission Adjustments"}

TRADING_DAYS = 252


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------

def parse_ibkr_flex(source):
    """Parse a concatenated IBKR Flex CSV into clean DataFrames.

    `source` may be a path, a bytes object, or a file-like object. Returns a dict
    with keys 'positions', 'trades', 'cash'. Raises ValueError naming any section
    that is missing entirely (so the caller can show a precise error).
    """
    # normalise the source into an iterable of text lines
    if hasattr(source, "read"):
        raw = source.read()
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    elif isinstance(source, bytes):
        text = source.decode("utf-8")
    elif isinstance(source, str) and ("\n" in source or not source.endswith(".csv")):
        text = source  # already CSV content
    else:
        with open(source, "r", newline="") as fh:
            text = fh.read()

    buffers = {"positions": [], "trades": [], "cash": []}
    headers = {}
    current = None

    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        sig6 = tuple(row[:6])
        if sig6 == POS_SIG:
            current, headers["positions"] = "positions", row
            continue
        if sig6 == TRD_SIG:
            current, headers["trades"] = "trades", row
            continue
        if tuple(row) == CASH_HDR:
            current, headers["cash"] = "cash", row
            continue
        if current is not None:
            buffers[current].append(row)

    missing = [name for name in ("positions", "trades", "cash") if name not in headers]
    if missing:
        raise ValueError(
            "CSV is missing the following IBKR section(s): "
            + ", ".join(missing)
            + ". Expected Open Positions, Trades and Cash Transactions sections."
        )

    out = {}
    for name in ("positions", "trades", "cash"):
        out[name] = pd.DataFrame(buffers[name], columns=headers[name])
    return out


# ----------------------------------------------------------------------------
# Data preparation
# ----------------------------------------------------------------------------

def prepare_positions(positions):
    df = positions.copy()
    for col in ["FXRateToBase", "Quantity", "MarkPrice", "PositionValue",
                "CostBasisMoney", "FifoPnlUnrealized"]:
        df[col] = df[col].astype(float)
    df["ReportDate"] = pd.to_datetime(df["ReportDate"], format="%Y%m%d")
    df["PositionValueGBP"] = df["PositionValue"] * df["FXRateToBase"]
    df["CostBasisGBP"] = df["CostBasisMoney"] * df["FXRateToBase"]
    df["UnrealizedPnLGBP"] = df["FifoPnlUnrealized"] * df["FXRateToBase"]
    return df


def prepare_trades(trades):
    df = trades.copy()
    # keep only real securities — drop FX conversion legs (GBP.USD etc.)
    df = df[df["AssetClass"].isin(["STK", "BOND"])].copy()
    df = df[~df["Symbol"].str.contains(".", regex=False, na=False) | (df["AssetClass"] == "BOND")]
    for col in ["FXRateToBase", "Quantity", "TradePrice", "Proceeds",
                "IBCommission", "NetCash", "CostBasis", "FifoPnlRealized"]:
        df[col] = df[col].astype(float)
    df["TradeDate"] = pd.to_datetime(df["TradeDate"], format="%Y%m%d")
    df["RealizedPnLGBP"] = df["FifoPnlRealized"] * df["FXRateToBase"]
    df["NetCashGBP"] = df["NetCash"] * df["FXRateToBase"]
    df = df.sort_values("TradeDate").reset_index(drop=True)
    return df


def prepare_cash(cash):
    df = cash.copy()
    # Date/Time has an optional ;HHMMSS suffix — strip it
    df["Date"] = pd.to_datetime(df["Date/Time"].str.split(";").str[0], format="%Y%m%d")
    df["Amount"] = df["Amount"].astype(float)
    df["FXRateToBase"] = df["FXRateToBase"].astype(float)
    df["AmountGBP"] = df["Amount"] * df["FXRateToBase"]

    def bucket(t):
        if t in CASH_CAPITAL_FLOW:
            return "Capital Flow"
        if t in CASH_INCOME:
            return "Income"
        if t in CASH_COSTS:
            return "Cost"
        return "Other"

    df["Category"] = df["Type"].map(bucket)
    df = df.sort_values("Date").reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# NAV reconstruction
# ----------------------------------------------------------------------------

def reconstruct_nav(positions, trades, cash):
    """Build a daily NAV series that separates market movement from capital flows.

    NAV(t) = sum(PositionValueGBP on t) + cumulative cash balance(t)

    The cash balance is the running sum of all cash transactions (deposits add,
    withdrawals/fees subtract, income adds) plus trade net cash. Trade net cash is
    applied on the TRADE date (not the settlement date): IBKR removes a sold
    position from the Open Positions section on the trade date, so the matching
    cash must move on the trade date too, otherwise NAV shows a multi-day phantom
    gap (e.g. the Feb-2026 sales settling in Mar-2026).

    Returns a DataFrame indexed by date with columns:
        securities_value, cash_balance, nav, capital_flow, net_deposits_cum
    """
    sec = positions.groupby("ReportDate")["PositionValueGBP"].sum().sort_index()
    idx = sec.index
    first_date = idx[0]

    # Combine every cash movement (transactions + trade settlements) into one daily
    # flow series. Flows that predate the first report date are excluded: whatever
    # they funded is already part of the opening positions (and hence nav0), so
    # counting them here would double-count. Flows on non-trading days are carried
    # forward to the next report date via an as-of (ffill) cumulative sum, so nothing
    # is silently dropped.
    flows = (cash.groupby("Date")["AmountGBP"].sum()
             .add(trades.groupby("TradeDate")["NetCashGBP"].sum(), fill_value=0)
             .sort_index())
    flows = flows[flows.index >= first_date]
    cash_balance = flows.cumsum().reindex(idx, method="ffill").fillna(0.0)

    # The running sum only recovers *changes* in cash, not its absolute level — the
    # true cash at the first date is unknown (the data rarely starts at account
    # inception). Anchoring the level at the *latest* report date (assume ~0
    # un-invested cash when fully deployed) makes NAV_latest = securities value and,
    # crucially, keeps the whole series stable no matter how far back history extends
    # as more (overlapping) yearly exports are accumulated. Without this, prepending
    # an earlier export drives early NAV toward zero and the Modified-Dietz
    # denominator explodes.
    cash_balance = cash_balance - cash_balance.iloc[-1]

    # Capital flows for the Dietz return, attributed to report-date periods the same
    # way (post-inception, with any non-trading-day flow rolled to the next report
    # date). net_deposits_cum is the cumulative series; capital_flow is the per-period
    # difference fed into the Modified-Dietz formula.
    cf_cum = (cash.loc[cash["Category"] == "Capital Flow"]
              .groupby("Date")["AmountGBP"].sum().sort_index())
    cf_cum = cf_cum[cf_cum.index >= first_date].cumsum().reindex(idx, method="ffill").fillna(0.0)
    capital_flow = cf_cum.diff()
    capital_flow.iloc[0] = cf_cum.iloc[0]
    net_deposits_cum = cf_cum

    nav = pd.DataFrame({
        "securities_value": sec,
        "cash_balance": cash_balance,
        "capital_flow": capital_flow,
        "net_deposits_cum": net_deposits_cum,
    })
    nav["nav"] = nav["securities_value"] + nav["cash_balance"]
    return nav


# ----------------------------------------------------------------------------
# Time-weighted return (daily Modified Dietz)
# ----------------------------------------------------------------------------

def compute_twr(nav_df):
    """Capital-adjusted daily return series and cumulative TWR.

    R_t = (NAV_t - NAV_{t-1} - CapitalFlow_t) / (NAV_{t-1} + 0.5 * CapitalFlow_t)
    TWR_cumulative = prod(1 + R_t) - 1
    """
    nav = nav_df["nav"]
    cf = nav_df["capital_flow"]
    prev = nav.shift()
    denom = (prev + 0.5 * cf).replace(0, np.nan)
    R = (nav - prev - cf) / denom
    R = R.fillna(0.0)

    out = pd.DataFrame(index=nav.index)
    out["return"] = R
    out["wealth_index"] = (1 + R).cumprod()
    out["twr_cum"] = out["wealth_index"] - 1
    out["drawdown"] = out["wealth_index"] / out["wealth_index"].cummax() - 1
    return out


# ----------------------------------------------------------------------------
# Drawdowns
# ----------------------------------------------------------------------------

def compute_drawdowns(wealth_index, threshold=0.02):
    """Identify drawdown episodes on a wealth-index series.

    Returns a list of dicts: peak_date, trough_date, depth (negative), recovered,
    recovery_date, recovery_days. Only episodes deeper than `threshold` are kept.
    """
    wi = wealth_index.dropna()
    peak = wi.iloc[0]
    peak_date = wi.index[0]
    trough = wi.iloc[0]
    trough_date = wi.index[0]
    in_dd = False
    episodes = []

    for date, val in wi.items():
        if val >= peak:
            # close any open episode (recovered)
            if in_dd:
                episodes.append({
                    "peak_date": peak_date, "trough_date": trough_date,
                    "depth": trough / peak - 1, "recovered": True,
                    "recovery_date": date,
                    "recovery_days": int(np.busday_count(trough_date.date(), date.date())),
                })
                in_dd = False
            peak, peak_date = val, date
            trough, trough_date = val, date
        else:
            in_dd = True
            if val < trough:
                trough, trough_date = val, date

    if in_dd:  # unrecovered episode still open at series end
        episodes.append({
            "peak_date": peak_date, "trough_date": trough_date,
            "depth": trough / peak - 1, "recovered": False,
            "recovery_date": None, "recovery_days": None,
        })

    return [e for e in episodes if e["depth"] <= -abs(threshold)]


# ----------------------------------------------------------------------------
# Risk statistics
# ----------------------------------------------------------------------------

def compute_risk_stats(twr_df, rf=0.045):
    """Performance and risk statistics from the capital-adjusted return series."""
    R = twr_df["return"]
    wi = twr_df["wealth_index"]
    n = len(R)
    stats = {}

    total_return = wi.iloc[-1] - 1
    cagr = (1 + total_return) ** (TRADING_DAYS / n) - 1 if n > 0 else np.nan
    stats["total_return"] = total_return
    stats["cagr"] = cagr

    best_idx, worst_idx = R.idxmax(), R.idxmin()
    stats["best_day"] = (R.loc[best_idx], best_idx)
    stats["worst_day"] = (R.loc[worst_idx], worst_idx)
    pos_days = int((R > 0).sum())
    stats["positive_days"] = pos_days
    stats["total_days"] = n
    stats["win_rate"] = pos_days / n if n else np.nan

    vol = R.std(ddof=1) * np.sqrt(TRADING_DAYS)
    stats["volatility"] = vol

    dd = twr_df["drawdown"]
    max_dd = dd.min()
    trough_date = dd.idxmin()
    peak_date = wi.loc[:trough_date].idxmax()
    stats["max_drawdown"] = max_dd
    stats["max_dd_peak"] = peak_date
    stats["max_dd_trough"] = trough_date

    # recovery from the max drawdown
    peak_val = wi.loc[peak_date]
    after = wi.loc[trough_date:]
    recovered = after[after >= peak_val]
    if len(recovered):
        rec_date = recovered.index[0]
        stats["recovery_days"] = int(np.busday_count(trough_date.date(), rec_date.date()))
        stats["recovery_date"] = rec_date
    else:
        stats["recovery_days"] = None
        stats["recovery_date"] = None
        stats["current_depth"] = dd.iloc[-1]

    episodes = compute_drawdowns(wi, threshold=0.02)
    stats["dd_episodes"] = len(episodes)
    stats["avg_dd_depth"] = np.mean([e["depth"] for e in episodes]) if episodes else 0.0

    # risk-adjusted ratios — require a meaningful window
    if n >= 60 and vol > 0:
        stats["sharpe"] = (cagr - rf) / vol
        downside = R[R < 0]
        dd_dev = downside.std(ddof=1) * np.sqrt(TRADING_DAYS) if len(downside) > 1 else np.nan
        stats["sortino"] = (cagr - rf) / dd_dev if dd_dev and dd_dev > 0 else np.nan
        stats["calmar"] = cagr / abs(max_dd) if max_dd < 0 else np.nan
    else:
        stats["sharpe"] = stats["sortino"] = stats["calmar"] = None

    return stats


# ----------------------------------------------------------------------------
# Per-symbol aggregates (contribution analysis + position table)
# ----------------------------------------------------------------------------

def unrealised_by_symbol(positions):
    """Wide frame: date index, one column per symbol, values = unrealised P&L GBP.

    Zero-filled so a symbol reads 0 before it is bought and after it is closed —
    which is what the stacked-area contribution chart needs.
    """
    return (positions.groupby(["ReportDate", "Symbol"])["UnrealizedPnLGBP"].sum()
            .unstack().sort_index().fillna(0.0))


def position_detail(positions, trades):
    """One row per currently-open position (latest report date)."""
    last = positions["ReportDate"].max()
    cur = positions[positions["ReportDate"] == last]
    agg = cur.groupby("Symbol").agg(
        Description=("Description", "first"),
        ISIN=("ISIN", "first"),
        Quantity=("Quantity", "sum"),
        MarkPrice=("MarkPrice", "first"),
        PositionValueGBP=("PositionValueGBP", "sum"),
        CostBasisGBP=("CostBasisGBP", "sum"),
        UnrealizedPnLGBP=("UnrealizedPnLGBP", "sum"),
    ).reset_index()

    total = agg["PositionValueGBP"].sum()
    agg["Weight"] = agg["PositionValueGBP"] / total
    agg["UnrealPct"] = agg["UnrealizedPnLGBP"] / agg["CostBasisGBP"].replace(0, np.nan)

    first_seen = positions.groupby("Symbol")["ReportDate"].min()
    agg["DaysHeld"] = agg["Symbol"].map(
        lambda s: int(np.busday_count(first_seen[s].date(), last.date()))
    )

    # 30-day P&L contribution: change in unrealised P&L over ~30 calendar days
    wide = unrealised_by_symbol(positions)
    ref_date = last - pd.Timedelta(days=30)
    ref_row = wide.loc[:ref_date]
    ref = ref_row.iloc[-1] if len(ref_row) else wide.iloc[0] * 0.0
    agg["Contrib30d"] = agg["Symbol"].map(
        lambda s: wide[s].loc[last] - ref.get(s, 0.0) if s in wide.columns else 0.0
    )
    return agg.sort_values("PositionValueGBP", ascending=False).reset_index(drop=True)


def realised_by_symbol(trades):
    return (trades.groupby("Symbol")["RealizedPnLGBP"].sum()
            .sort_values(ascending=False).reset_index())


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------

def run_validations(positions, trades, cash, nav_df, twr_df):
    """Return a list of (level, message) tuples; level is 'warning' or 'info'."""
    msgs = []

    nav = nav_df["nav"]
    nav0, nav1 = nav.iloc[0], nav.iloc[-1]
    # Only count flows/trades from the first report date onward — anything earlier is
    # baked into nav0 (and is excluded from the NAV reconstruction for the same
    # reason), so including it here would break the identity.
    first_date = positions["ReportDate"].min()
    cash_win = cash[cash["Date"] >= first_date]
    realised = trades.loc[trades["TradeDate"] >= first_date, "RealizedPnLGBP"].sum()
    upnl = positions.groupby("ReportDate")["UnrealizedPnLGBP"].sum()
    u0, u1 = upnl.iloc[0], upnl.iloc[-1]
    deposits = cash_win.loc[cash_win["Category"] == "Capital Flow", "AmountGBP"].sum()
    income = cash_win.loc[cash_win["Category"] == "Income", "AmountGBP"].sum()
    costs = cash_win.loc[cash_win["Category"] == "Cost", "AmountGBP"].sum()

    # 1. NAV reconciliation (accounts for the opening balance NAV0)
    expected = nav0 + deposits + realised + (u1 - u0) + income + costs
    resid = nav1 - expected
    if abs(resid) > 0.01 * abs(nav1):
        msgs.append(("warning",
            f"NAV reconciliation off by £{resid:,.0f} "
            f"({resid / nav1:+.2%} of NAV) — exceeds 1% tolerance."))
    else:
        msgs.append(("info",
            f"NAV reconciliation closes to £{resid:,.0f} ({resid / nav1:+.2%} of NAV)."))

    # 2. realised P&L parse check
    closing = trades[trades["Open/CloseIndicator"].astype(str).str.startswith("C")]
    if not np.isclose(closing["RealizedPnLGBP"].sum(), realised, atol=1.0):
        msgs.append(("warning",
            "Realised P&L from closing trades does not match the trade total — possible parse issue."))

    # 3. date gaps in the positions series
    dates = pd.Series(sorted(positions["ReportDate"].unique()))
    gaps = dates.diff().dropna()
    big = gaps[gaps > pd.Timedelta(days=7)]
    bgaps = [d for d in big.index
             if np.busday_count(dates[d - 1].date(), dates[d].date()) > 5]
    if bgaps:
        worst = max(np.busday_count(dates[d - 1].date(), dates[d].date()) for d in bgaps)
        msgs.append(("warning",
            f"{len(bgaps)} gap(s) > 5 business days in the positions data (largest {worst} days)."))

    # 4. implausible cumulative TWR for a ~1y window
    twr = twr_df["twr_cum"].iloc[-1]
    if abs(twr) > 1.0:
        msgs.append(("warning",
            f"Cumulative TWR is {twr:+.1%} — unusually large, check the parse."))

    return msgs


# ----------------------------------------------------------------------------
# Export archive — accumulate overlapping yearly exports into a growing history
# ----------------------------------------------------------------------------

def file_hash(b):
    return hashlib.md5(b).hexdigest()


def archive_bytes(file_bytes):
    """Persist an uploaded export, keyed by content hash. Returns the archive key.

    Idempotent: re-adding the identical file does nothing (same hash → same path).
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    key = f"{file_hash(file_bytes)}.csv"
    path = os.path.join(ARCHIVE_DIR, key)
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(file_bytes)
    return key


def list_archive():
    """Sorted list of archived export keys (filenames)."""
    if not os.path.isdir(ARCHIVE_DIR):
        return []
    return sorted(f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".csv"))


def remove_archive(key):
    path = os.path.join(ARCHIVE_DIR, key)
    if os.path.exists(path):
        os.remove(path)


def parse_many(sources):
    """Parse several exports and merge their sections, dropping the overlap.

    Each historical row is identical across exports, so an exact-row dedup collapses
    overlapping date ranges while preserving genuine intra-day duplicates (e.g. the
    same ISIN held in two sub-accounts on the same day, which differ in quantity).
    """
    buckets = {"positions": [], "trades": [], "cash": []}
    for src in sources:
        sections = parse_ibkr_flex(src)
        for name in buckets:
            buckets[name].append(sections[name])

    merged = {}
    for name, frames in buckets.items():
        merged[name] = (pd.concat(frames, ignore_index=True)
                        .drop_duplicates()
                        .reset_index(drop=True))
    return merged


# ----------------------------------------------------------------------------
# Cached orchestrator (keyed on the set of archived export hashes)
# ----------------------------------------------------------------------------

@st.cache_data(show_spinner="Parsing IBKR exports…")
def load_ibkr(archive_keys):
    """Parse + merge + reconstruct from the archived exports.

    `archive_keys` is the tuple of archive filenames (content hashes); it is the
    cache key, so adding or removing an export invalidates the cache automatically.
    """
    paths = [os.path.join(ARCHIVE_DIR, k) for k in archive_keys]
    sections = parse_many(paths)
    positions = prepare_positions(sections["positions"])
    trades = prepare_trades(sections["trades"])
    cash = prepare_cash(sections["cash"])

    nav_df = reconstruct_nav(positions, trades, cash)
    twr_df = compute_twr(nav_df)
    risk = compute_risk_stats(twr_df)
    validations = run_validations(positions, trades, cash, nav_df, twr_df)

    return {
        "positions": positions,
        "trades": trades,
        "cash": cash,
        "nav": nav_df,
        "twr": twr_df,
        "risk": risk,
        "validations": validations,
        "n_exports": len(archive_keys),
    }
