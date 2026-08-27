**Archived 2026-08-27 — shipped.** This is the plan as written *before*
implementation; the code as merged may differ. The change lives in
`tests_unit/test_handler_subclass_contract.py` (a new, pure-`ast` Live-free
test pinning every production handler's `class_identifier` and the
no-`__init__`/no-shadowing invariants) plus updates to `SESHAT.md`'s
merge-hazards section and `tests_unit/test_handler_lifecycle.py`'s
docstring; no `API.md` rows (no address or shape change). No follow-ups were
opened.

# Plan: Verify handler `class_identifier` and lifecycle invariants without Live

Roadmap item: **Verify handler `class_identifier` and lifecycle invariants
without Live** (source: pr-review of "Fix base handler initialization order",
`docs/archive/PLAN_base_handler_init_order.md`, nits 2 and 3). No dependencies.

## Context

The "Fix base handler initialization order" ship moved handler identity to a
class attribute: `AbletonOSCHandler` declares `class_identifier:
Optional[str] = None`, every subclass overrides it in its class statement, and
all subclass `__init__` overrides were deleted so the base's documented
constructor order (`Component.__init__` → invariants → `init_state()` →
`init_api()`) is the only constructor that runs. Listener pushes go out on
`/live/<class_identifier>/get/<prop>`, so that attribute *is* wire identity.

The test suite pins only half of this. `tests_unit/test_handler_lifecycle.py`
constructs the real `AbletonOSCHandler` (via `conftest.load_handler_module()`'s
one-class `ableton.v2` stub) and drives local `Probe` subclasses through it, so
a revert of the **base** constructor fails loudly. But the **production
subclasses** are never touched: five of the twelve (`application.py`,
`browser.py`, `clip.py`, `song.py`, `view.py`) do `import Live` at module
scope and cannot be imported Live-free at all; the other seven share
`device.py`'s stub-free import profile, but only `device.py` is actually
loaded and exercised today (`test_device_listeners.py`). Any
construction-based route therefore stops short of those five without a Live
stub, and covers none of the rest as things stand.
Consequences, as SESHAT.md's merge-hazard bullet for
`AbletonOSCHandler.__init__` spells out:

- A typo'd or copy-pasted identifier (`class_identifier = "clip_slot"` on the
  wrong handler) passes every test green. Nothing reads the attribute at
  registration time; it surfaces later as listener pushes on the wrong
  address, silently.
- A merge that restores a subclass `__init__` assigning
  `self.class_identifier` — upstream's shape — also passes green. The
  instance attribute shadows the class attribute *after* `init_api()` ran,
  recreating exactly the ordering hazard the shipped fix removed, invisible
  until the next handler that relies on the guarantee.

The hazard note currently ends "check subclasses by eye … until a Live-free
test covers them too". This item is that test.

### What research changed about the obvious approach

- **No construction, no imports — `ast` only.** The planner note already
  settles this, and research confirms it is the *only* Live-free route:
  `browser.py`, `view.py` and others do `import Live` at module scope, and
  widening conftest's stub surface to make them importable would be a far
  bigger (and riskier) change than this item warrants. Parsing source text
  reaches all twelve subclasses with zero stubs.
- **Every subclass names the base directly.** All twelve class statements are
  `class XHandler(AbletonOSCHandler)` with `from .handler import
  AbletonOSCHandler` — no aliases, no attribute-style bases, no intermediate
  handler subclasses today. The test should still resolve inheritance
  transitively over class names collected from all `abletonosc/*.py` files
  (about ten lines), so a future `class FooHandler(TrackHandler)` is subject
  to the same invariants instead of silently escaping the walk.
- **Two identifier/prefix pairings are deliberate and must be encoded, not
  "fixed".** `SongStructureHandler` declares `class_identifier = "song"` —
  its listeners push on `/live/song/get/...`, sharing `SongHandler`'s
  namespace (the class body carries a comment saying so; SESHAT.md documents
  it). And `ReturnTrackHandler` (`"return_track"`) registers both
  `/live/return_track/*` and `/live/master/*` addresses — the master
  addresses are hand-built strings, not identifier-derived. The expected map
  in the test needs comments on both rows so a future editor doesn't
  "correct" them.
- **The invariant to check is broader than `def __init__`.** The merge hazard
  is any assignment to `self.class_identifier`, wherever it lands — a
  restored `__init__` is the likely vehicle, but the same line pasted into
  `init_state()` shadows identity just as well (before `init_api()`, so even
  more quietly). The AST walk should reject the assignment anywhere in a
  subclass body, plus `def __init__` itself as the convention violation.
