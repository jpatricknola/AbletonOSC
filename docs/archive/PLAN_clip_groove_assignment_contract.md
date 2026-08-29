**Archived 2026-08-29 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The read gate lives in
`abletonosc/groove.py` (`clip_groove_index`, called by both
`clip_get_groove` and `clip_groove_listener_value` in `abletonosc/clip.py`)
and the withdrawn clear in `clip_set_groove`'s `NO_INDEX` branch; the wire
contract is [API.md](../../API.md) § "Groove API" ("Assignment is one-way",
"The clip↔groove readings") and the divergences are in
[SESHAT.md](../../SESHAT.md). The one follow-up still open — confirming
`Clip.has_groove` answers `False` for a UI-ungrooved clip, which needs a
human at Live's UI — stays tracked in [FORK_GAPS.md](../../FORK_GAPS.md)
§ *`Clip.groove` — the "no groove" read is gated, but the gate is
unverified*; it is not a roadmap item.

---

# Plan: The clip↔groove assignment contract

Roadmap item: **"The clip↔groove assignment contract is broken in both
directions"** (topmost entry in [ROADMAP.md](../../ROADMAP.md)). Closes the
`FORK_GAPS.md` shape gap *"`Clip.groove` — "no groove" is indistinguishable
from pool index 0"* and the `CLOSING_THE_GAPS.md` "Not a bucket" note that
points at it.

