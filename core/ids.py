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


def assign_ids(items: Iterable[Item], prefix: str, taken: Iterable[str] = ()) -> dict[str, str]:
    """Give every item without an ID the next free '<prefix>-<n>'.

    Valid existing IDs are kept. Missing, malformed or duplicate IDs are
    replaced. IDs in `taken` (e.g. from earlier versions of this stage) are
    never reused, so a deleted item's ID is not given to a new one.

    Returns {old_id: new_id} for items whose non-empty ID was replaced (e.g.
    temporary "NEW-1" IDs), so references to them can be rewritten.
    """
    items = list(items)
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    used = {i.id for i in items if i.id} | set(taken)
    next_n = max((int(m[1]) for u in used if (m := pattern.match(u))), default=0) + 1
    seen: set[str] = set()
    renamed: dict[str, str] = {}
    for item in items:
        if not item.id or not pattern.match(item.id) or item.id in seen:
            new_id = f"{prefix}-{next_n}"
            next_n += 1
            if item.id and item.id not in seen:
                renamed[item.id] = new_id
            item.id = new_id
        seen.add(item.id)
    return renamed
