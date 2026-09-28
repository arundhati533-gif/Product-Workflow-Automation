# Meeting-to-Backlog Assistant

A local app that turns a stakeholder meeting transcript into a delivery-ready backlog (epics, stories with acceptance criteria, tasks, dependencies), a RAID log and a follow-up email. You refine the output stage by stage, and it exports to Excel.

> Work in progress. A full case-study README comes in milestone M5.

## Docs

- [Requirements](docs/requirements.md)
- [User journey](docs/user-journey.md)
- [Technical design](docs/technical-design.md)

## Status

| Milestone | Status |
|---|---|
| M1 Foundation: parsers, schemas, storage, sample data, tests | Done |
| M2 Pipeline: LLM client, stage prompts, DoR checker | Next |
| M3 UI | |
| M4 Excel export and demo mode | |
| M5 Showcase README | |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your Anthropic API key
pytest
```

## Sample data

All sample data is fictional: [samples/](samples/) has a travel and expense platform project, plus two meeting transcripts (a kickoff meeting and a follow-up that changes scope).
