import pytest
from pydantic import ValidationError

from core.ids import assign_ids
from core.samples import load_sample_project, sample_project
from core.schemas import Epic, Requirement, Story
from core.storage import Storage


@pytest.fixture
def db():
    s = Storage(":memory:")
    yield s
    s.close()


# --- IDs -------------------------------------------------------------------

def _req(id_=None):
    return Requirement(id=id_, statement="s", type="Functional", source_quote="q")


def test_assign_ids_keeps_valid_and_fills_missing():
    items = [_req("REQ-2"), _req(), _req("REQ-5"), _req()]
    assign_ids(items, "REQ")
    assert [i.id for i in items] == ["REQ-2", "REQ-6", "REQ-5", "REQ-7"]


def test_assign_ids_replaces_malformed_and_duplicates():
    items = [_req("REQ-1"), _req("REQ-1"), _req("requirement one")]
    assign_ids(items, "REQ")
    assert [i.id for i in items] == ["REQ-1", "REQ-2", "REQ-3"]


def test_assign_ids_never_reuses_taken():
    items = [_req()]
    assign_ids(items, "REQ", taken=["REQ-1", "REQ-4"])
    assert items[0].id == "REQ-5"


# --- Schemas ---------------------------------------------------------------

def test_story_rejects_non_fibonacci_points_and_bad_priority():
    base = dict(epic_id="EPIC-1", as_a="traveller", i_want="x", so_that="y", acceptance_criteria=[])
    with pytest.raises(ValidationError):
        Story(**base, priority="High", points=4)
    with pytest.raises(ValidationError):
        Story(**base, priority="Urgent", points=3)
    s = Story(**base, priority="High", points=3)
    assert s.statement == "As a traveller, I want x, so that y."


def test_schema_json_is_usable_for_structured_output():
    schema = Epic.model_json_schema()
    assert set(schema["required"]) == {"title", "description", "requirement_ids"}


# --- Storage ---------------------------------------------------------------

def test_project_roster_and_meeting_roundtrip(db):
    pid = db.create_project("P", "desc")
    db.add_person(pid, "Priya Nair", "PM", "Integrations")
    db.add_system(pid, "Card Feed")
    mid = db.create_meeting(pid, "Kickoff", "2026-01-12", "text", "vtt")
    assert db.list_people(pid)[0]["name"] == "Priya Nair"
    assert db.list_systems(pid)[0]["name"] == "Card Feed"
    assert db.get_meeting(mid)["status"] == "new"
    db.set_meeting_status(mid, "stage 2")
    assert db.list_meetings(pid)[0]["status"] == "stage 2"


def test_stage_runs_history_status_and_cost(db):
    pid = db.create_project("P")
    mid = db.create_meeting(pid, "M", "2026-01-12", "t", "text")
    db.save_stage_run(mid, "extract", {"v": 1}, "h1", cost_usd=0.10)
    rid = db.save_stage_run(mid, "extract", {"v": 2}, "h2", cost_usd=0.05)
    db.set_stage_status(rid, "approved")
    latest = db.latest_stage_run(mid, "extract")
    assert latest["output"] == {"v": 2} and latest["status"] == "approved"
    assert len(db.stage_runs(mid, "extract")) == 2
    assert db.meeting_cost(mid) == pytest.approx(0.15)
    assert db.latest_stage_run(mid, "epics") is None
    with pytest.raises(ValueError):
        db.save_stage_run(mid, "unknown", {}, "h")


def test_feedback(db):
    pid = db.create_project("P")
    mid = db.create_meeting(pid, "M", "2026-01-12", "t", "text")
    rid = db.save_stage_run(mid, "extract", {}, "h")
    db.add_feedback(rid, "merge REQ-4 and REQ-7")
    db.add_feedback(rid, "too vague", item_id="REQ-2")
    fb = db.list_feedback(rid)
    assert [f["item_id"] for f in fb] == [None, "REQ-2"]


def test_backlog_upsert(db):
    pid = db.create_project("P")
    db.upsert_backlog_item(pid, None, "story", "STORY-1", {"title": "a"})
    db.upsert_backlog_item(pid, None, "story", "STORY-1", {"title": "b"}, status="dropped")
    items = db.list_backlog(pid, "story")
    assert len(items) == 1 and items[0]["data"] == {"title": "b"} and items[0]["status"] == "dropped"


def test_delete_project_cascades(db):
    pid = db.create_project("P")
    mid = db.create_meeting(pid, "M", "2026-01-12", "t", "text")
    db.save_stage_run(mid, "extract", {}, "h")
    db.delete_project(pid)
    assert db.get_meeting(mid) is None
    assert db.latest_stage_run(mid, "extract") is None


def test_load_sample_project_is_idempotent(db):
    pid = load_sample_project(db)
    assert load_sample_project(db) == pid
    assert len(db.list_people(pid)) == len(sample_project()["people"])
    assert len(db.list_systems(pid)) == len(sample_project()["systems"])


def test_storage_creates_file(tmp_path):
    s = Storage(tmp_path / "sub" / "app.db")
    s.create_project("P")
    s.close()
    assert (tmp_path / "sub" / "app.db").exists()


def test_assign_ids_replaces_ids_used_elsewhere_unless_kept():
    items = [_req("REQ-1"), _req("REQ-2")]
    renamed = assign_ids(items, "REQ", taken=["REQ-1", "REQ-2"], keep=["REQ-2"])
    assert [i.id for i in items] == ["REQ-3", "REQ-2"]
    assert renamed == {"REQ-1": "REQ-3"}
