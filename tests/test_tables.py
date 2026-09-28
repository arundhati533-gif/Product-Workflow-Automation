import pandas as pd
import pytest

from app import tables
from tests.fakes import AC_OK, RAID_EMAIL


def test_round_trip_keeps_items_and_lists():
    items = [{"id": "EPIC-1", "title": "Ingestion", "description": "d", "requirement_ids": ["REQ-1", "REQ-2"]}]
    df = tables.to_df("epics", items)
    assert df.loc[0, "requirement_ids"] == "REQ-1, REQ-2"
    assert tables.from_df("epics", df) == items


def test_new_and_blank_rows():
    df = pd.DataFrame([
        {"id": None, "title": "New", "description": None, "requirement_ids": "REQ-3 REQ-4"},
        {"id": None, "title": None, "description": None, "requirement_ids": None},
    ])
    assert tables.from_df("epics", df) == [
        {"id": None, "title": "New", "description": "", "requirement_ids": ["REQ-3", "REQ-4"]}]


def test_optional_fields_become_none():
    df = tables.to_df("tasks", [{"id": "TASK-1", "story_id": "STORY-1", "description": "x", "owner": None,
                                 "dependency_ids": [], "system": None}])
    task = tables.from_df("tasks", df)[0]
    assert task["owner"] is None and task["system"] is None and task["dependency_ids"] == []


def test_acceptance_criteria_text_round_trip():
    text = tables.ac_to_text(AC_OK)
    assert text.splitlines()[1].startswith("[negative] Given")
    assert tables.text_to_ac(text) == AC_OK


def test_acceptance_criteria_parse_error_names_line():
    with pytest.raises(ValueError, match="Line 2"):
        tables.text_to_ac("Given a; When b; Then c\nthis is not a criterion")


def test_email_text():
    text = tables.email_to_text(RAID_EMAIL["email"])
    assert text.startswith("Subject: Kickoff recap")
    assert "- Send v3 spec (Tom Becker)" in text
    assert "Open questions" in text
