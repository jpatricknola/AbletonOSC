# Plan: Application dialogs and versions (C-3)

Roadmap item: **#1 · C-3 · Application dialogs and versions** — from
`CLOSING_THE_GAPS.md` row C-3, closing the FORK_GAPS curated entry
"`Application` dialog members" and most of the
`Live.Application.Application` inventory rows. Folds in the `issues.md`
bug "Remove the unsolicited average-process-usage startup datagram".
Planned 2026-08-29.

## Context

`abletonosc/application.py` registers three addresses today —
`/live/application/get/version`, `/live/application/get/average_process_usage`
and the fork's `/live/application/dump_lom` — out of a
`Live.Application.Application` class with 21 members. The 16-member gap
includes the one surface the July 2026 audit ranked High and tiny: the
dialog reads. `open_dialog_count`, `current_dialog_message` and
`current_dialog_button_count` let a client detect and describe a blocking
Live dialog without accessibility APIs or pixel scraping — the audit
recorded "dialog detection needs AX" as a false Live limitation, kept
alive only by this fork gap. The named consumer is any Seshat command that
can raise a dialog (Stem Separation's mode chooser is the recorded
example).

The same PR carries the rest of the small application-level surface: the
exact version identity (`get_bugfix_version`, `get_build_id`,
`get_variant`, `get_version_string` — today a client knows "12.4" but not
"12.4.3", the build, or Suite-vs-Standard), `has_option` (Options.txt
queries), `peak_process_usage` (the CPU companion to the existing
average), `unavailable_features`, `number_of_push_apps_running`, the two
message methods (`show_message`, `show_on_the_fly_message`) and
`control_surfaces` **names only** — the audit noted the object list has
little value to Seshat, so the reply is the class names, nothing
traversable.

**Deliberately excluded, already settled:** `press_current_dialog_button`
stays out unless a separately reviewed, non-file use case proves it safe —
a current dialog may guard unsaved work. This is the roadmap entry's own
constraint and the FORK_GAPS disposition; it is not revisited here.
`get_document` needs no address (`self.song` *is* the document; the
inventory's "Reached under another address" list already carries `view`
and `browser`).

Two constraints research surfaced:

1. **The folded-in bug.** `ApplicationHandler.init_api`'s last line sends
   an argument-less `/live/application/get/average_process_usage` datagram
   at startup that nothing requested (`abletonosc/application.py`, final
   statement). It reaches the client looking like a malformed getter reply.
   `API.md`'s row for the address documents it with a ⚠️ ("a stray sibling
   of `/live/startup`... ignore it"). This PR deletes the send; the
   `/live/startup` notification stays. The line is upstream's, so the
   removal is a divergence `SESHAT.md` must record.
