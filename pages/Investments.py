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
