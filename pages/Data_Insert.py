import streamlit as st
import pandas as pd
import datetime as dt
from utils import (get_db_connection, month_input, get_currency, export_db_to_csv,
                   backup_db, DATE_FORMAT, get_setting, set_setting)

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

# parsed datetime columns for sorting/filtering — the stored 'date' column is
# ISO text, sortable as a string, but a real datetime is still handier here
all_data_df['date_dt'] = pd.to_datetime(all_data_df['date'], format=DATE_FORMAT)
salary_data['date_dt'] = pd.to_datetime(salary_data['date'], format=DATE_FORMAT)

accounts = sorted(all_data_df['platform'].unique().tolist())

# archived accounts are hidden from the monthly grid below but keep
# their full history everywhere else (Edit Data, Analytics, Investments) —
# archiving never deletes a monthly_logs row, it only sets a preference flag
archived_accounts = [a for a in get_setting("archived_accounts", []) if a in accounts]

if accounts:
    with st.expander("Archived accounts"):
        selected_archived = st.multiselect(
            "Archived accounts", accounts, default=archived_accounts,
            key="archived_accounts_select", label_visibility="collapsed",
        )
        if selected_archived != archived_accounts:
            set_setting("archived_accounts", selected_archived)
        archived_accounts = selected_archived

        st.caption(
            f"{len(archived_accounts)} account(s) archived — hidden from the monthly "
            "grid below, history kept everywhere else. Un-check one to bring it back."
            if archived_accounts else
            "Archive an account you no longer use to drop it from the monthly grid "
            "below. Its history stays everywhere else, and un-checking it here "
            "brings it back."
        )

active_accounts = [a for a in accounts if a not in archived_accounts]

# --- MONTHLY ENTRY ---

previous_month = (dt.date.today().replace(day=1) - dt.timedelta(days=1)).replace(day=1)
record_date = month_input("Record Date", value=previous_month, key="insert")
date = record_date.strftime(DATE_FORMAT)
record_ts = pd.Timestamp(record_date)

existing_this_month = all_data_df[all_data_df['date'] == date]
income_this_month = salary_data[salary_data['date'] == date]

st.subheader(record_date.strftime('%B %Y'))

# --- income, with last known value shown for context ---

prior_income = salary_data[salary_data['date_dt'] < record_ts].sort_values('date_dt')
last_income = int(prior_income['income'].iloc[-1]) if not prior_income.empty else None

income_existing = int(income_this_month['income'].iloc[0]) if not income_this_month.empty else None
income_default = income_existing if income_existing is not None else (last_income or 0)

income = st.number_input(f"Income ({CUR})", min_value=0, value=income_default)
if last_income is not None:
    st.caption(f"Last logged income ({prior_income['date_dt'].iloc[-1].strftime('%b %Y')}): {CUR}{last_income:,}")

# --- account positions grid: one row per account, edited and saved together ---

st.write("**Account positions**")
st.caption(
    "Edit each account's figures below. Add a row (bottom of the table) for a "
    "new account, or delete a row to skip it this month. \"Last Value\" is the "
    "most recent balance before this month, shown for reference."
)

prior_positions = all_data_df[all_data_df['date_dt'] < record_ts].sort_values('date_dt')
last_value_by_account = prior_positions.groupby('platform')['end_value'].last().to_dict()

existing_by_account = existing_this_month.groupby('platform')[['inflows', 'outflows', 'end_value']].sum()

grid_rows = []
for acct in active_accounts:
    last_val = last_value_by_account.get(acct)
    if acct in existing_by_account.index:
        row = existing_by_account.loc[acct]
        inflows_v, outflows_v, end_value_v = int(row['inflows']), int(row['outflows']), int(row['end_value'])
    else:
        inflows_v, outflows_v = 0, 0
        end_value_v = int(last_val) if last_val is not None else 0
    grid_rows.append({
        'Account': acct,
        'Last Value': f"{CUR}{int(last_val):,}" if last_val is not None else "—",
        'Inflows': inflows_v,
        'Outflows': outflows_v,
        'End Value': end_value_v,
    })

if grid_rows:
    grid_df = pd.DataFrame(grid_rows)
else:
    grid_df = pd.DataFrame({
        'Account': pd.Series(dtype='str'), 'Last Value': pd.Series(dtype='str'),
        'Inflows': pd.Series(dtype='int64'), 'Outflows': pd.Series(dtype='int64'),
        'End Value': pd.Series(dtype='int64'),
    })

edited = st.data_editor(
    grid_df,
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    column_config={
        "Account": st.column_config.TextColumn("Account", required=True),
        "Last Value": st.column_config.TextColumn("Last Value", disabled=True),
        "Inflows": st.column_config.NumberColumn(f"Inflows ({CUR})", step=1),
        "Outflows": st.column_config.NumberColumn(f"Outflows ({CUR})", step=1),
        "End Value": st.column_config.NumberColumn(f"End Value ({CUR})", step=1),
    },
    key="monthly_grid",
)

