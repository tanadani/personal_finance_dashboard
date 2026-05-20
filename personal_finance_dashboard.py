import streamlit as st
import pandas as pd
import sqlite3

st.title("Personal Finances Dashboard")

st.toggle('Randomize data', key='randomize', value=False)