"""Projects home: list, create, load sample (user journey J1)."""

import sqlite3

import streamlit as st

from app import state
from core.samples import load_sample_project


def render() -> None:
    st.title("Projects")
    db = state.storage()

    col_new, col_sample = st.columns([3, 1])
    with col_new.expander("➕ New project", expanded=not db.list_projects()):
        with st.form("new_project", clear_on_submit=True):
            name = st.text_input("Name")
            description = st.text_area("Short description", height=80)
            if st.form_submit_button("Create project"):
                if not name.strip():
                    st.error("Enter a project name.")
                else:
                    try:
                        pid = db.create_project(name, description)
                    except sqlite3.IntegrityError:
                        st.error("A project with that name already exists.")
                    else:
                        state.go("project", project_id=pid)
    if col_sample.button("Load sample project", help="Fictional travel & expense integration with two transcripts"):
        state.go("project", project_id=load_sample_project(db))

    projects = db.list_projects()
    if not projects:
        st.info("No projects yet. Create one, or load the sample project to try the app.")
        return
    for p in projects:
        meetings = db.list_meetings(p["id"])
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.markdown(f"**{p['name']}**")
            left.caption(f"{len(meetings)} meeting(s) · {len(db.list_people(p['id']))} people on roster")
            if right.button("Open", key=f"open-{p['id']}"):
                state.go("project", project_id=p["id"])
