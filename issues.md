# AbletonOSC issue punch list

This is the prioritized backlog produced from [HANDOFF.md](HANDOFF.md) after the
2026-08-03 code review and targeted contract probes against a running Ableton
Live instance. Items are ordered by recommended execution priority. The first
three are reproduced live defects; later items are static findings, contract
gaps, test-infrastructure problems, documentation debt, and cleanup.

This document describes the problem and the outcome each change must achieve.
Detailed implementation plans are intentionally out of scope and should be
created separately for each issue. Any change that further diverges from
upstream must also be reflected in [SESHAT.md](SESHAT.md).

## 1. Correct OSC wildcard matching

**Priority:** Critical — confirmed live protocol defect

Wildcard patterns are converted to regular expressions in
`abletonosc/osc_server.py`, but matching uses an unanchored expression and the
literal parts of the OSC address are not escaped. A pattern can therefore match
the prefix of a longer registered address instead of only the intended complete
address. During live testing, `/live/*/get/tempo 0` invoked
`/live/scene/get/tempo_enabled` in addition to the intended tempo endpoints.
`/live/track/get/*` can similarly reach nested routes such as
`/live/track/get/clips/name`.

This violates the documented wildcard contract, produces unexpected replies,
and can invoke callbacks with an argument shape intended for another endpoint.
Wildcard requests must match complete registered OSC addresses, and ordinary
characters in the requested pattern must not acquire regular-expression
semantics accidentally. The supported wildcard syntax must be explicit and
covered independently of a running Live instance.

**Affected area:** `abletonosc/osc_server.py`, wildcard contract tests, OSC API
documentation.

## 2. Isolate failures during wildcard fan-out

**Priority:** Critical — confirmed live protocol defect

Wildcard dispatch currently suppresses only `ValueError` and `AttributeError`
from an individual matched callback. Other callback failures escape the
per-match loop and prevent later matching endpoints from running. Live testing
confirmed that `/live/*/get/tempo` with no arguments invokes the song tempo
getter, then raises `IndexError` in the scene handler because it expects a scene
index; the rest of the wildcard fan-out is abandoned.

A wildcard request is a fan-out operation, so one endpoint's incompatible
argument requirements or runtime failure must not silently truncate unrelated
matches. The contract must define how individual match failures are treated and
ensure that every eligible match is considered. Diagnostics must retain enough
context to identify both the wildcard request and the concrete callback that
failed, without producing an ambiguous legacy error.

**Affected area:** `abletonosc/osc_server.py`, wildcard error reporting, fake
dispatcher tests.

## 3. Define and repair multi-track wildcard getter responses

**Priority:** Critical — confirmed live protocol defect

The track callback wrapper accepts `"*"` as a track identifier and iterates all
regular tracks. For getters, however, it returns as soon as the first callback
produces a value. Live testing of `/live/track/get/name *` produced exactly one
getter invocation for track 0. Setters appear to reach every track only because
their callbacks return `None`.

The intended wire contract for a multi-track getter is currently undefined. It
must state whether the server emits one response per track or one aggregate
response, including ordering, empty-set behavior, and partial-error behavior.
After that contract is chosen, getters must report every selected track and
single-track requests and wildcard setters must retain their existing behavior.
Seshat compatibility must be checked before selecting or changing the response
shape.

**Affected area:** `abletonosc/track.py`, client expectations, README/SESHAT
contract documentation, regression tests.

## 4. Make all endpoint failures use one correlated error contract

**Priority:** High — protocol reliability and client timeout behavior

Direct callback exceptions are handled by the dispatcher and sent as structured
`/live/error` messages containing `"request"`, the OSC address, error detail,
argument count, and the original arguments. Generic method calls and property
setters do not follow that path: `AbletonOSCHandler._call_method` and
`_set_property` catch their own exceptions and log them. The logging relay then
sends a legacy `['log', message]` error with no request address or arguments.

