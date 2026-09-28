"""Stable, app-assigned IDs such as REQ-1, EPIC-2, STORY-3."""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.schemas import Item

PREFIXES = {
    "requirement": "REQ",
    "decision": "DEC",
    "open_question": "Q",
    "epic": "EPIC",
    "story": "STORY",
    "task": "TASK",
    "raid": "RAID",
}


def assign_ids(items: Iterable[Item], prefix: str, taken: Iterable[str] = ()) -> None:
    """Give every item without an ID the next free '<prefix>-<n>'.

    Valid existing IDs are kept. Missing, malformed or duplicate IDs are
    replaced. IDs in `taken` (e.g. from earlier versions of this stage) are
    never reused, so a deleted item's ID is not given to a new one.
    """
    items = list(items)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    used = {i.id for i in items if i.id} | set(taken)
    next_n = max((int(m[1]) for u in used if (m := pattern.match(u))), default=0) + 1
    seen: set[str] = set()
    for item in items:
        if not item.id or not pattern.match(item.id) or item.id in seen:
            item.id = f"{prefix}-{next_n}"
            next_n += 1
        seen.add(item.id)
