import streamlit as st
import pandas as pd
import datetime as dt
from utils import get_db_connection, month_input, get_currency, export_db_to_csv, backup_db

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

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

record_date = month_input("Record Date", key="insert")
date = record_date.strftime('%d/%m/%y')

income = st.number_input("Income", min_value=0)

if st.button("Save Income"):
    existing = c.execute("SELECT COUNT(*) FROM salary_logs WHERE date = ?", (date,)).fetchone()[0]
    if existing > 0:
        st.warning(f"An income record for {date} already exists. Edit it in the section below instead.")
    else:
        backup_db(conn)
        conn.execute("INSERT INTO salary_logs VALUES (?, ?, ?)", (date, income, 0))
        conn.commit()
        export_db_to_csv(conn)
        st.session_state['data_insert_msg'] = "Income saved!"
        st.rerun()

account = st.selectbox("Account", accounts, accept_new_options=True)
inflows = st.number_input("Inflows")
outflows = st.number_input("Outflows")
end_value = st.number_input("End Value")

# a record for this account+month already existing is usually an accident, but
# can be intentional (e.g. merged sub-accounts) — warn and require confirmation
# rather than blocking, since the analytics sum duplicate (account, month) rows
dup_count = 0
if account:
    dup_count = c.execute(
        "SELECT COUNT(*) FROM monthly_logs WHERE date = ? AND account = ?",
        (date, account),
    ).fetchone()[0]

confirm_dup = True
if dup_count > 0:
    st.warning(
        f"A record for '{account}' in {record_date.strftime('%b %Y')} already exists. "
        "Saving will add another that gets summed with it."
    )
    confirm_dup = st.checkbox("Add anyway")

if st.button("Save Positions"):
    if dup_count > 0 and not confirm_dup:
        st.warning("Check 'Add anyway' to save a duplicate, or edit the existing record below.")
    else:
        backup_db(conn)
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
    if all_data_df.empty:
        st.info("No position records yet — add one above to start editing.")
        st.stop()

    all_data_df['label'] = all_data_df['platform'] + ' — ' + pd.to_datetime(
        all_data_df['date'], format='%d/%m/%y').dt.strftime('%b %Y')

    selected_label = st.selectbox("Select record to edit", all_data_df['label'])
    record = all_data_df[all_data_df['label'] == selected_label].iloc[0]

    with st.form("Edit Monthly"):
        new_date    = month_input("Record Date", value=dt.datetime.strptime(record["date"], "%d/%m/%y").date(), key="edit_monthly")
        account     = st.text_input("Platform", value=record["platform"])
        inflows     = st.number_input("Inflows", value=int(record["inflows"]))
        outflows    = st.number_input("Outflows", value=int(record["outflows"]))
        end_value   = st.number_input("End Value", value=int(record["end_value"]))
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            backup_db(conn)
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
                backup_db(conn)
                c.execute("DELETE FROM monthly_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['data_insert_msg'] = "Record deleted successfully!"
                st.rerun()

else:
    if salary_data.empty:
        st.info("No income records yet — add one above to start editing.")
        st.stop()

    salary_data['label'] = pd.to_datetime(
        salary_data['date'], format='%d/%m/%y').dt.strftime('%b %Y') + f' — {CUR}' + salary_data['income'].astype(str)

    selected_label = st.selectbox("Select record to edit", salary_data['label'])
    record = salary_data[salary_data['label'] == selected_label].iloc[0]

    with st.form("Edit Income"):
        new_date    = month_input("Record Date", value=dt.datetime.strptime(record["date"], "%d/%m/%y").date(), key="edit_income")
        income      = st.number_input("Income", value=int(record["income"]))
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            backup_db(conn)
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
                backup_db(conn)
                c.execute("DELETE FROM salary_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['data_insert_msg'] = "Record deleted successfully!"
                st.rerun()
