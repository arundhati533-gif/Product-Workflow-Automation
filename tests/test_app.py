"""Headless UI tests with Streamlit's AppTest, using the fake LLM."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.parsing import parse_transcript
from core.samples import load_sample_project, sample_transcript_path
from core.storage import Storage
from tests.fakes import FakeLLM

APP = str(Path(__file__).resolve().parent.parent / "app" / "main.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MTB_SETTINGS_PATH", str(tmp_path / "settings.json"))
    storage = Storage(":memory:")
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["storage"] = storage
    at.session_state["llm"] = FakeLLM()
    yield at, storage
    storage.close()


def _meeting(storage):
    pid = load_sample_project(storage)
    path = sample_transcript_path("01-kickoff.vtt")
    t = parse_transcript(filename=path.name, data=path.read_bytes())
    return storage.create_meeting(pid, "Kickoff", "2026-01-12", t.to_text(), "vtt")


def _click(at, key):
    at.button(key=key).click().run()
    assert not at.exception, at.exception


def test_projects_page_and_load_sample(app):
    at, storage = app
    at.run()
    assert not at.exception
    assert at.title[0].value == "Projects"
    next(b for b in at.button if b.label == "Load sample project").click().run()
    assert not at.exception
    assert at.session_state["view"] == "project"
    assert "Voyant" in at.title[0].value


def test_new_meeting_from_sample_transcript(app):
    at, storage = app
    pid = load_sample_project(storage)
    at.session_state["view"] = "project"
    at.session_state["project_id"] = pid
    at.run()
    at.radio(key="nm_source").set_value("Use a sample transcript").run()
    assert not at.exception
    assert any("Sam Ortiz" in w.value for w in at.warning)  # speaker not on roster
    next(b for b in at.button if b.label == "Create meeting").click().run()
    assert not at.exception
    assert at.session_state["view"] == "meeting"
    assert storage.list_meetings(pid)[0]["title"] == "Kickoff — Meridian card feed"


def test_stage_flow_generate_edit_approve(app):
    at, storage = app
    mid = _meeting(storage)
    at.session_state["view"] = "meeting"
    at.session_state["meeting_id"] = mid
    at.run()
    assert not at.exception

    _click(at, f"gen-{mid}-extract")
    run = storage.latest_stage_run(mid, "extract")
    assert run is not None and run["status"] == "draft"
    _click(at, f"approve-{mid}-extract-{run['id']}")
    assert storage.latest_stage_run(mid, "extract")["status"] == "approved"

    # The workspace moves on to Epics.
    _click(at, f"gen-{mid}-epics")
    _click(at, f"approve-{mid}-epics-{storage.latest_stage_run(mid, 'epics')['id']}")

    _click(at, f"gen-{mid}-stories")
    assert any("stories pass" in m.value for m in at.metric)
    _click(at, f"approve-{mid}-stories-{storage.latest_stage_run(mid, 'stories')['id']}")

    _click(at, f"gen-{mid}-tasks")
    assert any("Questions for you" in m.value for m in at.markdown)
    _click(at, f"approve-{mid}-tasks-{storage.latest_stage_run(mid, 'tasks')['id']}")

    _click(at, f"gen-{mid}-raid_email")
    assert any("Subject: Kickoff recap" in c.value for c in at.code)
    _click(at, f"approve-{mid}-raid_email-{storage.latest_stage_run(mid, 'raid_email')['id']}")
    assert any("All stages approved" in s.value for s in at.success)


def test_feedback_is_sent_on_regenerate(app):
    at, storage = app
    mid = _meeting(storage)
    at.session_state["view"] = "meeting"
    at.session_state["meeting_id"] = mid
    at.run()
    _click(at, f"gen-{mid}-extract")
    run_id = storage.latest_stage_run(mid, "extract")["id"]
    at.text_area(key=f"fb-{mid}-extract-{run_id}").input("Merge REQ-1 and REQ-2").run()
    _click(at, f"gen-{mid}-extract")
    llm = at.session_state["llm"]
    assert "Merge REQ-1 and REQ-2" in llm.calls[-1]["prompt"]


def test_no_api_key_blocks_generation(app, monkeypatch):
    at, storage = app
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    del at.session_state["llm"]
    mid = _meeting(storage)
    at.session_state["view"] = "meeting"
    at.session_state["meeting_id"] = mid
    at.run()
    assert not at.exception
    assert any("API key" in e.value for e in at.error)


def test_settings_page_saves_defaults(app):
    at, _ = app
    at.session_state["view"] = "settings"
    at.run()
    assert not at.exception
    at.selectbox[0].set_value("claude-sonnet-5")
    at.number_input[0].set_value(25.0)
    next(b for b in at.button if b.label == "Save").click().run()
    assert not at.exception
    from app import state
    assert state.load_settings() == {"model": "claude-sonnet-5", "monthly_cost_cap": 25.0}


def test_save_edits_round_trips_every_stage_editor(app):
    """Saving unchanged tables/forms must produce a valid new draft for each stage."""
    at, storage = app
    mid = _meeting(storage)
    at.session_state["view"] = "meeting"
    at.session_state["meeting_id"] = mid
    at.run()
    for stage in ["extract", "epics", "stories", "tasks", "raid_email"]:
        _click(at, f"gen-{mid}-{stage}")
        before = storage.latest_stage_run(mid, stage)
        save = [b for b in at.button if b.label == "Save edits"]
        assert save, stage
        save[-1].click().run()
        assert not at.exception, at.exception
        assert not at.error, [e.value for e in at.error]
        after = storage.latest_stage_run(mid, stage)
        assert after["id"] != before["id"] and after["model"] is None, stage
        assert pipeline_items(after) == pipeline_items(before), stage
        _click(at, f"approve-{mid}-{stage}-{after['id']}")


def pipeline_items(run):
    return {k: v for k, v in run["output"].items() if k != "dor_review"}
