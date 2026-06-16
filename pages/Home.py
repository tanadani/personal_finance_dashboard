import streamlit as st
from utils import get_db_connection

st.title("Personal Finance Dashboard")

st.write(
    "Track your savings, investments, expenses, travel, and retirement outlook — "
    "all stored locally on your machine."
)

conn = get_db_connection()

# --- First-run guidance ---
counts = conn.execute(
    "SELECT (SELECT COUNT(*) FROM monthly_logs) + (SELECT COUNT(*) FROM salary_logs)"
).fetchone()[0]

if counts == 0:
    st.info(
        "👋 **Welcome!** Your dashboard is empty.\n\n"
        "1. Open the **Data Insert** page in the left sidebar.\n"
        "2. Add your monthly **income** and your account **positions** "
        "(inflows, outflows, end value).\n"
        "3. The **Analytics**, **Investments**, and **Projections** pages will "
        "populate automatically.\n\n"
        "Use the **Travels** page any time to track trip costs. Brokerage analytics "
        "can be enabled under **⚙️ Settings** in the sidebar."
    )
else:
    st.success("Your data is loaded. Use the sidebar to explore each section.")
