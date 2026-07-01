import os
import datetime as dt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ibkr_analytics as ib
from utils import DATA_DIR

DEFAULT_CSV = os.path.join(DATA_DIR, "Daily_Positions_MTM.csv")


def _fmt_gbp(x):
    return f"£{x:,.0f}"


def _fmt_pct(x, dp=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{dp}%}"


# ----------------------------------------------------------------------------
# Render helpers (one per panel)
# ----------------------------------------------------------------------------

def render_kpi_strip(data):
    pos, trades, nav = data["positions"], data["trades"], data["nav"]
    last = pos["ReportDate"].max()
    current_nav = nav["nav"].iloc[-1]
    # capital committed across the window: opening NAV (deployed before the data
    # starts) plus net external flows during it
    capital_committed = nav["nav"].iloc[0] + nav["net_deposits_cum"].iloc[-1]
    cum_twr = data["risk"]["total_return"]
    unreal = pos.loc[pos["ReportDate"] == last, "UnrealizedPnLGBP"].sum()
    realised = trades["RealizedPnLGBP"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current NAV", _fmt_gbp(current_nav))
    c2.metric("Capital Committed", _fmt_gbp(capital_committed))
    c3.metric("Cumulative TWR", _fmt_pct(cum_twr))
    c4.metric("Unrealised P&L", _fmt_gbp(unreal))
    c5.metric("Realised P&L", _fmt_gbp(realised))


def render_risk_panel(risk):
    st.subheader("Performance & Risk Statistics")
    left, right = st.columns(2)

    best_r, best_d = risk["best_day"]
    worst_r, worst_d = risk["worst_day"]
    with left:
        st.markdown("**Returns**")
        st.write(pd.DataFrame({
            "Metric": ["CAGR (annualised)", "Best day", "Worst day", "Win rate"],
            "Value": [
                _fmt_pct(risk["cagr"]),
                f"{best_r:+.2%} ({best_d:%d %b %Y})",
                f"{worst_r:+.2%} ({worst_d:%d %b %Y})",
                f"{risk['win_rate']:.1%} ({risk['positive_days']}/{risk['total_days']} days)",
            ],
        }).set_index("Metric"))

        st.markdown("**Risk-adjusted**")
        st.write(pd.DataFrame({
            "Metric": ["Sharpe (rf 4.5%)", "Sortino", "Calmar"],
            "Value": [
                f"{risk['sharpe']:.2f}" if risk["sharpe"] is not None else "n/a",
                f"{risk['sortino']:.2f}" if risk["sortino"] is not None else "n/a",
                f"{risk['calmar']:.2f}" if risk["calmar"] is not None else "n/a",
            ],
        }).set_index("Metric"))

    with right:
        st.markdown("**Risk**")
        dd_range = f"{risk['max_dd_peak']:%d %b %Y} → {risk['max_dd_trough']:%d %b %Y}"
        if risk["recovery_days"] is not None:
            recovery = f"{risk['recovery_days']} business days"
        else:
            recovery = f"unrecovered (now {risk.get('current_depth', 0):.1%})"
        st.write(pd.DataFrame({
            "Metric": ["Annualised volatility", "Max drawdown", "Max DD window",
                       "Days to recover", "Drawdown episodes > 2%", "Average DD depth"],
            "Value": [
                _fmt_pct(risk["volatility"]),
                _fmt_pct(risk["max_drawdown"]),
                dd_range,
                recovery,
                str(risk["dd_episodes"]),
                _fmt_pct(risk["avg_dd_depth"]),
            ],
        }).set_index("Metric"))


def render_nav_charts(data, benchmark=None):
    nav, twr = data["nav"], data["twr"]

    # Chart A — NAV vs capital deployed
    st.subheader("Portfolio NAV vs Capital Deployed")
    flows = nav[nav["capital_flow"] != 0]
    figA = go.Figure()
    figA.add_trace(go.Scatter(x=nav.index, y=nav["nav"], mode="lines",
                              name="NAV (£)", line=dict(width=2)))
    figA.add_trace(go.Bar(x=flows.index, y=flows["capital_flow"],
                          name="Capital flow (£)", marker_color="#9467bd", opacity=0.6))
    figA.add_trace(go.Scatter(x=nav.index, y=nav["net_deposits_cum"], mode="lines",
                              name="Cumulative net deposits (£)", line=dict(dash="dot"),
                              yaxis="y2"))
    figA.update_layout(
        xaxis_title=None, yaxis_title="NAV (£)",
        yaxis2=dict(title="Net deposits (£)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(figA)

    # Chart B — capital-adjusted cumulative return
    st.subheader("Capital-Adjusted Return")
    figB = go.Figure()
    figB.add_trace(go.Scatter(x=twr.index, y=twr["twr_cum"], mode="lines",
                              name="Portfolio TWR"))
    if benchmark is not None:
        bench_cum = (1 + benchmark["return"]).cumprod() - 1
        figB.add_trace(go.Scatter(x=benchmark["date"], y=bench_cum, mode="lines",
                                  name="Benchmark", line=dict(dash="dash")))
    figB.update_layout(xaxis_title=None, yaxis_title="Cumulative return",
                       yaxis_tickformat=".0%")
    st.plotly_chart(figB)

    # Chart C — rolling 30-day annualised volatility
    st.subheader("30-Day Rolling Volatility")
    roll_vol = twr["return"].rolling(30).std() * np.sqrt(ib.TRADING_DAYS)
    figC = px.line(x=roll_vol.index, y=roll_vol)
    figC.update_layout(xaxis_title=None, yaxis_title="Annualised volatility",
                       yaxis_tickformat=".0%")
    st.plotly_chart(figC)

    # Chart D — drawdown underwater plot
    st.subheader("Drawdown from Peak")
    figD = go.Figure()
    figD.add_trace(go.Scatter(x=twr.index, y=twr["drawdown"], fill="tozeroy",
                              mode="lines", line=dict(color="#d62728"), name="Drawdown"))
    figD.update_layout(xaxis_title=None, yaxis_title="Drawdown", yaxis_tickformat=".0%")
    st.plotly_chart(figD)


def render_contribution(data):
    pos, trades = data["positions"], data["trades"]

    # Chart E — unrealised P&L contribution by symbol over time
    st.subheader("Unrealised P&L Contribution by Position")
    wide = ib.unrealised_by_symbol(pos)
    figE = px.area(wide, x=wide.index, y=wide.columns)
    figE.update_layout(xaxis_title=None, yaxis_title="Unrealised P&L (£)",
                       legend_title="Symbol")
    # annotate realised P&L booked when a position is closed (unrealised → 0)
    closes = trades[trades["Open/CloseIndicator"].astype(str).str.startswith("C")]
    booked = closes.groupby(["TradeDate", "Symbol"])["RealizedPnLGBP"].sum().reset_index()
    for _, r in booked.iterrows():
        figE.add_annotation(x=r["TradeDate"], y=0, text=f"{r['Symbol']} {r['RealizedPnLGBP']:+,.0f}",
                            showarrow=True, arrowhead=1, ay=-30, font=dict(size=9))
    st.plotly_chart(figE)

    # Chart F — weight vs contribution efficiency
    st.subheader("Position Efficiency — Weight vs Contribution")
    detail = ib.position_detail(pos, trades)
    realised_map = trades.groupby("Symbol")["RealizedPnLGBP"].sum()
    detail = detail.copy()
    detail["TotalPnL"] = detail["UnrealizedPnLGBP"] + detail["Symbol"].map(realised_map).fillna(0)
    detail["ContribPct"] = detail["TotalPnL"] / detail["CostBasisGBP"].replace(0, np.nan)
    figF = px.scatter(detail, x="Weight", y="ContribPct", size="PositionValueGBP",
                      text="Symbol", hover_name="Symbol")
    figF.update_traces(textposition="top center")
    # reference: portfolio aggregate return on cost (positions above the line outperformed)
    port_return = detail["TotalPnL"].sum() / detail["CostBasisGBP"].sum()
    figF.add_hline(y=port_return, line_dash="dash", line_color="grey",
                   annotation_text=f"Portfolio avg {port_return:.1%}")
    figF.update_layout(xaxis_title="Weight in portfolio", yaxis_title="Return on cost basis",
                       xaxis_tickformat=".0%", yaxis_tickformat=".0%")
    st.plotly_chart(figF)

    # Chart G — realised P&L by symbol
    st.subheader("Realised P&L by Symbol (Inception to Date)")
    rps = ib.realised_by_symbol(trades)
    rps = rps[rps["RealizedPnLGBP"] != 0]
    figG = px.bar(rps, x="RealizedPnLGBP", y="Symbol", orientation="h",
                  color="RealizedPnLGBP", color_continuous_scale=["#d62728", "#cccccc", "#2ca02c"],
                  color_continuous_midpoint=0)
    figG.update_layout(xaxis_title="Realised P&L (£)", yaxis_title=None,
                       yaxis=dict(categoryorder="total ascending"), coloraxis_showscale=False)
    st.plotly_chart(figG)


def _pnl_style(df, cols):
    def colour(v):
        if pd.isna(v):
            return ""
        return "color: #2ca02c" if v > 0 else ("color: #d62728" if v < 0 else "")
    return df.style.map(colour, subset=cols)


def render_position_table(data):
    st.subheader("Open Positions")
    detail = ib.position_detail(data["positions"], data["trades"])
    show = detail.assign(
        Description=detail["Description"].str.slice(0, 28),
    )[["Symbol", "Description", "ISIN", "Quantity", "MarkPrice", "PositionValueGBP",
       "CostBasisGBP", "UnrealizedPnLGBP", "UnrealPct", "Weight", "DaysHeld", "Contrib30d"]]
    show.columns = ["Symbol", "Description", "ISIN", "Qty", "Mark", "Value £",
                    "Cost £", "Unreal £", "Unreal %", "Weight", "Days held", "30d £"]
    styled = _pnl_style(show, ["Unreal £", "Unreal %", "30d £"]).format({
        "Qty": "{:,.0f}", "Mark": "{:,.2f}", "Value £": "£{:,.0f}", "Cost £": "£{:,.0f}",
        "Unreal £": "£{:,.0f}", "Unreal %": "{:.1%}", "Weight": "{:.1%}", "30d £": "£{:,.0f}",
    })
    st.dataframe(styled, width="stretch")


def render_logs(data):
    st.subheader("Trade & Cash Event Logs")
    trades, cash = data["trades"], data["cash"]
    tab_trades, tab_cash = st.tabs(["Trades", "Cash events"])

    with tab_trades:
        t = trades.sort_values("TradeDate", ascending=False).copy()
        t["Side"] = t["Buy/Sell"].str.title()
        view = t[["TradeDate", "Side", "Symbol", "Quantity", "TradePrice",
                  "NetCashGBP", "RealizedPnLGBP"]].rename(columns={
            "TradeDate": "Date", "Quantity": "Qty", "TradePrice": "Price",
            "NetCashGBP": "Net cash £", "RealizedPnLGBP": "Realised £"})
        styled = _pnl_style(view, ["Realised £"]).format({
            "Date": lambda d: d.strftime("%d %b %Y"), "Qty": "{:,.0f}",
            "Price": "{:,.2f}", "Net cash £": "£{:,.0f}", "Realised £": "£{:,.0f}"})
        st.dataframe(styled, width="stretch")

    with tab_cash:
        cat_colour = {"Capital Flow": "#1f77b4", "Income": "#2ca02c",
                      "Cost": "#d62728", "Other": "#7f7f7f"}
        cs = cash.sort_values("Date", ascending=False).copy()
        view = cs[["Date", "Category", "Type", "Amount", "AmountGBP", "Symbol", "Description"]]
        view = view.rename(columns={"Amount": "Amount (ccy)", "AmountGBP": "Amount £"})

        def colour_cat(v):
            return f"color: {cat_colour.get(v, '#000')}"
        styled = (view.style
                  .map(colour_cat, subset=["Category"])
                  .format({"Date": lambda d: d.strftime("%d %b %Y"),
                           "Amount (ccy)": "{:,.2f}", "Amount £": "£{:,.2f}"}))
        st.dataframe(styled, width="stretch")


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

st.title("IBKR Direct Sleeve — Analytics")

uploaded = st.file_uploader(
    "Upload IBKR Flex Query CSV (each yearly export is added to the running history)",
    type="csv",
)
if uploaded is not None:
    ib.archive_bytes(uploaded.getvalue())

archive_keys = ib.list_archive()

# first run: seed the history from the bundled export so the page works out of the box
if not archive_keys and os.path.exists(DEFAULT_CSV):
    with open(DEFAULT_CSV, "rb") as fh:
        ib.archive_bytes(fh.read())
    archive_keys = ib.list_archive()

if not archive_keys:
    st.info("Upload an IBKR Flex Query CSV to begin.")
    st.stop()

try:
    data = ib.load_ibkr(tuple(archive_keys))
except ValueError as e:
    st.error(str(e))
    st.stop()
except Exception as e:  # noqa: BLE001 — surface any parse failure cleanly
    st.error(f"Could not process the file: {e}")
    st.stop()

# coverage summary + archive management
pos_dates = data["positions"]["ReportDate"]
st.caption(
    f"📁 {data['n_exports']} export(s) merged · "
    f"{pos_dates.min():%d %b %Y} → {pos_dates.max():%d %b %Y} · "
    f"{pos_dates.nunique()} trading days"
)

with st.expander(f"Manage archived exports ({len(archive_keys)})"):
    st.caption("Each yearly export is stored and merged into the history above. "
               "Overlapping date ranges are de-duplicated automatically.")
    for key in archive_keys:
        path = os.path.join(ib.ARCHIVE_DIR, key)
        added = dt.datetime.fromtimestamp(os.path.getmtime(path))
        size_kb = os.path.getsize(path) / 1024
        row_l, row_r = st.columns([5, 1])
        row_l.write(f"`{key[:12]}…`  ·  added {added:%d %b %Y %H:%M}  ·  {size_kb:.0f} KB")
        if row_r.button("Remove", key=f"rm_{key}"):
            ib.remove_archive(key)
            st.rerun()

# optional benchmark overlay (date,return)
benchmark = None
with st.expander("Optional: upload a benchmark CSV (columns: date, return)"):
    bench_file = st.file_uploader("Benchmark CSV", type="csv", key="benchmark")
    if bench_file is not None:
        try:
            benchmark = pd.read_csv(bench_file)
            benchmark.columns = [c.strip().lower() for c in benchmark.columns]
            if not {"date", "return"}.issubset(benchmark.columns):
                raise ValueError("benchmark CSV must have 'date' and 'return' columns")
            benchmark["date"] = pd.to_datetime(benchmark["date"])
            benchmark["return"] = benchmark["return"].astype(float)
        except Exception as e:  # noqa: BLE001
            st.warning(f"Ignoring benchmark file: {e}")
            benchmark = None

# validation messages
for level, msg in data["validations"]:
    if level == "warning":
        st.warning(msg)

render_kpi_strip(data)
st.divider()
render_risk_panel(data["risk"])
st.divider()
render_nav_charts(data, benchmark)
st.divider()
render_contribution(data)
st.divider()
render_position_table(data)
st.divider()
render_logs(data)
