import json

import pytest

from core import config
from core.demo import ReplayLLM, load_recordings
from core.dor import pass_rate
from core.llm import LLMError
from core.parsing import parse_transcript
from core.pipeline import Pipeline
from core.samples import load_sample_project, sample_transcript_path
from core.schemas import STAGE_SCHEMAS, DorReviewOutput
from core.storage import Storage


@pytest.fixture
def env():
    storage = Storage(":memory:")
    pid = load_sample_project(storage)
    yield Pipeline(storage, ReplayLLM()), storage, pid
    storage.close()


def add_kickoff(storage, pid):
    path = sample_transcript_path("01-kickoff.vtt")
    t = parse_transcript(filename=path.name, data=path.read_bytes())
    return storage.create_meeting(pid, "Kickoff", "2026-01-12", t.to_text(), "vtt")


def run_all(p, mid):
    for stage in config.STAGES:
        p.run_stage(mid, stage)
        p.approve(mid, stage)


def test_recordings_are_valid():
    recordings = load_recordings()
    assert recordings, "no demo recordings found"
    for rec in recordings:
        for stage, schema in STAGE_SCHEMAS.items():
            schema.model_validate(rec.outputs[stage])
        DorReviewOutput.model_validate(rec.outputs["dor_review"])


def test_replay_reproduces_the_recording(env):
    p, storage, pid = env
    mid = add_kickoff(storage, pid)
    run_all(p, mid)
    rec = load_recordings()[0]
    for stage in config.STAGES:
        out = storage.latest_stage_run(mid, stage)["output"]
        out.pop("dor_review", None)
        assert out == rec.outputs[stage], stage
        assert p.link_warnings(mid, stage) == [], stage
    assert p.unverified_quotes(mid) == []
    assert storage.meeting_cost(mid) == 0
    passed, total = pass_rate(p.dor_results(mid))
    assert total == len(rec.outputs["stories"]["stories"]) and 0 < passed < total


def test_second_replay_in_same_project_gets_new_ids_with_consistent_links(env):
    p, storage, pid = env
    run_all(p, add_kickoff(storage, pid))
    mid2 = add_kickoff(storage, pid)
    run_all(p, mid2)
    extract = storage.latest_stage_run(mid2, "extract")["output"]
    req_ids = {r["id"] for r in extract["requirements"]}
    assert "REQ-1" not in req_ids
    assert all(set(q["linked_ids"]) <= req_ids for q in extract["open_questions"])
    for stage in ["epics", "stories", "tasks"]:
        assert p.link_warnings(mid2, stage) == [], stage
    tasks = storage.latest_stage_run(mid2, "tasks")["output"]["tasks"]
    task_ids = {t["id"] for t in tasks}
    assert all(set(t["dependency_ids"]) <= task_ids for t in tasks)


def test_regenerate_keeps_ids(env):
    p, storage, pid = env
    mid = add_kickoff(storage, pid)
    p.run_stage(mid, "extract")
    first = storage.latest_stage_run(mid, "extract")["output"]
    p.run_stage(mid, "extract", feedback="anything")
    assert storage.latest_stage_run(mid, "extract")["output"] == first


def test_other_transcripts_are_refused(env):
    p, storage, pid = env
    mid = storage.create_meeting(pid, "Mine", "2026-02-01", "Priya Nair: something else entirely", "text")
    with pytest.raises(LLMError, match="Demo mode only works"):
        p.run_stage(mid, "extract")


def test_placeholder_flag():
    meta = json.loads((config.SAMPLES_DIR / "demo" / "01-kickoff" / "meta.json").read_text())
    assert load_recordings()[0].placeholder == meta["placeholder"]
