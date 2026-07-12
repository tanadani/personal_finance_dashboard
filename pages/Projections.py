import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
import datetime as dt
from utils import get_db_connection, get_currency, generate_full_log, simulate_paths, apply_monthly_xaxis

conn = get_db_connection()
c = conn.cursor()

CUR = get_currency()

st.title('Projections')

if 'randomize' not in st.session_state:
    st.session_state['randomize'] = False

N_SIMS = 3000  # fixed: enough paths for smooth percentile bands, still instant
EQUITY_RETURN = 8  # long-run historic equities return %, used as the return default

# ---------------------------------------------------------------------------
# Baseline: where the projection starts from.
#
# Everything below (Monte Carlo, retirement estimation, runway) depends on the
# saved history only through a handful of derived numbers. A custom starting
# point simply sources those same numbers from three inputs instead of the
# database — nothing is read or written — so the projection can be shown for
# someone else without entering their history on Data Insert.
# ---------------------------------------------------------------------------
custom_start = st.toggle(
    "Custom starting point",
    help="Type in starting numbers instead of using your saved history. "
         "Nothing is read from or written to your data — useful for showing "
         "someone else their projection.",
)

if custom_start:
    b1, b2, b3 = st.columns(3)
    with b1:
        total_assets = float(st.number_input(
            f"Current total assets ({CUR})", value=50_000, min_value=0, step=1_000))
    with b2:
        start_income = float(st.number_input(
            f"Net monthly income ({CUR})", value=3_000, min_value=0, step=100))
    with b3:
        current_expenses = int(st.number_input(
            f"Monthly expenses ({CUR})", value=2_000, min_value=0, step=100))

    saving_rate = (1 - current_expenses / start_income) if start_income > 0 else 0.0
    measured_sigma = 15.0  # no history to measure — generic equity volatility
    savings_rate_note = "from the income and expenses entered above"
    expenses_range = "as entered above"
    sample_note = "Custom starting point — using generic 8% return / 15% volatility defaults."
else:
    # generating full data using utils function with randomization option
    if st.session_state.randomize:
        full_data = generate_full_log(c, randomized=True)
    else:
        full_data = generate_full_log(c)

    if full_data.empty:
        st.info("No data yet. Add monthly positions and income on the **Data Insert** page "
                "to build a projection — or flip on **Custom starting point** above to "
                "project from numbers you type in.")
        st.stop()

    # -----------------------------------------------------------------------
    # Estimate investment volatility from the user's own history.
    #
    # A straight-line return hides that markets swing. We model the investment
    # return each month as a random draw (geometric Brownian motion), so the
    # projection becomes a *distribution* of outcomes rather than a single line.
    # Volatility defaults to the user's realised monthly returns annualised
    # (std x sqrt(12)); the expected return defaults to a long-run equity
    # assumption (8%) rather than the user's short, likely-rosy realised mean.
    # -----------------------------------------------------------------------
    monthly_returns = (full_data['capital_gain'] / full_data['start_value'].replace(0, np.nan)).dropna()
    n_obs = len(monthly_returns)

    if n_obs >= 2:
        measured_sigma = monthly_returns.std() * np.sqrt(12) * 100  # annualised volatility %
    else:
        measured_sigma = 15.0  # generic equity volatility with too little history

    start_income = full_data['income'].iloc[-3:].median()
    total_assets = float(full_data['end_value'].iloc[-1])
    saving_rate = (1 - full_data['expenses'].iloc[-12:].median() / full_data['income'].iloc[-12:].median())

    expenses_window = full_data.iloc[-12:]
    current_expenses = int(expenses_window['expenses'].mean())
    expenses_range = f"based on past {len(expenses_window)} months"
    savings_rate_note = f"based on the last {min(12, len(full_data))} months"

    # surface how the defaults were derived so the user can trust / override them
    sample_note = (
        f"Return defaults to the long-run equity assumption (8%); volatility defaults "
        f"to your realised ≈ {measured_sigma:.0f}% from the last {n_obs} months."
        if n_obs >= 2 else
        "Not enough return history yet — using generic 8% return / 15% volatility defaults."
    )

default_sigma = round(measured_sigma)

# prompting all the variable inputs

col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

