# Seshat companion handoff for OSC dispatch hardening

## Purpose and status

This document describes the Seshat-side work required when
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) lands in the AbletonOSC fork.
The Python implementation is planned but not yet complete at the time of this
handoff. Do not update Seshat's submodule pin or source-level guards until the
fork commit containing the final implementation exists.

The work spans two repositories:

- **AbletonOSC fork:** implements corrected wildcard matching, per-callback
  wildcard failure isolation, explicit callback return validation, and
  correlated errors for the generic method/property paths.
- **Seshat:** consumes that fork as the `priv/AbletonOSC` git submodule,
  documents its OSC contract, and carries source-level merge guards for the
  Python behavior that Seshat depends on.

The expected result is a fork commit followed by a Seshat commit that updates
the submodule pin, tests, and documentation together. Editing Python is not
complete from Seshat's perspective until the pin is bumped, the installed
Remote Script is refreshed, and Live has restarted or safely reloaded it.

## Why Seshat needs a companion change

The AbletonOSC refactor changes both behavior and source structure:

1. Wildcard patterns will match complete registered OSC addresses, with literal
   address text escaped. This removes prefix overmatching such as
   `/live/*/get/tempo` reaching `/live/scene/get/tempo_enabled`.
2. One wildcard callback failure will no longer abort later matches. Known
   compatibility exceptions are skipped per callback; unexpected exceptions
   produce a structured `/live/error` and fan-out continues.
3. Callback return validation moves inside the structured error boundary and no
   longer uses `assert`.
4. Exceptions from generic `_call_method` and `_set_property` callbacks move
   from their local log-only catches to the dispatcher boundary. The queue
   resilience introduced from upstream PR #208 remains: later bundle messages
   and later queued datagrams still execute.
5. The structured `/live/error` send moves out of the exact-match body in
   `process_message` and into a shared dispatch helper. Seshat currently greps
   for the old local source expression, so its merge guard will fail even when
   the new implementation is correct.

The Seshat transport already understands both error shapes:

```text
/live/error ["request", address, message, arg_count, ...request_args]
/live/error ["log", message]
```

It correlates the first shape only when its address and wire arguments match the
active query. No Transport protocol change is expected. The work is primarily a
submodule update, a guard update, and documentation correction.

## Behavior Seshat must continue to rely on

These are release invariants, not optional implementation details:

- A direct callback exception produces exactly one `"request"`-tagged
  `/live/error`, echoing the request address, argument count, and original wire
  arguments.
- An unexpected wildcard callback exception produces the same envelope using
  the wildcard pattern address for correlation. The concrete registered address
  that failed remains present in the human-readable detail/log context.
- Records already sent as structured errors retain the
  `osc_request_error` marker, and `manager.py`'s log relay does not emit a second
  `"log"` copy.
- A matching structured error fails an active `Transport.query/3` immediately;
  malformed, mismatched, late, or `"log"` errors remain broadcasts and do not
  answer a query.
- A failing callback does not stop later messages in the same OSC bundle or
  later UDP datagrams queued for the same Live tick.
- Wildcard replies continue to use their concrete callback addresses. This
  change does not define or repair the separate multi-track `"*"` getter
  contract from AbletonOSC issue #3.
- Custom browser and return/master handlers may still return endpoint-specific
  tuples containing `"error"`. Intentionally silent view-steering endpoints
  remain silent. The Python PR does not normalize every semantic rejection in
  the fork onto `/live/error`.

## Important fire-and-forget limitation

Seshat sends generic setters and methods with
`Seshat.OSC.Transport.send_message/2`. That API is explicitly fire-and-forget:
it returns after the UDP send succeeds, before Live processes the request.

After the Python change, a failed generic setter or method carries better
request context on `/live/error`, but it does **not** retroactively fail the
already completed `send_message/2` call or its originating tool step. With no
matching query in flight, Transport broadcasts the structured error for
observability and answers nobody. Honest mutation acknowledgement or read-back
confirmation is separate future work.

Seshat documentation must not claim that this change makes mutations
synchronous or reliably reported to the tool caller. The benefit is consistent
request-context diagnostics while preserving the bridge's queue resilience.

## Required Seshat changes

### 1. Update the AbletonOSC submodule pin

**Path:** `priv/AbletonOSC`

