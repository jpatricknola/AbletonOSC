# Plan: Fix base handler initialization order

Roadmap item: **#1 · Fix base handler initialization order** (source:
`issues.md`, "Fix base handler initialization order", High). No dependencies.

## Context

`AbletonOSCHandler.__init__` (`abletonosc/handler.py`) runs in this order:

```python
super().__init__()                      # ableton.v2 Component
self.logger = logging.getLogger("abletonosc")
self.manager = manager
self.osc_server = self.manager.osc_server
self.init_api()                         # ← overridable route registration
self.listener_functions = {}            # ← base invariants created AFTER it
self.listener_objects = {}
self.class_identifier = None
```

Every subclass overrides `init_api()` to register its OSC routes, and every
subclass sets `self.class_identifier` in its own `__init__` *after*
`super().__init__(manager)` returns. So during route registration:

- `self.listener_functions` / `self.listener_objects` **do not exist** —
  touching them raises `AttributeError`;
- `self.class_identifier` **does not exist either**, and anything a subclass
  set before or during `init_api()` would be clobbered back to `None` by the
  base's own trailing assignment;
- any state a subclass assigns in its `__init__` body doesn't exist yet —
  `BrowserHandler.init_api` carries an explicit workaround comment and a
  `hasattr` guard for its `_index_cache` because of exactly this, and
  `ClipHandler`'s `_clip_notes_cache` only escapes the trap because nothing
  reads it until a message arrives.

Today the bug is **latent**: research confirmed (grep over every handler) that
no `init_api()` body reads `class_identifier` or the listener dicts at
registration time — they are only read later, inside callbacks, by which time
the constructor has finished. But every callback that builds a listener push
address does it as `"/live/%s/get/%s" % (self.class_identifier, prop)`, so the
invariant the whole wire depends on is being satisfied by accident of timing,
and every gap item below this one on the roadmap adds handlers on top of the
same trap. The roadmap Goal: every handler enters route registration with
`listener_functions`, `listener_objects` and `class_identifier` already set,
and subclass-owned initialization has an explicit lifecycle.

Key facts research established (all statically verifiable, none assumed):

- **`init_api()` has exactly one call site**: the base constructor. Reload
  (`Manager.reload_imports` → `clear_api()` → `Manager.init_api()`) builds
  *fresh* handler instances; it never re-invokes `init_api()` on an existing
  one. So "state created in `init_api`" and "state created in `__init__`" have
  identical lifetimes, and `BrowserHandler`'s `hasattr` guard guards a path
  that cannot occur.
- **`class_identifier` is written only in constructors** and read only at
  message time (logging, listener push addresses). Making it a declarative
  class attribute changes no runtime read.
- **`ApplicationHandler` never sets it at all** — its `class_identifier` is
  `None` today. It registers no listeners and never calls the generic
  `_get_property`/`_set_property`, so nothing observable depends on that; but
  it violates the Goal as stated and gets an identifier like everyone else.
- **Component is safe to build on.** Verified 2026-08-27 against the shipped
  bytecode in `/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/
  MIDI Remote Scripts/ableton/v2/` (compiled for Python 3.11, decoded with
  `marshal` + `dis`, nothing executed): `Component.__init__(self, name=None,
  parent=None, register_component=None, song=None, layer=None, is_enabled=True,
  *a, **k)` — the existing no-arg `super().__init__()` stays valid — and **no
  module under `ableton/v2/` defines `init_state` or `class_identifier`**
  anywhere in its code objects, so the names introduced below collide with
  nothing in Component's inheritance chain (`Component` ← `ControlManager`,
  plus the `ableton.v2.base` event/disconnect machinery).

### The reload trap this change would spring, and its fix

