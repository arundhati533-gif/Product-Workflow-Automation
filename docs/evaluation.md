# Evaluation — Is this worth building?

This is the evaluation done before any design work. It covers the value, the risks, the adjacent use cases and the build-vs-buy options.

## Problem

An integration product manager turns stakeholder meetings into a backlog by hand:

- Re-reading call transcripts to pull out requirements.
- Deciding how to split them into epics, stories and tasks.
- Writing acceptance criteria and working out dependencies and owners.

The work is fragmented and repetitive. Measured effort: **3–5 hours per week**.

## Value by step

| Step | Manual effort | How much a tool can remove |
|---|---|---|
| Re-reading transcripts to extract requirements | High | High: extracting decisions, open questions and owners is a strong fit for an LLM |
| Grouping requirements into epics | Medium | Medium: the tool drafts; the product manager decides the split |
| Writing stories and acceptance criteria | High, repetitive | High: follows templates |
| Mapping dependencies and owners | Medium | Low to medium: needs knowledge that isn't in the transcript |
| Entering items into Jira | Low but tedious | High, if the tool connects to it |

## Risks

1. **Data governance.** Transcripts from a regulated company can't go to unapproved tools. This project uses only fictional data and connects to no company systems.
2. **Wrong output.** An invented requirement is worse than a missing one. Every extracted item must cite the transcript, and owners are never guessed.
3. **Existing tools.** Copilot in Teams, Atlassian Rovo and ChatPRD already produce drafts in one pass. What sets this project apart is the **stage-by-stage review loop** and the **quality check** on each story.

## Options

| | A. Copilot prompt chain | B. Copilot Studio agent | C. Custom app (this repo) |
|---|---|---|---|
| Effort | 1–2 days | 1–3 weeks plus IT approval | Weeks |
| Fit for one user at work | Best | Good once proven | Hard to justify on time saved alone |
| Control over workflow and quality checks | Low | Medium | Full |

**Decision:** option A for day-to-day work, inside the approved tooling. **Option C, this repo,** is a portfolio project. It is used to design the whole workflow end to end, including checks that prompt chains can't enforce: verifying quotes, locking edited items, and code-based Definition of Ready checks. It uses no company data.

## Other use cases considered

The same approach (extract from a transcript, structure the result, have a person refine it) also covers:

| Use case | Status |
|---|---|
| RAID log from each meeting | In MVP |
| Follow-up email with action items and owners | In MVP |
| Change detection: a new meeting compared with the existing backlog | Release 2 |
| Release notes and stakeholder updates from completed stories | Release 2 |
| Test cases from acceptance criteria | Release 2 |
| Decision and open-question tracking across meetings, traceability, onboarding Q&A | Not planned |

## Success metrics

| Goal | Metric | Baseline | Target |
|---|---|---|---|
| Save time | Hours from meeting to finished backlog | 3–5 hrs/week | < 2 hrs/week |
| Better story quality | Share of stories passing the Definition of Ready on first pass | To be measured | +30 points |
