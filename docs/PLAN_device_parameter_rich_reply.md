# Plan: DeviceParameter rich reply (B-2)

Roadmap item: **#1 · B-2 · DeviceParameter rich reply** — from
`CLOSING_THE_GAPS.md` row B-2, closing FORK_GAPS "Device parameters —
numeric only". Planned 2026-08-29.

## Context

`/live/device/get/parameters/{name,value,min,max,is_quantized}` and the
singular `parameter/{value,value_string,name}` describe a parameter as a
number in a range. That is enough to *move* a parameter and not enough to
*explain* one: a quantized parameter's enum labels (`value_items`,
`short_value_items`), its GUI string (`display_value`), whether it is
greyed out (`state`), macro-mapped or Max-disabled (`is_enabled`), owned by
automation (`automation_state`), its reset value (`default_value`) and the
name a Max device or macro renamed it from (`original_name`) are all
`Live.DeviceParameter.DeviceParameter` members the fork never reads. The
FORK_GAPS inventory row lists the class as 17 members, 5 exposed, 12 gaps;
this item closes ten of them (`str_for_value` is already shipped as
`parameter/value_string`; `re_enable_automation` stays out, see Out of
scope).

Why now: it is the audit's Medium–high with a named consumer (Seshat's
`get_device_parameters` formats `name = value (range min–max)` per parameter
and cannot label an enum or warn that automation owns a knob), it has no
dependencies, and it is the first gap PR — the one that proves the
handlers + `API.md` rows + FORK_GAPS closure + inventory + Seshat pin
convention every later bucket reuses.

Key constraints research surfaced:

- **"One richer `parameters` reply" is the existing per-field bulk family
  growing fields, not a new record address.** Two things decide this.
  `API.md` § "Round trips cost ticks, not datagrams" measured that a burst
  of N different addresses answers in one tick, identical to one bulk
  endpoint, so a combined `parameters/info` record buys no latency; and a
  fixed-arity record cannot carry `value_items`, whose length varies per
  parameter. Seshat's `get_device_parameters` (`lib/seshat/tools/handlers.ex`)
  already sends `get/name` plus the four `parameters/{name,value,min,max}`
  reads as one `query_batch` and zips the parallel lists (it does not read
  `is_quantized` today), so new parallel lists drop into that decoder
  unchanged. The bulk reads are
  therefore `/live/device/get/parameters/<field>` for every field that is
  one scalar per parameter, and the variable-length members are
  per-parameter addresses only.
- **Every new address is registered with a literal string, not a loop.**
  Seshat's `vendored_addresses_test` extracts registrations with
  `~r/add_handler\(\s*['"](\/live\/[^'"]+)['"]/` plus a parser for the
  `methods` / `properties_r` / `properties_rw` lists. An address built by a
  new `"/live/device/get/parameters/%s" % field` loop would match neither
  and would be invisible to the docs-coverage tripwire. `device.py`'s
  existing parameter block is already literal-per-address; the new block
  follows it.
- **`DeviceParameter` members never enter the generic property loop** —
  the loop resolves a `Device`, and a parameter is one level down. Every
  address here is a hand-written callee under `create_device_callback`,
  which already normalises `(track_index, device_index)` to ints and
  prepends them to the reply; the callee int-casts `parameter_index`
  itself, exactly as `device_get_parameter_value` does.
- **`state` and `automation_state` are Boost.Python enums.** Live's shipped
  bytecode (`pushbase/device_parameter_component.pyc`,
  `Push2/device_options.pyc`, `Move/device.pyc`,
  `ableton/v2/control_surface/internal_parameter.pyc`, Live 12.4.5) names
  `Live.DeviceParameter.ParameterState.enabled` and
  `Live.DeviceParameter.AutomationState.none` / `overridden` as the values
  Live's own scripts compare against. A Boost enum is an `int` subclass, so
  the OSC builder would encode it as an int by accident; the handler casts
  with `int()` on purpose and the wire carries the **integer code**, the
  way `/live/device/get/type` already does, with the code→name table in
  `API.md`. ⚠️ The codes are from the LOM reference (`enabled=0`,
  `disabled=1`, `irrelevant=2`; `none=0`, `playing=1`, `overridden=2`) and
  unmeasured — Open question 1.
