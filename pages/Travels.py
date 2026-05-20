import sqlite3
import pandas as pd
import os
import plotly.express as px
import streamlit as st
import datetime as dt
from utils import generate_trip_data, export_db_to_csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "dashboard_memory.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
c = conn.cursor()

c.execute("""
    CREATE TABLE IF NOT EXISTS trips_logs (
        place        TEXT,
        days         INTEGER,
        flights      INTEGER,
        home         INTEGER,
        life         INTEGER,
        date         TEXT,
        unique_index INTEGER
    )
""")
conn.commit()

st.title('Travels')

# show success message from previous action if any
if 'travels_msg' in st.session_state:
    st.success(st.session_state.pop('travels_msg'))

trips = generate_trip_data(c)

per_month = trips.groupby(trips['date'].dt.year)['total'].sum().reset_index()['total'].iloc[-2]

if not trips.empty:
    st.write('A trip costs on average £' + str(int(trips['daily'].iloc[-10:].mean())) + ' per day based on previous data. Previous year travels added £' + str(int(per_month/12)) + ' per month in total costs.')


# --- CHARTS ---

if not trips.empty:
    trip_order = trips['unique_trip'].tolist()

    # cost by trip
    st.subheader('Cost by Trip')
    fig = px.bar(
        trips, x='unique_trip', y=['flights', 'house', 'life'],
        category_orders={'unique_trip': trip_order},
        labels={'unique_trip': 'Trip', 'value': 'Cost (£)', 'variable': 'Category'},
    )
    fig.for_each_trace(lambda t: t.update(name={'flights': 'Flights', 'house': 'Accommodation', 'life': 'Living'}[t.name]))
    fig.update_layout(xaxis_title=None, yaxis_title='Cost (£)', legend_title='Category')
    st.plotly_chart(fig)

    # daily cost by trip
    st.subheader('Daily Cost by Trip')
    fig2 = px.bar(trips, x='unique_trip', y='daily', category_orders={'unique_trip': trip_order})
    fig2.update_layout(xaxis_title=None, yaxis_title='Daily Cost (£)')
    st.plotly_chart(fig2)

    # cost by year
    st.subheader('Annual Travel Spend')
    yearly_trips = trips.groupby(trips['date'].dt.year)['total'].sum().reset_index()
    yearly_trips.columns = ['Year', 'Cost']
    fig3 = px.bar(yearly_trips, x='Year', y='Cost')
    fig3.update_layout(xaxis_title='Year', yaxis_title='Total Cost (£)')
    st.plotly_chart(fig3)

# --- INSERT ---

st.subheader('Add Trip')

destinations = trips['place'].unique().tolist() if not trips.empty else []

col1, col2 = st.columns([1, 1])
with col1:
    raw_date = str(st.date_input("Trip Date"))
    date = dt.datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d/%m/%y")
with col2:
    place = st.selectbox("Destination", destinations, accept_new_options=True)

col3, col4, col5, col6 = st.columns([1, 1, 1, 1])
with col3:
    days = st.number_input("Days", min_value=1, value=1)
with col4:
    flights = st.number_input("Flights £", min_value=0)
with col5:
    house = st.number_input("Accommodation £", min_value=0)
with col6:
    life = st.number_input("Living £", min_value=0)

if st.button("Save Trip"):
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
    display.columns = ['Trip', 'Days', 'Flights £', 'Accommodation £', 'Living £', 'Total £', 'Daily £']
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
        flights     = st.number_input("Flights £", value=int(record["flights"]), min_value=0)
        house       = st.number_input("Accommodation £", value=int(record["house"]), min_value=0)
        life        = st.number_input("Living £", value=int(record["life"]), min_value=0)
        confirm_del = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            c.execute("""
                UPDATE trips_logs
                SET place = ?, days = ?, flights = ?, home = ?, life = ?, date = ?
                WHERE rowid = ?
            """, (place, int(days), int(flights), int(house), int(life),
                  new_date.strftime("%d/%m/%y"), int(record["rowid"])))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['travels_msg'] = "Trip updated successfully!"
            st.rerun()

        elif deleted:
            if not confirm_del:
                st.warning("Check 'Confirm deletion' to delete this record.")
            else:
                c.execute("DELETE FROM trips_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['travels_msg'] = "Trip deleted successfully!"
                st.rerun()
