"""Demo mode: replay recorded stage outputs for the sample transcripts, no API key needed.

Recordings live in samples/demo/<transcript-stem>/<stage>.json (plus
dor_review.json and meta.json). They are made with
`python scripts/run_sample.py --record`.

Recorded IDs are mapped onto the IDs actually in use, so a replay links up
correctly with earlier stages even if the project already has other meetings.
"""

from __future__ import annotations

import copy
import json
import re
from functools import cached_property
from pathlib import Path

from core import config
from core.llm import LLMError, LLMResult, Usage
from core.parsing import parse_transcript
from core.pipeline import REF_FIELDS, STAGE_ITEMS
from core.schemas import STAGE_SCHEMAS, DorReviewOutput

DEMO_DIR = config.SAMPLES_DIR / "demo"
DEMO_MODEL = "demo"
FIXTURE_FILES = [*config.STAGES, "dor_review"]

_SCHEMA_TO_NAME = {schema: stage for stage, schema in STAGE_SCHEMAS.items()} | {DorReviewOutput: "dor_review"}


def _block(prompt: str, tag: str, skip_first_line: bool = False) -> object | None:
    m = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.DOTALL)
    if not m:
        return None
    body = m.group(1).split("\n", 1)[1] if skip_first_line else m.group(1)
    return json.loads(body)


def _remap(obj, mapping: dict[str, str]):
    """Replace IDs in 'id' and reference fields, recursively."""
    if isinstance(obj, list):
        return [_remap(v, mapping) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for key, value in obj.items():
        if key in REF_FIELDS | {"id"}:
            if isinstance(value, list):
                value = [mapping.get(v, v) for v in value]
            elif isinstance(value, str):
                value = mapping.get(value, value)
        else:
            value = _remap(value, mapping)
        out[key] = value
    return out


class Recording:
    def __init__(self, path: Path):
        self.path = path
        self.meta = json.loads((path / "meta.json").read_text())
        self.outputs = {name: json.loads((path / f"{name}.json").read_text()) for name in FIXTURE_FILES}

    @cached_property
    def transcript_text(self) -> str:
        source = config.SAMPLES_DIR / "transcripts" / self.meta["transcript"]
        return parse_transcript(filename=source.name, data=source.read_bytes()).to_text()

    @property
    def placeholder(self) -> bool:
        return bool(self.meta.get("placeholder"))


def load_recordings(demo_dir: Path = DEMO_DIR) -> list[Recording]:
    if not demo_dir.exists():
        return []
    return [Recording(p) for p in sorted(demo_dir.iterdir()) if (p / "meta.json").exists()]


class ReplayLLM:
    """Implements the same interface as ClaudeLLM, returning recorded outputs at no cost."""

    model = DEMO_MODEL

    def __init__(self, demo_dir: Path = DEMO_DIR):
        self.recordings = load_recordings(demo_dir)

    def generate(self, system: str, context: str, prompt: str, schema) -> LLMResult:
        recording = next((r for r in self.recordings if r.transcript_text in context), None)
        if recording is None:
            raise LLMError("Demo mode only works with the sample transcripts. Add an API key in Settings "
                           "to process your own.")
        name = _SCHEMA_TO_NAME[schema]
        data = copy.deepcopy(recording.outputs[name])
        data = _remap(data, self._id_mapping(recording, name, prompt))
        data.pop("dor_review", None)
        return LLMResult(schema.model_validate(data), DEMO_MODEL, Usage(), 0.0)

    @staticmethod
    def _id_mapping(recording: Recording, name: str, prompt: str) -> dict[str, str]:
        mapping: dict[str, str] = {}

        def pair(recorded: list[dict], actual: list[dict]) -> None:
            for r, a in zip(recorded, actual):
                if r.get("id") and a.get("id"):
                    mapping[r["id"]] = a["id"]

        if name == "dor_review":
            actual = _block(prompt, "stories") or []
            pair(recording.outputs["stories"]["stories"], actual)
            return mapping

        # Earlier stages: map recorded IDs to the approved ones, by position.
        approved = _block(prompt, "approved_outputs") or {}
        for stage, output in approved.items():
            for field, _ in STAGE_ITEMS[stage]:
                pair(recording.outputs[stage].get(field, []), output.get(field, []))

        # This stage: reuse the IDs of the version being revised, else temporary
        # IDs that the pipeline replaces with free ones.
        current = _block(prompt, "current_version", skip_first_line=True) or {}
        for field, _ in STAGE_ITEMS[name]:
            recorded = recording.outputs[name].get(field, [])
            for r in recorded:
                mapping[r["id"]] = f"TMP-{r['id']}"
            pair(recorded, current.get(field, []))
        return mapping
