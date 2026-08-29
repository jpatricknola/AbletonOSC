---
name: pr-review
description: Review a PR or branch against its implementation plan — plan conformance, correctness of the Python that runs inside Live, wire-contract fidelity to API.md, Live-free test coverage, documentation obligations, and downstream (Seshat) ripple. Use when the user asks to review a PR, a branch, or the current changes before merging.
argument-hint: [PR number or branch; defaults to current branch vs master]
---

Review this change: **$ARGUMENTS** (no argument → current branch against
`master`).

You are reviewing, not fixing. Report findings; only edit code if the user
asks afterwards. Read the *code*, not just the diff — a hunk that looks fine
can still be wrong in context, and the worst review misses are things that
are *absent* from the diff. This code runs inside Live's Python, cannot be
unit-tested against real objects here, and a mistake in it fails silently
over UDP — review accordingly.

1. **Establish the change set.** For a PR number, `gh pr view` and
   `gh pr diff`; for a branch, `git diff <base>...<branch>` plus `git log`
   for the commit story. Read every changed file in full, not just the hunks.

2. **Find the implementation plan.** Look, in order: a `docs/PLAN_*.md`
   matching the item, the [ROADMAP.md](ROADMAP.md) entry (and any source
   write-up it cites), the PR description, the commit messages. Read it before reading any code. If
   no plan exists anywhere, say so and review against the intent you can
   infer — but flag that intent is inferred, not stated.

3. **Judge plan conformance.** Three failure modes, check for each:
   - **Incomplete** — plan items with no corresponding code. List each one.
   - **Deviation** — code that does something the plan didn't say. Each
     deserves a sentence: justified improvement, or scope drift?
   - **Unplanned extras** — changes unrelated to the plan riding along.
     Flag them; they belong in their own PR. (Resolver / dispatch-refactor
     PRs in particular ship no scalar address padding.)

4. **Review correctness.** For each changed file, hunt for real defects:
   logic errors, unhandled edge cases (empty collections, index 0, a `*`
   wildcard, a float where an int index is expected — OSC clients send
   those), error paths that swallow a Live exception instead of letting
   `_dispatch` turn it into a correlated `/live/error`, listener keys that
   don't match between start and stop, state that survives
   `/live/api/reload`. Fork-specific traps:
   - **Every address in the diff appears verbatim in [API.md](API.md)** with
     the argument list and reply shape the code actually produces. A
     plausible-looking address that nothing documents is the most dangerous
     change in this codebase.
   - Replies echo the request's identifying arguments (index, ids) so a
     client can correlate them; a getter registered through a
     `create_*_callback` wrapper without `include_ids=True` where the reply
     needs ids is a defect, not a style note.
   - Setters are silent unless `API.md` says otherwise; a setter that
     replies and a getter that doesn't are both contract findings.
   - Object-valued LOM members never go through the generic property loop;
     a handler taking a wire-supplied filesystem path follows the browser
     exporter's rule (reject, private `mkstemp` root).
   - `hasattr` is not a safe feature test on LOM objects and reading some
     members raises rather than returning falsy — check the `try` scope.
   - Anything touching a file or function named in [SESHAT.md](SESHAT.md)
     § Merge hazards gets read twice.

5. **Review test coverage.** Is every new behaviour actually exercised in
   `tests_unit/` — not "a test file exists" but do the assertions pin the
   contract the plan asked for (dispatch, argument validation, reply shape,
   error envelope, listener bookkeeping)? Nothing in that suite may bind a
   fixed port, import `tests/`, or need Live. Then run
   `python3 -m pytest tests_unit/` yourself; never take the PR's word.

6. **Run the plan's Live verification checks, if you can do so honestly.**
   Preconditions, all of which must hold before any result means anything:
   Live is running; the installed copy equals the checkout under review
   (`diff -rq --exclude=__pycache__ abletonosc "$HOME/Music/Ableton/User
   Library/Remote Scripts/AbletonOSC/abletonosc"`); and Live was restarted
   after that copy was made — files on disk are not code in memory, so if
   you cannot establish the restart, a divergence the checkout contains
   that does not show on the wire means a stale bridge, not a bug. You may
   not install, restart Live, click in Live, or bind the reply port; a
   running client (Seshat) holds `11001` and `/live/api/reload` under a
   live session is a user action. Method: `API.md` § "The no-probe
   variant" — fire-and-forget UDP to `127.0.0.1:11000`, evidence read from
   the new bytes of the installed `logs/abletonosc.log`, every mutation
   inside `begin_undo_step`/`end_undo_step` and restored. Write dated,
   concrete observations under each check in the plan doc — what came back,
   not "passed"; a failed check is a blocking finding. If a precondition
   fails, mark every check **skipped by environment** with exactly what is
   missing; never approximate, never write a result for a check you did
   not run. This plan update is the one intentional repository mutation a
   review makes.

7. **Review style and readability.** Naming that lies, functions doing two
   jobs, duplication of a helper that already exists in `handler.py` or a
   sibling module (grep before assuming it's new), comments that narrate
   instead of explaining a constraint, inconsistency with how neighbouring
   handlers do the same thing. Proportionate — style notes are suggestions,
   not blockers, and say so.

8. **Check ripple effects — what *else* should have changed.**
   - A divergence from upstream with no `SESHAT.md` entry — invisible at
     the next merge. An edit to an upstream file with no § Merge hazards
     note where losing it would be silent.
   - A closed gap with its `FORK_GAPS.md` entries still standing or the
     generated inventory not regenerated; a fixed defect or closed gap with the
     source write-up its roadmap entry cited still standing.
   - **Downstream:** does the plan's Downstream section still describe the
     diff? A changed reply shape, renamed address, or listener push that
     gained fields is a Seshat break that arrives as a pin bump — say so
     explicitly, and name what Seshat's `vendored_addresses_test` or
     decoding must change. "Pin bump only" claimed on a wire-contract
     change is a finding.
   - Stale references anywhere to renamed or moved things.

9. **Verify and report.** Aside from recording live evidence in the plan,
   verify without mutating the tree: record the working-tree state, run
   `python3 -m pytest tests_unit/`, and restore anything a verification
   command changed. Then write the review:
   - **Verdict first** — one of: approve, approve with nits, needs changes
     — with a one-sentence reason.
   - **Live verification next** — one of: passed, failed, incomplete,
     skipped by environment, not applicable. Name every check run and its
     observed result, and every check skipped with the reason.
   - **Findings ranked by severity** (bugs → contract/API.md gaps → plan
     gaps → test gaps → doc obligations → downstream → style), each with a
     `file:line` reference and, for bugs, the concrete scenario in which it
     misbehaves. A finding you can't state a failure scenario for is a
     style note, not a bug.
   - Skip the compliment padding. If a section has no findings, one line
     saying you checked it and it's clean is worth more than praise — and
     more than silence, which reads as "didn't look."
