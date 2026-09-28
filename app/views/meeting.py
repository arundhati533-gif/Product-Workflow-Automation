"""Meeting workspace: the five stages, each generate → review → edit/feedback → approve (user journey J2)."""

from __future__ import annotations

from typing import get_args

import streamlit as st
from pydantic import ValidationError

from app import state, tables
from core import config
from core.dor import pass_rate
from core.llm import LLMError, estimate_meeting_cost
from core.pipeline import STAGE_ITEMS, StageNotReady
from core.schemas import Level, Priority, RaidItem, Requirement

ICONS = {"approved": "✅", "draft": "📝", "stale": "⚠️", "not_started": "⚪", "blocked": "🔒"}
STATUS_TEXT = {"approved": "Approved", "draft": "Draft — review, edit or give feedback, then approve",
               "stale": "Out of date — an earlier stage changed", "not_started": "Not generated yet",
               "blocked": "Waiting for earlier stages"}
SUMMARY = "summary"


def render() -> None:
    db = state.storage()
    pipe = state.pipeline()
    meeting = db.get_meeting(st.session_state.get("meeting_id", -1))
    if meeting is None:
        st.warning("Meeting not found.")
        return
    mid = meeting["id"]
    project = db.get_project(meeting["project_id"])

    if st.button(f"← {project['name']}", type="tertiary"):
        state.go("project", project_id=project["id"])
    st.title(meeting["title"])
    st.caption(f"{meeting['date']} · cost so far ${db.meeting_cost(mid):.2f}")
    _show_flash()

    states = pipe.status(mid)
    options = config.STAGES + [SUMMARY]
    default = next((s for s in config.STAGES if states[s].status != "approved"), SUMMARY)
    stage = st.segmented_control(
        "Stage", options, default=default, required=True, key=f"stage-{mid}",
        format_func=lambda s: "Summary" if s == SUMMARY else f"{ICONS[states[s].status]} {config.STAGE_LABELS[s]}",
        label_visibility="collapsed",
    )
    st.divider()
    if stage == SUMMARY:
        _summary(pipe, mid)
    else:
        _stage(pipe, meeting, stage, states[stage])


# --- Stage frame -------------------------------------------------------------------

def _stage(pipe, meeting: dict, stage: str, st_state) -> None:
    mid = meeting["id"]
    st.subheader(config.STAGE_LABELS[stage])
    status = st_state.status
    st.caption(f"{ICONS[status]} {STATUS_TEXT[status]}")

    if status == "blocked":
        st.info("Approve the earlier stages first.")
        return
    if status == "not_started":
        _generate_button(pipe, meeting, stage, "Generate", primary=True)
        return
    if status == "stale":
        st.warning("An earlier stage changed after this was generated. Regenerate to update it; "
                   "items you edited are kept.")

    run = st_state.run
    _checks(pipe, mid, stage)
    EDITORS[stage](pipe, mid, run)
    st.divider()
    _feedback_and_actions(pipe, meeting, stage, run, status)


def _checks(pipe, mid: int, stage: str) -> None:
    if stage == "extract":
        bad = pipe.unverified_quotes(mid)
        if bad:
            st.warning(f"Source quote not found in the transcript for {', '.join(bad)}. Check these items.")
    for w in pipe.link_warnings(mid, stage):
        st.warning(w)


