# This fork

`jpatricknola/AbletonOSC` is a fork of [ideoforms/AbletonOSC](https://github.com/ideoforms/AbletonOSC),
maintained as the bridge for [Seshat](https://github.com/jpatricknola/seshat) —
an AI assistant for Ableton Live. Seshat consumes this repository as a git
submodule at `priv/AbletonOSC`; `mix abletonosc.install` copies the tree
wholesale into the user's Remote Scripts directory.

This file lists **every divergence from upstream**, and is the thing to keep
current when a commit lands here. Before the fork, Seshat's additions lived as
four files patched into the user's install at install time, which made the delta
self-describing by construction. A fork loses that property unless someone
writes it down. This is that.

## Why the fork exists

Two things could no longer be done by patching upstream's install:

1. **A second override.** Seshat's extensions ride on `add_handler` being a
   dict assignment — register an address again and the later registration wins.
   That works for handlers. Upstream PR #213 fixes a one-line logger bug in
   `clip_slot.py` that raises a `RemoteScriptError` on *every* clip operation;
   there is no handler seam to override, only the file itself.
2. **Editing upstream's own files.** Upstream PR #208's resilience fixes live in
   the handler base class and in the OSC server's `process()` tick. No
   `add_handler` seam exists there at all.

Upstream is dormant (last merge 2025-11-16, 33 PRs open, some since 2023), so
waiting for these fixes to arrive by upgrade was not a strategy, and the fork's
ongoing cost — merging upstream releases — is close to zero.

## Divergences from upstream

### Fixes to upstream's own code

- **`handler.py` — `_stop_listen` unbinds from the stored object.** Upstream
  unbinds the listener from the target it is *handed*. Listeners are keyed by
  track/return index but bound to a LOM object, and indices renumber when
  something is deleted or reordered: delete track 0 of `[A, B, C]` and index 0
  now means B, so a re-subscribe hands the base class B while the stored
  callback belongs to A. `B.remove_name_listener` raises, the base swallows it
  as "likely benign", and the dict entry is dropped anyway — leaving A's
  listener alive forever, still pushing under index 0. `_start_listen` already
  records the true object in `listener_objects`; `_stop_listen` now reads it.

- **`track.py` — mixer listeners join the same bookkeeping.**
  `_start_mixer_listen` never populated `listener_objects`, so `_clear_listeners`
  (which iterates *all* of `listener_functions`) raised `KeyError` on script
  reload whenever a volume or panning listener was active. And
  `_stop_mixer_listen` re-resolved the `DeviceParameter` from the passed track,
  reproducing the wrong-object unbind above. Both now key as
  `("value", (*params, prop))` with the `DeviceParameter` stored, and stopping
  delegates to the fixed base `_stop_listen`.

- **`device.py` — parameter listeners join the same bookkeeping.** The same two
  bugs as `track.py`'s mixer listeners, in the third place upstream listens to a
  `DeviceParameter`: the key was `('device_parameter_value', …)` and
  `listener_objects` was never populated, so `_clear_listeners` raised on reload
  whenever a parameter listener was active — and since `Manager.clear_api`
  iterates its handler list unguarded, every handler after `DeviceHandler`
  (Seshat's three among them) then kept listeners bound to the dead song object.
  Now keyed `("value", (track, device, parameter))` with the `DeviceParameter`
  stored, stopping delegates to the base `_stop_listen`. Also removes a
  `NameError` in the no-listener warning path, which referenced an unbound
  `prop`.

- **`clip_slot.py` — logger format args.** Cherry-picked from upstream PR #213.
  `self.logger.info(track_index, clip_index, rv)` passes an `int` where a format
  string belongs, raising inside every clip-slot callback and flooding Live's
  `Log.txt`.

- **`handler.py` / `osc_server.py` — per-message resilience.** The behaviour is
  upstream PR #208's — one failing message no longer aborts the rest of that
  tick's queue, which matters because Seshat sends ordered multi-message
  sequences — but the mechanism has moved since it was first hand-applied.
  `process()` keeps its try/except inside the recvfrom loop, per #208. The
  handler-local catches are gone: `_call_method` and `_set_property` now let
  exceptions propagate, because every callback invocation is caught
  per-message by `OSCServer._dispatch`, which turns the failure into the
  structured `/live/error ("request", …)` envelope described below instead of
  an uncorrelatable log line. Later messages in the same bundle and later
  queued datagrams still execute; `tests_unit/test_handler_envelope.py` pins
  both properties without Live.

  **Not taken from #208:** its reply-to-sender-port routing. Listener pushes go
  to the fixed response port regardless, so that change buys nothing here and
  touches reply correlation.

### Deliberate changes to upstream's behaviour

Not bug fixes and not extensions: places where upstream works as intended and
this fork intends something different. Both of these are **security** changes,
so treat any merge that reverts one as a regression, not a preference.

- **`osc_server.py` — the OSC socket binds loopback only.** Upstream's
  `OSCServer.__init__` defaults `local_addr` to `('0.0.0.0', OSC_LISTEN_PORT)`,
  i.e. every local IPv4 interface. That is a reasonable default for upstream,
  whose users drive Live from phones, tablets and other machines on the LAN. It
  is the wrong default here: every OSC address can control Live, there is no
  authentication anywhere on the wire, and Seshat's only client is on the same
  machine. The default is now `('127.0.0.1', OSC_LISTEN_PORT)`. `Manager`
  constructs `OSCServer()` with no arguments and logs `_local_addr`, so the new
  bind is used and visible in `Log.txt` with no other change.

- **`osc_server.py` — the default reply address is never retargeted.** Upstream's
  `process()` reassigned `self._remote_addr` to the source of the most recent
  datagram, so listener pushes, `/live/startup`, `/live/error` and `/live/test`
  followed whichever client spoke last. (Upstream's own comment concedes this
  prevents listeners from more than one IP.) That assignment is gone; the default
  remote stays `('127.0.0.1', OSC_RESPONSE_PORT)` as constructed. The
  per-callback reply path in `process_message()` is untouched — it still answers
  the originating hostname on the response port, which after the bind change can
  only be loopback.

  **Merge hazard.** Either change is easy to lose: nothing fails, and locally
  everything keeps working, because loopback traffic is unaffected by both. The
  regression is silent remote exposure. Seshat's `vendored_addresses_test` greps
  this file's `osc_server.py` for the loopback default and for the absence of the
  `_remote_addr` assignment, and for this section of `SESHAT.md`. If a networked
  controller (TouchOSC and friends) is ever wanted, it gets an **explicit opt-in
  bind constant plus a security design** — do not restore the wildcard default.

### Additions to upstream's code

- **`clip.py` — `quantize` in the generic methods list.** From upstream PR #198
  (that PR's warp-marker and extended-note work is not taken). Gives
  `/live/clip/quantize track_id, clip_id, grid, amount` via the existing
  `_call_method` path. `grid` is Live's `GridQuantization` enum — **not**
  `RecordingQuantization`, and **not** what this file said until 2026-07-31.
  The enum was measured against a running Live on that date (one clip per
  value, probe notes chosen so every candidate grid lands distinguishably,
  `amount` 1.0, read back with `/live/clip/get/notes`, identical in 4/4 and
  6/8):

  | Value | Grid | | Value | Grid |
  |---|---|---|---|---|
  | 0 | no grid | | 5 | **1/16** |
  | 1 | 1/4 | | 6 | 1/16 triplet |
  | 2 | 1/8 | | 7 | 1/16 triplet |
  | 3 | 1/8 triplet | | 8 | 1/32 |
  | 4 | 1/8 triplet | | ≥9 | invalid — nothing moves |

  So sixteenths is **5**, not `8`. The previous claim here (`g_8_bars=1 …
  g_half=5, g_quarter=6, g_eighth=7, g_sixteenth=8, g_thirtysecond=9`) was
  wrong in every row, as was the matching claim that there are no triplet
  grids — 1/8T and 1/16T are reachable, and only this way. There is no 1/2
  grid and no bar-length grid. Whether the song's `swing_amount` colours the
  result is **unverified** — the property is now settable (see the `song.py`
  entry below), so this is finally testable, but it has not been tested.

  Seshat's `quantize_clip` never puts these integers in front of the model: it
  takes a string grid (`"1/16"`, `"1/8T"`, …) and maps it in one private
  function, `Seshat.Tools.Handlers.grid_quantization/1`, so a future
  correction is a one-line change. The address **never replies**, so a wrong
  integer is silent everywhere except in Live.

- **`song.py` — `swing_amount` in `properties_rw`.** One line in the existing
  list, which the generation loop turns into `/live/song/get/swing_amount`,
  `/live/song/set/swing_amount`, and the matching `start_listen`/`stop_listen`.
  Upstream lists `groove_amount` but not `swing_amount`, and the two are not
  interchangeable: `Song.groove_amount` (LOM, 0.0–1.3 in practice — Ableton's
  own Move script clamps it to `GROOVE_AMOUNT_MAX = 1.3125` and renders it as
  `round(min(x, 1.3) * 100)`%) only *scales* grooves already assigned to clips
  from the Groove Pool, and nothing in this bridge can assign one
  (`Clip.groove` is an unserializable LOM object — see the `clip.py` TODO). So
  on a set with no grooves assigned, upstream's knob does nothing at all.
  `Song.swing_amount` (LOM: float, get/set/observe, 0.0–1.0, "affects MIDI
  Recording Quantization and all direct calls to `Clip.quantize`") is the
  property that makes plain MIDI swing, and it is what Seshat's
  `set_swing_amount` and its session mirror need. The property is present in
  Live 12 Suite's own LOM table (`_MxDCore/LomTypes.pyc`) and both read and
  written by Ableton's Push code (`pushbase/quantization_component.pyc`, which
  also holds a `@listens('swing_amount')` slot — so the generated listener is
  sound), where the user-facing encoder clamps it into 0.0–0.5.

  Because these addresses are generated by a loop rather than written as
  literals, Seshat's `vendored_addresses_test` cannot see them the usual way;
  it greps this file's `song.py` for `swing_amount` instead. An upstream merge
  that drops the line is otherwise invisible — every other song address still
  answers, and swing sets fail the silent way all OSC fails.

- **`song.py` — `begin_undo_step` and `end_undo_step` in the generic methods
  list.** Two lines in the existing list, which the loop turns into
  `/live/song/begin_undo_step` and `/live/song/end_undo_step` (no arguments, no
  reply, exactly like `undo`). `Song.begin_undo_step()` / `Song.end_undo_step()`
  demarcate one undo step explicitly: everything a control-surface script
  changes between the two calls collapses into a single entry in Live's undo
  history. It is the same mechanism Ableton's own Push script uses
  (`pushbase/undo_step_handler.pyc` in Live's shipped Remote Scripts).

  Without them, Live groups script-driven mutations into undo steps by its own
  rules, and those rules are activity-sensitive: measured on Live 12.4.3
  (2026-08-01), `create_track` then `write_midi_notes` collapsed into **one**
  undo step — a single undo deleted the whole track, notes and all — while the
  same pair with an intervening timed-out call landed as two. Seshat wraps every
  tool dispatch in a `begin`/`end` pair (`Seshat.Tools.Handlers.call/2`) so one
  tool call is exactly one undo step.

  Behaviour measured on Live 12.4.3 (2026-08-01) and relied upon by the Elixir
  side: an empty `begin`/`end` pair leaves the undo history untouched (so
  read-only tools can be wrapped too, and no mutating-tool list has to be kept
  in sync); an unmatched `end` is logged as an ordinary method call with no
  exception and no history effect; and `begin` does **not** refcount — with two
  outstanding, the first `end` closes the step. A leaked `begin` therefore
  self-heals at the next wrapped call's `end`.

  Because these addresses are generated by the loop rather than written as
  literals, Seshat's `vendored_addresses_test` cannot see them the usual way; it
  greps this file's `song.py` for both names instead, the same way it does for
  `swing_amount`. An upstream merge that drops either line is otherwise
  invisible — the sends still go out, nothing answers them anyway, and undo
  silently goes back to reverting whole conversations.

- **`view.py` — `/live/view/show_view`, `/live/view/hide_view`,
  `/live/view/get/is_view_visible` and `/live/view/set/detail_clip`.** The
  first Seshat addresses to live in an upstream file rather than in a handler of
  our own: they belong to the View API by every other measure, and splitting them
  into a fourth module would put two `ViewHandler`s in `manager.py`. Upstream can
  *select* a track, scene, clip or device but cannot bring the pane those live in
  into view, put a pane away, or report which panes are open —
  `Application.View.show_view`, `.hide_view`, `.is_view_visible` and
  `song.view.detail_clip` have no OSC address at all. Seshat's view steering
  (every mutating tool ends by showing what it changed) needs the first:
  selecting a clip nobody can see is not confirmation that anything happened.

  The three setters are **silent**, like upstream's setters — an unknown view
  name or an empty clip slot is logged to `Log.txt` and nothing goes on the wire,
  because a steering send must never fail or delay the tool it follows.
  `get/is_view_visible` is the exception and follows the fork's getter rule
  instead: it **always replies**, `[view_name, "ok", 1|0]` or
  `[view_name, "error", message]`, echoing the name it was asked about, because
  a caller waits on it and silence must mean only "this extension isn't
  installed". Live raises on an unrecognised name there — unlike `show_view`,
  which ignores one — so the error arm is reachable and costs a fast reply
  rather than a guard timeout.

  `hide_view` passes its name through verbatim like the others, but only
  `Browser` and `Detail` truly hide (measured against Live 12 Suite,
  2026-07-31): hiding `Session` shows Arranger and vice versa, and hiding
  `Detail/Clip` or `Detail/DeviceChain` flips the detail panel to its other tab
  rather than closing it. Seshat's `hide_view` tool therefore offers a narrower
  enum than this file accepts.

- **`osc_server.py` + `manager.py` — `/live/error` carries the request that
  failed.** Upstream catches a raising callback nowhere near the callback: the
  exception unwinds out of `process_message()` into `process()`'s per-datagram
  `except`, which is the only place it is logged, and by then `message.address`
  and `message.params` are long out of scope. The log record is relayed onto
  `/live/error` by `manager.py`'s `LiveOSCErrorLogHandler`, so what reaches a
  client is one formatted string — `"Error handling OSC message: Index out of
  range"` — with nothing in it to say *which* request died. A client that just
  sent a query cannot tell whether that error is its own, so it can only wait
  out its timeout. For Seshat, whose whole query pipeline is serialized behind
  one in-flight request, a vanished track index therefore stalled every OSC read
  in the process for a full five seconds.

  Both dispatch branches now funnel through one private helper,
  `OSCServer._dispatch`, which invokes the callback with both halves of the
  request still in hand and sends a two-shape contract on the same address:

  | Payload | Meaning |
  |---|---|
  | `["request", address (s), message (s), arg_count (i), *request_args]` | The request `address` + `request_args` failed in its handler callback; `message` is the exception text. `address` is always the address **the client actually sent** — for a wildcard request that is the pattern, the only address the client can correlate a pending request against, and the concrete callback address rides in `message` as `"in <callback_address>: <detail>"`. Sent **instead of** a reply — the request gets no other answer. |
  | `["log", message (s)]` | An AbletonOSC error with no originating request (parse failures, socket errors, reload failures, a handler's own internal error logs). Never correlatable. |

  The correlated contract covers exactly: uncaught exceptions from ordinary
  callbacks (both direct and wildcard dispatch), exceptions from the generic
  `_call_method` path, exceptions from the generic `_set_property` path, and
  invalid (non-tuple, non-`None`) handler return values. It does **not** cover
  every semantic rejection in the fork — see the scope note below.

  `arg_count` makes the variable tail explicit and keeps a zero-argument request
  from needing a special case. `request_args` are `message.params` echoed back
  through `OscMessageBuilder`, so each keeps its wire type — note that an OSC
  `f` is 32-bit, so a client comparing the echo against what it sent must
  round-trip its own value through 32 bits first.

  The structured send goes out **directly via `self.send`**, not through the log
  relay, because the relay has no request context; the record is marked
  `extra={"osc_request_error": True}` and `LiveOSCErrorLogHandler.emit` skips
  marked records, so one failure produces exactly one datagram. (Measured on
  Live 12.4.3, 2026-08-03: the embedded `logging` does deliver `extra` through
  to a sibling handler's `record`.) The file log keeps its error-level line
  either way, now with the offending address in it. `str(e) or
  type(e).__name__` guards the empty-message case: a bare `Exception()`
  stringifies to `""`, which would render as a blank rejection in a client.

  **Wildcard matching is escaped and anchored.** Upstream compiled the raw
  request address as a regex (`address.replace("*", "[^/]+")`, matched with
  `re.match`), so `/live/*/get/tempo` also reached
  `/live/scene/get/tempo_enabled`, `/live/track/get/*` reached
  `/live/track/get/clips/name`, and any regex metacharacter in a pattern was
  interpreted as regex. Patterns now compile as
  `"[^/]+".join(re.escape(part) for part in address.split("*"))` and are
  matched with `fullmatch`. The contract this encodes: **`*` is the only
  supported metacharacter** (OSC's `?`, `[]`, `{}` and every regex character
  are literal — a documented non-goal, not an accident); `*` matches **one or
  more** non-`/` characters within a single address segment (`[^/]+` is kept
  deliberately — switching to OSC-1.0's zero-or-more would silently widen what
  existing Seshat patterns match); and patterns match **complete registered
  addresses only**. Replies from wildcard fan-out still go out on the concrete
  callback address, as before.

  **Wildcard fan-out failures are isolated.** Upstream ran matches in one
  try-free loop, so a matched callback raising anything outside
  `ValueError`/`AttributeError` aborted the remaining matches. Each match now
  dispatches independently through `_dispatch` and a failure never terminates
  the loop. The legacy skip set — endpoints that simply don't apply to the
  pattern request — is preserved **narrowly**: `ValueError`, `AttributeError`,
  and (new, the confirmed abort case) `IndexError`, when a matched endpoint
  reads a positional argument the pattern request omitted. Skips are logged at
  debug naming the concrete callback and send nothing. `TypeError` and
  `KeyError` are deliberately **not** in the set — both commonly indicate a
  real handler defect, and no broad exception class proves an argument-shape
  mismatch — so they, and every other exception, become the structured
  `("request", <pattern>, "in <callback>: <detail>", …)` error above while the
  remaining matches still run. Widening the skip set waits on per-route
  argument schemas (issue #15). The former "legacy uncorrelated error" outcome
  for wildcard failures is gone entirely.

  **`IndexError` is qualified by argument count** (`_is_wildcard_skip`), because
  the class alone carries both meanings. Live's LOM raises
  `IndexError("Index out of range")` from an out-of-range collection subscript
  — verified in `logs/abletonosc.log`, traceback through `track.py`'s
  `self.song.tracks[track_index]` — and that is the single most common way a
  request is legitimately refused. An unqualified skip would answer
  `/live/track/get/* 99` with **nothing at all**: no reply, no error,
  indistinguishable from a pattern that matched no endpoint, on the fork's most
  frequent rejection. The reproduced abort case is the opposite shape — a
  pattern carrying *no* index reaching an endpoint that reads `params[0]` — so
  `IndexError` is skipped only when `message.params` is empty, and a bad index
  (which always arrives as the argument that produced it) always reports. The
  residual imprecision is deliberately one-sided: a multi-argument pattern
  reaching an endpoint that wants one argument more than it sent (e.g.
  `/live/device/get/* 0 0` and an endpoint reading `params[2]`) reports instead
  of skipping — a correlated error naming that endpoint, with every other match
  still replying. Issue #15's per-route schemas are what remove the guess.

  **Wildcards are a fan-out, not a query — do not reach for them as a batching
  shortcut.** A pattern produces one reply per matched endpoint, each on its own
  concrete address, plus possibly an error on the pattern address. Seshat's
  `Transport.query/3` awaits a single reply, and its `/live/error` clause is
  ordered first and cancels the timer, so a wildcard sent through it resolves on
  whichever datagram lands first and discards the rest — and one failing match
  fails the whole query even while the other endpoints reply successfully.
  Correlating the error on the pattern is still right (the concrete address has
  no pending request to match, which is exactly the uncorrelated error this
  change removed); the mismatch is cardinality, so a fully successful wildcard
  is just as wrong through `query/3`, only silently. `query_batch/2` over the
  concrete addresses is the answer. Nothing in Seshat sends a wildcard today.

  **Reply validation replaced the `assert`.** Upstream checked handler return
  values with `assert isinstance(rv, tuple)` — stripped under `python -O`, and
  an uncorrelated crash otherwise. A non-tuple, non-`None` return now raises an
  explicit `TypeError` inside the same boundary, so it comes back as the
  structured error naming the request and the offending handler, identically
  for direct and wildcard dispatch. The error deliberately names only the
  return's *type*, never its repr — an invalid return may be large, sensitive,
  or capable of pushing the error datagram past UDP limits. A `None` return
  still sends nothing; `()` still sends an empty reply.

  Bundles are covered for free, since `process_bundle` funnels every message
  through `process_message`. `process()`'s outer `try`/`except` stays, guarding
  parse errors; callback failures no longer reach it.

  **Scope: what still doesn't use the correlated envelope.** Audited 2026-08-04
  across every `logger.error` request path. Custom browser and
  return/master handlers deliberately reply with endpoint-specific tuples
  containing `"error"` (and their paired `logger.error` lines still relay a
  duplicate legacy `("log", …)` datagram for the same failure — known, left
  for issues #4/#15 as an explicit behaviour change rather than smuggled in
  here); view-steering setters deliberately log and stay silent;
  `song/get/track_data` can log and return partial output. Only the
  dispatcher boundary sets the `osc_request_error` marker — it means "a
  structured `/live/error` was already sent", and nothing else may claim it.

  **Fire-and-forget caveat.** Seshat sends generic setters and methods with
  `Transport.send_message/2`, which returns once UDP transmission succeeds. A
  structured error arriving later is broadcast for observability but cannot
  retroactively fail that completed tool step; only an address-and-argument
  match against an active `Transport.query/3` fails fast. Honest mutation
  acknowledgement/read-back is separate work. The gain from this change is
  context — which request died, with its arguments — not delivery semantics.

  **Companion Seshat update (required before this commit is consumed, not yet
  done as of 2026-08-04).** Seshat's `vendored_addresses_test.exs` greps this
  file's `osc_server.py` for the exact fragment
  `("request", message.address, detail, …)`, which the `_dispatch` refactor
  renamed (the send now reads `("request", error_address, detail, …)`), so the
  guard will fail against this commit until it is updated to assert the
  refactored send semantically. The same companion change must update
  `docs/abletonosc-api-docs.md` where wildcard failures are documented as
  uncorrelated `"log"` messages, record there that wildcards must not be sent
  through `Transport.query/3` (see the fan-out note above — `query_batch/2` is
  the answer), re-run the Transport and vendored-address tests, and bump the
  AbletonOSC submodule pointer / install verification.
  Record the compatibility result here when that lands.

  `LiveOSCErrorLogHandler.emit` also loses upstream's
  `message[message.index(":") + 2:]`, which raises `ValueError` on any error
  message with no colon in it — swallowed by `logging`, so the relay silently
  dropped that error rather than sending it. A `partition(": ")` strip keeps the
  whole message when there is no prefix.

  **Merge hazard.** Losing either half in a merge is completely invisible: every
  address still answers, every error still shows up in `Log.txt`, and clients
  just quietly go back to paying a full timeout per rejection. Seshat's
  `vendored_addresses_test` greps `osc_server.py` for the structured payload
  (historically the fragment `("request", message.address, …)`; after the
  `_dispatch` refactor its target must be the `("request", error_address, …)`
  send — see the companion-update note above), `manager.py` for the
  `("log", …)` tag and the `osc_request_error` check, and this file for this
  section. `tests_unit/test_osc_server.py` and
  `tests_unit/test_handler_envelope.py` pin the behaviour itself without Live.

### Seshat's own handlers

Three modules that upstream has no equivalent of. Each carries its own header
comment explaining what it adds and why. They are registered at the end of
`manager.py`'s handler list; position is not load-bearing.

- **`abletonosc/browser.py`** — `/live/browser/*`. Upstream exposes no browser
  API at all. Indexing, search, load-onto-track, bulk export to JSON, and
  preview. `load_item`'s ok reply carries the loaded device's **index** as well
  as its name — `[track_index, uri, "ok", name, device_index]`, where
  `device_index` is the position in `track.devices` that
  `/live/view/set/selected_device` and the `/live/device/*` addresses take, and
  `-1` when the device isn't on the chain yet (asynchronously instantiating
  VST/AU plugins). `load_item` does not always append at the end (an
  instrument lands *before* existing audio effects), and a same-named device
  can already be on the chain, so `_loaded_device` disambiguates by diffing
  the post-load chain against a snapshot taken immediately before the load —
  the device that's new — falling back to a name match, then the last device,
  when diffing doesn't resolve it. Without the index, steering the view onto a
  freshly loaded device would cost a second round trip to re-read the whole
  chain.

  `/live/browser/load_item_on_return [return_index, uri]` and
  `/live/browser/load_item_on_master [uri]` are the same load aimed at the two
  chains upstream can't reach — `browser.load_item` loads onto
  `song.view.selected_track`, which accepts a return or the master perfectly
  well, so all three endpoints share one implementation and differ only in
  target resolution and reply shape. They are separate addresses rather than a
  widened `load_item` so the shipped address keeps its exact shape and the reply
  arity says which index space was targeted:
  `[return_index, uri, "ok", return_name, device_name, device_index]` and
  `[uri, "ok", device_name, device_index]`. The return's name is read back
  **after** the load, because Live renames an empty return the moment its first
  device lands (`A-Return` → `A-Reverb`, measured 2026-07-31).

  Both carry a guard `load_item` doesn't need. Measured 2026-07-31 on both a
  return and the master: loading a *non-effect* item with one of them selected
  does not fail — Live silently creates a new MIDI track and loads the
  instrument there, leaving the target chain untouched. So a return/master load
  is verified twice, by the set's track count being unchanged and by the
  target's chain having gained a device; either check failing is an error reply
  naming what actually happened. The stray track is deliberately **not** deleted
  — reporting it and letting the caller offer to remove it is the lesson of
  Seshat's removed `create_project`.

  `/live/browser/export` takes **no arguments** and chooses its own destination:
  it creates a uniquely named file with `tempfile.mkstemp` inside
  `~/.seshat/browser-exports` (owner-only, created on demand) and returns the
  absolute path it wrote — `[export_path, "ok", total_items]`, or
  `["", "error", message]`, which never names a partial file. It used to take a
  `dest_path` and open it with Live's privileges; that request form is now
  rejected with an error reply and an error-level log line, and nothing is
  written. Since only this handler knows an export's name, it is also the only
  thing that can sweep up an export whose reply never reached the caller: a
  startup-and-pre-export sweep deletes matching **regular** direct children of
  the export root (`os.lstat`, so a symlink is skipped rather than followed) that
  are at least ten minutes old. The age gate keeps an overlapping caller's
  finished export alive — the caller reads the file only after its reply
  arrives, outside any transport ordering, so a later export's pre-sweep can
  run mid-read — while
  bounding how long an orphaned multi-megabyte file survives. The export root is
  derived with `expanduser` + `abspath`, **not** `realpath`, because the Elixir
  consumer derives the same string with `Path.expand/1` and validates the reply
  path against it.
- **`abletonosc/return_track.py`** — `/live/return_track/*` and `/live/master/*`.
  Upstream's track addresses resolve through `song.tracks` only, so return
  tracks and the master are unreachable. `/live/return_track/select` is the same
  gap one level up: `/live/view/set/selected_track` indexes `song.tracks` too, so
  no upstream address can select a return. `song.view.selected_track` itself
  accepts any track — the master included — so that handler is the lookup and
  nothing more, and it is silent, for the same reason as the two view addresses
  above.

  The file covers the whole mixer (name, volume, panning, mute and solo per
  return; volume, panning and cue volume on the master) and the whole **device
  chain**, because every `/live/device/*` address, `/live/track/delete_device`
  and `/live/view/set/selected_device` resolves through `song.tracks` as well:
  `get/devices`, `device/get/name`, `device/get/parameters`,
  `device/get|set/parameter/value`, `device/get/parameter/value_string`,
  `delete_device` and `select_device`, each in a return-indexed and a master
  form. Two departures from upstream's spelling are deliberate. The list getters
  **combine** what upstream splits — one `get/devices` reply carries
  `count, (name, type, class_name)×N` where upstream needs three round trips,
  and one `device/get/parameters` reply carries
  `device_name, count, (name, value, min, max)×N` where upstream needs five —
  because the caller wants all of them together and assembling parallel lists
  from separate replies risks describing two different devices. And
  `delete_device` **replies** (`[…, "ok", remaining]`) where upstream's is
  silent: it is a method with a real failure path, and the alternative is
  sandwiching it between two count reads.

  The master deliberately offers no `mute`, `solo` or `arm`: reading one raises
  `RuntimeError("Main track has no 'mute' property!")` rather than returning
  something falsy (measured 2026-07-31), so `hasattr` feature-detection is
  unsafe on a LOM object and the addresses simply do not exist. Returns have no
  `arm` either.

  The mixer listeners are keyed `(index, "volume")` / `(index, "panning")` /
  `("master", "cue_volume")` and so on, **not** by the bare index. The base
  class's `_stop_listen` derives `remove_value_listener` from the *prop* half of
  the key, which forces every DeviceParameter listener to register under
  `"value"` — so the discriminator has to live in the params half, or
  subscribing a return's pan would silently evict its volume listener.
- **`abletonosc/song_structure.py`** — `/live/song/{start,stop}_listen/tracks`
  and `.../return_tracks`. Upstream can only listen to *scalar* song properties,
  so nothing fires when tracks are added, deleted or reordered by hand.

`browser.py`'s `preview_item` / `stop_preview` use the Live API calls proven by
upstream PRs #204 and #192, with Seshat's own URI resolution and reply envelope.

## Merge hazards

Read this before merging anything from upstream.

Remotes are local config, so a fresh checkout of this repo (including the
submodule checkout `git submodule update --init` creates in Seshat) has only
`origin`. Merging or cherry-picking from upstream needs, once per clone:

    git remote add upstream https://github.com/ideoforms/AbletonOSC.git

- **PRs #182 / #185 rename `/live/clip_slot/duplicate_clip_to` to
  `duplicate_to`, with no alias.** Seshat's `duplicate_clip` tool depends on the
  old name. Merging either PR silently breaks it — silently, because OSC is
  fire-and-forget UDP and an unknown address just does nothing. If you take
  those PRs, either keep an alias registration or update Seshat in the same
  change. Seshat's `audit-osc` workflow is the verifier: it checks every
  `/live/` address in Seshat's `lib/` against the API docs.

- **Anything touching `OSCServer.__init__`'s defaults or `process()`.** The
  loopback bind and the removed reply retargeting are both one-liners against
  upstream, and reverting either is invisible from the machine Live runs on —
  loopback keeps working exactly as before. See the deliberate-changes section
  above.

- **Anything touching `process_message()`, `_dispatch`, or
  `LiveOSCErrorLogHandler.emit`.** The structured `/live/error` payload lives
  in `OSCServer._dispatch` and `manager.py`'s relay and nowhere else. A merge
  that takes upstream's `process_message` drops `_dispatch` wholesale — the
  `("request", …)` send, the escaped/anchored wildcard matching, the fan-out
  isolation, and the reply-type validation, and it reintroduces the handler
  exceptions that `handler.py` no longer catches locally (turning every
  generic method/setter failure back into an aborted tick queue). One that
  takes upstream's `emit` drops the `("log", …)` tag and the
  `osc_request_error` skip, which leaves the structured send *and* a duplicate
  legacy line going out for the same failure. Neither is loud: errors still
  reach `Log.txt` and `/live/error`, and clients just go back to timing out.
  `tests_unit/` fails loudly on most of this — run it on every merge. See the
  additions section above.

- **Anything touching `song.py`'s generic methods list or `properties_rw`.**
  Three entries there are ours — `begin_undo_step`, `end_undo_step` and
  `swing_amount` — and each is a single quoted string inside a list upstream
  also edits, so a merge that takes upstream's version of the list drops them
  without a conflict. Losing the two undo entries doesn't break anything
  loudly: the sends still go out over UDP and nothing answers them either way,
  and undo quietly reverts whole conversations again. Seshat's
  `vendored_addresses_test` greps for all three names for exactly this reason.

- **Anything touching `_stop_listen`, `_start_listen`, or `listener_objects`.**
  The wrong-object unbind fix above is small and easy to lose in a merge. Its
  symptom is invisible — every address still answers, and the mirror just
  quietly reports one track's name under another's index.

## Contributing back

The base-class listener fix and the mixer-listener bookkeeping are general bugs,
not Seshat-specific, and would be worth filing upstream if it revives. Doing so
is a courtesy, never a dependency.
