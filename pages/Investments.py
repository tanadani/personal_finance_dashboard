import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from utils import get_db_connection, get_currency, load_monthly_positions, apply_monthly_xaxis

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

# title
st.title('Investments')

# loading monthly logs — one row per (account, month), duplicates collapsed and
# cross-account flows already folded into inflows/outflows, so an account that
# pays its interest away to another account is still credited with earning it
monthly_df = load_monthly_positions(c)

if monthly_df.empty:
    st.info("No investment data recorded yet. Add monthly positions on the **Data Insert** page.")
    st.stop()

# calculate per-account capital gain and monthly return
monthly_df = monthly_df.sort_values(['account', 'date'])
monthly_df['start_value'] = monthly_df.groupby('account')['end_value'].shift().fillna(0)
monthly_df['capital_gain'] = monthly_df['end_value'] - monthly_df['start_value'] - monthly_df['inflows'] + monthly_df['outflows']
# zero out each account's first month — no prior start_value available, gain is not meaningful
first_idx = monthly_df.groupby('account')['date'].idxmin()
monthly_df.loc[first_idx, 'capital_gain'] = 0
monthly_df['monthly_return'] = monthly_df['capital_gain'] / monthly_df['start_value'].replace(0, np.nan)

# --- CHARTS ---

st.subheader('Investment Value by Account')

pivot = monthly_df.pivot_table(index='date', columns='account', values='end_value', aggfunc='sum').fillna(0).sort_index()

fig = px.bar(pivot, x=pivot.index, y=pivot.columns)
fig.update_layout(barmode='stack', xaxis_title=None, yaxis_title=f'Value ({CUR})', legend_title='Account')
apply_monthly_xaxis(fig, len(pivot))
st.plotly_chart(fig)

# capital gains by account
st.subheader('Capital Gains by Account')

gain_pivot = monthly_df.pivot_table(index='date', columns='account', values='capital_gain', aggfunc='sum').fillna(0).sort_index()

fig2 = px.bar(gain_pivot, x=gain_pivot.index, y=gain_pivot.columns)
fig2.update_layout(barmode='relative', xaxis_title=None, yaxis_title=f'Capital Gain ({CUR})', legend_title='Account')
apply_monthly_xaxis(fig2, len(gain_pivot))
st.plotly_chart(fig2)

# income vs price return
#
# A distribution paid to another account is added back as an outflow, so it is
# already inside the capital gain above. Splitting it out separates the cash an
# account generated from the price move underneath — the reason a coupon is
# worth recording as a distribution rather than a plain transfer. Computed off
# the months where a gain exists at all (each account's first month is zeroed
# above), so the two halves always add back to the figure shown.
gain_months = monthly_df.drop(index=first_idx)

if gain_months[['dist_out', 'dist_in']].to_numpy().sum() > 0:
    st.subheader('Income vs Price Return by Account')

    split = gain_months.groupby('account').agg(
        capital_gain=('capital_gain', 'sum'),
        income=('dist_out', 'sum'),
        received=('dist_in', 'sum'),
    )
    split['price'] = split['capital_gain'] - split['income']
    split = split[(split[['capital_gain', 'income', 'received']] != 0).any(axis=1)]

    money = lambda v: f"{CUR}{v:,.0f}"  # noqa: E731 — local display helper
    st.dataframe(
        pd.DataFrame({
            'Account': split.index,
            'Capital Gain': split['capital_gain'].map(money),
            'of which Income': split['income'].map(money),
            'of which Price': split['price'].map(money),
            'Distributions Received': split['received'].map(money),
        }),
        hide_index=True, width="stretch",
    )
    st.caption(
        "**Income** is interest, coupons and dividends this account paid out to another "
        "account, recorded as distributions on the Data Insert page. **Price** is the rest "
        "of the gain — what the holdings themselves did. **Distributions Received** is cash "
        "that arrived from another account: it is not this account's return, which is why "
        "it sits outside the capital gain rather than inside it."
    )

# capital gain % by account
st.subheader('Capital Gain % by Account')

return_pivot = monthly_df.pivot_table(index='date', columns='account', values='monthly_return', aggfunc='sum').sort_index()

fig3 = px.line(return_pivot, x=return_pivot.index, y=return_pivot.columns, markers=True)
fig3.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='Monthly Return %', legend_title='Account')
apply_monthly_xaxis(fig3, len(return_pivot))
st.plotly_chart(fig3)

