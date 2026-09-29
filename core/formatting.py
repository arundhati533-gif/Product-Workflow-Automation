"""Plain-text rendering shared by the UI and the Excel export."""


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
