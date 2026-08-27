---
name: lifecycle
description: Run the full item lifecycle unattended — plan → plan-review (with rival-plan tournament) → implement → pr-review (with fix loop) → ship — as sequential subagents on a feature branch. Ends by pushing the branch and opening a PR on the fork; merging stays with the user. Use when the user wants a roadmap item taken from plan to shipped end to end without stopping at the usual human gates.
argument-hint: [roadmap item; optional model overrides, e.g. "wildcard getters, implement=sonnet" or "judge=opus" or "model=opus"]
---

Run the full lifecycle for: **$ARGUMENTS** (no item named → the top item in
[ROADMAP.md](ROADMAP.md)).

You are the orchestrator. Each phase is one **synchronous** `Agent` call
(`run_in_background: false`) — never run phases in parallel or in the
background: each phase consumes the previous phase's report, and running
them inline is the point, so the user can watch every agent's actions in the
chat. Do the phase work only through those agents; your own job is
sequencing, passing reports along, and posting a one-line status between
phases.

## Models

Each step has a default model; `$ARGUMENTS` may override per step
(`implement=sonnet review=opus`) or all steps at once (`model=opus`). Spend on
the steps that decide things, save on the steps that execute a decision
already made:

| step | default |
|---|---|
| plan | fable |
| plan-review | fable |
| rival | fable |
| judge | fable |
| implement | opus |
| review | opus |
| fix | sonnet |
| nits | sonnet |
| ship | sonnet |

The whole plan-review phase runs on fable deliberately. Its reviewer decides a
phase by approving — an approval leaves no artifact for anyone to check — and
its judge is the only decision in this pipeline that nothing downstream
reviews. Rival and judge fire only on disagreement, so the aggregate cost is
nearer one extra agent per plan than three.

Pass the resolved model as the `Agent` call's `model` parameter.

## Rules for every phase prompt

Start every agent prompt with this preamble, verbatim:

> You are one phase of an autonomous end-to-end lifecycle run; no user is
> available. Where the skill's instructions say to stop and ask the user,
> instead make the best call yourself, record it in your report under
> "Assumptions", and continue. Report STATUS: blocked only if you genuinely
> cannot proceed. Your final report goes to the next phase's agent, not to a
> human — include every concrete detail the next phase needs (paths, branch
> names, decisions, caveats). Work only in this repository. Never commit on
> master, and never push or open a PR unless your phase instructions
> explicitly direct it. Do not modify the skills running this lifecycle —
> .claude/skills/lifecycle/, plan/, plan-review/, implement/, pr-review/,
> ship/ — that is the tooling running you, out of scope regardless of what
> you notice about it.
>
> This repository is a fork of ideoforms/AbletonOSC and is consumed by Seshat
> as a git submodule. Python here never executes in this repository: Live
> runs the copy installed in its Remote Scripts directory, loaded at startup.
> `python3 -m pytest tests_unit/` is the Live-free gate and the only one. You
> may not install the bridge into Live, restart Live, or bind the OSC reply
> port (11001); if Live is running, the read-only methods in API.md
> ("Measuring the Live API…" and "The no-probe variant") are the limit of
> what you may do to it, and only under begin/end_undo_step with everything
> restored. Documentation is part of the code: every address change carries
> its API.md rows, every divergence from upstream its SESHAT.md entry, every
> closed gap its FORK_GAPS.md deletion and inventory regeneration, every
> shipped item the removal of the source write-up its ROADMAP entry cites —
> in the same commit.

And end every prompt with:

> End your report with a fields block, one per line, omitting lines you have
> no value for:
> STATUS: complete | blocked
> BRANCH: <feature branch name, if one exists yet>
> BASE_SHA: <full SHA the branch was created from>
> PLAN_PATH: <e.g. docs/PLAN_wildcard_getters.md>
> PLAN_VERDICT: <plan-review phase only>
> JUDGE_VERDICT: <judge agent only>
> VERDICT: <code review phase only>
> DOWNSTREAM: <what Seshat must do when this lands — "pin bump only" or the change>
> PR_URL: <opened PR, ship phase only>

