import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import datetime as dt
from utils import (get_db_connection, get_currency, generate_pension_log,
                   simulate_paths, get_setting, set_setting, month_input,
                   export_db_to_csv, backup_db, DATE_FORMAT, apply_monthly_xaxis)

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

# UK pension rules (verify against the current tax year — these move):
#   - Normal Minimum Pension Age is 55, rising to 57 from 6 April 2028.
#   - 25% of the pot is normally tax-free (PCLS), capped by the Lump Sum
#     Allowance (£268,275 as of 2024/25).
LUMP_SUM_ALLOWANCE = 268_275
TAX_FREE_FRACTION = 0.25
N_SIMS = 3000

st.title('Pension')

# show success message from previous action if any
if 'pension_msg' in st.session_state:
    st.success(st.session_state.pop('pension_msg'))

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

pensions = generate_pension_log(c, randomized=st.session_state.randomize)

st.caption(
    "Private pensions are tracked separately because the money is locked until "
    "access age — it is **not** counted in the spendable assets or runway on other pages."
)


def _persist(key):
    set_setting(key, st.session_state[key])


# ---------------------------------------------------------------------------
# Current state — latest snapshot per provider
# ---------------------------------------------------------------------------
if not pensions.empty:
    latest = pensions.sort_values('date').groupby('provider').tail(1)
    locked_total = int(latest['value'].sum())
    monthly_contribution = int(latest['contribution'].sum())
else:
    locked_total = 0
    monthly_contribution = 0

col1, col2, col3 = st.columns(3)
with col1:
    current_age = st.number_input(
        "Your current age", min_value=16, max_value=74,
        value=int(get_setting("current_age", 30)),
        key="current_age", on_change=_persist, args=("current_age",),
    )
with col2:
    access_age = st.number_input(
        "Pension access age", min_value=55, max_value=75,
        value=int(get_setting("access_age", 57)),
        key="access_age", on_change=_persist, args=("access_age",),
        help="Normal Minimum Pension Age is 55, rising to 57 from 6 April 2028 (birth-date dependent).",
    )
with col3:
    years_to_access = max(0, access_age - current_age)
    st.metric("Years until you can access it", f"{years_to_access}")

mcol1, mcol2 = st.columns(2)
mcol1.metric("Locked pension pot", f"{CUR}{locked_total:,}")
mcol2.metric("Gross monthly contribution", f"{CUR}{monthly_contribution:,}")

# ---------------------------------------------------------------------------
# Monte Carlo projection to access age (pure accumulation, no withdrawals)
# ---------------------------------------------------------------------------
st.subheader('Projection to Access Age')

if pensions.empty:
    st.info("Add your first pension snapshot below to see a projection.")
elif years_to_access == 0:
    st.info(
        f"You are at or past the access age ({access_age}), so the pot is already "
        f"available: {CUR}{locked_total:,}."
    )
