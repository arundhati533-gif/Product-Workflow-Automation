"""Project page: meetings, new meeting, roster, systems, backlog."""

from datetime import date

import pandas as pd
import streamlit as st

from app import state
from core import config
from core.llm import estimate_meeting_cost, estimate_tokens
from core.parsing import SUPPORTED_EXTENSIONS, TranscriptError, parse_transcript
from core.samples import SAMPLE_TRANSCRIPTS, sample_project, sample_transcript_path


def render() -> None:
    db = state.storage()
    project = db.get_project(st.session_state.get("project_id", -1))
    if project is None:
        st.warning("Project not found.")
        if st.button("Back to projects"):
            state.go("projects")
        return

    st.caption("Projects /")
    st.title(project["name"])
    if project["description"]:
        st.write(project["description"])

    meetings_tab, new_tab, roster_tab, systems_tab, backlog_tab = st.tabs(
        ["Meetings", "New meeting", "Roster", "Systems", "Backlog"])
    with meetings_tab:
        _meetings(project)
    with new_tab:
        _new_meeting(project)
    with roster_tab:
        _roster(project)
    with systems_tab:
        _systems(project)
    with backlog_tab:
        _backlog(project)


def _meetings(project: dict) -> None:
    db = state.storage()
    meetings = db.list_meetings(project["id"])
    if not meetings:
        st.info("No meetings yet. Add one in the **New meeting** tab.")
        return
    for m in meetings:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            left.markdown(f"**{m['title']}** · {m['date']}")
            left.caption(f"{_status_label(m['status'])} · cost so far ${db.meeting_cost(m['id']):.2f}")
            if right.button("Open", key=f"meeting-{m['id']}"):
                state.go("meeting", meeting_id=m["id"])


def _status_label(status: str) -> str:
    if status == "new":
        return "Not started"
    stage, _, phase = status.partition(":")
    n = config.STAGES.index(stage) + 1 if stage in config.STAGES else "?"
    return f"Stage {n} of {len(config.STAGES)} · {phase}"


def _new_meeting(project: dict) -> None:
    db = state.storage()
    is_sample = project["name"] == sample_project()["name"]

    title = st.text_input("Meeting title", key="nm_title")
    when = st.date_input("Date", value=date.today(), key="nm_date")
    source = st.radio("Transcript", ["Upload a file", "Paste text"] + (["Use a sample transcript"] if is_sample else []),
                      horizontal=True, key="nm_source")

    transcript = None
    try:
        if source == "Upload a file":
            f = st.file_uploader("Transcript file", type=[e.lstrip(".") for e in sorted(SUPPORTED_EXTENSIONS)])
            if f is not None:
                transcript = parse_transcript(filename=f.name, data=f.getvalue())
        elif source == "Paste text":
            text = st.text_area("Paste the transcript", height=200, key="nm_text")
            if text.strip():
                transcript = parse_transcript(text=text)
        else:
            name = st.selectbox("Sample", list(SAMPLE_TRANSCRIPTS),
                                format_func=lambda n: SAMPLE_TRANSCRIPTS[n][0], key="nm_sample")
            path = sample_transcript_path(name)
            transcript = parse_transcript(filename=path.name, data=path.read_bytes())
            if not title:
                title = SAMPLE_TRANSCRIPTS[name][0]
                when = date.fromisoformat(SAMPLE_TRANSCRIPTS[name][1])
    except TranscriptError as exc:
        st.error(str(exc))
        return

    if transcript is None:
        return

    # Preview (user journey J2, step 1)
    text = transcript.to_text()
    model = state.load_settings()["model"]
    roster = {p["name"] for p in db.list_people(project["id"])}
    unknown = [s for s in transcript.speakers if s not in roster]
    st.subheader("Preview")
    c1, c2, c3 = st.columns(3)
    c1.metric("Speakers", len(transcript.speakers))
    c2.metric("Words", f"{transcript.word_count:,}")
    c3.metric("Estimated cost (all stages)", f"${estimate_meeting_cost(model, text):.2f}", help=f"Using {model}")
    if estimate_tokens(text) > config.TRANSCRIPT_WARN_TOKENS:
        st.warning("This is a very long transcript. It will still fit in one call, but costs more.")
    if unknown:
        st.warning(f"Not on the roster: {', '.join(unknown)}")
        for name in unknown:
            if st.button(f"Add {name} to roster", key=f"add-{name}"):
                db.add_person(project["id"], name)
                st.rerun()
    with st.expander("Transcript as the model will see it"):
        st.text(text[:5000] + ("\n…" if len(text) > 5000 else ""))

    if st.button("Create meeting", type="primary"):
        if not title.strip():
            st.error("Enter a meeting title.")
            return
        mid = db.create_meeting(project["id"], title, when.isoformat(), text, transcript.source_format)
        state.go("meeting", meeting_id=mid)


def _roster(project: dict) -> None:
    db = state.storage()
    people = db.list_people(project["id"])
    st.caption("Used to match owners and speakers. Add people as they join meetings.")
    if people:
        st.dataframe(pd.DataFrame(people)[["name", "role", "team"]], hide_index=True, width="stretch")
    with st.form("add_person", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name")
        role = c2.text_input("Role")
        team = c3.text_input("Team")
        if st.form_submit_button("Add person") and name.strip():
            db.add_person(project["id"], name, role, team)
            st.rerun()


def _systems(project: dict) -> None:
    db = state.storage()
    systems = db.list_systems(project["id"])
    st.caption("Systems and partners the team integrates with. Used to find dependencies.")
    if systems:
        st.dataframe(pd.DataFrame(systems)[["name", "description"]], hide_index=True, width="stretch")
    with st.form("add_system", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("System")
        description = c2.text_input("Description")
        if st.form_submit_button("Add system") and name.strip():
            db.add_system(project["id"], name, description)
            st.rerun()


def _backlog(project: dict) -> None:
    db = state.storage()
    items = db.list_backlog(project["id"])
    if not items:
        st.info("The backlog fills up as you approve epics, stories, tasks and RAID items.")
        return
    for type_, label in [("epic", "Epics"), ("story", "Stories"), ("task", "Tasks"), ("raid", "RAID")]:
        rows = [{"id": i["item_key"], **{k: v for k, v in i["data"].items() if k != "id"}}
                for i in items if i["type"] == type_]
        if rows:
            st.markdown(f"**{label}** ({len(rows)})")
            st.dataframe(pd.DataFrame(rows).astype(str), hide_index=True, width="stretch")
