"""Load the fictional sample project into storage (user journey J1, step 4)."""

from __future__ import annotations

import json

from core import config
from core.storage import Storage

SAMPLE_TRANSCRIPTS = {
    "01-kickoff.vtt": ("Kickoff — Meridian card feed", "2026-01-12"),
    "02-follow-up.txt": ("Two-week follow-up", "2026-01-26"),
}


def sample_project() -> dict:
    return json.loads((config.SAMPLES_DIR / "project.json").read_text())


def sample_transcript_path(filename: str):
    return config.SAMPLES_DIR / "transcripts" / filename


def load_sample_project(storage: Storage) -> int:
    """Create the sample project with its roster and systems. Returns the project ID.

    Meetings are not created here: you add the sample transcripts through the
    normal "New meeting" flow, which is what the demo shows.
    """
    data = sample_project()
    existing = next((p for p in storage.list_projects() if p["name"] == data["name"]), None)
    if existing:
        return existing["id"]
    project_id = storage.create_project(data["name"], data["description"])
    for person in data["people"]:
        storage.add_person(project_id, person["name"], person["role"], person["team"])
    for system in data["systems"]:
        storage.add_system(project_id, system["name"], system["description"])
    return project_id
