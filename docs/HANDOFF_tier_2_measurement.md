# Handoff — measuring what the LOM members actually do

_Written 2026-08-30, at the end of the session that closed the inventory
question. This is the starting point for the next one: the inventory of Live's
Python API is effectively complete, and **almost none of it has been called**.
That is now the largest gap between this fork and its goal._

## Where things stand

**Settled — do not re-derive this.** The name-level inventory is done, and its
boundary has been checked from outside the walk:

- `dir(Live)` read from a running Live 12.4.5 is **exactly** the 43 modules the
  walker covers, in both directions.
- 141 entries — 134 classes and 7 modules.
- Method signature type edges: 61 distinct types named, 56 already walked, four
  of the remaining five are parse artefacts.
- Live's shipped binary was mined for its Boost.Python registration table and
  diffed against the walk. It is a **superset** of the Python API — it carries
  a module (`TestUtilities`, 43 functions), a member (`last_played_level`) and
  argument literals the interpreter does not expose. Absence from the walk is
  not evidence of a hole.

See [BLIND_SPOTS.md](../BLIND_SPOTS.md) for the measurements and the two
corrections that came out of them.

**One inventory hole remains**, and it is not a static problem: classes
reachable only as some *property's* value type. All 894 properties have a
getter and none carries a docstring, so no static walk can find them. That is
ROADMAP.md "Walk a live instance graph, not only the class graph".

## The actual gap

Everything in the inventory is **tier 1**: name, kind and docstring, read from
a running Live. Not called.

| kind | count |
|---|---|
| property | 894 |
| method | 589 |
| observable (`add_*_listener`) | 477 |
| enum / constant values | 533 |
| nested classes | 25 |
| **total members** | **3,472** |

The **callable surface is 1,483** (properties + methods). Against that,
`API.md` ships 559 address rows and carries **129 `⚠️` warning markers**, of
which **36** lines say "unmeasured" outright — places where a contract on an
already-shipped address is documented as unknown or unverified. Recounted
2026-08-30. Count them again before planning against the number; they move
with every address PR.

Two facts from this session are what the plan below is built on, because both
were invisible until something was called:

- `audio_to_midi_clip` declares `-> None` and is **asynchronous**. Nothing in
  the signature says so, and it decides the entire handler shape.
- It inserts the new track **directly after the source**, not last. The
  original claim was measured — on a layout where the wrong answer and the
  right one produce the same index. See issue #38.

A declared signature is not a contract. That is the whole reason this document
exists.

## The strategy: the read half is sweepable, the write half is not

Do not plan a 1,483-member manual campaign. Split it.

### Read half — exhaustive, automatable, one pass

Every property read and every getter-shaped method can be exercised in a single
read-only probe run that records, per member:

- the **actual type** of what comes back (`type(v).__name__`, and the element
  type for vectors — this is also what closes the instance-walk inventory hole)
- a truncated `repr`
- whether the read **raised**, and with what

This converts the majority of the surface from tier 1 to tier 2 in one run, and
it is safe: no mutation, no undo step needed. It is the same shape as the probe
run in this session, just wider. **Do this first** — it is the highest ratio of
answered questions to Live sessions available, and it subsumes ROADMAP #3's
inventory half.

Run it once per Live version, and once per edition if licences ever allow;
diffing two runs is what would finally answer which surface is edition-gated.

### Write half — not sweepable, demand-driven

Mutations cannot be swept. A blind sweep of 589 methods would load devices,
create tracks, fire clips and change routing in a real set. Measure a mutation
only when something needs it, one at a time, wrapped in
`/live/song/begin_undo_step` … `end_undo_step`, with the set snapshotted first.

Prioritise in this order:

1. **The `⚠️` markers in `API.md`** — 129 at the time of writing. These are
   shipped addresses whose contract is documented as unknown or unverified. They are the ones a consumer can already
   hit, so a wrong guess there is a live defect, not a future one. Start with
   any that Seshat calls.
2. **The next bucket in `CLOSING_THE_GAPS.md`** before its addresses are
   designed, not after. The conversions work is the cautionary tale: the
   handlers were designed against signatures, and both the asynchrony and the
   track placement had to be retrofitted into shipped docs.
3. Everything else, opportunistically, when a PR is already touching it.

## The rig

`API.md` § "Measuring the Live API without building the feature first" is
correct and was exercised successfully on 2026-08-30. Two updates to what it
says:

- ~~**Issue #35 is closed.**~~ Done 2026-08-30. `BLIND_SPOTS.md`'s two
  "currently broken on a fresh session (issue #35)" claims are corrected;
  `/live/api/reload` worked repeatedly this session and the issue is CLOSED on
  the fork. `API.md` never carried the claim.
- Probe output reaches `logs/abletonosc.log` in the **installed** copy *and*
  Live's own `Log.txt`. Prefix every line with something greppable and record
  the log's line count before the run.

### Hazards, all of them hit at least once

- **Port 11001 is Seshat's.** Replies cannot be captured. Send fire-and-forget
  to 11000 and read answers out of the log. Never bind 11001.
- **Never `stop_listen` a property Seshat subscribes to.** Grep the log for
  `Adding listener` for the current set — tempo, signature, `is_playing`,
  `root_note`, `scale_name`, groove/swing, `tracks`, `return_tracks`, master
  mixer params. `metronome` is free.
- **`hasattr` is not a safe feature test on LOM objects**, and a failed read is
  not falsy — `master_track.mute` raises `RuntimeError`. Every probe line needs
  its own `try`/`except` or one failure aborts the run.
- **A broken install reports as `NameError: name 'Manager' is not defined`**
  and nothing more, whatever the actual cause. Before debugging a probe that
  produces no output, `diff -rq -x __pycache__` the install against the repo.
  ROADMAP #1 is the fix for the reporting; jpatricknola/seshat#83 is the fix
  for the cause.
- **`mix abletonosc.install` is not atomic.** An interrupted run leaves the
  tree missing `manager.py` and `pythonosc/` — the last two things it copies.
  Verify both exist after any install.
- **Restore the installed copy afterwards** and confirm the probe address is
  gone (`Unknown OSC address`), then `diff` the install against the repo.

## What "measured" has to mean

The two corrections this session both came from claims that were technically
measured and still wrong. So:

- **Record the layout, not just the result.** "Appended last" was true of the
  set it was measured on and false in general. A measurement that cannot
  distinguish the answer from its alternative is not evidence — say what the
  set looked like and what a different result would have looked like.
- **One sample is one sample.** Say so, and say what would generalise it.
- **Do not correct one unfounded claim into another.** When
  `audio_to_midi_clip` was corrected, the other two conversions were recorded
  as *unknown* rather than assumed to match.
- **Tier 1 is not a conclusion.** `TestUtilities` was written up as falsifying
  a claim before anything had been called; the probe showed it is not reachable
  from Python at all.

## Open decisions for whoever picks this up

1. **Where does read-half output live?** It is a third artefact next to
   `lom_dump.json` and `FORK_GAPS.md`, and it is per-Live-version. Deciding
   whether it merges into the dump or sits beside it also decides whether
   `tools/lom_gaps.py` and `tests_unit/test_lom_gaps.py` have to move.
2. **What is the reference set?** Both the read sweep and the instance walk
   measure whatever set is open. A walk over a working set measures that set,
   not Live. Someone has to build and describe a set holding one of every
   device, and the dump has to record which set produced it.
3. **How much of the read half is worth doing before the instance walk**, given
   they overlap heavily — the read sweep answers the instance walk's inventory
   question as a side effect. They may be one item, not two.