with col1:
    annual_increase = st.number_input("Annual salary increase %", value=5) / 100
with col2:
    bonus_percentage = st.number_input("Annual bonus (% of pay)", value=60) / 100
with col3:
    income_tax = st.number_input("Income Tax %", value=40) / 100
with col4:
    expected_return = st.number_input(
        "Expected Investment Return %", value=EQUITY_RETURN,
        help="Defaults to the long-run historic return of equities (~8%). "
             "Lower it for a bond-heavier, more conservative plan."
    ) / 100

col5, col6 = st.columns([1, 1])

with col5:
    volatility = st.number_input(
        "Investment Volatility %", value=int(default_sigma), min_value=0,
        help="Annual standard deviation of returns. Higher = wider range of outcomes. "
             "Defaults to your own realised volatility. Equities are ~15-18%, "
             "a 60/40 portfolio ~10-12%."
    ) / 100
with col6:
    years = st.slider('Years', value=10, min_value=1, max_value=30, step=1)

n_sims = N_SIMS
months = years * 12

st.caption(sample_note)

# The recorded income is treated as take-home, so salary growth applies directly
# to it without any assumed starting tax bracket.
starting_tax_rate = income_tax

start_date = (pd.Timestamp.today().replace(day=1) + dt.timedelta(days=32)).replace(day=1)

dates = pd.date_range(start=start_date, periods=months, freq="MS")

# starting variables (start_income, total_assets, saving_rate come from the baseline block above)

gross_income = start_income / (1 - starting_tax_rate)
income = gross_income * (1 - income_tax)

# ---------------------------------------------------------------------------
# Monte Carlo engine
#
# Income, savings and bonus are deterministic (not market-driven), so we first
# build the per-month contribution schedule, then hand it to the shared
# simulate_paths engine (utils) which randomises only the market return.
# ---------------------------------------------------------------------------
inc = income
income_path, savings_path, bonus_path, contrib_path = [], [], [], []

for i in range(months):
    current_date = dates[i]

    # Increase income and apply bonus every February
    if current_date.month == 2 and i != 0:
        bonus = inc * 12 * bonus_percentage
        inc *= (1 + annual_increase)
    else:
        bonus = 0

    savings = inc * saving_rate

    income_path.append(int(inc))
    savings_path.append(int(savings))
    bonus_path.append(int(bonus))
    contrib_path.append(savings + bonus)

# (n_months, n_sims) matrix of asset values; kept in full so we can later pull
# out one real simulated trajectory (see "representative path" below) rather
# than reconstructing a fake one from cross-sectional percentiles
assets_history = simulate_paths(total_assets, contrib_path, expected_return, volatility, n_sims)

p10, p25, p50, p75, p90 = (list(np.percentile(assets_history, q, axis=1))
                           for q in (10, 25, 50, 75, 90))

projection = pd.DataFrame({
    "date": dates,
    "income": income_path,
    "savings": savings_path,
    "bonus": bonus_path,
    "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90,
})

# plotting the fan chart: shaded 10-90 and 25-75 bands around the median

BLUE = "#2a78d6"
fig = go.Figure()
# 10-90 band (lightest): invisible lower bound, then upper bound fills down to it
fig.add_trace(go.Scatter(x=dates, y=p10, line=dict(width=0), showlegend=False, hoverinfo='skip'))
fig.add_trace(go.Scatter(x=dates, y=p90, fill='tonexty', fillcolor='rgba(42,120,214,0.12)',
                         line=dict(width=0), name='10th–90th'))
# 25-75 band (darker)
fig.add_trace(go.Scatter(x=dates, y=p25, line=dict(width=0), showlegend=False, hoverinfo='skip'))
fig.add_trace(go.Scatter(x=dates, y=p75, fill='tonexty', fillcolor='rgba(42,120,214,0.30)',
                         line=dict(width=0), name='25th–75th'))
# median line
fig.add_trace(go.Scatter(x=dates, y=p50, line=dict(color=BLUE, width=2.5), name='Median'))
fig.update_layout(xaxis_title=None, yaxis_title=f'Total Assets ({CUR})',
                  hovermode='x unified', legend_title=None)
apply_monthly_xaxis(fig, len(dates))
st.plotly_chart(fig)

# writing only fixed variable