st.caption(f"Saving will overwrite any existing {record_date.strftime('%B %Y')} entries below.")

if st.button("Save Month", type="primary"):
    backup_db(conn)

    c.execute("DELETE FROM salary_logs WHERE date = ?", (date,))
    conn.execute("INSERT INTO salary_logs VALUES (?, ?, ?)", (date, int(income), 0))

    valid_rows = edited[edited['Account'].astype(str).str.strip() != '']
    if not valid_rows.empty:
        # sum duplicate account names within the same save (e.g. merged sub-accounts),
        # mirroring how the analytics pages already treat duplicate (account, month) rows
        summed = valid_rows.groupby('Account')[['Inflows', 'Outflows', 'End Value']].sum()
        for acct, row in summed.iterrows():
            c.execute("DELETE FROM monthly_logs WHERE date = ? AND account = ?", (date, acct))
            conn.execute(
                "INSERT INTO monthly_logs VALUES (?, ?, ?, ?, ?, ?)",
                (date, acct, int(row['Inflows']), int(row['Outflows']), int(row['End Value']), 0),
            )

    conn.commit()
    export_db_to_csv(conn)
    st.session_state['data_insert_msg'] = f"{record_date.strftime('%B %Y')} saved!"
    st.rerun()

# --- SHOW ALL ---

if st.toggle('Show all saved data'):
    col1, col2 = st.columns([1, 1])
    with col1:
        st.write('Monthly logs')
        st.write(all_data_df.drop(columns=['rowid', 'index', 'date_dt']))
    with col2:
        st.write('Income logs')
        st.write(salary_data.drop(columns=['rowid', 'index', 'date_dt']))

# --- BULK IMPORT ---

with st.expander("Bulk import (CSV)"):
    st.caption(
        "Import several months at once. Columns must match the app's own export "
        "format — positions: date, account, inflows, outflows, end_value; income: "
        "date, income. Any date is rounded to the 1st of its month. Months already "
        "logged are skipped, not overwritten — edit those individually below instead."
    )

    def _parse_month_dates(df, col):
        parsed = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        return parsed.dt.to_period('M').dt.to_timestamp()

    ic1, ic2 = st.columns(2)

    with ic1:
        pos_file = st.file_uploader("Positions CSV", type="csv", key="bulk_positions")
        if pos_file is not None:
            try:
                raw = pd.read_csv(pos_file)
                raw.columns = [col.strip().lower() for col in raw.columns]
                required = {'date', 'account', 'inflows', 'outflows', 'end_value'}
                missing = required - set(raw.columns)
                if missing:
                    st.error(f"Missing column(s): {', '.join(sorted(missing))}")
                else:
                    raw['parsed_date'] = _parse_month_dates(raw, 'date')
                    bad = int(raw['parsed_date'].isna().sum())
                    raw = raw.dropna(subset=['parsed_date']).copy()
                    raw['date_str'] = raw['parsed_date'].dt.strftime(DATE_FORMAT)
                    raw['account'] = raw['account'].astype(str).str.strip()

                    existing_pairs = set(zip(all_data_df['date'], all_data_df['platform']))
                    raw['dup'] = raw.apply(lambda r: (r['date_str'], r['account']) in existing_pairs, axis=1)
                    new_rows = raw[~raw['dup']]
                    dup_count = int(raw['dup'].sum())

                    preview = raw[['date_str', 'account', 'inflows', 'outflows', 'end_value', 'dup']].rename(
                        columns={'date_str': 'Date', 'account': 'Account', 'inflows': 'Inflows',
                                 'outflows': 'Outflows', 'end_value': 'End Value', 'dup': 'Already logged'})
                    st.dataframe(preview, hide_index=True)

                    msg = f"{len(new_rows)} new row(s) ready to import"
                    if dup_count:
                        msg += f", {dup_count} skipped (already logged)"
                    if bad:
                        msg += f", {bad} row(s) skipped (unreadable date)"
                    st.caption(msg + ".")

                    if len(new_rows) > 0 and st.button("Import Positions"):
                        backup_db(conn)
                        for _, r in new_rows.iterrows():
                            conn.execute(
                                "INSERT INTO monthly_logs VALUES (?, ?, ?, ?, ?, ?)",
                                (r['date_str'], r['account'], int(r['inflows']), int(r['outflows']),
                                 int(r['end_value']), 0),
                            )
                        conn.commit()
                        export_db_to_csv(conn)
                        st.session_state['data_insert_msg'] = f"Imported {len(new_rows)} position row(s)."
                        st.rerun()
            except Exception as e:  # noqa: BLE001 — surface any parse failure cleanly
                st.error(f"Could not read this CSV: {e}")

    with ic2:
        inc_file = st.file_uploader("Income CSV", type="csv", key="bulk_income")
        if inc_file is not None:
            try:
                raw = pd.read_csv(inc_file)
                raw.columns = [col.strip().lower() for col in raw.columns]
                required = {'date', 'income'}
                missing = required - set(raw.columns)
                if missing:
                    st.error(f"Missing column(s): {', '.join(sorted(missing))}")
                else:
                    raw['parsed_date'] = _parse_month_dates(raw, 'date')
                    bad = int(raw['parsed_date'].isna().sum())
                    raw = raw.dropna(subset=['parsed_date']).copy()
                    raw['date_str'] = raw['parsed_date'].dt.strftime(DATE_FORMAT)

                    existing_dates = set(salary_data['date'])
                    raw['dup'] = raw['date_str'].isin(existing_dates)
                    new_rows = raw[~raw['dup']]
                    dup_count = int(raw['dup'].sum())

                    preview = raw[['date_str', 'income', 'dup']].rename(
                        columns={'date_str': 'Date', 'income': 'Income', 'dup': 'Already logged'})
                    st.dataframe(preview, hide_index=True)

                    msg = f"{len(new_rows)} new row(s) ready to import"
                    if dup_count:
                        msg += f", {dup_count} skipped (already logged)"
                    if bad:
                        msg += f", {bad} row(s) skipped (unreadable date)"
                    st.caption(msg + ".")

                    if len(new_rows) > 0 and st.button("Import Income"):
                        backup_db(conn)
                        for _, r in new_rows.iterrows():
                            conn.execute("INSERT INTO salary_logs VALUES (?, ?, ?)",
                                         (r['date_str'], int(r['income']), 0))
                        conn.commit()
                        export_db_to_csv(conn)
                        st.session_state['data_insert_msg'] = f"Imported {len(new_rows)} income row(s)."
                        st.rerun()
            except Exception as e:  # noqa: BLE001 — surface any parse failure cleanly
                st.error(f"Could not read this CSV: {e}")

