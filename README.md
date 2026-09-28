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
| M2 Pipeline: LLM client, stage prompts, DoR checker | Done |
| M3 UI: settings, projects, meeting workspace | Done |
| M4 Excel export and demo mode | Next |
| M5 Showcase README | |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your Anthropic API key
pytest                 # no API key needed; the model is faked in tests
```

Start the app:

```bash
streamlit run app/main.py
```

Then click **Load sample project**, open it, and add the sample kickoff transcript under **New meeting**.

Run all five stages on a sample transcript with the real Claude API (auto-approves each stage):

```bash
python scripts/run_sample.py --model claude-sonnet-5   # or claude-opus-5
```

## Sample data

All sample data is fictional: [samples/](samples/) has a travel and expense platform project, plus two meeting transcripts (a kickoff meeting and a follow-up that changes scope).