After the fork implementation has been committed and pushed, advance the
submodule from the current pin to that exact commit. Confirm that the pinned
tree contains all of the following from the AbletonOSC plan:

- escaped, whole-address wildcard matching;
- per-match wildcard exception isolation;
- explicit tuple-or-`None` callback return validation inside the dispatcher
  error boundary;
- generic `_call_method`/`_set_property` exception propagation to that boundary;
- Live-free dispatcher regression tests;
- corrected legacy Python integration tests; and
- updated fork `README.md` and `SESHAT.md`.

The Seshat commit must stage the submodule gitlink, not copy equivalent Python
files into the parent repository. A fresh checkout must resolve the same commit
with `git submodule update --init`.

### 2. Update the structured-error source guard

**Path:** `test/seshat/osc/vendored_addresses_test.exs`

The test around the current lines 639–673 assumes that the error envelope is
built directly in `process_message` and asserts this exact fragment:

```text
("request", message.address, detail,
```

That assertion will become stale when the shared dispatch helper uses an
`error_address` parameter for direct requests and wildcard patterns. Rewrite the
guard against the final implementation structure. It must continue to protect
the behavior Seshat actually needs:

- the dispatcher sends `/live/error` with the `"request"` tag;
- the selected correlation address is included;
- `len(message.params)` and every `message.params` value are echoed;
- the record carries `extra={"osc_request_error": True}`;
- both direct and wildcard callback paths use the guarded boundary; and
- callback return validation cannot escape that same boundary.

Do not replace one brittle exact-source check with another that merely happens
to match the first refactor. Prefer several small assertions tied to the final
helper's semantic ingredients and explanatory failure messages that name the
lost invariant. Seshat's guard is still a source tripwire—`mix test` cannot run
the Python inside Live—but it should tolerate harmless local-variable and
formatting changes.

Keep the existing `manager.py` assertions that the relay tags uncorrelated
errors with `"log"` and skips records carrying `osc_request_error`.

Add or extend the merge guard for the new wildcard invariants if the final fork
source has stable semantic markers worth protecting: literal escaping,
whole-address matching, and continuation after an individual match failure.
The fork's own Python unit tests are the primary behavioral coverage; Seshat's
grep exists to catch an incorrect submodule update or future upstream merge.

### 3. Update the canonical OSC API documentation

**Path:** `docs/abletonosc-api-docs.md`

Revise the Status Messages section and wildcard documentation to reflect the
new contract:

- The `"request"` envelope applies to uncaught direct callback exceptions,
  unexpected wildcard callback exceptions, and failures propagated from the
  generic method/property handlers.
- A wildcard structured error names the pattern address in its correlation
  field; the concrete callback address is carried in its diagnostic detail.
- Known wildcard compatibility exceptions are skipped per match and do not stop
  later matches.
- Wildcard failures are no longer categorically part of the uncorrelated
  `"log"` row. That description is currently stale.
- `*` is the fork's only supported pattern metacharacter, matches one or more
  non-`/` characters, and is matched against the complete registered address.
  Other regex/OSC pattern characters are literal under this fork's documented
  subset.
- Replies from successful wildcard matches retain the concrete registered
  callback address.
- Generic setter/method errors are observable as structured errors but their
  normal Seshat calls remain fire-and-forget; no mutation acknowledgement is
  implied.
- Custom inline error envelopes and intentionally silent view steering remain
  distinct contracts.

Preserve the existing explanation of `arg_count`, exact wire-argument matching,
32-bit OSC float comparison, and why false-positive correlation is more harmful
than a timeout.

### 4. Update Seshat's architecture/context documentation

**Paths:** `CLAUDE.md`, and any current non-archived document that describes the
old exact-match implementation

Update references that say the structured payload lives specifically in
`process_message`'s exact-match branch. The new description should say it lives
at the shared per-callback dispatcher boundary used by direct and wildcard
requests.

Update the PR #208/resilience explanation to state that generic method/property
exceptions propagate to this boundary, where they are caught without aborting
the rest of a bundle or tick queue. Do not say that `_call_method` still owns the
catch.

The current `CLAUDE.md` discussion around the bridge module map and the shipped
failed-query correlation should remain accurate after the refactor. Update its
source-location wording and add the fire-and-forget limitation where relevant.