Depends on: nothing. The Groove item it regresses (PR #22) has shipped.

## Context

The Groove item (PR #22, merged 2026-08-29) put `Clip.groove` on the wire as a
pool index and specified `/live/clip/set/groove -1` as **the one sanctioned
exception** to this fork's rule that "`-1` is an answer, never an argument"
(`API.md` § "Object-valued reads"). The first Live run after it merged
(PR #23, recorded in `API.md`) found both halves of that round trip broken:

- `clip.groove = None` raises `Boost.Python.ArgumentError` — Live's setter is
  typed `None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)` and refuses
  `NoneType` — so `set/groove -1` answers `/live/error` and the clip keeps its
  groove (`abletonosc/clip.py:501-531`).
- `get/groove` never answers `-1`: `groove_index`'s `==` scan
  (`abletonosc/groove.py:104`) matched an ungrooved clip's `groove` against
  `grooves[0]`, so "no groove" and "pool index 0" are the same value on the
  wire.

The consumer harm is the composition: replaying a read taken from an ungrooved
clip **assigns** it pool groove 0. That is worse than lossy, and it defeats the
Groove item's own stated purpose (making `Song.groove_amount` mean something on
sets where no human dragged a groove onto a clip).

### What research changed about the obvious approach

The obvious approach — "make `groove_index` compare by identity instead of
`==`" — is wrong on two counts, and a third finding reframes the read half
entirely.

**1. `==` on Live's Python proxies is not the broken part.** Measured against
Live 12.4.5 on 2026-08-29 (this plan's own run, no-probe variant, evidence in
`logs/abletonosc.log`): with Live's selection moved to scene 2,
`/live/view/get/selected_clip` logged `(0, 2)`. That getter is
`list(self.song.scenes).index(self.song.view.selected_scene)`
(`abletonosc/view.py:106`) — an `==` scan over LOM proxies — and it resolved to
the correct non-zero index. So "LOM proxies compare equal to anything" is
refuted for `Scene`, and identity (`is`) is *not* a candidate fix in any case:
Boost.Python hands back a fresh proxy on every attribute access, so
`clip.groove is grooves[0]` would be `False` even for a genuinely assigned
groove and every read would collapse to `-1`.

**2. Live has a purpose-built discriminator, and it is already on the wire.**
`Clip.has_groove` — LOM: *"Returns true if a groove is associated with this
clip. Available since Live 11.0"*, type `bool`, access `get`
([Cycling '74 LOM, Clip](https://docs.cycling74.com/apiref/lom/clip/)) — is
registered by upstream in `clip.py`'s `properties_r` (`clip.py:245`) and
documented at `API.md:1499`. Its *existence* is itself evidence that
`Clip.groove` never returns `None`: nothing else would need a separate flag.
Contrast `Track.group_track`, which does return `None` — measured this run,
`/live/track/get/group_track 0` logged `-1` for the single ungrouped track, via
`group_track_index`'s `is None` short-circuit (`track_identity.py:217`). So the
`is None` guard `groove_index` copied from that helper can never fire for a
groove, and the fix is to ask Live the question Live answers.

**3. ⚠️ The measured evidence is consistent with the read never having been
broken at all.** On the measured set (one MIDI track, no clips, a pool holding
one real groove — "Swing 16ths 66", `timing_amount = 100.0`, `base
gb_sixteen`), a clip created one second earlier by
`/live/clip_slot/create_clip 0 0 4` reported:

| Request | Log line |
|---|---|
| `/live/clip/get/has_groove 0 0` | `Getting property for clip: has_groove = True` |
| `/live/clip/get/groove 0 0` | `Getting property for clip: groove = 0` |
| `/live/clip/start_listen/groove 0 0` | `Adding listener for clip (0, 0), property: groove` then `Property groove changed of clip (0, 0): (0,)` (the immediate current-value push, `handler.py:168`) |
| `/live/clip/set/groove 0 0 0` | `Resolving groove pool index 0 of 1`, `Setting property for clip: groove = 0` — **and no subsequent push**, although the listener was still bound |

Three independent signals agree that this brand-new clip already held pool
groove 0: Live's own `has_groove`, the `==` scan, and the absence of a change
notification on an observable property when that same groove was assigned. The
alternative readings — that `has_groove` is `True` for every clip, or that
`clip.groove = <pool groove>` silently does nothing — cannot be separated from
this one without **a pool holding at least two grooves**, and grooves cannot be
added to the pool over this bridge (`GroovePool` exposes only `grooves`, no
add/remove; there is no `Browser.grooves` root — see `FORK_GAPS.md`
§ "Loading an `.agr` groove file into the pool"). That measurement needs Live's
UI and is Live verification check **LV1/LV2** below.

This does not change what to build. Gating the read on `has_groove` is right
under every reading: if Live's flag is honest the defect is fixed, and if it is
not, no read this fork can write would have fixed it — but the fork stops
guessing with an `==` scan and starts reporting Live's own answer.

**4. No spelling for "no groove" exists in any public source.** Checked this
run against the Cycling '74 LOM reference (`Clip`, `Groove`, `GroovePool`), the
NSUSpray `Live_API_Doc` generated XML, the Ableton Live 12 manual, and the M4L
forum threads on groove assignment: `Clip` has no `remove_groove` /
`clear_groove` / `commit`; `GroovePool` has exactly one member, `grooves`;
`Groove` has `base`, `name` and the four amounts and nothing else. The only
documented route to Groove = None is the UI's **Commit** button, which has no
LOM equivalent. The forum answer on assigning a groove
([Cycling '74](https://cycling74.com/forums/m4l-api-question-assign-a-groove-to-a-clip))
covers assignment only. The roadmap's own fallback therefore applies: **the
`-1` argument is withdrawn.**

## Wire contract

No address is added, removed or renamed. Two addresses change **meaning**; one
changes its error text. Argument lists and reply arities are untouched.

| Address | Request | Reply | Status |
|---|---|---|---|
| `/live/clip/get/groove` | `track_id, clip_id` | `track_id, clip_id, groove_index` | **changed** (values) |
| `/live/clip/set/groove` | `track_id, clip_id, groove_index` | — | **changed** (`-1` rejected) |
| `/live/clip/start_listen/groove` | `track_id, clip_id` | pushes on `/live/clip/get/groove` as `track_id, clip_id, groove_index` | **changed** (values) |
| `/live/clip/stop_listen/groove` | `track_id, clip_id` | — | unchanged |
| `/live/clip/get/has_groove` | `track_id, clip_id` | `track_id, clip_id, has_groove` | unchanged-but-relied-on |
| `/live/groove/*`, `/live/song/get/groove_pool` | — | — | unchanged |

**`/live/clip/get/groove`** — three ints, fixed arity, as today. `-1` becomes
**reachable**: it is answered whenever `Clip.has_groove` is false, without
consulting `clip.groove` at all. When `has_groove` is true the reply is the
pool index found by the `==` scan, still `-1` if that groove is somehow not a
pool member (absence stays an answer, `API.md` § "Object-valued reads" rule 6).
A getter still never errors for a "none" reason. `has_groove` raising
`RuntimeError` on some clip kind would surface as a structured `/live/error` on
the request path — loud, and not silently mistaken for "none"; no such clip
kind is known.

**`/live/clip/set/groove`** — `groove_index` must now be `>= 0`. Exactly `-1`
is rejected with a `ValueError` raised *by this fork*, arriving as
`/live/error ["request", "/live/clip/set/groove", "<detail>", 3, t, c, -1]`
where `<detail>` names the Live limit and points at the pool index range. The
clip is not touched. Previously this reached Live and came back as a
`Boost.Python.ArgumentError` naming a C++ signature — same envelope, same
address, different (and now truthful) detail. `-2` and below and any index past
the end of the pool keep exactly today's error, `resolve_groove`'s
`"Groove pool index out of range: %s (this pool has %d groove(s))"`. The setter
is otherwise silent on success, as today.

**`/live/clip/start_listen/groove`** — the push value is produced by the same
gate as the getter, so a push and a read of the same clip can never disagree.
The immediate current-value push at subscribe time is unchanged.

**Withdrawn contract text.** `API.md` § "Object-valued reads" stops carrying an
exception to "`-1` is an answer, never an argument": that rule becomes true as
written, everywhere, with no exceptions.

## Numbered parts

### Part 1 — `abletonosc/groove.py`: a clip-aware resolver

- Add a module-level `clip_groove_index(song, clip) -> int` beside
  `groove_index`:

  ```python
  def clip_groove_index(song: Any, clip: Any) -> int:
      """
      The pool index of `clip`'s groove, or NO_INDEX when it has none.

      `Clip.has_groove` is the discriminator, not `clip.groove`'s value.
      Live never hands back None here — the flag exists precisely because
      the member always holds an object — so the `is None` guard that works
      for `Track.group_track` can never fire for a groove, and an `==` scan
      alone cannot tell "no groove" from "pool index 0".
      """
      if not clip.has_groove:
          return NO_INDEX
      return groove_index(song, clip.groove)
  ```

- Keep `groove_index(song, groove)` exactly as it is — it is still the pool
  scan, is still what `clip_groove_index` calls, and its Live-free tests stay
  valid. Replace its ⚠️ docstring paragraph (the one describing the unreachable
  `NO_INDEX`) with a sentence saying it answers "which pool member is this
  object", that "has this clip a groove at all" is `clip_groove_index`'s
  question, and that callers must not ask this one about a clip.
- Rewrite the `NO_INDEX` comment block: it is reply-only **everywhere** in this
  fork now; delete the "one sanctioned exception" sentence and the ⚠️ block
  under it, and point at the Live limit recorded in `API.md` § "Groove API".
- Update the module header comment where it lists the conventions ("'none' as
  an answer (-1)") only if it also claims `-1` is an argument anywhere.

### Part 2 — `abletonosc/clip.py`: the read, the push and the withdrawal

- Import `clip_groove_index` alongside the existing
  `groove_index, resolve_groove, NO_INDEX` (`clip.py:5`). Drop `groove_index`
  from the import if nothing in this file still calls it (it will not).
- `clip_get_groove` calls `clip_groove_index(self.song, clip)`. Logging
  unchanged (`"Getting property for clip: groove = %d"`) — it is the evidence
  channel for LV1/LV3.
- `clip_groove_listener_value` calls `clip_groove_index(self.song, clip)` after
  re-resolving the clip from the pushed identity, so push and getter share one
  gate.
- `clip_set_groove`: replace the `index == NO_INDEX` branch's
  `clip.groove = None` with a raise. Keep the branch condition on exactly
  `NO_INDEX`, so `-2` and below still fall through to `resolve_groove` and keep
  their existing message:

  ```python
  if index == NO_INDEX:
      raise ValueError(
          "A clip's groove cannot be cleared over this bridge: Live's setter "
          "is typed (TPyHandle<AClip>, TPyHandle<AAbstractGroove>) and "
          "rejects None (measured against Live 12.4.5, 2026-08-29); no other "
          "spelling for \"no groove\" is documented in the LOM. Send a pool "
          "index >= 0 to assign; un-assign in Live's Clip Groove chooser. "
          "This pool has %d groove(s)."
          % len(self.song.groove_pool.grooves))
  ```

  ⚠️ **Keep "measured" attached only to what was measured.** `clip.groove =
  None` raising is a measurement (PR #23). "There is no spelling for no
  groove" is a *search* of public sources (OQ3), not a measurement, and the
  wire's error detail must not claim otherwise — this fork's evidence-tier
  discipline (`FORK_GAPS.md` § "Evidence tiers") applies to strings it puts on
  the wire as much as to its documents. The same split governs the `API.md`
  § "Groove API" wording in Part 3.

  The literal substring **`cannot be cleared`** is what distinguishes this
  message from `resolve_groove`'s; Part 4's `-2` test asserts on that
  distinction.

- Rewrite the `# Clip: groove` comment block (`clip.py:466-500`). It currently
  says "Do not 'tidy' the -1 branch away: it is the shape the fix restores" —
  that instruction is now wrong and must go. The replacement states: the read
  is gated on `Clip.has_groove`; assignment is one-way because Live offers no
  "no groove" value; `-1` is no longer an argument anywhere in this fork.

### Part 3 — Documentation, in the same commit as Parts 1–2

- **`API.md` § "Object-valued reads"** — delete the whole ⚠️ block that begins
  *"`/live/clip/set/groove` was specified as the one sanctioned exception…"*
  (currently `API.md:178-202`). Rule 4's parenthetical "the same half of the
  convention as '`-1` is an answer, never an argument'" then stands unqualified.
  Add one sentence to rule 3 or 4 recording that `Clip.groove` is the member
  where "none" is *not* a `None` — `Clip.has_groove` is the discriminator — so
  a future object-valued read checks for a companion flag before assuming
  `is None`.
- **`API.md` Clip API rows** (`API.md:1499-1503`) — rewrite `get/groove`,
  `set/groove` and `start_listen/groove` to the contract above. `get/groove`
  loses its "⚠️ the `-1` documented here is unreachable" and gains "answers
  `-1` when `Clip.has_groove` is false". `set/groove` loses "⚠️ `-1` does not
  clear" and gains "`-1` is rejected with a structured `/live/error`;
  assignment is one-way — Live offers no way to un-assign over this bridge".
  `has_groove`'s own row gains a pointer to `get/groove`.
- **`API.md` § "Groove API"** — add a short **"Assignment is one-way"**
  paragraph: what was searched (LOM `Clip`/`Groove`/`GroovePool` member lists,
  the Live 12 manual, M4L forum threads), that the UI's Commit button is the
  only documented route to Groove = None, and that this reopens only if a
  future Live adds a member.
- **`API.md` measurements** — fold this plan's run in beside the measurements
  already there, dated and version-stamped: the `has_groove`/`get/groove`
  readings on a freshly created clip, the missing change-notification on
  re-assignment, `group_track = -1` for an ungrouped track, and
  `selected_clip = (0, 2)` as the evidence that an `==` scan over LOM proxies
  resolves correctly. Verbatim log lines are in this plan's Context §3.
- **`FORK_GAPS.md`** — delete the shape-gap entry
  `### Clip.groove — "no groove" is indistinguishable from pool index 0`
  (currently `FORK_GAPS.md:330-341`) once LV1 passes. A missing *clear* is a
  Live limit, layer 1 in that file's own taxonomy, not a fork shape gap; it
  lives in `API.md` § "Groove API" and `SESHAT.md` instead. **No inventory
  regeneration is needed**: no member's reachability changes, `Clip.groove` and
  `Clip.has_groove` are both already counted as exposed, and `tools/lom_gaps.py`
  needs a fresh `/live/application/dump_lom` this change does not produce.
  **Three branches, and the implementer must take exactly one — the third is
  the likely one:**
  1. **LV1 run and it passes** (`has_groove = False` → `groove = -1` on a
     UI-confirmed ungrooved clip): delete the entry, and write the `API.md`
     rows as measured fact, dated and version-stamped.
  2. **LV1 run and it falsifies the gate** (`has_groove = True` on that clip):
     keep the entry, narrowed to the read half, and say what LV1 measured. The
     `API.md` rows must *not* claim the fix — they say the read is now Live's
     own `has_groove` answer and that Live's flag does not discriminate.
  3. **LV1 could not be run** (no Live, no permission to install into the
     Remote Scripts directory, or no way to build the two-groove /
     ungrooved-clip set through Live's UI): **keep the `FORK_GAPS.md` entry**
     and rewrite it, rather than deleting it — the gate has landed but the
     Live-side claim is unverified, so the gap is not closed. Every `API.md`
     and `SESHAT.md` sentence about the read carries a ⚠️ **unverified** marker
     naming `Clip.has_groove` as the assumption, in the fork's usual
     measured-vs-assumed idiom (`FORK_GAPS.md` § "Evidence tiers"). Do **not**
     delete the entry and do **not** write "measured" anywhere. The setter half
     is unaffected: the `-1` withdrawal rests on `clip.groove = None` having
     *already* been measured to raise (PR #23), not on LV1.
- **`CLOSING_THE_GAPS.md`** — update the "Not a bucket: **`Clip.groove`'s
  unreachable `-1`**" note (currently `CLOSING_THE_GAPS.md:99-100`) so it stops
  pointing at a roadmap entry that is about to be deleted; either drop it or
  restate it as the Live limit.
- **`SESHAT.md`** — this is a divergence edit, not a new entry: the groove
  family's entry (around `SESHAT.md:1312-1326`) currently describes the
  sanctioned `-1` exception and its failure. Rewrite it to say `-1` was
  withdrawn, the read is gated on `Clip.has_groove`, and this fork now has no
  exception to "`-1` is an answer, never an argument". Update the
  "**Measured against Live 12.4.5 on 2026-08-29**" paragraph
  (`SESHAT.md:1363`) with this run's readings.
- **`ROADMAP.md`** — untouched by the implementer; `/ship` deletes the entry.
- **`README.md`** — untouched. Its tables are upstream's.

### Part 4 — `tests_unit/test_groove.py`

The fakes are what made this look green, so they change first.

- `FakeClip` gains `has_groove`. Model Live honestly: make `groove` a property
  whose setter also sets `self.has_groove = True`, with `has_groove`
  independently assignable so a test can construct the pathological
  combination. Because the `groove` setter sets the flag, the pathological
  fixture is built in that order — assign `groove`, *then* force
  `has_groove = False`.
  The module docstring makes the withdrawn claim in **two** places, and both
  must go: `test_groove.py:12-15` ("the one address in this fork that accepts
  `-1` as an *argument* (exactly `-1` clears; `-2` and below are a
  `ValueError`)") and `test_groove.py:23` ("whether `clip.groove = None`
  actually clears the assignment" as an open question).
- Tests to change:
  - `test_clip_set_minus_one_clears_the_assignment` (`:712`) → becomes
    `test_clip_set_minus_one_is_a_structured_error`: assert
    `/live/error` on `/live/clip/set/groove`, that the detail carries
    `cannot be cleared` and names the pool size, and that the clip's groove is
    **unchanged** (still `song.groove_pool.grooves[0]`, not `None`).
  - `test_clip_set_round_trips_a_read` (`:724`) → becomes
    `test_a_read_of_minus_one_cannot_be_replayed`: read `-1` from an ungrooved
    clip, send it back, assert the structured error and no mutation. The
    docstring says plainly that this is deliberately *not* a round trip.
  - `test_clip_get_reports_minus_one_when_no_groove_is_assigned` (`:675`) keeps
    its name; the fixture clip must now carry `has_groove = False`.
  - `test_clip_listener_pushes_the_index_with_the_clip_identity` (`:765`) keeps
    working through the property setter.
- Tests to add:
  - **The defect itself:** a clip with `has_groove = False` whose `groove` is
    `song.groove_pool.grooves[0]` reads `-1` from `/live/clip/get/groove`. This
    is the one test that fails against today's code.
  - The same clip pushes `-1` through `/live/clip/start_listen/groove`.
  - `clip_groove_index` driven directly as a plain function (the loader in
    `conftest.py`'s `load_groove_module()` already exposes the module): False
    flag → `NO_INDEX` without touching `.groove`; True flag → the scan's index;
    True flag with an orphan groove → `NO_INDEX`.
  - `set/groove -2` still answers the *out-of-range* message, not the new one —
    pins that the withdrawal did not swallow the range check. ⚠️ **Assert on
    text that actually separates the two.** Both messages will end
    `... groove(s)`, so the existing `"2 groove(s)" in detail` idiom cannot
    tell them apart: assert `"out of range" in detail` **and**
    `"cannot be cleared" not in detail` for `-2`, and the converse for `-1`.
- Test to rename: `test_clip_set_rejects_everything_but_minus_one_and_a_real_index`
  (`:737`, parametrized `[-2, -100, 2, 42]`). Its name asserts the withdrawn
  contract. Rename to drop "but_minus_one", and either fold `-1` into the
  parametrize list with a per-case expected substring or leave `-1` to its own
  test above — but the name must stop saying `-1` is accepted. Its
  `"2 groove(s)" in detail` assertion stays valid for the four existing cases.
- Live-free only. `tests_unit/` drives dispatch, validation, reply shape and
  listener bookkeeping through `conftest.py`'s `dispatch` fixture against fakes;
  it proves nothing about how a real `Live.Clip.Clip` behaves, which is exactly
  the gap that produced this defect. `tests/` mutates a running Live on import
  and is **not** part of the gate. The gate is the command in **Testing** below.

## Testing

The Live-free gate and the only one. It must be green before and after, and
the new "defect itself" test must be demonstrably red against `HEAD` before
Parts 1–2 land (run it once on the unfixed code and record that in the PR).

⚠️ **Bare `python3` on this machine has no pytest** (`/opt/homebrew/.../python3.13`
answers `No module named pytest`). The gate runs as:

    /opt/anaconda3/bin/python3.12 -m pytest tests_unit/

**Baseline measured 2026-08-29 at `23e9df6`: 729 passed.** Any run reporting
fewer collected tests than that is a broken invocation, not a green gate.

What `tests_unit/` covers here: address registration, the dispatch path for all
four clip groove addresses, the `-1` rejection's structured `/live/error`
envelope and detail, reply arity and int-ness, the listener's bookkeeping and
push value, and `clip_groove_index` / `groove_index` / `resolve_groove` as
plain functions.

What it cannot cover: whether `Clip.has_groove` is false for a clip Live's UI
shows as ungrooved, whether `Groove.__eq__` compares the underlying object or
matches the first pool member, and whether `clip.groove = <pool groove>`
actually lands. Those are LV1–LV5.

## Live verification

**Precondition shared by every check:** the Remote Scripts copy at
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/` must equal this
checkout byte for byte (`diff -rq`, ignoring `__pycache__`, `logs/` and the
markdown files) **and** Live must have been restarted since it was copied —
files on disk are not code in memory. Every setter is fire-and-forget, so each
mutating check below names its read-back. Method: `API.md` § "The no-probe
variant" — send from a plain UDP socket to `127.0.0.1:11000`, read the new
lines of `logs/abletonosc.log`; never bind `11001`. Wrap mutations in
`/live/song/begin_undo_step` … `/live/song/end_undo_step`.

**Set-up (needed by LV1 and LV2, and only doable in Live's UI):** a set whose
Groove Pool holds **two** grooves — drag a second one in from Live's browser —
and a Session clip whose Clip Groove chooser reads **None**. Grooves cannot be
added to the pool over this bridge.

⚠️ **None of LV1–LV5 is a gate on landing the code, and LV1/LV2 will most
often be un-runnable.** They need a human at Live's UI, a matching installed
copy and a restart — none of which an unattended implementer has. The Live-free
gate above is the only gate. What LV1's outcome *does* decide is what Part 3
writes in `FORK_GAPS.md`, `API.md` and `SESHAT.md`; that bullet names all three
branches, including "could not be run", and the implementer must state in the
PR which branch it took. Shipping unverified is allowed here; shipping
unverified while *claiming* it was measured is not.

- **LV1 — the read (decisive).** Send `/live/clip/get/has_groove <t> <c>` then
  `/live/clip/get/groove <t> <c>` against the UI-confirmed ungrooved clip.
  Evidence: `Getting property for clip: has_groove = False` followed by
  `Getting property for clip: groove = -1`. A `has_groove = True` on a clip the
  UI shows as None falsifies the gate — the read cannot be fixed, and Part 3's
  `API.md` rows and the `FORK_GAPS.md` entry must say so instead of claiming
  the fix.
- **LV2 — the scan (decisive for `==`).** With two grooves in the pool, send
  `/live/clip/set/groove <t> <c> 1`, then `/live/clip/get/groove <t> <c>`.
  Evidence: `Resolving groove pool index 1 of 2`,
  `Setting property for clip: groove = 1`, then
  `Getting property for clip: groove = 1`. A `0` on the read-back proves the
  `==` scan matches the first pool member regardless, and `groove_index` needs
  a different comparison (open question OQ2 reopens). Restore with
  `/live/clip/set/groove <t> <c> <original>` or the undo step.
- **LV3 — the withdrawal.** Send `/live/clip/set/groove <t> <c> -1` on a
  grooved clip. Evidence: an `[ERROR]` line naming
  `/live/clip/set/groove` whose message is this fork's "cannot be cleared over
  this bridge" text — **not** a `Boost.Python.ArgumentError` traceback — and a
  following `/live/clip/get/groove <t> <c>` logging the clip's unchanged index.
- **LV4 — range check intact.** Send `/live/clip/set/groove <t> <c> -2`.
  Evidence: `Groove pool index out of range: -2 (this pool has 2 groove(s))`,
  and a read-back showing no change.
- **LV5 — the push.** `/live/clip/start_listen/groove <t> <c>` on the ungrooved
  clip: evidence `Adding listener for clip (<t>, <c>), property: groove`
  immediately followed by `Property groove changed of clip (<t>, <c>): (-1,)`.
  Then `/live/clip/set/groove <t> <c> 0` and expect a second push `(0,)` — this
  also settles whether the setter lands at all, which this plan's run could not
  (no push arrived when the assigned groove was already the clip's). Finish
  with `/live/clip/stop_listen/groove <t> <c>`.

### Results — 2026-08-29 (PR review)

**LV1, LV2, LV3, LV4, LV5 — all skipped by environment.** No check was run and
no result is recorded for any of them.

What is missing, checked at review time: Live 12 Suite *is* running
(pid 99572), but the installed copy is **not** this checkout —
`diff -rq --exclude=__pycache__ abletonosc "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc"`
reports `abletonosc/clip.py` and `abletonosc/groove.py` differ, i.e. the
installed bridge still carries the pre-fix `groove_index(self.song, clip.groove)`
read and the `clip.groove = None` clear. Installing the checkout and restarting
Live are both forbidden to this lifecycle run, so the precondition every check
shares cannot be met; LV1 and LV2 additionally need a human at Live's UI to
build a two-groove pool and a UI-confirmed ungrooved clip.

Consequently Part 3's **branch 3** is the correct and confirmed branch: the
`FORK_GAPS.md` entry stays open, and every `API.md` / `SESHAT.md` claim about
the read remains marked unverified.

**Remains uncovered.** Whether Live has any private, undocumented spelling for
"no groove" reachable from Remote Script Python — nothing in the LOM,
the apiref, the manual or the M4L corpus suggests one, and this fork cannot
enumerate C++ overloads. Whether a `Clip.groove` push fires when the *pool*
renumbers (already an ⚠️ on `API.md:1502`, unchanged by this item).

## Downstream

**Not a pin bump only.** No address is added, removed or renamed, so Seshat's
`vendored_addresses_test` needs no new tripwire and will not fire — which is
exactly why this must be called out: it is a silent semantic change to two
addresses.

1. `/live/clip/get/groove` can now answer `-1`. Any Seshat decoder that treats
   the third argument as a pool index must handle `-1` as "no groove" and must
   never feed it back to `/live/clip/set/groove`.
2. `/live/clip/set/groove <t> <c> -1` is now a rejected request. Any Seshat
   caller that sends `-1` to clear must be removed; clearing is not available
   over this bridge.

⚠️ **Unverified from this repository.** Whether Seshat consumes these addresses
at all could not be checked here. The groove family shipped on 2026-08-29, one
day before this plan, so the likely answer is "not yet" and the real downstream
action is a pin bump. The implementer or the shipper should grep Seshat for
`clip/get/groove`, `clip/set/groove` and `groove_pool` (start with
`lib/seshat/tools/handlers.ex` and the `vendored_addresses_test` fixture) and
record the answer in the PR. If nothing consumes them: **pin bump only**, and
say so having actually looked.

## Out of scope

- **Adding an address that clears a groove.** There is nothing to call.
  Reopens only if a future Live adds a member; the `API.md` § "Groove API"
  paragraph carries that condition.
- **Loading an `.agr` into the pool** (`/live/browser/*`). Stays in
  `FORK_GAPS.md` § "Loading an `.agr` groove file into the pool" and the
  browser-tree bucket in `CLOSING_THE_GAPS.md`. This item needs a two-groove
  pool only for *verification*, which the UI provides.
- **Folding `base` into the pool dump.** Stays the standalone
  `CLOSING_THE_GAPS.md` bucket. ⚠️ Note for whoever takes it: the LOM documents
  `Groove.base` as an **int** with an index-based setter
  (`0 = 1/4, 1 = 1/8, 2 = 1/8T, 3 = 1/16, 4 = 1/16T, 5 = 1/32`), while this
  fork measured it reading back as the string `gb_sixteen` — `API.md:1903`
  currently calls the mapping unmeasured. Do not fix that row here; it is a
  different address family and a different wire-contract change.
- **`stop_listen` stranding a listener when its collection shrinks.** Its own
  roadmap entry.
- **Any change to `/live/groove/*` or `/live/song/get/groove_pool`.** Untouched.

## Open questions

- **OQ1 — Is `Clip.has_groove` false for a clip Live's UI shows as ungrooved?**
  Unknown. Measured 2026-08-29 against Live 12.4.5: a clip created one second
  earlier reported `has_groove = True` in a set whose pool held one groove, and
  re-assigning that same groove fired no `Clip.groove` change notification. The
  reading that fits every signal is that the new clip genuinely held pool
  groove 0 — under which the read was never broken. It could not be separated
  from "`has_groove` is always true" without a second pool groove and a UI
  confirmation of the clip's Groove chooser, neither of which this session
  could produce (the Groove Pool cannot be written over this bridge, and this
  session was limited to read-only interaction with the running Live).
  **The plan assumes `has_groove` is honest** — it is Live's own documented
  answer to exactly this question, and gating on it is a strict improvement
  under either reading. **LV1 decides**, and Part 3 names what to write if it
  goes the other way.
- **OQ2 — Does `Groove.__eq__` compare the underlying object, or match the
  first pool member?** Unknown, for the same reason: one pool groove. `==` over
  `Scene` proxies resolves correctly (`selected_clip = (0, 2)`, measured this
  run), so the plan assumes `Groove` does too and leaves `groove_index`'s scan
  alone. **LV2 decides.** If it fails, `groove_index` needs a different
  comparison — `_live_ptr` equality is the candidate the LOM exposes — and that
  is a follow-up, not a reason to hold this item: the `has_groove` gate is
  independent of it.
- **OQ3 — Is there any spelling for "no groove"?** Answered as far as public
  sources go: no. `GroovePool` has only `grooves`; `Clip` has no
  `remove_groove`/`clear_groove`/`commit`; the manual's Commit button has no
  LOM equivalent; no M4L or GitHub example clears a groove. The plan withdraws
  `-1` on that basis. A probe handler in the *installed* copy could still try
  `dst.groove = <an ungrooved clip's groove object>` — the null-handle
  round-trip — in minutes (`API.md` § "Measuring the Live API without building
  the feature first"); this session was not permitted to write into the Remote
  Scripts directory. If that probe ever succeeds, the withdrawal is reversed
  and `-1` comes back as a sanctioned argument.
- **OQ4 — Does Seshat consume `/live/clip/get|set/groove`?** Not checkable from
  this repository. Assumed no (the family is one day old). See **Downstream**
  for the exact grep and where to record the answer.
