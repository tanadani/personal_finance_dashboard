import streamlit as st
import pandas as pd
import sqlite3

st.set_page_config(layout="wide")

st.title("Personal Finances Dashboard")

st.toggle('Randomize data', key='randomize', value=False)