When a later phase needs an earlier phase's report, paste the **full report
verbatim** inside a tagged block (`<plan-report>`, `<plan-review-findings>`,
`<judge-decision>`, `<implementer-report>`, `<fix-report round="N">`,
`<review-findings>`, `<nit-triage-report>`) — never a summary; details you
drop are decisions the next agent will re-make differently.

If any `Agent` call dies or returns nothing usable, treat it as blocked —
with two exceptions at opposite ends. The code review phase **fails closed**:
a dead review agent means the branch has *not* been reviewed, so stop and
hand the branch back unreviewed rather than proceeding to ship. The plan
review phase **fails open**: code review still stands behind it, so a dead
agent there means continuing to implement with an unreviewed plan and saying
so in the final report.

Failing open means carrying on with **plan A, and only plan A on disk**. A
dead reviewer leaves nothing to clean; a dead rival or a dead judge can leave
a `docs/PLAN_*_alt.md` behind, and you delete it before Phase 3 — everything
downstream assumes exactly one active plan doc. Say in the final report which
agent died and that you deleted the rival.

Whenever you stop early, tell the user which phase stopped, why (quote the
report), and the branch/plan state so they can pick it up by hand.

## Phase 1 — Plan

Agent prompt: preamble, then —

> Read .claude/skills/plan/SKILL.md and carry out its instructions, with
> $ARGUMENTS = "<the item>". Commit nothing in this phase; just write the
> plan doc and the ROADMAP.md link edit in the working tree. Return
> PLAN_PATH and a report covering: the item chosen, key decisions, the
> Downstream verdict, open questions and how far you got resolving them, and
> what the implementer must check first.

If blocked, stop. If the planner forgot PLAN_PATH, describe it to later
phases as "the single active docs/PLAN_*.md" rather than a made-up path.

## Phase 2 — Plan review, with tournament (conditional)

One review agent always; a rival author and a judge only if the reviewer
disagrees. There is no revise loop here — the reviewer either approves or
commissions a competing plan, and the judge's decision is final.

**Review** agent prompt: preamble, `<plan-report>` block, then —

> Read .claude/skills/plan-review/SKILL.md and carry out § Review for the
> plan at <PLAN_PATH>. Apply corrections to the plan doc itself as that
> section directs, but commit nothing — the plan doc and the ROADMAP edit
> are still uncommitted in the working tree and Phase 3 commits them. State
> your verdict on a line "PLAN_VERDICT: <verdict>".

On `approve` or `approve_with_corrections`, go to Phase 3. On `rival`, run
two more agents in sequence.

**Rival** agent prompt: preamble, `<plan-review-findings>` block, then —

> Read .claude/skills/plan-review/SKILL.md and carry out § Rival. The review
> findings above are your brief; read the roadmap entry and its source
> yourself as that section directs — those are your inputs and nothing else
> is. Do not open <PLAN_PATH> until your own plan is written — that section
> says when to read it and what to do with it. Write to the `_alt.md` path
> § Rival names, never to <PLAN_PATH>. Commit nothing. Return the path you
> wrote.

