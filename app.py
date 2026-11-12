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
            background:
              radial-gradient(ellipse 900px 480px at 10% -10%, rgba(20, 184, 166, 0.16), transparent 55%),
              radial-gradient(ellipse 700px 420px at 100% 0%, rgba(8, 145, 178, 0.12), transparent 50%);
          }
          .block-container {
            padding: 1.5rem 2rem 3rem;
            max-width: 1280px;
          }
          h1, h2, h3 { letter-spacing: -0.02em; }

          /* Hero banner */
          .inflight-hero {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1.5rem 1.75rem;
            margin-bottom: 1.5rem;
            border-radius: 1rem;
            background: linear-gradient(120deg, rgba(15, 118, 110, 0.35), rgba(8, 145, 178, 0.18));
            border: 1px solid rgba(94, 234, 212, 0.25);
          }
          .inflight-hero__badge {
            font-size: 2rem;
            line-height: 1;
          }
          .inflight-hero__title {
            margin: 0;
            font-size: 1.5rem;
            font-weight: 800;
            color: #f8fafc;
            letter-spacing: -0.01em;
          }
          .inflight-hero__subtitle {
            margin: 0.15rem 0 0;
            font-size: 0.9rem;
            color: #94a3b8;
          }

          .inflight-kicker {
            display: inline-block;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-size: 0.72rem;
            font-weight: 700;
            color: #2dd4bf;
            background: rgba(45, 212, 191, 0.12);
            border-radius: 999px;
            padding: 0.2rem 0.65rem;
            margin-bottom: 0.6rem;
          }

          /* Tabs */
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

          /* Buttons */
          [data-testid="stBaseButton-primary"] {
            background: linear-gradient(115deg, #0f766e, #0891b2);
            color: #ffffff;
            border: 0;
            border-radius: 0.7rem;
            box-shadow: 0 5px 16px rgba(8, 145, 178, 0.25);
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

          /* Cards and surfaces */
          [data-testid="stExpander"],
          [data-testid="stDataFrame"],
          [data-testid="stFileUploader"],
          [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 0.9rem;
          }
          [data-testid="stVerticalBlockBorderWrapper"] {
            border-color: rgba(148, 163, 184, 0.22) !important;
          }
          [data-testid="stMetric"] {
            background: rgba(148, 163, 184, 0.08);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 0.8rem;
            padding: 0.75rem 1rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_hero() -> None:
    st.markdown(
        """
        <div class="inflight-hero">
          <div class="inflight-hero__badge">🧭</div>
          <div>
            <p class="inflight-hero__title">Inflight Solutions</p>
            <p class="inflight-hero__subtitle">
              Corporate travel optimizer &amp; expense collector — fare intelligence
              and receipt automation in one workspace.
            </p>
          </div>
        </div>
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
    _render_hero()

    travel_tab, expense_tab = st.tabs(
        ["✈️ Travel Booking & Loyalty Optimizer", "🧾 Receipt & Expense Collector"]
    )
    with travel_tab:
        st.markdown('<span class="inflight-kicker">Challenge 1</span>', unsafe_allow_html=True)
        st.title("Travel Booking & Loyalty Optimizer")
        st.caption(
            "Compare North–South America itineraries by net effective cost, "
            "after ancillary fees and the value of miles earned at the selected loyalty tier."
        )
        render_travel_optimizer(ROOT)

    with expense_tab:
        st.markdown('<span class="inflight-kicker">Challenge 2</span>', unsafe_allow_html=True)
        st.title("Receipt & Expense Collector")
        st.caption(
            "Upload a receipt image or PDF and extract vendor, date, totals, "
            "tax, category, and project code for finance handoff."
        )
        render_expense_collector()


if __name__ == "__main__":
    main()
