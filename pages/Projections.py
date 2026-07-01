import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
import datetime as dt
from utils import get_db_connection, get_currency, generate_full_log

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

st.title('Projections')

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

# generating full data using utils function with randomization option
if st.session_state.randomize:
    full_data = generate_full_log(c, randomized=True)
else:
    full_data = generate_full_log(c)

if full_data.empty:
    st.info("No data yet. Add monthly positions and income on the **Data Insert** page to build a projection.")
    st.stop()

# prompting all the variable inputs

average_monthly_return = (full_data['capital_gain'] / full_data['start_value']).median()

col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

with col1:
    annual_increase = st.number_input("Annual salary increase %", value=5) / 100
with col2:
    bonus_percentage = st.number_input("Annual bonus (% of pay)", value=60) / 100
with col3:
    income_tax = st.number_input("Income Tax %", value=40) / 100
with col4:
    monthly_return = st.number_input("Investment Returns %", value=5) / 12 / 100

# The recorded income is treated as take-home, so salary growth applies directly
# to it without any assumed starting tax bracket.
starting_tax_rate = income_tax

# generate number of months in scope and list of dates

months = st.slider('Years', value=10, min_value=1, max_value=30, step=1) * 12

start_date = (pd.Timestamp.today().replace(day=1) + dt.timedelta(days=32)).replace(day=1)

dates = pd.date_range(
    start=start_date,
    periods=months,
    freq="MS")

# starting variables

start_income = full_data['income'].iloc[-3:].median()
gross_income = start_income / (1 - starting_tax_rate)
income = gross_income * (1 - income_tax)
total_assets = full_data['end_value'].iloc[-1]
saving_rate = (1 - full_data['expenses'].iloc[-12:].median() / full_data['income'].iloc[-12:].median())
bonus = 0

# creating dataframe
projection = pd.DataFrame({"date": dates})
projection["income"] = income
projection["total_assets"] = total_assets
projection["returns"] = full_data['capital_gain'].iloc[-1]
projection["bonus"] = bonus

# generating projection

for i in range(len(projection)):

    current_date = projection.loc[i, "date"]

    # Increase income and apply bonus every February
    if current_date.month == 2 and i != 0:
        bonus = income * 12 * bonus_percentage
        income *= (1 + annual_increase)

    else:
        bonus = 0

    # Returns based on previous total assets
    returns = int(total_assets * monthly_return)

    # Update total assets
    savings = int(income * saving_rate)
    total_assets = int(total_assets + savings + returns + bonus)

    # Store values
    projection.loc[i, "income"] = int(income)
    projection.loc[i, "bonus"] = int(bonus)
    projection.loc[i, "returns"] = int(returns)
    projection.loc[i, "total_assets"] = int(total_assets)


# plotting results

fig = px.line(projection, x='date', y='total_assets')
fig.update_traces(name='Total Assets')
fig.update_layout(xaxis_title=None, yaxis_title=f'Total Assets ({CUR})')
st.plotly_chart(fig)

# writing only fixed variable

savings_rate_months = min(12, len(full_data))
st.write(
    f'Assuming current net base salary savings rate: {int(saving_rate * 100)}% '
    f'(based on the last {savings_rate_months} months)'
)

# writing estimate retirement goal based on current expenses and fixed income return

st.subheader('Retirement Estimation')

fixed_income_return = st.number_input('Fixed Income Return %', value=5) / 100

current_expenses = int(full_data['expenses'].iloc[-12:].mean())
projection['risk_free_return'] = projection['total_assets'] * fixed_income_return / 12 * (1 - income_tax)

goal_reached = projection[projection['risk_free_return'] >= current_expenses]

if goal_reached.empty:
    st.write(
        f'At the current projection, your fixed income return does not reach '
        f'monthly expenses of {CUR}{current_expenses:,} within the {months // 12}-year window. '
        f'Try extending the horizon or increasing the investment return rate.'
    )
else:
    asset_needed = int(goal_reached.iloc[0]['total_assets'])
    years_missing = int((goal_reached.iloc[0]['date'] - dt.datetime.today()).days / 365)
    st.write(
        f'To maintain the current monthly life expenses of {CUR}{current_expenses:,} '
        f'you can stop working in {years_missing} years with {CUR}{asset_needed:,} of assets '
        f'invested at fixed income rate of {round(fixed_income_return * 100, 1)}%'
    )

total_assets_last = int(full_data['end_value'].iloc[-1])
st.write(
    f'With current assets of {CUR}{total_assets_last:,} and monthly expenses of {CUR}{current_expenses:,} '
    f'you could live {round(total_assets_last / (current_expenses * 12), 1)} years without working before running out of assets.'
)

# showing cleaned data

projection['savings'] = (projection['income'] * saving_rate).astype(int)
clean_projection = projection.copy()
clean_projection.index = clean_projection.date.dt.date
clean_projection = clean_projection[['income', 'bonus', 'savings', 'returns', 'total_assets']]
clean_projection.columns = ['Income', 'Bonus', 'Savings', 'Returns', 'Total Assets']

if st.toggle('Show Detailed Monthly Projection'):
    st.write(clean_projection)
