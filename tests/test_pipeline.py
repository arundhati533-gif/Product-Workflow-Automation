import copy

import pytest

from core.parsing import parse_transcript
from core.pipeline import Pipeline, StageNotReady
from core.samples import load_sample_project, sample_transcript_path
from core.schemas import ExtractOutput, TasksOutput
from core.storage import Storage
from tests.fakes import EXTRACT, TASKS, FakeLLM


@pytest.fixture
def env():
    storage = Storage(":memory:")
    project_id = load_sample_project(storage)
    path = sample_transcript_path("01-kickoff.vtt")
    t = parse_transcript(filename=path.name, data=path.read_bytes())
    meeting_id = storage.create_meeting(project_id, "Kickoff", "2026-01-12", t.to_text(), t.source_format)
    llm = FakeLLM()
    yield Pipeline(storage, llm), storage, llm, project_id, meeting_id
    storage.close()


def run_and_approve(p, mid, stages):
    for s in stages:
        p.run_stage(mid, s)
        p.approve(mid, s)


def test_full_flow(env):
    p, storage, llm, pid, mid = env
    run_and_approve(p, mid, ["extract", "epics", "stories"])
    p.run_stage(mid, "tasks")
    tasks = storage.latest_stage_run(mid, "tasks")["output"]

    # Temporary NEW-n IDs are replaced and references rewritten.
    assert [t["id"] for t in tasks["tasks"]] == ["TASK-1", "TASK-2", "TASK-3", "TASK-4"]
    assert tasks["tasks"][1]["dependency_ids"] == ["TASK-1"]
    # Missing owner becomes a question, never a guess.
    assert [(m["item_id"], m["field"]) for m in tasks["missing_info"]] == [("TASK-3", "owner")]

    p.answer_missing_info(mid, {"TASK-3": "Raj Patel"})
    tasks = storage.latest_stage_run(mid, "tasks")["output"]
    assert tasks["tasks"][2]["owner"] == "Raj Patel" and tasks["missing_info"] == []

    p.approve(mid, "tasks")
    run_and_approve(p, mid, ["raid_email"])

    assert all(s.status == "approved" for s in p.status(mid).values())
    assert len(storage.list_backlog(pid, "story")) == 3
    assert len(storage.list_backlog(pid, "raid")) == 1
    # extract, epics, stories + DoR review, tasks, raid_email = 6 calls
    assert len(llm.calls) == 6
    assert storage.meeting_cost(mid) > 0


def test_stages_must_run_in_order(env):
    p, *_ , mid = env
    with pytest.raises(StageNotReady):
        p.run_stage(mid, "epics")
    p.run_stage(mid, "extract")
    with pytest.raises(StageNotReady):
        p.run_stage(mid, "epics")  # extract is only a draft


def test_context_is_identical_across_stages_for_caching(env):
    p, _, llm, _, mid = env
    run_and_approve(p, mid, ["extract", "epics"])
    assert llm.calls[0]["context"] == llm.calls[1]["context"]
    assert llm.calls[0]["system"] == llm.calls[1]["system"]
    assert "Sam Ortiz" in llm.calls[0]["context"]  # transcript is in the cached context
    assert "<approved_outputs>" in llm.calls[1]["prompt"]


def test_editing_earlier_stage_makes_later_stages_stale(env):
    p, storage, _, _, mid = env
    run_and_approve(p, mid, ["extract", "epics"])
    edited = copy.deepcopy(storage.latest_stage_run(mid, "extract")["output"])
    edited["requirements"][0]["statement"] = "Ingest by 7 a.m. Eastern."
    p.save_edit(mid, "extract", edited)

    status = p.status(mid)
    assert status["extract"].status == "draft"
    assert status["epics"].status == "stale"
    assert status["stories"].status == "blocked"

    p.approve(mid, "extract")
    assert p.status(mid)["epics"].status == "stale"  # inputs changed
    with pytest.raises(StageNotReady):
        p.approve(mid, "epics")
    p.run_stage(mid, "epics")
    assert p.status(mid)["epics"].status == "draft"


