"""Convert stage outputs to and from the flat rows shown in editable tables.

Pure functions (no Streamlit), so they are unit tested.
"""

from __future__ import annotations

import re

import pandas as pd

# Columns per item type, in display order. List fields are shown as comma-separated text.
COLUMNS: dict[str, list[str]] = {
    "requirements": ["id", "statement", "type", "speaker", "timestamp", "source_quote"],
    "decisions": ["id", "statement", "decided_by", "timestamp", "source_quote"],
    "open_questions": ["id", "question", "raised_by", "owner", "linked_ids", "resolved"],
    "epics": ["id", "title", "description", "requirement_ids"],
    "tasks": ["id", "story_id", "description", "owner", "dependency_ids", "system"],
    "raid": ["id", "type", "description", "owner", "status", "impact", "likelihood", "mitigation",
             "due_date", "linked_ids"],
}
LIST_FIELDS = {"linked_ids", "requirement_ids", "dependency_ids"}
OPTIONAL_TEXT = {"speaker", "timestamp", "decided_by", "raised_by", "owner", "system", "likelihood", "due_date"}


def to_df(field: str, items: list[dict]) -> pd.DataFrame:
    rows = []
    for item in items:
        row = {}
        for col in COLUMNS[field]:
            value = item.get(col)
            row[col] = ", ".join(value) if col in LIST_FIELDS else value
        rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS[field])


def from_df(field: str, df: pd.DataFrame) -> list[dict]:
    """Rows back to item dicts. Blank rows are dropped; new rows get id None."""
    items = []
    for row in df.to_dict("records"):
        item = {}
        for col in COLUMNS[field]:
            value = row.get(col)
            if _is_blank(value):
                value = None
            if col in LIST_FIELDS:
                item[col] = split_ids(value)
            elif col == "resolved":
                item[col] = bool(value)
            elif col in OPTIONAL_TEXT or col == "id":
                item[col] = str(value).strip() if value is not None else None
            else:
                item[col] = str(value).strip() if value is not None else ""
        if any(v for k, v in item.items() if k != "id"):
            items.append(item)
    return items


def split_ids(value) -> list[str]:
    if _is_blank(value):
        return []
    return [p.strip() for p in re.split(r"[,\s]+", str(value)) if p.strip()]


def _is_blank(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and not value.strip()


# --- Acceptance criteria as editable text -------------------------------------------

_AC_LINE = re.compile(r"^(?P<neg>\[negative\]\s*)?given\s+(?P<given>.+?);\s*when\s+(?P<when>.+?);\s*then\s+(?P<then>.+)$",
                      re.IGNORECASE)


def ac_to_text(criteria: list[dict]) -> str:
    """One line per criterion: '[negative] Given ...; When ...; Then ...'."""
    return "\n".join(
        f"{'[negative] ' if ac.get('negative') else ''}Given {ac['given']}; When {ac['when']}; Then {ac['then']}"
        for ac in criteria
    )


def text_to_ac(text: str) -> list[dict]:
    """Parse ac_to_text output. Raises ValueError naming the first bad line."""
    criteria = []
    for n, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        m = _AC_LINE.match(line)
        if not m:
            raise ValueError(f"Line {n} must look like 'Given …; When …; Then …': {line}")
        criteria.append({"given": m["given"].strip(), "when": m["when"].strip(),
                         "then": m["then"].strip(), "negative": bool(m["neg"])})
    return criteria


# --- Follow-up email as plain text ----------------------------------------------------

def email_to_text(email: dict) -> str:
    lines = [f"Subject: {email['subject']}", "", "Hi all,", "", email["summary"], ""]
    if email["decisions"]:
        lines += ["Decisions", *[f"- {d}" for d in email["decisions"]], ""]
    if email["action_items"]:
        lines.append("Action items")
        for a in email["action_items"]:
            extra = ", ".join(x for x in [a.get("owner") or "Owner TBC", a.get("due_date") and f"due {a['due_date']}"] if x)
            lines.append(f"- {a['action']} ({extra})")
        lines.append("")
    if email["open_questions"]:
        lines += ["Open questions", *[f"- {q}" for q in email["open_questions"]], ""]
    lines += ["Thanks,"]
    return "\n".join(lines)
