"""Definition of Ready checks (requirements §10).

Countable checks run in code so results are reliable; judgement checks come
from the model's review (DorReviewOutput). A story that fails is flagged, not
blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core import config
from core.schemas import DorReviewOutput, ExtractOutput, Story, StoriesOutput, TasksOutput

CHECKS = [
    "Clear statement",
    "Independent",
    "Small",
    "Testable",
    "Acceptance criteria complete",
    "Dependencies and owner named",
    "No open questions",
]


@dataclass
class StoryResult:
    story_id: str
    failures: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def check_story(
    story: Story,
    extract: ExtractOutput,
    review: DorReviewOutput | None = None,
    tasks: TasksOutput | None = None,
) -> StoryResult:
    result = StoryResult(story.id or "")

    # 1, 2, 4: judgement checks from the model review
    r = next((r for r in review.reviews if r.story_id == story.id), None) if review else None
    if r is None:
        result.pending += ["Clear statement", "Independent", "Testable"]
    else:
        reasons = " ".join(r.reasons)
        for ok, name in [(r.clear_statement, "Clear statement"), (r.independent, "Independent"),
                         (r.testable, "Testable")]:
            if not ok:
                result.failures.append(f"{name}: {reasons}" if reasons else name)

    # 3: small
    if story.points > config.DOR_MAX_POINTS:
        result.failures.append(f"Small: {story.points} points, consider splitting (max {config.DOR_MAX_POINTS})")

    # 5: acceptance criteria complete
    n = len(story.acceptance_criteria)
    if n < config.DOR_MIN_ACCEPTANCE_CRITERIA:
        result.failures.append(f"Acceptance criteria complete: only {n}, need at least {config.DOR_MIN_ACCEPTANCE_CRITERIA}")
    if not any(ac.negative for ac in story.acceptance_criteria):
        result.failures.append("Acceptance criteria complete: no negative or edge case")

    # 6: dependencies and owner named (only once tasks exist)
    if tasks is None:
        result.pending.append("Dependencies and owner named")
    else:
        story_tasks = [t for t in tasks.tasks if t.story_id == story.id]
        if not story_tasks:
            result.failures.append("Dependencies and owner named: no tasks")
        unowned = [t.id for t in story_tasks if not t.owner]
        if unowned:
            result.failures.append(f"Dependencies and owner named: no owner for {', '.join(unowned)}")
        unclear = {m.item_id for m in tasks.missing_info if m.field == "dependency"}
        unclear_deps = [t.id for t in story_tasks if t.id in unclear]
        if unclear_deps:
            result.failures.append(f"Dependencies and owner named: unclear dependency on {', '.join(unclear_deps)}")

    # 7: no open questions linked to the story, its epic or its requirements
    linked = {story.id, story.epic_id, *story.requirement_ids}
    open_qs = [q.id for q in extract.open_questions if not q.resolved and linked & set(q.linked_ids)]
    if open_qs:
        result.failures.append(f"No open questions: {', '.join(open_qs)} unresolved")

    return result


def check_stories(
    stories: StoriesOutput,
    extract: ExtractOutput,
    review: DorReviewOutput | None = None,
    tasks: TasksOutput | None = None,
) -> dict[str, StoryResult]:
    return {s.id: check_story(s, extract, review, tasks) for s in stories.stories}


def pass_rate(results: dict[str, StoryResult]) -> tuple[int, int]:
    """(passed, total)."""
    return sum(r.passed for r in results.values()), len(results)