Clients therefore receive different error shapes based on where the exception
was caught, even when two requests fail for the same reason. Uncorrelated errors
cannot reliably resolve a pending request and can force Seshat to wait for a
timeout after the server already knows the operation failed. All request-driven
failures need a single stable, correlated error envelope. Unsolicited internal
logging may remain distinguishable from request failures.

**Affected area:** `abletonosc/handler.py`, `abletonosc/osc_server.py`,
`manager.py` log relay, Seshat error decoding, error-contract tests.

## 5. Bring callback reply validation inside the error contract

**Priority:** High — prevents dispatcher-level contract failures

When a callback returns a non-`None` value, `OSCServer.process_message` uses an
`assert` to require a tuple. That assertion is outside the exception boundary
that creates the structured request error. A malformed callback return can
therefore escape to the outer processing loop and produce an uncorrelated error.
Assertions can also be disabled by optimized Python, making behavior dependent
on interpreter flags.

Callback response validation must be deterministic in every runtime mode and a
bad handler return must identify the request and handler that violated the
contract. The same rule must apply to direct and wildcard dispatch.

**Affected area:** `abletonosc/osc_server.py`, callback contract tests.

## 6. Make the test suite safe, isolated, and usable as a regression gate

**Priority:** High — required to protect the protocol fixes above

The repository has 54 pytest test functions, but they are stateful Live
integration tests rather than isolated unit tests. Importing `tests` immediately
sends `/live/api/reload`, so test discovery itself mutates the running system.
The client binds fixed port `0.0.0.0:11001`, which conflicts with Seshat and is
broader than the fork's loopback-only security policy. Tests assume exactly four
tracks and eight scenes, modify playback, clips, recording, tempo, tracks,
scenes, undo history, and require configured audio input. Cleanup is not
consistently protected against assertion failures.

The project needs a dependable regression boundary that can exercise routing,
validation, reply shapes, and listener bookkeeping without Live. Live-dependent
tests must be explicitly opt-in, discover the current set rather than require a
specific blank template, isolate their fixtures, and restore all mutations even
when a test fails. Seshat end-to-end coverage must remain distinct because it
owns the fixed response port and long-lived listeners.

The development dependencies and supported test commands also need a tracked
manifest and an automated unit/contract test workflow. At review time neither
`pytest` nor `ruff` was installed and no CI workflow existed.

**Affected area:** `tests/`, `client/client.py`, project metadata, CI.

## 7. Update stale and incorrect existing tests

**Priority:** High — existing tests encode contracts that are already wrong

Several concrete defects exist independently of the broader test redesign:

- `tests/test_application.py` expects the obsolete unstructured error response,
  while the current direct-callback contract begins with `"request"` and echoes
  the failing address and arguments.
- `tests/test_clip_slot.py` stops a clip-slot listener with only the track index;
  the clip index is missing. The stop request fails and can leave the listener
  registered until a reload.
- `tests/__init__.py` shadows the imported `TICK_DURATION`, making timing policy
  harder to understand and maintain.

The committed tests must describe the current public contract accurately and
must not leak listeners or other state when they pass. These corrections should
be coordinated with the test-architecture issue so obsolete assumptions are
not simply moved into a new harness.

**Affected area:** `tests/__init__.py`, `tests/test_application.py`,
`tests/test_clip_slot.py`.

## 8. Fix base handler initialization order

**Priority:** High — architectural fragility in every handler

`AbletonOSCHandler.__init__` invokes the overridable `init_api()` before it
creates `listener_functions`, `listener_objects`, and `class_identifier`.
Subclass route registration therefore runs against a partially initialized
object. `BrowserHandler` already contains a workaround explaining that its
registration cannot depend on state assigned by its own constructor.

Every handler must enter route registration with its base invariants available,
and subclass identity and subclass-owned initialization must have an explicit
lifecycle. The corrected lifecycle must preserve current route registration,
listener cleanup, reload behavior, and Seshat handler overrides.