else:
    rcol1, rcol2 = st.columns(2)
    with rcol1:
        expected_return = st.number_input(
            "Expected Investment Return %", value=7,
            help="Pensions are usually equity-heavy over a long horizon; ~7% is a "
                 "common long-run equity assumption. Lower it for a de-risked pot.",
        ) / 100
        tcol1, tcol2 = st.columns(2)
        with tcol1:
            grow_contribution = st.toggle(
                "Grow contribution with salary",
                value=True,
                help="Pension contributions are usually a fixed % of pay, so they "
                     "rise with salary increases. Turn off to project a flat "
                     "monthly contribution instead.",
            )
        with tcol2:
            if grow_contribution:
                contribution_growth = st.number_input(
                    "Annual contribution growth %", value=5, min_value=0,
                ) / 100
            else:
                contribution_growth = 0.0
    with rcol2:
        volatility = st.number_input(
            "Investment Volatility %", value=15, min_value=0,
            help="Annual standard deviation of returns. Equities ~15-18%, "
                 "a 60/40 mix ~10-12%.",
        ) / 100

    months = years_to_access * 12
    start_date = (pd.Timestamp.today().replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    dates = pd.date_range(start=start_date, periods=months, freq="MS")
    # contributions step up once a year in line with salary growth; a zero
    # contribution stays zero regardless of the growth setting
    years_elapsed = np.arange(months) // 12
    contributions = monthly_contribution * (1.0 + contribution_growth) ** years_elapsed

    history = simulate_paths(locked_total, contributions, expected_return, volatility, N_SIMS)
    p10, p25, p50, p75, p90 = (np.percentile(history, q, axis=1) for q in (10, 25, 50, 75, 90))

    BLUE = "#2a78d6"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=p10, line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=dates, y=p90, fill='tonexty', fillcolor='rgba(42,120,214,0.12)',
                             line=dict(width=0), name='10th–90th'))
    fig.add_trace(go.Scatter(x=dates, y=p25, line=dict(width=0), showlegend=False, hoverinfo='skip'))
    fig.add_trace(go.Scatter(x=dates, y=p75, fill='tonexty', fillcolor='rgba(42,120,214,0.30)',
                             line=dict(width=0), name='25th–75th'))
    fig.add_trace(go.Scatter(x=dates, y=p50, line=dict(color=BLUE, width=2.5), name='Median'))
    fig.update_layout(xaxis_title=None, yaxis_title=f'Pension Pot ({CUR})',
                      hovermode='x unified', legend_title=None)
    apply_monthly_xaxis(fig, len(dates))
    st.plotly_chart(fig)

    median_pot = int(p50[-1])
    low_pot = int(p10[-1])
    high_pot = int(p90[-1])

    st.write(f"Projected pot at age **{access_age}** (in {years_to_access} years):")
    pcol1, pcol2, pcol3 = st.columns(3)
    pcol1.metric("Median", f"{CUR}{median_pot:,}")
    pcol2.metric("Downside (10th pct)", f"{CUR}{low_pot:,}",
                 f"{(low_pot / median_pot - 1) * 100:.0f}% vs median")
    pcol3.metric("Upside (90th pct)", f"{CUR}{high_pot:,}",
                 f"+{(high_pot / median_pot - 1) * 100:.0f}% vs median")

    # What the median pot could mean at access age
    tax_free = min(TAX_FREE_FRACTION * median_pot, LUMP_SUM_ALLOWANCE)
    sustainable_monthly = int(median_pot * 0.04 / 12)  # 4% rule as a rough income guide

    st.divider()
    with st.container(border=True):
        icol1, icol2 = st.columns([1, 2])
        with icol1:
            st.metric("Sustainable income from pot", f"{CUR}{sustainable_monthly:,}/mo")
        with icol2:
            st.markdown(
                f"On the median pot of **{CUR}{median_pot:,}** at age {access_age}, roughly "
                f"**{CUR}{int(tax_free):,}** could be taken tax-free (25%, capped at the "
                f"{CUR}{LUMP_SUM_ALLOWANCE:,} lump sum allowance), and a 4%-rule drawdown "
                f"would provide about **{CUR}{sustainable_monthly:,}/month** before tax. "
                "The State Pension is separate and not included."
            )

# ---------------------------------------------------------------------------
# Pot value by provider over time (needs at least one snapshot)
# ---------------------------------------------------------------------------
if not pensions.empty:
    if pensions['date'].nunique() >= 2:
        st.subheader('Pension Value by Provider')
        pivot = pensions.pivot_table(index='date', columns='provider',
                                     values='value', aggfunc='last').sort_index()
        fig = px.area(pivot, x=pivot.index, y=pivot.columns)
        fig.update_layout(xaxis_title=None, yaxis_title=f'Value ({CUR})', legend_title='Provider')
        apply_monthly_xaxis(fig, len(pivot))
        st.plotly_chart(fig)
    else:
        st.subheader('Current Pot by Provider')
        fig = px.bar(latest, x='provider', y='value')
        fig.update_layout(xaxis_title=None, yaxis_title=f'Value ({CUR})')
        st.plotly_chart(fig)