- **Two docs currently describe this gap as open** and must be updated in the
  same commit: SESHAT.md's merge-hazard bullet ("check subclasses by eye…",
  explicitly flagged by the roadmap entry) and
  `test_handler_lifecycle.py`'s docstring ("Most production subclasses …
  are still out of reach … so the probes below stand in for them").

## Wire contract

No address is added, changed, or removed; no request or reply shape changes;
no `/live/error` behaviour changes. This item is a test plus documentation.

**Unchanged-but-relied-on:** the per-handler identifier map below. Each
identifier is the `<class_identifier>` half of that handler's
`/live/<class_identifier>/get/<prop>` listener-push addresses and log lines;
the test pins it so the wire namespaces cannot drift silently. This table is
the expected map the test encodes:

| Module (`abletonosc/`) | Class | `class_identifier` |
|---|---|---|
| `application.py` | `ApplicationHandler` | `application` |
| `browser.py` | `BrowserHandler` | `browser` |
| `clip.py` | `ClipHandler` | `clip` |
| `clip_slot.py` | `ClipSlotHandler` | `clip_slot` |
| `device.py` | `DeviceHandler` | `device` |
| `midimap.py` | `MidiMapHandler` | `midimap` |
| `return_track.py` | `ReturnTrackHandler` | `return_track` |
| `scene.py` | `SceneHandler` | `scene` |
| `song.py` | `SongHandler` | `song` |
| `song_structure.py` | `SongStructureHandler` | `song` |
| `track.py` | `TrackHandler` | `track` |
| `view.py` | `ViewHandler` | `view` |

Deliberate irregularities the test must encode with comments:
- `SongStructureHandler` → `"song"`: shares `SongHandler`'s push namespace on
  purpose (its listeners push `/live/song/get/...`).
- `ReturnTrackHandler` → `"return_track"`: additionally registers
  `/live/master/*` addresses as hand-built strings; the identifier governs
  only its log lines and any identifier-derived pushes, and the map is *not*
  a claim that one handler owns exactly one `/live/<x>/` prefix.

## Parts

### Part 1 — AST-based subclass contract test (`tests_unit/test_handler_subclass_contract.py`, new file)

One new test module, no fixtures, no imports from `conftest` beyond computing
the repo root the same way (`Path(__file__).resolve().parent.parent`). It
must not import anything from `abletonosc/` — parsing only.

Discovery:
- Parse every `abletonosc/*.py` with `ast.parse` (`constants.py`,
  `osc_server.py`, `track_callback.py`, `track_identity.py`,
  `introspection.py`, `__init__.py`, `handler.py` simply contribute no
  handler subclasses; `handler.py` contributes the root name).
- Collect every `ast.ClassDef` with its base names (handle both `ast.Name`
  and `ast.Attribute` bases, keyed on the terminal identifier) across all
  files, then compute the transitive closure of names reachable from
  `AbletonOSCHandler`. The classes in that closure, minus the base itself,
  are the handler subclasses under test.

Checks (each its own test function, so a failure names the invariant):

1. **The discovered set equals the expected map — both directions.** The map
   is `{("<module>.py", "<ClassName>"): "<identifier>"}` exactly as in the
   Wire contract table, with comments on the `song_structure.py` and
   `return_track.py` rows. A new handler module fails until its row is added
   (deliberate tripwire); a removed or renamed one fails the other way.
2. **Each subclass declares `class_identifier` at class-body level, exactly
   once, as a plain string constant, matching the map.** Accept `ast.Assign`
   and `ast.AnnAssign` (the base uses the annotated form), require the value
   to be an `ast.Constant` whose value is a `str` — an identifier computed at
   runtime would defeat static verification, and none exists today.
3. **No subclass defines `__init__`** (`ast.FunctionDef` or
   `ast.AsyncFunctionDef` named `__init__` anywhere in the class body). The
   base's docstring is explicit that `init_state()` is the one home for
   subclass instance state.
4. **No subclass method assigns `self.class_identifier`.** Walk each
   subclass body for `ast.Assign`/`ast.AnnAssign`/`ast.AugAssign` whose
   target is `ast.Attribute(value=ast.Name(id='self'),
   attr='class_identifier')`. This is the actual merge hazard — catching it
   in `init_state()` or any helper, not just in a restored `__init__`.

Failure messages must name the file, class, and expected-vs-found value —
this test exists to be read at 2am after a bad upstream merge.

During development (not committed), verify the test actually fails under each
mutation it claims to catch: typo one identifier, add a `def __init__` to one
subclass, add a `self.class_identifier = ...` line to one `init_state()`.
Also confirm the discovery count is exactly twelve — an empty or short walk
passing vacuously is this test's own failure mode, and check 1's two-way set
equality is what guards it.

### Part 2 — retire the "uncovered" language, same commit

