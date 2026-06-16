import streamlit as st
from utils import get_db_connection, render_controls

st.set_page_config(page_title="Finance Dashboard", layout="wide")

# ensure the database and its schema exist before any page queries it
get_db_connection()

# shared sidebar settings — rendered on every page so their state persists;
# returns whether the optional IBKR brokerage analytics page is enabled
ibkr_enabled = render_controls()

# explicit, ordered, capitalized navigation
pages = [
    st.Page("pages/Home.py",        title="Home",        icon="🏠", default=True),
    st.Page("pages/Data_Insert.py", title="Data Insert", icon="📝"),
    st.Page("pages/Analytics.py",   title="Analytics",   icon="📊"),
    st.Page("pages/Investments.py", title="Investments", icon="📈"),
    st.Page("pages/Projections.py", title="Projections", icon="🔮"),
    st.Page("pages/Travels.py",     title="Travels",     icon="✈️"),
]

# optional feature: only appears in the nav when enabled (off by default)
if ibkr_enabled:
    pages.append(
        st.Page("pages/IBKR_Direct_Sleeve.py", title="IBKR Direct Sleeve", icon="💼")
    )

pg = st.navigation(pages)
pg.run()