def test_regenerate_keeps_ids_locks_and_sends_feedback(env):
    p, storage, llm, _, mid = env
    p.run_stage(mid, "extract")
    edited = copy.deepcopy(storage.latest_stage_run(mid, "extract")["output"])
    edited["requirements"][0]["statement"] = "USER EDIT"
    p.save_edit(mid, "extract", edited)

    # The model returns REQ-1 changed and drops REQ-2; both must survive/restore as appropriate.
    regenerated = copy.deepcopy(EXTRACT)
    for i, r in enumerate(regenerated["requirements"]):
        r["id"] = f"REQ-{i + 1}"
    regenerated["requirements"][0]["statement"] = "MODEL REWRITE"
    del regenerated["requirements"][1]
    regenerated["requirements"].append({"statement": "New one", "type": "Functional", "source_quote": "x"})
    llm.overrides[ExtractOutput] = regenerated

    p.run_stage(mid, "extract", feedback="Split REQ-3", item_feedback={"REQ-2": "drop this"},
                locked_ids={"REQ-1"})
    out = storage.latest_stage_run(mid, "extract")["output"]
    reqs = {r["id"]: r["statement"] for r in out["requirements"]}
    assert reqs["REQ-1"] == "USER EDIT"  # lock enforced
    assert "REQ-2" not in reqs  # deleted by model per feedback
    assert "REQ-4" in reqs  # new item gets a fresh ID, REQ-2 is not reused
    prompt = llm.calls[-1]["prompt"]
    assert "<current_version>" in prompt and "Split REQ-3" in prompt and "REQ-2: drop this" in prompt
    assert "<locked_items>" in prompt
    run = storage.latest_stage_run(mid, "extract")
    assert [f["text"] for f in storage.list_feedback(run["id"])] == ["drop this", "Split REQ-3"]


def test_ids_are_unique_across_meetings_in_a_project(env):
    p, storage, _, pid, mid = env
    p.run_stage(mid, "extract")
    mid2 = storage.create_meeting(pid, "Follow-up", "2026-01-26", "Priya Nair: hi", "text")
    p.run_stage(mid2, "extract")
    ids2 = [r["id"] for r in storage.latest_stage_run(mid2, "extract")["output"]["requirements"]]
    assert ids2 == ["REQ-4", "REQ-5", "REQ-6"]


def test_dor_results_and_review(env):
    p, storage, _, _, mid = env
    run_and_approve(p, mid, ["extract", "epics"])
    p.run_stage(mid, "stories")
    results = p.dor_results(mid)
    assert results["STORY-1"].passed and "Dependencies and owner named" in results["STORY-1"].pending
    assert any(f.startswith("Small") for f in results["STORY-2"].failures)
    assert any("only 1" in f for f in results["STORY-2"].failures)
    assert any("no negative" in f for f in results["STORY-2"].failures)
    s3 = results["STORY-3"].failures
    assert any(f.startswith("Independent") for f in s3)
    assert any(f.startswith("No open questions: Q-1") for f in s3)

    # Editing a story drops the model review for that story only.
    out = copy.deepcopy(storage.latest_stage_run(mid, "stories")["output"])
    out["stories"][0]["i_want"] = "changed"
    p.save_edit(mid, "stories", out)
    reviewed = {r["story_id"] for r in storage.latest_stage_run(mid, "stories")["output"]["dor_review"]["reviews"]}
    assert reviewed == {"STORY-2", "STORY-3"}
    assert "Clear statement" in p.dor_results(mid)["STORY-1"].pending

    # Once tasks exist, unowned tasks fail the owner check.
    p.approve(mid, "stories")
    p.run_stage(mid, "tasks")
    assert any("no owner for TASK-3" in f for f in p.dor_results(mid)["STORY-2"].failures)


def test_unverified_quotes_and_link_warnings(env):
    p, storage, llm, _, mid = env
    bad = copy.deepcopy(EXTRACT)
    bad["requirements"][2]["source_quote"] = "a quote that was never said"
    llm.overrides[ExtractOutput] = bad
    p.run_stage(mid, "extract")
    assert p.unverified_quotes(mid) == ["REQ-3"]

    p.approve(mid, "extract")
    llm.overrides.clear()
    p.run_stage(mid, "epics")
    assert p.link_warnings(mid, "epics") == []


def test_tasks_missing_info_dropped_when_owner_present(env):
    p, storage, llm, _, mid = env
    run_and_approve(p, mid, ["extract", "epics", "stories"])
    tasks = copy.deepcopy(TASKS)
    tasks["missing_info"] = [{"item_id": "NEW-1", "field": "owner", "question": "?"},
                             {"item_id": "NEW-4", "field": "dependency", "question": "SkyLane date?"}]
    llm.overrides[TasksOutput] = tasks
    p.run_stage(mid, "tasks")
    missing = storage.latest_stage_run(mid, "tasks")["output"]["missing_info"]
    assert [(m["item_id"], m["field"]) for m in missing] == [("TASK-4", "dependency"), ("TASK-3", "owner")]
    assert any("unclear dependency on TASK-4" in f for f in p.dor_results(mid)["STORY-3"].failures)
