---
name: plan
description: Write an implementation plan for the highest-priority roadmap item (or a named one) — research the handler code, the Live Object Model and the existing wire contract first, then produce a docs/PLAN_*.md that later review and ship steps can check the work against. Use when the user says "plan the next item", "what's next", or names a roadmap item to plan.
argument-hint: [roadmap item, e.g. "wildcard getters" or "B-2"; defaults to highest priority]
---

Write an implementation plan for: **$ARGUMENTS** (no argument → the topmost
item in [ROADMAP.md](ROADMAP.md)).

You are planning, not implementing. The deliverable is a plan doc the user
reviews before any code is written. This plan is also the contract
`/pr-review` will later judge the implementation against, and `/ship` will
archive — so write items that are *checkable*: someone reading the diff should
be able to say yes/no to each one.

1. **Pick the item and read it closely.** The roadmap entry is the seed,
   not the plan — its **Goal** is the required outcome, its **Why** the
   problem, its **Planner notes** the constraints. If the entry cites a
   source write-up, read that too; for a gap, read the per-member rows of
   the generated inventory in [FORK_GAPS.md](FORK_GAPS.md) (owner class,
   rw/ro, observable, M4L column). Check the entry's **Depends on** list: a dependency that
   has not shipped is either folded into scope (and the plan says so) or the
   reason to stop and pick the next item.

2. **Research before writing a single plan line.** This is where plans earn
   their keep — the value of an archived plan is what research *changed*
   about the obvious approach.
   - **The wire as it stands.** Every address the plan touches or neighbours,
     verbatim in [API.md](API.md) — exact address, argument list, reply
     shape, and any measured behaviour recorded beside it. `API.md` is the
     canonical reference; `README.md`'s tables are upstream's, kept for merge
     fidelity, and lose where they disagree.
   - **The code that registers it.** Which handler module, whether the
     address comes from the generic `properties_r` / `properties_rw` /
     methods loops or a hand-written `add_handler`, whether it goes through
     `create_*_callback` wrappers (and with `include_ids`), and how
     `osc_server.py`'s `_dispatch` will treat its reply and its failures.
     Read [SESHAT.md](SESHAT.md) § Merge hazards before touching anything it
     names — those are the places where a careless edit is invisible.
   - **The Live API behind it.** The LOM member's real signature and
     behaviour, from Live's own shipped Python or the apiref, and — for
     anything marked Remote-Script-only or undocumented — a measurement
     (step 5). Object-valued members (`groove`, `group_track`, `appointed_device`,
     `cue_points`, `tracks`, `scenes`, `tuning_system`, …) never enter the
     generic property loop — they get a hand-written, index- or name-keyed
     handler; a handler taking a filesystem path follows the fork's
     path-safety rule (`browser/export` is the model: reject a wire-supplied
     destination, write under a private root).
   - **What is already settled.** ROADMAP's "Deliberately not planned",
     any Declined section in a source write-up the entry cites, the
     dispositions in `FORK_GAPS.md`, and any
     related doc in [docs/archive/](docs/archive/). Don't relitigate.
   - **The downstream consumer.** Seshat is the known client. A changed
     reply shape, a renamed address, a listener push that gains fields — each
     is a wire-contract change that the plan must call out as such, because
     it ships to Seshat as a submodule pin bump plus `vendored_addresses_test`,
     and a silent change there is a silent break there.
   - Anything you could not verify goes in the plan flagged with ⚠️, not
     silently assumed.