**Affected area:** `abletonosc/handler.py`, all handler constructors,
registration and listener lifecycle tests.

## 9. Normalize device parameter listener identifiers

**Priority:** High — listener leaks and float-valued OSC compatibility

Individual device parameter getters and setters convert the parameter index to
an integer, but the parameter listener path indexes with raw `params[2]` and
stores the raw values in its listener key. Interfaces such as TouchOSC commonly
send numeric arguments as floats. A float parameter index can fail when indexing
Live's parameter collection, and start/stop calls using numerically equivalent
but differently typed paths can fail to find the same listener.

The listener contract must normalize track, device, and parameter identifiers
consistently before Live lookup, response echoing, and bookkeeping. Starting,
restarting, stopping, clearing, and renumbering listeners must all address the
same underlying `DeviceParameter` without leaks.

**Affected area:** `abletonosc/device.py`, listener lifecycle tests.

## 10. Define selected-track identity across regular, return, and master tracks

**Priority:** High — valid fork operations can break the view query contract

The fork adds endpoints that select return tracks and the master track, but
`/live/view/get/selected_track` determines the selected index only within
`song.tracks`. After a valid `/live/return_track/select` or
`/live/master/select`, the generic view getter can fail because the selected
object is not a regular track. `/live/view/get/selected_device` inherits the
same regular-track assumption.

The public contract needs an unambiguous representation for regular, return,
and master track identities that can be used consistently by selection, view,
device, and state-mirroring operations. Backward compatibility with consumers
expecting a single regular-track index must be assessed. The view setters and
getters must also agree on whether setters are silent: currently
`/live/view/set/selected_device` returns a tuple despite being documented as a
silent setter.

**Affected area:** `abletonosc/view.py`, `abletonosc/return_track.py`, Seshat
session state, view and selection documentation/tests.

## 11. Make live code reload ordered and failure-safe

**Priority:** Medium-high — development reload can create a mixed runtime

`Manager.reload_imports` reloads several concrete handler modules before
reloading their `handler` base. Those modules can remain subclasses of the old
base class after `/live/api/reload`. In addition, a reload exception is logged
but execution still clears and reinitializes the API, allowing a partially
reloaded module graph to become active.

A successful reload must produce a coherent set of modules whose handlers share
the intended current base classes. A failed reload must preserve a usable
previous API or fail in a clearly reported, recoverable state; it must not
silently activate a mixture of old and new code. Listener cleanup and Seshat's
extension registrations are especially important because reload is used during
development and tests currently trigger it automatically.

**Affected area:** `manager.py`, `abletonosc/__init__.py`, reload tests.

## 12. Remove the process-global and shared-file risks from song structure export

**Priority:** Medium-high — security and cross-process correctness

`/live/song/export/structure` clears `os.environ['TMPDIR']` for the entire Live
process on macOS and writes to a fixed predictable filename in the shared temp
directory. This changes process-global behavior beyond the request, allows
concurrent exports to overwrite each other, and uses a location and permission
model that the newer browser exporter was explicitly hardened to avoid.

The endpoint must either have a private, collision-safe export contract with
appropriate permissions and cleanup ownership or be removed if Seshat no
longer consumes it. Its response must identify the produced artifact reliably;
global environment mutation must not be part of an OSC request's side effects.

**Affected area:** `abletonosc/song.py`, export documentation and tests, Seshat
consumer audit.

## 13. Stop masking Remote Script import failures

**Priority:** Medium — startup diagnostics and reliability

The package root catches every `ImportError` raised while importing `Manager`,
ostensibly so pytest can import the package without Ableton's modules. In Live,
the same guard can hide a genuine missing dependency or programming error.
`create_instance()` then references an undefined `Manager`, replacing the
original failure with a less useful `NameError`.

Testability must not suppress production import failures. Live startup should
surface the original actionable exception, while non-Live tests should be able
to import the portions they need without depending on a broad exception guard
in the Remote Script entry point.

**Affected area:** root `__init__.py`, test import structure, startup diagnostics.

