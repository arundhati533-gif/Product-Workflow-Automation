"""Streamlit entry point:  streamlit run app/main.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app import state  # noqa: E402
from app.views import meeting, project, projects, settings  # noqa: E402

st.set_page_config(page_title="Meeting-to-Backlog", page_icon="🗂️", layout="wide")

VIEWS = {
    "projects": projects.render,
    "project": project.render,
    "meeting": meeting.render,
    "settings": settings.render,
}

with st.sidebar:
    st.markdown("### 🗂️ Meeting-to-Backlog")
    if st.button("Projects", width="stretch"):
        state.go("projects")
    if st.button("Settings", width="stretch"):
        state.go("settings")
    st.divider()
    s = state.load_settings()
    st.caption(f"Model: {s['model']}")
    spent = state.storage().month_cost()
    cap = s["monthly_cost_cap"]
    st.caption(f"Spent this month: ${spent:.2f}" + (f" of ${cap:.2f}" if cap else ""))
    if not state.api_key() and "llm" not in st.session_state:
        st.warning("No API key yet. Add one in Settings.")

VIEWS.get(state.current_view(), projects.render)()