2. **Testability decides the module's structure.** The roadmap entry asks
   whether `Application` gets the generic property loop or stays
   hand-rolled. It gets the loop — five of the new members are plain
   scalars — but the target object has to come from
   `Live.Application.get_application()`, and `tests_unit/` imports
   application.py over the *empty* `Live` stub (no behaviour, by
   conftest.py's design). So the handler resolves the application through
   a one-line module seam, `get_application()`, called at `init_api` time;
   tests monkeypatch the seam with a fake before constructing the
   handler, exactly parallel to how `bind_song()` supplies `self.song`.
   Resolving at `init_api` time is safe in production: handlers are
   constructed inside `ControlSurface`'s component guard with Live fully
   up, and ableton.v2's own components call
   `Live.Application.get_application()` during construction.

The Live-side facts below come from the FORK_GAPS generated inventory
(`/live/application/dump_lom` against Live 12.4.3): member kinds,
observability (presence of `add_<x>_listener`), and Boost signatures. A
planned probe run against the running Live (API.md § "Measuring the Live
API without building the feature first") was blocked by the environment's
permission system, so the element-type and semantics questions it would
have closed are carried in **Open questions** with the assumption the
implementation codes to.

## Wire contract

All addresses live under `/live/application/`. No setters exist in this
item, no existing reply changes shape, and every failure surfaces as the
structured `/live/error ("request", address, detail, argc, *args)`
envelope via `OSCServer._dispatch`. None of the new addresses take a
wildcard or an index.

### New — generic-loop scalars

| Address | Request | Reply | Notes |
|---|---|---|---|
| `/live/application/get/open_dialog_count` | — | `count: int` | 0 when no dialog is open |
| `/live/application/get/current_dialog_message` | — | `message: str` | Text of the last dialog; empty once dialogs are gone |
| `/live/application/get/current_dialog_button_count` | — | `count: int` | Buttons on the current dialog |
| `/live/application/get/peak_process_usage` | — | `usage: float` | Peak CPU companion to the existing `average_process_usage` |
| `/live/application/get/number_of_push_apps_running` | — | `count: int` | Connected Push apps |

### New — listen pairs (observable members only)

| Address | Request | Push | Notes |
|---|---|---|---|
| `/live/application/start_listen/open_dialog_count` | — | `/live/application/get/open_dialog_count count` | Immediate initial push, then on every change (base `_start_listen` contract). The dialog-detection pattern: listen here, and on a change read `current_dialog_message` / `current_dialog_button_count` — those two are **not** observable in the LOM, so there is no listen pair for them. A `start_listen` sent to them anyway is an *unknown address*: dropped with a log line, no `/live/error` (see Part 2) |
| `/live/application/stop_listen/open_dialog_count` | — | — | |
| `/live/application/start_listen/peak_process_usage` | — | `/live/application/get/peak_process_usage usage` | |
| `/live/application/stop_listen/peak_process_usage` | — | — | |

`unavailable_features` and `control_surfaces` are also observable in the
LOM but get no listen pair: both are session-static in practice (edition
and preferences), and their pushes would need custom flattening getters.
Get-only now; a listen pair is a five-line follow-up if a consumer
appears.

### New — hand-written reads

| Address | Request | Reply | Notes |
|---|---|---|---|
| `/live/application/get/bugfix_version` | — | `bugfix: int` | `app.get_bugfix_version()`; the `.3` of `12.4.3` |
| `/live/application/get/build_id` | — | `build_id: str` | `app.get_build_id()` |
| `/live/application/get/variant` | — | `variant: str` | `app.get_variant()`; edition, e.g. `"Suite"` ⚠️ exact string unmeasured |
| `/live/application/get/version_string` | — | `version: str` | `app.get_version_string()` |
| `/live/application/get/has_option` | `option: str` | `option: str, present: bool` | `app.has_option(str(params[0]))`; echoes the option so bursts correlate. Options.txt semantics ⚠️ unmeasured — the string is passed through verbatim |
| `/live/application/get/unavailable_features` | — | `feature: str, ...` (flat, possibly empty) | Each element coerced with `str()` ⚠️ element type unmeasured. Flat like `available_input_routing_types`, no count prefix |
| `/live/application/get/control_surfaces` | — | `name: str, ...` (flat, one per preferences slot) | `type(cs).__name__` per slot, `""` for an empty slot ⚠️ empty-slot representation unmeasured. Names only, by design — the objects are deliberately not traversable from the wire |

### New — methods with a reply

| Address | Request | Reply | Notes |
|---|---|---|---|
| `/live/application/show_message` | `text: str` | `result: int` | `app.show_message(str(params[0]))` — Live defaults for every other parameter, so the dialog is **OK-only**: since `press_current_dialog_button` is deliberately unexposed, the bridge must never raise a remote dialog with choices the remote cannot make. ⚠️ blocking behaviour and the meaning of the returned int are unmeasured; the int is passed through opaquely |
| `/live/application/show_on_the_fly_message` | `text: str` | `result: int` | Same shape, same defaults ⚠️ display surface without a Push connected is unmeasured |

### Changed

| Address | Change |
|---|---|
| `/live/application/get/average_process_usage` | Query/reply behaviour unchanged. The **unsolicited argument-less datagram** sent on this address at every `init_api` is removed; startup traffic is `/live/startup` alone. The ⚠️ note in its `API.md` row comes off, replaced by one line recording the removal |

### Unchanged but relied on

`/live/startup` (still sent from `init_api`, same position),
`/live/application/get/version`, `/live/application/dump_lom`, and the
`/live/error` envelope.

## Numbered parts

### Part 1 — `abletonosc/application.py`: the addresses

- Add the module seam directly under the imports:
  `def get_application(): return Live.Application.get_application()`
  with a comment saying it exists so `tests_unit/` can substitute a fake
  (the application-object image of conftest's `bind_song()`).
- In `init_api`, leave the upstream `get_version` and
  `get_average_process_usage` callbacks byte-identical, **delete the
  final `self.osc_server.send("/live/application/get/average_process_usage")`
  line**, and keep `/live/startup` where it is.
- Below the upstream block, resolve `application = get_application()`
  once and register:
  - the generic loop: `properties_r = ["open_dialog_count",
    "current_dialog_message", "current_dialog_button_count",
    "peak_process_usage", "number_of_push_apps_running"]` →
    `get/<prop>` via `partial(self._get_property, application, prop)`;
    `properties_listen = ["open_dialog_count", "peak_process_usage"]` →
    `start_listen/<prop>` / `stop_listen/<prop>` via
    `partial(self._start_listen / _stop_listen, application, prop)`.
    Two lists, not one — registering listen on the non-observable dialog
    members would only manufacture `/live/error AttributeError`s.
  - hand-written callbacks for the four version reads, `has_option`,
    `unavailable_features`, `control_surfaces`, `show_message`,
    `show_on_the_fly_message`, per the wire contract above (flattening
    exactly as specified; `show_*` called with `str(params[0])` only).
- **`API.md`** (same commit): add every new row to the "Application API"
  table, reword the `average_process_usage` row, and add a short
  "Detecting dialogs" paragraph documenting the
  listen-count-then-read-message pattern and that the two `current_dialog_*`
  members are not observable (a `start_listen` sent to them is dropped as
  an unknown address — no `/live/error` comes back). Keep the ⚠️ markers
  from the wire contract on the unmeasured cells until Part 4's checks run.
- **`SESHAT.md`** (same commit): two entries, not one. Extend
  § "Additions to upstream's code" with an `application.py` entry — the
  new addresses and the seam (with the merge hazard: an upstream merge
  that takes upstream's `application.py` silently restores the stray
  send and deletes every address in this item — the tripwire is
  `tests_unit/test_application.py` from Part 2). The **startup-datagram
  removal goes under § "Fixes to upstream's own code"** — it is a defect
  fix (`issues.md` files it as malformed unsolicited traffic), not an
  extension, and § "Deliberate changes to upstream's behaviour" declares
  itself security-only; cross-reference the Additions entry's merge
  hazard rather than repeating it.
- **`tools/lom_gaps.py`** (same commit): extend
  `ALIASES["Live.Application.Application"]` with
  `get_bugfix_version` / `get_build_id` / `get_variant` /
  `get_version_string` → their `get/<name>` addresses (the tool's
  segment-equality rule would otherwise keep counting them as gaps).

### Part 2 — `tests_unit/`: loader and coverage

- `tests_unit/conftest.py`: add `load_application_module()`
  (`load_handler_module()` + `_install_empty_live_stub()` +
  `load_module("abletonosc.application")` — application.py's module-scope
  needs are `Live`, `os`, `typing`, `.handler`, all satisfied). Update the
  module docstring's loader inventory ("Seven of the twelve" → eight;
  remove application.py from the no-loader list; note that its tests
  substitute the `get_application` seam rather than giving the Live stub
  behaviour, keeping the "empty Live stub" rule intact).
- New `tests_unit/test_application.py`, driven through the `server` /
  `receiver` fixtures and `dispatch()`, with a local `FakeApplication`
  (scalars, a `has_option` recording its argument, fake
  `add/remove_<x>_listener` for the two observable members, list-valued
  `unavailable_features` / `control_surfaces` including a `None` slot,
  `show_message` / `show_on_the_fly_message` recording call args and
  returning an int). Cases:
  - construction (with the seam monkeypatched) sends `/live/startup` and
    **nothing else** — the regression test for the removed datagram;
  - each generic `get/<prop>` replies `(value,)`;
  - the four version reads, `has_option` echo, and both flattened reads
    (including `None` slot → `""` and empty-list → empty reply);
  - `show_message` calls the fake with exactly one positional argument
    and replies with the returned int;
  - `start_listen/open_dialog_count`: listener registered on the fake,
    immediate initial push on `/live/application/get/open_dialog_count`,
    push on simulated change, `stop_listen` unbinds, `clear_api()` clears
    bookkeeping;
  - dispatching `get/has_option` with no arguments produces the
    documented `/live/error` envelope (`IndexError` from `params[0]`,
    caught by `OSCServer._dispatch`);
  - dispatching `start_listen/current_dialog_message` (deliberately
    unregistered) sends **nothing** — `OSCServer.process_message` drops
    an unknown address with only an "Unknown OSC address" log line, no
    `/live/error` datagram (`osc_server.py`, the final `else` of
    `process_message`). The test asserts the receiver saw no datagram;
    do not expect an error reply there.
- Update the two test-file docstrings that enumerate which handlers have
  loaders (`tests_unit/test_handler_lifecycle.py`,
  `tests_unit/test_handler_subclass_contract.py`), and the matching
  sentence in `SESHAT.md`'s merge-hazards section ("constructs seven of
  the twelve production handlers... but not `application.py`").
- `tests/test_application.py` (live suite, not the gate): add read-only
  assertions for `get/version_string` and `get/open_dialog_count == 0`,
  guarded by the existing opt-in fixture. No dialog-raising test.

### Part 3 — `FORK_GAPS.md`: closure

- Move the curated section "### `Application` dialog members" to § Closed
  as "Application dialogs and versions — closed <date>" in the style of
  the existing closed entries: what the gap was, the members closed, and
  what deliberately remains open (`press_current_dialog_button`, with the
  unsaved-work rationale; `get_document`, reached as `self.song`;
  `Application.View` members, which are C-2's).
- Mark the Dispositions row "High | `Application.open_dialog_count`, ..."
  **Landed**, pointing at the closed entry, and update the false-gap row
  "Dialog detection needs AX" to say the fork surface now exists.
- Inventory: regenerate with `tools/lom_gaps.py` **if** a `dump_lom` from
  a Live running the installed post-change copy is available; if not
  (this lifecycle cannot install), add the same "no dump has been taken
  since this landed" sentence the earlier closures carry, so the
  `Live.Application.Application` row's counts are known-stale rather than
  wrong-looking.
- `CLOSING_THE_GAPS.md` row C-3 and the `issues.md` datagram entry are
  **not** touched here — `/ship` strikes the row and removes the entry,
  per the roadmap.

### Part 4 — Live verification results into `API.md`

A commit obligation, not code: whatever the Live checks below measure
(`variant` string, `unavailable_features` element type, `control_surfaces`
slot behaviour, `show_message` blocking/return semantics, `has_option`
semantics) lands in `API.md` beside the existing dated measurement blocks,
stamped with the Live version, and the ⚠️ markers come off the rows. If
verification cannot run, the rows keep their ⚠️ and say so.

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` covers: registration of every new
address, reply shapes for all reads (including flattening, `None` slot
coercion and empty lists), the `has_option` echo, the `show_*` argument
discipline (exactly one positional argument — the OK-only guarantee),
listener bookkeeping for the two listen pairs across `clear_api()`, the
error envelope for a missing argument, and — the folded-in bug — that
construction emits `/live/startup` and no `average_process_usage`
datagram. All of it drives the real `ApplicationHandler` through
`OSCServer.process_message` via conftest's `dispatch()`, with only the
`get_application` seam substituted.

Explicitly *not* covered there: behaviour against the real LOM objects —
whether the real `unavailable_features` elements stringify usefully,
whether `show_message` blocks, what `has_option` matches. That is Live
verification. `tests/` mutates a running Live on import gating and is not
part of the gate; its two added assertions run only under
`ABLETONOSC_LIVE_TESTS=1`.

## Live verification

Precondition for every check: the Remote Scripts copy equals this
checkout byte for byte (`diff -rq`) **and** Live has been restarted since
it was copied. Method: `API.md` § "The no-probe variant" — fire-and-forget
UDP to 11000, evidence read from the installed `logs/abletonosc.log`
(`_get_property` logs every value). Wrap anything that could mutate in
`/live/song/begin_undo_step` / `end_undo_step`.

1. `get/version_string`, `get/bugfix_version`, `get/build_id`,
   `get/variant`, no args → log lines with the four values; cross-check
   version and edition against Live's About screen. Record the exact
   `variant` string in `API.md`.
2. `get/open_dialog_count`, `get/current_dialog_message`,
   `get/current_dialog_button_count` with no dialog open → `0`, `''`
   (or last message — record which), `0`.
3. `start_listen/open_dialog_count`, then open a dialog by hand (e.g. a
   menu action that raises one), read the two `current_dialog_*`
   addresses, close it → log shows the initial push, a push on open, the
   message/button values, and a push back to 0 on close. `stop_listen`
   afterwards.
4. `get/unavailable_features` → log line; on Suite likely empty — record
   the element strings if any. Decides Open question 1.
5. `get/control_surfaces` → log line naming `AbletonOSC` among the slots;
   record how empty slots appear. Decides Open question 2.
6. `get/has_option` with a nonsense string → `False` in the log; with a
   known Options.txt line from the user's config, if any → `True`.
   Decides Open question 5.
7. `show_message "AbletonOSC C-3 check"` → an OK-only dialog appears;
   immediately send `get/version` and confirm the reply logs within a
   tick (non-blocking evidence); `open_dialog_count` reads 1; click OK;
   count reads 0. Record the returned int from the reply log. Decides
   Open question 3. **Human present required** — the dialog must be
   dismissed by hand.
8. `show_on_the_fly_message "AbletonOSC C-3 check"` → record where (or
   whether) it appears without a Push connected. Decides Open question 4.
9. Restart Live with a capture client on 11001 (only when Seshat is not
   holding the port) → the first datagrams contain `/live/startup` and
   **no** `/live/application/get/average_process_usage`.

Remains uncovered even after these: `number_of_push_apps_running` beyond
the zero case (no Push hardware/app assumed available), and
`peak_process_usage`'s push cadence under load (listen registered and
initial push verified; long-run cadence is observational only).

## Downstream

**Pin bump only.** Every address is new; the only removal is a datagram
`API.md` explicitly told clients to ignore, so no correct consumer can
notice its absence. No existing reply, push or error changes shape; no
address is renamed. The new surface is available for Seshat to adopt
(dialog detection is the audit's named use), and any
`vendored_addresses_test` additions happen when Seshat starts using the
addresses, not as part of the bump.

## Out of scope

- `press_current_dialog_button` — settled exclusion (roadmap Why,
  FORK_GAPS disposition); reopens only with a separately reviewed,
  non-file use case.
- `Application.View` members (`focused_document_view`,
  `available_main_views`, ...) — C-2's bucket.
- `show_message`'s `buttons` / `enable_markup` / `show_success_icon` and
  `show_on_the_fly_message`'s `push_dialog_type` — deliberately pinned to
  Live defaults; exposing buttons without `press_current_dialog_button`
  would create remote dialogs the remote cannot answer. Reopens with that
  member, not before.
- D-5's `TuningSystem` / `Song.get_data` fold-in — `CLOSING_THE_GAPS.md`
  offers it "if a PR is small"; this PR is already ~15 addresses and D-5
  is Song-side, different files. Stays in its own row.
- Listen pairs for `unavailable_features` / `control_surfaces` — see the
  wire contract; five-line follow-up when a consumer appears.
- Deleting the `issues.md` datagram entry and striking the
  `CLOSING_THE_GAPS.md` C-3 row — `/ship`'s job.

## Open questions

A read-only probe against the running Live (per API.md's measurement
section) was prepared to close 1, 2 and 5 and the enum halves of 3/4 at
planning time, but the environment's permission system denied writing the
probe into the installed Remote Scripts copy, so all five stay open for
the implementer's Live verification (Part 4). None of them block writing
the code; each states what the implementation assumes.

1. **`unavailable_features` element type.** The LOM docstring says "list
   of features"; whether elements are strings or enum objects is
   unmeasured. *Assumed:* `str()` on each element yields a stable,
   readable name; the handler coerces unconditionally, so the reply is
   well-formed either way. Check 4 decides; `API.md` records the real
   element form.
2. **`control_surfaces` empty slots.** The list mirrors the preferences
   slots; whether unassigned slots appear as `None`, are omitted, or the
   list is variable-length is unmeasured. *Assumed:* elements may be
   `None` and map to `""`; anything non-None is named
   `type(cs).__name__`. Check 5 decides.
3. **`show_message` semantics.** Whether the call blocks the calling
   (tick) thread until the dialog is dismissed, and what the returned int
   means (pressed button vs. dialog id vs. 0), are unmeasured. *Assumed:*
   non-blocking (Live's dialog state being modelled as observable
   `open_dialog_count` state strongly suggests queued, asynchronous
   dialogs) and the int is passed through opaquely, documented as
   "meaning unmeasured". If check 7 finds it blocks, the address ships
   anyway — one OK-only dialog raised deliberately by the client is the
   documented cost — but `API.md` must say so in the row.
4. **`show_on_the_fly_message` display surface.** With `push_dialog_type`
   defaulted and no Push connected, where the message appears (Live
   status bar, transient overlay, nowhere) is unmeasured. *Assumed:* it
   is transient and self-clearing; check 8 records the reality.
5. **`has_option` matching semantics.** Presumed to test Options.txt
   lines; the exact expected string form (with or without leading `-`) is
   unmeasured. *Assumed:* verbatim pass-through of the wire string, with
   `API.md` documenting it as "the string is handed to Live unmodified".
   Check 6 decides.