def _feedback_and_actions(pipe, meeting: dict, stage: str, run: dict, status: str) -> None:
    mid = meeting["id"]
    key = f"{mid}-{stage}-{run['id']}"
    comments: dict = st.session_state.setdefault(f"comments-{key}", {})

    st.markdown("**Feedback for the next version**")
    feedback = st.text_area("Feedback on the whole stage", key=f"fb-{key}", height=80,
                            placeholder="e.g. REQ-4 and REQ-7 are the same; ignore the reporting discussion")
    item_ids = [i["id"] for field, _ in STAGE_ITEMS[stage] for i in run["output"].get(field, [])]
    if item_ids:
        c1, c2, c3 = st.columns([1, 3, 1])
        item = c1.selectbox("Item", item_ids, key=f"item-{key}")
        text = c2.text_input("Comment on this item", key=f"itemtext-{key}")
        c3.write("")
        if c3.button("Add comment", key=f"add-{key}") and text.strip():
            comments[item] = text.strip()
            st.rerun()
    for item_id, text in list(comments.items()):
        c1, c2 = st.columns([6, 1])
        c1.caption(f"**{item_id}:** {text}")
        if c2.button("Remove", key=f"rm-{key}-{item_id}"):
            del comments[item_id]
            st.rerun()

    locked = pipe.edited_item_ids(mid, stage)
    if locked:
        st.caption(f"🔒 Your edits to {', '.join(sorted(locked))} will be kept when you regenerate.")

    c1, c2 = st.columns([1, 1])
    with c1:
        _generate_button(pipe, meeting, stage, "Regenerate", feedback=feedback, comments=comments,
                         locked=locked, clear_keys=[f"comments-{key}"])
    with c2:
        if st.button("Approve ✓", type="primary", disabled=status in ("approved", "stale"), key=f"approve-{key}"):
            try:
                pipe.approve(mid, stage)
            except StageNotReady as exc:
                st.error(str(exc))
            else:
                _flash("success", f"{config.STAGE_LABELS[stage]} approved.")
                st.session_state.pop(f"stage-{mid}", None)  # jump to the next stage
                st.rerun()


def _generate_button(pipe, meeting: dict, stage: str, label: str, primary: bool = False, feedback: str = "",
                     comments: dict | None = None, locked=frozenset(), clear_keys=()) -> None:
    mid = meeting["id"]
    if pipe.llm is None:
        st.error("Add your Anthropic API key in Settings to generate.")
        return
    db = state.storage()
    settings = state.load_settings()
    per_call = estimate_meeting_cost(pipe.llm.model, meeting["transcript_text"]) / (len(config.STAGES) + 1)
    estimate = per_call * (2 if stage == "stories" else 1)
    cap = settings["monthly_cost_cap"]
    over_cap = bool(cap) and db.month_cost() + estimate > cap
    confirmed = True
    if over_cap:
        st.warning(f"This run (~${estimate:.2f}) would take you over your ${cap:.2f} monthly cap.")
        confirmed = st.checkbox("Run anyway", key=f"cap-{mid}-{stage}")
    if st.button(f"{label} (~${estimate:.2f})", type="primary" if primary else "secondary",
                 disabled=not confirmed, key=f"gen-{mid}-{stage}"):
        with st.spinner(f"Generating {config.STAGE_LABELS[stage]}… this can take a minute."):
            try:
                pipe.run_stage(mid, stage, feedback=feedback, item_feedback=dict(comments or {}), locked_ids=locked)
            except (LLMError, StageNotReady) as exc:
                st.error(str(exc))
                return
        for k in clear_keys:
            st.session_state.pop(k, None)
        _flash("success", f"{config.STAGE_LABELS[stage]} generated. Review it below.")
        st.rerun()


def _save(pipe, mid: int, stage: str, output: dict) -> None:
    try:
        pipe.save_edit(mid, stage, output)
    except ValidationError as exc:
        st.error(f"Could not save: {_validation_message(exc)}")
    except StageNotReady as exc:
        st.error(str(exc))
    else:
        _flash("success", "Edits saved.")
        st.rerun()


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3])


# --- Stage editors ---------------------------------------------------------------------

def _options(model_cls, field: str) -> list[str]:
    """Allowed values of a Literal field."""
    return list(get_args(model_cls.model_fields[field].annotation))


LABELS = {"id": "ID", "linked_ids": "Linked to", "requirement_ids": "Requirements", "dependency_ids": "Depends on",
          "decided_by": "Decided by", "raised_by": "Raised by", "source_quote": "Source quote", "due_date": "Due date"}