- **`value_items` / `short_value_items` raise on a non-quantized parameter**
  (Live's own docstring, in the FORK_GAPS inventory row: "Raises an error if
  'is_quantized' is False"). The exception type is unmeasured (⚠️ Open
  question 2); Push2's `model/repr.pyc` guards the same read with
  `AttributeError, RuntimeError`. The handler catches `Exception` around
  that one read and answers **no items** rather than a `/live/error`: a
  client describing a whole device would otherwise collect one error per
  continuous parameter on Seshat's reply socket, and `is_quantized` already
  says which parameters can have items. This mirrors upstream's own
  `_get_property` convention of turning a "does not apply" `RuntimeError`
  into a graceful reply.
- **`default_value` may not exist for every parameter.** Live's docstring
  starts "Return the default value for this parameter. A Default value is
  only …" and the inventory truncates it there. ⚠️ Whether the read raises,
  returns `NaN`, or returns `min` for a parameter without one is Open
  question 3. The handler reads it under a `try` and substitutes OSC nil
  (`None`, which the vendored builder encodes as `N`) so one such parameter
  cannot poison a bulk reply.
- **The permission layer blocked measurement** during planning, as it did
  for A-4: writing the probe into the installed copy and even snapshotting
  the installed `return_track.py` were refused, and the no-probe variant
  cannot reach members no address registers. Live 12.4.5 is running; the
  probe (`/live/probe/b2/{enumerate,deep,gesture}`) is written and sits in
  the session scratchpad, so the implementer can run it in minutes — see
  the recommendation at the end of Open questions.
- **The installed copy is not this checkout.** `diff -rq` shows
  `abletonosc/track_identity.py` differs (the installed one predates the
  comment-only change in "Test coverage for the object-read glue"). Live
  verification's precondition is not met until the checkout is reinstalled
  and Live restarted.

