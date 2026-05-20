import streamlit as st
import pandas as pd
import sqlite3
import os
import datetime as dt
from utils import *

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "dashboard_memory.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
c = conn.cursor()

st.title("Data Insert")

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

# show success message from previous action if any
if 'data_insert_msg' in st.session_state:
    st.success(st.session_state.pop('data_insert_msg'))

# load all saved data (rowid included for safe record identification)

all_data = c.execute("SELECT rowid, * FROM monthly_logs").fetchall()
all_data_df = pd.DataFrame(all_data, columns=['rowid', 'date', 'platform', 'inflows', 'outflows', 'end_value', 'index'])

salary_data = c.execute("SELECT rowid, * FROM salary_logs").fetchall()
salary_data = pd.DataFrame(salary_data, columns=['rowid', 'date', 'income', 'index'])

# adding randomization option
if st.session_state.randomize:
    all_data_df.loc[:, ['inflows', 'outflows', 'end_value']] = 0
    salary_data.loc[:, 'income'] = 0

# --- INSERT ---

accounts = all_data_df.platform.unique().tolist()

raw_date = str(st.date_input("Record Date"))
date = dt.datetime.strptime(raw_date, '%Y-%m-%d').strftime('%d/%m/%y')

income = st.number_input("Income", min_value=0)

if st.button("Save Income"):
    existing = c.execute("SELECT COUNT(*) FROM salary_logs WHERE date = ?", (date,)).fetchone()[0]
    if existing > 0:
        st.warning(f"An income record for {date} already exists. Edit it in the section below instead.")
    else:
        conn.execute("INSERT INTO salary_logs VALUES (?, ?, ?)", (date, income, 0))
        conn.commit()
        export_db_to_csv(conn)
        st.session_state['data_insert_msg'] = "Income saved!"
        st.rerun()

account = st.selectbox("Account", accounts, accept_new_options=True)
inflows = st.number_input("Inflows")
outflows = st.number_input("Outflows")
end_value = st.number_input("End Value")

if st.button("Save Positions"):
    conn.execute("INSERT INTO monthly_logs VALUES (?, ?, ?, ?, ?, ?)",
                 (date, account, inflows, outflows, end_value, 0))
    conn.commit()
    export_db_to_csv(conn)
    st.session_state['data_insert_msg'] = "Position saved!"
    st.rerun()

# --- SHOW ALL ---

if st.toggle('Show all saved data'):
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write('Monthly logs')
        st.write(all_data_df.drop(columns=['rowid', 'index']))
    with col2:
        st.write('Income logs')
        st.write(salary_data.drop(columns=['rowid', 'index']))

# --- EDIT / DELETE ---

st.subheader('Edit Data')

chosen_table = st.selectbox('Table', ['Monthly logs', 'Income logs'])

if chosen_table == 'Monthly logs':
    all_data_df['label'] = all_data_df['platform'] + ' — ' + pd.to_datetime(
        all_data_df['date'], format='%d/%m/%y').dt.strftime('%b %Y')

    selected_label = st.selectbox("Select record to edit", all_data_df['label'])
    record = all_data_df[all_data_df['label'] == selected_label].iloc[0]

    with st.form("Edit Monthly"):
        new_date    = st.date_input("Record Date", value=dt.datetime.strptime(record["date"], "%d/%m/%y").date())
        account     = st.text_input("Platform", value=record["platform"])
        inflows     = st.number_input("Inflows", value=int(record["inflows"]))
        outflows    = st.number_input("Outflows", value=int(record["outflows"]))
        end_value   = st.number_input("End Value", value=int(record["end_value"]))
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            c.execute("""
                UPDATE monthly_logs
                SET date = ?, platform = ?, inflows = ?, outflows = ?, end_value = ?
                WHERE rowid = ?
            """, (new_date.strftime("%d/%m/%y"), account, inflows, outflows, end_value, int(record["rowid"])))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['data_insert_msg'] = "Record updated successfully!"
            st.rerun()

        elif deleted:
            if not confirm_del:
                st.warning("Check 'Confirm deletion' to delete this record.")
            else:
                c.execute("DELETE FROM monthly_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['data_insert_msg'] = "Record deleted successfully!"
                st.rerun()

else:
    salary_data['label'] = pd.to_datetime(
        salary_data['date'], format='%d/%m/%y').dt.strftime('%b %Y') + ' — £' + salary_data['income'].astype(str)

    selected_label = st.selectbox("Select record to edit", salary_data['label'])
    record = salary_data[salary_data['label'] == selected_label].iloc[0]

    with st.form("Edit Income"):
        new_date    = st.date_input("Record Date", value=dt.datetime.strptime(record["date"], "%d/%m/%y").date())
        income      = st.number_input("Income", value=int(record["income"]))
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            c.execute("""
                UPDATE salary_logs SET date = ?, income = ? WHERE rowid = ?
            """, (new_date.strftime("%d/%m/%y"), income, int(record["rowid"])))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['data_insert_msg'] = "Record updated successfully!"
            st.rerun()

        elif deleted:
            if not confirm_del:
                st.warning("Check 'Confirm deletion' to delete this record.")
            else:
                c.execute("DELETE FROM salary_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['data_insert_msg'] = "Record deleted successfully!"
                st.rerun()