def _table(field: str, items: list[dict], key: str, column_config: dict | None = None):
    config_ = {col: st.column_config.TextColumn(LABELS.get(col, col.replace("_", " ").capitalize()))
               for col in tables.COLUMNS[field]}
    config_["id"] = st.column_config.TextColumn("ID", disabled=True, width="small",
                                                help="Assigned by the app when you save")
    return st.data_editor(tables.to_df(field, items), key=key, num_rows="dynamic", hide_index=True,
                          width="stretch", column_config=config_ | (column_config or {}))


def _extract_editor(pipe, mid: int, run: dict) -> None:
    out = run["output"]
    with st.form(f"edit-extract-{run['id']}"):
        st.markdown(f"**Requirements** ({len(out['requirements'])})")
        reqs = _table("requirements", out["requirements"], f"req-{run['id']}", {
            "statement": st.column_config.TextColumn("Statement", width="large", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=_options(Requirement, "type"), required=True),
            "source_quote": st.column_config.TextColumn("Source quote", width="large"),
        })
        st.markdown(f"**Decisions** ({len(out['decisions'])})")
        decs = _table("decisions", out["decisions"], f"dec-{run['id']}",
                      {"statement": st.column_config.TextColumn("Statement", width="large", required=True)})
        st.markdown(f"**Open questions** ({len(out['open_questions'])})")
        qs = _table("open_questions", out["open_questions"], f"q-{run['id']}", {
            "question": st.column_config.TextColumn("Question", width="large", required=True),
            "resolved": st.column_config.CheckboxColumn("Resolved"),
        })
        if st.form_submit_button("Save edits"):
            _save(pipe, mid, "extract", {
                "requirements": [r | {"source_quote": r["source_quote"] or ""} for r in tables.from_df("requirements", reqs)],
                "decisions": [d | {"source_quote": d["source_quote"] or ""} for d in tables.from_df("decisions", decs)],
                "open_questions": tables.from_df("open_questions", qs),
            })


def _epics_editor(pipe, mid: int, run: dict) -> None:
    out = run["output"]
    with st.form(f"edit-epics-{run['id']}"):
        df = _table("epics", out["epics"], f"epics-{run['id']}", {
            "title": st.column_config.TextColumn("Title", required=True),
            "description": st.column_config.TextColumn("Description", width="large"),
            "requirement_ids": st.column_config.TextColumn("Requirements", help="Comma-separated, e.g. REQ-1, REQ-4"),
        })
        if st.form_submit_button("Save edits"):
            _save(pipe, mid, "epics", {"epics": tables.from_df("epics", df)})


