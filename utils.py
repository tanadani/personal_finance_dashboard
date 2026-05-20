import sqlite3
import pandas as pd
import os
import plotly
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import numpy as np

# Root directory (where utils.py lives) — used as canonical CSV export location
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def export_db_to_csv(conn):
    """Export all database tables to CSV files in the project root, overwriting previous exports."""
    tables = {
        "monthly_logs": "monthly_logs_export.csv",
        "salary_logs":  "salary_logs_export.csv",
        "trips_logs":   "trips_logs_export.csv",
    }
    for table, filename in tables.items():
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df.to_csv(os.path.join(_ROOT_DIR, filename), index=False)
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

def generate_full_log(c, randomized = False):
    # loading monthly logs and salary logs from database and formatting
    monthly = c.execute(""" SELECT * from monthly_logs""").fetchall()
    monthly_df = pd.DataFrame(monthly)
    monthly_df.columns = ['date', 'platform', 'inflows', 'outflows', 'end_value','index']
    monthly_df['date'] = pd.to_datetime(monthly_df['date'], format = '%d/%m/%y')
    
    income = c.execute(""" SELECT * from salary_logs""").fetchall()
    income_df = pd.DataFrame(income)
    income_df.columns = ['date', 'income','index']
    income_df['date'] = pd.to_datetime(income_df['date'], format = '%d/%m/%y')
    income_df.set_index('date', inplace = True)
    
    # creating a monthly dataframe
    total_df = monthly_df.groupby('date').sum()[['inflows','outflows','end_value']]

    # creating random option
    if randomized:
        total_df = randomize(total_df)
        income_df = randomize(income_df)
        
    # calculating capital gains, incomes and expenses and creating a merged dataframe
    total_df['start_value'] = total_df['end_value'].shift().fillna(0)
    total_df['capital_gain'] = total_df['end_value'] - total_df['start_value'] - total_df['inflows'] + total_df['outflows']
    full_data = income_df.merge(total_df, left_index = True, right_index = True, how = 'outer')
    full_data['expenses'] = full_data['income']-full_data['inflows']+full_data['outflows']
    full_data['savings'] = full_data['income']- full_data['expenses']
    # zero out first month — no prior start_value available, gain is not meaningful
    full_data.loc[total_df.index[0], 'expenses'] = 0
    full_data.loc[total_df.index[0], 'capital_gain'] = 0
    full_data['total_income'] = full_data['savings']+full_data['capital_gain']
    full_data['total_income_rolling'] = full_data['total_income'].rolling(3).mean().fillna(0)

    # drop months with missing income or position data and warn the user
    rows_before = len(full_data)
    full_data = full_data.dropna()
    dropped = rows_before - len(full_data)
    if dropped > 0:
        st.warning(f"{dropped} month(s) excluded — missing income or position data for those periods.")
    
    # creating cumulative capital gains and savings
    full_data.loc[:,'cumulative_capital_gains'] = full_data['capital_gain'].cumsum()
    full_data.loc[:,'cumulative_savings'] = full_data['savings'].cumsum()
    full_data.loc[:,'date'] = full_data.index

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