## 14. Correct and complete the public API documentation

**Priority:** Medium — users and planners cannot reliably discover the contract

The README remains largely upstream documentation. Its installation link
downloads `ideoforms/AbletonOSC` rather than this fork, it does not explain the
loopback-only bind and security policy, and it describes the track API as
covering regular, return, and master tracks even though the fork now exposes
separate contracts. `CONTRIBUTING.md` instructs developers to reload using
`/live/reload`; the implemented endpoint is `/live/api/reload`.

A static comparison found 75 of 139 literal registered addresses absent from
README, including nearly all browser, return-track, master-track, and fork view
routes. Dynamically generated registrations make the complete contract harder
to measure. Documentation must identify this fork, provide the correct install
source and operational security expectations, and describe every supported
endpoint's request, success response, error response, listener behavior, and
side effects.

**Affected area:** `README.md`, `CONTRIBUTING.md`, `SESHAT.md`, all public route
families.

## 15. Establish a single authoritative endpoint contract inventory

**Priority:** Medium — prevents drift between code, docs, tests, and clients

The OSC contract is currently duplicated across programmatic route registration,
literal `add_handler` calls, README tables, extensive SESHAT.md prose, pytest
expectations, and Seshat client decoding. This duplication has already produced
stale error tests, undocumented endpoints, a silent/replying setter mismatch,
and ambiguous wildcard behavior.

The project needs one authoritative, machine-checkable inventory of endpoint
addresses and their argument, response, error, listener, and mutation semantics.
Documentation and basic contract checks should be verifiably consistent with
that inventory. Dynamically generated property and method routes, fork-only
extensions, and upstream merge hazards all need representation.

**Affected area:** route registration architecture, documentation generation,
contract tests, Seshat compatibility checks.

## 16. Add bounded log retention

**Priority:** Medium — unattended disk growth

`Manager.start_logging` uses an unbounded `FileHandler`. Getter-heavy clients
log every request, so the installed `abletonosc.log` grows continuously; it was
approximately 855KB during this review and has no retention ceiling. Long-lived
Seshat use will continue increasing the file indefinitely.

Logging must retain enough recent history for diagnosis while placing an
explicit bound on disk consumption. Rotation and retention behavior should be
documented, and reload/disconnect must not accumulate duplicate handlers or
leave file descriptors open.

**Affected area:** `manager.py`, operational documentation, logging lifecycle
tests.

## 17. Validate log-level requests without assertions

**Priority:** Medium-low — invalid input has runtime-dependent behavior

`/live/api/set/log_level` validates its argument with `assert`. Optimized Python
can remove the check, while normal mode raises an assertion that flows through
the generic error machinery. The endpoint also changes only the file handler,
which makes the meaning of the manager's log level incomplete if other handlers
are intended to follow it.

The endpoint needs a stable public contract for missing and invalid levels and a
clear definition of which logging outputs are controlled. Runtime optimization
flags must not alter validation behavior.

**Affected area:** `manager.py`, application API documentation and tests.

## 18. Remove the unsolicited average-process-usage startup datagram

**Priority:** Medium-low — malformed unsolicited protocol traffic

`ApplicationHandler.init_api` sends `/live/startup`, registers the average
process usage getter, and then sends an empty
`/live/application/get/average_process_usage` message. The latter is not tied to
a request and contains no usage value, so clients can interpret it as a malformed
getter response. It is also inconsistent with other getters, which respond only
when queried or when a listener contract explicitly pushes state.

Startup traffic must contain only documented startup notifications. Average
process usage should follow a clearly documented query or listener contract.

**Affected area:** `abletonosc/application.py`, startup and application tests.

## 19. Retire or formally support the experimental clip filtering API

**Priority:** Low — incorrect, stale, undocumented behavior