`Manager.reload_imports` reloads `abletonosc.application`, `.clip`,
`.clip_slot` and `.device` **before** `abletonosc.handler`. After one
`/live/api/reload`, those four modules' classes still subclass the *old*
`AbletonOSCHandler`. Today that's harmless (old and new base are identical).
But deploy this change and reload once without restarting Live, and those four
handlers would be constructed by the **old** base `__init__`: `init_state()`
would never be called (old base doesn't know it), so `ClipHandler`'s notes
cache would be missing → `AttributeError` on the first `/live/clip/get/notes`;
worse, the old base's trailing `self.class_identifier = None` would shadow the
new class attribute → clip/clip_slot/device listener pushes would silently go
out on `/live/None/get/<prop>`. Part 3 therefore moves `osc_server` and
`handler` to the top of the reload list (handler does a `from`-import of
`OSCServer`, so its dependency reloads first), exactly the ordering fix the
list already documents for `track_callback` before `track`. The *general*
reload robustness item ("Make live code reload ordered and failure-safe",
`issues.md`, Medium-high) stays open and out of scope — this is only the two
lines needed so this change survives its own deployment.

### Design

**Decision: invariants first, then a subclass-state hook, then registration.**
The corrected base constructor:

```python
super().__init__()                      # Component
self.logger = ...
self.manager = manager
self.osc_server = manager.osc_server
self.listener_functions = {}
self.listener_objects = {}
self.init_state()                       # subclass-owned state (new hook)
self.init_api()                         # route registration
```

`init_state()` is a new overridable no-op on the base: the one documented
place for subclass instance state, guaranteed to run after every base
invariant and before any route is registered. `init_api()` may rely on
everything above it. Alternatives rejected: merely reordering the existing
lines (fixes the dicts but leaves `class_identifier = None` during
registration and leaves subclass state with no legal home — the Goal
explicitly demands an explicit lifecycle); having subclasses assign state
before `super().__init__(manager)` (works in CPython but re-creates the same
ordering trap inverted, and puts attribute writes ahead of Component's own
`__init__`).

**Decision: `class_identifier` becomes a class attribute.** Base declares
`class_identifier: Optional[str] = None`; each subclass declares its own
(`class_identifier = "track"`, …) at class level. Identity is then available
from the first line of `init_state()`/`init_api()` with no ordering hazard at
all, and every subclass `__init__` override becomes empty and is **deleted** —
the resulting lifecycle is fully declarative: identity in the class statement,
state in `init_state()`, routes in `init_api()`, teardown in `clear_api()`.
`SongStructureHandler` keeps its deliberate `class_identifier = "song"`
(shared namespace) with its existing comment. The alternative — passing the
identifier up through `super().__init__(manager, "track")` — touches every
call site for no gain and changes a constructor signature Seshat-side code
could in principle subclass.

**Decision: no behaviour change on the wire, none in logs except
`ApplicationHandler`.** Same addresses, same registration order (the
`manager.py` handler list is untouched), same `/live/startup` emission point
(inside `ApplicationHandler.init_api`), same listener push addresses — now
guaranteed rather than accidental. The only observable delta anywhere is that
a hypothetical future `ApplicationHandler` log line would say `application`
instead of `None`.

## Wire contract

**No address is added, removed, or renamed. No request or reply shape
changes.** This section exists to name what the change *relies on keeping
identical*:

- **Unchanged-but-relied-on: the full registered address set.** Every address
  in `API.md` keeps registering exactly as today; the handler list in
  `Manager.init_api` and every `init_api()` body's registration lines are
  untouched.
- **Unchanged-but-relied-on: listener push addresses.**
  `/live/<class_identifier>/get/<prop>` pushes (built at message time in
  `_start_listen`, and in the overrides in `track.py`, `device.py`,
  `return_track.py`) keep their exact addresses: the class attribute values
  are character-identical to the strings the deleted `__init__` bodies
  assigned.
- **Unchanged-but-relied-on: startup traffic.** `/live/startup` is still sent
  from `ApplicationHandler.init_api` at construction, at the same position in
  the handler list. (Its known startup-noise issue is a separate `issues.md`
  entry; untouched.)
- **Unchanged-but-relied-on: error behaviour.** Nothing in `_dispatch` or the
  error envelope changes; handler failures still surface as
  `/live/error ("request", address, detail, argc, *args)`.
- **Unchanged-but-relied-on: reload.** `/live/api/reload` still ends with a
  working API; after Part 3 it also ends with every handler on the *new* base
  in a single reload, which today's order cannot guarantee once handler.py
  changes.

## Parts

### Part 1 — base lifecycle (`abletonosc/handler.py`)

- Reorder `AbletonOSCHandler.__init__` as shown above: Component init, logger,
  `manager`, `osc_server`, `listener_functions = {}`,
  `listener_objects = {}`, then `self.init_state()`, then `self.init_api()`.
- Delete the trailing `self.class_identifier = None` instance assignment;
  declare `class_identifier: Optional[str] = None` as a class attribute.
- Add `def init_state(self): pass` with a docstring stating the contract:
  runs once per instance, after all base invariants, before `init_api()`;
  subclass instance state belongs here; route registration does not.
- Extend the class docstring/comment to state the constructor contract
  `init_api()` may now rely on (this comment is what future gap PRs read).
- **Docs, same commit:** `SESHAT.md` § "Fixes to upstream's own code" gains an
  entry — *handler.py: base invariants exist before `init_api()`* — covering
  the reorder, the class-attribute identity, the `init_state()` hook, and the
  Part 3 reload-order line move; `SESHAT.md` § "Merge hazards" gains a bullet:
  any upstream merge touching `AbletonOSCHandler.__init__` or a subclass
  `__init__` must keep invariants-first order and the class-level
  `class_identifier`s — a reverted order is invisible (everything still works
  by timing accident) until the first handler that uses the guarantee.
  No `API.md` rows (no address or shape changes) and no `FORK_GAPS.md` edit
  (defect fix, not a gap closure; inventory unaffected).

### Part 2 — subclasses (all handler modules)

For each of `song.py`, `clip.py`, `clip_slot.py`, `track.py`, `device.py`,
`scene.py`, `view.py`, `midimap.py`, `browser.py`, `return_track.py`,
`song_structure.py`:

- Move the `class_identifier` string to a class attribute; delete the
  now-empty `__init__` override.
- `application.py`: add `class_identifier = "application"` (new — it was
  `None`; no listeners or generic property paths exist there, so no wire or
  log delta today).
- `clip.py`: move `self._clip_notes_cache = []` into `init_state()`.
- `midimap.py`: move `self.midi_map_handle = None` into `init_state()` — its
  `__init__` is *not* empty after the identifier moves. The attribute is
  assigned and never read anywhere in this repository, but it is
  upstream-visible state; preserve it rather than judge it vestigial in this
  item.
- `browser.py`: move `self._index_cache = {}` into `init_state()`, drop the
  `hasattr` guard, and replace the workaround comment ("init_api() is called
  from AbletonOSCHandler.__init__, so it must not depend on anything assigned
  in our own __init__ body") with one sentence pointing at the base lifecycle
  contract. The startup stale-export sweep stays in `init_api()` (it is
  registration-adjacent behaviour, not state).
- `song.py`: move `self.last_song_time = -1.0` into `init_state()`; the beat
  listener registration itself stays in `init_api()` beside the rest of the
  song listeners, and `clear_api()`'s removal path is untouched.
- `song_structure.py`: class attribute `class_identifier = "song"` keeps its
  shared-namespace comment.
- The fork's method overrides (`track.py`'s `_set_property`/`_get_property`/
  `_start_listen`, `device.py`'s and `return_track.py`'s listener overrides)
  are untouched — they read `class_identifier` and the listener dicts at
  message time only.

### Part 3 — reload order (`manager.py`)

- In `reload_imports`, move `importlib.reload(abletonosc.osc_server)` and
  `importlib.reload(abletonosc.handler)` to the **top** of the list (osc_server
  first — handler.py `from`-imports `OSCServer`), with a comment mirroring the
  existing `track_callback`-before-`track` note: *base before subclass modules,
  so one reload never constructs handlers on a stale base*. Everything else in
  the list keeps its current relative order.
- **Docs, same commit:** covered by the Part 1 `SESHAT.md` entry
  (`reload_imports` is already a named merge hazard; the entry notes the two
  moved lines).

### Part 4 — Live-free lifecycle tests (`tests_unit/`)

- `tests_unit/conftest.py` gains `load_handler_module()`: installs a minimal
  synthetic `ableton.v2.control_surface.component` module chain in
  `sys.modules` (a `Component` class whose `__init__` accepts and ignores
  anything) and then loads the **real** `abletonosc.handler` under the
  existing synthetic root. This is the first stub in tests_unit; the conftest
  docstring's "no Live stubs" sentence gets amended to name the one narrow
  exception and why it is safe (handler.py's only Live-side dependency is a
  trivial base class; `osc_server.py` remains stub-free). The stub is
  process-global for the pytest run but shadows nothing importable outside
  Live.
- New `tests_unit/test_handler_lifecycle.py`, driving the real
  `AbletonOSCHandler` with a fake one-attribute manager (`.osc_server` = the
  real `OSCServer` from the existing `server` fixture):
  1. **Invariants precede registration** — a probe subclass snapshots, inside
     `init_api()`, the presence and values of `listener_functions` (`{}`),
     `listener_objects` (`{}`), `class_identifier` (the subclass's value, not
     `None`), `osc_server`, `manager`, `logger`.
  2. **Hook ordering** — an event list proves `init_state()` runs after base
     invariants exist and strictly before `init_api()`.
  3. **Registration works end-to-end** — the probe registers an address in
     `init_api()` built from `self.class_identifier`; the conftest `dispatch`
     helper sends to it; the reply arrives at the receiver (real dispatcher, real
     base class, first time this pairing is testable outside Live).
  4. **Listener bookkeeping** — against a fake target exposing
     `add_x_listener`/`remove_x_listener`: `_start_listen` fires the immediate
     push on `/live/<id>/get/x` and records both dicts; `_stop_listen` unbinds
     and clears them; `_clear_listeners` empties everything; the
     stored-object unbind (the fork's `_stop_listen` fix) unbinds from the
     recorded object, not the handed one.

  These pin the lifecycle *contract*; they do not construct the production
  subclasses (those import `Live` at module scope — making them importable
  Live-free is roadmap item "Make the test suite safe…", not this one).

## Testing

- Gate: `python3 -m pytest tests_unit/` — the whole existing suite (dispatch,
  envelope, track_callback, import smoke) must stay green untouched, plus the
  new `test_handler_lifecycle.py` above. The existing tests are the net the
  planner notes name: they prove `_dispatch`, the error envelope and the
  wildcard fan-out don't move.
- Not covered Live-free, by design: construction of the twelve production
  handlers against real LOM objects; `Manager.reload_imports` (imports
  `ableton.v2.control_surface.ControlSurface` — the reload half stays
  untestable until the test-suite item, exactly as the roadmap entry says).
- `tests/` mutates a running Live on import and is not part of the gate.

## Live verification

Precondition for every check: the Remote Scripts copy equals this checkout
byte for byte, and Live has been restarted since it was copied. Method:
`API.md` § "The no-probe variant" (fire-and-forget UDP in, evidence out of
`logs/abletonosc.log`).

1. **All handlers constructed and registered** — send `/live/test` (expect
   `Received OSC OK` in Live's status bar / `/live/test` reply logged), then
   one getter per handler: `/live/application/get/version`,
   `/live/song/get/tempo`, `/live/track/get/name 0`,
   `/live/clip_slot/get/has_clip 0 0`, `/live/scene/get/name 0`,
   `/live/view/get/selected_track`, `/live/device/get/name 0 0`,
   `/live/browser/get/items nonsense` (expect the error-shaped reply naming
   valid categories), `/live/return_track/get/count`,
   `/live/song/get/track_names`. Evidence: each request's reply/handling line
   in `logs/abletonosc.log`, with `Getting property for <identifier>:` lines
   showing the real identifier, never `None`.
2. **Listener lifecycle** — `/live/song/start_listen/tempo`: expect the
   immediate push line for `/live/song/get/tempo`; `/live/song/stop_listen/tempo`:
   expect the "Removing listener" line and no further pushes. Proves the
   dicts-before-registration order holds where listeners actually bind.
3. **Reload survives the new ordering** — `/live/api/reload`, expect
   `Reloaded code` in the log with no traceback, then repeat checks 1–2.
   Specifically re-check a handler whose module reloads *early*
   (`/live/clip_slot/get/has_clip 0 0`) and confirm its log line still says
   `clip_slot`, not `None` — that line is exactly where the mixed-base trap
   would surface.
4. **Startup notification unchanged** — after a Live restart with the new
   copy installed, the log/first traffic still shows `/live/startup` sent
   once from application handler construction.

No mutating checks are needed: the change registers no setter and alters no
setter path. Remains uncovered: nothing wire-visible; internal Component
interactions under Live are exercised implicitly by every check above.

## Downstream

**Pin bump only.** No address, shape, or timing changes; Seshat's
`vendored_addresses_test` set is untouched and needs no new tripwire. (If
Seshat ever subclasses a handler — nothing in `SESHAT.md` says it does — the
new contract is strictly more permissive: state available earlier, an explicit
`init_state()` hook to override instead of `__init__` juggling.)

## Out of scope

- **General reload robustness** — partial-failure semantics, the
  reload-then-clear-then-init sequencing, old handler instances never being
  disconnected: stays in `issues.md` ("Make live code reload ordered and
  failure-safe"). Part 3 takes only the two-line ordering move this change
  itself requires.
- **Startup `average_process_usage` noise** — separate `issues.md` entry,
  untouched.
- **Making production handler modules importable Live-free** (stubbing
  `Live`) — roadmap item "Make the test suite safe, isolated, and usable as a
  regression gate".
- **`/live/api/reload` re-invoking `init_api` on live instances** — no such
  path exists today and none is added.

## Open questions

None. The two questions research raised were both closed statically on
2026-08-27 against the shipped bytecode of Live 12 Suite (Python 3.11 pycs
under `MIDI Remote Scripts/ableton/v2/`, decoded with `marshal`, nothing
executed): (1) `Component.__init__` accepts the existing no-arg
`super().__init__()` call unchanged; (2) no name in the `ableton.v2` package
collides with `init_state` or a class-level `class_identifier`. Live was
running throughout planning but no probe was needed — every remaining risk is
either statically checked above or explicitly deferred to the Live
verification list.
