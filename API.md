# AbletonOSC API Reference

> The canonical address list for this fork — every address the installed
> Remote Script registers, its arguments, its reply shape, and the behaviour
> measured against real Live where that differs from what the code suggests.
> [README.md](README.md) keeps upstream's original tables and prose; where the
> two disagree, this file is right and the README is upstream's. Addresses
> marked "Seshat extension" exist only in this fork — [SESHAT.md](SESHAT.md)
> lists every divergence from `ideoforms/AbletonOSC`, including fixes to
> upstream's own code, and [FORK_GAPS.md](FORK_GAPS.md) lists what the Live
> Object Model offers that has no address here yet.
>
> This fork is consumed by [Seshat](https://github.com/jpatricknola/seshat)
> as a git submodule at `priv/AbletonOSC`, installed with
> `mix abletonosc.install`; Seshat's `vendored_addresses_test` checks that
> every address registered in Python appears in this file. Notes below that
> name Seshat modules (`Seshat.OSC.Transport`, tool names) record how the
> consumer reacts to a wire fact, and stay here because the wire fact is what
> they rest on.
>
> Protocol: OSC over UDP
> Send commands to: **`127.0.0.1:11000`**
> Reply port: 11001
> The fork binds its command socket to loopback only, so nothing off this
> machine can reach any address below. Callback replies go to the originating
> host — which can therefore only be loopback — on port 11001, and listener
> pushes, `/live/startup` and `/live/error` go to a fixed `127.0.0.1:11001` that
> incoming traffic never retargets. Upstream binds `0.0.0.0` and follows the
> last sender; see `SESHAT.md`, and don't widen either without the
> deployment-gated work in Seshat's `docs/evaluating/SECURITY_BACKLOG.md`.
> Wildcard patterns supported (e.g., `/live/clip/get/* 0 0` queries all properties of track 0, clip 0).

---

## Conventions the address tables don't show

### Address naming is not fully regular

Do not derive an address by analogy. Some real examples that break the pattern:

- Track panning is `/live/track/set/panning`, not `.../pan`.
- Device parameters are `/live/device/set/parameter/value` (singular `parameter`
  for one, plural `parameters` for the bulk getters).
- Device *count* is on the track: `/live/track/get/num_devices`.
- Scene and clip-slot operations are on `/live/song/...` and
  `/live/clip_slot/...` respectively, not under a `/live/scene/` create verb.

A wrong address gets no reply on the request's address. The server logs
`Unknown OSC address: /live/...` at ERROR, and the log relay forwards that as
`/live/error ["log", "Unknown OSC address: /live/..."]` — uncorrelatable to the
request, so a caller waiting on the reply address still times out. The symptom
is a tool that reports success while nothing moves in Ableton.

### Listener pattern

**Scalar** properties can be subscribed to:

```
/live/<object>/start_listen/<property>  [index_args...]
/live/<object>/stop_listen/<property>   [index_args...]
```

Changes are then pushed to 11001 as if they were get replies:

```
/live/<object>/get/<property>  [index_args..., new_value]
```

Upstream registers `start_listen` only for the scalars in each handler's
hardcoded property list. A property holding a *list of LOM objects* — `tracks`,
`return_tracks` — is not in any of them, so nothing upstream fires when a track
is added, deleted or reordered. Those two are fork additions, in
`abletonosc/song_structure.py`, which pushes a tuple of names via the base
class's optional `getter` argument. Don't assume a property is listenable
because it is gettable; check the handler's list first.

Because pushes and query replies share a shape, a client that correlates
replies by address will also receive listener pushes as if they were replies
— a consumer's decode path has to expect both.

Two gotchas that don't show in the address tables:

- **An index-keyed listener must be unbound from the object it was registered
  on.** Listeners are keyed by index but bound to a LOM object, and indices
  renumber on delete or reorder. Unbinding from the target you were *handed* is
  the wrong object after a renumber — it fails silently, the base swallows it as
  "likely benign", and the old listener keeps pushing under an index that now
  means someone else. Upstream did exactly that; the fork's base `_stop_listen`
  resolves through `listener_objects` instead, so every handler gets it right by
  default. Don't hand-roll a stop that passes an index-resolved object.
- **`/live/startup` invalidates every listener.** AbletonOSC sends it whenever
  its control surface initialises (Live launching, a set loading, the surface
  toggled). Every listener registered against the previous song object is dead
  by then, so a client mirroring state must treat it as a full refresh +
  re-subscribe. Without that a mirror is stale permanently, not just until the
  next change.

### Object-valued reads

Some LOM members hold another LOM object rather than a number or a string —
`Song.appointed_device`, `Track.group_track`, `ClipSlot.clip`, and
`Song.View`'s `selected_chain`, `selected_parameter`, `mod_mapping_device` and
`mod_mapping_parameter`. The generic property loops cannot put one of those on
the wire (the value is unencodable, so it becomes an error or a `None`), so
each has a hand-written handler that answers with **indices into the
collections the existing address families already accept**. The rules, which
every later object-valued read follows:

1. An object-valued member never enters the generic property loop.
2. The reply names the object by index, prefixed by the track-identity
   category (see **Selected-track identity** under the View API) when the
   owning track can be any of the three kinds:

   | Kind of member | Reply shape | Example |
   |---|---|---|
   | Track-valued, regular tracks only | `track_index` | `/live/track/get/group_track` |
   | Clip-valued, in a slot the request already names | `clip_index` | `/live/clip_slot/get/clip` |
   | Device-valued | `category, track_index, device_index` | `/live/song/get/appointed_device` |
   | Parameter-valued | `category, track_index, device_index, parameter_index` | `/live/view/get/selected_parameter` |
   | Chain-valued | `category, track_index, device_index, chain_index` | `/live/view/get/selected_chain` |

   `category` is `"track"`, `"return_track"` or `"master"` — exactly the
   address family that reaches that track — so a reply is directly
   actionable: a device triple maps onto `/live/track/device/*`,
   `/live/return_track/device/*` or `/live/master/device/*` respectively.
3. **`-1` means "none, or not representable at top level"**: no group track,
   an empty clip slot, or a device nested inside a rack chain, which has no
   index in `track.devices` and no address that reaches it until a path
   resolver exists.
4. When the member itself is `None`, the category slot carries the
   **reply-only category `"none"`** and every index is `-1`. `"none"` never
   appears anywhere but a reply, and no setter accepts it — the same half of
   the convention as "`-1` is an answer, never an argument".
5. Replies are fixed-arity: a given address always answers the same number of
   fields, whatever it found.
6. **Getters never error for a "none" reason** — that is an answer, and it
   goes on the wire. A genuine resolution failure (an object in none of the
   collections, an exhausted `canonical_parent` ascent) raises and arrives as
   a structured `/live/error` on the **request** path, loudly. A *listener
   push* has no such envelope: the getter runs inside Live's own listener
   callback, outside `OSCServer._dispatch`'s per-message catch, so a
   resolution failure there kills that push with nothing on the wire and only
   Live's `Log.txt` to show for it — the same accepted limit as
   `start_listen/selected_track_identity`.
7. Every object-read handler logs its resolution at info level, because the
   installed `logs/abletonosc.log` is the only evidence channel when another
   client holds the reply port.

⚠️ **The `canonical_parent` ascent is not measured yet.** Every reply above a
bare index is resolved by climbing `canonical_parent` from the object until a
track is reached (chain → rack device → track; parameter → device → track).
That is Ableton's own idiom — `Push2/track_selection` in Live 12.4.3's shipped
`MIDI Remote Scripts` climbs `canonical_parent` off a `Live.Chain` to reach a
track (read from the installed bundle, 2026-08-27) — but it has not been
exercised against a running Live from this fork, and neither has cross-class
`==` between a device/chain/parameter and a track. The ascent is bounded (16
levels) and fails loudly, so a wrong assumption surfaces as a structured
`/live/error` naming the object rather than a wrong index or a hung UI thread.

The setter side is deliberately narrow: `/live/song/set/appointed_device` is
the only one, it takes the same triple its getter replies, and it *validates*
every argument — an unknown category (`"none"` included), a negative or
out-of-range index, and a master index other than `0` are each a `ValueError`
arriving as a structured `/live/error`, never a Python negative-index
wrap-around. It reaches top-level devices only, and cannot un-appoint.

⚠️ **Seshat extension.** All nine object-valued reads (`track/get/group_track`,
`clip_slot/get/clip`, the `song/…/appointed_device` trio and the four
`view/get/…` rows) are added by this fork; none exists in stock AbletonOSC.
`Track.group_track` is the only one of the seven members that is not
observable, so it is the only one that could not have a listen pair even if a
consumer asked. Without the install they are unknown addresses: the getters
never reply and the setter silently does nothing.

### Queries that raise instead of replying

Some queries make AbletonOSC raise internally. **Since the dispatch-boundary
rework (2026-08-03), that fails fast, not silently:** the fork's `osc_server.py` sends a
structured `/live/error ["request", address, message, arg_count,
...request_args]` naming the request that raised, and `Seshat.OSC.Transport`
matches it against the in-flight query and returns `{:error, {:live_error,
message}}` in roughly one AbletonOSC tick instead of waiting out
`@query_timeout` (5,000ms) — see Transport's "Failed-query correlation"
section for the matching rules and their residual collision classes. A caller
still gets *no distinguishing value back* — `describe_error/1`'s message says
Ableton rejected the request, not which guard to add — so guard rather than
diagnose after the fact:

> **Setters and generic methods raise too, and it buys you nothing.** The
> fork's dispatch-boundary rework widened the correlated envelope past
> callbacks that reply: a failing `/live/*/set/*` or a failing generic method
> now comes back with its own address and arguments as well. That is a
> diagnostic gain, not a delivery-semantics one. Seshat sends those with
> `Transport.send_message/2`, which returns as soon as UDP transmission
> succeeds, so the tool step is already complete and reported by the time the
> error lands — it is broadcast on `"osc:in"` and answers nobody. A setter that
> must be *known* to have landed still needs a guard before it or a read-back
> after it (`set_track_send` and `set_device_parameter` are the patterns).

- **An index that doesn't exist** — a track, slot, or scene index past the end
  of the set raises `IndexError` inside the callback. This is the single most
  common cause of a rejected query, so guard error messages should lead with
  "check the index", not "is Ableton running".
- **Clip queries against an empty slot** (`.clip` is `None` upstream) — check
  `/live/clip_slot/get/has_clip` first, as `get_clip_notes` and
  `Registry.ensure_clip/3` do. Notes queries against an *audio* clip likewise
  raise — check `/live/clip/get/is_midi_clip`.
- **`/live/clip/get/notes` range args are all-or-nothing** — the handler raises
  unless it gets exactly 0 or 4 of `start_pitch, pitch_span, start_time,
  time_span`. If any is given, fill all four (`Handlers.note_range_args/1`).
- **Audio-only clip properties on a MIDI clip** — `gain`,
  `gain_display_string`, `warp_mode`, `warping`. Check
  `/live/clip/get/is_midi_clip` first, as
  `get_clip_properties`/`set_clip_properties` do — but **not because they
  raise**. Measured 2026-08-05 on Live 12.4.3: each replies normally with a
  `nil` value (`/live/clip/get/gain [0, 0, nil]`), because Live raises
  `RuntimeError` and `AbletonOSCHandler._get_property` converts exactly that
  into `None` as deliberate inapplicable-property semantics — the one branch
  the 2026-08-05 dispatch-boundary merge left untouched. So the guard exists to
  avoid presenting meaningless nils, not to avoid an error, and a query for one
  costs a round trip rather than failing fast. This entry previously said they
  raise; that was never measured, and a smoke test written on it failed
  immediately. What *does* raise is a clip query against an **empty slot**,
  above.

A install still running the pre-2026-08-03 copy (no `mix abletonosc.install`
since, or a Live restart still pending) is unaffected by any of the above and
keeps the old behaviour: no reply at all, then a full timeout.

### Measuring the Live API without building the feature first

Plenty of questions about the Live Object Model can't be answered from source —
what `browser.load_item` does with an instrument while a return is selected,
whether an assignment sticks, what a parameter's real range and display string
are. They can be *measured* in minutes, without a Live restart and without
writing any of the feature. The rig (validated 2026-07-31, Live 12.4.3):

1. **Add a temporary probe handler to the installed copy**, at
   `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc/return_track.py`
   — never this repo. No commit, no pin bump, nothing to revert in git.
   `return_track.py` is on `reload_imports`' list, which is why it's the
   convenient host.
2. **Trigger it with fire-and-forget UDP to 11000** — `/live/api/reload`
   (registered in `manager.py`, re-imports the handler modules and re-runs
   `init_api`) then your probe address. Sending only, so you never bind 11001
   and never contend with a running client for AbletonOSC's fixed reply
   port. A dozen lines of `socket.sendto` with hand-rolled OSC padding is
   enough; no reply plumbing is needed.
3. **Read the answers out of Live's own log**, not off the wire:
   `~/Library/Preferences/Ableton/Live <version>/Log.txt`, where
   `self.logger.info` lands. Prefix every line with something greppable and
   record the log's line count first so you can read only what your run added.
4. **Restore with `mix abletonosc.install`, then reload again**, and confirm
   the probe address is gone (it logs `Unknown OSC address`).

Two rules for the probe itself. **Snapshot before mutating and undo after** —
record device lists and track counts at the start, delete only what the probe
created, restore the previous selection, and delete a return track the probe
added. **Wrap every measurement in its own `try`/`except` and log the
exception**: reading `master_track.mute` raises `RuntimeError` rather than
returning falsy, so one unguarded probe line aborts the rest of the run, and
`hasattr` is not a safe feature test on LOM objects.

Ask before running one. It writes into the user's Remote Scripts and reloads
the bridge under a live session, and a probe that loads devices mutates a real
set — cheap to undo, but the user's call, and the answer may be "that session
is a scratch set, go ahead."

**The no-probe variant — checking an existing address against the running
instance.** When the question is "does the installed script do what this doc
says", no probe handler is needed (validated 2026-08-03, Live 12.4.3):

- First `diff -rq` this repo against the installed copy; the answers only
  describe the installed one.
- Replies can't be captured: they go to `127.0.0.1:11001`, held by Seshat's
  `beam.smp` (no `SO_REUSEPORT` on its socket, so the port can't be shared).
  Send from a plain UDP socket to `127.0.0.1:11000` — the vendored `pythonosc`
  builds datagrams (`OscMessageBuilder(addr).add_arg(x).build().dgram`) — and
  read the new bytes of the installed
  `logs/abletonosc.log` after each send. `_get_property` / `_set_property` /
  `_call_method` log the value; error paths log the offending address.
- Ok-paths of the custom handlers (return_track getters, `browser/get/items`,
  `is_view_visible`) log **nothing**. Probe counts via deliberate bad-index
  requests instead — the error message embeds the count
  ("this set has N return track(s)").
- Wrap every mutation in `/live/song/begin_undo_step` / `end_undo_step` and
  restore what you changed.
- Never `stop_listen` a property Seshat subscribes to — grep the log for
  "Adding listener" to see the current set (song tempo, signature pair,
  `is_playing`, `root_note`, `scale_name`, `groove_amount`, `swing_amount`,
  `tracks`, `return_tracks`, master mixer params). `metronome` is free.
- Stray replies land on Seshat's socket; keep the volume low.
- The committed pytest suite is still not a substitute for this. It is now
  safe to have around — `tests/` is inert unless `ABLETONOSC_LIVE_TESTS=1` is
  set, its client binds `127.0.0.1:11001` rather than `0.0.0.0:11001`, and the
  `/live/api/reload` it sends happens inside the opted-in session fixture
  rather than at import time, so collection sends nothing — but it still needs
  the reply port to itself. With Seshat holding 11001 the whole suite skips,
  which is the interlock, not a workaround: reading the log file is the only
  way to interrogate a Live that another client is already talking to.

---

---

## Round trips cost ticks, not datagrams

**Measured against Live 12 on 2026-08-04** (harness bound to `127.0.0.1:11001`
with no Seshat instance running; large-burst runs at 9 tracks, temporary tracks
deleted afterwards). This is the fact every read-shaped design decision here
rests on, so it is stated before the address tables rather than inside one.

`manager.py` schedules `tick()` once per 100ms on Live's main thread, and each
tick's `osc_server.process()` drains **every** datagram already queued on the
socket, answering each inline. A query therefore costs ~100ms because it waits
for the next tick — not because the datagram is expensive.

| Test | Result |
|---|---|
| Serialized getter ×20, same address (`/live/song/get/tempo`) | 99.6–100.4ms each — exactly one tick per query |
| Serialized getters ×20, alternating addresses | identical: 99.1–100.4ms each |
| Burst of 10 different-address song getters, ×3 | all 10 answered in **one tick**, 1.1–1.9ms spread |
| Burst of 45 (5 mixer getters × 9 tracks) ×3 | 45/45 in one tick, 11.7–13.0ms spread |
| Burst of 63 (song scalars + 8 scene names + 45 track reads) | 63/63 in one tick, 14.2ms spread, **zero drops** |
| Same-address burst (`/live/track/get/name` × 9 tracks at once) | 9/9 in one tick, replies in send order, told apart by the echoed index |
| Bulk endpoints (`track_names`, `scenes/name`, `track_data`) | one tick each — **identical latency to a burst** |
| Single query at random phase ×10 | uniform 15–100ms — RTT is time-to-next-tick and nothing else |

Consequences, all of them load-bearing:

- **N serialized reads cost N ticks; the same N sent back-to-back cost one.**
  That is what `Seshat.OSC.Transport.query_batch/2` exists for, and what
  `get_clip_properties`, `get_track_sends` and the regular-track device reads
  use. Replies inside a tick arrive in datagram order; per-message processing is
  ~0.25ms.
- **A bulk endpoint buys no latency over a burst.** Adding aggregate addresses
  to the fork to collapse an N+1 read was evaluated on these numbers and not
  pursued — see Seshat's `docs/archive/PLAN_batched_queries.md`. Reopen only for a read needing
  more than one burst's worth of datagrams, or an atomic multi-tick snapshot.
- **63 datagrams is where the evidence stops, not where the wire breaks.** The
  server reads each datagram with `recvfrom(65536)` and never sets
  `SO_RCVBUF`/`SO_SNDBUF`, so the socket buffers are the OS defaults, against
  ~40-byte requests and ~60-byte replies. `query_batch/2` caps a batch at 64
  entries for that reason; measure before raising it.

---

## Application API

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/test` | | `'ok'` | Confirmation message in Live + OSC reply |
| `/live/application/get/version` | | `major_version, minor_version` | Live's version |
| `/live/application/get/average_process_usage` | | `average_process_usage` | Live's average CPU load. ⚠️ `application.py` also *sends* one argument-less datagram on this address every time AbletonOSC initialises — a stray sibling of `/live/startup`, not a reply to anything; ignore it |
| `/live/application/dump_lom` | `[path]` | `path, num_classes, num_addresses` | Seshat extension. Walks the installed Live API (every class and member reachable from the `Live` module, plus the Max-for-Live device tables) and this server's registered addresses, and writes both to a JSON file — `path` if given, else `logs/lom_dump.json` next to the Remote Script. `tools/lom_gaps.py` diffs the two; `FORK_GAPS.md` is maintained from that diff. ⚠️ Takes an arbitrary path from the wire and writes it with Live's privileges — the opposite of `browser/export`'s policy; see `issues.md`, "Bound `/live/application/dump_lom`'s output path" |
| `/live/api/reload` | | | Live reload of AbletonOSC server code (dev only — see the warning below) |
| `/live/api/get/log_level` | | `log_level` | Current log level (default: `info`) |
| `/live/api/set/log_level` | `log_level` | | Set log level: `debug`, `info`, `warning`, `error`, `critical` |
| `/live/api/show_message` | `message` | | Show message in Live's status bar |

⚠️ **Don't reach for `/live/api/reload`.** Two problems, both observed:

1. It reloads modules, not files on disk that Live never imported. Editing the
   Python in this repository does nothing until it is copied into Live's
   Remote Scripts (Seshat's `mix abletonosc.install` does that), and a reload won't pick up a *new* module either — that
   needs Live restarted, or AbletonOSC toggled off and back on under
   Preferences > Link/Tempo/MIDI > Control Surface.
2. It can take the whole API down. `Manager.clear_api()` unregisters every
   address (`clear_handlers()`) as its first line, *then* tears down each
   handler's listeners. If anything in that teardown or in the re-import that
   follows raises, the script is left with zero handlers registered and no way
   to re-register them over OSC, since `/live/api/reload` has unregistered
   itself too. Every address then answers "Unknown OSC address" until Live is
   restarted or the control surface is toggled. (Observed once as a `KeyError`
   from a listener on a deleted track; the fork's `_stop_listen` now guards
   that path, so the current trigger is unknown — the failure mode isn't.)

### Status Messages (sent automatically)

| Address | Response Params | Description |
|---|---|---|
| `/live/startup` | | Sent when AbletonOSC starts |
| `/live/error` | `"request", address, error_msg, arg_count, *request_args` | A request failed inside its handler. Carries the request that produced it, and is sent **instead of** a reply — the request gets no other answer. `address` is the address **the client sent**, which for a wildcard request is the pattern. Fork-only (see `SESHAT.md`); upstream sends only the shape below. |
| `/live/error` | `"log", error_msg` | An error with no originating OSC request — an unknown address (`Unknown OSC address: /live/...`), parse failures, socket errors, a handler's own internal error logs. Never correlatable to a request. |

The `"request"` shape covers exactly four failures: an uncaught exception in an
ordinary callback (direct dispatch *or* wildcard fan-out), an exception in the
generic `_call_method` path, an exception in the generic `_set_property` path,
and a handler returning something that is neither a tuple, a list of tuples,
nor `None`. It does not cover every rejection in the fork — the browser and
return/master handlers
reply with their own `"error"`-tagged envelopes, and the three fork-added
`/live/view/...` setters (`show_view`, `hide_view`, `set/detail_clip`) fail
silently by design. Upstream's four `/live/view/set/selected_*` setters have no
guard: a bad index raises and comes back as a `"request"` error like any other
callback.

A handler's return value decides how many datagrams a request gets: `None`
sends nothing, a tuple sends one reply, and a **list of tuples sends one reply
per element**, in list order, all on the same reply address. The list form is
what a fan-out request answers with — a track-index wildcard replies once per
track (see [Track API](#track-api)). The whole list is validated before
anything is sent, so a list containing a non-tuple produces the structured
error above and **no** replies, never a partial fan-out.

Those envelope handlers cost **two** datagrams per rejection, not one. Measured
2026-08-05, Live 12.4.3 — `get_track_devices` with `target: "return"` on return
99 put both of these on the wire in the same millisecond:

```
/live/error                    ["log", "Return track 99 does not exist — this set has 0 return track(s) (get/devices)"]
/live/return_track/get/devices [99, "error", "Return track 99 does not exist — this set has 0 return track(s)"]
```

The envelope reply is the one the caller reads; the `"log"` copy is the relay
echoing the handler's own `logger.error`, which carries no `osc_request_error`
marker to suppress it. Harmless — a `"log"` payload is never correlated to a
query — but it is why "one rejection, one datagram" holds only for the
dispatcher-boundary path. Tracked fork-side (`issues.md`, endpoint contract inventory), not a Seshat
defect.

> **Three of those four arrived with the fork's dispatch-boundary rework
> (`_dispatch`).** Before it, only a direct callback's own exception was
> correlated: wildcard failures, generic method/setter failures and invalid
> handler returns all reached the client as an uncorrelatable `"log"` line or
> not at all. A Remote Scripts copy predating that commit therefore still
> answers every address, still sends one datagram per failure, and just goes
> quiet on the three — verify with `mix abletonosc.install` and a Live restart
> before relying on them.

`arg_count` makes the variable tail explicit and keeps a zero-argument request
from needing a special case; `request_args` are the request's own arguments
echoed back with their wire types intact (so an OSC `f` is still 32-bit —
compare against a 32-bit round-trip of what was sent, never a 64-bit float).
`Seshat.OSC.Transport` is the only place that knows this payload: a `"request"`
error matching the in-flight query's address *and* every argument fails that
query immediately instead of letting it wait out its timeout.

Measured on the wire, Live 12.4.3, **re-measured 2026-08-05** — since the
2026-08-04 batching work `get_track_devices` reads through
`Transport.query_batch/2`, so a track index past the end of the set now raises
once *per entry* and produces **one datagram per raise**, still with no
`"log"`-tagged duplicate for any of them:

```
/live/error ["request", "/live/track/get/devices/name",       "Index out of range", 1, 99]
/live/error ["request", "/live/track/get/devices/type",       "Index out of range", 1, 99]
/live/error ["request", "/live/track/get/devices/class_name", "Index out of range", 1, 99]
```

All three landed within 2ms of each other — one AbletonOSC tick — and each was
correlated to its own batch entry. That is the first live confirmation of the
per-entry correlation; the 2026-08-03 measurement below predates batching and
recorded the single-datagram form of the same behaviour.

The whole rejection, client call to tool result, took 198ms against a 5,000ms
query timeout (212ms on the serial path, 2026-08-03). Two batches on the *same
three addresses* with different arguments, fired back to back, were served one
tick apart — 99ms — the second returning correct data, so an error releases the
FIFO slot immediately and argument-level correlation holds when address alone
would not distinguish them.

**Inapplicable clip properties reply `nil`, they do not raise. Measured
2026-08-05, Live 12.4.3.** `/live/clip/get/* 0 0` against a MIDI clip returned
all 36 registered clip getters, including the audio-only four:

```
/live/clip/get/gain                [0, 0, nil]
/live/clip/get/gain_display_string [0, 0, nil]
/live/clip/get/warp_mode           [0, 0, nil]
/live/clip/get/warping             [0, 0, nil]
```

Live raises `RuntimeError` for these and `AbletonOSCHandler._get_property`
converts exactly that to `None` before returning — deliberate
inapplicable-property semantics, and the one branch the dispatch-boundary
merge left untouched. So `get_clip_properties`' `is_midi_clip` guard avoids
presenting meaningless nils and a wasted round trip, **not** an error: a query
for one of these costs a reply, never a rejection. Guidance saying they "raise
on a MIDI clip" was unmeasured and is corrected. A clip query against an
**empty slot** does raise, and is a different case.

**Wildcard fan-out, measured 2026-08-05 against the merged dispatch boundary.**
`/live/*/get/tempo` with no arguments now replies once, on
`/live/song/get/tempo`, and sends no `/live/error` at all. Before that commit
the same request also matched `/live/scene/get/tempo_enabled` (the pattern was
compiled unescaped and matched unanchored), which raised `IndexError` wanting a
scene index, abandoned the rest of the fan-out, and surfaced as an
uncorrelatable `/live/error ["log", "Error handling OSC message: list index out
of range"]`. That one request is the cheapest probe there is for *which* bridge
Live currently has in memory — a reply with no error means the merged code, a
reply followed by that `"log"` line means the old one, and it mutates nothing. The raising address is the one that actually raised, which is not
always the address the tool is named for: `get_clip_notes` on a bad index raises
at its `/live/clip_slot/get/has_clip` guard, never reaching
`/live/clip/get/notes`.

---

## Song API

Top-level Song object. Playback control, scene/track creation, cue points, global params (tempo, metronome).

### Song Methods

| Address | Query Params | Description |
|---|---|---|
| `/live/song/begin_undo_step` | | ⚠️ **Seshat fork addition** — open an explicit undo step. Everything changed before the matching `end` collapses into one entry in Live's undo history |
| `/live/song/end_undo_step` | | ⚠️ **Seshat fork addition** — close the open undo step. Harmless when none is open; `begin` does not refcount, so the first `end` closes |
| `/live/song/capture_and_insert_scene` | | Capture the currently playing clips into a new scene inserted below the selected one (Live's "Capture and Insert Scene" command) |
| `/live/song/capture_midi` | | Capture MIDI |
| `/live/song/continue_playing` | | Resume session playback |
| `/live/song/create_audio_track` | `index` | Create audio track at index (-1 = end) |
| `/live/song/create_midi_track` | `index` | Create MIDI track at index (-1 = end) |
| `/live/song/create_return_track` | | Create return track |
| `/live/song/create_scene` | `index` | Create scene at index (-1 = end) |
| `/live/song/cue_point/jump` | `cue_point` | Jump to cue point (by name or index) |
| `/live/song/cue_point/add_or_delete` | | Add/delete cue point at cursor |
| `/live/song/cue_point/set/name` | `cue_point_index, name` | Rename cue point. Index only — unlike `cue_point/jump`, a name in the first slot is not resolved |
| `/live/song/delete_scene` | `scene_index` | Delete scene |
| `/live/song/delete_return_track` | `return_index` | Delete return track — indexes `song.return_tracks`, a separate space from regular track indices |
| `/live/song/delete_track` | `track_index` | Delete track |
| `/live/song/duplicate_scene` | `scene_index` | Duplicate scene |
| `/live/song/duplicate_track` | `track_index` | Duplicate track |
| `/live/song/force_link_beat_time` | | Force Ableton Link to adopt Live's current beat time |
| `/live/song/jump_by` | `time` | Jump song position by beats |
| `/live/song/jump_to_next_cue` | | Jump to next cue marker |
| `/live/song/jump_to_prev_cue` | | Jump to previous cue marker |
| `/live/song/re_enable_automation` | | Re-enable automation that manual tweaks have overridden (Live's "Re-Enable Automation" button) |
| `/live/song/redo` | | Redo last undone operation |
| `/live/song/set_or_delete_cue` | | Toggle a cue point at the playhead — the same LOM method `/live/song/cue_point/add_or_delete` above calls; two addresses, one behaviour |
| `/live/song/start_playing` | | Start session playback |
| `/live/song/stop_playing` | | Stop session playback |
| `/live/song/stop_all_clips` | | Stop all clips |
| `/live/song/tap_tempo` | | Tap tempo |
| `/live/song/trigger_session_record` | | Trigger session record |
| `/live/song/undo` | | Undo last operation |

#### Song method extensions (Seshat — not in upstream AbletonOSC)

⚠️ `begin_undo_step` and `end_undo_step` do **not** exist in stock AbletonOSC.
They are two entries in the generic methods list of `abletonosc/song.py` in
this repository, installed with `mix abletonosc.install`
(restart Live afterwards). Like every other row in this table they are
send-only: nothing replies, so a missing install is indistinguishable from
success on the wire — undo simply goes back to reverting whole conversations.

Left to itself Live groups script-driven mutations into undo steps by its own
activity-sensitive rules; `Song.begin_undo_step()` / `Song.end_undo_step()` are
what Ableton's own Push script uses to make the boundary explicit.
`Seshat.Tools.Handlers.call/2` wraps every tool dispatch in a pair, so one tool
call is exactly one undo step. Measured on Live 12.4.3 (2026-08-01): an empty
pair leaves the history untouched, an unmatched `end` is harmless, and `begin`
does not refcount.

**`can_undo` / `can_redo`, measured on Live 12.4.3 (2026-08-02, probe rig).**
`Seshat.Tools.Handlers`'s `history_guard/2` reads one of these before sending an
`undo` or `redo`, and `/live/song/undo` and `/live/song/redo` never reply — so
what these two properties actually do is the only thing that can turn "off the
end of the history" into an honest refusal rather than a fabricated success.

- **Both are plain `bool` attributes** — `type=bool`, `callable=False`, and
  neither raises. A reply is therefore always encodable; a `getattr` yielding
  something unencodable is not a failure mode here.
- **Not hardwired true.** In a set reading `can_undo=True can_redo=True`, one
  new edit (a `create_midi_track`) flipped `can_redo` to **False** — so the
  guard's refusal branch is reachable on real hardware.
- **They track availability independently and in both directions.** Undoing
  that edit flipped `can_redo` back to `True` while `can_undo` never moved. A
  `false` reading therefore means the stack is genuinely empty, not that the
  property is stuck.
- ⚠️ **`can_undo=False` at a genuinely empty history is still unmeasured** — it
  needs File → New Live Set, which no probe can reach without discarding the
  open set. Tracked as measurement tripwire 5 in
  Seshat's `docs/smoke_tests/auto/undo.md` as *`can_undo=False` is reachable
  at an empty history*; fold the reading in here once made.

### Song Getters

Listen via `/live/song/start_listen/<property>`, stop via
`/live/song/stop_listen/<property>`, and receive responses on
`/live/song/get/<property>`.

| Address | Response Params | Description |
|---|---|---|
| `/live/song/get/appointed_device` | `category, track_index, device_index` | ⚠️ **Seshat extension** — the appointed ("blue hand") device, as a device triple: `category` is `"track"`, `"return_track"`, `"master"`, or `"none"` with both indices `-1` when nothing is appointed. A device nested in a rack chain answers `category, track_index, -1`. Its listen pair pushes the same triple. See **Object-valued reads** |
| `/live/song/get/arrangement_overdub` | `arrangement_overdub` | Arrangement overdub state |
| `/live/song/get/back_to_arranger` | `back_to_arranger` | "Back to arranger" lit state |
| `/live/song/get/can_redo` | `can_redo` | Redo available? Plain `bool` attribute — see the measured semantics below |
| `/live/song/get/can_undo` | `can_undo` | Undo available? Plain `bool` attribute — see the measured semantics below |
| `/live/song/get/clip_trigger_quantization` | `clip_trigger_quantization` | Clip trigger quantization level |
| `/live/song/get/current_song_time` | `current_song_time` | Current song time (beats) |
| `/live/song/get/groove_amount` | `groove_amount` | Groove Pool amount (0.0-1.3; 1.0 = the dial's 100%, 1.3 = its 130% maximum); scales how strongly each clip's *assigned* groove applies — no effect on clips without one |
| `/live/song/get/is_ableton_link_enabled` | `is_ableton_link_enabled` | Ableton Link on? (1=on, 0=off) |
| `/live/song/get/is_playing` | `is_playing` | Song playing? |
| `/live/song/get/loop` | `loop` | Looping? |
| `/live/song/get/loop_length` | `loop_length` | Loop length |
| `/live/song/get/loop_start` | `loop_start` | Loop start point |
| `/live/song/get/metronome` | `metronome_on` | Metronome on/off |
| `/live/song/get/midi_recording_quantization` | `midi_recording_quantization` | MIDI recording quantization |
| `/live/song/get/nudge_down` | `nudge_down` | Nudge down |
| `/live/song/get/nudge_up` | `nudge_up` | Nudge up |
| `/live/song/get/punch_in` | `punch_in` | Punch in |
| `/live/song/get/punch_out` | `punch_out` | Punch out |
| `/live/song/get/record_mode` | `record_mode` | Record mode |
| `/live/song/get/root_note` | `root_note` | Root note |
| `/live/song/get/scale_name` | `scale_name` | Scale name |
| `/live/song/get/session_record` | `session_record` | Session record enabled? |
| `/live/song/get/session_record_status` | `session_record_status` | Session record status |
| `/live/song/get/signature_denominator` | `denominator` | Time signature denominator |
| `/live/song/get/signature_numerator` | `numerator` | Time signature numerator |
| `/live/song/get/song_length` | `song_length` | Arrangement length (beats) |
| `/live/song/get/swing_amount` | `swing_amount` | Global swing amount (0.0-1.0); applied by MIDI record quantization and `/live/clip/quantize` |
| `/live/song/get/tempo` | `tempo_bpm` | Song tempo |

### Song Setters

| Address | Query Params | Description |
|---|---|---|
| `/live/song/set/appointed_device` | `category, track_index, device_index` | ⚠️ **Seshat extension** — appoint a top-level device, by the same triple the getter replies. Every argument is validated: `"none"`, an unknown category, a negative or out-of-range index, or a master index other than `0` each answer on `/live/error` and change nothing. There is no un-appoint. Only `"track"` has been exercised against a running Live; whether Live accepts a return-track or master device as `appointed_device` is unmeasured |
| `/live/song/set/arrangement_overdub` | `arrangement_overdub` | Set arrangement overdub (1=on, 0=off) |
| `/live/song/set/back_to_arranger` | `back_to_arranger` | Set back to arranger (1=on, 0=off) |
| `/live/song/set/clip_trigger_quantization` | `clip_trigger_quantization` | Set clip trigger quantization |
| `/live/song/set/current_song_time` | `current_song_time` | Set song time (beats) |
| `/live/song/set/groove_amount` | `groove_amount` | Set Groove Pool amount (0.0-1.3); 0 = assigned grooves off |
| `/live/song/set/is_ableton_link_enabled` | `is_ableton_link_enabled` | Enable/disable Ableton Link (1=on, 0=off) |
| `/live/song/set/loop` | `loop` | Set looping (1=on, 0=off) |
| `/live/song/set/loop_length` | `loop_length` | Set loop length |
| `/live/song/set/loop_start` | `loop_start` | Set loop start |
| `/live/song/set/metronome` | `metronome_on` | Set metronome (1=on, 0=off) |
| `/live/song/set/midi_recording_quantization` | `midi_recording_quantization` | Set MIDI recording quantization |
| `/live/song/set/nudge_down` | `nudge_down` | Set nudge down |
| `/live/song/set/nudge_up` | `nudge_up` | Set nudge up |
| `/live/song/set/punch_in` | `punch_in` | Set punch in |
| `/live/song/set/punch_out` | `punch_out` | Set punch out |
| `/live/song/set/record_mode` | `record_mode` | Set record mode |
| `/live/song/set/root_note` | `root_note` | Set the song's root note (int; pairs with the documented getter) |
| `/live/song/set/scale_name` | `scale_name` | Set the song's scale by name (string; pairs with the documented getter) |
| `/live/song/set/session_record` | `session_record` | Set session record (1=on, 0=off) |
| `/live/song/set/signature_denominator` | `signature_denominator` | Set time sig denominator |
| `/live/song/set/signature_numerator` | `signature_numerator` | Set time sig numerator |
| `/live/song/set/swing_amount` | `swing_amount` | Set global swing amount (0.0-1.0) |
| `/live/song/set/tempo` | `tempo_bpm` | Set tempo |

### Song: Track/Scene/Cue Queries

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/song/get/cue_points` | | `name, time, ...` | List cue points |
| `/live/song/get/num_scenes` | | `num_scenes` | Number of scenes |
| `/live/song/get/num_tracks` | | `num_tracks` | Number of regular tracks (excludes return and master tracks) |
| `/live/song/get/scenes/name` | `[index_min, index_max]` | `[names...]` | All scene names in one reply, in index order (optional half-open range — see below) |
| `/live/song/get/track_names` | `[index_min, index_max]` | `[names...]` | Regular track names, in index order (optional range) |
| `/live/song/get/track_data` | `start_track, end_track, properties...` | `[values...]` | Bulk track/clip data query (regular tracks only) |

The three track queries iterate `song.tracks`, so return tracks and the master
track are absent from their counts and their index space. Return-track count
and names come from `/live/return_track/get/count` and
`/live/return_track/get/name` — see the Return Track & Master API below.

`/live/song/get/scenes/name` differs from `track_names` in three ways worth
knowing before relying on it: the range is half-open (`[min, max)`, so
`0 num_scenes` reads everything), `-1` is **not** accepted as "to the end"
(`track_names` special-cases it; here `range(min, -1)` is simply empty, so the
reply is an empty list that looks exactly like a set with no scenes), and the
reply carries **names only — the range is not echoed back**, so on a transport
that correlates by address alone a straggler from an earlier ranged query is
indistinguishable from the current reply by content.

#### Bulk Track Data

`/live/song/get/track_data` queries multiple tracks/clips at once. Properties use format `track.property_name`, `clip.property_name`, `clip_slot.property_name`, or `device.property_name` (one value per device on the track). `track.num_devices` is special-cased to `len(track.devices)`. An `end_index` of `-1` means "through the last track".

Example: `/live/song/get/track_data 0 12 track.name clip.name clip.length` queries tracks 0–11.

#### Legacy structure export — do not use

`/live/song/export/structure` (no arguments, replies `1`) dumps every track's
clips, devices and parameters to a JSON file. ⚠️ It predates the hardened
export pattern `/live/browser/export` uses and keeps everything that pattern
was built to remove: it writes to a **fixed, world-guessable path** in the
global temp directory (`abletonosc-song-structure.json`) with Live's
privileges, and on macOS it first blanks `TMPDIR` **for the whole Live
process** so that path is discoverable — redirecting every temp file Live
creates afterwards. Upstream code, kept only to avoid an unforced divergence;
Seshat never calls it. Read structure through the per-address queries or
`track_data` instead.

### Beat Events

Call `/live/song/start_listen/beat` to receive beat messages on `/live/song/get/beat` with the current beat number. Stop with `/live/song/stop_listen/beat`.

---

## View API

User interface control — selecting tracks, scenes, clips, devices.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/view/get/selected_scene` | | `scene_index` | Selected scene (0-indexed) |
| `/live/view/get/selected_track` | | `track_index` | Selected track (0-indexed), or `-1` when a return track or the master is selected — see **Selected-track identity** below |
| `/live/view/get/selected_clip` | | `track_index, scene_index` | Selected clip. `track_index` is `-1` when a return track or the master is selected |
| `/live/view/get/selected_device` | | `track_index, device_index` | Selected device (0-indexed). `device_index` is `-1` when the selected regular track has no top-level device to report; both are `-1` when a return track or the master is selected |
| `/live/view/set/selected_scene` | `scene_index` | | Set selected scene |
| `/live/view/set/selected_track` | `track_index` | | Set selected track |
| `/live/view/set/selected_clip` | `track_index, scene_index` | | Set selected clip |
| `/live/view/set/selected_device` | `track_index, device_index` | `track_index, device_index` | Set selected device. The only view setter that replies — it echoes both indices on the request address. Deliberately kept; see **Selected-track identity** below |
| `/live/view/start_listen/selected_scene` | | `selected_scene` | Listen for scene selection changes |
| `/live/view/start_listen/selected_track` | | `selected_track` | Listen for track selection changes. Pushes the same value `get/selected_track` replies with, `-1` included |
| `/live/view/stop_listen/selected_scene` | | | Stop listening for scene changes |
| `/live/view/stop_listen/selected_track` | | | Stop listening for track changes |
| `/live/view/show_view` | `view_name` | | ⚠️ **Seshat extension** — bring a pane into view |
| `/live/view/hide_view` | `view_name` | | ⚠️ **Seshat extension** — put a pane away |
| `/live/view/get/is_view_visible` | `view_name` | `view_name, "ok", visible` or `view_name, "error", message` | ⚠️ **Seshat extension** — is a pane visible? `visible` is 1 or 0 |
| `/live/view/set/detail_clip` | `track_index, scene_index` | | ⚠️ **Seshat extension** — put a clip in the Detail view |
| `/live/view/get/selected_track_identity` | | `category, index` | ⚠️ **Seshat extension** — which track is selected, in any category: `"track"`, `"return_track"` or `"master"` |
| `/live/view/start_listen/selected_track_identity` | | `category, index` | ⚠️ **Seshat extension** — listen for selection changes across all three categories |
| `/live/view/stop_listen/selected_track_identity` | | | ⚠️ **Seshat extension** — stop listening for identity changes |
| `/live/view/get/selected_chain` | | `category, track_index, device_index, chain_index` | ⚠️ **Seshat extension** — the highlighted rack chain. `device_index` is the owning rack's index in that track's `devices`, `-1` if the rack is itself nested; `chain_index` its index in that rack's `chains`. Nothing selected → `"none", -1, -1, -1`. See **Object-valued reads** |
| `/live/view/get/selected_parameter` | | `category, track_index, device_index, parameter_index` | ⚠️ **Seshat extension** — the selected device parameter. A mixer/send parameter, or a parameter of a device nested in a rack chain, answers `category, track_index, -1, -1`. Nothing selected → `"none", -1, -1, -1` |
| `/live/view/get/mod_mapping_device` | | `category, track_index, device_index` | ⚠️ **Seshat extension** — the device waiting for a Max-for-Live/macro mapping. Idle → `"none", -1, -1` |
| `/live/view/get/mod_mapping_parameter` | | `category, track_index, device_index, parameter_index` | ⚠️ **Seshat extension** — the parameter waiting for that mapping. Idle → `"none", -1, -1, -1` |

### Selected-track identity

`song.view.selected_track` can hold a regular track, a return track or the
master — this fork can put any of the three there, via
`/live/view/set/selected_track`, `/live/return_track/select` and
`/live/master/select`. But there is only one selection, and three separate
index spaces to report it in, so **`/live/view/get/selected_track_identity`**
answers with a `(category, index)` pair:

| `category` | `index` counts within | Selected with |
|---|---|---|
| `"track"` | `song.tracks` | `/live/view/set/selected_track <track_index>` |
| `"return_track"` | `song.return_tracks` | `/live/return_track/select <return_index>` |
| `"master"` | — always `0` | `/live/master/select` |

The category strings are exactly the OSC address-family prefixes that reach
that track, so a reply is directly actionable: the category names the family
to use next, and the index is already in that family's coordinates.

- `/live/view/set/selected_track` still resolves its index through
  `song.tracks`, so it reaches **regular tracks only** — a return track cannot
  be selected on it at any index. Use `/live/return_track/select` (Seshat
  extension, see the Return Track & Master API below), or `/live/master/select`
  for the master. There is deliberately no identity *setter*: each category
  already has its own select address, and the table above is the mapping.
- **The legacy single-int getters keep their shapes and answer `-1` outside
  their index space.** `get/selected_track` replies `-1`, `get/selected_clip`
  replies `(-1, scene_index)`, and `get/selected_device` replies `(-1, -1)`
  when a return track or the master is selected. Before this fork's
  `/live/return_track/select` and `/live/master/select` existed, that state was
  unreachable and upstream's getters simply raised `ValueError` on it; they now
  answer instead. `-1` is the same "not in this index space" sentinel used
  elsewhere for object-valued reads — see **Object-valued reads** in
  *Conventions the address tables don't show*, which is the pattern all nine
  of them follow.
- **`-1` is an answer, never an argument.** None of the three setters
  (`set/selected_track`, `set/selected_clip`, `set/selected_device`) reject
  it: they index `song.tracks`/`.devices` directly with whatever
  `track_index` they are given, and Python resolves a negative index
  from the end of the list rather than raising. Sending back a `-1` read from
  `get/selected_track` therefore does not restore "a return track or the
  master was selected" — it silently selects the **last regular track**
  instead. Restore a snapshot through the category it actually names:
  `/live/view/set/selected_track` for `"track"`,
  `/live/return_track/select` for `"return_track"`, `/live/master/select`
  for `"master"` — i.e. round-trip through `get/selected_track_identity`,
  not the legacy getters.
- `get/selected_device` also answers `(track_index, -1)` when a regular track
  is selected but there is no **top-level** device to report — either nothing
  is selected in the device chain, or the selected device is nested inside a
  rack chain and so is not a member of `track.devices`. Devices on a return
  track or the master read `(-1, -1)`: their chains exist, but there is no
  regular-track index to report them under yet.
- **Two listeners, one observable property.**
  `start_listen/selected_track_identity` subscribes to the same LOM property
  as `start_listen/selected_track` (`Song.View.selected_track`) and pushes
  `[category, index]` on `/live/view/get/selected_track_identity` — once
  immediately on subscribe, then on every selection change, in any category.
  The two coexist independently: starting or stopping one does not touch the
  other, and `stop_listen/selected_track_identity` removes exactly its own
  subscription. Before this change a return or master selection killed the
  `selected_track` push outright: the getter raised inside Live's listener
  callback, which is outside the per-message error envelope, so no push and no
  `/live/error` went out at all.
- **`/live/view/set/selected_device`'s echo is deliberate, and stays** (settled
  2026-08-27). It is upstream's own behaviour; silencing it would be a
  permanent behavioural divergence inside an upstream file, with breakage risk
  for non-Seshat clients, to remove a reply that costs one datagram. It remains
  the single documented exception to "view setters are silent", and Seshat's
  `FollowCam` ignores it.
- These getters never error for a *selection-category* or *no-device-selected*
  reason — those are answers, and they are on the wire. A genuine failure (a
  selection in none of the three collections, `None` included — not a state a
  loaded set is expected to produce) still raises and arrives as a structured
  `/live/error`, loudly, rather than being laundered into a sentinel.

### View extensions (Seshat — not in upstream AbletonOSC)

⚠️ Eleven rows above do **not** exist in stock AbletonOSC: `show_view`,
`hide_view`, `get/is_view_visible`, `set/detail_clip`, the identity trio
`get/selected_track_identity`, `start_listen/selected_track_identity` and
`stop_listen/selected_track_identity`, and the four object-valued reads of
`Song.View` — `get/selected_chain`, `get/selected_parameter`,
`get/mod_mapping_device` and `get/mod_mapping_parameter`. They are served by
`abletonosc/view.py` in this repository, installed with
`mix abletonosc.install` (restart Live afterwards). They are not the only Seshat
addresses living in an *upstream* file — `/live/song/begin_undo_step` and
`/live/song/end_undo_step` are two more, in `song.py` (see Song Methods above).
Without that install none of the eleven is known: of the four view-steering
addresses, the three setters silently do nothing and the getter never replies;
of the identity trio, the getter never replies and the listen pair is unknown,
so nothing is ever pushed; and the four object-valued getters never reply. The three upstream getters the identity note above
describes are *present* without the install, and go back to raising
`ValueError` — no reply — the moment a return track or the master is selected.

Upstream can *select* a track, scene, clip or device, but it cannot show the
pane those live in, put one away, or say which panes are open at all:
`Application.View.show_view`, `.hide_view`, `.is_view_visible` and
`song.view.detail_clip` have no upstream address. Seshat's view steering needs
the first — selecting a clip nobody can see is not confirmation that anything
happened — and its view tools need the rest.

- `show_view` takes one of Live's own pane names: `Browser`, `Arranger`,
  `Session`, `Detail`, `Detail/Clip`, `Detail/DeviceChain`. `FollowCam` sends
  `Session`, `Detail/Clip` and `Detail/DeviceChain` after a mutation; the
  `show_view` tool exposes all six, so `Arranger`, `Browser` and bare `Detail`
  are also model-reachable for direct navigation and pre-action sequencing.
- `hide_view` takes the same six names — the Python passes the name through
  verbatim — but only two of them genuinely hide anything. Measured against
  Live 12 Suite, 2026-07-31, reading all six flags back after every send:

  | Sent | What actually happens |
  |---|---|
  | `Browser` | browser closes — a true hide |
  | `Detail` | detail panel closes, and its active tab flag goes false with it — a true hide |
  | `Session` | Arranger becomes visible instead — a main-view swap, not a hide |
  | `Arranger` | Session becomes visible instead — a main-view swap, not a hide |
  | `Detail/Clip` | detail panel stays open, flips to `Detail/DeviceChain` |
  | `Detail/DeviceChain` | detail panel stays open, flips to `Detail/Clip` |

  Seshat's `hide_view` **tool** therefore offers only `Browser` and `Detail`:
  the address is silent, so a name that merely swaps or does nothing would be
  an undetectable no-op. Switching between Session and Arrangement is
  `show_view`'s job, and closing the detail panel is bare `Detail`.
- `get/is_view_visible` takes any of the six and answers for all of them,
  including the sub-views. `Detail/Clip` and `Detail/DeviceChain` mean "the
  detail panel is open **and** that tab is active": exactly one of them reads 1
  while `Detail` reads 1, and both read 0 when the panel is hidden.
  `Session` and `Arranger` measured strictly complementary — never both 1, never
  both 0 — so the main view can be derived from the pair, and
  `focused_document_view` is not needed.
- `set/detail_clip` puts `song.tracks[track_index].clip_slots[scene_index]`'s
  clip into the Detail view. Pair it with `show_view Detail/Clip` to open the
  note editor on it.
- **The four object-valued getters** answer `Song.View`'s `selected_chain`,
  `selected_parameter`, `mod_mapping_device` and `mod_mapping_parameter` —
  LOM *objects*, which the generic property loop can only render as an error
  or a `None` — as indices under a track-identity category, per
  **Object-valued reads**. Get-only in this fork: all four members are
  observable and two are LOM-writable, but no consumer has named a setter or a
  listener for them yet, and the `getter=` machinery makes either a cheap
  follow-up. ⚠️ Not yet measured against a running Live: whether a drum rack's
  `DrumChain` appears in its rack's `chains` (so `selected_chain` resolves a
  `chain_index`) or only under `drum_pads[*].chains` (so it answers `-1`), and
  what the `mod_mapping_*` pair reads mid-gesture — the idle `"none"` shapes
  are what the LOM docstrings describe.
- **The three setters are silent**, like upstream's setters — an unknown view
  name or an empty clip slot is logged to Live's `Log.txt` and nothing goes on
  the wire. `show_view` and `set/detail_clip` are view steering that follows an
  already-successful tool, and steering must never fail or delay the thing it
  follows, so the ok/error envelope the fork's *getters* use deliberately does
  not apply. `hide_view` is silent for consistency with them, and is verified
  instead from the Elixir side by reading `get/is_view_visible` back.
- **`get/is_view_visible` always replies**, in that envelope, echoing the name
  it was asked about, because a caller waits on it: silence must mean only
  "the fork isn't installed". An unrecognised name is a fast `"error"` reply
  (`could not read visibility of '<name>': The specified View Identifier does
  not exist` — the handler's prefix wrapping Live's exception, which raises
  here unlike `show_view`, which ignores a bad name), never a guard timeout. The boolean is an int
  on the wire, 1 or 0, like every other AbletonOSC boolean.
- **Read-after-write ordering holds.** A `hide_view` immediately followed by a
  read reflects the hide: AbletonOSC processes datagrams sequentially on Live's
  timer thread, and roughly thirty send-then-read-six cycles in the 2026-07-31
  measurement produced zero stale reads. No sleep is needed between them.

---

## Track API

**Regular (audio/MIDI) tracks only.** Every handler here resolves its index
through `song.tracks`, which holds audio and MIDI tracks and nothing else — a
return track or the master track cannot be reached on any `/live/track/*`
address, at any index. Return tracks and the master are addressable through
Seshat's return_track extension (see below); sends, being a property of a
*regular* track's mixer, live here.

Volume, panning, send, mute, solo, devices, clips.

Listen via `/live/track/start_listen/<property> <track_index>`, stop via
`/live/track/stop_listen/<property> <track_index>`, and receive responses on
`/live/track/get/<property>` with `<track_index> <value>`. `*` in place of the
index subscribes every track — see **The track-index argument wildcard** below,
which is the contract for `*` on every `/live/track/...` address, not just the
listeners.

**A subscription's identity is one int** (2026-08-27) — `track_index` is
normalised to an int at the callback boundary and that int alone is the
subscription's identity, for every listen pair on this section including
`volume` and `panning`. Float-sending clients (TouchOSC; upstream issue #33)
can start and stop interchangeably with int-sending ones, non-integral
floats truncate toward zero. **Arguments past the index are not part of the
identity and are ignored**: they enter neither the bookkeeping key nor any
push, so a stray trailing argument can no longer key a subscription that a
well-formed stop could never reach (nor, being uncast, echo a non-numeric
value as a push field). Pushes on `/live/track/get/<property>` therefore
always carry `track_index, value` in exactly the query-reply shape, whatever
the subscribing request's tail looked like. The rule composes with `*`:
extras after the wildcard are equally ignored, so every fanned-out
subscription keys on its own `track_index` and a well-formed
`/live/track/stop_listen/<property> *` ends whatever a malformed wildcard
start began. Sending **no** index remains a malformed request and answers on
`/live/error`.

⚠️ Listener pairs exist for the **scalar** properties only (the property loops
in `track.py`, plus `volume` and `panning`). The composite getters — `send`,
the routing properties, `clips/*`, `arrangement_clips/*`, `devices/*`,
`num_devices` — register no listeners, and neither does `group_track`, whose
LOM member is not observable at all: `/live/track/start_listen/send` is an
unknown address and fails silently, which also means **nothing pushes a
send's accepted value into the mirror** after `/live/track/set/send`.
Reading the value back is therefore the only way to observe that a send
landed, which is what `set_track_send` does.

**Measured against Live 12.4.3 on 2026-08-04** (Seshat's `docs/smoke_tests/auto/sends.md`),
for that read-back:

- **A `/live/track/get/send` issued immediately after `/live/track/set/send`
  returns the new value.** Five consecutive set-then-get pairs at
  in-process spacing (microseconds apart, well inside one AbletonOSC tick)
  all reported the value just written — AbletonOSC processes the two
  datagrams in arrival order at that spacing, never the stale value.
- **Live applies no quantization to a send value.** `0.0`, `0.37` and `1.0`
  each round-tripped to themselves; the only distortion is the OSC wire's
  32-bit float (`0.37` returns as `0.3700000047683716`), so a comparison
  rounded to 4 decimals matches exactly across the whole 0.0–1.0 range.
- **A send index Live doesn't have raises on the *getter*.** `send_id` 9
  against a one-return set raises `IndexError: Index out of range` on
  `/live/track/get/send`, arriving via the structured `/live/error` in
  ~0.14s (measured end-to-end through an MCP HTTP call), not as a timeout.

> ⚠️ **These listeners are fixed in the fork**, in `AbletonOSCHandler._stop_listen`
> and `TrackHandler`'s mixer-listener pair. Same addresses, same arguments, same
> pushes — nothing calling them can tell the difference, which is exactly why the
> bug is worth writing down.
>
> A listener is keyed by track index but bound to a track *object*, and upstream
> unbinds it from whatever object the index resolves to at teardown time. Delete a
> track and every later index shifts, so re-subscribing tries to unbind the old
> callback from the wrong track: the removal fails, the base class swallows it as
> "likely benign", and the old listener stays alive pushing under an index that
> now belongs to someone else. A rename afterwards writes one track's name onto
> another in `Seshat.Session.State`. The fork unbinds from the object the callback
> was actually registered on, which `_start_listen` already records in
> `listener_objects`.
>
> The mixer listeners (volume, panning) had a second bug: they never recorded
> anything in `listener_objects` at all, so `_clear_listeners` raised `KeyError`
> on script reload once either was active. They now key as
> `("value", (track_id, prop))` with the `DeviceParameter` stored, and stop
> through the fixed base class.
>
> Seshat used to fix this from outside, by re-registering the five affected
> addresses from a `track_listeners.py` that had to be instantiated after
> `TrackHandler`. That file no longer exists.

### The track-index argument wildcard (`*`)

Every `/live/track/...` address accepts `"*"` (the OSC string) in the
track-index slot, and it means the same thing an address pattern means in
[README § Wildcard queries](README.md#wildcard-queries): **a fan-out, not a
query.** One request, one action per regular track.

| Form | `*` behaviour |
|---|---|
| `/live/track/get/<prop> *` | **One reply datagram per regular track**, each on the concrete request address, each carrying the exact single-track payload `track_index, ...values`. Built and sent in ascending `track_index` order within a single tick. |
| `/live/track/set/<prop> * <value>` | Applies to every regular track. No reply, exactly as the single-track form. |
| `/live/track/<method> *`, `/live/track/delete_clip * <slot>` | Invoked on every regular track. No reply. |
| `/live/track/start_listen/<prop> *` / `stop_listen` | Subscribes/unsubscribes every track. Pushes remain one per track, `track_index, value`, on `/live/track/get/<prop>`. Unchanged. |

- **"Every regular track" means `song.tracks`** — audio and MIDI tracks. Return
  and master tracks are not in this namespace at any index, wildcard included.
- **Correlate on the leading `track_index`, not on arrival order.** The
  datagrams are sent in index order, but UDP guarantees no delivery ordering.
- **Zero regular tracks → zero replies, no error.**
- **All-or-nothing on error.** Every track is read before anything is sent, so
  a failure at any track produces **no replies at all** and exactly one
  correlated error naming the track:
  `/live/error ["request", "/live/track/get/<prop>", "wildcard fan-out failed at track <i>: <detail>", 1, "*"]`.
  A partial fan-out is never left on the wire. To isolate which track is
  refusing, fall back to per-index requests. (The per-track exception keeps its
  class through the wrap, so the dispatcher's skip-vs-report decision for
  composed pattern requests is unaffected — see below.)
- **An address pattern and the argument wildcard compose.**
  `/live/track/get/* *` fans out per endpoint *and* per track: each matched
  getter replies once per track on its own concrete address, and a matched
  endpoint whose arguments don't fit the request (e.g. `get/send`, which needs
  a send index the request omitted) is skipped silently under README's
  wildcard rules. This composition can also hide a genuine failure: if a
  matched getter fails on a later track after already succeeding on earlier
  ones, `OSCServer._is_wildcard_skip`'s class-based test (which cannot see
  *where* in the fan-out an exception was raised) treats it the same as an
  immediate arg-mismatch, so that endpoint answers with nothing at all —
  neither the replies already collected nor an error — while every other
  matched endpoint is unaffected. Send the concrete address to see the error.
- **A client helper that awaits a single reply cannot use this**, for the same
  reason it cannot use an address pattern. Seshat's `Transport.query/3` resolves
  on the first datagram and drops the rest; `query_batch/2` over concrete track
  indices is the answer. Nothing in Seshat sends `*` today (`SESHAT.md`).

**Measured against Live 12.4.3:**

- **2026-08-03** (`issues.md` code review, multi-track set): `/live/track/get/name *`
  produced exactly **one** getter invocation, for track 0 — the defect. The
  wildcard loop returned on the first track that produced a value, so every
  wildcard getter answered for track 0 alone while setters, methods and
  listeners (whose workers return nothing) iterated correctly.
- **2026-08-27** (single-track set, installed copy code-identical to the
  repository): `/live/track/get/name *` and `/live/track/get/mute *` each
  produced exactly one `Getting property for track:` log line, confirming the
  logged path is the dispatched one. A single-track set cannot distinguish the
  defect from correct behaviour on its own.
- ⚠️ **The repaired fan-out has not been confirmed inside Live.** The fix is
  covered Live-free by `tests_unit/test_track_callback.py` against the real
  factory, but no ≥2-track run has been made with the repaired code installed.
  The check to run is in the plan's Live verification section; the reply
  *datagrams* are in any case unobservable from this side, since replies go to
  port 11001.

### Track Methods

| Address | Query Params | Description |
|---|---|---|
| `/live/track/delete_clip` | `track_id, clip_index` | Delete the clip in slot `clip_index`. No reply — same address family as `/live/clip_slot/delete_clip`, which Seshat uses instead |
| `/live/track/delete_device` | `track_id, device_id` | Delete a device from the track's chain. **No reply on success** — `_call_method` returns nothing. A bad index raises inside the callback and comes back as `/live/error ["request", "/live/track/delete_device", ...]`. Callers wanting positive confirmation re-read `/live/track/get/num_devices` |
| `/live/track/stop_all_clips` | `track_id` | Stop all clips on track |

### Track Getters

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/track/get/arm` | `track_id` | `track_id, armed` | Track armed? |
| `/live/track/get/available_input_routing_channels` | `track_id` | `track_id, channel, ...` | List input channels |
| `/live/track/get/available_input_routing_types` | `track_id` | `track_id, type, ...` | List input routes |
| `/live/track/get/available_output_routing_channels` | `track_id` | `track_id, channel, ...` | List output channels |
| `/live/track/get/available_output_routing_types` | `track_id` | `track_id, type, ...` | List output routes |
| `/live/track/get/can_be_armed` | `track_id` | `track_id, can_be_armed` | Can track be armed? |
| `/live/track/get/color` | `track_id` | `track_id, color` | Track color |
| `/live/track/get/color_index` | `track_id` | `track_id, color_index` | Track color index |
| `/live/track/get/current_monitoring_state` | `track_id` | `track_id, state` | Monitoring state (1=on, 0=off) |
| `/live/track/get/fired_slot_index` | `track_id` | `track_id, index` | Currently-fired slot |
| `/live/track/get/fold_state` | `track_id` | `track_id, fold_state` | Group folded state |
| `/live/track/get/group_track` | `track_id` | `track_id, group_track_index` | ⚠️ **Seshat extension** — the index in `song.tracks` of the group track this track is in, or `-1` when it is not grouped. `*` fans out like every other track getter. **No listen pair** — `Track.group_track` is not observable. See **Object-valued reads** |
| `/live/track/get/has_audio_input` | `track_id` | `track_id, has_audio_input` | Has audio input? |
| `/live/track/get/has_audio_output` | `track_id` | `track_id, has_audio_output` | Has audio output? |
| `/live/track/get/has_midi_input` | `track_id` | `track_id, has_midi_input` | Has MIDI input? |
| `/live/track/get/has_midi_output` | `track_id` | `track_id, has_midi_output` | Has MIDI output? |
| `/live/track/get/input_routing_channel` | `track_id` | `track_id, channel` | Current input routing channel |
| `/live/track/get/input_routing_type` | `track_id` | `track_id, type` | Current input routing type |
| `/live/track/get/output_routing_channel` | `track_id` | `track_id, channel` | Current output routing channel |
| `/live/track/get/output_meter_left` | `track_id` | `track_id, level` | Output level, left |
| `/live/track/get/output_meter_level` | `track_id` | `track_id, level` | Output level, both channels |
| `/live/track/get/output_meter_right` | `track_id` | `track_id, level` | Output level, right |
| `/live/track/get/output_routing_type` | `track_id` | `track_id, type` | Current output routing type |
| `/live/track/get/is_foldable` | `track_id` | `track_id, is_foldable` | Is a group? |
| `/live/track/get/is_grouped` | `track_id` | `track_id, is_grouped` | In a group? |
| `/live/track/get/is_visible` | `track_id` | `track_id, is_visible` | Visible? (1=on, 0=off) |
| `/live/track/get/mute` | `track_id` | `track_id, mute` | Muted? (1=on, 0=off) |
| `/live/track/get/name` | `track_id` | `track_id, name` | Track name |
| `/live/track/get/panning` | `track_id` | `track_id, panning` | Track panning (-1.0 to 1.0) |
| `/live/track/get/playing_slot_index` | `track_id` | `track_id, index` | Currently-playing slot |
| `/live/track/get/send` | `track_id, send_id` | `track_id, send_id, value` | Send level (0.0 to 1.0) |
| `/live/track/get/solo` | `track_id` | `track_id, solo` | Soloed? |
| `/live/track/get/volume` | `track_id` | `track_id, volume` | Track volume (0.0 to 1.0) |

### Track Setters

| Address | Query Params | Description |
|---|---|---|
| `/live/track/set/arm` | `track_id, armed` | Set arm (1=on, 0=off) |
| `/live/track/set/color` | `track_id, color` | Set color |
| `/live/track/set/color_index` | `track_id, color_index` | Set color index |
| `/live/track/set/current_monitoring_state` | `track_id, state` | Set monitoring |
| `/live/track/set/fold_state` | `track_id, fold_state` | Set group fold (1=on, 0=off) |
| `/live/track/set/input_routing_channel` | `track_id, channel` | Set input routing channel |
| `/live/track/set/input_routing_type` | `track_id, type` | Set input routing type |
| `/live/track/set/mute` | `track_id, mute` | Set mute (1=on, 0=off) |
| `/live/track/set/name` | `track_id, name` | Set track name |
| `/live/track/set/output_routing_channel` | `track_id, channel` | Set output routing channel |
| `/live/track/set/output_routing_type` | `track_id, type` | Set output routing type |
| `/live/track/set/panning` | `track_id, panning` | Set panning (-1.0 to 1.0) |
| `/live/track/set/send` | `track_id, send_id, value` | Set send level |
| `/live/track/set/solo` | `track_id, solo` | Set solo (1=on, 0=off) |
| `/live/track/set/volume` | `track_id, volume` | Set volume (0.0 to 1.0) |

### Track: Clip Queries

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/track/get/clips/name` | `track_id` | `track_id, [name, ...]` | All clip names |
| `/live/track/get/clips/length` | `track_id` | `track_id, [length, ...]` | All clip lengths |
| `/live/track/get/clips/color` | `track_id` | `track_id, [color, ...]` | All clip colors |
| `/live/track/get/arrangement_clips/name` | `track_id` | `track_id, [name, ...]` | Arrangement clip names |
| `/live/track/get/arrangement_clips/length` | `track_id` | `track_id, [length, ...]` | Arrangement clip lengths |
| `/live/track/get/arrangement_clips/start_time` | `track_id` | `track_id, [start_time, ...]` | Arrangement clip start times |

### Track: Device Queries

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/track/get/num_devices` | `track_id` | `track_id, num_devices` | Number of devices |
| `/live/track/get/devices/name` | `track_id` | `track_id, [name, ...]` | All device names |
| `/live/track/get/devices/type` | `track_id` | `track_id, [type, ...]` | All device types |
| `/live/track/get/devices/class_name` | `track_id` | `track_id, [class, ...]` | All device class names |
| `/live/track/get/devices/can_have_chains` | `track_id` | `track_id, [can_have_chains, ...]` | Per device: is it a rack (can hold chains)? |

---

## Clip Slot API

Container for clips. Create, delete, and query clip existence.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/clip_slot/fire` | `track_index, clip_index, [record_length]` | | Fire clip slot — with `record_length` (beats), records for exactly that long (see note below) |
| `/live/clip_slot/stop` | `track_index, clip_index` | | Stop the slot's playing clip |
| `/live/clip_slot/create_clip` | `track_index, clip_index, length` | | Create clip in slot |
| `/live/clip_slot/delete_clip` | `track_index, clip_index` | | Delete clip |
| `/live/clip_slot/get/has_clip` | `track_index, clip_index` | `track_index, clip_index, has_clip` | Has clip? |
| `/live/clip_slot/get/clip` | `track_index, clip_index` | `track_index, clip_index, clip_index_or_-1` | ⚠️ **Seshat extension** — the object-read form of `has_clip`: the third field is the clip's index in `/live/clip/*` coordinates, which is the slot's own `clip_index`, or `-1` when the slot is empty. **No listen pair.** See **Object-valued reads** |
| `/live/clip_slot/get/controls_other_clips` | `track_index, clip_index` | `track_index, clip_index, controls_other_clips` | Group slot controlling the clips below it? |
| `/live/clip_slot/get/is_group_slot` | `track_index, clip_index` | `track_index, clip_index, is_group_slot` | Slot belongs to a group track? |
| `/live/clip_slot/get/is_playing` | `track_index, clip_index` | `track_index, clip_index, is_playing` | Slot's clip playing? |
| `/live/clip_slot/get/is_triggered` | `track_index, clip_index` | `track_index, clip_index, is_triggered` | Fired and waiting on quantization? |
| `/live/clip_slot/get/playing_status` | `track_index, clip_index` | `track_index, clip_index, playing_status` | Slot playing status |
| `/live/clip_slot/get/will_record_on_start` | `track_index, clip_index` | `track_index, clip_index, will_record_on_start` | Firing this slot would record (armed track, empty slot)? |
| `/live/clip_slot/get/has_stop_button` | `track_index, clip_index` | `track_index, clip_index, has_stop_button` | Has stop button? |
| `/live/clip_slot/set/has_stop_button` | `track_index, clip_index, has_stop_button` | | Set stop button (1=on, 0=off) |
| `/live/clip_slot/duplicate_clip_to` | `track_index, clip_index, target_track, target_clip` | | Duplicate clip to target slot |

Every `get/` property above **except `get/clip`** also has
`/live/clip_slot/start_listen/<property> <track_index> <clip_index>` and
`/live/clip_slot/stop_listen/<property> <track_index> <clip_index>`; pushes
arrive on the matching `get/` address as `track_index, clip_index, value`.
`get/clip` has no listen pair — `get/has_clip`'s is the one to use for slot
occupancy, and whether `ClipSlot` even offers an `add_clip_listener` is
unmeasured (the fork does not register one either way).

**A subscription's identity is two ints** (2026-08-27) — both indices are
normalised to ints at the callback boundary and that pair is used for the clip
slot lookup, the subscription's identity, and the indices echoed in every
push, so pushes carry the query-reply shape whatever number type the client
sent. Float-sending clients (TouchOSC; upstream issue #33) can start and stop
interchangeably with int-sending ones, non-integral floats truncate toward
zero, and **arguments past the second are not part of the identity and are
ignored**. Sending fewer than two is a malformed request and answers on
`/live/error`.

> ℹ️ **`fire` takes an optional `record_length`, and that is fixed-length
> recording.** The handler passes everything after the two indices straight
> into `ClipSlot.fire()`, whose first optional positional argument is
> `record_length` in beats (then `launch_quantization`, `force_legato`). Fire
> an empty slot on an armed track with a length and Live records exactly that
> long, stops itself, and leaves a clip of that length playing — loop brace
> and play markers already set. With no length it records until something
> stops it. Verified against Live 12.4.3, 2026-07-29; it is also how Live's
> own control surfaces implement fixed-length record. This is what `record_clip`
> and `stop_recording` are built on.

> ⚠️ **`duplicate_clip_to` is a merge hazard.** Upstream PRs #182 and #185 rename
> it to `duplicate_to` with no alias, and Seshat's `duplicate_clip` tool depends
> on the old name — so merging either into the fork breaks the tool silently
> (an unknown address over UDP just does nothing). Recorded in `SESHAT.md` at the
> fork root; the `audit-osc` workflow is what catches it.

---

## Clip API

Audio or MIDI clip. Start/stop, notes, name, gain, pitch, color, playing state/position.

Every `get/` property below also has
`/live/clip/start_listen/<property> <track_id> <clip_id>` and
`/live/clip/stop_listen/<property> <track_id> <clip_id>`; pushes arrive on the
matching `get/` address as `track_id, clip_id, value`. The `playing_position`
pair is listed explicitly only because it is the one Seshat uses.

**A subscription's identity is two ints** (2026-08-27) — both indices are
normalised to ints at the callback boundary and that pair is used for the clip
lookup, the subscription's identity, and the indices echoed in every push, so
pushes carry the query-reply shape whatever number type the client sent.
Float-sending clients (TouchOSC; upstream issue #33) can start and stop
interchangeably with int-sending ones, non-integral floats truncate toward
zero, and **arguments past the second are not part of the identity and are
ignored**. Sending fewer than two is a malformed request and answers on
`/live/error`.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/clip/fire` | `track_id, clip_id` | | Start clip |
| `/live/clip/stop` | `track_id, clip_id` | | Stop clip |
| `/live/clip/duplicate_loop` | `track_id, clip_id` | | Duplicate clip loop |
| `/live/clip/quantize` | `track_id, clip_id, grid, amount` | | **Seshat extension** (fork only). Quantize the clip's notes. `grid` is Live's `GridQuantization` enum — see below. `amount` is 0.0–1.0 (Live's UI shows it as a percentage). No reply, ever |
| `/live/clip/get/notes` | `track_id, clip_id, [start_pitch, pitch_span, start_time, time_span]` | `track_id, clip_id, pitch, start_time, duration, velocity, mute, ...` | Query notes (optional range) |
| `/live/clip/add/notes` | `track_id, clip_id, pitch, start_time, duration, velocity, mute, ...` | | Add MIDI notes |
| `/live/clip/remove/notes` | `track_id, clip_id, [start_pitch, pitch_span, start_time, time_span]` | | Remove notes (no range = all) |
| `/live/clip/remove_notes_by_id` | `track_id, clip_id, note_id, ...` | | Remove notes by Live note id. ⚠️ Of limited use here: `get/notes` replies carry no ids, so nothing in this API yields an id to pass |
| `/live/clip/get/color` | `track_id, clip_id` | `track_id, clip_id, color` | Clip color |
| `/live/clip/set/color` | `track_id, clip_id, color` | | Set clip color |
| `/live/clip/get/color_index` | `track_id, clip_id` | `track_id, clip_id, color_index` | Color index (0-69) |
| `/live/clip/set/color_index` | `track_id, clip_id, color_index` | | Set color index (0-69) |
| `/live/clip/get/name` | `track_id, clip_id` | `track_id, clip_id, name` | Clip name |
| `/live/clip/set/name` | `track_id, clip_id, name` | | Set clip name |
| `/live/clip/get/gain` | `track_id, clip_id` | `track_id, clip_id, gain` | Clip gain |
| `/live/clip/set/gain` | `track_id, clip_id, gain` | | Set clip gain |
| `/live/clip/get/gain_display_string` | `track_id, clip_id` | `track_id, clip_id, gain_display_string` | Human-readable gain as dB string (audio clips only, read-only) |
| `/live/clip/get/length` | `track_id, clip_id` | `track_id, clip_id, length` | Clip length |
| `/live/clip/get/sample_length` | `track_id, clip_id` | `track_id, clip_id, sample_length` | Sample length |
| `/live/clip/get/start_time` | `track_id, clip_id` | `track_id, clip_id, start_time` | Start time |
| `/live/clip/get/end_time` | `track_id, clip_id` | `track_id, clip_id, end_time` | End time (beats) |
| `/live/clip/get/pitch_coarse` | `track_id, clip_id` | `track_id, clip_id, semitones` | Coarse pitch |
| `/live/clip/set/pitch_coarse` | `track_id, clip_id, semitones` | | Set coarse pitch |
| `/live/clip/get/pitch_fine` | `track_id, clip_id` | `track_id, clip_id, cents` | Fine pitch |
| `/live/clip/set/pitch_fine` | `track_id, clip_id, cents` | | Set fine pitch |
| `/live/clip/get/file_path` | `track_id, clip_id` | `track_id, clip_id, file_path` | Clip file path |
| `/live/clip/get/is_audio_clip` | `track_id, clip_id` | `track_id, clip_id, is_audio_clip` | Is audio clip? |
| `/live/clip/get/is_midi_clip` | `track_id, clip_id` | `track_id, clip_id, is_midi_clip` | Is MIDI clip? |
| `/live/clip/get/is_playing` | `track_id, clip_id` | `track_id, clip_id, is_playing` | Is playing? |
| `/live/clip/get/is_overdubbing` | `track_id, clip_id` | `track_id, clip_id, is_overdubbing` | Is overdubbing? |
| `/live/clip/get/is_recording` | `track_id, clip_id` | `track_id, clip_id, is_recording` | Is recording? |
| `/live/clip/get/is_triggered` | `track_id, clip_id` | `track_id, clip_id, is_triggered` | Fired and waiting on quantization? (clip-level twin of the clip_slot/scene property) |
| `/live/clip/get/will_record_on_start` | `track_id, clip_id` | `track_id, clip_id, will_record_on_start` | Will record on start? |
| `/live/clip/get/playing_position` | `track_id, clip_id` | `track_id, clip_id, playing_position` | Playing position |
| `/live/clip/start_listen/playing_position` | `track_id, clip_id` | | Listen for playing position |
| `/live/clip/stop_listen/playing_position` | `track_id, clip_id` | | Stop listening for position |
| `/live/clip/get/looping` | `track_id, clip_id` | `track_id, clip_id, looping` | Clip loop on/off (1=on, 0=off) |
| `/live/clip/set/looping` | `track_id, clip_id, looping` | | Set clip loop on/off (1=on, 0=off) |
| `/live/clip/get/loop_start` | `track_id, clip_id` | `track_id, clip_id, loop_start` | Loop start |
| `/live/clip/set/loop_start` | `track_id, clip_id, loop_start` | | Set loop start |
| `/live/clip/get/loop_end` | `track_id, clip_id` | `track_id, clip_id, loop_end` | Loop end |
| `/live/clip/set/loop_end` | `track_id, clip_id, loop_end` | | Set loop end |
| `/live/clip/get/warping` | `track_id, clip_id` | `track_id, clip_id, warping` | Warp mode |
| `/live/clip/set/warping` | `track_id, clip_id, warping` | | Set warp mode |
| `/live/clip/get/launch_mode` | `track_id, clip_id` | `track_id, clip_id, launch_mode` | Launch mode (0=Trigger, 1=Gate, 2=Toggle, 3=Repeat) |
| `/live/clip/set/launch_mode` | `track_id, clip_id, launch_mode` | | Set launch mode |
| `/live/clip/get/launch_quantization` | `track_id, clip_id` | `track_id, clip_id, launch_quantization` | Launch quantization (0=Global, 1=None, 2=8Bars, 3=4Bars, 4=2Bars, 5=1Bar, 6=1/2, 7=1/2T, 8=1/4, 9=1/4T, 10=1/8, 11=1/8T, 12=1/16, 13=1/16T, 14=1/32) |
| `/live/clip/set/launch_quantization` | `track_id, clip_id, launch_quantization` | | Set launch quantization |
| `/live/clip/get/ram_mode` | `track_id, clip_id` | `track_id, clip_id, ram_mode` | RAM mode (0=False, 1=True) |
| `/live/clip/set/ram_mode` | `track_id, clip_id, ram_mode` | | Set RAM mode |
| `/live/clip/get/warp_mode` | `track_id, clip_id` | `track_id, clip_id, warp_mode` | Warp mode (0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 6=Pro) |
| `/live/clip/set/warp_mode` | `track_id, clip_id, warp_mode` | | Set warp mode |
| `/live/clip/get/has_groove` | `track_id, clip_id` | `track_id, clip_id, has_groove` | Has groove? |
| `/live/clip/get/legato` | `track_id, clip_id` | `track_id, clip_id, legato` | Legato (0=False, 1=True) |
| `/live/clip/set/legato` | `track_id, clip_id, legato` | | Set legato |
| `/live/clip/get/position` | `track_id, clip_id` | `track_id, clip_id, position` | Position (LoopStart) |
| `/live/clip/set/position` | `track_id, clip_id, position` | | Set position |
| `/live/clip/get/muted` | `track_id, clip_id` | `track_id, clip_id, muted` | Muted? (0=False, 1=True) |
| `/live/clip/set/muted` | `track_id, clip_id, muted` | | Set muted |
| `/live/clip/get/velocity_amount` | `track_id, clip_id` | `track_id, clip_id, velocity_amount` | Velocity amount (0.0-1.0) |
| `/live/clip/set/velocity_amount` | `track_id, clip_id, velocity_amount` | | Set velocity amount |
| `/live/clip/get/start_marker` | `track_id, clip_id` | `track_id, clip_id, start_marker` | Start marker |
| `/live/clip/set/start_marker` | `track_id, clip_id, start_marker` | | Set start marker (beats) |
| `/live/clip/get/end_marker` | `track_id, clip_id` | `track_id, clip_id, end_marker` | End marker |
| `/live/clip/set/end_marker` | `track_id, clip_id, end_marker` | | Set end marker (beats) |

### `/live/clips/*` — experimental upstream pair, do not use

Two more addresses are registered in `clip.py` under the plural prefix
`/live/clips/`: `/live/clips/filter [note_name, ...]` mutes every session clip
whose notes fall outside the given set, and
`/live/clips/unfilter [track_start, track_end]` unmutes clips again (no
arguments = every track). They are upstream experiments, not
API: `filter` infers a clip's notes from a suffix in its **name** (regex
`[_-][A-G]...$`), builds a whole-set cache on first use that is **never
invalidated** — clips added, deleted or renamed later are judged by stale
data — and both silently rewrite `muted` across the entire set with no reply.
Documented so the addresses aren't mistaken for gaps; nothing in Seshat calls
them and nothing should.

### A fired slot's clip does not exist yet

Measured 2026-08-03, Live 12.4.3. `/live/clip_slot/fire` is processed in
datagram order like anything else, but the clip it creates lands
**asynchronously**. Polling immediately after the fire with launch quantization
set to None, `/live/clip_slot/get/has_clip` answered `False` on the first query
and `True` 99ms later — with `/live/clip/get/is_recording` already `True` by
that second read.

So datagram ordering does not buy you the engine state a fire *triggers*. Any
read-back that treats an immediate `has_clip: false` as "nothing was created"
will misreport a take that started fine; `Handlers.record_echo/3` re-reads once
for exactly this reason. A slot genuinely waiting for a boundary has no clip for
up to a full bar, so the two cases are still distinguishable — just not on one
read.

### `clip_trigger_quantization` is not the `launch_quantization` enum

Measured 2026-08-03, Live 12.4.3, and an easy way to silently change a global
setting while thinking you restored it. The **song** property
`/live/song/set/clip_trigger_quantization` is offset from the **clip** property
`launch_quantization` used by `set_clip_properties`, because the clip enum
starts with `0=Global` and the song enum has no such entry:

| Value | `clip_trigger_quantization` (song) | `launch_quantization` (clip) |
|---|---|---|
| 0 | None | Global |
| 1 | 8 bars | None |
| 4 | **1 bar** (`q_bar`, Live's default) | 2 bars |
| 5 | 1/2 (`q_half`) | **1 bar** |

Read it back with `/live/song/get/clip_trigger_quantization`, which answers with
a name (`q_bar`, `q_half`) rather than the integer — the only cheap way to be
sure which enum you just wrote into.

### The loop pair rejects an inversion

Measured 2026-08-03, Live 12.4.3. `/live/clip/set/loop_start` with a value at or
past the current `loop_end` **does not move the brace** — Live does not clamp it
to a legal value. Live raises `Cannot set LoopStart behind LoopEnd`; the
dispatcher catches it, writes `AbletonOSC: Error handling OSC message
/live/clip/set/loop_start: …` to Live's `Log.txt`, and sends `/live/error
["request", "/live/clip/set/loop_start", ...]`. The property keeps its old value.
(`/live/clip/set/loop_end` is symmetric.) The measurement predates the fork's
dispatch-boundary rework, when the failure was logged and nothing reached the
wire.

That is why `set_clip_properties` validates the pair caller-side and orders the
two writes end-first when a brace moves entirely past its old position: without
both, moving a brace forward would silently half-apply.

Also measured the same day: **with `looping` off, `loop_start`/`loop_end` read
`0.0` and the clip length** — they do not track `start_marker`/`end_marker`. A
clip with markers at 0.0–2.0 and an 8-beat length reports a loop pair of
0.0–8.0. Reading the pair to decide anything while looping is off therefore
reads the clip extent, not the brace Live will restore when looping goes back on
(that brace survives independently — measured by toggling looping off and on
around a 2.0–6.0 brace, which came back as 2.0–6.0).

### Note windows match by start, and a read can be re-sent — after two conversions

Measured 2026-08-27, Live 12.4.3, on a fresh MIDI clip holding four notes with
off-grid values (starts 0.0 / 1.6667 / 0.25 / 2.125, durations 0.3333 / 1.75 /
0.5 / 0.125, velocities 100 / 37 / 100 / 127).

- **The time window of `/live/clip/remove/notes` (and, per the LOM,
  `get/notes`) selects notes that *start* inside it.** Removing
  `[60, 1, 2.0, 1.0]` — pitch 60, beats 2–3 — left the pitch-60 note starting
  at 1.6667 untouched even though it sounds until 3.4167. A tool that promises
  "notes in this range" must say "notes that begin in this range".
- **Read → remove window → re-add is lossless in the five wire fields.** The
  values `get/notes` returned (`0.33330002427101135`, `1.666700005531311` —
  float32 already) came back identical after `add/notes` re-sent them, and
  the notes outside the window were byte-identical before and after.
  Bracketed in `begin_undo_step`/`end_undo_step`, one `undo` restored the
  pre-edit notes exactly.
- **But the reply cannot be re-sent verbatim.** `get/notes` returns `mute` as
  an OSC boolean (`T`/`F`) and velocity as a float (`100.0`); `add/notes`
  expects `0|1` and an integer. Seshat's `Seshat.OSC.Message.encode/2` has no
  type tag for booleans, so re-sending the reply's fields raised
  `FunctionClauseError` inside the Transport GenServer (reproduced, restarted
  by its supervisor). Convert before sending: `mute` → `0|1`, velocity →
  `round/1`.
- What the round trip cannot preserve: `probability`, `velocity_deviation`,
  `release_velocity` — the reply does not carry them (FORK_GAPS.md, "Notes
  flatten to five fields"), so re-added notes get Live's defaults.

### Quantization grid

`/live/clip/quantize`'s `grid` argument is Live's `GridQuantization` enum, which
is **not** the `RecordingQuantization` enum used elsewhere in Live's API, and
**not** the `launch_quantization` enum `set_clip_properties` uses (where 1/16 is
`12`). Sending the wrong integer quantizes to the wrong grid, silently.

The table below was **measured against a running Live on 2026-07-31**, one clip
per enum value, five probe notes chosen so that every candidate grid produces a
distinct set of landing positions, `amount` 1.0, read back with
`/live/clip/get/notes`. Identical results in 4/4 and 6/8, so the mapping does
not depend on the time signature.

| Value | Grid | | Value | Grid |
|---|---|---|---|---|
| 0 | none (nothing moves) | | 5 | **1/16** (0.25 beat) |
| 1 | 1/4 (1.0 beat) | | 6 | 1/16 triplet (1/6 beat) |
| 2 | 1/8 (0.5 beat) | | 7 | 1/16 triplet (1/6 beat) |
| 3 | 1/8 triplet (1/3 beat) | | 8 | 1/32 (0.125 beat) |
| 4 | 1/8 triplet (1/3 beat) | | ≥9 | invalid — nothing happens |

Notes on the measurements, because they contradict what this file said until
2026-07-31 (previously: `1=8 bars … 5=1/2, 6=1/4, 7=1/8, 8=1/16, 9=1/32`, every
row of it wrong; the fork's `abletonosc/clip.py` carried the same wrong table
until its comment was corrected to the measured one):

- **Triplet grids exist** — 1/8T and 1/16T. The old claim that there are none,
  and that swing instead comes from the song's `swing_amount`, is wrong in its
  first half; the second half is still untested here, though the fork now
  exposes `/live/song/set/swing_amount` to test it with.
- **There are no bar-length grids, and no 1/2 grid.** Nothing in the valid
  range is coarser than a 1/4 note.
- **3 and 4 behave identically, as do 6 and 7.** Reproduced across separate
  runs and both meters. Reason unknown; prefer the lower value of each pair.
- **Values ≥ 9 do not move anything.** The callback raises inside AbletonOSC
  and the dispatcher reports it as `/live/error ["request",
  "/live/clip/quantize", ...]` — no reply on the request address, no movement.
  (Measured before the dispatch-boundary rework, when the exception was only
  logged and the wire looked like success.)
- Only note *starts* move; durations are preserved, except that a move which
  lands two same-pitch notes on one point **merges** them (later velocity
  wins) and a move that creates a same-pitch overlap **trims** the earlier
  note. `amount` is linear: `new = old + amount × (target − old)`.

---

## Scene API

Trigger a row of clips simultaneously. Set/query name, color, tempo, time signature.

### Scene Methods

| Address | Query Params | Description |
|---|---|---|
| `/live/scene/fire` | `scene_id` | Trigger scene |
| `/live/scene/fire_as_selected` | `scene_id` | Trigger scene, select next |
| `/live/scene/fire_selected` | | Trigger selected scene, select next |

### Scene Getters

Listen via `/live/scene/start_listen/<property> <scene_index>`, stop via
`/live/scene/stop_listen/<property> <scene_index>`, and receive responses on
`/live/scene/get/<property>`.

**A subscription's identity is one int** (2026-08-27) — `scene_index` is
normalised to an int at the callback boundary and that int is used for all
three things that must agree: the scene lookup, the subscription's identity,
and the `scene_id` echoed in every push. Pushes therefore carry
`scene_id, value` in exactly the query-reply shape, whatever number type the
client sent. Clients that send floats by default (TouchOSC; upstream issue
#33) can start and stop interchangeably with int-sending ones, non-integral
floats truncate toward zero, and **arguments past the index are not part of
the identity and are ignored** — so a stray trailing argument can no longer
key a subscription that a well-formed stop could never reach. Sending **no**
index is a malformed request and answers on `/live/error`.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/scene/get/color` | `scene_id` | `scene_id, color` | Scene color |
| `/live/scene/get/color_index` | `scene_id` | `scene_id, color_index` | Color index |
| `/live/scene/get/is_empty` | `scene_id` | `scene_id, is_empty` | Is empty? |
| `/live/scene/get/is_triggered` | `scene_id` | `scene_id, is_triggered` | Is triggered? |
| `/live/scene/get/name` | `scene_id` | `scene_id, name` | Scene name |
| `/live/scene/get/tempo` | `scene_id` | `scene_id, tempo` | Scene tempo |
| `/live/scene/get/tempo_enabled` | `scene_id` | `scene_id, tempo_enabled` | Tempo enabled? |
| `/live/scene/get/time_signature_numerator` | `scene_id` | `scene_id, numerator` | Time sig numerator |
| `/live/scene/get/time_signature_denominator` | `scene_id` | `scene_id, denominator` | Time sig denominator |
| `/live/scene/get/time_signature_enabled` | `scene_id` | `scene_id, enabled` | Time sig enabled? |

### Scene Setters

| Address | Query Params | Description |
|---|---|---|
| `/live/scene/set/name` | `scene_id, name` | Set name |
| `/live/scene/set/color` | `scene_id, color` | Set color |
| `/live/scene/set/color_index` | `scene_id, color_index` | Set color index |
| `/live/scene/set/tempo` | `scene_id, tempo` | Set tempo |
| `/live/scene/set/tempo_enabled` | `scene_id, tempo_enabled` | Set tempo enabled |
| `/live/scene/set/time_signature_numerator` | `scene_id, numerator` | Set time sig numerator |
| `/live/scene/set/time_signature_denominator` | `scene_id, denominator` | Set time sig denominator |
| `/live/scene/set/time_signature_enabled` | `scene_id, enabled` | Set time sig enabled |

---

## Device API

Instruments and effects. Query/set parameters.

Every `/live/device/*` address resolves its track through `song.tracks`
(`device.py`, `create_device_callback`) — **regular tracks only**. Devices on
return tracks and the master are unreachable through this API; they have their
own addresses under `/live/return_track/device/*` and `/live/master/device/*`
in the Return Track & Master API below, which is also where
`/live/track/delete_device`'s and `/live/view/set/selected_device`'s equivalents
live (both resolve through `song.tracks` too).

Parameter 0 of every device is its "Device On" switch — the power button in the
device's corner — so `/live/device/set/parameter/value <track> <device> 0 0.0`
bypasses a device and `1.0` re-enables it. ⚠️ The parameter's identity comes
from the Live Object Model, not from a smoke test; `bypass_device` reads
parameter 0's `value_string` and refuses unless it reads On/Off rather than
trusting it blind.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/device/get/name` | `track_id, device_id` | `track_id, device_id, name` | Device name |
| `/live/device/get/class_name` | `track_id, device_id` | `track_id, device_id, class_name` | Device class name |
| `/live/device/get/type` | `track_id, device_id` | `track_id, device_id, type` | Device type (1=instrument, 2=audio_effect, 4=midi_effect) |
| `/live/device/get/num_parameters` | `track_id, device_id` | `track_id, device_id, num_parameters` | Number of parameters |
| `/live/device/get/parameters/name` | `track_id, device_id` | `track_id, device_id, [name, ...]` | Parameter names |
| `/live/device/get/parameters/value` | `track_id, device_id` | `track_id, device_id, [value, ...]` | Parameter values |
| `/live/device/get/parameters/min` | `track_id, device_id` | `track_id, device_id, [value, ...]` | Parameter min values |
| `/live/device/get/parameters/max` | `track_id, device_id` | `track_id, device_id, [value, ...]` | Parameter max values |
| `/live/device/get/parameters/is_quantized` | `track_id, device_id` | `track_id, device_id, [value, ...]` | Is quantized? (int/bool param) |
| `/live/device/set/parameters/value` | `track_id, device_id, value, ...` | | Set all parameter values |
| `/live/device/get/parameter/value` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, value` | Get single parameter |
| `/live/device/get/parameter/value_string` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, value` | Get parameter as string (e.g., "2500 Hz") |
| `/live/device/get/parameter/name` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, name` | Get single parameter's name |
| `/live/device/set/parameter/value` | `track_id, device_id, parameter_id, value` | | Set single parameter |
| `/live/device/get/parameters/display_value` | `track_id, device_id` | `track_id, device_id, [display_value, ...]` | Parameter values as the GUI shows them (e.g. "2500 Hz", "On") |
| `/live/device/get/parameters/state` | `track_id, device_id` | `track_id, device_id, [state, ...]` | Per parameter: enabled / disabled / irrelevant, as an integer code (see Parameter description) |
| `/live/device/get/parameters/is_enabled` | `track_id, device_id` | `track_id, device_id, [is_enabled, ...]` | False where a parameter has been macro-mapped or disabled by Max |
| `/live/device/get/parameters/automation_state` | `track_id, device_id` | `track_id, device_id, [automation_state, ...]` | Per parameter: none / playing / overridden, as an integer code (see Parameter description) |
| `/live/device/get/parameters/default_value` | `track_id, device_id` | `track_id, device_id, [default_value, ...]` | Reset value per parameter; OSC nil where the parameter has none |
| `/live/device/get/parameters/original_name` | `track_id, device_id` | `track_id, device_id, [original_name, ...]` | Name before a rack macro or Max device renamed the parameter |
| `/live/device/get/parameter/display_value` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, display_value` | Single parameter's GUI string |
| `/live/device/set/parameter/display_value` | `track_id, device_id, parameter_id, display_value` | | Set a parameter from Live's own GUI string ("880 Hz"); Live parses it |
| `/live/device/get/parameter/state` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, state` | Integer code (see Parameter description) |
| `/live/device/get/parameter/is_enabled` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, is_enabled` | |
| `/live/device/get/parameter/automation_state` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, automation_state` | Integer code (see Parameter description) |
| `/live/device/get/parameter/default_value` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, default_value` | OSC nil where the parameter has no default |
| `/live/device/get/parameter/original_name` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, original_name` | |
| `/live/device/get/parameter/value_items` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, [item, ...]` | Enum labels of a quantized parameter; the three indices and no items otherwise |
| `/live/device/get/parameter/short_value_items` | `track_id, device_id, parameter_id` | `track_id, device_id, parameter_id, [item, ...]` | Same, preferring Live's short labels where it has them |
| `/live/device/parameter/begin_gesture` | `track_id, device_id, parameter_id` | | Start a continuous edit: the `set/parameter/value` writes that follow become one undo step and one automation gesture |
| `/live/device/parameter/end_gesture` | `track_id, device_id, parameter_id` | | End the continuous edit opened by `begin_gesture` |

### Device Type Reference

- `name`: human-readable name
- `type`: 1 = instrument, 2 = audio_effect, 4 = midi_effect — measured against
  Live 12.4.3 on 2026-07-31 (an Operator reports 1, a Reverb and an EQ Eight
  report 2). The first two were documented the other way round until then; if
  another source disagrees, it is repeating the old guess.
- `class_name`: Live instrument/effect name (e.g., Operator, Reverb). External plugins: AuPluginDevice, PluginDevice. Racks: InstrumentGroupDevice, etc.

### Parameter description

Everything beyond `value` / `min` / `max` / `is_quantized` describes what a
parameter *means* rather than where it sits in its range. Each bulk address
answers **one element per parameter** in `device.parameters` order — the same
order and length as `get/parameters/name`, and `track_id, device_id` alone for
a device with no parameters — so a client can send several of them in one
burst and zip the replies. There is no combined record address on purpose: a
burst of N addresses answers inside a single tick, identical to one bulk
endpoint (see "Round trips cost ticks, not datagrams"), and `value_items` is
variable-length so it could not sit in a fixed-arity record anyway.

**`state` and `automation_state` go on the wire as integer codes**, the same
convention as `/live/device/get/type`.

| `state` | meaning | | `automation_state` | meaning |
|---|---|---|---|---|
| 0 | `enabled` | | 0 | `none` — no automation on this parameter |
| 1 | `disabled` — greyed out | | 1 | `playing` — automation is driving the value |
| 2 | `irrelevant` — no effect in the device's current mode | | 2 | `overridden` — a manual edit has overridden the automation (the "Re-enable Automation" state) |

⚠️ **The codes above are unmeasured (2026-08-29).** The member names are
Live's, and `enabled`, `none` and `overridden` appear as constants in Live
12.4.5's shipped Remote Script bytecode, but the integer each maps to comes
from the LOM reference and has not been read off a running Live. The handler
sends whatever `int()` of Live's enum yields, so a correction changes this
table and no code — re-derive it with
`dict(Live.DeviceParameter.ParameterState.names)` and the `AutomationState`
equivalent, via the probe rig above, before depending on a specific number.

**`value_items` / `short_value_items` answer the three indices and no items at
all for a parameter that is not quantized.** Live raises on that read ("Raises
an error if `is_quantized` is False"), and reporting it as `/live/error` would
mean one error per continuous parameter for a client describing a whole
device, so an empty list is the answer instead;
`get/parameters/is_quantized` already says which parameters can have items.
Where items exist, item `i` is the label for the quantized value `min + i`.
⚠️ Both the index rule and the exception Live raises are unmeasured
(2026-08-29); the handler catches broadly. A bad *parameter index* is still a
`/live/error` — the empty answer covers the member read, not the lookup.

**`default_value` can be OSC nil (`N`).** Live's docstring says a default
value exists only for some parameters, so where the read raises the reply
carries nil in that parameter's slot rather than dropping the element — a bulk
reply always stays the same length as `get/parameters/name`. ⚠️ Whether a real
parameter ever raises is unmeasured (2026-08-29).

**`set/parameter/display_value` takes Live's own GUI string**, passed through
uncast and unparsed by the bridge; Live does the parsing. Read the result back
with `get/parameter/value` or `get/parameter/value_string`. ⚠️ What Live does
with a string it cannot parse is unmeasured (2026-08-29) — if it raises, that
arrives as a structured `/live/error` naming the request.

**`parameter/begin_gesture` / `parameter/end_gesture`** bracket a run of
`set/parameter/value` writes so Live treats them as one continuous edit: one
undo step, and one automation gesture rather than one per write. Both are
silent. They take the *object segment then verb* form
(`/live/device/parameter/<verb>`) rather than `/live/device/<verb>`, because
the generic method loop in `device.py` reaches a `Device` and these are
methods of one of its parameters. ⚠️ An `end_gesture` with no matching
`begin_gesture` is assumed harmless; unmeasured (2026-08-29).

### Device: Listening

Every `get/` property in the table below (`name`, `type`, `class_name`) has
`/live/device/start_listen/<property> <track_id> <device_id>` and
`/live/device/stop_listen/<property> <track_id> <device_id>` registered — but
only `name` is observable in Live, and it is also the only one of the three
that can change (a device's `type` and `class_name` are fixed for its
lifetime).

- **`name`** subscribes **per device**. On subscribe and on every change it
  pushes on `/live/device/get/name` with `(track_id, device_id, name)` — the
  same shape as the query reply, so one decoder serves both. Two devices can
  be subscribed at once; `stop_listen/name` with the same two indices ends
  exactly that one subscription.
- ⚠️ **`type` and `class_name` cannot be listened for.** Subscribing answers
  a structured `/live/error ("request", <address>, <detail naming
  add_type_listener / add_class_name_listener>, 2, track_id, device_id)` and
  registers nothing. The addresses stay registered so the refusal is explicit
  and correlatable rather than an unknown-address silence.

> **Measured 2026-08-27, Live 12.4.3**, via `/live/application/dump_lom`:
> `Live.Device.Device` exposes `add_name_listener`,
> `add_parameters_listener`, `add_is_active_listener`,
> `add_is_using_compare_preset_b_listener`, `add_latency_in_ms_listener` and
> `add_latency_in_samples_listener` — and **no** `add_type_listener` or
> `add_class_name_listener`. `type` and `class_name` are plain non-observable
> read-only properties. Don't re-derive this from the apiref; if a future
> Live version adds them, re-run the dump and update this note.

Listen for parameter changes via
`/live/device/start_listen/parameter/value <track_index> <device_index> <parameter_index>`,
and stop with `stop_listen/parameter/value` (same three arguments). Each change
pushes **two** datagrams: one on `/live/device/get/parameter/value` and one on
`/live/device/get/parameter/value_string`, both echoing all three indices.

**Indices are normalised to ints** (2026-08-27) — in the parameter lookup, in
the subscription's identity, and in the echo. Clients that send floats by
default (TouchOSC; upstream issue #33) can subscribe, a start sent as floats
is stopped by a stop sent as ints, and both the query reply and the push echo
ints either way. The same index normalisation applies to the property listen
pair above.

**Truncation is uniform across both pairs** — a subscription's identity is the
leading indices and nothing else: two for the property pair
(`track_id, device_id`), three for the parameter pair
(`track_id, device_id, parameter_id`). Arguments past that are ignored, so a
stray trailing argument neither appears in a push nor keys a subscription that
a well-formed stop could never reach. Sending **fewer** than a pair's indices
is a malformed request and answers on `/live/error`.

Subscribing pushes the current value immediately, before any change — true of
every listener in this API, and how a client seeds its initial state without a
separate query. Stopping a subscription that was never started is a logged
warning and is silent on the wire.

---

## Browser API (Seshat extension — not in upstream AbletonOSC)

⚠️ These seven addresses do **not** exist in stock AbletonOSC. They are served by
`abletonosc/browser.py` in this repository, installed with
`mix abletonosc.install` (restart Live afterwards). Without that install all
seven addresses are unknown and queries time out.

Unlike the rest of AbletonOSC, these always reply — including on every error
path — so a query resolves instead of hanging.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/browser/get/items` | `category, filter, max_results` | `category, filter, 'ok', returned, total, [name, path, uri, ...]` | Search a browser category |
| `/live/browser/get/items` | | `category, filter, 'error', message` | Unknown category, or indexing failed |
| `/live/browser/load_item` | `track_id, uri` | `track_id, uri, 'ok', device_name, device_index` | Load a browser item onto a track |
| `/live/browser/load_item` | | `track_id, uri, 'error', message` | Bad track index, unknown uri, or load failed. If `track_id` is missing or not a number the echo is `-1, ""`, not what was sent |
| `/live/browser/load_item_on_return` | `return_index, uri` | `return_index, uri, 'ok', return_name, device_name, device_index` | Load a browser item onto a return track's chain |
| `/live/browser/load_item_on_return` | | `return_index, uri, 'error', message` | Bad return index, unknown uri, load failed, or the load didn't land on the return. If `return_index` is missing or not a number the echo is `-1, ""` |
| `/live/browser/load_item_on_master` | `uri` | `uri, 'ok', device_name, device_index` | Load a browser item onto the master track's chain |
| `/live/browser/load_item_on_master` | | `uri, 'error', message` | Missing/unknown uri, load failed, or the load didn't land on the master |
| `/live/browser/export` | | `export_path, 'ok', total_items` | Walk every category and write the whole index to a JSON file the handler names |
| `/live/browser/export` | | `'', 'error', message` | Arguments supplied, no category indexable, or the write failed |
| `/live/browser/preview_item` | `uri` | `uri, 'ok', name` | Audition a browser item without loading it — nothing in the set changes |
| `/live/browser/preview_item` | | `uri, 'error', message` | Missing or unknown uri, or the preview call failed |
| `/live/browser/stop_preview` | | `'ok'` | Stop the running preview |
| `/live/browser/stop_preview` | | `'error', message` | The stop call failed |

- `preview_item` plays through Live's **cue** bus, so audibility depends on the
  set's cue routing: with cue routed nowhere the preview is silent. That is a
  property of the user's set, not something the handler can detect, so a silent
  preview still replies `'ok'`. Whether a given preset carries a preview at all
  is Live's business too.
- `stop_preview` takes no argument and so has no bad-index failure to report,
  but it replies anyway — unlike the index-less getters below, nothing else
  confirms that the preview stopped.

- `category`: `instruments`, `sounds`, `drums`, `audio_effects`, `midi_effects`,
  `plugins`, `samples`, `user_library`
- `filter`: case-insensitive substring match on `"path/name"`, so it matches
  folder names too. `""` = no filter.
- `max_results`: clamped to 1–100 by the Python handler.
- `returned` is how many name/path/uri **triples** follow; `total` is how many
  matched before truncation.
- `path` is the `/`-joined chain of browser folder names above the item
  (`"Bass/808 & Sub"`), `""` for a top-level item.
- `export` takes **no arguments**. It chooses its own destination inside
  `~/.seshat/browser-exports` and returns the absolute path it wrote; an error
  reply carries `''` in that slot, so it never names a partial file.
- `uri` values come from `get/items` or `export` and are stable within a Live
  session — never construct one.
- The first walk of a large category takes seconds (it runs on Live's UI
  thread, capped at 20,000 nodes / depth 6); the result is cached per category
  for the rest of the Live session. `export` is the exception: it always drops
  the cache and re-walks, so a reindex picks up Packs and presets added since
  the last walk.
- `load_item` selects the target track and loads in one operation, then reads
  the track's device list back so `device_name` reflects what actually landed.
- `device_index` is that device's position in `track.devices` — the index
  `/live/view/set/selected_device` and every `/live/device/*` address take — so
  the caller can act on what it just loaded without re-reading the chain. It is
  **`-1`** when the device isn't on the chain to be indexed: some VST/AU plugins
  instantiate asynchronously and aren't there yet when the reply is built.
  `load_item` does not always append at the end (an instrument lands *before*
  existing audio effects), so the index is found by diffing the chain against
  what it held immediately before the load — the device that's new — falling
  back to a name match, then the last device, when diffing doesn't resolve it.
- `load_item` is regular tracks only (`song.tracks`). Return tracks and the
  master are reached with `load_item_on_return` / `load_item_on_master`
  instead — separate addresses rather than a widened `load_item`, so the
  original keeps its exact reply shape and the arity itself says which index
  space was targeted. All three share one implementation: `browser.load_item`
  loads onto `song.view.selected_track`, which accepts a return or the master
  perfectly well.
- `load_item_on_return`'s reply carries the **return's name read back after the
  load**, not the one it had before: Live renames an empty return the moment its
  first device lands (`A-Return` → `A-Reverb`, measured 2026-07-31), so the
  post-load name is the only correct one to report.
- ⚠️ **A non-effect load on a return or the master does not fail — it creates a
  stray MIDI track.** Measured 2026-07-31 on both: `browser.load_item` with an
  instrument selected loads it onto a *new* track and leaves the target chain
  untouched. So both new endpoints verify the load twice — the set's track count
  must be unchanged, and the target's chain must have gained a device — and
  return `'error'` naming the stray track if not. The stray track is **not**
  deleted; the reply names it and leaves removing it to the caller.

### `/live/browser/export`

Backs `Seshat.Library.Catalog.reindex/1`. It walks every category except
`samples` and writes one JSON file, rather than replying over OSC — a full
index is far past what a UDP datagram (or `get/items`' 100-item cap) can carry,
and Python and Elixir share a filesystem.

**The request carries no path.** The handler creates a uniquely named file with
`tempfile.mkstemp` inside `~/.seshat/browser-exports` (created owner-only on
demand) and returns the absolute path in the reply's first slot; Elixir reads it,
then deletes it. The old `[dest_path]` form — which opened a caller-supplied path
with Live's privileges — is rejected with an error reply and an error-level log
line, and writes nothing. A request in the old form against a current install, or
a no-argument request against an install predating 2026-07-30, means
`mix abletonosc.install` and a Live restart are overdue; `reindex_library` says
so rather than reporting a browser failure.

Because only the handler knows an export's name, only the handler can clean up an
export whose reply never arrived (a query timeout, a lost datagram, a path Elixir
refused). It sweeps at startup and before each export, removing matching
**regular** direct children of the export root that are at least ten minutes old
— old enough that no in-flight caller, bounded by the 120s query timeout, can
still be reading one.

```json
{
  "sounds": [
    {"name": "808 Drifter.adg", "path": "Bass/808 & Sub", "uri": "query:Sounds#Bass:FileId_5200"}
  ],
  "instruments": [ ... ]
}
```

- Takes up to a minute on a large library, all of it on Live's UI thread — the
  UI will hitch. Query it with a generous timeout (Seshat uses 120s).
- A category that fails to index is logged and skipped; the export still
  succeeds with the rest. Only a total failure returns `'error'`.
- `samples` is excluded deliberately: it is by far the largest category and raw
  samples carry no useful tags. Reach them with `get/items`.
- The `FileId_<n>` in a preset uri is the primary key of Ableton's own browser
  database, which is where Seshat gets preset tags — see
  `Seshat.Library.AbletonDB`.

---

## Return Track & Master API (Seshat extension — not in upstream AbletonOSC)

⚠️ These fifty-one addresses do **not** exist in stock AbletonOSC. They are served
by `abletonosc/return_track.py` in this repository, installed
with `mix abletonosc.install` (restart Live afterwards). Without that install all
fifty-one addresses are unknown and queries time out.

They exist because upstream reaches regular tracks only: every `/live/track/*`
handler resolves its index through `song.tracks`. Return tracks live in
`song.return_tracks` and the master in `song.master_track`, so upstream can
create and delete a return track but can neither name one nor touch its level,
and the master fader is unreachable entirely. `/live/view/set/selected_track`
indexes `song.tracks` too, which is why selecting a return needs an address of
ours as well — and so do `/live/device/*`, `/live/track/delete_device` and
`/live/view/set/selected_device`, which is why the whole device surface is
repeated here.

⚠️ **The master has no `mute`, `solo` or `arm` at all.** Reading one raises
`RuntimeError("Main track has no 'mute' property!")` rather than returning
something falsy (measured 2026-07-31, Live 12.4.3), so those addresses simply do
not exist here — and `hasattr` is not a safe feature test on a LOM object.
Return tracks have no `arm` either. Live 12 also calls the master track **Main**
in its UI and in those error strings; `song.master_track.name` is `'Main'`.

Return-track indices are 0-based **within `song.return_tracks`** — a separate
index space from regular tracks. Return N is the target of send N on every
regular track: return 0 = send A, return 1 = send B, and so on. The master
track needs no index at all.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/return_track/get/count` | | `count` | Number of return tracks. Also the "is the extension installed?" probe |
| `/live/return_track/get/name` | `return_index` | `return_index, "ok", name` | Return track name |
| | | `return_index, "error", message` | Index out of range |
| `/live/return_track/set/name` | `return_index, name` | | Rename a return track |
| `/live/return_track/get/volume` | `return_index` | `return_index, "ok", volume` | Return fader, 0.0 to 1.0 |
| | | `return_index, "error", message` | Index out of range |
| `/live/return_track/set/volume` | `return_index, volume` | | Set the return fader |
| `/live/return_track/get/panning` | `return_index` | `return_index, "ok", pan` | Return pan, -1.0 to 1.0 |
| | | `return_index, "error", message` | Index out of range |
| `/live/return_track/set/panning` | `return_index, pan` | | Set the return pan |
| `/live/return_track/get/mute` | `return_index` | `return_index, "ok", 0\|1` | Return muted? |
| | | `return_index, "error", message` | Index out of range |
| `/live/return_track/set/mute` | `return_index, 0\|1` | | Mute/unmute the return |
| `/live/return_track/get/solo` | `return_index` | `return_index, "ok", 0\|1` | Return soloed? |
| | | `return_index, "error", message` | Index out of range |
| `/live/return_track/set/solo` | `return_index, 0\|1` | | Solo/unsolo the return |
| `/live/return_track/select` | `return_index` | | Select a return track in Live's UI |
| `/live/master/get/volume` | | `volume` | Master fader, 0.0 to 1.0 |
| `/live/master/set/volume` | `volume` | | Set the master fader |
| `/live/master/get/panning` | | `pan` | Master pan, -1.0 to 1.0 |
| `/live/master/set/panning` | `pan` | | Set the master pan |
| `/live/master/get/cue_volume` | | `value` | Cue (preview/headphone) level, 0.0 to 1.0 |
| `/live/master/set/cue_volume` | `value` | | Set the cue level |
| `/live/master/select` | | | Select the master track in Live's UI |
| `/live/return_track/start_listen/name` | `return_index` | | Push `/live/return_track/get/name [return_index, name]` on every change |
| `/live/return_track/stop_listen/name` | `return_index` | | |
| `/live/return_track/start_listen/volume` | `return_index` | | Push `/live/return_track/get/volume [return_index, volume]` on every change |
| `/live/return_track/stop_listen/volume` | `return_index` | | |
| `/live/return_track/start_listen/panning` | `return_index` | | Push `/live/return_track/get/panning [return_index, pan]` on every change |
| `/live/return_track/stop_listen/panning` | `return_index` | | |
| `/live/return_track/start_listen/mute` | `return_index` | | Push `/live/return_track/get/mute [return_index, muted]` on every change |
| `/live/return_track/stop_listen/mute` | `return_index` | | |
| `/live/return_track/start_listen/solo` | `return_index` | | Push `/live/return_track/get/solo [return_index, soloed]` on every change |
| `/live/return_track/stop_listen/solo` | `return_index` | | |
| `/live/master/start_listen/volume` | | | Push `/live/master/get/volume [volume]` on every change |
| `/live/master/stop_listen/volume` | | | |
| `/live/master/start_listen/panning` | | | Push `/live/master/get/panning [pan]` on every change |
| `/live/master/stop_listen/panning` | | | |
| `/live/master/start_listen/cue_volume` | | | Push `/live/master/get/cue_volume [value]` on every change |
| `/live/master/stop_listen/cue_volume` | | | |

### Return Track & Master: Device Chains

Upstream's `/live/device/*`, `/live/track/delete_device` and
`/live/view/set/selected_device` all resolve through `song.tracks`, so the whole
device surface is repeated here — once indexed by return, once for the master.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/return_track/get/devices` | `return_index` | `return_index, "ok", count, [name, type, class_name] × count` | The return's whole device chain in one reply |
| | | `return_index, "error", message` | Index out of range |
| `/live/master/get/devices` | | `count, [name, type, class_name] × count` | The master's device chain (no index → no failure path) |
| `/live/return_track/device/get/name` | `return_index, device_index` | `return_index, device_index, "ok", name` | Device name |
| | | `return_index, device_index, "error", message` | Either index out of range |
| `/live/master/device/get/name` | `device_index` | `device_index, "ok", name` | Device name |
| | | `device_index, "error", message` | Index out of range |
| `/live/return_track/device/get/parameters` | `return_index, device_index` | `return_index, device_index, "ok", device_name, count, [name, value, min, max] × count` | Every parameter in one reply |
| | | `return_index, device_index, "error", message` | Either index out of range |
| `/live/master/device/get/parameters` | `device_index` | `device_index, "ok", device_name, count, [name, value, min, max] × count` | Every parameter in one reply |
| | | `device_index, "error", message` | Index out of range |
| `/live/return_track/device/get/parameter/value` | `return_index, device_index, parameter_index` | `return_index, device_index, parameter_index, "ok", value` | One parameter's numeric value |
| | | `return_index, device_index, parameter_index, "error", message` | Any index out of range |
| `/live/master/device/get/parameter/value` | `device_index, parameter_index` | `device_index, parameter_index, "ok", value` | One parameter's numeric value |
| | | `device_index, parameter_index, "error", message` | Either index out of range |
| `/live/return_track/device/get/parameter/value_string` | `return_index, device_index, parameter_index` | `return_index, device_index, parameter_index, "ok", string` | Live's display value ("2.5 kHz") |
| | | `return_index, device_index, parameter_index, "error", message` | Any index out of range |
| `/live/master/device/get/parameter/value_string` | `device_index, parameter_index` | `device_index, parameter_index, "ok", string` | Live's display value |
| | | `device_index, parameter_index, "error", message` | Either index out of range |
| `/live/return_track/device/set/parameter/value` | `return_index, device_index, parameter_index, value` | | Set one parameter (silent) |
| `/live/master/device/set/parameter/value` | `device_index, parameter_index, value` | | Set one parameter (silent) |
| `/live/return_track/delete_device` | `return_index, device_index` | `return_index, device_index, "ok", remaining` | Delete a device; `remaining` is the chain length re-read afterwards |
| | | `return_index, device_index, "error", message` | Either index out of range, or the delete raised |
| `/live/master/delete_device` | `device_index` | `device_index, "ok", remaining` | Delete a device from the master chain |
| | | `device_index, "error", message` | Index out of range, or the delete raised |
| `/live/return_track/select_device` | `return_index, device_index` | | Select a device on a return, in Live's UI |
| `/live/master/select_device` | `device_index` | | Select a device on the master, in Live's UI |

- **Getters always reply**, on the address they were called on, including on
  every error path — the same rule as the Browser API above, and the opposite of
  upstream's "raise inside the callback and send nothing". For an optional
  extension that silence is ambiguous: a bad index would be indistinguishable
  from an install that never happened, and would cost a full guard timeout to
  learn nothing either way. With the envelope, **an error reply means a bad
  index and silence means the extension isn't loaded.**
- **The index-less master getters reply with the bare value**, no envelope:
  `get/count`, `/live/master/get/volume`, `/live/master/get/panning`,
  `/live/master/get/cue_volume` and `/live/master/get/devices` take nothing to
  look up, so they have no failure to report.
- **`delete_device` is the one setter-shaped address that replies.** It is a
  *method* with a real failure path — the same class as `load_item` — and the
  alternative is sandwiching it between two count reads to learn whether it
  landed. Its `remaining` is the chain length re-read from Live afterwards, not
  a number computed from the request.
- **The two list getters combine what upstream splits.** `get/devices` carries
  `count` then `count` × `(name, type, class_name)`;
  `device/get/parameters` carries `device_name`, `count`, then `count` ×
  `(name, value, min, max)`. Upstream needs three and five separate round trips
  respectively, and on a protocol with no request ids, assembling parallel lists
  from separate replies risks describing two different devices. `count` comes
  first so the flat tail stays parseable — a tail that isn't a whole number of
  triples (or quadruples), or whose group count disagrees with `count`, is a
  shape error the caller must reject rather than truncate. A large device
  (Operator, ~130 parameters) makes a ~5–6 KB datagram; `Transport`'s receive
  buffer is 64 KB, and upstream's own list getters already ship multi-KB
  replies.
- **Setters are silent**, like upstream's. Every caller guards with the matching
  getter immediately beforehand, so a bad index has already been reported by the
  time a setter goes out, and nothing waits on one.
- `select`, `select_device` and `/live/master/select` are silent too, for a
  stronger reason: they are view steering that follows a tool which has already
  succeeded, and steering must never fail — or delay — the thing it follows. A
  bad index is logged in Live and nothing happens. `song.view.select_device`
  also opens `Detail/DeviceChain` on its own (measured 2026-07-31), so the
  follow cam needs no separate pane call after one.
- Volume is `mixer_device.volume.value` on Live's fader scale, the same property
  and scale as `/live/track/get|set/volume`. Panning is
  `mixer_device.panning.value`, -1.0 to 1.0, displayed by Live in its L/C/R form
  (`-1.0` → `50L`, `0.0` → `C`, `1.0` → `50R`) — not degrees or a percentage.
  Cue volume is `mixer_device.cue_volume.value`, 0.0 to 1.0, parameter name
  **`Preview Volume`**, and shares the *identical* dB curve with track volume
  (`0.0` → `-inf dB`, `0.5` → `-14.0 dB`, `0.85` → `0.0 dB`, `1.0` → `6.0 dB`).
  All three measured against Live 12.4.3, 2026-07-31.
- Mute and solo are plain `Track` properties, not DeviceParameters — so their
  listeners use the base class's `_start_listen` while the three mixer
  parameters need the hand-rolled one below. The getters report `0`/`1`; Live's
  own push carries a bool.
- Creating and deleting return tracks is upstream's job:
  `/live/song/create_return_track` (no arguments, appends after the existing
  returns) and `/live/song/delete_return_track [return_index]`. A newly created
  return's index is therefore the old `get/count` — query the count, create,
  then `set/name` at that index.
- Sends belong to the *regular* track that feeds the return, so they stay on
  `/live/track/get|set/send [track_id, send_id, ...]` in the Track API above.
- **The listeners push the bare value**, not the ok/error envelope — a push has
  no failure path to report, and the differing arity is what lets
  `Seshat.Session.State` accept a push and a query reply on the same address
  without confusing them. Like upstream's listeners, each sends once immediately
  on subscribe. `start_listen`/`stop_listen` reply with nothing at all on a bad
  index (they are guarded by `get/count` and nothing waits on them).
- A `get/*` address therefore carries both query replies and listener pushes.
  Live's own track listeners upstream already work this way, and a push landing
  on a pending query is harmless: it carries a current value.
- Return-track volume, pan and the master's cue level are listened to on
  `mixer_device.*`, which are `DeviceParameter`s with `add_value_listener`
  rather than Track properties — so those listeners are hand-rolled instead of
  using the base class's `_start_listen`, which would derive
  `/live/return_track/get/value`. Because the base class's bookkeeping key is
  `(prop, params)` and `prop` is forced to `"value"` for all of them, the
  property has to be discriminated in the *params* half:
  `(index, "volume")`, `(index, "panning")`, `("master", "cue_volume")` and so
  on. Without that, subscribing a return's pan would silently evict its volume
  listener. The tuple never reaches the wire.
- **Re-subscribing an index unbinds the object it used to mean.** These
  listeners are keyed by return index but bound to a return-track object, and
  deleting a return renumbers everything after it. Upstream's `_stop_listen`
  removes the callback from whatever target it is *handed*, so re-subscribing
  index 0 after a delete would try to unbind it from the wrong object, silently
  fail, and leave the old listener pushing under an index that now belongs to
  someone else. The fork's base class unbinds from the object the callback was
  actually registered on, which is what makes any index-keyed listener safe —
  see the note under the Track API above.

---

## Song Structure API (Seshat extension — not in upstream AbletonOSC)

⚠️ These four addresses do **not** exist in stock AbletonOSC. They are served by
`abletonosc/song_structure.py` in this repository, installed
with `mix abletonosc.install` (restart Live afterwards).

Upstream's `SongHandler` registers `start_listen` only for the *scalar* Song
properties in its hardcoded list (tempo, root_note, is_playing, …). `tracks` and
`return_tracks` are lists of LOM objects, so they aren't in it — meaning nothing
upstream fires when a track is added, deleted, duplicated or reordered, and
`Seshat.Session.State`'s mirror drifts silently.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/song/start_listen/tracks` | | | Push `/live/song/get/tracks` on every change to the track list |
| `/live/song/stop_listen/tracks` | | | |
| `/live/song/start_listen/return_tracks` | | | Push `/live/song/get/return_tracks` on every change to the return list |
| `/live/song/stop_listen/return_tracks` | | | |

The two push addresses are **push-only** — sent by the listener callback, never
registered as handlers, so querying them gets silence:

| Push address | Args |
|---|---|
| `/live/song/get/tracks` | `name0, name1, …` (regular tracks, in order) |
| `/live/song/get/return_tracks` | `name0, name1, …` (return tracks, in send order) |

- **Names only, deliberately.** The push is a change *signal*; `Session.State`
  compares it against its mirror and re-reads everything only when it differs, so
  this handler never becomes a second source of truth for track state.
- Upstream registers no handler on either push address — its equivalent is
  `/live/song/get/track_names`, a different address. No collision.
- Neither address exists on stock AbletonOSC, so a Live without the install just
  drops the `start_listen` messages: no error, and the mirror falls back to
  refresh-only staleness.

### `/live/startup` is acted on

AbletonOSC sends `/live/startup` (see the Application API above) whenever its
control surface initialises — Live launching, a different set being loaded, or
AbletonOSC toggled off and on. `Seshat.Session.State` treats it as a refresh
trigger, because by that point every listener registered against the previous
song object is dead: without it the mirror would be stale *permanently*, not
just until the next change.

---

## MidiMap API

Assign MIDI CC to Live parameters. Note: channels are 0-indexed (MIDI channel 1 = index 0).

| Address | Query Params | Description |
|---|---|---|
| `/live/midimap/map_cc` | `track_id, device_id, param_id, channel, cc` | Map CC to parameter |

---

## Quick Reference: Common POC Commands

```
# Test connection
/live/test

# Get session info
/live/song/get/tempo
/live/song/get/num_tracks
/live/song/get/track_names

# Transport
/live/song/start_playing
/live/song/stop_playing
/live/song/set/tempo 120.0

# Track control (track_id is 0-indexed)
/live/track/set/panning 0 -1.0       # Pan track 0 hard left
/live/track/set/panning 0 0.0        # Pan track 0 center
/live/track/set/panning 0 1.0        # Pan track 0 hard right
/live/track/set/volume 0 0.85        # Set track 0 volume
/live/track/set/mute 0 1             # Mute track 0
/live/track/set/mute 0 0             # Unmute track 0
/live/track/set/solo 0 1             # Solo track 0
/live/track/set/solo 0 0             # Unsolo track 0

# Create/delete tracks
/live/song/create_midi_track -1      # New MIDI track at end
/live/song/create_audio_track -1     # New audio track at end
/live/song/delete_track 3            # Delete track 3
```
