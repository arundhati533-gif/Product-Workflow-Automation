# Requirements — Meeting-to-Backlog Assistant

Status: Draft for confirmation · Owner: Product Manager (sole user)

## 1. Problem

Turning stakeholder meeting transcripts into a delivery-ready backlog is manual and fragmented: transcripts are re-read several times, requirements are synthesized by hand, and epics, stories, acceptance criteria, dependencies and owners are written from scratch. Current effort: **3–5 hours/week**.

## 2. Goals and success metrics

| Goal | Metric | Baseline | Target |
|---|---|---|---|
| Save time | Hours from meeting to finished backlog | 3–5 hrs/week | < 2 hrs/week |
| Better story quality | % of stories meeting Definition of Ready on first pass | Measure in pilot | +30 pts vs baseline |

## 3. Constraints

- **No real data sources.** No Teams, Jira or company system integration. Only fictional or sanitized transcripts go into the public repo.
- **Local web app** (Streamlit, Python), single user.
- **LLM:** Claude API. Model selectable in settings (Opus 5 for quality, Sonnet 5 for cost). Show the cost of each run.
- **Costs:** Only Claude API usage (pay per use, prepaid credits at console.anthropic.com). All other components are free and open source.
- **Output:** One Excel workbook with a tab per output, linked by IDs.

## 4. Inputs

- Transcript as pasted text, `.txt`, `.docx`, or `.vtt` (Teams format, with speakers and timestamps).
- Project context entered once per project: team roster (names, roles, teams) and systems.
- Your feedback and clarifications at each stage.

## 5. Data model

**Project → Meetings → Backlog** (stored locally in SQLite). Each new meeting belongs to a project and is compared against that project's current backlog.

## 6. Scope

### MVP (release 1)

**F1. Core backlog breakdown, refined stage by stage in the app**

1. Requirements, decisions and open questions extracted from the transcript.
2. Epics.
3. Stories:
   - "As a / I want / so that" statement
   - Given/When/Then acceptance criteria
   - Priority: High/Med/Low
   - Estimate: Fibonacci points (1, 2, 3, 5, 8, 13)
4. Tasks with owners and dependencies.

At each stage you can edit the output directly or give feedback, then regenerate or move to the next stage. Owners and dependencies come from the transcript. Where one can't be found, the app asks you for it instead of guessing.

**F2. RAID log.** Each item has: type (Risk, Assumption, Issue, Dependency), description, owner, status, impact (H/M/L), likelihood (H/M/L), mitigation or next step with due date, and the epic or story it affects.

**F3. Follow-up email.** One concise, professional email to all attendees with: summary, decisions, action items (owner and due date), and open questions.

**F4. Excel export,** available at any stage.

### Release 2

- **F5. Change detection.** Compare a new meeting against the project's saved backlog. Flag new, changed and dropped scope, and let you accept or reject each change.
- **F6. Release notes and stakeholder update.** You select completed stories in the app, and the app generates both documents.
- **F7. Test cases.** Generated from each story's Given/When/Then acceptance criteria.

## 7. Excel workbook structure

| Tab | Key columns |
|---|---|
| Summary | Project, meeting, date, model, cost, counts |
| Requirements | REQ-ID, statement, type, source speaker/timestamp, status |
| Epics | EPIC-ID, title, description, linked REQ-IDs |
| Stories | STORY-ID, EPIC-ID, story statement, acceptance criteria, priority, points, status |
| Tasks | TASK-ID, STORY-ID, description, owner, dependency IDs |
| RAID | RAID-ID, type, description, owner, status, impact, likelihood, mitigation, due date, linked ID |
| Open Questions | Q-ID, question, raised by, owner, linked ID |
| Follow-up Email | Email text |
| *(Release 2)* Changes, Test Cases, Release Notes | |

## 8. Non-functional

- Every generated item keeps a reference to the transcript text it came from. Nothing is invented without a flag.
- Your Anthropic API key is stored in a local `.env` file and never committed.
- A sample project with a fictional transcript ships in the repo for the demo.

## 9. Showcase (GitHub)

- **Audience:** hiring managers for product manager roles.
- **README as a case study:** problem, options considered, decisions, workflow, metrics, demo GIF, and a sample Excel output.

## 10. Open items

- Definition of Ready checklist (for the quality metric).
- Fictional domain and sample transcript for the demo.