# total portfolio monthly return — single source of truth shared by the
# "Total" line on the YTD chart and the Risk & Return metrics below, so every
# portfolio-level return figure on this page derives from the same series
total_df = monthly_df.groupby('date')[['inflows', 'outflows', 'end_value']].sum().sort_index()
total_df['start_value'] = total_df['end_value'].shift().fillna(0)
total_df['capital_gain'] = total_df['end_value'] - total_df['start_value'] - total_df['inflows'] + total_df['outflows']
# zero out the first month — no prior start_value available, gain is not meaningful
total_df.iloc[0, total_df.columns.get_loc('capital_gain')] = 0
total_df['monthly_return'] = total_df['capital_gain'] / total_df['start_value'].replace(0, np.nan)

# cumulative capital gain % by account, restarting each calendar year
#
# Time-weighted return: monthly returns are chained geometrically within each
# (account, year), so the line shows the year-to-date compounded return and
# drops back near zero every January. Chaining (rather than a money-weighted
# IRR) strips out the timing of the user's own deposits, which is what makes
# accounts comparable on the same chart.
st.subheader('Cumulative Capital Gain % by Account (YTD)')

ytd_df = monthly_df.copy()
ytd_df['year'] = ytd_df['date'].dt.year
ytd_df['ytd_return'] = (ytd_df.groupby(['account', 'year'])['monthly_return']
                        .transform(lambda r: (1 + r.fillna(0)).cumprod() - 1))

ytd_pivot = ytd_df.pivot_table(index='date', columns='account', values='ytd_return').sort_index()

# portfolio-wide line: compounds the combined portfolio's monthly returns —
# the exact series behind the CAGR/volatility/drawdown metrics below — so the
# total is capital-weighted (accounts summed first, larger accounts weigh more)
ytd_pivot['Total'] = ((1 + total_df['monthly_return'].fillna(0))
                      .groupby(total_df.index.year).cumprod() - 1)

fig4 = px.line(ytd_pivot, x=ytd_pivot.index, y=ytd_pivot.columns, markers=True)
fig4.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='YTD Return %', legend_title='Account')
fig4.update_traces(selector=dict(name='Total'), line=dict(width=3.5, color='#444444'))

# vertical marker at each January so the reset reads as a new year starting,
# not as a crash in returns; skipped for the first year (nothing resets there)
for boundary_year in sorted(ytd_df.loc[ytd_df['year'] > ytd_df['year'].min(), 'year'].unique()):
    fig4.add_vline(
        # epoch ms, not a Timestamp: plotly's vline annotation placement chokes
        # on datetime coordinates (tries to average them as numbers)
        x=pd.Timestamp(int(boundary_year), 1, 1).value / 1e6,
        line_dash="dash", line_width=1.5, line_color="rgba(214,120,42,0.75)",
        annotation_text=str(boundary_year), annotation_position="top left",
        annotation_font_color="rgba(214,120,42,0.9)",
    )
apply_monthly_xaxis(fig4, len(ytd_pivot))
st.plotly_chart(fig4)
st.caption(
    "Time-weighted: each account's monthly returns are compounded within the calendar year, "
    "so deposit/withdrawal timing doesn't distort the comparison. Resets every January. "
    "**Total** compounds the combined portfolio's monthly return — the same series behind "
    "the CAGR, volatility and drawdown figures below — so larger accounts weigh more."
)

# --- TOTAL PORTFOLIO RISK & RETURN ---

st.subheader('Total Portfolio — Risk & Return')

# metrics below use total_df['monthly_return'], computed above the YTD chart
# and shared with its "Total" line
n_months = len(total_df)

if n_months < 2:
    st.info("Need at least two months of combined data to compute portfolio-level risk and return.")
else:
    monthly_returns = total_df['monthly_return'].fillna(0)

    # CAGR from the compounded monthly return series, annualized
    wealth_index = (1 + monthly_returns).cumprod()
    total_return = wealth_index.iloc[-1] - 1
    cagr = (1 + total_return) ** (12 / n_months) - 1

    # annualized volatility from the dispersion of monthly returns
    volatility = monthly_returns.std(ddof=1) * np.sqrt(12)

    # max drawdown from the compounded wealth index
    drawdown = wealth_index / wealth_index.cummax() - 1
    max_drawdown = drawdown.min()

    # Sharpe ratio vs a 4.5% risk-free rate, same benchmark used on the IBKR sleeve page
    risk_free_rate = 0.045
    sharpe = (cagr - risk_free_rate) / volatility if volatility > 0 else np.nan

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("CAGR", f"{cagr:.1%}")
    col2.metric("Volatility (annualized)", f"{volatility:.1%}")
    col3.metric("Max Drawdown", f"{max_drawdown:.1%}")
    col4.metric("Sharpe (rf 4.5%)", f"{sharpe:.2f}" if not np.isnan(sharpe) else "n/a")

    st.caption(
        f"Based on {n_months} months of combined account data. Monthly-based volatility and "
        "drawdown are a floor estimate — they miss intra-month swings that daily data would catch."
    )