`/live/clips/filter` and `/live/clips/unfilter` are undocumented upstream
experiments. Their cache is built once and never invalidated when tracks, clips,
or clip names change. The note-name helper returns a pitch class rather than a
full MIDI note despite its name and docstring, so octave-bearing names do not
have the represented semantics. Filtering mutates clip mute state across the
set, increasing the risk of surprising project changes.

The routes should be removed if no current consumer relies on them. If they are
part of the supported product, their musical semantics, cache invalidation,
mutation/restoration behavior, and public request contract need to be defined
and tested against Live.

**Affected area:** `abletonosc/clip.py`, consumer audit, clip API documentation
and tests.

## 20. Remove dead introspection code

**Priority:** Low — maintenance noise and misleading utilities

`abletonosc/introspection.py` is not imported. It contains a Python-2-era string
comparison for property types and a malformed `logger.info('Method', obj)` call
that would itself raise a logging formatting error if reached. Its recursive
module traversal also has no documented safety boundary.

Dead code should not imply a supported debugging facility. Remove the module,
or explicitly define and test a bounded introspection feature if it is still
needed.

**Affected area:** `abletonosc/introspection.py`.

## 21. Normalize remaining small transport and endpoint inconsistencies

**Priority:** Low — opportunistic consistency work

Several smaller inconsistencies should be resolved after the core contract is
stable:

- Jumping to a cue point by an unknown name is a silent no-op, while an invalid
  numeric cue index raises an error. Both identify a missing target but expose
  different failure behavior.
- `OSCServer.send` handles OSC message construction errors but not socket
  `OSError` failures from `sendto`, leaving transport failure reporting dependent
  on the caller.
- The test client binds all IPv4 interfaces even though this fork deliberately
  restricts the production server to loopback; this is also covered by the test
  harness issue but should remain an explicit security invariant.

These behaviors need consistent documented outcomes aligned with the canonical
error contract and the fork's local-only security model.

**Affected area:** `abletonosc/song.py`, `abletonosc/osc_server.py`,
`client/client.py`, related tests and documentation.

## 22. Split oversized extension modules along contract boundaries

**Priority:** Low — maintainability before further expansion

`abletonosc/browser.py` and `abletonosc/return_track.py` are large and
well-commented, but each combines OSC request parsing, validation, Live-object
lookup, business rules, response serialization, listener management, and file
or device operations. This makes it difficult to test contract behavior without
constructing a full handler and increases the chance that new endpoints repeat
slightly different validation and error patterns.

The extension code should have clear internal boundaries between protocol
handling, Live model access, and serialization while retaining the Remote Script
entry points and documented Seshat behavior. This work should follow the
canonical error and endpoint-contract decisions so the new boundaries reflect
the settled architecture.

**Affected area:** `abletonosc/browser.py`, `abletonosc/return_track.py`, unit
test organization.

## 23. Give device property listeners their identity back

**Priority:** Medium — defective listener contract, found in the 2026-08-03
integration review follow-up (PR #62 review on the Seshat side)

`/live/device/start_listen/{name,type,class_name}` are registered through
`create_device_callback(self._start_listen, prop)` without `include_ids=True`,
so the wrapper strips the track and device indices before `_start_listen` sees
them. Two consequences: the asynchronous push on the corresponding `get/`
address carries the bare value with no indices, so a client cannot tell which
device changed; and the listener key collapses to `(prop, ())` for every
device, so subscribing a second device to the same property silently stops and
replaces the first — one subscription per property, process-wide.

`start_listen/parameter/value` already handles this correctly with
`include_ids=True`. The property listeners need the same treatment, with the
caveat that this is a wire-contract change: the push gains two leading indices
and subscription identity becomes per-device, so any existing subscriber's
decoding and unsubscribe calls must be checked (Seshat currently subscribes to
none of these — its API doc documents the hobbled behavior and warns against
building on it until this issue is fixed). Regression coverage should share
the listener-lifecycle tests that issue #9 calls for.

**Affected area:** `abletonosc/device.py`, listener lifecycle tests, Seshat
API documentation (remove the warning once fixed), SESHAT.md.
