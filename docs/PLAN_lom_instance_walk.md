# Plan: Walk a live instance graph, not only the class graph

Roadmap item: **#3 · "Walk a live instance graph, not only the class graph"**
([ROADMAP.md](../ROADMAP.md)). Planned as **one item** merged with the
read-half sweep in [docs/HANDOFF_tier_2_measurement.md](HANDOFF_tier_2_measurement.md),
on the user's decision of 2026-08-30: the sweep's type column and the instance
walk's property-value-type answer are the same data, so one traversal produces
both. Closes [BLIND_SPOTS.md](../BLIND_SPOTS.md) blind spot 5, and the half of
blind spot 4 that migrated into it.

Depends on: nothing. ROADMAP #1 (masked import failures) has **not** shipped
and is not folded in — it would improve the development loop, not the
deliverable. Its consequence is a hazard, not a blocker, and is carried in
Live verification below: a broken install reports only as
`NameError: name 'Manager' is not defined`.

## Context

Every member in this repository's inventory is **tier 1**: name, kind and
docstring, read from a running Live and never called. 3,472 members, of which
the **callable surface is 1,483** (894 properties + 589 methods). Against that,
`API.md` ships 559 address rows carrying 129 `⚠️` markers, 36 of which say
"unmeasured" outright — contracts on already-shipped addresses documented as
unknown.