# --- EDIT / DELETE ---

st.subheader('Edit Data')

show_all_months = st.toggle('Show all months', key='edit_show_all')

chosen_table = st.selectbox('Table', ['Monthly logs', 'Income logs'])

if chosen_table == 'Monthly logs':
    if all_data_df.empty:
        st.info("No position records yet — add one above to start editing.")
        st.stop()

    edit_pool = all_data_df
    if not show_all_months:
        latest_date = all_data_df['date_dt'].max()
        edit_pool = all_data_df[all_data_df['date_dt'] == latest_date]
        st.caption(f"Showing {latest_date.strftime('%B %Y')} only — toggle above to see all months.")

    edit_pool = edit_pool.copy()
    edit_pool['label'] = edit_pool['platform'] + ' — ' + edit_pool['date_dt'].dt.strftime('%b %Y')

    selected_label = st.selectbox("Select record to edit", edit_pool['label'])
    record = edit_pool[edit_pool['label'] == selected_label].iloc[0]

    with st.form("Edit Monthly"):
        new_date    = month_input("Record Date", value=dt.datetime.strptime(record["date"], DATE_FORMAT).date(), key=f"edit_monthly_{int(record['rowid'])}")
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
                SET date = ?, account = ?, inflows = ?, outflows = ?, end_value = ?
                WHERE rowid = ?
            """, (new_date.strftime(DATE_FORMAT), account, inflows, outflows, end_value, int(record["rowid"])))
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

    edit_pool = salary_data
    if not show_all_months:
        latest_date = salary_data['date_dt'].max()
        edit_pool = salary_data[salary_data['date_dt'] == latest_date]
        st.caption(f"Showing {latest_date.strftime('%B %Y')} only — toggle above to see all months.")

    edit_pool = edit_pool.copy()
    edit_pool['label'] = edit_pool['date_dt'].dt.strftime('%b %Y') + f' — {CUR}' + edit_pool['income'].astype(str)

    selected_label = st.selectbox("Select record to edit", edit_pool['label'])
    record = edit_pool[edit_pool['label'] == selected_label].iloc[0]

    with st.form("Edit Income"):
        new_date    = month_input("Record Date", value=dt.datetime.strptime(record["date"], DATE_FORMAT).date(), key=f"edit_income_{int(record['rowid'])}")
        income      = st.number_input("Income", value=int(record["income"]))
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            backup_db(conn)
            c.execute("""
                UPDATE salary_logs SET date = ?, income = ? WHERE rowid = ?
            """, (new_date.strftime(DATE_FORMAT), income, int(record["rowid"])))
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