3. **Write the plan** to `docs/PLAN_<snake_case_name>.md` (create `docs/` if
   it doesn't exist), matching the house style of the docs in
   [docs/archive/](docs/archive/) once any exist:
   - **Context** — the gap or defect, why now, and any key constraint
     research surfaced. A reader should understand the change from this
     section alone.
   - **Wire contract** — every address added or changed, with exact request
     and reply argument lists, error behaviour (what arrives on
     `/live/error`), listener behaviour where applicable, and whether a
     setter is silent. Mark each as new, changed, or unchanged-but-relied-on.
     This section is load-bearing: it's what makes the rest of the plan
     checkable, and it is what becomes the `API.md` rows.
   - **Numbered parts** in implementation order, each naming the exact files
     to touch. Every part that adds or changes an address carries its
     documentation obligations *inside the same part*: the `API.md` rows,
     the `SESHAT.md` divergence entry (any deviation from upstream, including
     an edit to an upstream file), the `FORK_GAPS.md` entries to delete and
     the inventory to regenerate (`tools/lom_gaps.py`), the source write-up
     the roadmap entry cites to remove or update. All in the same commit as
     the code.
   - **Testing** — what `tests_unit/` covers (dispatch, validation, reply
     shape, listener bookkeeping — all Live-free, driven through
     `conftest.py`'s `dispatch` fixture). Be explicit that handler code
     against real LOM objects is *not* covered there, and that `tests/`
     mutates a running Live on import and is not part of the gate.
   - **Live verification** — what only a running Live can confirm, each as
     a concrete check: the address to send, the arguments, and the exact
     evidence that decides it (a reply, a `/live/error` naming the real
     count, a line in `logs/abletonosc.log`, a value read off Live's UI).
     Every setter is fire-and-forget, so each mutating check names the
     read-back that proves it landed. State the precondition every check
     shares: the Remote Scripts copy must equal this checkout byte for byte
     *and* Live must have been restarted since it was copied (files on disk
     are not code in memory). End with what remains uncovered and why. The
     method for running these without a client on the reply port is
     `API.md` § "The no-probe variant".
   - **Downstream** — what Seshat has to do when this lands: pin bump only,
     or a decoding change, a renamed address, a new tripwire in
     `vendored_addresses_test`. "Pin bump only" is a claim; mean it.
   - **Out of scope** — what you're deliberately not doing and where it
     goes (usually: stays on the roadmap or in its bucket). A plan without
     this section grows during implementation.
   - **Open questions** — every question the plan leaves unanswered, each
     stating what's unknown, why it couldn't be resolved now, and what the
     plan assumes meanwhile. The ⚠️ markers in the body should each have an
     entry here. Omit the section only if there are truly none.
   - Ordinary design choices don't belong in Open questions: make the call
     and record the reasoning in a sentence or two. A question is only
     *open* if it genuinely can't be answered at planning time.

4. **Link it from the roadmap.** Add a pointer to the plan doc in the item's
   `ROADMAP.md` entry (a `**Plan:** [docs/PLAN_x.md](docs/PLAN_x.md)` line
   under the title). Do **not** remove or shrink the entry — that happens at
   `/ship` time.

5. **Address open questions — by experiment, not by reasoning, wherever
   Live can answer.** Take a pass at every open question and try to *close*
   it. Check whether Live is running (`ps aux | grep -i "[A]bleton Live"`),
   and if it is, measure. The rig is written up in `API.md` § "Measuring the
   Live API without building the feature first": a temporary probe handler
   in the *installed* copy (never this checkout), `/live/api/reload` plus the
   probe address over fire-and-forget UDP, answers read out of Live's
   `Log.txt`, then the installed copy restored from this checkout. No Live
   restart, no commit, minutes not hours. Snapshot what you touch and undo it
   afterwards. Fold every measurement back into the plan *and* into
   `API.md` beside the measurements already there, dated and Live-version-
   stamped — a measurement that lives only in a plan is one the next person
   re-derives from the apiref.

   The only question that may stay open is one no available resource can
   answer. If Live isn't running, say exactly what is missing and make a
   confident recommendation the implementer can act on.

6. **Stop and summarize.** No implementation. Report: which item you
   planned, the two or three decisions most worth the user's attention,
   anything research contradicted in the roadmap entry or its source, what
   you measured against Live and what it changed, the Downstream verdict,
   and the Open questions verbatim. Implementation starts only when the user
   says go.

   End by recommending `/plan-review` — it re-derives this plan's wire
   contract independently of you, judges whether the approach is the
   smallest one that meets the objective, and on disagreement commissions a
   rival plan and adjudicates. Self-review is no substitute: the address
   check in particular is worthless performed by the agent that transcribed
   the addresses. `/lifecycle` runs it automatically as its own phase.