Two corrections from 2026-08-30 are why this item exists rather than more
static tooling. `audio_to_midi_clip` declares `-> None` and is **asynchronous**;
nothing in the signature says so, and it decided the entire handler shape. The
same method inserts its new track **directly after the source**, not last — the
original claim was measured, on a layout where the wrong answer and the right
one produce the same index (issue #38). A declared signature is not a contract.

The static channels are exhausted, and that is settled — do not re-derive it.
`dir(Live)` read from a running Live 12.4.5 is exactly the 43 modules the
walker covers, in both directions. Of 61 distinct type names in method
signatures, 56 already resolve to a walked entry and four of the remaining five
are parse artefacts. Live's shipped binary is a **superset** of the Python API,
so absence from the walk is not evidence of a hole. "Walk the type graph, not
the namespace" is declined in ROADMAP.md § Deliberately not planned, on that
measurement.

**One hole survives all of them, and it is not static.** A probe against Live
12.4.5 returned `Q1 properties=894 with_fget=894 fget_doc=0 fget_signature=0`:
every property has a getter and **not one carries a docstring**. `Song.tracks`
documents itself as *"Const access to a list of all Player Tracks"* — prose, no
type. A class reachable only as some property's value type is invisible to
every static walk, because the information is not in the interpreter to be
read. The only way to learn what `Song.tracks` holds is to hold a `Song` and
look. That is this item, and it is the last channel through which the walked
class list can be checked for completeness at all.

Three constraints research surfaced that shape the design below.

**The write-side path rule.** `/live/application/dump_lom [path]` takes an
arbitrary wire path and writes it with Live's privileges — the fork's one
outstanding violation of its own rule, tracked in `issues.md` (Low) and named
as such in `API.md:326` and `abletonosc/path_safety.py`'s header. The new
address must not repeat it. It takes **no path argument at all**.

**The fresh-session reload trap.** `introspection` was once imported only
inside the `dump_lom` callback, so on any session where that address had never
been fired `manager.reload_imports()` raised `AttributeError` on it and
silently skipped every module below while still logging `Reloaded code`.
`tests_unit/test_reload_list.py` now pins this with two dedicated tests
(`test_introspection_is_imported_by_the_package_init`,
`test_introspection_is_never_imported_inside_a_function`). Any new module in
`abletonosc/` inherits the same obligation — which is one reason this plan adds
none.

**Seshat's tripwire scrapes `add_handler` literals.** `vendored_addresses_test`
greps the vendored source for every `add_handler` string literal and checks
each appears in `API.md`. A new address whose `API.md` row is missing fails the
consumer's test, not ours.

## Wire contract

### `/live/application/dump_lom_instances` — **new**

| | |
|---|---|
| **Request** | *(no arguments)* |
| **Reply** | `path, num_types, num_objects, num_errors` — `str, int, int, int` |
| **Errors** | Any exception inside the handler reaches the caller as the structured `/live/error ["request", "/live/application/dump_lom_instances", message, 0]` through `osc_server.py`'s `_dispatch`, as for every other address. The walk itself never raises: every read is individually guarded and a failure becomes a record in the file. |
| **Listener** | None. Not a property. |
| **Path policy** | **Takes no destination from the wire.** Writes `logs/lom_instances.json` beside `logs/abletonosc.log`, the same directory `dump_lom` defaults to, and replies with the absolute path actually written. This is `browser/export`'s write-side rule in its simplest form (a fixed location rather than `mkstemp`, which is what `issues.md` names as an acceptable outcome for `dump_lom` too). |

Deliberately **not** `dump_lom [path]`'s shape. Adding a second address that
accepts a wire path would double the fork's one known policy violation while
`issues.md` still has it open.

### `/live/application/dump_lom` — **unchanged, relied on**

Reply `path, num_classes, num_addresses`. Unchanged in this item: the class
walk keeps its own address, its own file (`logs/lom_dump.json`) and its own
consumer (`tools/lom_gaps.py` → `FORK_GAPS.md`). Stated here because the two
are easily confused and a future reader must not merge them.

### `/live/song/get/file_path` — **unchanged, relied on**

Read once by the walk to record which set produced the dump. Already shipped
and already carries a `⚠️` in `API.md`: what a never-saved set answers is
unmeasured. The walk reads it under the same per-read guard as everything else,
so a `RuntimeError` there becomes `null` in the provenance block rather than an
aborted run.

## The output schema

Settled here because the handoff left it open, and because it is what makes the
rest checkable.

The dump is **keyed by type, not by object**. Recording every member of every
object would multiply 3,472 members by hundreds of instances into a file
nobody reads, most of it identical. Aggregating per type answers both of the
item's questions — the actual value type behind each property, and the surface
a given kind of object carries — at a size in the same order as the 545 KB
class dump.

The one place per-type is too coarse is exactly the one blind spot 5 names:
`Live.Device.Device` is one type whose instances differ by `class_name`, and
"which `DeviceParameter`s a Wavetable carries" is the question. So an object's
key is its type qualname **plus a discriminator** — `class_name` where the
object has one, absent otherwise. `Live.Device.Device/Wavetable` and
`Live.Device.Device/Operator` are separate entries.

```json
{
  "schema": 1,
  "live_version": "12.4.5",
  "provenance": {
    "song_file_path": "/Users/…/Whatever.als",
    "track_count": 12,
    "return_track_count": 2,
    "scene_count": 8,
    "device_class_names": ["Operator", "Wavetable", "…"],
    "coverage": "set-scoped",
    "walk_seconds": 4.1
  },
  "types": {
    "Live.Track.Track": {
      "instances": 12,
      "example_paths": ["song.tracks[0]", "song.tracks[3]"],
      "members": {
        "name": {
          "kind": "property",
          "reads": 12,
          "types": {"str": 12},
          "repr": "'Drums'"
        },
        "devices": {
          "kind": "property",
          "reads": 12,
          "types": {"DeviceVector": 12},
          "element_types": {"Live.Device.Device": 31},
          "repr": "<DeviceVector object at 0x…>"
        },
        "mute": {
          "kind": "property",
          "reads": 12,
          "types": {"bool": 11},
          "errors": {"RuntimeError: Master track has no mute": 1}
        }
      }
    }
  },
  "skipped": {
    "methods_not_read_shaped": 512,
    "methods_denylisted": ["…"],
    "depth_truncations": 0,
    "cycle_hits": 214
  },
  "totals": {
    "types": 38, "objects": 431, "reads": 9022, "errors": 57
  }
}
```

`element_types` is the field that closes blind spot 4's migrated half: it is
the only place in this repository where the value type of a property is
recorded rather than inferred. Vectors are sampled — the element type of the
**first** element, not every element, with the count recorded — because a
1,000-note vector's elements are all the same type and reading them all is
pure cost.

`repr` is the **first** observed value, truncated to 100 characters, matching
`_classify()`'s existing convention in `introspection.py`.

## Where the file lives, and what does not move

**`logs/lom_instances.json`, beside `logs/lom_dump.json` — not merged into
it.** `tools/lom_gaps.py` and `tests_unit/test_lom_gaps.py` therefore **do not
move and are not touched by this item.** The handoff flagged that decision as
gating them; this is the answer.

The reasoning, so it is not relitigated. The two files have different
provenance and different lifetimes: `lom_dump.json` is per-Live-version and
reproducible from any session, `lom_instances.json` is per-*set* and is only
as good as the set it was taken against. `FORK_GAPS.md` is a **member-level
coverage diff**, and BLIND_SPOTS.md blind spot 5 states outright that instance
shape "is not member-level surface, so this is not an argument that the
inventory is wrong". Merging set-scoped data into the file whose consumer
regenerates a per-version coverage report would make the report's numbers move
with whatever set happened to be open.

"One dump artefact" in the user's decision is satisfied: the read sweep and the
instance walk produce **one** file between them, from **one** traversal. It
sits beside the class dump rather than inside it.

## What may be called: the read-shaped predicate

All 894 properties are read. For methods, the sweep calls a method only when
**all** of these hold:

1. the name matches `get_*`, `is_*`, `has_*` or `can_*`;
2. the Boost.Python docstring parses to a signature taking **exactly one
   argument**, the receiver (`get_document( (Application)arg1) -> Song :` —
   yes; `get_data( (Song)arg1, (object)key, (object)default_value) -> object :`
   — no);
3. the name is not in an explicit denylist constant.

Everything else stays tier 1 and falls to the demand-driven write half, which
is not swept and is not in this item. `hasattr` is never used as a feature
test: it is not safe on LOM objects, and a failed read is not falsy.

Rule 2 does the real work and cannot be replaced by `inspect`: Boost.Python
methods expose no signature to `inspect.signature`, which is why the arity has
to come from the docstring — the same string `_classify()` already records.
A docstring that does not parse means **skip**, counted in
`skipped.methods_not_read_shaped`. Failing closed is the whole point.

Rule 3 exists because 1 and 2 are syntactic and Live is not obliged to be
honest. It ships as a named constant with a comment per entry, and it is
**not empty** — see the measurement below.

### Measured 2026-08-30, Live 12.4.5 — this predicate, against the real surface

The predicate was run before being planned, on this repository's own rule. A
temporary read-only probe in the installed copy applied rules 1 and 2 to every
method in `walk_live()`'s output and logged what survived:

```
PROBE2 totals methods=589 prefixed=44 selected=18 unparsed=0
```

Four things follow, and they change the plan rather than confirm it.

**The method half of the read sweep is 18 calls, not 589.** Of 589 methods,
44 carry one of the four prefixes and 18 of those take only the receiver. The
callable surface this item converts to tier 2 is therefore **894 properties +
18 methods**, and the remaining 571 methods stay tier 1 until something demands
one. That is a much smaller and much safer sweep than the handoff's framing
implied, and it is the honest number to plan against.

**The arity parser met no docstring it could not parse** — `unparsed=0` across
all 44. The Boost.Python signature format is uniform enough that rule 2's
fail-closed branch is a guard, not a routine path.

**The denylist is not empty.** Three of the 18 are
`Live.Licensing.PythonLicensingBridge`:

```
Live.Licensing.PythonLicensingBridge.get_progress_dialog
Live.Licensing.PythonLicensingBridge.get_session_id
Live.Licensing.PythonLicensingBridge.get_trial_time_left
```

`BLIND_SPOTS.md` already states the policy — *"Reachable is not desirable.
`Live.Licensing` is reachable and stays shut"* — and `get_progress_dialog`
additionally sits next to the `press_current_dialog_button` safety decline in
ROADMAP § Deliberately not planned. All three ship in
`READ_METHOD_DENYLIST` with that reason in the comment. A syntactic predicate
was always going to need a policy override; this is it, found by measuring
rather than by argument.

**The other 15 are unremarkable and the sweep calls them:**
`Application.get_bugfix_version`, `get_build_id`, `get_document`,
`get_major_version`, `get_minor_version`, `get_variant`, `get_version_string`;
`Clip.get_all_notes_extended`, `get_selected_notes`,
`get_selected_notes_extended`; `MaxDevice.get_bank_count`;
`Song.get_beats_loop_length`, `get_beats_loop_start`,
`get_current_beats_song_time`, `is_cue_point_selected`. Every one is a read.
`Application.get_document` returns the `Song` and is a recursion edge, not a
leaf.

**What this run does not establish.** It is one Live version, one edition, and
it proves only which methods the predicate *selects* — not that calling the 15
is harmless. The first real walk is what tests that, and its error map is what
would demote any of them into the denylist.

## Numbered parts

### 1 · The read-shaped predicate, and its tests

*Files:* `abletonosc/introspection.py`, `tests_unit/test_introspection_walk.py`

Add to `introspection.py`:

- `READ_METHOD_PREFIXES = ("get_", "is_", "has_", "can_")`
- `READ_METHOD_DENYLIST` — the three
  `Live.Licensing.PythonLicensingBridge` methods measured on 2026-08-30
  (`get_progress_dialog`, `get_session_id`, `get_trial_time_left`), each with
  its reason in the comment above it. Matched on the **qualified** name, not
  the bare one: `get_session_id` elsewhere in Live would be a different
  method.
- `_docstring_arity(doc)` → `int` or `None`. Parses the Boost.Python
  signature's parenthesised argument list; `None` when it does not parse.
- `is_read_shaped(name, doc)` → `bool`. Rules 1–3 above.

Pure functions over strings. No Live import, no I/O — directly unit-testable
the way `path_safety.py` is.

Tests, driven through `load_module` as the existing walk tests are:

- each of the four prefixes accepted at arity 1; a bare `name` rejected
- `get_data( (Song)arg1, (object)key, (object)default_value) -> object :`
  rejected on arity — the real signature, verbatim
- `get_document( (Application)arg1) -> Song :` accepted — the real signature
- an unparseable docstring rejected, and the empty docstring rejected
- a denylisted name rejected even when 1 and 2 hold (test injects an entry;
  it does not assert the shipped denylist is non-empty)

### 2 · The instance walk

*Files:* `abletonosc/introspection.py`

`walk_instances(root_objects, max_depth)` → `(types_dict, totals, skipped)`.

- **Cycle guard on `id()`**, one `seen` set for the whole walk. Live's object
  graph has `canonical_parent` back-edges the class walk never had to handle,
  and every device points back at its track.
- **Depth bound**, default 8, counted in `skipped.depth_truncations` when hit.
- **Every read in its own `try`/`except Exception`**, recording the exception
  class and message into the member's `errors` map and continuing.
  `master_track.mute` raising `RuntimeError` is the canonical case and one
  unguarded line aborts the run.
- **Never calls `add_*_listener` / `remove_*_listener` / `*_has_listener`.**
  `_classify()` already identifies all three kinds; they are recorded and not
  touched. This is what keeps the walk clear of the Seshat-subscription hazard
  — the walk cannot `stop_listen` anything because it never calls a listener
  member at all.
- **Recurses into** a value whose type is a `Live.*` class, and into the
  elements of a vector (first element only, for type; the count is recorded).
  Does not recurse into scalars, strings or `None`.
- **Instantiates nothing** and loads nothing from the browser. `type()`,
  `dir()`, attribute reads and read-shaped zero-argument calls only.

### 3 · The dump, the address and its documentation

*Files:* `abletonosc/introspection.py`, `abletonosc/application.py`,
`API.md`, `SESHAT.md`, `README.md` *(no — see below)*

`dump_lom_instances(path)` in `introspection.py`: builds the provenance block
(`song.file_path` under its own guard, track/return/scene counts, the sorted
set of `class_name` values actually found), runs `walk_instances` from
`get_application()` and `song`, writes the JSON, logs one greppable summary
line, returns `(path, num_types, num_objects, num_errors)`.

In `application.py`, beside the existing `dump_lom` block and using the same
`introspection` module already imported at module scope:

```python
def dump_lom_instances(params: Tuple[Any] = ()) -> Tuple:
    module_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    path = os.path.join(module_path, "logs", "lom_instances.json")
    return introspection.dump_lom_instances(path)
self.osc_server.add_handler("/live/application/dump_lom_instances", dump_lom_instances)
```

`params` is accepted and **ignored** — the signature is the dispatch
convention, not an argument channel.

Documentation obligations, in this same commit:

- **`API.md`** — one row in the Application API table for the new address,
  with the reply argument list, the no-path policy and a sentence saying the
  output is set-scoped. Also amend the § "Handlers that name a file to read"
  paragraph at `API.md:326`, which currently says "One address still violates
  the write-side rule": it must name `dump_lom` specifically rather than
  implying the count is one across the file, now that a second dump address
  exists which does *not* violate it.
- **`SESHAT.md`** — extend the existing
  `introspection.py` + `application.py` divergence entry (§ "Additions to
  upstream's code") rather than adding a second: same module, same rationale,
  new address. Record that the new address takes no wire path *and why*, so a
  future reader does not "fix" the inconsistency by giving it one.
- **`README.md`** — **not** touched. Its address tables are upstream's, kept
  for merge fidelity; ROADMAP § Deliberately not planned says never to rewrite
  them.
- **`FORK_GAPS.md`** — **no entries deleted and no regeneration.** This item
  adds no member coverage: it calls members the fork already reaches and
  records what they return. `tools/lom_gaps.py` is not run.

### 4 · Blind spots and the roadmap

*Files:* `BLIND_SPOTS.md`, `ROADMAP.md`, `docs/HANDOFF_tier_2_measurement.md`

Only after the first successful run, with its numbers:

- `BLIND_SPOTS.md` blind spot 5 gains a **"Measured <date>, Live 12.4.5"**
  subsection carrying the run's counts, the set it was taken against, and the
  list of types found only through a property value — the answer it was
  written to get. It is **not** struck through: one run against one set does
  not close it. Blind spot 4's migrated half is answered in the same
  subsection.
- `ROADMAP.md` #3 keeps its entry until `/ship`, per the skill's rule. This
  plan is linked from it now.
- The handoff doc's read-half section is updated to point at the shipped tool
  rather than describing it as future work.

## Testing

`tests_unit/`, Live-free, through `conftest.py`'s `load_module`:

- **The predicate** (part 1), in full — every rule, against real Boost.Python
  signature strings taken from `FORK_GAPS.md`.
- **The walk**, over a synthetic object graph built in the test file, exactly
  as `test_introspection_walk.py` already drives `_visit_module` over synthetic
  modules. Cases: a cycle terminates; the depth bound truncates and is counted;
  a property that raises is recorded as an error and the walk continues; a
  vector's element type is recorded from the first element; two objects of the
  same type merge into one entry; two devices with different `class_name`
  values land in different entries; a listener member is recorded and **never
  called** (assert with a member that raises if called).
- **The schema**, pinned the way `test_lom_gaps.py` pins the report: one test
  asserting the top-level keys and one asserting a member record's shape, so a
  silent change to either is a failing test rather than a broken consumer.
- **`test_reload_list.py` needs no change** — no module is added to
  `abletonosc/`, so `test_every_package_module_is_reloaded_or_exempt` is
  unaffected. If implementation reverses that call, both introspection-specific
  tests must gain siblings for the new module; the reason to extend
  `introspection.py` rather than add `instance_walk.py` is precisely that this
  obligation, the package-init import and a second `SESHAT.md` entry all come
  free.

**Not covered there, and this is the limit of the gate:** none of this proves
the walk works against real LOM objects. The synthetic graph is Python objects
with the shape Live's are believed to have. `tests/` mutates a running Live and
is not part of the gate.

## Live verification

**Precondition for every check below:** the Remote Scripts copy equals this
checkout byte for byte (`diff -rq -x __pycache__` — verified clean as of
2026-08-30 apart from docs), **and** `mix abletonosc.install` completed —
it is not atomic, and an interrupted run leaves the tree missing `manager.py`
and `pythonosc/`, the last two things it copies. Verify both exist. A broken
install reports as `NameError: name 'Manager' is not defined` and nothing
more, whatever the actual cause.

Replies cannot be captured on this machine: **11001 is Seshat's**
(`beam.smp`, no `SO_REUSEPORT`). Send fire-and-forget to 11000 and read
answers out of the installed `logs/abletonosc.log`, recording its line count
first. Never bind 11001. This is `API.md` § "The no-probe variant".

| # | Send | Evidence that decides it |
|---|---|---|
| 1 | `/live/api/reload` | `logs/abletonosc.log` gains `Reloaded code` with no `error` line naming a module. A reload that fails part-way arrives as `/live/error "log", …`; a *silent* success is not evidence the edit is live, which is why check 2 exists. |
| 2 | `/live/application/dump_lom_instances` | `logs/lom_instances.json` exists, is newer than the reload, and parses. The handler's own summary line appears in the log with the four reply values. |
| 3 | *(read the file)* | `provenance.song_file_path` names the set that is actually open. `types` contains `Live.Song.Song`, `Live.Track.Track`, `Live.Device.Device/<class_name>` for at least two distinct `class_name`s. |
| 4 | *(read the file)* | `types["Live.Track.Track"].members.devices.element_types` names `Live.Device.Device` — **the item's whole point**: a property's value type, recorded from an instance, which no static walk could produce. |
| 5 | *(read the file)* | `skipped.cycle_hits > 0` — proof the `canonical_parent` guard fired rather than the graph happening to be a tree. `depth_truncations` is 0, or the bound is raised and the run repeated. `vector_truncations` may count only named note/warp-marker payload vectors; structural collections (tracks, returns, scenes, devices, chains, pads and parameters) must be traversed in full. |
| 6 | *(read the file)* | Compare the set of type keys against `lom_dump.json`'s `classes` keys. **Any type present here and absent there is the blind-spot-5 answer** and goes into `BLIND_SPOTS.md`. An empty difference is also a result, and is recorded as one. |
| 7 | *(grep the log)* | **No `Adding listener` line appears during the run.** The walk must never subscribe. Seshat's live subscriptions — tempo, signature, `is_playing`, `root_note`, `scale_name`, groove/swing, `tracks`, `return_tracks`, master mixer params — must be untouched; `metronome` is the only free one and the walk touches none of them either. |
| 8 | *(watch Live's UI)* | Live's UI does not freeze audibly or visibly during the walk. See the open question on walk duration. |

No mutating check appears in this table, because **the walk performs no
mutation** — no `begin_undo_step`/`end_undo_step` pair is needed and none is
sent. That is the item's defining safety property, not an omission.

**Afterwards:** restore the installed copy from this checkout and confirm the
address is gone (`Unknown OSC address`), then `diff -rq -x __pycache__` again.

**Uncovered:** everything the open set does not contain. A set without a drum
rack produces no `DrumPad` evidence, and the file says so through
`provenance` rather than by claiming completeness.

### Ran 2026-08-30, Live 12.4.5 — results against a 1-track unsaved set

Three runs; the first two found defects in the walker and are written up in
`BLIND_SPOTS.md`. Final run:

```
13 types, 42 objects, 647 reads, 11 calls, 43 errors, 0.018s
```

| # | verdict |
|---|---|
| 1 | **Pass.** `Reloaded code`, no error line. |
| 2 | **Pass.** `logs/lom_instances.json` written, parses, summary line carries the four reply values. |
| 3 | **Partial.** `provenance` correct (1 track, 0 returns, 8 scenes, `song_file_path` `""`). `Live.Song.Song` and `Live.Track.Track` present; **no `Live.Device.Device/<class_name>` at all** — the set holds no devices, so the `class_name` discriminator is untested against Live. Needs a denser set. |
| 4 | **Pass.** `Song.tracks` → `element_types: {"Live.Track.Track": 1}`, plus `scenes` → `Scene.Scene`, `Scene.clip_slots` → `ClipSlot.ClipSlot`, `GroovePool.grooves` → `Groove.Groove`. A property's value type, read off an instance — the thing no static walk could produce. |
| 5 | **Pass.** `cycle_hits` 52, `depth_truncations` 0. |
| 6 | **Empty difference, recorded as a result.** No type reached by the walk is absent from `lom_dump.json`. Three `View` entries differ only in key format — the class walk names a nested class by its owner (`Live.Song.Song.View`), Boost.Python's `__qualname__` is the bare `View` — and are **not** new types. A set with no devices cannot answer this question properly. |
| 7 | **Pass.** No `Adding listener` line during the run; 1,143 listener members recorded and none called. |
| 8 | **Pass.** 18–20ms, no visible or audible stall. |

### PR review 2026-08-30 22:40 EEST — skipped by environment

Live was running, but its process started at 20:51:56 while the installed
`abletonosc/application.py` and `abletonosc/introspection.py` were updated at
22:12 and 22:19 respectively. Files on disk therefore matched the checkout,
but Live had not been restarted after that copy was made. Checks 1–8 were all
**skipped by environment**: without the required restart, a wire observation
could come from stale in-memory code and would not be review evidence. No OSC
request was sent and port 11001 was not bound.

**The run's real yield: 21 measured failure contracts**, e.g.
`Track.mute` → `RuntimeError: Main track has no 'mute' property!`,
`MixerDevice.crossfader` → `Only the main track has a crossfader!`,
`DeviceParameter.value_items` → `Only quantized parameters have value items`.
Preconditions on already-shipped addresses, stated by Live and carried in no
docstring. Tabulated in `BLIND_SPOTS.md`.

**A green Live-free suite proved nothing about either defect.** Both runs 1 and
2 passed 920 tests and reported 0 errors while measuring nothing — a synthetic
object graph has an honest `__module__` and a stable `id()`, which is exactly
what Live does not.

## Downstream

**Pin bump only — and it is a claim, so here is what it rests on.**

- No existing address changes shape, name or reply arity. Seshat decodes
  nothing new.
- The new address is a **developer tool**, not consumer surface. Seshat is not
  expected to call it, now or later.
- `vendored_addresses_test` scrapes `add_handler` literals and checks each
  appears in `API.md`. The new literal therefore **requires** its `API.md` row
  in the same commit — part 3 — or the consumer's test fails on the pin bump.
  No new tripwire is needed beyond that existing mechanism.
- `logs/lom_instances.json` is a new file in the install tree. Seshat's
  install verification should be checked for a strict file-set assertion; if it
  has one, the new artefact is a companion update. ⚠️ Not verified from this
  repository.

## Out of scope

- **The write half.** 589 methods' mutation behaviour is demand-driven, one at
  a time, wrapped in `begin_undo_step`/`end_undo_step` with the set
  snapshotted. Stays in the handoff, prioritised behind `API.md`'s `⚠️`
  markers.
- **The curated "one of every device" set.** Decided 2026-08-30: the first run
  goes against the working set and the dump records which set it was. Building
  and describing a reference set is a follow-up that re-runs *this same tool*
  and needs no code. It stays on the roadmap.
- **Clearing `API.md`'s 129 `⚠️` markers.** The sweep produces evidence for
  some of them; converting evidence into corrected rows is per-address work,
  ranked behind the markers Seshat actually calls.
- **Bounding `dump_lom`'s path** (`issues.md`, Low). Adjacent and tempting,
  since this item establishes the correct pattern one function away. Left
  alone: it is a wire-contract change to a shipped address with a Seshat
  tripwire obligation, and folding it in would make this item's diff two
  changes. The new address's comment points at it.
- **Edition and version diffing.** Running the tool twice and diffing is what
  finally answers which surface is edition-gated. Bounded by licences, not by
  work; not this item.

## Open questions

1. ~~**How long does the walk take, and does it stall Live's UI?**~~
   **Closed 2026-08-30, Live 12.4.5: 18–20ms, no stall.** Measured on a
   1-track set with no devices, so it is a floor, not a ceiling —
   `provenance.walk_seconds` is recorded on every run and a denser set is what
   would move it. The mitigations shipped as planned. Original text: ⚠️ A Remote
   Script's callbacks run on Live's main thread. `dump_lom`'s class walk is
   comparable in size (545 KB output) and is not known to stall anything, but
   it performs `getattr` on *classes*; this walk performs thousands of reads
   and calls on *live objects*, and a property read can be arbitrarily
   expensive. Unmeasured, and not measurable before the tool exists.
   **Meanwhile the plan assumes** it is acceptable and mitigates rather than
   optimises: `walk_seconds` is recorded in `provenance`, the depth bound
   defaults to 8, and vectors are sampled rather than fully traversed. If
   check 8 shows a stall, the answer is a lower depth bound or chunking across
   ticks — a follow-up, not a redesign.
2. ~~**What does `Song.file_path` answer on a never-saved set?**~~
   **Closed 2026-08-30, Live 12.4.5: the empty string**, not `RuntimeError`.
   The set the walk ran against was unsaved and `provenance.song_file_path`
   came back `""`. The assumption `API.md` carried was correct and its ⚠️ is
   now a measurement. One sample, one version. Original text: ⚠️ Already
   carried as unmeasured in `API.md:900` — the assumption there is the empty
   string, with `RuntimeError` the alternative. This walk reads it under the
   same guard as every other read, so **either answer is handled** and the
   provenance block records `null` on a raise. The first run against a saved
   set does not answer it; a run against an unsaved one would, and is worth
   doing once.
3. ~~**Is the denylist really empty?**~~ **Closed by measurement 2026-08-30,
   Live 12.4.5** — see § "What may be called". No: it carries the three
   `Live.Licensing.PythonLicensingBridge` methods the predicate selects and
   this repository's policy shuts. The run also resized the sweep's method half
   from 589 to 18 and showed the arity parser handles every real Boost.Python
   docstring (`unparsed=0`). What remains open is narrower and is not blocking:
   whether calling the 15 non-denylisted methods is harmless, which only the
   first real walk tests, and whose answer arrives as that run's error map.
4. **Does Seshat's install verification assert a strict file set?** ⚠️ Not
   checkable from this repository. If it does, `logs/lom_instances.json` is a
   companion update in the same pin bump. **The plan assumes** it does not, on
   the evidence that `logs/lom_dump.json` and `logs/abletonosc.log` already
   appear there without one.
