<task>
Stage 4 of 5: break each approved story into engineering tasks with owners and dependencies.

- 2 to 6 tasks per story, each a concrete unit of work a single person can complete in a few days (design, build, integrate, test, configure).
- owner: set only when the transcript assigns the work to someone, or the roster makes the owner unambiguous (for example, the only person in that role). Otherwise leave owner empty. Never guess.
- dependency_ids: IDs of other tasks in this output that must finish first (see below for new tasks).
- system: the roster system the task changes or depends on, if any.
- missing_info: for every task with no owner, and for every dependency on something outside the team that the transcript leaves unclear (e.g. a partner deliverable with no date), add a short question the product manager can answer, with item_id set to the task's ID.

Dependencies between new tasks: because new tasks have no IDs yet, give each new task a temporary id of the form "NEW-1", "NEW-2", ... and use those in dependency_ids and missing_info. The app replaces them with permanent IDs.
</task>
