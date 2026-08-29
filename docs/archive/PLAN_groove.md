**Archived 2026-08-29 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`abletonosc/groove.py` (new — `GrooveHandler`, `/live/groove/*`, plus the
Live-free pool helpers `song.py` and `clip.py` import), a hand-written
`/live/song/get/groove_pool` dump and listen pair in `abletonosc/song.py`,
and a hand-written `/live/clip/get|set/groove` pair and listen pair in
`abletonosc/clip.py`; `API.md` § "Groove API" and the `groove_pool` /
`groove` rows under Song and Clip are the permanent record. Live
verification's six checks did not run — the installed Remote Scripts copy
differs from this checkout in eight files and does not contain `groove.py`
at all (see the pr-review re-check recorded under Live verification below)
— so every ⚠️ marker in `API.md` stands and all four Open questions below
stay open for whoever verifies against a running Live next. One follow-up
surfaced in review — `stop_listen` can strand a listener when its indexed
collection shrinks (present in both `groove.py` and `scene.py`, fork-wide,
not groove-specific) — went to `ROADMAP.md` as its own item rather than
being fixed here; the `.agr`-via-browser measurement this item deferred
stays open under `FORK_GAPS.md`'s Groove Pool entry.

# Plan: Groove (D-2)

Roadmap item: **#1 · D-2 · Groove** — from `CLOSING_THE_GAPS.md` row D-2 and
the curated `Clip.groove` entry it named in `FORK_GAPS.md` (since folded
into [Groove Pool — closed](../../FORK_GAPS.md#groove-pool--closed-2026-08-29)).
Closes the whole `Live.Groove.Groove` class (6
members), `Live.GroovePool.GroovePool` (1 member, `grooves`),
`Live.Song.Song.groove_pool`, and the curated `Clip.groove` gap.

## Context

`Song.groove_amount` (`/live/song/get|set/groove_amount`, 0.0–1.3) scales how
strongly each clip's *assigned* groove applies — and nothing in this bridge
can assign one. `Clip.groove` holds a `Live.Groove.Groove` object, so it can
never ride the generic property loop: upstream left it commented out in
`clip.py`'s `properties_r` TODO list (currently `clip.py:256`) with the
observed failure `"Infered arg_value type is not supported"`. The result is
that on a set where no human has dragged a groove onto a clip, the
`groove_amount` knob does nothing at all — Seshat's generation work (feel
transfer, existing-context timing) is the named consumer that needs this
closed.

The object-read pattern this needs has shipped (roadmap item A-4 and its
successors): object-valued members get hand-written handlers that answer with
**indices into collections the address families already accept**, resolution
helpers live outside the handler so `tests_unit/` can drive them Live-free,
and `-1` means "none". See `API.md` § "Object-valued reads". The groove
family is index-keyed against one flat collection —
`song.groove_pool.grooves` — so it needs none of `track_identity.py`'s
category machinery; it reuses only the conventions (validate-don't-index,
fixed-arity replies, "none" as an answer, info-level logging on every
resolution) and `_index_of`-style `==` scanning.

Key constraints research surfaced:

- **The LOM surface is exactly** (generated inventory, Live 12.4.3 dump,
  2026-08-27): `GroovePool.grooves` (ro, observable);
  `Groove.base` (rw, **not** observable), `Groove.name`,
  `quantization_amount`, `random_amount`, `timing_amount`,
  `velocity_amount` (all rw, observable); `Clip.groove` (rw, observable,
  in the M4L table); `Song.groove_pool` (ro, observable — but the useful
  subscription is `grooves` on the pool object). `Clip.has_groove` (ro,
  observable) already works and stays as it is.
- **Live's own Move script** reads `song.groove_pool.grooves` as a plain
  sequence and `song.groove_amount` (read from the installed
  `MIDI Remote Scripts/Move/transport.pyc`, 2026-08-29) — confirming
  `groove_pool.grooves` is ordinary sequence access from Remote Script
  Python. Nothing shipped assigns `clip.groove`, so the write side is
  unwitnessed (see Open questions).
- **The roadmap goal sanctions `-1` as a setter argument** —
  `/live/clip/set/groove <track> <clip> <pool_index | -1>` where `-1`
  clears the assignment. That is a deliberate, documented exception to
  "`-1` is an answer, never an argument" (`API.md` § Object-valued reads):
  the appointed-device setter refused it because un-appointing was out of
  scope there; clearing a groove is *in* the goal here. Exactly `-1` is
  accepted; `-2` and below stay `ValueError`. Part 4 amends the convention
  text.
- **The browser has no groove root.** `Live.Browser.Browser` (inventory,
  21 members) has `instruments`/`sounds`/`drums`/…/`packs`/`user_library` —
  no `grooves` member exists in the LOM, and `browser.py`'s `CATEGORIES`
  does not include `packs`. So whether an `.agr` file is reachable at all
  through `/live/browser/get/items`, and what `browser.load_item` does with
  one, is genuinely open and Live-dependent (Live verification check 5; the
  roadmap explicitly defers this as a measurement).
- **Live is running but cannot be probed from this run**: probe writes into
  the installed copy and UDP sends were denied by the permission classifier
  in previous runs of this series, so per the archived-plan precedent
  (`PLAN_song_remainder.md`) every measurement is deferred to the Live
  verification section and each assumption carries a ⚠️.

## Wire contract

Canonical per-groove field order, shared by the pool dump and documented in
`API.md` (a module constant `GROOVE_FIELDS` the way `EXTENDED_NOTE_FIELDS`
is): `name, quantization_amount, timing_amount, random_amount,
velocity_amount` — Live's Groove Pool column order with `base` deliberately
left out of the dump (its wire type is unverified, and pythonosc drops an
entire reply it cannot encode; `base` is reachable via its own address, so an
encoding surprise breaks one address instead of the whole dump).

### New — Song: the pool dump (hand-written, `song.py`)

| Address | Request | Reply |
|---|---|---|
| `/live/song/get/groove_pool` | — | `(name, quantization_amount, timing_amount, random_amount, velocity_amount) * N` — five fields per groove, pool order; an empty pool replies with no payload arguments |
| `/live/song/start_listen/groove_pool` | — | immediate push + a push of the full dump on every pool **membership** change (`GroovePool.grooves` observer; amount/name edits do **not** fire it — subscribe per-groove) |
| `/live/song/stop_listen/groove_pool` | — | — |

The listen pair subscribes `grooves` on the `song.groove_pool` object via
`_start_listen(self.song.groove_pool, "groove_pool", (),
getter=song_get_groove_pool, lom_property="grooves")` — the `lom_property`
alias built for `selected_track_identity`. Push address is
`/live/song/get/groove_pool` (class identifier "song").

Errors: none specific — the getter never errors for an empty pool (empty is
an answer).

### New — Groove: per-groove properties (new handler, `groove.py`)

Every address takes `groove_index` (int, index into
`song.groove_pool.grooves`) as its first argument. A negative or
out-of-range index is a `ValueError` → structured `/live/error` naming the
real count — never a Python wrap-around. Replies are fixed-arity:
`groove_index, value`.

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/groove/get/name` | `groove_index` | `groove_index, name` |
| `/live/groove/set/name` | `groove_index, name` | silent |
| `/live/groove/get/base` | `groove_index` | `groove_index, base` ⚠️ wire type unverified — assumed an int-encodable enum like `warp_mode`/`launch_quantization`; value↔grid mapping unmeasured (Live verification check 4) |
| `/live/groove/set/base` | `groove_index, base` | silent ⚠️ same caveat |
| `/live/groove/get/quantization_amount` | `groove_index` | `groove_index, quantization_amount` |
| `/live/groove/set/quantization_amount` | `groove_index, amount` | silent |
| `/live/groove/get/timing_amount` | `groove_index` | `groove_index, timing_amount` |
| `/live/groove/set/timing_amount` | `groove_index, amount` | silent |
| `/live/groove/get/random_amount` | `groove_index` | `groove_index, random_amount` |
| `/live/groove/set/random_amount` | `groove_index, amount` | silent |
| `/live/groove/get/velocity_amount` | `groove_index` | `groove_index, velocity_amount` |
| `/live/groove/set/velocity_amount` | `groove_index, amount` | silent |
| `/live/groove/start_listen/<prop>` | `groove_index` | for the five observable props (`name` + the four amounts; **not** `base`); push on `/live/groove/get/<prop>` as `groove_index, value` |
| `/live/groove/stop_listen/<prop>` | `groove_index` | — |

⚠️ Amount ranges are unmeasured — the UI shows Quantize/Timing/Random as
0–100% and Velocity as −100–100%, so floats `0.0–1.0` and `-1.0–1.0` are
assumed; setters pass the float through unclamped (Live clamps), and
`API.md` marks the ranges as unverified until Live verification check 3.

Pool indices are positional and renumber when a groove is removed from the
pool — the same caveat as scene and track indices, stated in `API.md`.
Listener bookkeeping survives renumbering the same way every indexed family
does (`listener_objects` unbinds from the object actually subscribed).

### New — Clip: the assignment (hand-written, `clip.py`)

| Address | Request | Reply / behaviour |
|---|---|---|
| `/live/clip/get/groove` | `track_id, clip_id` | `track_id, clip_id, groove_index` — the index of `clip.groove` in `song.groove_pool.grooves`, or `-1` when no groove is assigned (or the object is not found in the pool by `==` scan — absence is an answer, not an error) |
| `/live/clip/set/groove` | `track_id, clip_id, groove_index` | silent. `groove_index >= 0`: validated against the pool (out-of-range → `ValueError` → `/live/error` naming the real count) then `clip.groove = grooves[groove_index]`. Exactly `-1`: clears — `clip.groove = None` ⚠️ (Live verification check 2). Below `-1`: `ValueError` |
| `/live/clip/start_listen/groove` | `track_id, clip_id` | `Clip.groove` is observable; push on `/live/clip/get/groove` as `track_id, clip_id, groove_index` |
| `/live/clip/stop_listen/groove` | `track_id, clip_id` | — |

Registered hand-written (never in the generic loops — the fork rule for
object-valued members) via `create_clip_callback`; the listen pair uses
`pass_clip_index=True` with a `getter` that re-resolves the clip from the
pushed identity, the `appointed_device` precedent. An empty clip slot fails
the same way every `/live/clip/*` address does (`AttributeError` →
structured `/live/error`).

### Changed

None. No existing address changes its arguments or reply shape.

### Unchanged but relied on

- `/live/song/get|set/groove_amount` — the knob these assignments make
  meaningful; its `API.md` row gains a cross-reference only.
- `/live/clip/get/has_groove` — the cheap read-back that proves a set/clear
  landed; already registered with its listen pair via the generic loop.
- `/live/error` structured envelope (`osc_server.py::_dispatch`) — carries
  every validation failure above.

## Numbered parts

### Part 1 — `abletonosc/groove.py`: the Groove handler and shared helpers

New module, modelled on `scene.py` (single-index callback family) with the
validation discipline of `track_identity.py`'s resolvers. Contents:

- `GROOVE_FIELDS = ("name", "quantization_amount", "timing_amount",
  "random_amount", "velocity_amount")` — the canonical order, with the
  do-not-reorder comment pointing at `API.md`.
- Module-level, Live-free helpers (importable by `song.py`/`clip.py`
  without cycles — `groove.py` imports only `.handler`/typing/functools):
  - `resolve_groove(song, index)` — validating `(index) -> Groove`;
    negative or out-of-range raises `ValueError` naming the real count
    (never a wrap-around).
  - `groove_index(song, groove)` — `==` scan of
    `song.groove_pool.grooves`, `-1` for `None`/absent (the `_index_of`
    semantics; do not import `track_identity._index_of` — it is private to
    that module's contract, so `groove.py` carries its own three-line scan
    with a comment saying it mirrors those semantics on purpose).
  - `groove_pool_dump(song)` — flattened `GROOVE_FIELDS` tuple per groove,
    coerced (`str(name)`, `float(...)` amounts) so an unencodable LOM
    value cannot drop the reply.
- `class GrooveHandler(AbletonOSCHandler)` with `class_identifier =
  "groove"` as a class-body assignment, **no** `__init__` (the subclass
  contract). `init_api` registers, via a `create_groove_callback` that
  normalises `int(params[0])` and truncates identity exactly as
  `create_scene_callback` does (`include_ids=True` for the listen pairs),
  resolving the groove through `resolve_groove`:
  - get/set for `name`, `base`, and the four amounts;
  - start/stop_listen for `name` + the four amounts only (`base` is not
    observable — registering a listen pair would fail at
    `add_base_listener` lookup);
  - every get logs its resolution at info level (object-read rule 7 —
    the installed log is the evidence channel).

Wire-in, same commit: `abletonosc/__init__.py` exports `GrooveHandler`;
`manager.py` adds `abletonosc.GrooveHandler(self)` to the handler list
(with the fork-owned-line comment style of the neighbouring additions);
`tests_unit/test_handler_subclass_contract.py`'s `EXPECTED_IDENTIFIERS`
gains `("groove.py", "GrooveHandler"): "groove"`, and that file's module
docstring tally ("nine of the twelve are loaded and driven end to end
today …") is updated to count `groove.py` and its conftest loader — ten of
thirteen — so the docstring stays true.

### Part 2 — `abletonosc/song.py`: the pool dump

In the SongHandler, after the `appointed_device` block (keeping the
object-valued hand-written handlers together): `song_get_groove_pool`
delegating to `groove_pool_dump(self.song)` (import at top of file), logged
at info; registered for `/live/song/get/groove_pool`, plus the
listen pair via `_start_listen(self.song.groove_pool, "groove_pool", (),
getter=song_get_groove_pool, lom_property="grooves")` and the matching
`_stop_listen(self.song.groove_pool, "groove_pool")`. A fork-owned comment
block states why `groove_pool` never enters the generic loops (object
collection) and that membership, not amounts, fires the push.

### Part 3 — `abletonosc/clip.py`: the assignment

Replace the `##"groove", ## if other than None, says …` TODO line (and only
that line — the neighbouring `warp_markers`/`view` TODOs stay) with a
comment pointing at the hand-written block. Add, alongside the other
hand-written clip handlers:

- `clip_get_groove(clip, params)` → `(groove_index(self.song, clip.groove),)`;
- `clip_set_groove(clip, params)` → parse `int(params[0])`; `-1` →
  `clip.groove = None`; `>= 0` → `clip.groove =
  resolve_groove(self.song, index)`; `< -1` → `ValueError`;
- the listen pair via `create_clip_callback(partial(self._start_listen,
  getter=<identity-resolving getter>), "groove", pass_clip_index=True)` —
  the getter re-resolves `self.song.tracks[t].clip_slots[c].clip` from the
  pushed identity and returns the index tuple;
- info-level logging on get and set.

### Part 4 — documentation, same commit as Parts 1–3

- **`API.md`**:
  - New `## Groove API (Seshat extension — not in upstream AbletonOSC)`
    section between `## Scene API` and `## Device API`: the
    `/live/groove/*` table above, the `GROOVE_FIELDS` order, the
    index-renumbering caveat, the `base`/range ⚠️ markers, and the
    listener-membership note.
  - § "Song Getters": a `groove_pool` row (dump shape + listen-pair
    behaviour + empty-pool answer); cross-reference from the
    `groove_amount` getter/setter rows ("assign via
    `/live/clip/set/groove`").
  - `## Clip API` table: `get/set/start_listen/stop_listen groove` rows
    next to `has_groove`, with the `-1`-clears contract spelled out.
  - § "Object-valued reads": add the groove family to the member list and
    amend the "`-1` is an answer, never an argument" sentence with the one
    sanctioned exception — `/live/clip/set/groove`'s `-1` = clear — and
    why the appointed-device setter stays narrow.
- **`SESHAT.md`** (§ Additions to upstream's code): one entry for the
  groove family — the new module + manager/`__init__` wire-in, the
  hand-written `song.py`/`clip.py` blocks (edits to upstream files), the
  removed TODO line, and the `-1`-as-argument exception. Rewrite the
  `swing_amount`/`groove_amount` entry's sentence "nothing in this bridge
  can assign one (`Clip.groove` is an unserializable LOM object — see the
  `clip.py` TODO)" to point at the new addresses.
- **`FORK_GAPS.md`**: delete the curated `Clip.groove` entry; add a
  `### Groove — closed <date>` entry to § Closed (naming every member
  closed: `Clip.groove`, `Song.groove_pool`, `GroovePool.grooves`,
  `Groove.*` × 6, and carrying forward the `.agr` question as still open),
  with the standard "the generated inventory below still lists the closed
  members as gaps: it is regenerated only from a `/live/application/dump_lom`
  taken against a Live running the installed copy" staleness note (the
  C-1/A-3 precedent — no dump can be taken this run). Update the
  § Dispositions "Groove Pool enumeration and clip assignment" row to
  **Landed** with a pointer to the Closed entry. Update the two prose
  mentions that still call the family open: the "Object-valued reads —
  closed" entry's "still unreached" sentence (`Device.view` remains,
  `Clip.groove` goes), and the "`Song` remainder — closed" entry's
  "Deliberately still open on this class" list (drop `groove_pool` from
  it, or point it at the new Closed entry). The § "cautions" bullet
  listing `groove_pool` among never-generic-loop members **stays** — it
  records why the family is hand-written, not that a gap is open.
- **`tools/lom_gaps.py`**: add `"groove": ["Live.Groove.Groove"]` to
  `PREFIX_CLASSES` and `ALIASES["Live.GroovePool.GroovePool"] =
  {"grooves": "/live/song/get/groove_pool, /live/groove/*"}` so the next
  real regeneration counts the family (`Song.groove_pool` and
  `Clip.groove` are covered by segment equality already).
- `CLOSING_THE_GAPS.md` row D-2 is **not** struck here — that happens at
  ship time, per the C-1/C-3/B-1/A-3 precedent.

### Part 5 — `tests_unit/`: coverage (same commit)

See Testing.

## Testing (`tests_unit/`, the only gate)

All Live-free, driven through `conftest.py`'s dispatch machinery.

- `conftest.py`: add `load_groove_module()` — `groove.py` imports only
  typing/functools/`.handler`, so it constructs on the Component stub alone
  (the `scene.py` shape); update the module docstring's handler tally.
- New `tests_unit/test_groove.py`:
  - fake song exposing `groove_pool.grooves` as a list of fake grooves
    (attributes per `GROOVE_FIELDS` + `base`, recording
    `add_/remove_<prop>_listener` the way existing fakes do);
  - `/live/groove/get|set/<prop>` dispatch and reply shape
    (`groove_index, value` echo, int-normalised index);
  - validation: negative, `-1`, out-of-range, float index (TouchOSC
    normalisation) → structured error path, message naming the real count,
    no wrap-around;
  - listener bookkeeping: start/stop pair keyed by normalised identity,
    push address `/live/groove/get/<prop>`, push carries
    `groove_index, value`, immediate initial push, float-start/int-stop
    naming one subscription, no listen registration exists for `base`;
  - `groove_pool_dump` / `/live/song/get/groove_pool`: field order, stride
    5, empty pool → empty payload, coercion to str/float;
  - `/live/song/start_listen/groove_pool`: subscribes `grooves` on the
    pool object (the `lom_property` alias — assert `add_grooves_listener`
    was called on the pool fake), push carries the full dump, stop
    unbinds;
  - `/live/clip/get/groove`: assigned → index, `None` → `-1`,
    object-not-in-pool → `-1`;
  - `/live/clip/set/groove`: index assigns the pool object, `-1` assigns
    `None`, `-2`/out-of-range → error, float index normalised;
  - `/live/clip/start_listen/groove`: identity-keyed bookkeeping and push
    shape `track, clip, index`.
- `test_handler_subclass_contract.py` covers the new row automatically once
  the map entry from Part 1 is added.

Explicitly *not* covered here: any behaviour of real LOM objects — whether
`clip.groove = None` is accepted, what `Groove.base` encodes to, listener
firing semantics. `tests/` (the live suite) is not part of the gate and is
not extended by this item.

## Live verification (deferred — the whole section)

Checked 2026-08-29 while planning: Live 12.4.3 is running, but the installed
copy differs from this checkout in seven files (`application.py`, `clip.py`,
`device.py`, `return_track.py`, `song.py`, `track.py`, `track_identity.py` —
`diff -rq`, pycache excluded), so even the no-probe variant would describe
code four unmerged PRs behind — and this run's environment denies the probe
writes and UDP sends the measurement rig needs anyway. Everything below
therefore waits for a session where the stacked branches are merged,
installed, and Live restarted.

**PR review, 2026-08-29 — every check below is SKIPPED BY ENVIRONMENT.** The
precondition fails on both halves. `diff -rq --exclude=__pycache__ abletonosc
"$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc"`
reports eight differing files (`__init__.py`, `application.py`, `clip.py`,
`device.py`, `return_track.py`, `song.py`, `track.py`, `track_identity.py`)
and `Only in .../ableton-osc/abletonosc: groove.py` — the installed bridge
does not contain this family's code at all, so no send could exercise it and
a silent wire would mean a stale install, not a bug. This run may not install,
restart Live, or send UDP either. Checks 1 (pool dump), 2 (assign and clear),
3 (amount ranges), 4 (`base`), 5 (`.agr` via the browser) and 6 (listeners)
are therefore each recorded as **skipped by environment: installed copy is not
this checkout and lacks `groove.py`; probe writes and UDP sends denied**. No
result is written for any of them.

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte (`diff -rq`) **and** Live has been restarted since it was
copied. Method: `API.md` § "The no-probe variant" — fire-and-forget UDP to
`127.0.0.1:11000`, evidence read from the installed `logs/abletonosc.log`
(all new handlers log at info; replies are invisible while Seshat's
`beam.smp` holds 11001). Wrap mutations in `begin_undo_step`/`end_undo_step`.
Setup once: drag any Core Library groove into the Groove Pool of a scratch
set so the pool is non-empty (check 5 may replace this step if it passes).

1. **Pool dump.** Send `/live/song/get/groove_pool`; evidence: the info log
   line with the dump matching the pool the UI shows (names, five fields per
   groove, UI column order). Empty-pool variant on a fresh set: log shows an
   empty tuple, no error.
2. **Assign and clear.** `/live/clip/set/groove t c 0` on a MIDI clip;
   read-back `/live/clip/get/has_groove t c` → `True` in the log, and the
   clip's groove chooser in the UI shows the groove. Then
   `/live/clip/set/groove t c -1`; read-back `has_groove` → `False`. If the
   clear raises (⚠️ `clip.groove = None` unwitnessed), the log shows the
   structured-error line — then the fallback is a measured alternative (M4L
   `id 0` analogue, or documenting clear-not-possible and rejecting `-1`),
   folded back into `API.md` and this plan's contract.
3. **Amount ranges.** `/live/groove/get/timing_amount 0` etc. against known
   UI values (100% ↔ ?); set `velocity_amount` to `-0.5` and read Live's UI.
   Evidence: log values + UI. Fold measured ranges into the `API.md` rows,
   dated and version-stamped.
4. **`base`.** `/live/groove/get/base 0` for each UI base setting (1/4,
   1/8, 1/16, 1/32) → the enum↔int mapping; one `set/base` round-trip with
   UI read-back. If the get errors (unencodable type), drop the
   `base` pair to get-only-via-int-coercion or remove it, and record why.
5. **`.agr` via the browser** (the roadmap's named measurement).
   `/live/browser/get/items user_library ".agr" 10` (and, in the same
   session, a filter of `"groove"`): does any loadable `.agr` item exist in
   the exposed categories at all? If yes: `/live/browser/load_item <uri>`
   on a selected scratch track, then `/live/song/get/groove_pool` — did the
   pool gain a groove, and what (if anything) landed on the track? Evidence:
   the browser handler's reply log + the dump diff. If `.agr`s are only
   reachable under `packs` (not an exposed category), record that: the
   answer is "not reachable today", and exposing `packs` becomes a
   candidate roadmap item — not scope here.
6. **Listeners.** `/live/groove/start_listen/timing_amount 0`, drag the
   dial in the UI → push lines in the log; `/live/song/start_listen/groove_pool`,
   drag a groove in/out of the pool → full-dump push lines, and confirm an
   amount edit alone does *not* fire it; `/live/clip/start_listen/groove`,
   assign via the UI chooser → push with the new index. Stop each listener
   afterwards (none of these properties is in Seshat's standing
   subscription set — grep the log for "Adding listener" first to confirm).

Uncovered even after all six: cross-version behaviour (only the running
12.4.3 is measured) and whether `Clip.groove` pushes fire on pool
*renumbering* (a groove removed above the assigned one changes the index but
not the object — the push only fires if Live notifies; the getter stays
correct either way, which is why the dump+get pair, not the listener, is the
source of truth).

## Downstream

**Pin bump plus one Seshat-side doc correction; no decoding changes.** Every
address here is new; no existing reply shape, address name, or listener push
changes. When this lands:

- Seshat bumps the submodule pin; `vendored_addresses_test` gains rows only
  if/when Seshat's `lib/` starts using the new addresses.
- Seshat's `CLAUDE.md` sentence saying the bridge cannot assign a groove
  (named by the curated FORK_GAPS entry) must be removed/rewritten — that
  claim becomes false the moment this merges.
- New tool surface (groove enumeration/assignment for the generation epic)
  is Seshat's call, not part of this item.

## Out of scope

- **Browser `packs`/groove-category exposure** — only if Live verification
  check 5 proves `.agr`s unreachable does this become a proposed roadmap
  item; nothing here touches `browser.py`.
- **`GroovePool` beyond `grooves`** — the class has no other members.
- **Groove extraction/commit workflows** (extract groove from clip, commit
  groove to clip) — no LOM surface exists in the inventory for either.
- **Seshat tools and prompts** — downstream's own work.
- **`warp_markers` and `view`** — the neighbouring commented-out TODO
  entries in `clip.py` stay exactly as they are.
- **`tests/` (live suite) additions** — the deferred verification section
  is the contract; folding checks into `tests/` can ride a later item.

## Open questions

1. **Does `clip.groove = None` clear the assignment?** Unmeasurable now
   (probe writes and UDP sends are permission-denied this run; nothing in
   Live's shipped scripts assigns `clip.groove`). The plan assumes yes —
   the M4L `id 0` idiom's Python analogue — and Live verification check 2
   decides; the fallback (reject `-1`, document clear-not-possible) is a
   contract change that must come back through `API.md` if taken.
2. **Can `browser.load_item` put an `.agr` into the pool, and are `.agr`s
   reachable through the exposed categories at all?** The LOM has no
   `Browser.grooves` root and `packs` is not an exposed category, so this
   may be unreachable today. Deferred to Live verification check 5; the
   answer decides whether ~3,000 shipped grooves are reachable without a
   human dragging one in, and a "no" spawns a follow-up item rather than
   widening this one.
3. **`Groove.base`'s wire type and value mapping.** Assumed an
   int-encodable enum (the `warp_mode` precedent). If it is not, the
   `base` addresses shrink to coerced-get-only or vanish — isolated by
   keeping `base` out of the pool dump. Live verification check 4.
4. **Amount ranges** (especially `velocity_amount`'s sign). Assumed
   `0.0–1.0` / `-1.0–1.0` per the UI percentages; setters pass values
   through unclamped either way. Live verification check 3.
