"""Stage orchestration: run, edit, approve and track staleness of the five stages.

The pipeline has no Streamlit imports, so it can be tested directly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import get_args

from pydantic import BaseModel

from core import config, dor
from core.ids import PREFIXES, assign_ids
from core.llm import LLMResult, StructuredLLM, Usage
from core.schemas import (
    STAGE_SCHEMAS,
    DorReviewOutput,
    ExtractOutput,
    MissingInfo,
    StoriesOutput,
    TasksOutput,
)
from core.storage import Storage

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Which list in each stage's output holds items, and their ID prefix.
STAGE_ITEMS: dict[str, list[tuple[str, str]]] = {
    "extract": [("requirements", PREFIXES["requirement"]), ("decisions", PREFIXES["decision"]),
                ("open_questions", PREFIXES["open_question"])],
    "epics": [("epics", PREFIXES["epic"])],
    "stories": [("stories", PREFIXES["story"])],
    "tasks": [("tasks", PREFIXES["task"])],
    "raid_email": [("raid", PREFIXES["raid"])],
}

# Items copied to the project backlog when a stage is approved.
BACKLOG_TYPES = {"epics": ("epics", "epic"), "stories": ("stories", "story"),
                 "tasks": ("tasks", "task"), "raid_email": ("raid", "raid")}


class StageNotReady(RuntimeError):
    """An earlier stage must be approved (and current) first."""


@cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text().strip()


def _dump(obj) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False)


@dataclass
class StageState:
    stage: str
    status: str  # not_started | draft | approved | stale | blocked
    run: dict | None = None


class Pipeline:
    def __init__(self, storage: Storage, llm: StructuredLLM | None = None):
        self.storage = storage
        self.llm = llm

    # --- Context and hashing ---------------------------------------------------

    def context(self, meeting_id: int) -> str:
        """Project, roster, systems and transcript: the cached prefix for every stage."""
        meeting = self._meeting(meeting_id)
        project = self.storage.get_project(meeting["project_id"])
        people = self.storage.list_people(project["id"])
        systems = self.storage.list_systems(project["id"])
        roster = "\n".join(f"- {p['name']} — {p['role']}, {p['team']}" for p in people) or "(none)"
        system_lines = "\n".join(f"- {s['name']}: {s['description']}" for s in systems) or "(none)"
        return (
            f"<project>\nName: {project['name']}\n{project['description']}\n</project>\n\n"
            f"<roster>\n{roster}\n</roster>\n\n"
            f"<systems>\n{system_lines}\n</systems>\n\n"
            f"<meeting title=\"{meeting['title']}\" date=\"{meeting['date']}\">\n"
            f"{meeting['transcript_text']}\n</meeting>"
        )

    def input_hash(self, meeting_id: int, stage: str) -> str:
        prior = self._prior_outputs(meeting_id, stage, require=False)
        payload = self.context(meeting_id) + _dump(prior)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # --- State ---------------------------------------------------------------

    def status(self, meeting_id: int) -> dict[str, StageState]:
        """Status of every stage. A stage is stale when its inputs changed since it ran."""
        states: dict[str, StageState] = {}
        upstream_ok = True
        for stage in config.STAGES:
            run = self.storage.latest_stage_run(meeting_id, stage)
            if run is None:
                status = "not_started" if upstream_ok else "blocked"
            elif not upstream_ok or run["input_hash"] != self.input_hash(meeting_id, stage):
                status = "stale"
            else:
                status = run["status"]
            states[stage] = StageState(stage, status, run)
            upstream_ok = upstream_ok and status == "approved"
        return states

    def approved_output(self, meeting_id: int, stage: str) -> dict | None:
        run = self.storage.latest_stage_run(meeting_id, stage)
        return run["output"] if run and run["status"] == "approved" else None

    # --- Actions -------------------------------------------------------------

    def run_stage(
        self,
        meeting_id: int,
        stage: str,
        feedback: str = "",
        item_feedback: dict[str, str] | None = None,
        locked_ids: set[str] | frozenset[str] = frozenset(),
    ) -> dict:
        """Generate (or regenerate) a stage. Returns the saved draft run."""
        if self.llm is None:
            raise RuntimeError("No LLM configured.")
        self._require_upstream(meeting_id, stage)
        prior = self._prior_outputs(meeting_id, stage)
        current = self.storage.latest_stage_run(meeting_id, stage)
        current_output = current["output"] if current else None

        prompt = self._build_prompt(stage, prior, current_output, feedback, item_feedback or {}, locked_ids)
        result = self.llm.generate(load_prompt("system"), self.context(meeting_id), prompt, STAGE_SCHEMAS[stage])
        output = self._post_process(meeting_id, stage, result.output, current_output, locked_ids)
        results = [result]

        if stage == "stories":
            review = self._dor_review(meeting_id, output)
            results.append(review)
            output["dor_review"] = review.output.model_dump()

        run_id = self._save(meeting_id, stage, output, results)
        for item_id, text in (item_feedback or {}).items():
            self.storage.add_feedback(run_id, text, item_id=item_id)
        if feedback.strip():
            self.storage.add_feedback(run_id, feedback)
        self.storage.set_meeting_status(meeting_id, f"{stage}:draft")
        return self.storage.latest_stage_run(meeting_id, stage)

    def save_edit(self, meeting_id: int, stage: str, output: dict) -> dict:
        """Save the user's direct edits as a new draft (no model call)."""
        self._require_upstream(meeting_id, stage)
        current = self.storage.latest_stage_run(meeting_id, stage)
        parsed = STAGE_SCHEMAS[stage].model_validate(output)
        new_output = self._post_process(meeting_id, stage, parsed, current["output"] if current else None)
        if stage == "stories" and current and "dor_review" in current["output"]:
            new_output["dor_review"] = self._carry_over_review(current["output"], new_output)
        self._save(meeting_id, stage, new_output, [])
        self.storage.set_meeting_status(meeting_id, f"{stage}:draft")
        return self.storage.latest_stage_run(meeting_id, stage)

    def answer_missing_info(self, meeting_id: int, owners: dict[str, str]) -> dict:
        """Fill in task owners the model could not find (user journey J2, step 5)."""
        run = self.storage.latest_stage_run(meeting_id, "tasks")
        if run is None:
            raise StageNotReady("Tasks have not been generated yet.")
        output = json.loads(json.dumps(run["output"]))
        for task in output["tasks"]:
            if task["id"] in owners and owners[task["id"]].strip():
                task["owner"] = owners[task["id"]].strip()
        return self.save_edit(meeting_id, "tasks", output)

    def approve(self, meeting_id: int, stage: str) -> dict:
        state = self.status(meeting_id)[stage]
        if state.run is None:
            raise StageNotReady(f"{config.STAGE_LABELS[stage]} has not been generated yet.")
        if state.status == "stale":
            raise StageNotReady(f"{config.STAGE_LABELS[stage]} is out of date. Regenerate it first.")
        self.storage.set_stage_status(state.run["id"], "approved")
        self._update_backlog(meeting_id, stage, state.run["output"])
        self.storage.set_meeting_status(meeting_id, f"{stage}:approved")
        return self.storage.latest_stage_run(meeting_id, stage)

    # --- Checks ------------------------------------------------------------

    def dor_results(self, meeting_id: int) -> dict[str, dor.StoryResult]:
        stories_run = self.storage.latest_stage_run(meeting_id, "stories")
        extract = self.approved_output(meeting_id, "extract")
        if not stories_run or extract is None:
            return {}
        stories = StoriesOutput.model_validate(stories_run["output"])
        review = stories_run["output"].get("dor_review")
        tasks_run = self.storage.latest_stage_run(meeting_id, "tasks")
        return dor.check_stories(
            stories,
            ExtractOutput.model_validate(extract),
            DorReviewOutput.model_validate(review) if review else None,
            TasksOutput.model_validate(tasks_run["output"]) if tasks_run else None,
        )

    def unverified_quotes(self, meeting_id: int) -> list[str]:
        """IDs of extracted items whose source quote is not found in the transcript."""
        run = self.storage.latest_stage_run(meeting_id, "extract")
        if not run:
            return []
        transcript = _normalise(self._meeting(meeting_id)["transcript_text"])
        out = run["output"]
        return [
            item["id"]
            for item in out["requirements"] + out["decisions"]
            if _normalise(item["source_quote"]) not in transcript
        ]

    def link_warnings(self, meeting_id: int, stage: str) -> list[str]:
        """References to unknown IDs, and requirements not covered downstream."""
        run = self.storage.latest_stage_run(meeting_id, stage)
        if not run:
            return []
        prior = self._prior_outputs(meeting_id, stage, require=False)
        out = run["output"]
        warnings = []
        req_ids = {r["id"] for r in prior.get("extract", {}).get("requirements", [])}
        epic_ids = {e["id"] for e in prior.get("epics", {}).get("epics", [])}
        story_ids = {s["id"] for s in prior.get("stories", {}).get("stories", [])}
        if stage == "epics":
            used = {rid for e in out["epics"] for rid in e["requirement_ids"]}
            warnings += [f"{e['id']} references unknown requirement {rid}"
                         for e in out["epics"] for rid in e["requirement_ids"] if rid not in req_ids]
            warnings += [f"{rid} is not in any epic" for rid in sorted(req_ids - used)]
        elif stage == "stories":
            warnings += [f"{s['id']} references unknown epic {s['epic_id']}"
                         for s in out["stories"] if s["epic_id"] not in epic_ids]
            covered = {rid for s in out["stories"] for rid in s["requirement_ids"]}
            warnings += [f"{rid} is not covered by any story" for rid in sorted(req_ids - covered)]
        elif stage == "tasks":
            warnings += [f"{t['id']} references unknown story {t['story_id']}"
                         for t in out["tasks"] if t["story_id"] not in story_ids]
            with_tasks = {t["story_id"] for t in out["tasks"]}
            warnings += [f"{sid} has no tasks" for sid in sorted(story_ids - with_tasks)]
        return warnings

    # --- Internals -------------------------------------------------------------

    def _meeting(self, meeting_id: int) -> dict:
        meeting = self.storage.get_meeting(meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found.")
        return meeting

    def _prior_stages(self, stage: str) -> list[str]:
        return config.STAGES[: config.STAGES.index(stage)]

    def _prior_outputs(self, meeting_id: int, stage: str, require: bool = True) -> dict[str, dict]:
        prior = {}
        for s in self._prior_stages(stage):
            out = self.approved_output(meeting_id, s)
            if out is None:
                if require:
                    raise StageNotReady(f"Approve {config.STAGE_LABELS[s]} first.")
                continue
            prior[s] = {k: v for k, v in out.items() if k != "dor_review"}
        return prior

    def _require_upstream(self, meeting_id: int, stage: str) -> None:
        states = self.status(meeting_id)
        for s in self._prior_stages(stage):
            if states[s].status != "approved":
                raise StageNotReady(f"Approve {config.STAGE_LABELS[s]} first.")

    def _build_prompt(self, stage, prior, current_output, feedback, item_feedback, locked_ids) -> str:
        parts = []
        if prior:
            parts.append(f"<approved_outputs>\n{_dump(prior)}\n</approved_outputs>")
        if current_output:
            current = {k: v for k, v in current_output.items() if k != "dor_review"}
            parts.append(
                "<current_version>\nThe product manager has reviewed this version. Revise it rather than "
                f"starting over: keep IDs and anything the feedback does not ask to change.\n{_dump(current)}\n"
                "</current_version>"
            )
        if locked_ids:
            parts.append(
                "<locked_items>\nThe product manager edited these items. Return them exactly as they are in "
                f"the current version: {', '.join(sorted(locked_ids))}\n</locked_items>"
            )
        if feedback.strip() or item_feedback:
            lines = [feedback.strip()] if feedback.strip() else []
            lines += [f"{item_id}: {text}" for item_id, text in item_feedback.items()]
            parts.append("<feedback>\n" + "\n".join(lines) + "\n</feedback>")
        parts.append(load_prompt(stage))
        return "\n\n".join(parts)

    def _post_process(self, meeting_id: int, stage: str, output: BaseModel, current_output: dict | None,
                      locked_ids=frozenset()) -> dict:
        project_id = self._meeting(meeting_id)["project_id"]
        renamed: dict[str, str] = {}
        for field_name, prefix in STAGE_ITEMS[stage]:
            items = getattr(output, field_name)
            if current_output and locked_ids:
                item_cls = get_args(type(output).model_fields[field_name].annotation)[0]
                items = _enforce_locks(items, current_output.get(field_name, []), locked_ids, item_cls)
                setattr(output, field_name, items)
            renamed |= assign_ids(items, prefix, taken=self._taken_ids(project_id, stage, field_name))

        if stage == "tasks":
            _rewrite_task_refs(output, renamed)
            _ensure_owner_questions(output)
        return output.model_dump()

    def _taken_ids(self, project_id: int, stage: str, field_name: str) -> set[str]:
        """IDs used by any version of this stage in any meeting of the project."""
        taken = set()
        for run in self.storage.stage_runs_for_project(project_id, stage):
            taken |= {i["id"] for i in run["output"].get(field_name, []) if i.get("id")}
        return taken

    def _dor_review(self, meeting_id: int, stories_output: dict) -> LLMResult:
        stories = [
            {"id": s["id"], "statement": f"As a {s['as_a']}, I want {s['i_want']}, so that {s['so_that']}.",
             "acceptance_criteria": s["acceptance_criteria"], "epic_id": s["epic_id"]}
            for s in stories_output["stories"]
        ]
        prompt = f"<stories>\n{_dump(stories)}\n</stories>\n\n{load_prompt('dor_review')}"
        return self.llm.generate(load_prompt("system"), self.context(meeting_id), prompt, DorReviewOutput)

    @staticmethod
    def _carry_over_review(old_output: dict, new_output: dict) -> dict:
        """Keep the model's DoR review only for stories the user did not change."""
        old = {s["id"]: s for s in old_output["stories"]}
        unchanged = {s["id"] for s in new_output["stories"] if old.get(s["id"]) == s}
        reviews = old_output["dor_review"]["reviews"]
        return {"reviews": [r for r in reviews if r["story_id"] in unchanged]}

    def _save(self, meeting_id: int, stage: str, output: dict, results: list[LLMResult]) -> int:
        usage = sum((r.usage for r in results), Usage())
        return self.storage.save_stage_run(
            meeting_id, stage, output, self.input_hash(meeting_id, stage),
            model=results[0].model if results else None,
            input_tokens=usage.input_tokens + usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            cached_tokens=usage.cache_read_tokens,
            cost_usd=round(sum(r.cost_usd for r in results), 4),
        )

    def _update_backlog(self, meeting_id: int, stage: str, output: dict) -> None:
        if stage not in BACKLOG_TYPES:
            return
        field_name, type_ = BACKLOG_TYPES[stage]
        project_id = self._meeting(meeting_id)["project_id"]
        for item in output[field_name]:
            self.storage.upsert_backlog_item(project_id, meeting_id, type_, item["id"], item)


# --- Helpers -------------------------------------------------------------------

def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split())


