---
name: implement
description: Implement the change described in a docs/PLAN_*.md — work the numbered parts in order, resolve its open questions, verify with the Live-free suite, and report per-item status. Use when the user says to implement, build, or start on a planned item.
argument-hint: [plan or item, e.g. "wildcard getters"; defaults to the only active plan]
---

Implement the plan for: **$ARGUMENTS**

1. **Find the plan.** A `docs/PLAN_*.md` outside `archive/` matching
   $ARGUMENTS; with no argument, the single active plan doc — several, ask
   which; none, stop and suggest `/plan`. This skill implements a written
   plan, it doesn't invent one.

2. **Read the whole plan first**, Out of scope included — it binds as
   tightly as the parts. Settle Open questions before the parts that depend
   on them:
   - *Needs the user's call* → ask now, before code makes the choice by
     accident.
   - *Needs the Live API* → Live's own shipped Python and the apiref answer
     signatures; behaviour needs a measurement.
   - *Needs live Ableton* → check (`ps aux | grep -i "[A]bleton Live"`) and
     measure. **The plan's reason for leaving it open doesn't bind you** —
     it was written in another session. The probe rig in
     [API.md](API.md) § "Measuring the Live API without building the feature
     first" runs against the *installed* copy, never this checkout; prefer a
     non-destructive reading, and ask before spending the user's set.

   Only a question no available resource can answer stays open: implement
   the plan's assumption, carry the ⚠️ into your report, name what was
   missing.

3. **Set up the branch.** If on the default branch (`master`), create a
   feature branch named after the item — never implement on `master`.
   Confirm `python3 -m pytest tests_unit/` is green *before* you change
   anything, so a red suite later is yours.

4. **Work the parts in plan order** — it usually encodes real dependencies
   (contract → handler → docs). Per part:
   - Re-verify every address against [API.md](API.md) and the registering
     code as you write it — plan-to-code transcription is where a silent
     collision with a generic-loop registration creeps in.
   - Write that part's promised `tests_unit/` tests with it, not as a batch
     at the end. Drive dispatch through `conftest.py`'s fixtures; nothing in
     this suite may bind a fixed port, import `tests/`, or need Live.
   - **Documentation lands in the same commit as the code**: `API.md` rows for every added or changed address, a
     `SESHAT.md` entry for every divergence from upstream — including an edit
     to an upstream file, which also goes under § Merge hazards if losing it
     in a merge would be silent — the `FORK_GAPS.md` entries deleted and the
     inventory regenerated with `tools/lom_gaps.py` when a gap closes, the
     source write-up the roadmap entry cites removed or updated. `README.md`'s address
     tables are upstream's: leave them alone.
   - Every wire-contract change the plan's Downstream section names must
     still be true of what you built; if you widened it, say so in the
     report — Seshat's decoding is what breaks.

5. **When reality contradicts the plan, weigh it.** Mechanical corrections
   (a wrong wrapper, a helper that already exists): change it and log a
   deviation. Shape changes — a LOM member that misbehaves, a part that's
   unnecessary or insufficient: stop and tell the user. The plan doc stays
   as written either way; it's a point-in-time record, and deviations belong
   in your report, where [/pr-review](../pr-review/SKILL.md) looks for them.
   What [/plan-review](../plan-review/SKILL.md) corrected before you started
   is part of the plan, not a deviation from it.

6. **Verify.** `python3 -m pytest tests_unit/` green, and every changed
   module imports (`python3 -c` against the `conftest.py` loader if the
   module is one it can load; otherwise `python3 -m py_compile`). **Green
   proves less than usual here:** nothing in this repository executes a
   handler against a real Live object. Live runs the copy in
   `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`, loaded at
   startup — so your Python has never run until that copy is replaced from
   this checkout *and* Live is restarted. Say so plainly. If Live is
   running and the user has said the set is scratch, you may do both and
   run the plan's **Live verification** checks via `API.md` § "The no-probe
   variant" (fire-and-forget UDP, evidence from `logs/abletonosc.log`),
   writing dated observations under each check in the plan. Never claim a
   check you didn't run. **If the implementation outgrew the plan** — a
   behaviour its Live verification section doesn't cover — add the check
   there before anyone runs it.

7. **Report per plan item**: **done**, **deviated** (what and why) or
   **blocked** (on what). Then open questions resolved vs. carried — for
   each carried one, whether Live was running and what you measured — which
   Live verification checks ran and which only Live can still confirm, the
   Downstream verdict as built (pin bump only, or what Seshat must change),
   and the next step (`/pr-review`). Leave committing and pushing to the
   user unless they've said otherwise.