st.write(
    f'Assuming current net base salary savings rate: {int(saving_rate * 100)}% '
    f'({savings_rate_note})'
)

median_terminal = int(p50[-1])
low_terminal = int(p10[-1])
high_terminal = int(p90[-1])

colA, colB, colC = st.columns(3)
colA.metric(f"Median in {years}y", f"{CUR}{median_terminal:,}")
colB.metric(f"Downside (10th pct)", f"{CUR}{low_terminal:,}",
            f"{(low_terminal / median_terminal - 1) * 100:.0f}% vs median")
colC.metric(f"Upside (90th pct)", f"{CUR}{high_terminal:,}",
            f"+{(high_terminal / median_terminal - 1) * 100:.0f}% vs median")

# writing estimate retirement goal based on current expenses and fixed income return

st.subheader('Retirement Estimation')

fixed_income_return = st.number_input('Fixed Income Return %', value=5) / 100


def years_to_goal(asset_series):
    """First calendar year at which fixed-income yield on assets covers monthly expenses."""
    yields = np.array(asset_series) * fixed_income_return / 12 * (1 - income_tax)
    hit = np.where(yields >= current_expenses)[0]
    if len(hit) == 0:
        return None
    idx = int(hit[0])
    return max(0, int((dates[idx] - pd.Timestamp.today()).days / 365)), int(asset_series[idx])


st.write(
    f'To cover current average monthly expenses of {CUR}{current_expenses:,} ({expenses_range}) '
    f'from a fixed income return of {round(fixed_income_return * 100, 1)}%, here is when you reach that in each scenario:'
)

for label, series in [("Median (50th percentile)", p50),
                      ("Downside (10th percentile)", p10),
                      ("Upside (90th percentile)", p90)]:
    result = years_to_goal(series)
    if result is None:
        st.write(
            f'• **{label}:** not reached within the {years}-year window — '
            f'extend the horizon or raise the return/savings rate.'
        )
    else:
        yrs, asset_needed = result
        st.write(
            f'• **{label}:** in {yrs} years with {CUR}{asset_needed:,} of assets invested.'
        )

total_assets_last = int(total_assets)
runway_years = round(total_assets_last / (current_expenses * 12), 1) if current_expenses > 0 else 0.0

st.divider()
with st.container(border=True):
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.metric("Runway if you stopped today", f"{runway_years} years")
    with col_b:
        st.markdown(
            f"With current assets of **{CUR}{total_assets_last:,}** and average monthly expenses "
            f"of **{CUR}{current_expenses:,}** ({expenses_range}), you could cover your "
            f"spending for **{runway_years} years** without any income before running out — "
            f"assuming assets are simply drawn down, earning no return."
        )

# showing cleaned data for one representative simulated path
#
# The percentile bands (p10-p90) are computed independently at each month —
# each is "the 50th percentile across paths at month t", not a single
# trajectory. Differencing that series month-to-month doesn't recover a real
# path's returns: cross-sectional medians march upward almost monotonically
# purely because contributions are added every month, even though every
# individual simulated path has plenty of down months. So we instead pick one
# actual simulated path — the one whose ending assets land closest to the
# median outcome — and show its real (and sometimes negative) monthly returns.

rep_idx = int(np.argmin(np.abs(assets_history[-1] - p50[-1])))
rep_path = assets_history[:, rep_idx]
rep_prev = np.concatenate([[total_assets], rep_path[:-1]])
rep_returns = (rep_path - rep_prev - np.array(contrib_path)).astype(int)

clean_projection = projection.copy()
clean_projection['returns'] = rep_returns
clean_projection['total_assets'] = rep_path.astype(int)
clean_projection.index = clean_projection.date.dt.date
clean_projection = clean_projection[['income', 'bonus', 'savings', 'returns', 'total_assets']]
clean_projection.columns = ['Income', 'Bonus', 'Savings', 'Returns', 'Total Assets']

if st.toggle('Show Detailed Monthly Projection (one simulated path near the median outcome)'):
    st.caption(
        "A single simulated trajectory whose ending assets land near the median "
        "across all runs — shown so monthly returns include realistic down months, "
        "unlike the smoothed percentile bands in the chart above."
    )
    st.write(clean_projection)