**Judge** agent prompt: preamble, `<plan-review-findings>` block ("contested
claims, not facts — read them only after you have formed your own view of
both plans"), then —

> Read .claude/skills/plan-review/SKILL.md and carry out § Judge, choosing
> between <PLAN_PATH> as plan A and <rival path> as plan B. Promote the
> winner and delete the loser file exactly as that section directs, but
> commit nothing. State "JUDGE_VERDICT: <verdict>" and return PLAN_PATH for
> the surviving doc.

On `neither`, stop: report both plans — by path, both still on disk — and
the judge's reasoning to the user. That verdict is a judgment about the
roadmap item itself, which is theirs to make.

Otherwise carry the surviving PLAN_PATH into Phase 3, and confirm before you
do that only one `docs/PLAN_*.md` is active. If a rival survives the judge,
delete it yourself and note it.

## Phase 3 — Implement

Agent prompt: preamble, `<plan-report>` block ("treat its assumptions as
decisions already made"), `<plan-review-findings>` and — if a tournament
ran — `<judge-decision>` ("the plan you are given is the one that survived
this; its corrections and amendments are already in the doc"), then —

> Read .claude/skills/implement/SKILL.md and carry out its instructions for
> the plan at <PLAN_PATH>. Create the feature branch in place with
> 'git checkout -b' from wherever HEAD currently is — do not check out or
> switch to another ref first: the planner's plan doc and ROADMAP edit are
> uncommitted in the working tree and must ride along onto the new branch.
> Before you create it, record the current HEAD SHA ('git rev-parse HEAD')
> and return it as BASE_SHA — later phases diff against that exact commit
> rather than guessing the branch point. Always return both BRANCH and
> BASE_SHA, even if you end up blocked partway. When done and
> 'python3 -m pytest tests_unit/' is clean, commit on the feature branch:
> the plan doc + ROADMAP link edit as one commit, then the implementation
> with its documentation (API.md, SESHAT.md, FORK_GAPS.md, cited sources) in
> the same commit as the code it documents. Stage files individually —
> never 'git add -A' or 'git add .'. Put your per-plan-item report
> (done/deviated/blocked, assumptions carried, DOWNSTREAM) in the final
> commit message body as well as your returned report, so it survives for
> the reviewer.

If blocked, stop. If it reports complete but returns no BRANCH, stop too —
no later phase can be targeted.

## Phase 4 — Review, with fix loop (max 3 rounds)

Keep every fix round's report, oldest first; each round's reviewer gets
**all** of them — a false positive rebutted in round 1 must stay rebutted in
round 3, not resurface because only the latest fix report was passed along.

**Review** agent prompt: preamble, `<implementer-report>` block
("deviations and assumptions are recorded here — judge them, don't
rediscover them"), all `<fix-report round="N">` blocks so far ("findings
rebutted as false positives in these reports stay settled unless you have
new evidence"), then —

> Read .claude/skills/pr-review/SKILL.md and carry out its instructions,
> reviewing branch "<BRANCH>" against commit <BASE_SHA> — the exact commit
> it was branched from, so 'git diff <BASE_SHA>...<BRANCH>' is your change
> set. (No BASE_SHA recorded → derive the merge base with 'git merge-base';
> the branch point may not be master.) The plan doc is <PLAN_PATH>. Check
> out "<BRANCH>" first if HEAD is not already on it — the skill's test step
> runs against the working tree, and testing the wrong checkout would pass
> a review the branch never earned. Report findings only — change no code.
> State your verdict as exactly one of: approve, approve_with_nits, or
> needs_changes, on a line "VERDICT: <verdict>".

On `approve`, go to Ship. On `approve_with_nits`, run Phase 4b, then Ship.
On `needs_changes` after round 3, stop and report the outstanding findings.
Otherwise run a **fix** agent — preamble, `<review-findings>` block, then —

> You are addressing review findings on branch "<BRANCH>" (check it out if
> needed). The plan doc is <PLAN_PATH>. Fix every finding below that you
> agree with; for any you believe is a false positive, don't change code —
> rebut it in your report with evidence. A finding about a missing API.md
> row, SESHAT.md entry, FORK_GAPS.md deletion or cited-source deletion is
> fixed by writing it, not by arguing the code is fine without it. Run
> 'python3 -m pytest tests_unit/' until clean, then commit the fixes on
> the same branch with a message referencing the review round.

If the fix agent is blocked, stop (include the last review's findings in
your report to the user). Otherwise append its report and loop back to
review.

## Phase 4b — Nit triage (only on `approve_with_nits`)

A nit is *non-blocking*, not *worthless*. Left alone it ships as debt nobody
returns to, because the PR body records it as knowingly accepted and the
roadmap never hears about it. So nits get a decision — one cheap pass that
applies the ones worth applying and says why the rest were declined. What
this phase must never do is quietly promote nits into blockers: a reviewer
who says "non-blocking" has made a judgment, and an agent that fixes all
four regardless takes that judgment away.

One **nit** agent — preamble, `<review-findings>` block ("the nits are the
non-blocking items; the blocking findings, if any, were already fixed"),
then —

> You are triaging the non-blocking nits from a code review of branch
> "<BRANCH>" (check it out if needed). The plan doc is <PLAN_PATH>. These
> were explicitly judged non-blocking — your job is to decide each one, not
> to clear the list.
>
> Take each nit in turn and classify it:
> - **Apply** when the fix is small, local, and makes the code, its tests
>   or its documentation state the truth more precisely — a loose
>   assertion, a stale name, an API.md line that no longer matches
>   behaviour.
> - **Decline** when applying it would grow scope beyond the plan, reopen a
>   question the plan settled, change wire behaviour rather than describe
>   it, or overturn a wording call the reviewer already judged defensible.
>   Declining is a real outcome; a pass that applies everything has
>   misunderstood this phase.
> - **Already resolved** when a later phase fixed it as a side effect —
>   check before you edit, and never "fix" a line that no longer exists.
>
> Judgment calls that are genuinely the author's to make go in your report
> as a recommendation for the human PR reader, not a commit.
>
> Apply the ones you classified Apply, run 'python3 -m pytest tests_unit/'
> until clean, and commit them on the same branch with a message naming
> them as review nits. If you applied none, commit nothing and say so. Do
> not re-run the review and do not touch anything the nits did not name.
>
> Any nit you decline that is nonetheless a real problem worth doing later
> gets a self-contained ROADMAP.md entry (Goal, Why, Planner notes)
> slotted by priority — the PR body is read once at merge, the roadmap is
> the queue.
>
> Report every nit with its classification and one line of reasoning, so
> the ship phase can write applied-vs-declined into the PR body.

Nit fixes are **not** re-reviewed: they are by definition non-blocking. The
unit suite is the gate. If the nit agent dies or is blocked, do not stop the
run — carry on to Ship with the nits unapplied and say so in the final
report, exactly as if the verdict had been plain `approve`.

## Phase 5 — Ship

Agent prompt: preamble, `<implementer-report>`,
`<review-verdict verdict="...">` and — if Phase 4b ran —
`<nit-triage-report>` blocks, then —

> Read .claude/skills/ship/SKILL.md and carry out its instructions for the
> item just implemented on branch "<BRANCH>" (plan doc: <PLAN_PATH>) — the
> item was implemented and reviewed on this branch. Get today's date from
> the 'date' command for the archive banner. Commit the close-out (roadmap
> and source edits, archived plan, any doc fix step 4 found missing) on
> the same branch as its own commit.
>
> Then — this phase's explicit exception to the no-push rule — publish the
> branch and open a PR: 'git push -u origin <BRANCH>', then
> 'gh pr create --repo jpatricknola/AbletonOSC'. The --repo flag is
> mandatory: this clone is a GitHub fork and without it gh targets the
> ideoforms parent (a hook refuses the command, but do not rely on it).
> Base the PR on master, EXCEPT when this branch was cut from somewhere
> else: it was created from commit <BASE_SHA>, so if that commit is not on
> master, base the PR on the branch containing it instead — otherwise the
> PR would carry unrelated commits that were never part of this review.
>
> PR title: the item name. PR body, in order: a two-sentence summary of
> what changed on the wire; a link to the archived plan doc; the
> implementer's per-plan-item report; the review verdict and the nits; the
> DOWNSTREAM line — what Seshat must do when this merges, and that Live
> runs the old copy until reinstall and restart; assumptions carried
> through the run. The reports are given above — quote from them rather
> than reconstructing them from the diff, and list the nits verbatim. Where
> a nit triage report is given, mark every nit **applied**, **declined**
> (with its one-line reason), **already resolved**, or **left for the
> author to judge**. Ignore the repository's pull_request_template.md
> checklist — it is upstream's and refers to README tables this fork does
> not maintain. Add no attribution footer, badge, or `Co-Authored-By`
> trailer — this repository's commits and PRs carry the author's identity
> alone.
> Return the PR URL as PR_URL. If push or PR creation fails (no remote, no
> gh auth), still return STATUS: complete with the close-out done — report
> the failure in your report instead of blocking.

## Final report to the user

Branch, plan path, the plan-review verdict — and if a tournament ran, which
plan won and what decided it — the code review verdict, whether the
close-out shipped, the DOWNSTREAM line, and the PR URL. If nits were
triaged, say how many were applied and name the ones declined or left for
the author to judge. Then the two things this repository cannot do for
itself: merging stays with the user, and so does the Seshat side — bump the
submodule pin, run `mix abletonosc.install`, restart Live, and only then has
this Python ever executed. If no PR was opened: say why and point at the
branch to inspect manually.
