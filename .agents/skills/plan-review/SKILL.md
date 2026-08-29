---
name: plan-review
description: Challenge an implementation plan before any code is written — verify its wire contract independently against API.md and the handler code, judge whether the approach is adequate and proportionate, and on disagreement commission a rival plan and adjudicate between them. Use after /plan, or when a plan doc needs a second opinion before implementation starts.
argument-hint: [plan doc path; defaults to the single active docs/PLAN_*.md]
---

Challenge the plan at: **$ARGUMENTS** (no path → the single active
`docs/PLAN_*.md`; if several are active, the one the roadmap links from).

Invoked directly, this skill means **§ Review** — that is the whole of it.
§ Rival and § Judge are the escalation § Review can call for, and they only
work as their own agents with inputs `$ARGUMENTS` has no room for (§ Rival
needs the reviewer's brief; § Judge needs both plan paths). `/lifecycle` runs
them that way; § Review step 7 says what to do outside it.

The point of this skill is to catch, while a plan is still prose, what would
otherwise be caught after an implementation has faithfully built the wrong
thing. In this repository the canonical case is a wire contract that looks
right and isn't: an address that collides with a generic-loop registration, a
reply shape a client cannot correlate, a listener push with no identity in it.
None of that is wrong *loudly* — OSC over UDP has no reply for a mistake.
[implement](../implement/SKILL.md) re-checks each address as it writes it and
[pr-review](../pr-review/SKILL.md) checks every one against `API.md`, but this
is the *cheapest* net: one agent here versus an implement cycle and a fix
round there. And a plan wrong in its **shape** has no downstream net at all —
pr-review judges the code against the plan.

---

## § Review

You are challenging the plan, not rewriting it. Beyond the corrections in
step 5, change nothing in the doc.

1. **Read the roadmap entry first — before the plan.** The entry in
   [ROADMAP.md](ROADMAP.md) states the Goal, Why and Planner notes; if it
   cites a source write-up, read that too. Form your own view of what the
   item needs. If you read
   the plan first you can only check whether it hangs together internally —
   the plan's own framing becomes the objective, and a plan that solves an
   adjacent problem immaculately will pass.

2. **Read what is already settled.** ROADMAP's "Deliberately not planned",
   any Declined section in a source write-up the entry cites, the dispositions in [FORK_GAPS.md](FORK_GAPS.md),
   [SESHAT.md](SESHAT.md) § "Why the fork exists" and § Merge hazards, and any
   related doc in [docs/archive/](docs/archive/). A reviewer that relitigates a
   settled decision every run is worse than no reviewer.

3. **Now read the plan, and run these checks.**

   - **Wire contract, re-derived.** Every address in the plan's contract
     section, checked against [API.md](API.md) and against the handler code
     that would register it — does the address already exist under a generic
     loop, does a `create_*_callback` wrapper strip the ids the reply needs,
     will `_dispatch` accept the reply type, does the error path reach
     `/live/error` with the request echoed. Derive it yourself; do not trust
     the plan's transcription. Downstream will re-check these — but only
     once code exists, which is exactly why you do it now.
   - **Adequacy.** Fully implemented, does this plan deliver the roadmap
     entry's **Goal** — the whole of it, not the convenient part? The failure
     mode is a plan that is internally perfect and solves the wrong problem.
   - **Invasiveness.** Is there a smaller change with the same outcome? The
     recurring axes here: an entry in a generic property/method list vs. a
     hand-written handler; an addition inside an upstream file vs. a handler
     module of ours (the second is cheaper at every upstream merge); a new
     address vs. widening an existing one's arguments; a resolver that
     several buckets share vs. one copied per handler table. And the one
     that costs most: a **wire-contract change** on an address a client
     already consumes.
   - **Risk, stated as blast radius.** What does this touch that everything
     else depends on — `osc_server.py`'s dispatch, `handler.py`'s base
     lifecycle, `manager.py`'s reload and error relay, a generic loop that
     every handler uses? Cross that with verifiability: `tests_unit/` can
     drive dispatch without Live, but nothing in this repository executes a
     handler against a real LOM object — that runs only in Live. High blast
     radius *plus* Live-only verifiability is what should stop a plan;
     either alone usually should not.
   - **Checkability.** Every numbered part must be yes/no decidable from a
     diff. "Wire it up appropriately" is where an implementer invents scope.
   - **Grounding.** Every file path named in the plan exists; every function,
     wrapper and list it references exists; the conventions it cites are
     real (0-based indices, echoed request args on replies, silent setters,
     the `("request", …)` error envelope).
   - **Structural completeness.** The plan carries every section
     [plan](../plan/SKILL.md) step 3 requires — Context, Wire contract,
     numbered parts, Testing, Live verification, Downstream, Out of scope,
     Open questions. Out of scope is the one that costs when it's missing.
     A Testing section that claims handler behaviour against Live objects
     is covered by `tests_unit/` is claiming a test nobody can write.
   - **The documentation sweep.** New address but no `API.md` rows in the
     same part? An edit to an upstream file with no `SESHAT.md` entry? A gap
     closed with no `FORK_GAPS.md` deletion and inventory regeneration? A
     fixed defect or closed gap whose cited source write-up is left standing? A changed reply
     shape with a Downstream section that still says "pin bump only"?
   - **Open-questions triage.** Are they genuinely open, or deferred
     decisions wearing a question mark? Anything tagged as needing the
     user's call is exactly what an unattended implementer will silently
     invent — either force a resolution or promote it to an assumption the
     implementer must record.

4. **Default to approve.** The failure mode of a plan reviewer is not
   missing things, it is finding things: plan churn that leaves each round
   longer and more hedged than the last. A finding needs a concrete
   downstream failure — *"if the implementer follows part 3 literally, X
   breaks"* — not a preference about the doc.

5. **Split what you found: correction or rival.** A **correction** is
   anything applicable without changing the plan's shape — a wrong address,
   a missing doc obligation, an unstated assumption. Apply corrections to
   the plan doc yourself *and* list them in your report, so the doc stays
   true for [pr-review](../pr-review/SKILL.md) and `/ship` while the
   implementer still sees them. Everything else — a different approach, a
   different decomposition — you cannot fix by editing, and you owe a rival
   plan.

6. **The bar for commissioning a rival.** All three, or it is a correction
   or a note:
   - Named concretely: files, addresses, approach. Not "consider something
     simpler."
   - Same objective, **smaller or safer** — never larger. An alternative
     that adds capability is out of bounds.
   - Clearly better, not arguable. Where reasonable people would split, the
     plan's author already made the call and it stands.

7. **Report.** Verdict first, on its own line:

   `PLAN_VERDICT: approve | approve_with_corrections | rival`

   Then: your independent reading of the objective; findings ranked by
   severity, each citing the plan section; corrections applied, listed
   verbatim; and — on `rival` — the brief: what is wrong with the approach
   and what direction the alternative should take. That brief is the rival
   author's entire starting point, so make it self-contained.

   Outside `/lifecycle`, `rival` is where you stop: give the user the brief
   and let them decide whether a competing plan is worth two more agents. Do
   not run § Rival yourself — its only value is that a different agent, which
   has not read the plan, writes it.

---

## § Rival

You are writing a competing plan. Your inputs are the roadmap entry (and any
source write-up it cites) and the reviewer's findings.
**Do not read the original plan while writing.**

1. Write your plan to `docs/PLAN_<same_snake_case_name>_alt.md` — **never**
   the canonical `docs/PLAN_<name>.md`, which still holds the plan you are
   competing with. Follow steps 1–3 of [plan](../plan/SKILL.md) against the
   brief for everything else: your own research, your own verified wire
   contract, your own complete doc, every section that skill requires. (Its
   step 3 names the canonical filename — that instruction is for the
   original author, not for you.) A rival that arrives as a critique or a
   sketch loses to a finished plan regardless of merit.

2. Do not touch the original doc and do not edit the ROADMAP link — the
   judge handles both.

3. Address the objection without overshooting it. You are not obliged to
   differ from the original anywhere the original is right, and you have no
   way of knowing where that is — which is the point. Where two
   independently derived plans agree, the judge learns the shared part is
   solid; where they diverge is the decision.

4. **Only when the plan is finished**, read the original once and append a
   short **"Differences from `PLAN_<name>.md`"** section: descriptive only,
   the divergences and what each turns on. Do not revise your own plan after
   reading it. That section is for the judge, who removes it either way.

5. Report the path you wrote and a two-paragraph case for your approach.

---

## § Judge

You are choosing between two plans and your decision is the only one in this
pipeline that nothing downstream reviews. Nobody checks you.

1. **Read the roadmap entry and its source, then both plans, and form your
   own view** before reading anything argued.

2. **Re-derive the decisive facts yourself.** Every address in *both*
   contracts against [API.md](API.md) and the registering code; every file
   path in both plans. A wrong address is invisible in prose, it is
   frequently what actually decides which plan is correct, and you cannot
   take either author's word for it. Where the two plans agree on a contract
   they derived independently, treat the agreement as evidence.

3. **Read the reviewer's findings last, as contested claims — not facts.**
   They are the only argued position you will see, and they were written by
   the agent that commissioned the challenger.

4. **Decide.** State it on its own line:

   `JUDGE_VERDICT: A | B | A_with_amendments | B_with_amendments | neither`

   where A is the original plan and B the rival. Amendments are bounded: a
   named part grafted from the loser, each citing its source plan and part
   number. If you want more than a few grafts you are rewriting rather than
   judging — that is `neither`.

5. **Promote the winner** (skip on `neither`):
   - The winner's content lands at the canonical `docs/PLAN_<name>.md`,
     amendments applied. If the rival won, its content replaces the
     original's at that filename — and drop its **"Differences from
     `PLAN_<name>.md`"** section as you move it; what it says belongs in the
     rejected-approach section below.
   - Delete the `_alt.md` file. The ROADMAP link points at the canonical
     path and never has to change, and `/ship` only ever sees one doc.
     **Exactly one `docs/PLAN_*.md` must be left active when you finish.**
   - Fold a short **"Approach considered and rejected"** section into the
     winner: what the losing plan proposed, and why you chose otherwise. A
     rejected rival is the strongest record this process produces of what
     research changed about the obvious approach; deleting it unrecorded is
     the one real loss available here.

6. **Report**: the verdict line, `PLAN_PATH: docs/PLAN_<name>.md`, what
   decided it, every amendment applied, and any finding you rejected and
   why. On `neither`, explain what both plans miss and stop — that is a
   judgment about the roadmap item itself, which belongs to the user. Leave
   both docs in place in that case and name both paths in your report.