def _stories_editor(pipe, mid: int, run: dict) -> None:
    out = run["output"]
    results = pipe.dor_results(mid)
    passed, total = pass_rate(results)
    epics = [e["id"] for e in (pipe.approved_output(mid, "epics") or {"epics": []})["epics"]]
    c1, c2 = st.columns(2)
    c1.metric("Definition of Ready", f"{passed}/{total} stories pass")
    c2.metric("Total points", sum(s["points"] for s in out["stories"]))
    st.caption("Acceptance criteria: one per line, `Given …; When …; Then …`. Start a line with `[negative]` "
               "for a negative or edge case.")

    with st.form(f"edit-stories-{run['id']}"):
        edited, errors = [], []
        for s in out["stories"] + [None]:
            new = s is None
            s = s or {"id": None, "epic_id": epics[0] if epics else "", "as_a": "", "i_want": "", "so_that": "",
                      "acceptance_criteria": [], "priority": "Medium", "points": 3, "requirement_ids": []}
            r = results.get(s["id"])
            badge = "➕" if new else ("✅" if r and r.passed else "⚠️")
            label = "Add a story" if new else f"{badge} {s['id']} · {s['i_want'][:70]} ({s['priority']}, {s['points']} pts)"
            k = f"{run['id']}-{s['id'] or 'new'}"
            with st.expander(label):
                if r and r.failures:
                    st.warning("\n".join(f"- {f}" for f in r.failures))
                if r and r.pending:
                    st.caption(f"Checked later: {', '.join(r.pending)}")
                c1, c2, c3 = st.columns([2, 1, 1])
                epic_id = c1.selectbox("Epic", epics, index=epics.index(s["epic_id"]) if s["epic_id"] in epics else 0,
                                       key=f"epic-{k}")
                priority = c2.selectbox("Priority", list(Priority.__args__),
                                        index=list(Priority.__args__).index(s["priority"]), key=f"prio-{k}")
                points = c3.selectbox("Points", config.FIBONACCI_POINTS,
                                      index=config.FIBONACCI_POINTS.index(s["points"]), key=f"pts-{k}")
                as_a = st.text_input("As a", s["as_a"], key=f"asa-{k}")
                i_want = st.text_input("I want", s["i_want"], key=f"want-{k}")
                so_that = st.text_input("So that", s["so_that"], key=f"so-{k}")
                ac_text = st.text_area("Acceptance criteria", tables.ac_to_text(s["acceptance_criteria"]),
                                       height=120, key=f"ac-{k}")
                reqs = st.text_input("Requirements", ", ".join(s["requirement_ids"]), key=f"reqs-{k}")
                delete = False if new else st.checkbox("Delete this story", key=f"del-{k}")
            if delete or (new and not i_want.strip()):
                continue
            try:
                criteria = tables.text_to_ac(ac_text)
            except ValueError as exc:
                errors.append(f"{s['id'] or 'New story'}: {exc}")
                continue
            edited.append({"id": s["id"], "epic_id": epic_id, "as_a": as_a, "i_want": i_want, "so_that": so_that,
                           "acceptance_criteria": criteria, "priority": priority, "points": points,
                           "requirement_ids": tables.split_ids(reqs)})
        if st.form_submit_button("Save edits"):
            if errors:
                for e in errors:
                    st.error(e)
            else:
                _save(pipe, mid, "stories", {"stories": edited})


def _tasks_editor(pipe, mid: int, run: dict) -> None:
    out = run["output"]
    db = state.storage()
    project_id = db.get_meeting(mid)["project_id"]
    roster = [p["name"] for p in db.list_people(project_id)]
    stories = [s["id"] for s in (pipe.approved_output(mid, "stories") or {"stories": []})["stories"]]

    if out["missing_info"]:
        st.markdown("**Questions for you** — the transcript didn't say, so nothing was guessed.")
        with st.form(f"missing-{run['id']}"):
            owners, deps = {}, {}
            tasks_by_id = {t["id"]: t for t in out["tasks"]}
            for m in out["missing_info"]:
                task = tasks_by_id.get(m["item_id"], {})
                label = f"{m['item_id']} · {task.get('description', '')[:80]} — {m['question']}"
                if m["field"] == "owner":
                    owners[m["item_id"]] = st.selectbox(label, roster, index=None, accept_new_options=True,
                                                        placeholder="Choose or type a name",
                                                        key=f"own-{run['id']}-{m['item_id']}") or ""
                else:
                    deps[m["item_id"]] = st.text_input(label, key=f"dep-{run['id']}-{m['item_id']}")
            if st.form_submit_button("Save answers"):
                try:
                    pipe.answer_missing_info(mid, owners, deps)
                except (ValidationError, StageNotReady) as exc:
                    st.error(str(exc))
                else:
                    _flash("success", "Answers saved.")
                    st.rerun()

    with st.form(f"edit-tasks-{run['id']}"):
        st.markdown(f"**Tasks** ({len(out['tasks'])})")
        df = _table("tasks", out["tasks"], f"tasks-{run['id']}", {
            "story_id": st.column_config.SelectboxColumn("Story", options=stories, required=True),
            "description": st.column_config.TextColumn("Description", width="large", required=True),
            "owner": st.column_config.SelectboxColumn("Owner", options=roster),
            "dependency_ids": st.column_config.TextColumn("Depends on", help="Comma-separated task IDs"),
        })
        if st.form_submit_button("Save edits"):
            _save(pipe, mid, "tasks", {"tasks": tables.from_df("tasks", df),
                                       "missing_info": out["missing_info"]})


