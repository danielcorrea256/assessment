"""Inflight Solutions — corporate travel optimizer and expense collector.

Run from the project root:

    streamlit run app.py

Optionally add `loyalty_rules.json` in the project root for custom loyalty tiers.
Add API keys to `.streamlit/secrets.toml` locally or to the app's secrets in
Streamlit Community Cloud. See `.streamlit/secrets.toml.example` for the format.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from utils.expense_parser import render_expense_collector
from utils.travel_optimizer import render_travel_optimizer

ROOT = Path(__file__).resolve().parent


def _apply_theme() -> None:
    st.markdown(
        """
        <style>
          :root { --primary-color: #14b8a6; }
          [data-testid="stAppViewContainer"] {
            background-image:
              radial-gradient(ellipse at 8% 0%, rgba(13, 148, 136, 0.13), transparent 38%);
          }
          .block-container {
            padding: 2rem 2rem 3rem;
            max-width: 1280px;
          }
          h1 { letter-spacing: -0.035em; }
          .inflight-kicker {
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-size: 0.75rem;
            font-weight: 700;
            color: #2dd4bf;
            margin-bottom: 0.35rem;
          }
          [data-testid="stTabs"] [role="tablist"] {
            gap: 0.4rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.28);
          }
          [data-testid="stTabs"] [data-testid="stTab"] {
            border-radius: 0.7rem 0.7rem 0 0;
            padding: 0.65rem 1rem;
            transition: background-color 140ms ease, color 140ms ease;
          }
          [data-testid="stTabs"] [data-testid="stTab"][aria-selected="true"] {
            background: rgba(13, 148, 136, 0.16);
            color: #5eead4;
          }
          [data-testid="stTabs"] .react-aria-SelectionIndicator {
            background-color: #14b8a6 !important;
          }
          [data-testid="stBaseButton-primary"] {
            background: linear-gradient(115deg, #0f766e, #0891b2);
            color: #ffffff;
            border: 0;
            border-radius: 0.7rem;
            box-shadow: 0 5px 16px rgba(8, 145, 178, 0.2);
          }
          [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(115deg, #115e59, #0e7490);
            color: #ffffff;
          }
          [data-testid="stMultiSelect"] [data-tag] {
            background-color: #0f766e !important;
            color: #ffffff !important;
            border-radius: 0.45rem;
          }
          [data-testid="stExpander"],
          [data-testid="stDataFrame"],
          [data-testid="stFileUploader"] {
            border-radius: 0.75rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Inflight Solutions",
        page_icon="✈️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _apply_theme()

    travel_tab, expense_tab = st.tabs(
        ["✈️ Travel Booking & Loyalty Optimizer", "🧾 Receipt & Expense Collector"]
    )
    with travel_tab:
        st.markdown('<p class="inflight-kicker">Challenge 1</p>', unsafe_allow_html=True)
        st.title("Travel Booking & Loyalty Optimizer")
        st.caption(
            "Compare North–South America itineraries by net effective cost, "
            "after ancillary fees and the value of miles earned at the selected loyalty tier."
        )
        render_travel_optimizer(ROOT)

    with expense_tab:
        st.markdown('<p class="inflight-kicker">Challenge 2</p>', unsafe_allow_html=True)
        st.title("Receipt & Expense Collector")
        st.caption(
            "Upload a receipt image or PDF and extract vendor, date, totals, "
            "tax, category, and project code for finance handoff."
        )
        render_expense_collector()


if __name__ == "__main__":
    main()
