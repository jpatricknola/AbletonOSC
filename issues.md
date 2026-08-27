# AbletonOSC issue punch list

This is the prioritized backlog produced from the 2026-08-03 code review and
targeted contract probes against a running Ableton Live instance. Items are grouped by kind — bugs, robustness, infrastructure
and documentation, cleanup — and ordered by priority within each group.
Completed entries are removed; other documents refer to items by title, not
by position. None of these is a fork gap: every item
concerns an address or code path that already exists. Missing Live Object
Model surface is tracked in [FORK_GAPS.md](FORK_GAPS.md) instead.

This document describes the problem and the outcome each change must achieve.
Detailed implementation plans are intentionally out of scope and should be
created separately for each issue. Any change that further diverges from
upstream must also be reflected in [SESHAT.md](SESHAT.md).

## Bugs — existing addresses misbehave

### Remove the unsolicited average-process-usage startup datagram


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

## Robustness — code that works today but fails unsafely

### Make live code reload ordered and failure-safe


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

### Remove the process-global and shared-file risks from song structure export


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

### Stop masking Remote Script import failures


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

### Validate log-level requests without assertions


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

### Bound `/live/application/dump_lom`'s output path


**Priority:** Low — policy inconsistency, loopback-only exposure

_Re-scoped 2026-08-27. The original item ("remove dead introspection code")
is moot: `introspection.py` was rewritten as the LOM walker behind
`FORK_GAPS.md`, is imported by `application.py`, hot-reloaded by
`manager.reload_imports`, and documented in `SESHAT.md`. The Python-2-era
type check and the malformed `logger.info` call it flagged are gone._

What remains is a path-policy gap. `/live/application/dump_lom [path]` takes
an arbitrary filesystem path from the wire and writes to it with Live's
privileges (`application.py:30-31`). The fork's own rule, enforced for
`/live/browser/export`, is the opposite: a caller-supplied destination is
rejected without writing, and the file lands under a private directory via
`mkstemp` (`browser.py:70`, `:122-130`, `:403`). Seshat's
`vendored_addresses_test` tripwires the browser rule
(`dest_path = str(params`) but has no equivalent for `dump_lom`. Loopback-only
binding limits the exposure, but the two endpoints should not state opposite
policies for the same hazard.

Outcome: `dump_lom` writes only to its fixed default (`logs/lom_dump.json`
beside `abletonosc.log`) or to a `mkstemp` file under a private root, and
rejects a wire-supplied path the way `browser/export` does. `tools/lom_gaps.py`
and `API.md` follow the new location. Seshat's guard test gains the matching
tripwire in the same pin bump.

**Affected area:** `abletonosc/application.py`, `abletonosc/introspection.py`,
`tools/lom_gaps.py`, `API.md`, `SESHAT.md`, Seshat's
`vendored_addresses_test.exs`.

## Infrastructure and documentation

### Correct and complete the public API documentation


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

### Establish a single authoritative endpoint contract inventory


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

### Add bounded log retention


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

## Cleanup

### Retire or formally support the experimental clip filtering API


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

### Normalize remaining small transport and endpoint inconsistencies


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

### Split oversized extension modules along contract boundaries


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

## Declined

Recorded so they are not re-raised; each names what would reopen it.

### `pythonosc`'s dispatcher has an invalid escape sequence

`pythonosc/dispatcher.py` uses `'[\w|\+]*'`, which emits a `SyntaxWarning`
and treats `|` as a literal class member. Declined 2026-07-30: this is
`pythonosc` vendored inside AbletonOSC — two levels from code this fork owns —
and editing it buys one silenced warning for a `SESHAT.md` divergence entry and
a merge conflict surface. **Reconsider if** an Ableton release bumps the
bundled Python to a version where this is an error, or if the file needs
changing for another reason — then fix it in passing. Upstream `pythonosc` is
the right owner.