def _raid_email_editor(pipe, mid: int, run: dict) -> None:
    out = run["output"]
    email = out["email"]
    levels = list(Level.__args__)
    with st.form(f"edit-raid-{run['id']}"):
        st.markdown(f"**RAID log** ({len(out['raid'])})")
        raid = _table("raid", out["raid"], f"raid-{run['id']}", {
            "type": st.column_config.SelectboxColumn("Type", options=_options(RaidItem, "type"), required=True),
            "description": st.column_config.TextColumn("Description", width="large", required=True),
            "status": st.column_config.SelectboxColumn("Status", options=_options(RaidItem, "status"), required=True),
            "impact": st.column_config.SelectboxColumn("Impact", options=levels, required=True),
            "likelihood": st.column_config.SelectboxColumn("Likelihood", options=levels),
            "mitigation": st.column_config.TextColumn("Mitigation / next step", width="large"),
        })
        st.markdown("**Follow-up email**")
        subject = st.text_input("Subject", email["subject"])
        summary = st.text_area("Summary", email["summary"], height=90)
        decisions = st.text_area("Decisions (one per line)", "\n".join(email["decisions"]), height=100)
        actions = st.data_editor(
            [{"action": a["action"], "owner": a.get("owner"), "due_date": a.get("due_date")} for a in email["action_items"]],
            num_rows="dynamic", width="stretch", key=f"actions-{run['id']}")
        questions = st.text_area("Open questions (one per line)", "\n".join(email["open_questions"]), height=100)
        if st.form_submit_button("Save edits"):
            action_rows = actions.to_dict("records") if hasattr(actions, "to_dict") else actions
            _save(pipe, mid, "raid_email", {
                "raid": [r | {"mitigation": r["mitigation"] or ""} for r in tables.from_df("raid", raid)],
                "email": {
                    "subject": subject, "summary": summary,
                    "decisions": [d.strip() for d in decisions.splitlines() if d.strip()],
                    "action_items": [{"action": str(a["action"]), "owner": a.get("owner") or None,
                                      "due_date": a.get("due_date") or None}
                                     for a in action_rows if a.get("action")],
                    "open_questions": [q.strip() for q in questions.splitlines() if q.strip()],
                },
            })
    st.markdown("**Email ready to copy**")
    st.code(tables.email_to_text(email), language=None, wrap_lines=True)


EDITORS = {
    "extract": _extract_editor,
    "epics": _epics_editor,
    "stories": _stories_editor,
    "tasks": _tasks_editor,
    "raid_email": _raid_email_editor,
}


# --- Summary --------------------------------------------------------------------------

def _summary(pipe, mid: int) -> None:
    db = state.storage()
    st.subheader("Summary")
    counts = {}
    for stage in config.STAGES:
        out = pipe.approved_output(mid, stage)
        for field, _ in STAGE_ITEMS[stage]:
            counts[field.replace("_", " ").capitalize()] = len(out[field]) if out else "—"
    cols = st.columns(4)
    for i, (label, n) in enumerate(counts.items()):
        cols[i % 4].metric(label, n)
    passed, total = pass_rate(pipe.dor_results(mid))
    c1, c2 = st.columns(2)
    c1.metric("Definition of Ready", f"{passed}/{total}" if total else "—")
    c2.metric("Total cost", f"${db.meeting_cost(mid):.2f}")
    if all(s.status == "approved" for s in pipe.status(mid).values()):
        st.success("All stages approved.")
    else:
        st.info("Some stages are not approved yet.")
    st.caption("Excel export is added in the next milestone (M4).")


# --- Flash messages survive st.rerun() ---------------------------------------------

def _flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def _show_flash() -> None:
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)

