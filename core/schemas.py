"""Pydantic schemas for each pipeline stage's output.

`id` is optional on every item: the model leaves it empty for new items and
keeps it for items passed back on regenerate. The app fills in missing IDs
(see core/ids.py), so IDs stay stable across edits and regenerations.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Priority = Literal["High", "Medium", "Low"]
Level = Literal["High", "Medium", "Low"]
Points = Literal[1, 2, 3, 5, 8, 13]


class Item(BaseModel):
    id: str | None = Field(None, description="Leave empty for new items; keep unchanged for existing ones.")


# --- Stage 1: Extract ------------------------------------------------------------

class Requirement(Item):
    statement: str
    type: Literal["Functional", "Non-functional", "Constraint"]
    source_quote: str = Field(description="Verbatim quote from the transcript supporting this item.")
    speaker: str | None = None
    timestamp: str | None = None


class Decision(Item):
    statement: str
    decided_by: str | None = None
    source_quote: str
    timestamp: str | None = None


class OpenQuestion(Item):
    question: str
    raised_by: str | None = None
    owner: str | None = None
    linked_ids: list[str] = Field(default_factory=list)
    resolved: bool = False


class ExtractOutput(BaseModel):
    requirements: list[Requirement]
    decisions: list[Decision]
    open_questions: list[OpenQuestion]


# --- Stage 2: Epics ------------------------------------------------------------

class Epic(Item):
    title: str
    description: str
    requirement_ids: list[str]


class EpicsOutput(BaseModel):
    epics: list[Epic]


# --- Stage 3: Stories ------------------------------------------------------------

class AcceptanceCriterion(BaseModel):
    given: str
    when: str
    then: str
    negative: bool = Field(False, description="True for a negative or edge-case scenario.")


class Story(Item):
    epic_id: str
    as_a: str
    i_want: str
    so_that: str
    acceptance_criteria: list[AcceptanceCriterion]
    priority: Priority
    points: Points
    requirement_ids: list[str] = Field(default_factory=list)

    @property
    def statement(self) -> str:
        return f"As a {self.as_a}, I want {self.i_want}, so that {self.so_that}."


class StoriesOutput(BaseModel):
    stories: list[Story]


class StoryReview(BaseModel):
    story_id: str
    clear_statement: bool
    independent: bool
    testable: bool
    reasons: list[str] = Field(default_factory=list, description="One sentence per failed check.")


class DorReviewOutput(BaseModel):
    reviews: list[StoryReview]


# --- Stage 4: Tasks ------------------------------------------------------------

class Task(Item):
    story_id: str
    description: str
    owner: str | None = Field(None, description="Only if stated in the transcript or clear from the roster; else null.")
    dependency_ids: list[str] = Field(default_factory=list)
    system: str | None = None


class MissingInfo(BaseModel):
    item_id: str
    field: Literal["owner", "dependency"]
    question: str


class TasksOutput(BaseModel):
    tasks: list[Task]
    missing_info: list[MissingInfo]


# --- Stage 5: RAID + email ---------------------------------------------------------

class RaidItem(Item):
    type: Literal["Risk", "Assumption", "Issue", "Dependency"]
    description: str
    owner: str | None = None
    status: Literal["Open", "In progress", "Closed"] = "Open"
    impact: Level
    likelihood: Level | None = Field(None, description="For risks; null otherwise.")
    mitigation: str
    due_date: str | None = None
    linked_ids: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    action: str
    owner: str | None = None
    due_date: str | None = None


class FollowUpEmail(BaseModel):
    subject: str
    summary: str
    decisions: list[str]
    action_items: list[ActionItem]
    open_questions: list[str]


class RaidEmailOutput(BaseModel):
    raid: list[RaidItem]
    email: FollowUpEmail


STAGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "extract": ExtractOutput,
    "epics": EpicsOutput,
    "stories": StoriesOutput,
    "tasks": TasksOutput,
    "raid_email": RaidEmailOutput,
}