def _enforce_locks(items: list, current_items: list[dict], locked_ids, item_cls: type[BaseModel]) -> list:
    """Replace or restore locked items with the user's version."""
    locked = {i["id"]: i for i in current_items if i.get("id") in locked_ids}
    if not locked:
        return items
    out = [item_cls.model_validate(locked[i.id]) if i.id in locked else i for i in items]
    returned = {i.id for i in out}
    out += [item_cls.model_validate(v) for k, v in locked.items() if k not in returned]
    return out


def _rewrite_task_refs(output: TasksOutput, renamed: dict[str, str]) -> None:
    if not renamed:
        return
    for task in output.tasks:
        task.dependency_ids = [renamed.get(d, d) for d in task.dependency_ids]
    for m in output.missing_info:
        m.item_id = renamed.get(m.item_id, m.item_id)


def _ensure_owner_questions(output: TasksOutput) -> None:
    """Every task without an owner has an owner question; answered ones are dropped."""
    owned = {t.id for t in output.tasks if t.owner}
    output.missing_info = [m for m in output.missing_info if not (m.field == "owner" and m.item_id in owned)]
    asked = {m.item_id for m in output.missing_info if m.field == "owner"}
    for t in output.tasks:
        if not t.owner and t.id not in asked:
            output.missing_info.append(MissingInfo(item_id=t.id, field="owner", question=f"Who owns '{t.description}'?"))
