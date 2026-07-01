import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from utils import get_db_connection, get_currency

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

# title
st.title('Investments')

# loading monthly logs

monthly = c.execute("SELECT * FROM monthly_logs").fetchall()
monthly_df = pd.DataFrame(monthly, columns=['date', 'account', 'inflows', 'outflows', 'end_value', 'unique_index'])

if monthly_df.empty:
    st.info("No investment data recorded yet. Add monthly positions on the **Data Insert** page.")
    st.stop()

monthly_df['date'] = pd.to_datetime(monthly_df['date'], format='%d/%m/%y')

# collapse duplicate (account, date) rows — e.g. merged sub-accounts that both
# reported in the same month — before computing month-over-month changes
monthly_df = (monthly_df.groupby(['account', 'date'], as_index=False)
               [['inflows', 'outflows', 'end_value']].sum())

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
st.plotly_chart(fig)

# capital gains by account
st.subheader('Capital Gains by Account')

gain_pivot = monthly_df.pivot_table(index='date', columns='account', values='capital_gain', aggfunc='sum').fillna(0).sort_index()

fig2 = px.bar(gain_pivot, x=gain_pivot.index, y=gain_pivot.columns)
fig2.update_layout(barmode='relative', xaxis_title=None, yaxis_title=f'Capital Gain ({CUR})', legend_title='Account')
st.plotly_chart(fig2)

# capital gain % by account
st.subheader('Capital Gain % by Account')

return_pivot = monthly_df.pivot_table(index='date', columns='account', values='monthly_return', aggfunc='sum').sort_index()

fig3 = px.line(return_pivot, x=return_pivot.index, y=return_pivot.columns, markers=True)
fig3.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='Monthly Return %', legend_title='Account')
st.plotly_chart(fig3)

# --- TOTAL PORTFOLIO RISK & RETURN ---

st.subheader('Total Portfolio — Risk & Return')

total_df = monthly_df.groupby('date')[['inflows', 'outflows', 'end_value']].sum().sort_index()
total_df['start_value'] = total_df['end_value'].shift().fillna(0)
total_df['capital_gain'] = total_df['end_value'] - total_df['start_value'] - total_df['inflows'] + total_df['outflows']
# zero out the first month — no prior start_value available, gain is not meaningful
total_df.iloc[0, total_df.columns.get_loc('capital_gain')] = 0
total_df['monthly_return'] = total_df['capital_gain'] / total_df['start_value'].replace(0, np.nan)

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