Evidence tiers: member names, rw/ro, observability and docstrings are tier
1 (read from a running Live 12.4.3 by the generated inventory). Enum names
are tier 1 for `enabled`, `none`, `overridden` (present as constants in
Live 12.4.5's shipped bytecode) and tier 2 for the rest. Enum integer
codes, the exception type, `default_value` on a parameter without one, and
what `display_value = <unparsable string>` does are unmeasured.

## Wire contract

All addresses are under `/live/device/`, resolve through `song.tracks`
(regular tracks only, same as the rest of the family), and int-cast every
index. Failures — bad track/device/parameter index, Live raising on the
member — arrive as `/live/error ("request", <address>, <detail>, argc,
*args)` from `_dispatch`, unchanged. No listener is added or changed. Every
setter and method is silent.

**Unchanged but relied on**: `get/parameters/{name,value,min,max,is_quantized}`,
`get/parameter/{value,value_string,name}`, `set/parameter/value`,
`set/parameters/value`, and both listen pairs. The `value` listener keeps
pushing its two datagrams; no push gains a field.

### New — bulk, one scalar per parameter, in `device.parameters` order

| Address | Query | Reply | Notes |
|---|---|---|---|
| `/live/device/get/parameters/display_value` | `track_id, device_id` | `track_id, device_id, [display_value: str, ...]` | `DeviceParameter.display_value` per parameter |
| `/live/device/get/parameters/state` | `track_id, device_id` | `track_id, device_id, [state: int, ...]` | `int(ParameterState)` codes, table below |
| `/live/device/get/parameters/is_enabled` | `track_id, device_id` | `track_id, device_id, [is_enabled: bool, ...]` | OSC `T`/`F`, as `is_quantized` already is |
| `/live/device/get/parameters/automation_state` | `track_id, device_id` | `track_id, device_id, [automation_state: int, ...]` | `int(AutomationState)` codes, table below |
| `/live/device/get/parameters/default_value` | `track_id, device_id` | `track_id, device_id, [default_value: float or nil, ...]` | nil (`N`) where Live raises on the read |
| `/live/device/get/parameters/original_name` | `track_id, device_id` | `track_id, device_id, [original_name: str, ...]` | |

A device with no parameters answers `track_id, device_id` and nothing else,
as `parameters/name` does today.

### New — per parameter

| Address | Query | Reply | Notes |
|---|---|---|---|
| `/live/device/get/parameter/display_value` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, display_value: str` | |
| `/live/device/set/parameter/display_value` | `track_id, device_id, parameter_id, display_value: str` | *(silent)* | Assigns `DeviceParameter.display_value`; read back with `get/parameter/value` or `value_string`. A string Live cannot parse is whatever Live does with it — ⚠️ Open question 4; if Live raises it is a `/live/error` |
| `/live/device/get/parameter/state` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, state: int` | |
| `/live/device/get/parameter/is_enabled` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, is_enabled: bool` | |
| `/live/device/get/parameter/automation_state` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, automation_state: int` | |
| `/live/device/get/parameter/default_value` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, default_value: float or nil` | |
| `/live/device/get/parameter/original_name` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, original_name: str` | |
| `/live/device/get/parameter/value_items` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, [item: str, ...]` | Item `i` is the label for quantized value `min + i`. Non-quantized: the three indices and **no items**, no error |
| `/live/device/get/parameter/short_value_items` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, [item: str, ...]` | Same rule; short labels where Live has them |
| `/live/device/parameter/begin_gesture` | `track_id, device_id, parameter_id` | *(silent)* | `DeviceParameter.begin_gesture()` — marks the start of a continuous edit so Live records one undo step and one automation gesture across the `set/parameter/value` calls that follow |
| `/live/device/parameter/end_gesture` | `track_id, device_id, parameter_id` | *(silent)* | `DeviceParameter.end_gesture()`; harmless without a matching begin — ⚠️ Open question 5 |

The method addresses take the `song/cue_point/jump` form (object segment,
then verb) rather than `device/<method>`, because the generic `methods`
loop reaches the `Device`, not one of its parameters.

### Enum codes (⚠️ unmeasured — Open question 1)

| `state` | meaning | | `automation_state` | meaning |
|---|---|---|---|---|
| 0 | `enabled` | | 0 | `none` — no automation |
| 1 | `disabled` — greyed out | | 1 | `playing` — automation is driving the value |
| 2 | `irrelevant` — has no effect in the current mode | | 2 | `overridden` — a manual edit has overridden the automation (the "Re-enable automation" state) |

The Live verification run replaces this table with the measured one before
it becomes `API.md` rows; if measurement finds different codes the code
changes nothing (it sends whatever `int()` yields) and the table does.

## Numbered parts

### Part 1 — `abletonosc/device.py`: the addresses

Inside `init_api`, after the existing "Get/set individual parameters" block
and before its `add_handler` lines (so the parameter-listener comment block
stays where it is):

1. A private helper `_parameter_at(device, params)` returning
   `(param_index, device.parameters[param_index])` with the TouchOSC
   int-cast, used by every per-parameter callee; and a helper
   `_enum_code(value)` that returns `int(value)`.
2. Six bulk callees `device_get_parameters_<field>` returning
   `tuple(... for parameter in device.parameters)`. `state` and
   `automation_state` go through `int()`; `default_value` reads under
   `try/except Exception` per parameter and yields `None` on failure, with
   a comment naming the docstring that makes this necessary.
3. Per-parameter getters for the same six fields, `value_items` and
   `short_value_items` (the last two read under `try/except Exception`
   and return `(param_index,)` with no items on failure, comment citing
   Live's "Raises an error if 'is_quantized' is False"), the
   `display_value` setter (`params[1]` assigned as-is, no cast — it is a
   string), and `begin_gesture` / `end_gesture` callees that call the
   method and return `None`.
4. Literal `self.osc_server.add_handler("/live/device/...", create_device_callback(...))`
   lines for all seventeen addresses, no `include_ids`, no loop.

Every reply tuple starts with `param_index` for the per-parameter forms
and with nothing for the bulk forms; the wrapper prepends
`(track_index, device_index)` either way.

Documentation in the same commit:

- **`API.md` § Device API**: rows for all seventeen addresses in the table
  after `/live/device/set/parameter/value`, a short "Parameter description"
  subsection under "Device Type Reference" holding the enum-code table, the
  `value_items` index rule, the nil rule for `default_value`, and the
  gesture pair's purpose; and, once measured, the dated Live-version-stamped
  measurement block beside the existing 2026-08-27 one.
- **`SESHAT.md` § Additions to upstream's code**: one entry, "`device.py` —
  DeviceParameter description addresses", listing the seventeen addresses,
  the two graceful-empty rules and why, the literal-registration reason
  (Seshat's tripwire regex), and "Downstream: pin bump only, see below".
  Also extend the § Merge hazards `device.py` bullet with one sentence: a
  merge that takes upstream's "individual parameters" block wholesale
  drops these seventeen registrations without a conflict, and
  `tests_unit/test_device_parameters.py` is the tripwire.

### Part 2 — `tests_unit/test_device_parameters.py` (new) and the fakes

A new test module (see Testing) plus the minimum fake surface it needs:
`FakeParameter` in `test_device_listeners.py` stays untouched — the new
file defines its own richer fake so the listener file's docstring claim
about its fakes stays true. The new fake carries `display_value` (rw),
`state`, `is_enabled`, `automation_state`, `default_value` (optionally
raising), `original_name`, `value_items` / `short_value_items` (raising
`RuntimeError` when `is_quantized` is false, matching the documented LOM
behaviour), and records `begin_gesture` / `end_gesture` calls. The enums
are modelled as `int` subclasses with a `name`, which is what a Boost
enum is for the purposes of `int()`.

`tests_unit/conftest.py` needs no change — `load_device_module()` already
constructs the real `DeviceHandler`.

### Part 3 — FORK_GAPS and the gaps write-up

Same commit as Parts 1–2:

- `FORK_GAPS.md`: delete the "Device parameters — numeric only" shape-gap
  section; move it to § Closed as "Device parameters — numeric only —
  closed 2026-08-29" in the style of the A-4 entry (what was the gap, what
  closed it, the members closed, what remains: `re_enable_automation`, and
  every listener on the newly readable members). Update the curated
  Medium–high table row that names `DeviceParameter.value_items, is_enabled,
  automation_state, default_value, original_name` to point at the closed
  entry rather than the shape gap. Regenerate the inventory with
  `tools/lom_gaps.py` **if** a `dump_lom` from a Live running the installed
  post-change copy is available; if not (this lifecycle cannot install),
  add the same "no dump has been taken since this landed" sentence the A-4
  closure carries, so the inventory's 12-gap count is known-stale rather
  than wrong-looking.
- `CLOSING_THE_GAPS.md` row B-2: not touched here — `/ship` strikes it
  through and removes the `str_for_value` clause, per the roadmap note.

### Part 4 — Live verification results into `API.md`

Not a code part, but a commit obligation: whatever the probe measures
(enum codes and names, exception types, the `default_value` and garbage
`display_value` behaviour, the gesture pair) lands in `API.md` beside the
2026-08-27 measurement block, dated and stamped "Live 12.4.5", and the
⚠️ markers in the rows come off. If verification cannot run, the rows keep
their ⚠️ and say so — a plan-only measurement is one the next person
re-derives.

## Testing (`tests_unit/`, the only gate)

`tests_unit/test_device_parameters.py`, driven through `conftest.dispatch`
against the production `OSCServer` + `DeviceHandler`, fakes for the LOM:

1. Each of the six bulk addresses answers `(track, device, *values)` in
   parameter order, with the right OSC types (`str`, `int`, `bool`,
   `float`) — one parametrized test over a two-device track.
2. A device with zero parameters answers `(track, device)` for each bulk
   address.
3. `parameters/default_value` with one raising parameter answers `None` in
   that slot and real floats elsewhere; the wire carries an `N` tag there
   (assert on the decoded `None`).
4. Each per-parameter getter answers `(track, device, param, value)`;
   float indices normalise (`0.0, 1.0, 2.0` → ints in the echo).
5. `parameter/value_items` on a quantized fake answers the labels;
   `short_value_items` likewise; on a non-quantized fake both answer
   exactly `(track, device, param)` and nothing on `/live/error`.
6. `set/parameter/display_value` assigns the string to the fake and is
   silent; a fake whose setter raises produces one structured
   `/live/error ("request", address, detail, 4, t, d, p, s)`.
7. `parameter/begin_gesture` / `end_gesture` call the fake's methods once
   each and send nothing.
8. An out-of-range parameter index on each per-parameter address, and an
   out-of-range device index on each bulk address, answers a structured
   `/live/error` echoing the request (`argc` and args), and nothing else.
9. `test_device_listeners.py` passes unmodified — the proof that the
   existing addresses and both listen pairs are untouched.

What this layer does **not** cover, stated plainly: handler code against
real `Live.DeviceParameter` objects — the enum codes, what actually raises,
what `display_value =` accepts. `tests/` mutates a running Live and is not
part of the gate.

## Live verification

Precondition for every check: the installed Remote Scripts copy equals
this checkout byte for byte (**today it does not** — `track_identity.py`
differs) **and** Live has been restarted since it was copied. Method:
`API.md` § "The no-probe variant" — send to 11000, read
`logs/abletonosc.log`; replies cannot be captured while Seshat holds 11001.
Every mutation under `/live/song/begin_undo_step` / `end_undo_step` with
the value restored. The custom callees log nothing on their ok path, so
each ok-path check below is decided by a `/live/error` line *not*
appearing plus a read-back through an address that does log
(`get/parameter/value` logs nothing either — use a deliberate bad index
for counts, and the probe's own log lines for values).

1. **Enum codes and names.** Probe: for every parameter of one device log
   `int(state), str(state), state.name` and the same for
   `automation_state`, plus `dict(Live.DeviceParameter.ParameterState.names)`
   and `AutomationState.names`. Evidence: the `B2PROBE` lines. Decides the
   `API.md` table.
2. **`value_items` on a continuous parameter.** Probe: read
   `value_items` inside `try`; log the exception type and message.
   Evidence: the `!!` line. Decides the comment in Part 1 step 3 and the
   `API.md` row's wording; the handler's `except Exception` is right either
   way.
3. **`default_value` without a default.** Probe: read it on every parameter
   of a Max for Live device or a rack macro, if one is in the set; log
   raise vs value. Evidence: `!!` line or a value. Decides whether the nil
   rule ever fires in practice.
4. **`display_value` setter.** Probe on one continuous parameter under an
   undo step: set to `str_for_value(min)`, read `value`; set to
   `"garbage!!"`, read `value`; restore. Evidence: the value after each
   set, and whether the garbage set raised. Decides Open question 4's row
   note.
5. **Gesture pair.** Probe: `begin_gesture()`, a `value` write, `end_gesture()`,
   `end_gesture()` again. Evidence: no `!!` lines; and, off Live's UI,
   Edit → Undo shows one step for the write. Decides Open question 5.
6. **Through the installed addresses**, once reinstalled and restarted:
   `/live/device/get/parameters/state 0 0` — evidence: no
   `Error handling OSC message` line for it; `/live/device/get/parameter/value_items 0 0 99`
   — evidence: an error line naming the request, proving the index path
   behaves like `get/parameter/value`'s.

Uncovered afterwards, and why: `is_enabled` false and `automation_state`
playing/overridden require a macro-mapped parameter and a clip with
automation in the user's set, which the plan does not create; `state`
`irrelevant` requires a device mode that makes a knob moot. Their codes
come from the `names` dict in check 1, which is the whole mapping without
needing an instance of each.

## Downstream

**Pin bump only — with one optional follow-up.** No existing address,
request shape, reply shape, push or error envelope changes.
`vendored_addresses_test` gains no tripwire it does not already have: the
seventeen new registrations are literal strings, so its docs-coverage test
picks them up on the bump and passes as long as `API.md` carries every
row — which is exactly why Part 1 documents them in the same commit. Seshat
may then extend `get_device_parameters` (add `parameters/is_quantized`,
`state`, `is_enabled`, `automation_state`, `display_value` to its
`query_batch` and the per-parameter `value_items` where `is_quantized`),
but nothing in Seshat breaks or changes behaviour on the pin alone. Its
docs-coverage check (`vendored_addresses_test.exs`, `documented?/2`) is a
plain substring match of each registered address against `API.md`, so
every one of the seventeen addresses must appear verbatim in a row.

## Out of scope

- **Listeners on `state`, `automation_state`, `display_value`** — all three
  are observable (inventory `obs` column). Not in the Goal; the pattern is
  `device_get_parameter_value_listener` and a follow-up can add
  `start_listen/parameter/<field>` pairs the same way. Recorded in the
  FORK_GAPS closed entry as what remains.
- **`re_enable_automation`** — a mutation the Goal does not name; belongs
  with an automation-shaped item.
- **Return-track and master parameter parity** (`/live/return_track/device/*`,
  `/live/master/device/*`) — A-3's job; those families keep their combined
  `get/parameters` shape until then.
- **Devices inside racks** — A-1, declined until a workflow needs it.
- **A combined `parameters/info` record address** — declined for the
  reasons in Context; reopens if a consumer needs an atomic multi-field
  snapshot that a one-tick burst cannot give.
- **Touching `FakeParameter` in `test_device_listeners.py`** — that file's
  docstring documents its fakes as the measured `Device` shape; the new
  file owns its own.

## Open questions

1. **Enum integer codes and names.** Unknown: the exact `int()` value and
   `name` of each `ParameterState` / `AutomationState` member. Why
   unresolved: measurement blocked by the permission layer (probe write
   refused); the bytecode confirms only `enabled`, `none`, `overridden`
   exist. Assumed meanwhile: the LOM-reference order in the table above.
   The code is independent of the answer.
2. **What `value_items` raises on a continuous parameter.** Unknown: the
   exception class and message. Why: as above. Assumed: any `Exception`;
   the handler catches broadly and the comment quotes Live's docstring.
3. **`default_value` on a parameter without one.** Unknown: raise vs
   sentinel. Why: docstring truncated in the inventory, no measurement.
   Assumed: may raise; the nil rule handles both.
4. **`display_value = <unparsable>`.** Unknown: ignored, clamped, or
   raises. Why: mutation, needs Live. Assumed: the setter passes the
   string through and any raise becomes a structured `/live/error`; the
   `API.md` row says so until measured.
5. **`end_gesture()` without `begin_gesture()`.** Unknown: silent or
   raises. Why: needs Live. Assumed: silent; if it raises, that is a
   correct structured error and the row gains a sentence.

Recommendation for the implementer: run the scratchpad probe first (the
answers land in minutes and change only prose and the enum table), then
build. If the probe still cannot be installed, build against the
assumptions above — every one is handled defensively in code — and leave
the ⚠️ rows in `API.md` marked as unmeasured with today's date.