# ---------------------------------------------------------------------------
# Add snapshot
# ---------------------------------------------------------------------------
st.subheader('Add Snapshot')

providers = pensions['provider'].unique().tolist() if not pensions.empty else []

acol1, acol2 = st.columns([1, 1])
with acol1:
    record_date = month_input("Snapshot Date", key="pension_insert")
    date = record_date.strftime(DATE_FORMAT)
with acol2:
    provider = st.selectbox("Provider", providers, accept_new_options=True)

bcol1, bcol2 = st.columns([1, 1])
with bcol1:
    contribution = st.number_input(f"Gross monthly contribution {CUR}", min_value=0)
with bcol2:
    value = st.number_input(f"Current pot value {CUR}", min_value=0)

if st.button("Save Snapshot"):
    if not provider:
        st.warning("Enter a provider name.")
    else:
        existing = c.execute(
            "SELECT COUNT(*) FROM pension_logs WHERE date = ? AND provider = ?",
            (date, provider),
        ).fetchone()[0]
        if existing > 0:
            st.warning(
                f"A snapshot for '{provider}' in {record_date.strftime('%b %Y')} already "
                "exists. Edit it in the section below instead."
            )
        else:
            backup_db(conn)
            conn.execute("INSERT INTO pension_logs VALUES (?, ?, ?, ?, ?)",
                         (date, provider, int(contribution), int(value), 0))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['pension_msg'] = "Snapshot saved!"
            st.rerun()

# --- SHOW ALL ---

if not pensions.empty and st.toggle('Show all saved snapshots'):
    display = pensions[['date', 'provider', 'contribution', 'value']].copy()
    display['date'] = display['date'].dt.strftime('%b %Y')
    display.columns = ['Date', 'Provider', f'Contribution {CUR}', f'Value {CUR}']
    st.write(display)

# --- EDIT / DELETE ---

st.subheader('Edit Snapshot')

if pensions.empty:
    st.info("No pension snapshots recorded yet.")
else:
    pensions['label'] = pensions['provider'] + ' — ' + pensions['date'].dt.strftime('%b %Y')
    selected_label = st.selectbox("Select snapshot to edit", pensions['label'])
    record = pensions[pensions['label'] == selected_label].iloc[0]

    with st.form("Edit Pension"):
        new_date     = month_input("Snapshot Date", value=record["date"].date(),
                                   key=f"edit_pension_{int(record['rowid'])}")
        new_provider = st.text_input("Provider", value=record["provider"])
        contribution = st.number_input(f"Gross monthly contribution {CUR}",
                                       value=int(record["contribution"]), min_value=0)
        value        = st.number_input(f"Current pot value {CUR}",
                                       value=int(record["value"]), min_value=0)
        confirm_del  = st.checkbox("Confirm deletion")

        submitted = st.form_submit_button("Update Record")
        deleted   = st.form_submit_button("Delete Record")

        if submitted:
            backup_db(conn)
            c.execute("""
                UPDATE pension_logs
                SET date = ?, provider = ?, contribution = ?, value = ?
                WHERE rowid = ?
            """, (new_date.strftime(DATE_FORMAT), new_provider, int(contribution),
                  int(value), int(record["rowid"])))
            conn.commit()
            export_db_to_csv(conn)
            st.session_state['pension_msg'] = "Record updated successfully!"
            st.rerun()

        elif deleted:
            if not confirm_del:
                st.warning("Check 'Confirm deletion' to delete this record.")
            else:
                backup_db(conn)
                c.execute("DELETE FROM pension_logs WHERE rowid = ?", (int(record["rowid"]),))
                conn.commit()
                export_db_to_csv(conn)
                st.session_state['pension_msg'] = "Record deleted successfully!"
                st.rerun()
