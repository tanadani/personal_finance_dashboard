import sqlite3
import pandas as pd
import numpy as np
import os
import plotly
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils import *

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "dashboard_memory.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
c = conn.cursor()

# title
st.title('Analytics')

# generating full data using utils function

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

randomized = st.session_state.randomize

if randomized:
    full_data = generate_full_log(c, randomized = True)
else:
    full_data = generate_full_log(c)

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
fig3.update_layout(xaxis_title=None, yaxis_title='Amount (£)')
st.plotly_chart(fig3)

# monthly returns

st.subheader('Monthly Returns')
full_data['monthly_returns'] = full_data['capital_gain'] / full_data['start_value'].replace(0, np.nan)
fig4 = px.bar(full_data, x='date', y='monthly_returns')
fig4.update_layout(yaxis_tickformat=".0%", xaxis_title=None, yaxis_title='Return %')
st.plotly_chart(fig4)