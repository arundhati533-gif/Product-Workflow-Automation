"""A fake LLM that returns canned outputs, so pipeline tests are free and repeatable."""

from __future__ import annotations

import copy

from core.llm import LLMResult, Usage, compute_cost
from core.schemas import (
    DorReviewOutput,
    EpicsOutput,
    ExtractOutput,
    RaidEmailOutput,
    StoriesOutput,
    TasksOutput,
)

EXTRACT = {
    "requirements": [
        {"statement": "Ingest the daily Meridian card file by 6 a.m. Eastern.", "type": "Non-functional",
         "source_quote": "The whole thing needs to be done by six a.m. Eastern", "speaker": "Raj Patel",
         "timestamp": "02:25"},
        {"statement": "Persist only the last four digits of the card number.", "type": "Constraint",
         "source_quote": "Only the last four digits can be persisted", "speaker": "Lena Park", "timestamp": "03:41"},
        {"statement": "Match transactions to SkyLane trips within a ±2 day window.", "type": "Functional",
         "source_quote": "a window of plus or minus two days around the trip", "speaker": "Mei Chen",
         "timestamp": "04:49"},
    ],
    "decisions": [
        {"statement": "Phase one uses the SFTP file drop.", "decided_by": "Priya Nair",
         "source_quote": "Phase one uses the SFTP file drop, not the API.", "timestamp": "02:11"},
    ],
    "open_questions": [
        {"question": "Does the SkyLane API return employee ID?", "raised_by": "Mei Chen", "owner": None,
         "linked_ids": ["REQ-3"], "resolved": False},
    ],
}

EPICS = {"epics": [
    {"title": "Card file ingestion", "description": "Load and mask the daily file.", "requirement_ids": ["REQ-1", "REQ-2"]},
    {"title": "Transaction matching", "description": "Match transactions to trips.", "requirement_ids": ["REQ-3"]},
]}

AC_OK = [
    {"given": "a valid file", "when": "it lands at 4 a.m.", "then": "it is loaded by 6 a.m.", "negative": False},
    {"given": "a file with a bad trailer count", "when": "it is processed", "then": "it is rejected and alerted",
     "negative": True},
]

STORIES = {"stories": [
    {"epic_id": "EPIC-1", "as_a": "finance operations manager", "i_want": "card transactions loaded daily",
     "so_that": "travellers see them each morning", "acceptance_criteria": AC_OK, "priority": "High",
     "points": 5, "requirement_ids": ["REQ-1"]},
    {"epic_id": "EPIC-1", "as_a": "compliance analyst", "i_want": "card numbers masked on read",
     "so_that": "we stay PCI compliant", "acceptance_criteria": AC_OK[:1], "priority": "High",
     "points": 13, "requirement_ids": ["REQ-2"]},
    {"epic_id": "EPIC-2", "as_a": "traveller", "i_want": "transactions matched to my trip",
     "so_that": "I don't enter them by hand", "acceptance_criteria": AC_OK, "priority": "High",
     "points": 8, "requirement_ids": ["REQ-3"]},
]}

DOR_REVIEW = {"reviews": [
    {"story_id": "STORY-1", "clear_statement": True, "independent": True, "testable": True, "reasons": []},
    {"story_id": "STORY-2", "clear_statement": True, "independent": True, "testable": True, "reasons": []},
    {"story_id": "STORY-3", "clear_statement": True, "independent": False, "testable": True,
     "reasons": ["Depends on the SkyLane identifier question."]},
]}

TASKS = {
    "tasks": [
        {"id": "NEW-1", "story_id": "STORY-1", "description": "Build v3 file parser", "owner": "Raj Patel",
         "dependency_ids": [], "system": "Meridian Card Feed"},
        {"id": "NEW-2", "story_id": "STORY-1", "description": "Load parsed records", "owner": "Raj Patel",
         "dependency_ids": ["NEW-1"], "system": "Voyant Expense Service"},
        {"id": "NEW-3", "story_id": "STORY-2", "description": "Mask PAN on read", "owner": None,
         "dependency_ids": ["NEW-1"], "system": None},
        {"id": "NEW-4", "story_id": "STORY-3", "description": "Design matching rules", "owner": "Mei Chen",
         "dependency_ids": [], "system": "Voyant Matching Engine"},
    ],
    "missing_info": [],
}

RAID_EMAIL = {
    "raid": [
        {"type": "Risk", "description": "Meridian spec v4 in Q1 may cause rework.", "owner": "Mei Chen",
         "status": "Open", "impact": "Medium", "likelihood": "High", "mitigation": "Configurable layout.",
         "due_date": None, "linked_ids": ["EPIC-1"]},
    ],
    "email": {
        "subject": "Kickoff recap", "summary": "We agreed phase one scope.",
        "decisions": ["Phase one uses the SFTP file drop."],
        "action_items": [{"action": "Send v3 spec", "owner": "Tom Becker", "due_date": None}],
        "open_questions": ["Does SkyLane return employee ID?"],
    },
}

CANNED = {
    ExtractOutput: EXTRACT,
    EpicsOutput: EPICS,
    StoriesOutput: STORIES,
    DorReviewOutput: DOR_REVIEW,
    TasksOutput: TASKS,
    RaidEmailOutput: RAID_EMAIL,
}


class FakeLLM:
    model = "claude-sonnet-5"

    def __init__(self, overrides: dict | None = None):
        self.overrides = overrides or {}
        self.calls: list[dict] = []

    def generate(self, system, context, prompt, schema):
        self.calls.append({"system": system, "context": context, "prompt": prompt, "schema": schema})
        data = copy.deepcopy(self.overrides.get(schema, CANNED[schema]))
        usage = Usage(input_tokens=1000, output_tokens=500, cache_write_tokens=2000, cache_read_tokens=0)
        return LLMResult(schema.model_validate(data), self.model, usage, compute_cost(self.model, usage))