- **`SESHAT.md`**, merge-hazards bullet "Anything touching
  `AbletonOSCHandler.__init__`, a subclass's class-level `class_identifier`,
  or `init_state()`" (§ Merge hazards): replace the closing "It does **not**
  catch the subclass half … check subclasses by eye for the other until a
  Live-free test covers them too" with a pointer to
  `tests_unit/test_handler_subclass_contract.py` — the subclass half now
  fails the suite: a restored subclass `__init__`, a dropped or typo'd class
  attribute, and any `self.class_identifier` assignment are all caught
  statically. Keep the surrounding description of *why* the revert is
  invisible in Live — that is what makes the hazard worth listing.
- **`SESHAT.md`**, fixes-section paragraph for the constructor ordering
  (the sentence "`tests_unit/test_handler_lifecycle.py` constructs the *real*
  `AbletonOSCHandler` outside Live …"): append a sentence that the subclass
  declarations are pinned by `test_handler_subclass_contract.py`.
- **`tests_unit/test_handler_lifecycle.py`** module docstring: after "the
  probes below stand in for them (device.py is the exception …)", note that
  the production subclasses' *declarations* — identifier map, no `__init__`
  — are covered statically by `test_handler_subclass_contract.py`.

Documentation obligations not triggered, stated for completeness: no `API.md`
rows (no address or shape changes); no `FORK_GAPS.md` deletion or inventory
regeneration (not a LOM gap); the SESHAT.md edits above are this change's
divergence record (a fork-only test file plus fork-doc updates — no upstream
file is modified). The source write-up this item cites is the archive banner
of `docs/archive/PLAN_base_handler_init_order.md`, whose "lives on as
ROADMAP.md's …" sentence gets rewritten at `/ship` time when the roadmap
entry is deleted, per the ship skill — not in this change.

## Testing

`python3 -m pytest tests_unit/` remains the only gate (127 passing at
baseline, on `master` at the time of writing). The new file adds pure-AST
tests: no sockets, no stubs, no Live, no construction of any handler — it
runs identically with or without Live installed. It complements, not
replaces, the behavioural layers:

- `test_handler_lifecycle.py` keeps pinning the *base* constructor order and
  listener bookkeeping by construction (local probes).
- `test_device_listeners.py` keeps driving the one production subclass
  currently loaded and exercised end to end (`device.py`).
- The new file pins the *declarations* of all twelve production subclasses —
  identifier values and the no-`__init__` / no-shadowing convention — which
  no amount of probe construction can reach.

Explicitly not covered, as always: handler code against real LOM objects
(`tests_unit/` never talks to Live), and `tests/` (mutates a running Live on
import; not part of the gate).

## Live verification

None. Nothing in this change alters the installed bridge's behaviour — no
handler code, no address, no reply shape is touched, and the test asserts
properties of source text, not of a running Live. There is no check that only
a running Live could decide, so the "Measuring the Live API…" rig stays cold
for this item.

## Downstream

**Pin bump only** — and even that is inert. No address, shape, or behaviour
changes; Seshat's `vendored_addresses_test` greps the same names it did
before and is unaffected. The next routine submodule pin picks this up with
no decoding change and no new tripwire.

## Out of scope

- Making `browser.py`, `song.py`, `view.py`, `clip.py` and `application.py`
  importable without Live (stub surface for `import Live`), or loading the
  remaining stub-free modules (`track.py`, `scene.py`, …) the way
  `test_device_listeners.py` loads `device.py`, so their handlers could be
  constructed in tests. Separate, larger decision; the declaration-level
  checks here are what the roadmap item asks for. Runtime coverage of
  production subclasses stays where it is (`device.py` only).
- Listener-identity normalization in `scene.py` / `clip.py` /
  `clip_slot.py` / `device.py`'s property pair — roadmap item "Normalize
  listener argument identity…", already ranked.
- Reload robustness, including the `midimap` never-reloaded gap noted in
  `manager.py` — roadmap item "Make live code reload ordered and
  failure-safe".
- Any enforcement that registered address strings match the identifier
  (e.g. walking `add_handler` literals): `ReturnTrackHandler`'s `/live/master`
  and hand-built formatted addresses make prefix-lint noisy and low-value;
  `API.md` plus Seshat's tripwire own address inventory.

## Open questions

None. The two candidate design questions were closable at planning time and
are decided above with reasoning recorded: (a) discovery follows transitive
subclassing over collected class names rather than direct bases only —
trivially more code, closes the escape hatch; (b) a legitimate future
subclass `__init__` has no sanctioned path — the base docstring names
`init_state()` as the home for subclass state, and a future exception would
edit the test alongside the base-class contract, visibly. No question in this
item requires a running Live.
