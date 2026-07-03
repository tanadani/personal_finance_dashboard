import pandas as pd
import plotly.express as px
import streamlit as st
import datetime as dt
from utils import get_db_connection, generate_trip_data, export_db_to_csv, get_currency, backup_db, DATE_FORMAT

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

st.title('Travels')

# show success message from previous action if any
if 'travels_msg' in st.session_state:
    st.success(st.session_state.pop('travels_msg'))

trips = generate_trip_data(c)

if not trips.empty:
    yearly_totals = trips.groupby(trips['date'].dt.year)['total'].sum()
    # previous full year's spend (0 until at least two years of trips exist)
    prev_year_total = yearly_totals.iloc[-2] if len(yearly_totals) >= 2 else 0
    avg_daily = int(trips['daily'].iloc[-10:].mean())
    st.write(
        f'A trip costs on average {CUR}{avg_daily} per day based on previous data. '
        f'Previous year travels added {CUR}{int(prev_year_total / 12)} per month in total costs.'
    )


# --- CHARTS ---

if not trips.empty:
    trip_order = trips['unique_trip'].tolist()

    # cost by trip
    st.subheader('Cost by Trip')
    fig = px.bar(
        trips, x='unique_trip', y=['flights', 'house', 'life'],
        category_orders={'unique_trip': trip_order},
        labels={'unique_trip': 'Trip', 'value': f'Cost ({CUR})', 'variable': 'Category'},
    )
    fig.for_each_trace(lambda t: t.update(name={'flights': 'Flights', 'house': 'Accommodation', 'life': 'Living'}[t.name]))
    fig.update_layout(xaxis_title=None, yaxis_title=f'Cost ({CUR})', legend_title='Category')
    st.plotly_chart(fig)

    # daily cost by trip
    st.subheader('Daily Cost by Trip')
    fig2 = px.bar(trips, x='unique_trip', y='daily', category_orders={'unique_trip': trip_order})
    fig2.update_layout(xaxis_title=None, yaxis_title=f'Daily Cost ({CUR})')
    st.plotly_chart(fig2)

    # cost by year
    st.subheader('Annual Travel Spend')
    yearly_trips = trips.groupby(trips['date'].dt.year)['total'].sum().reset_index()
    yearly_trips.columns = ['Year', 'Cost']
    fig3 = px.bar(yearly_trips, x='Year', y='Cost')
    fig3.update_layout(xaxis_title='Year', yaxis_title=f'Total Cost ({CUR})')
    st.plotly_chart(fig3)

# --- INSERT ---

st.subheader('Add Trip')

destinations = trips['place'].unique().tolist() if not trips.empty else []

col1, col2 = st.columns([1, 1])
with col1:
    date = st.date_input("Trip Date").strftime(DATE_FORMAT)
with col2:
    place = st.selectbox("Destination", destinations, accept_new_options=True)

col3, col4, col5, col6 = st.columns([1, 1, 1, 1])
with col3:
    days = st.number_input("Days", min_value=1, value=1)
with col4:
    flights = st.number_input(f"Flights {CUR}", min_value=0)
with col5:
    house = st.number_input(f"Accommodation {CUR}", min_value=0)
with col6:
    life = st.number_input(f"Living {CUR}", min_value=0)

if st.button("Save Trip"):
    backup_db(conn)
    conn.execute(
        "INSERT INTO trips_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (place, int(days), int(flights), int(house), int(life), date, 0),
    )
    conn.commit()
    export_db_to_csv(conn)
    st.session_state['travels_msg'] = "Trip saved!"
    st.rerun()

# --- SHOW ALL ---

if st.toggle('Show all saved trips'):
    display = trips[['unique_trip', 'days', 'flights', 'house', 'life', 'total', 'daily']].copy()
    display.columns = ['Trip', 'Days', f'Flights {CUR}', f'Accommodation {CUR}', f'Living {CUR}', f'Total {CUR}', f'Daily {CUR}']
    st.write(display)

# --- EDIT / DELETE ---

st.subheader('Edit Trip')

if trips.empty:
    st.info("No trips recorded yet.")
else:
    selected_label = st.selectbox("Select trip to edit", trips["label"])
    record = trips[trips["label"] == selected_label].iloc[0]

    with st.form("Edit Trip"):
        place       = st.text_input("Destination", value=record["place"])
        new_date    = st.date_input("Trip Date", value=record["date"].date())
        days        = st.number_input("Days", value=int(record["days"]), min_value=1)
        flights     = st.number_input(f"Flights {CUR}", value=int(record["flights"]), min_value=0)
        house       = st.number_input(f"Accommodation {CUR}", value=int(record["house"]), min_value=0)
        life        = st.number_input(f"Living {CUR}", value=int(record["life"]), min_value=0)
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            backup_db(conn)
            c.execute("""
                UPDATE trips_logs
                SET place = ?, days = ?, flights = ?, home = ?, life = ?, date = ?
                WHERE rowid = ?
            """, (place, int(days), int(flights), int(house), int(life),
                  new_date.strftime(DATE_FORMAT), int(record["rowid"])))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['travels_msg'] = "Trip updated successfully!"
            st.rerun()

        elif deleted:
            if not confirm_del:
                st.warning("Check 'Confirm deletion' to delete this record.")
            else:
                backup_db(conn)
                c.execute("DELETE FROM trips_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['travels_msg'] = "Trip deleted successfully!"
                st.rerun()
