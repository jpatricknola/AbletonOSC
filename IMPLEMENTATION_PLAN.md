# Implementation plan: issues 1, 2, 4, 5, 7

Covers items **#1, #2, #4, #5, #7** from [issues.md](issues.md). These five are
planned together because they form one coherent unit of work: a single
dispatch/error boundary in `OSCServer.process_message` (#1, #2, #5), the
handler-level failures that must be routed onto that same boundary (#4), and
the committed tests that encode the contracts being corrected (#7).

Issues #3 (multi-track wildcard reply shape) and #6 (test-harness redesign) are
explicitly out of scope, but this plan is written so it does not pre-empt
either: no track.py changes, and new tests are placed so the later harness
work can absorb them.

Issue #4 is closed here for the defect that motivated it: uncaught callbacks and
the generic `_call_method`/`_set_property` paths gain the same correlated
exception envelope. This PR does not normalize custom handlers that deliberately
return inline `"error"` tuples or silent view-steering endpoints. If issue #4 is
interpreted literally as one representation for every semantic rejection in the
entire fork, leave it partially open and track that broader contract migration
with issue #15 rather than claiming this PR completed it.

## Dependency order

```
Phase 1  (#1 wildcard matching, #2 fan-out isolation, #5 reply validation)
   └── one refactor of osc_server.process_message around a shared dispatch helper
Phase 2  (#4 correlated generic method/property failures)
   └── depends on Phase 1: handler exceptions must land on the boundary Phase 1 builds
Phase 3  (#7 test corrections)
   └── depends on Phase 2: test_application.py must assert the final envelope, once
Docs/SESHAT.md updated per phase (SESHAT.md's own rule: every further divergence is recorded)
```

Each phase is one commit (plus a shared test-scaffolding commit before
Phase 1). Every phase leaves the tree shippable.

---

## Phase 0: Live-free dispatcher test scaffolding

The regression tests for Phases 1–2 must run without Ableton. Three obstacles:

1. Importing the `tests` package sends `/live/api/reload` at module scope
   ([tests/__init__.py:28-30](tests/__init__.py#L28-L30)), so nothing new can
   live under `tests/` without mutating a running Live instance during
   collection. Full cleanup is issue #6; for now, create a separate top-level
   package **`tests_unit/`** with a plain `__init__.py` (no side effects).
   Issue #6 can later fold it into the restructured `tests/` tree.
2. A normal `from abletonosc.osc_server import OSCServer` does **not** work from
   this checkout. `osc_server.py` imports `..pythonosc`, so importing
   `abletonosc` as a top-level package raises "attempted relative import beyond
   top-level package"; importing through the Remote Script root executes the
   Live-dependent package initializers. The repository directory is also named
   `ableton-osc`, which is not a Python identifier. The test scaffold must prove
   its import path before any dispatcher tests are written.
3. `OSCServer.__init__` binds a real UDP socket — but it accepts `local_addr`
   and `remote_addr`, so tests can construct it with
   `local_addr=("127.0.0.1", 0)` and point `remote_addr` at a plain receiver
   socket bound to an ephemeral port. `process_message` can then be driven
   directly with messages built by the vendored
   `pythonosc.osc_message_builder.OscMessageBuilder` — no Live, no fixed
   ports, no conflict with Seshat's 11001.

Deliverable: `tests_unit/conftest.py` providing

- a narrowly scoped module loader that recreates Live's package layout without
  executing either Remote Script `__init__.py`: create a synthetic test-only
  root package whose `__path__` is the repository root, expose `pythonosc/` as
  its `pythonosc` subpackage, expose `abletonosc/` as a namespace-style
  `abletonosc` subpackage, then import
  `<synthetic_root>.abletonosc.osc_server`. This preserves the production
  module's relative imports instead of rewriting them or stubbing Live. Include
  a dedicated import smoke test so the loader cannot fail only when the first
  real test is collected;

- a `server` fixture: `OSCServer` on ephemeral ports, shut down in teardown;
- a `receiver` fixture: UDP socket + helper that drains and OSC-decodes
  everything the server sent (address + params), with a short deadline;
- a `dispatch(server, address, *args)` helper that builds the datagram and
  calls `server.process_message(OscMessage(dgram), ("127.0.0.1", <port>))`.

No production code changes in this phase. `pytest` is the only external test
dependency for this temporary suite; record the exact interpreter and pytest
version used and invoke it as `python3 -m pytest tests_unit/`. Dependency
metadata and the permanent test layout remain issue #6, but this PR must not
claim a regression gate unless that command has actually run successfully.

---

## Phase 1: rework the dispatch core (#1, #2, #5)

All three defects live in `process_message`
([abletonosc/osc_server.py:95-167](abletonosc/osc_server.py#L95-L167)), and the
direct and wildcard branches currently duplicate the send/validate logic with
different error behavior. Fix all three by extracting one helper used by both
branches.

### 1a. Shared dispatch helper

Add a private method, shape roughly:

```python
def _dispatch(self, callback, callback_address, message, remote_addr,
              reply_address=None, error_address=None) -> None:
    # reply_address: address to send a non-None result on
    #   (direct: message.address; wildcard: the concrete callback_address)
    # error_address: address echoed in the /live/error envelope
    #   (direct: message.address; wildcard: the pattern the client sent)
```

Inside `_dispatch`, one `try` block covers **both** the callback call and the
return-value validation:

```python
try:
    rv = callback(message.params)
    if rv is not None and not isinstance(rv, tuple):
        raise TypeError("callback for %s returned %s; handlers must return "
                        "a tuple or None"
                        % (callback_address, type(rv).__name__))
except Exception as e:
    <existing structured-error path>   # log with osc_request_error marker,
    return                             # send /live/error ("request", ...)
if rv is not None:
    <existing reply send>
```

This resolves **#5** by construction: validation is an explicit raise inside
the same boundary that produces the structured `/live/error`, it is immune to
  `python -O` (no `assert`), it names the request and the offending handler, and
  it applies identically to direct and wildcard dispatch because both go through
  `_dispatch`. Do not include `repr(rv)` in the error: an invalid return may be
  large, sensitive, or capable of making the error datagram itself exceed UDP
  limits. Delete both `assert isinstance(rv, tuple)` statements
([osc_server.py:135](abletonosc/osc_server.py#L135),
[osc_server.py:160](abletonosc/osc_server.py#L160)).

### 1b. Correct wildcard matching (#1)

Replace [osc_server.py:142-144](abletonosc/osc_server.py#L142-L144):

```python
regex = message.address.replace("*", "[^/]+")
...
if re.match(regex, callback_address):
```

with an escaped, anchored translation compiled once per request:

```python
pattern = re.compile("[^/]+".join(re.escape(part)
                                  for part in message.address.split("*")))
...
if pattern.fullmatch(callback_address):
```

Contract decisions this encodes (to be stated in the docs, see Phase 4):

- **`*` matches one or more non-`/` characters within a single address
  segment.** `[^/]+` is retained deliberately — it is the existing observable
  behavior for every non-buggy match, and changing to the OSC-1.0 `[^/]*`
  (zero-or-more) would silently widen what existing Seshat patterns match.
- **`*` is the only supported metacharacter.** `re.escape` makes OSC pattern
  characters `?`, `[]`, `{}` and any regex character (`.`, `+`, `(`…) literal.
  This is a documented non-goal, not an accident.
- **Patterns match complete registered addresses only** (`fullmatch`), so
  `/live/*/get/tempo` can no longer reach `/live/scene/get/tempo_enabled`, and
  `/live/track/get/*` no longer reaches `/live/track/get/clips/name` (the `*`
  cannot cross the `/` in `clips/name`).

### 1c. Isolate fan-out failures (#2)

In the wildcard branch, each matched callback is dispatched independently and
a failure never terminates the loop. Two failure classes, decided as follows:

- **Known compatibility exceptions — skip, log at debug, continue.** Preserve
  the existing wildcard behavior for `ValueError` and `AttributeError`, and add
  only the confirmed `IndexError` case that currently aborts fan-out when a
  matched endpoint needs an omitted positional argument. Do **not** silently
  add `TypeError` or `KeyError`: both commonly indicate a real handler defect,
  and none of these broad exception classes proves an argument-shape mismatch.
  This is a deliberately minimal compatibility rule until issue #15 gives
  routes explicit argument schemas. Every skip names the concrete callback in
  a debug log.
- **Any other exception (and non-tuple returns) — structured error,
  continue.** The `/live/error` envelope keeps the existing 5-field shape and
  echoes **the pattern address the client actually sent** in the address slot,
  because that is the only address the client can correlate a pending request
  against. The concrete callback address goes into the detail string, e.g.
  `"in /live/scene/get/tempo_enabled: <detail>"`. The paired log line names
  both. This removes the "legacy uncorrelated error" outcome entirely.

Mechanically: the wildcard branch becomes

```python
for callback_address, callback in self._callbacks.items():
    if not pattern.fullmatch(callback_address):
        continue
    try:
        self._dispatch(callback, callback_address, message, remote_addr,
                       reply_address=callback_address,
                       error_address=message.address)
    except _WildcardSkip:          # ValueError/AttributeError/IndexError only;
                                   # or the check lives inside _dispatch
        continue                    # _dispatch behind a wildcard flag
```

(Exact mechanism — a `wildcard=True` flag on `_dispatch` vs. a pre-check — is
an implementation detail; the flag is simpler and keeps one try block.)

Delete the now-false comment block at
[osc_server.py:116-119](abletonosc/osc_server.py#L116-L119) claiming the
wildcard branch is "deliberately left on legacy behaviour".

### Phase 1 tests (`tests_unit/test_osc_server.py`)

Matching (#1):
- `/live/*/get/tempo` matches `/live/song/get/tempo` and
  `/live/scene/get/tempo` but **not** `/live/scene/get/tempo_enabled`
  (regression for the confirmed live defect).
- `/live/track/get/*` does not match `/live/track/get/clips/name`.
- A pattern containing regex metacharacters (`/live/song/get/temp.` or `+`)
  while also containing `*` matches those characters literally rather than
  behaving as a regex.
- Leading, trailing, multiple, and consecutive `*` cases pin their chosen
  one-or-more, single-segment behavior; no wildcard may cross `/`.
- A wildcard with no match sends nothing and does not raise.
- Direct (non-wildcard) lookup is byte-exact and unaffected.

Fan-out isolation (#2):
- Register three callbacks matching one pattern; the middle one raises
  `IndexError` → the other two still reply (regression for the confirmed
  defect), no `/live/error` is sent for the skip.
- Middle one raises `RuntimeError` → the other two still reply **and** one
  `/live/error` arrives with `params[0] == "request"`, `params[1] == <pattern>`,
  and the concrete address inside the detail.
- Middle callbacks raising `TypeError` and `KeyError` each produce a structured
  error and do not stop later matches; they are not mistaken for signature
  incompatibility.
- Replies from wildcard fan-out carry the concrete callback address, as today.

Reply validation (#5):
- Direct callback returning a `list` → structured `/live/error` naming the
  address; no reply datagram; the server keeps dispatching subsequent
  messages.
- Same for a wildcard match returning a non-tuple; remaining matches still run.
- Callback returning `None` sends nothing; returning `()` sends an empty reply
  (current behavior, pinned).

---

## Phase 2: correlate generic method/property failures (#4)

### 2a. Let handler exceptions reach the dispatcher boundary

[abletonosc/handler.py:27-45](abletonosc/handler.py#L27-L45): remove the
`try/except`-and-log in `_call_method` and `_set_property` so exceptions
propagate. Keep the `info`-level call/set logging lines.

The comment in `_call_method` justifying the local catch ("a failure would
unwind through the dispatcher and abort the rest of the messages queued on
this tick") is obsolete: since the structured-error divergence, and now
Phase 1, **every** callback invocation is caught per-message inside
`_dispatch`, and `process()` additionally has its per-datagram catch
([osc_server.py:224-234](abletonosc/osc_server.py#L224-L234)). An exception
from `_set_property` now becomes
`/live/error ("request", <address>, <detail>, <argc>, *args)` with full
request correlation, and the tick queue continues. Delete the comment along
with the catch.

`_get_property`'s `RuntimeError → None` handling
([handler.py:48-55](abletonosc/handler.py#L48-L55)) is intentional
inapplicable-property semantics, not error suppression — leave it.

This moves the resilience mechanism; it does not remove the behavior introduced
from upstream PR #208. A method failure is caught per callback by `_dispatch`,
so later messages in the same bundle and later queued datagrams still execute.
SESHAT.md's existing PR #208 section must be revised to attribute queue
resilience to the dispatcher boundary rather than claiming `_call_method`
itself catches the exception.

### 2b. Define the scope of the correlated-error contract

[manager.py:53-85](manager.py#L53-L85) needs **no change** for generic handler
exceptions: the
`osc_request_error` marker already suppresses double-sends for records emitted
by the dispatcher boundary, and once handlers stop logging errors themselves,
`("log", message)` on `/live/error` is left meaning exactly what issue #4
permits — unsolicited internal errors not attributable to a request (socket
errors, reload failures).

Do **not** claim that every semantic request failure in the fork now uses
`/live/error`. Custom browser and return/master handlers deliberately return
endpoint-specific tuples containing `"error"`; view steering setters
deliberately log and remain silent; `song/get/track_data` can log and return
partial output. Redesigning those contracts is outside this PR. The scope here
is precisely:

- uncaught exceptions from ordinary callbacks;
- exceptions from the generic `_call_method` path; and
- exceptions from the generic `_set_property` path.

Audit `logger.error` request paths and record the existing exceptions to the
canonical contract, but do not casually add `osc_request_error`: that marker
means a structured `/live/error` was already sent. If duplicate legacy log
datagrams from handlers that return inline error tuples are addressed here, use
a separately named no-relay marker or lower the relay-eligible severity only
after treating that as an explicit behavior change. It is acceptable—and
safer for this PR—to leave those pre-existing custom-handler duplicates for a
follow-up under issues #4/#15.

### 2c. Seshat compatibility work (required before merge)

Failures that today arrive as `("log", message)` will arrive as
`("request", address, detail, argc, *args)`. That is the *intended* fix — it
adds request context while keeping the queue alive. Seshat's decoder is already
known to branch on `params[0] == "request"` vs `"log"` and validates the
address, argument count, and echoed wire arguments before correlating an error.

The functional benefit must not be overstated. Seshat sends generic setters and
methods with `Transport.send_message/2`, which is fire-and-forget and returns
once UDP transmission succeeds. A later structured error is broadcast for
observability but cannot retroactively fail that completed tool step. Only an
address-and-argument match against an active `Transport.query/3` fails fast.
Honest mutation acknowledgement/read-back is separate work.

The dispatcher refactor will break Seshat's source-level merge guard even if
runtime behavior is correct: `vendored_addresses_test.exs` currently greps for
the exact fragment `("request", message.address, detail, ...)`. The companion
Seshat update must:

- update that guard to assert the refactored structured send semantically rather
  than depend on the old local variable;
- update `docs/abletonosc-api-docs.md` where wildcard failures are currently
  documented as uncorrelated `"log"` messages;
- run the Transport and vendored-address tests; and
- update the AbletonOSC submodule pointer/install verification when this fork
  commit is consumed.

Record the compatibility result and the fire-and-forget limitation in SESHAT.md.

### Phase 2 tests

`handler.py` imports `ableton.v2`, which does not exist outside Live, so
`AbletonOSCHandler` cannot be unit-tested directly without a stub. Two-level
approach:

- **Unit (in `tests_unit/`):** the dispatcher-boundary behavior is already
  proven by Phase 1 tests (a raising callback yields the structured
  envelope). Add one test with a callback that mimics the new `_set_property`
  (raises on `setattr`) to pin the end-to-end envelope for setter-style
  failures.
- **Live smoke (manual, per the HANDOFF procedure):** against a running
  instance, send a known-bad set using a value known to be rejected by Live and
  a non-mutating invalid method target such as deleting an impossible track
  index, and verify in the installed log that a
  single structured error is recorded and no `("log", …)` duplicate is
  relayed. Wrap any mutation in `begin_undo_step`/`end_undo_step` and restore
  state, per [HANDOFF.md](HANDOFF.md) rules.
- **Resilience:** exercise a bundle containing a failing generic method followed
  by a successful getter, plus separately queued datagrams in the same order.
  The getter must still run and the failure must produce exactly one structured
  error. These checks explicitly preserve PR #208's behavior after moving the
  catch.

---

## Phase 3: correct the stale committed tests (#7)

These are live-integration tests; they cannot run in this environment (port
11001 is Seshat's) — the corrections are reviewed statically and validated the
next time the live suite is run under issue #6's harness. Scope is exactly the
three defects; no restructuring (that is #6).

1. **[tests/test_application.py:14-17](tests/test_application.py#L14-L17)** —
   `test_application_error` asserts the pre-fork unstructured payload
   (`response[0] == "Error handling OSC message: Index out of range"`).
   It also sends the failing request *before* `await_message()` installs its
   `/live/error` handler, leaving a timing race. Rewrite the test so the handler
   and synchronization event are installed before the request is sent, then
   assert the final Phase-1/2 envelope:

   ```python
   # Pseudocode: install /live/error capture first, then send and wait.
   response = capture_after_send(
       client, "/live/error",
       lambda: client.send_message("/live/clip/get/color", (0, 10)))
   assert response[0] == "request"
   assert response[1] == "/live/clip/get/color"
   # response[2] is the human-readable detail — assert it is a non-empty
   # string, not its exact wording
   assert response[3] == 2
   assert response[4:] == (0, 10)
   ```

   Keep the capture helper local to the live-integration tests unless it belongs
   naturally in the later issue-#6 harness. Not pinning the detail wording keeps
   the test from re-staling when messages improve.

2. **[tests/test_clip_slot.py:32](tests/test_clip_slot.py#L32)** — the
   listener started with `(0, 0)` is stopped with `(0,)`, so the stop fails
   and leaks the listener until reload. Change to
   `client.send_message("/live/clip_slot/stop_listen/has_clip", (0, 0))`, and
   move the stop into a `try/finally` around the test body so the listener is
   released even when an intermediate assertion fails (the leak was the
   defect; leaving cleanup unprotected would preserve it under failure).

3. **[tests/__init__.py:11-14](tests/__init__.py#L11-L14)** — the module
   imports `TICK_DURATION` (0.150s) from the client and immediately shadows it
   with `0.125`. Delete the local reassignment and its comment so the client's
   constant — which already documents the tick-plus-overhead policy — is the
   single timing source. `wait_one_tick()` and `test_clip_slot.py`'s
   `TICK_DURATION * 2` waits get slightly *longer*, which is
   safe-by-direction for timing-based tests. The module-scope
   `/live/api/reload` side effect on lines 28-30 stays put — removing it is
   issue #6's call, and yanking it here would silently change what code the
   live suite exercises.

---

## Phase 4: documentation and SESHAT.md

Per [issues.md](issues.md): every further divergence must be reflected in
[SESHAT.md](SESHAT.md). One docs commit at the end (or folded per phase):

- **SESHAT.md**: update the existing PR #208 resilience entry and the structured
  error entry, plus any new divergence text needed for (a) escaped/anchored wildcard
  semantics and the `*`-only pattern language, (b) the fan-out
  failure-isolation contract including the deliberately narrow skip-exception set and the
  pattern-address error correlation, (c) reply-type validation replacing the
  `assert`, (d) `_call_method`/`_set_property` failures now emitting the
  structured request envelope instead of `("log", …)`, while remaining
  fire-and-forget from Seshat's caller perspective, plus the Phase-2c companion
  Seshat verification result.
- **README.md** (line 32 wildcard paragraph): state the supported syntax
  precisely — `*` only, matches one or more non-`/` characters, whole-address
  matching, per-match replies on concrete addresses, mismatched-signature
  endpoints skipped, other failures reported on `/live/error` with the
  pattern address. Document the `/live/error` `("request", …)` envelope as
  the error contract for uncaught callback exceptions and failures in the
  generic method/property paths; explicitly distinguish custom handlers that
  return inline `"error"` tuples and intentionally silent view steering.
- The full README endpoint-inventory overhaul remains issue #14/#15.

---

## Decisions locked by this plan (flag now if disagreed)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | `*` keeps `[^/]+` (one-or-more) semantics, not OSC-1.0 zero-or-more | Preserves every currently-working match; widening is a separate contract change |
| 2 | `?`, `[]`, `{}` are literal characters, not patterns | Matches current reality; `re.escape` makes it explicit and safe |
| 3 | Fan-out preserves the existing `ValueError`/`AttributeError` skips and adds only the reproduced `IndexError`; `TypeError`/`KeyError` are structured failures | Exception type is not a reliable signature schema. This is the narrow compatibility fix until route metadata exists |
| 4 | Wildcard errors correlate on the **pattern** address; concrete address rides in the detail | The pattern is the only address the client has a pending request under |
| 5 | Handler `_call_method`/`_set_property` stop catching; dispatcher owns their request errors | One correlated envelope for uncaught callbacks and the generic method/property paths; tick-queue safety remains at the boundary |
| 6 | New unit tests live in top-level `tests_unit/` until issue #6 restructures `tests/` | Importing `tests/` reloads the live API; unit tests must be collectable side-effect-free |
| 7 | Correlated errors from fire-and-forget setters/methods improve context but do not fail the completed Seshat send | `Transport.send_message/2` has no in-flight request to resolve; mutation acknowledgement is separate work |
| 8 | Custom inline error envelopes and intentionally silent steering remain out of scope | Calling the result “one contract for all failures” would be inaccurate and would substantially broaden the PR |

## Commit sequence

1. `tests_unit/` scaffolding (fixtures + helpers, no production change)
2. Phase 1: dispatch core (`osc_server.py`) + its unit tests — issues #1, #2, #5
3. Phase 2: handler error propagation (`handler.py`) + logger.error audit + unit test — issue #4
4. Phase 3: stale test corrections (`tests/`) — issue #7
5. Phase 4: SESHAT.md + README wildcard/error-contract docs
6. Companion Seshat change: source guard, API docs, relevant Elixir tests, and
   submodule/install update after the fork commit is available

## Verification

- `python3 -m pytest tests_unit/` green without Live (new regression gate for #1/#2/#5
  and the #4 envelope).
- Live smoke per the HANDOFF log-observation method: re-run the three
  original probes (`/live/*/get/tempo 0` → exactly the two tempo handlers;
  `/live/*/get/tempo` with no args → song replies, scene skipped, no abort;
  bad setter and invalid method target → one structured `/live/error` each, no
  `("log", …)` duplicate, and a following message in the same bundle/queue still
  runs),
  under undo-step protection with state restored.
- Run Seshat's Transport tests and updated vendored-address guard. Confirm that
  matching query errors still fail fast, unrelated/fire-and-forget structured
  errors are only broadcast, and the submodule/install copy contains the fork
  change before release.
