import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils import get_db_connection, get_currency, generate_full_log

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

# title
st.title('Analytics')

# generating full data using utils function

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

randomized = st.session_state.randomize

if randomized:
    full_data = generate_full_log(c, randomized=True)
else:
    full_data = generate_full_log(c)

if full_data.empty:
    st.info("No data yet. Add monthly positions and income on the **Data Insert** page to see analytics.")
    st.stop()

# --- CHARTS ---

# overall savings chart

st.subheader('Cumulative Savings and Returns')

full_data["total"] = full_data["cumulative_capital_gains"] + full_data["cumulative_savings"]

fig = px.area(full_data, x='date', y=['cumulative_capital_gains', 'cumulative_savings'])
fig.for_each_trace(
    lambda t: t.update(
        name={
            "cumulative_capital_gains": "Capital Gains",
            "cumulative_savings": "Savings"
        }[t.name]
    )
)
fig.add_trace(
    go.Scatter(
        x=full_data["date"],
        y=full_data["total"],
        mode="lines",
        name="Total",
        line=dict(width=3, color="black")
    )
)
fig.update_layout(xaxis_title=None, yaxis_title=None)
st.plotly_chart(fig)

# monthly savings and capital gain chart
st.subheader('Monthly Savings and Returns')
fig2 = px.bar(
    full_data,
    x='date',
    y=['capital_gain', 'savings']
)

fig2.update_layout(barmode="relative")
fig2.for_each_trace(
    lambda t: t.update(
        name={"capital_gain": "Capital Gains", "savings": "Savings"}.get(t.name, t.name)
    )
)
fig2.add_trace(
    go.Scatter(
        x=full_data['date'],
        y=full_data['total_income'],
        mode='lines+markers',
        name='Total Income', line_color='blue'
    )
)
fig2.update_layout(xaxis_title=None, yaxis_title=None)
st.plotly_chart(fig2)

# monthly expenses

st.subheader('Monthly Expenses')
fig3 = px.bar(full_data, x='date', y='expenses')
# 5-month rolling average of expenses
expenses_rolling = full_data['expenses'].rolling(5).mean()
fig3.add_trace(
    go.Scatter(
        x=full_data['date'],
        y=expenses_rolling,
        mode='lines',
        name='5-Month Rolling Avg',
        line=dict(color='red', dash='dash')
    )
)
fig3.update_layout(xaxis_title=None, yaxis_title=f'Amount ({CUR})')
st.plotly_chart(fig3)

# monthly returns

st.subheader('Monthly Returns')
full_data['monthly_returns'] = full_data['capital_gain'] / full_data['start_value'].replace(0, np.nan)
fig4 = px.bar(full_data, x='date', y='monthly_returns')
fig4.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='Return %')
st.plotly_chart(fig4)

# --- CURRENT FISCAL YEAR SUMMARY ---

st.title('Current Fiscal Year')

today = pd.Timestamp.today()
current_fy_start = pd.Timestamp(year=today.year, month=1, day=1)
current_fy_end = pd.Timestamp(year=today.year + 1, month=1, day=1)

current_fy_data = full_data[(full_data['date'] >= current_fy_start) & (full_data['date'] < current_fy_end)]

if current_fy_data.empty:
    st.info(f"No data available for {current_fy_start.strftime('%b %Y')} – {current_fy_end.strftime('%b %Y')}.")
else:
    current_fy_income_savings = current_fy_data['savings'].sum()
    current_fy_capital_gain = current_fy_data['capital_gain'].sum()
    current_fy_total_savings = current_fy_income_savings + current_fy_capital_gain

    current_fy_twr = (1 + current_fy_data['monthly_returns'].fillna(0)).prod() - 1

    st.subheader(f"{current_fy_start.strftime('%b %Y')} – {current_fy_end.strftime('%b %Y')}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Savings", f"{CUR}{current_fy_total_savings:,.0f}")
    col2.metric("From Income", f"{CUR}{current_fy_income_savings:,.0f}")
    col3.metric("From Capital Gains", f"{CUR}{current_fy_capital_gain:,.0f}", f"{current_fy_twr:.1%} time-weighted return")

# --- PREVIOUS FISCAL YEAR SUMMARY ---

st.title('Previous Fiscal Year')

fy_end = pd.Timestamp(year=today.year, month=1, day=1)
fy_start = pd.Timestamp(year=today.year - 1, month=1, day=1)

fy_data = full_data[(full_data['date'] >= fy_start) & (full_data['date'] < fy_end)]

if fy_data.empty:
    st.info(f"No data available for {fy_start.strftime('%b %Y')} – {fy_end.strftime('%b %Y')}.")
else:
    fy_income_savings = fy_data['savings'].sum()
    fy_capital_gain = fy_data['capital_gain'].sum()
    fy_total_savings = fy_income_savings + fy_capital_gain

    fy_twr = (1 + fy_data['monthly_returns'].fillna(0)).prod() - 1

    st.subheader(f"{fy_start.strftime('%b %Y')} – {fy_end.strftime('%b %Y')}")

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Savings", f"{CUR}{fy_total_savings:,.0f}")
    col2.metric("From Income", f"{CUR}{fy_income_savings:,.0f}")
    col3.metric("From Capital Gains", f"{CUR}{fy_capital_gain:,.0f}", f"{fy_twr:.1%} time-weighted return")
