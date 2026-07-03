import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils import get_db_connection, get_currency, generate_full_log, generate_net_worth, apply_monthly_xaxis

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

# --- LIQUID ASSETS & LOCKED PENSION ---

net_worth = generate_net_worth(c, full_data, randomized=randomized)
latest = net_worth.iloc[-1]

col1, col2 = st.columns(2)
with col1:
    # pension snapshots are sporadic, so the month-over-month delta tracks the
    # liquid side only — the last two months of actual position data
    liquid_series = full_data['end_value']
    if len(liquid_series) >= 2:
        mom_change = liquid_series.iloc[-1] - liquid_series.iloc[-2]
        mom_pct = mom_change / liquid_series.iloc[-2] if liquid_series.iloc[-2] else 0
        st.metric("Liquid Assets", f"{CUR}{latest['liquid']:,.0f}",
                  f"{CUR}{mom_change:+,.0f} ({mom_pct:+.1%}) vs last month")
    else:
        st.metric("Liquid Assets", f"{CUR}{latest['liquid']:,.0f}")
with col2:
    st.metric("Locked Pension", f"{CUR}{latest['pension']:,.0f}")

st.caption(
    "Pension money is tracked separately and stays excluded from the "
    "spendable-asset and runway figures on this and other pages."
)

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
apply_monthly_xaxis(fig, len(full_data))
st.plotly_chart(fig)

# monthly savings and capital gain chart
st.subheader('Monthly Savings and Returns')
focus_view = st.toggle(
    'Focus view (clip outlier months)',
    help="Caps the y-axis so smaller months are readable. Bars that get "
         "clipped are labeled with their real value.",
    key='monthly_savings_focus'
)

# exclude the first month — its "savings" is the opening balances flowing in,
# which belongs in the cumulative chart above but would dwarf the monthly bars
monthly_data = full_data[full_data['date'] > full_data['date'].min()]

fig2 = px.bar(
    monthly_data,
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
        x=monthly_data['date'],
        y=monthly_data['total_income'],
        mode='lines+markers',
        name='Total Income', line_color='blue'
    )
)
fig2.update_layout(xaxis_title=None, yaxis_title=None)
apply_monthly_xaxis(fig2, len(monthly_data))

if focus_view:
    pos_stack = monthly_data[['capital_gain', 'savings']].clip(lower=0).sum(axis=1)
    neg_stack = monthly_data[['capital_gain', 'savings']].clip(upper=0).sum(axis=1)

    # base the clip range on the 5th-95th percentile of typical months so a
    # handful of bonus/first-month spikes don't stretch the axis
    y_low, y_high = np.percentile(pd.concat([pos_stack, neg_stack]), [10, 90])
    y_low, y_high = min(y_low, 0), max(y_high, 0)
    pad = (y_high - y_low) * 0.15 or 1
    y_min, y_max = y_low - pad, y_high + pad
    fig2.update_layout(yaxis=dict(range=[y_min, y_max]))

    for date, top, bottom in zip(monthly_data['date'], pos_stack, neg_stack):
        if top > y_max:
            fig2.add_annotation(x=date, y=y_max, yshift=12, text=f"{CUR}{top:,.0f}",
                                 showarrow=False, font=dict(size=10))
        if bottom < y_min:
            fig2.add_annotation(x=date, y=y_min, yshift=-12, text=f"{CUR}{bottom:,.0f}",
                                 showarrow=False, font=dict(size=10))

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
apply_monthly_xaxis(fig3, len(full_data))
st.plotly_chart(fig3)

# monthly returns

st.subheader('Monthly Returns')
full_data['monthly_returns'] = full_data['capital_gain'] / full_data['start_value'].replace(0, np.nan)
fig4 = px.bar(full_data, x='date', y='monthly_returns')
fig4.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='Return %')
apply_monthly_xaxis(fig4, len(full_data))
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