Review `docs/ROADMAP.md`'s shipped failed-query-correlation history. Historical
measurements and decisions should remain historical, but statements presenting
the exact-match branch as the current architecture should be updated or
qualified. Do not rewrite archived plans as though they described the new
implementation; archived plans are point-in-time records.

### 5. Confirm that Transport code requires no behavioral change

**Paths:** `lib/seshat/osc/transport.ex`,
`test/seshat/osc/transport_test.exs`

The existing Transport behavior should already be compatible. Verify rather
than redesign it:

- a matching `"request"` envelope fails the active query with
  `{:error, {:live_error, message}}`;
- the correlation requires matching address, arity, and wire arguments;
- wildcard pattern addresses can be correlated when that exact pattern is the
  active query address;
- a structured error with no active query is broadcast only;
- an unrelated structured error does not fail another query; and
- `"log"` errors remain uncorrelated broadcasts.

Add a Transport test for a wildcard-pattern correlation only if the existing
suite does not already prove that arbitrary address strings—including `*`—are
matched byte-for-byte. Add or clarify a fire-and-forget test showing that an
unsolicited structured error after `send_message/2` is broadcast and does not
manufacture a completed-call failure.

No production Transport change is expected unless verification disproves one
of these assumptions.

## Verification

### Pure Seshat verification

Run from the Seshat repository after advancing the submodule:

```text
mix test test/seshat/osc/transport_test.exs
mix test test/seshat/osc/vendored_addresses_test.exs
mix test
```

The full suite is safe with Live open because Seshat's tests inject isolated
ephemeral UDP ports and do not target AbletonOSC's production ports.

Also confirm:

- `git submodule status priv/AbletonOSC` reports the intended fork commit with
  no leading `-`, `+`, or `U`;
- the updated source guard reads the pinned Python file, not another checkout;
- no Elixir caller was changed to treat fire-and-forget mutation errors as
  synchronous replies; and
- current documentation consistently distinguishes structured request errors,
  uncorrelated log errors, and inline endpoint error envelopes.

### Installed bridge verification

Pure Seshat tests do not execute the Python Remote Script. After the Seshat
commit points at the new fork version:

1. Run `mix abletonosc.install` so Live's installed copy receives the pinned
   submodule contents.
2. Restart Ableton Live, or use `/live/api/reload` only if the AbletonOSC reload
   path is known safe for the final implementation.
3. Confirm Live is bound to `127.0.0.1:11000` and Seshat to
   `127.0.0.1:11001`; the refactor must not weaken the fork's loopback-only
   security policy or fixed reply routing.
4. Run the AbletonOSC live smoke probes from `HANDOFF.md` and the implementation
   plan: anchored wildcard matching, wildcard continuation after an incompatible
   callback, one structured error without a `"log"` duplicate, and successful
   execution of a message following a failing generic method in the same bundle
   and queue.
5. Observe that Seshat still fails a matching bad getter query quickly with an
   Ableton rejection, while a failed fire-and-forget setter/method is only an
   asynchronous diagnostic unless a later read-back detects it.

Do not stop Seshat-owned Live listeners during the smoke run. Wrap real
mutations in `begin_undo_step`/`end_undo_step` and restore project state, as
documented in [HANDOFF.md](HANDOFF.md).

## Delivery order

1. Complete, test, commit, and push the AbletonOSC fork implementation.
2. In Seshat, advance `priv/AbletonOSC` to that exact commit.
3. Update Seshat's vendored source guard and current documentation in the same
   Seshat change as the pin bump.
4. Run targeted and full `mix test` verification.
5. Commit the Seshat submodule pin, tests, and docs together.
6. Run `mix abletonosc.install`, restart/reload Live, and complete live smoke
   verification.

This order prevents Seshat documentation and guards from describing Python that
its pinned submodule does not yet contain, and prevents Live smoke tests from
accidentally exercising an older installed copy.

## Explicitly out of scope

- Changing `Seshat.OSC.Transport.send_message/2` into a request/acknowledgement
  protocol.
- Making generic setters or methods synchronously fail their originating tool
  calls.
- Redesigning custom browser, return/master, or view error envelopes.
- Fixing AbletonOSC's separate `/live/track/get/<prop> "*"` multi-track reply
  contract.
- The full AbletonOSC endpoint inventory and test-harness redesign tracked by
  later issues.
