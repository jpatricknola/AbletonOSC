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

**One family breaks that shape deliberately.** The return-track and master
getters added by this fork answer a *query* with an `ok`/`error` envelope,
while their listener pushes carry the bare value (§ "Return Track & Master:
`Track` parity"). A push has no failure path to report, and the differing
arity is what lets a consumer tell the two apart on one address — so a decoder
written for `/live/return_track/*` and `/live/master/*` must branch on arity
rather than assume the shapes match. Everywhere else in this document the
paragraph above holds.

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
`Song.appointed_device`, `Track.group_track`, `ClipSlot.clip`, `Clip.groove`,
`Song.groove_pool` (a collection of them), and `Song.View`'s `selected_chain`,
`selected_parameter`, `mod_mapping_device` and `mod_mapping_parameter`. The
generic property loops cannot put one of those on the wire (the value is
unencodable, so it becomes an error or a `None`), so each has a hand-written
handler that answers with **indices into the collections the existing address
families already accept**. The rules, which
every later object-valued read follows:

1. An object-valued member never enters the generic property loop.
2. The reply names the object by index, prefixed by the track-identity
   category (see **Selected-track identity** under the View API) when the
   owning track can be any of the three kinds:

   | Kind of member | Reply shape | Example |
   |---|---|---|
   | Track-valued, regular tracks only | `track_index` | `/live/track/get/group_track` |
   | Clip-valued, in a slot the request already names | `clip_index` | `/live/clip_slot/get/clip` |
   | Clip-slot-valued, regular tracks only | `track_index, scene_index` | `/live/view/get/highlighted_clip_slot` |
   | Groove-valued | `groove_index` (into `/live/song/get/groove_pool`) | `/live/clip/get/groove` |
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
   resolver exists. ⚠️ **"None" is not always a `None`.** `Track.group_track`
   *is* `None` when there is none (measured against Live 12.4.5 on 2026-08-29:
   `/live/track/get/group_track 0` answered `-1` for an ungrouped track),
   whereas ⚠️ `Clip.groove` is taken to *always* hold an object — Live's
   discriminator is the companion flag `Clip.has_groove`, and an `is None`
   guard there can never fire. Note the tier change: the `group_track`
   reading is measured, the `Clip.groove` one is **inferred from
   `has_groove`'s existence, not measured** — this fork has never seen
   `has_groove` answer `False` (see the **Groove API**, "The clip↔groove
   readings"). Before assuming `is None` answers "none" for a new
   object-valued read, look for a `has_<member>` flag beside it.
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

What *is* measured is that an `==` scan over LOM proxies resolves correctly
for at least one class: with Live's selection moved to scene 2,
`/live/view/get/selected_clip` answered `(0, 2)` (Live 12.4.5, 2026-08-29).
That getter composes a track index with a scene index, and the scene half is
the scan — `list(song.scenes).index(song.view.selected_scene)`. So
"proxies compare equal to anything" is refuted for `Scene`; whether `Groove`
behaves the same is still unmeasured (see the **Groove API**).

The setter side is deliberately narrow. `/live/song/set/appointed_device` takes
the same triple its getter replies and *validates* every argument — an unknown
category (`"none"` included), a negative or out-of-range index, and a master
index other than `0` are each a `ValueError` arriving as a structured
`/live/error`, never a Python negative-index wrap-around. It reaches top-level
devices only, and cannot un-appoint.

`/live/clip/set/groove` is the same shape. It has no category slot for rule 4
to govern — rule 2's table gives it a bare `groove_index` — and it **takes no
exception to rule 4's closing clause**, "`-1` is an answer, never an
argument". It was once specified to accept exactly `-1` as "clear the
assignment" — the one sanctioned place where `-1` was an argument. That is
withdrawn: Live's setter refuses `NoneType` and no other spelling for "no
groove" is documented, so assignment is one-way and `-1` is now a rejected
request. `-1` is an answer, never an argument, everywhere in this fork with no
exceptions. See the **Groove API**, "Assignment is one-way".

⚠️ **Seshat extension.** Every object-valued read is added by this fork; none
exists in stock AbletonOSC — `track/get/group_track`, `clip_slot/get/clip`, the
`song/…/appointed_device` trio, the five `view/get/…` rows, and the groove
family (`clip/…/groove`, `song/…/groove_pool`, and `/live/groove/*`; see the
**Groove API**). `Track.group_track` and `Song.View.highlighted_clip_slot` are
the two members of the set that are not observable, so they are the only ones
that could not have a listen pair even if a consumer asked. Without the install
they are unknown addresses: the getters never reply and the setters silently do
nothing.

### Handlers that name a file to read

⚠️ **Seshat extension.** Three addresses take an argument that names a file on
disk for Live to **read**, and all three follow one rule. Upstream AbletonOSC
has none of them.

| Address | What it does |
|---|---|
| `/live/clip_slot/create_audio_clip` | Imports the file into a Session slot as an audio clip |
| `/live/track/create_audio_clip` | Imports the file onto the track's Arrangement at a position |
| `/live/device/replace_sample` | Swaps the sample of a top-level Simpler |

**The wire never carries a path.** The argument is a *name relative to a single
fixed import root*:

    ~/.seshat/generated

A bare `foo.wav` is the normal form; `sub/foo.wav` also resolves. The handler
joins the name onto the root and builds the absolute path itself, so a caller
can never hand Live a path of its own choosing. Given a fixed root, an absolute
argument could only ever name files the relative form already names — it would
buy the caller nothing and keep exactly the shape this rule exists to remove.

The root is **not created by this fork**. A root that does not exist simply
refuses everything; the consumer creates it (Seshat, mode 0700, alongside
`~/.seshat/browser-exports`). It is not configurable and no environment
variable redirects it: it is one constant on one line in
`abletonosc/path_safety.py`, and changing it is a fork change.

The rule, in order, is:

1. reject a non-string, an empty string, or a name containing a NUL;
2. reject an absolute path — the refusal message names the root, because
   nothing else on the wire tells a caller where names resolve from;
3. resolve **both** sides with `realpath`: `root = realpath(IMPORT_ROOT)` and
   `candidate = realpath(join(root, name))`;
4. reject unless `candidate` is strictly under `root` — the root itself is a
   rejection. Resolving first is what defeats a `..` component and a symlink
   inside the root that points outside it;
5. reject unless `candidate` is a regular file. Already resolved, so this one
   check also refuses a directory, a dangling symlink and a device node;
6. otherwise hand `candidate` to Live.

A symlink inside the root that resolves to a file **inside** the root is
accepted deliberately: the rule is "resolves inside the root", not "is not a
symlink". Every rejection is logged at error level and **nothing is opened —
no Live method is called at all on a refused request.**

**On a target the address applies to, all three always reply**, on the address
they were called on, including on every refusal — the `/live/browser/*`
convention, not the silent-on-success convention of the generic
`/live/track/<method>` and `/live/clip_slot/<method>` loops. A path refusal is
caller-fixable and undiagnosable from silence, the importing caller needs the
clip's length back, and silence would otherwise be indistinguishable from an
install that predates these addresses. `replace_sample` has one applicability
failure outside that convention: on a device that is not a Simpler, binding the
method raises and the direct request receives structured `/live/error` instead
of a reply on `/live/device/replace_sample` (and an address-pattern request
skips it silently), as detailed below and in the address row.

The `"ok"`/`"error"` discriminator sits at a **fixed index** — 2 for the
clip-slot and device addresses, 1 for the track address — so a client switches
on it positionally. **Arity is not the invariant:** the clip-slot and device
addresses reply four fields either way, but the track address replies four on
success and three on a refusal. Do not count arguments; read the fixed slot.

**Two failure channels, and the split is deliberate.** A bad `track_index`,
`clip_index` or `device_index` raises inside the wrapper *before* the worker
runs, so it arrives as the structured `/live/error ["request", address, …]`
envelope like every other address in its family. A non-Simpler target for
`replace_sample` takes that channel too: the worker binds the method before it
does anything else, and the resulting `AttributeError` means the endpoint does
not apply. Everything else the worker decides — a refused name, an unreadable
occupancy flag, an occupied slot, a malformed argument list, an exception
raised by Live inside the call — arrives as an `"error"` reply on the request
address instead. A client that treats the two as one will mis-handle both.

**Under an address pattern the three do not behave alike, deliberately.**
`/live/device/replace_sample` binds the Simpler method *before* it looks at the
name, so a device that is not a Simpler is the silent wildcard skip
[README](README.md#wildcard-queries) describes. The two `create_audio_clip`
addresses do the opposite: a missing or malformed argument list is an `"error"`
reply, never a skip. So `/live/clip_slot/* <t> <c>` and `/live/track/* <t>` each
draw one `"error"` datagram from these addresses — they are the only addresses
on those two prefixes that *answer* a malformed pattern request at all. A
malformed request is not the same thing as an endpoint that does not apply, and
answering says which it was.

⚠️ **That is not a claim that the rest of either prefix is inert.** A pattern
request matches every address on the prefix, and the neighbours react to an
empty argument tail in their own ways rather than staying quiet:
`/live/track/stop_all_clips`, `/live/clip_slot/fire`, `/live/clip_slot/stop` and
`/live/clip_slot/delete_clip` take no required argument, so they **execute**;
`/live/track/insert_device`, `/live/track/delete_device` and
`/live/clip_slot/create_clip` raise `TypeError` inside `_call_method`, which is
not one of the wildcard-skip classes, so each answers its own `/live/error`. Do
not use a pattern request on these prefixes to probe. (Nothing in Seshat sends
one today.)

**This is the read-side rule. `/live/browser/export` is the write-side one**,
and it is deliberately different: it takes no destination from the wire at all,
chooses one inside a private root and replies with the absolute path it wrote.
A read has to name *which* existing file; a write does not. (`EXPORT_ROOT` is
`abspath` + `expanduser` and explicitly **not** `realpath`, because Seshat
re-derives that exact string in Elixir with `Path.expand/1`; `IMPORT_ROOT`'s
resolved form never leaves the handler, so it can and must resolve both sides.
See the comments in `abletonosc/browser.py` and `abletonosc/path_safety.py`.)

One address still violates the write-side rule and is **not** covered here:
`/live/application/dump_lom` takes an arbitrary wire path and writes it with
Live's privileges. It is tracked in `issues.md` (Low) and should adopt
`browser/export`'s pattern, not this one. It remains the *only* such address:
`/live/application/dump_lom_instances`, added later beside it and writing a
file of the same kind, deliberately takes **no** path argument at all and
writes a fixed location. The inconsistency between the two is not an oversight
to be tidied by giving the newer one a path — it is the older one that is
wrong, and the newer one is the pattern.

The command socket is loopback-only, so a caller reaching any of these
addresses is already local code running as the user and could read the file
without Live at all. That is why the read side can be a bounded root rather
than `export`'s no-argument form.

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
  - The one exception is `/live/application/get/has_option`, whose ok path
    logs its answer at `info` (`has_option for application: <key> = <bool>`)
    precisely so it is readable this way. It was added on 2026-08-29 because
    the address had shipped with the wrong contract documented, unmeasurable
    on a machine where 11001 is taken. An `info` record reaches
    `logs/abletonosc.log` only — `manager.py`'s `LiveOSCErrorLogHandler`,
    the one relay onto OSC, is set to `logging.ERROR` — so this is not new
    wire traffic.
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
| `/live/application/get/average_process_usage` | | `average_process_usage` | Live's average CPU load. (Until 2026-08-29 `application.py` also *sent* one argument-less datagram on this address at every initialisation, a stray sibling of `/live/startup` that this doc told clients to ignore. It is gone: startup traffic is `/live/startup` alone.) |
| `/live/application/get/version_string` | | `version` | Seshat extension. Live's full version string, e.g. `12.4.3` — `get/version` gives only the major and minor halves |
| `/live/application/get/bugfix_version` | | `bugfix` | Seshat extension. The third component, e.g. the `3` of `12.4.3` |
| `/live/application/get/build_id` | | `build_id` | Seshat extension. The exact build |
| `/live/application/get/variant` | | `variant` | Seshat extension. Live's edition (Suite, Standard, Intro, Lite), which decides whether a given LOM member exists at all — see `get/unavailable_features`. ⚠️ The exact strings Live returns are unmeasured |
| `/live/application/get/has_option` | `key` | `key, present` | Seshat extension. Looks up a key in Live's internal option table. **Not an Options.txt query** — it shipped documented as one and is not: `key` must be **exactly 64 hexadecimal characters** (`[0-9a-fA-F]`, case-insensitive to Live), which is a digest of an internal Live option name. Ableton publishes no name→key mapping and the digest is not a plain SHA-256 of the name it guards, so a caller can only use a key it already holds. The one key readable anywhere is in Live's own shipped Python: `abl/live/licensing/__init__.pyc` calls `has_option("fbb8b6e2603b931b8fc884f09e56c4d9391d78105cbf2c711c9a22e0fb7152fd")` to guard a `skip_unlock_file` property. The key is echoed back verbatim — not case-folded — as the only discriminator for a client firing a burst. A malformed key is rejected by the handler with a structured `/live/error` naming the requirement, and **Live is never called**; under a wildcard such as `/live/application/get/*` it is a silent skip instead (`ValueError` is in `WILDCARD_SKIP_EXCEPTIONS`). The answer is also written to `logs/abletonosc.log`, so the address is readable without a free reply port |
| `/live/application/get/open_dialog_count` | | `count` | Seshat extension. Number of open Live dialogs; `0` when none. Observable — see **Detecting dialogs** below |
| `/live/application/get/current_dialog_message` | | `message` | Seshat extension. Text of the last dialog that appeared; empty once all dialogs have gone. **Not** observable |
| `/live/application/get/current_dialog_button_count` | | `count` | Seshat extension. Buttons on the current dialog. **Not** observable |
| `/live/application/get/peak_process_usage` | | `usage` | Seshat extension. Live's peak CPU load — the companion to `average_process_usage`. Observable |
| `/live/application/get/number_of_push_apps_running` | | `count` | Seshat extension. Connected Push apps |
| `/live/application/get/unavailable_features` | | `feature, ...` | Seshat extension. Features unavailable in the running edition, flattened into one reply with no count prefix, like `/live/track/get/available_input_routing_types`. An empty list still replies — with zero arguments. ⚠️ Each element is coerced with `str()`; whether Live's elements are strings or enum objects is unmeasured |
| `/live/application/get/control_surfaces` | | `name, ...` | Seshat extension. The **class name** of each control surface selected in preferences, in preferences-slot order, flattened like the row above. An unassigned slot goes out as the empty string so the remaining slots keep their positions. Names only, by design — the surface objects are deliberately not traversable from the wire. ⚠️ How Live represents an empty slot is unmeasured |
| `/live/application/start_listen/open_dialog_count` | | pushes on `/live/application/get/open_dialog_count` | Seshat extension. Immediate initial push, then one per change |
| `/live/application/stop_listen/open_dialog_count` | | | Seshat extension |
| `/live/application/start_listen/peak_process_usage` | | pushes on `/live/application/get/peak_process_usage` | Seshat extension. Immediate initial push, then one per change |
| `/live/application/stop_listen/peak_process_usage` | | | Seshat extension |
| `/live/application/show_message` | `text` | `result` | Seshat extension. Raises a Live dialog carrying `text`. **OK-only**: every other Live parameter keeps its default, including `buttons` — see the note below. ⚠️ Whether the call blocks, and what the returned int means, are unmeasured; it is passed through opaquely |
| `/live/application/show_on_the_fly_message` | `text` | `result` | Seshat extension. The transient variant, same shape and same OK-only rule. ⚠️ Where it appears with no Push connected is unmeasured |
| `/live/application/dump_lom` | `[path]` | `path, num_classes, num_addresses` | Seshat extension. Walks the installed Live API (every class and member reachable from the `Live` module, plus the Max-for-Live device tables) and this server's registered addresses, and writes both to a JSON file — `path` if given, else `logs/lom_dump.json` next to the Remote Script. `tools/lom_gaps.py` diffs the two; `FORK_GAPS.md` is maintained from that diff. ⚠️ Takes an arbitrary path from the wire and writes it with Live's privileges — the opposite of `browser/export`'s policy; see `issues.md`, "Bound `/live/application/dump_lom`'s output path" |
| `/live/application/dump_lom_instances` | | `path, num_types, num_objects, num_errors` | Seshat extension. Walks the **live object graph** — from `get_application()` and `song` through tracks, devices, chains and parameters — and records each object's *actual* type, the value type behind each property, and what every read returned or raised, to `logs/lom_instances.json`. This is the only channel that can answer what a property holds: every one of Live's 894 properties has a getter and none carries a docstring, so no static walk can see it. **Takes no path from the wire** — unlike `dump_lom` above, which is the fork's one open violation of its own write-side rule. Read-only by construction: it instantiates nothing, calls a method only when the name carries a `get_`/`is_`/`has_`/`can_` prefix *and* its Boost.Python signature takes only the receiver *and* it is not policy-denylisted (18 of 589 methods, measured 2026-08-30 on Live 12.4.5), and it **never calls a listener member**, so it cannot disturb a running client's subscriptions. ⚠️ The output is **set-scoped, not Live-scoped**: it measures whatever set is open, and `provenance` records which one. ⚠️ How long the walk takes on a large set, and whether it stalls Live's UI, is **unmeasured** — `provenance.walk_seconds` is recorded so the first runs answer it |
| `/live/api/reload` | | | Live reload of AbletonOSC server code (dev only — see the warning below). Sends no reply on success. A reload that **fails part-way** logs at `error` level and therefore arrives as `/live/error` `"log", ...` naming the module it stopped at — the only signal the caller gets, and the reason a silent success is no longer evidence the edit is live |
| `/live/api/get/log_level` | | `log_level` | Current log level (default: `info`) |
| `/live/api/set/log_level` | `log_level` | | Set log level: `debug`, `info`, `warning`, `error`, `critical` |
| `/live/api/show_message` | `message` | | Show message in Live's status bar |

(`/live/api/show_message` and `/live/application/show_message` are different
addresses and different mechanisms: the first writes Live's status bar and
replies nothing, the second raises an actual dialog and replies with Live's
return value.)

**Detecting dialogs.** A blocking Live dialog used to be invisible to a
client without accessibility APIs or pixel scraping. It isn't: three
`Application` members describe one exactly. Only `open_dialog_count` is
observable, though, so the pattern is:

1. `start_listen/open_dialog_count` once, at startup.
2. On a push with a non-zero count, read `get/current_dialog_message` and
   `get/current_dialog_button_count` to find out what appeared.
3. A push back to `0` means the dialog has gone.

`current_dialog_message` and `current_dialog_button_count` have **no**
`start_listen`/`stop_listen` addresses, because Live offers no
`add_<name>_listener` for them — there is nothing to subscribe to. They are
not registered at all, so a `start_listen` sent to one is an *unknown
address*: it is dropped with a log line and **no `/live/error` comes back**.
Don't wait on a reply there.

⚠️ **Dialogs raised over OSC are OK-only, on purpose.**
`show_message` and `show_on_the_fly_message` pass Live the text and nothing
else, so `buttons` keeps its `OK_BUTTON` default. There is deliberately no
`press_current_dialog_button` address — a dialog on screen may be guarding
unsaved work — so a dialog offering choices would be one the remote has no
way to answer. The two constraints move together: exposing button choices
requires exposing the press, and that is a separate, reviewed decision.

Both `show_*` addresses also sit inside `/live/application/*`'s wildcard
blast radius: `*` matches one or more non-`/` characters within a single
address segment (see the intro's "Wildcard patterns supported" note and
`osc_server.py`'s `process_message`), so a broadcast like
`/live/application/* "x"` calls `show_message("x")` as a side effect —
raising exactly this undismissable dialog even though the sender may have
meant something else entirely. Because `*` cannot cross a `/`, that pattern
does *not* reach any `/live/application/get/...` address: it matches exactly
the three top-level routes — `dump_lom`, `show_message` and
`show_on_the_fly_message`. Sweeping the getters takes
`/live/application/get/*`, which is a different, side-effect-free pattern.
`dump_lom` sits in the `/live/application/*` blast radius already, for the
unrelated reason noted in its own row above.

> **Partially measured against Live 12.4.5 on 2026-08-29.** These addresses
> shipped without a measurement pass and one has since run. What it settled:
>
> - **`has_option` does not do what this document said.** It is not an
>   Options.txt query — it takes a 64-hex-character key. See its row above.
>   A second run the same day settled the rest of the contract, by the
>   no-probe variant below, with an
>   `/live/application/get/open_dialog_count` read interleaved between cases
>   as a marker so each log line correlates to one send:
>
>   | Argument | Result |
>   |---|---|
>   | 64 hex chars (`"0" * 64`) | **Accepted** — no error, no log output (as measured, before this change added the ok-path log line); Live answered |
>   | the `abl.live.licensing` key, lower case | **Accepted** |
>   | the same key, **upper** case | **Accepted** — the hex is case-insensitive |
>   | 63 hex chars | `IndexError: basic_string` → `/live/error` |
>   | empty string | `IndexError: basic_string` → `/live/error` |
>   | 64 non-hex chars (`"z" * 64`) | `RuntimeError: Key contains non-hex characters` → `/live/error` |
>   | `-_EnableExtendedFileFormat` (26 chars, non-hex) | `RuntimeError: Key contains non-hex characters` — the hex check fires **before** the length check |
>
>   So a well-formed key does answer: the address is a working lookup with an
>   argument nobody had documented, not a dead end. The handler now validates
>   the key itself and logs the answer — see its row above and `SESHAT.md`.
> - **The registration table is exactly 21 addresses**, matching
>   `tests_unit/test_application.py::test_registration_table_is_exactly_this`,
>   read back from the live server through `/live/application/dump_lom`.
> - **Every remaining getter answers without raising**, including the four
>   version reads and both flattened list reads, so no member name or arity
>   in this section is wrong.
>
> Still unmeasured, and still carrying ⚠️ — the exact `get/variant` strings,
> whether `unavailable_features` elements are strings or enum objects, how
> `control_surfaces` represents an unassigned slot, and whether
> `show_message` blocks the tick thread. These are **values**, and this fork
> cannot read a reply on the machine it is developed on: replies go to
> `(sender_host, 11001)`, that port belongs to another consumer, and no
> loopback alias is bindable (`Errno 49`), so verification reads the
> handler's own log lines — which these custom getters do not write. They
> need either a free reply port or a temporary logging patch.
>
> `has_option`'s **returned boolean** was in that list and no longer is: the
> handler logs it, so it is readable from `logs/abletonosc.log` by the
> no-probe variant. No value has been recorded yet — the log line ships in
> the same change and needs a Live running the new code to produce one — so
> what any particular key answers on a given installation is still an open
> reading, not an unreachable one. The reply
> *shapes* are pinned by `tests_unit/test_application.py` and do not depend
> on any of it; the handler coerces defensively (`str()` on every list
> element, `None` slots to `""`) so a wrong guess degrades the reply's
> readability, not its well-formedness. The measurement procedure is
> § "Measuring the Live API without building the feature first" above.

⚠️ **Don't reach for `/live/api/reload`.** Two problems, both observed:

1. It reloads modules, not files on disk that Live never imported. Editing the
   Python in this repository does nothing until it is copied into Live's
   Remote Scripts (Seshat's `mix abletonosc.install` does that), and a reload won't pick up a *new* module either — that
   needs Live restarted, or AbletonOSC toggled off and back on under
   Preferences > Link/Tempo/MIDI > Control Surface. The two port constants are
   restart-only too: `OSCServer` copies them into instance state and binds its
   socket during startup, and a module reload does not replace that running
   server.
2. It can take the whole API down. `Manager.clear_api()` unregisters every
   address (`clear_handlers()`) as its first line, *then* tears down each
   handler's listeners. If anything in that teardown or in the re-import that
   follows raises, the script is left with zero handlers registered and no way
   to re-register them over OSC, since `/live/api/reload` has unregistered
   itself too. Every address then answers "Unknown OSC address" until Live is
   restarted or the control surface is toggled. (Observed once as a `KeyError`
   from a listener on a deleted track; the fork's `_stop_listen` now guards
   that path, so the current trigger is unknown — the failure mode isn't.)

A third problem is **fixed**, and is recorded here because the probe rig above
depended on it. `reload_imports` used to abort on `abletonosc.introspection` —
imported only inside the `/live/application/dump_lom` callback, so on any
session where that address had never been fired the attribute did not exist —
and then log `Reloaded code` anyway. Every handler module after it was skipped,
so a probe handler added to `return_track.py` never registered and its address
answered `Unknown OSC address`. The reload now (a) imports `introspection`
eagerly, (b) names the module it stopped at, and (c) logs a partial reload at
`error`, which reaches the client as `/live/error` `"log", ...` rather than
sitting in the log file above an unconditional success line. Step 2 of the
probe rig works on a fresh session as written.

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
reply with their own `"error"`-tagged envelopes, and the four fork-added
`/live/view/...` setters (`show_view`, `focus_view`, `hide_view`, `set/detail_clip`) fail
silently by design. Upstream's four `/live/view/set/selected_*` setters have no
guard: a bad index raises and comes back as a `"request"` error like any other
callback. The fork-added `set/highlighted_clip_slot` also answers on the
`"request"` path rather than failing silently — it is a selection write, not a
steer — but it gets there by *validating* its indices and raising, not by
subscripting with them: see "`-1` is an answer, never an argument" under
**Selected-track identity**.

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
| `/live/song/play_selection` | | ⚠️ **Seshat fork addition** — play the current Arrangement selection |
| `/live/song/re_enable_automation` | | Re-enable automation that manual tweaks have overridden (Live's "Re-Enable Automation" button) |
| `/live/song/redo` | | Redo last undone operation |
| `/live/song/scrub_by` | `delta` | ⚠️ **Seshat fork addition** — scrub the playhead by a beat delta. The value is passed to Live unmodified, so send a float |
| `/live/song/set_or_delete_cue` | | Toggle a cue point at the playhead — the same LOM method `/live/song/cue_point/add_or_delete` above calls; two addresses, one behaviour |
| `/live/song/start_playing` | | Start session playback |
| `/live/song/stop_playing` | | Stop session playback |
| `/live/song/stop_all_clips` | | Stop all clips |
| `/live/song/sync_parameter_changes` | | ⚠️ **Seshat fork addition** — `Song.sync_parameter_changes()`, exposed because the LOM has it. ⚠️ **What it does is unknown**: it is Remote-Script-only, absent from Max for Live's table, and Live's own docstring is the signature and nothing else. Registered as a plain fire-and-forget method; do not build behaviour on it until it has been measured |
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
| `/live/song/get/can_capture_midi` | `can_capture_midi` | ⚠️ **Seshat extension** — is there material to capture on any track? The read behind Live's Capture MIDI button. Observable |
| `/live/song/get/can_redo` | `can_redo` | Redo available? Plain `bool` attribute — see the measured semantics below |
| `/live/song/get/can_undo` | `can_undo` | Undo available? Plain `bool` attribute — see the measured semantics below |
| `/live/song/get/clip_trigger_quantization` | `clip_trigger_quantization` | Clip trigger quantization level |
| `/live/song/get/count_in_duration` | `count_in_duration` | ⚠️ **Seshat extension** — the count-in preference, as an **index** into Live's count-in table, not a bar count. Observable. ⚠️ The mapping is unmeasured — assumed `0` = None, `1` = 1 Bar, `2` = 2 Bars, `3` = 4 Bars (Max for Live's documentation; Live 12.4.3's own Push 2 script indexes a `COUNT_IN_DURATION_IN_BARS` table with this value) |
| `/live/song/get/current_song_time` | `current_song_time` | Current song time (beats) |
| `/live/song/get/exclusive_arm` | `exclusive_arm` | ⚠️ **Seshat extension** — the Exclusive Arm preference — arming one track disarms the others. Observable |
| `/live/song/get/exclusive_solo` | `exclusive_solo` | ⚠️ **Seshat extension** — the Exclusive Solo preference. **Not** observable — no listen pair exists (see the note below the table) |
| `/live/song/get/file_path` | `file_path` | ⚠️ **Seshat extension** — the open Live Set's path on disk. **Not** observable. **Measured 2026-08-30, Live 12.4.5:** a never-saved set answers the **empty string**, not `RuntimeError` — read through `/live/application/dump_lom_instances`, whose `provenance.song_file_path` was `""` against an unsaved set. The assumption recorded here was correct; it is now a measurement. One sample, one Live version |
| `/live/song/get/groove_amount` | `groove_amount` | Groove Pool amount (0.0-1.3; 1.0 = the dial's 100%, 1.3 = its 130% maximum); scales how strongly each clip's *assigned* groove applies — no effect on clips without one. Assign one with `/live/clip/set/groove` |
| `/live/song/get/groove_pool` | `name, quantization_amount, timing_amount, random_amount, velocity_amount, ...` | ⚠️ **Seshat extension** — the whole Groove Pool, flattened with **no count prefix**: five fields per groove, in pool order, in the canonical order given in the **Groove API** section (`base` is excluded — read it per groove). An empty pool replies with **no arguments at all**, which is an answer, not an error. Each groove is then addressable by its position in this reply under `/live/groove/*`. Observable — but what the listen pair actually subscribes is `GroovePool.grooves`, so it pushes the full dump on **membership** changes (a groove added, removed or reordered) and **not** when an amount or a name is edited; subscribe `/live/groove/start_listen/<property>` per groove for that |
| `/live/song/get/is_ableton_link_enabled` | `is_ableton_link_enabled` | Ableton Link on? (1=on, 0=off) |
| `/live/song/get/is_ableton_link_start_stop_sync_enabled` | `is_ableton_link_start_stop_sync_enabled` | ⚠️ **Seshat extension** — Link Start/Stop Sync. A separate switch from `is_ableton_link_enabled`, which is Link itself. Observable |
| `/live/song/get/is_counting_in` | `is_counting_in` | ⚠️ **Seshat extension** — true while the count-in runs. Observable, so this is the honest "wait for recording to actually start" subscription |
| `/live/song/get/is_playing` | `is_playing` | Song playing? |
| `/live/song/get/last_event_time` | `last_event_time` | ⚠️ **Seshat extension** — beat time of the last event in the Set. **Not** observable |
| `/live/song/get/loop` | `loop` | Looping? |
| `/live/song/get/loop_length` | `loop_length` | Loop length |
| `/live/song/get/loop_start` | `loop_start` | Loop start point |
| `/live/song/get/metronome` | `metronome_on` | Metronome on/off |
| `/live/song/get/midi_recording_quantization` | `midi_recording_quantization` | MIDI recording quantization |
| `/live/song/get/nudge_down` | `nudge_down` | Nudge down |
| `/live/song/get/nudge_up` | `nudge_up` | Nudge up |
| `/live/song/get/num_visible_tracks` | `num_visible_tracks` | ⚠️ **Seshat extension** — how many regular tracks are visible — Live's own `len(visible_tracks)`, the `num_tracks` companion. No listen pair; subscribe to `visible_tracks` instead. Normally equal to the number of indices `get/visible_tracks` replies, and a disagreement means a track could not be matched to an index rather than a short answer |
| `/live/song/get/overdub` | `overdub` | ⚠️ **Seshat extension** — Live 8's legacy overdub hook. Observable. ⚠️ Live's docstring is truncated ("Now hooks to…") — assumed to mirror session-record state, unmeasured; read `session_record` when you mean session record |
| `/live/song/get/punch_in` | `punch_in` | Punch in |
| `/live/song/get/punch_out` | `punch_out` | Punch out |
| `/live/song/get/re_enable_automation_enabled` | `re_enable_automation_enabled` | ⚠️ **Seshat extension** — true when some automated parameter has been overridden — i.e. when Live's Re-Enable Automation button is lit and `/live/song/re_enable_automation` would do something. Observable |
| `/live/song/get/record_mode` | `record_mode` | Record mode |
| `/live/song/get/root_note` | `root_note` | Root note |
| `/live/song/get/scale_intervals` | `interval, ...` | ⚠️ **Seshat extension** — the current scale's intervals in halfsteps from the root, flattened into one reply with **no count prefix** (Major → `0 2 4 5 7 9 11`), like `/live/application/get/unavailable_features`. Each element is coerced with `int()`. Observable — the listen pair pushes the same flattened tuple |
| `/live/song/get/scale_mode` | `scale_mode` | ⚠️ **Seshat extension** — Live's Scale Mode setting (scale highlighting in the MIDI note editor, scale-degree editing in MIDI tools). Pairs with the existing `root_note` / `scale_name`. Observable |
| `/live/song/get/scale_name` | `scale_name` | Scale name |
| `/live/song/get/select_on_launch` | `select_on_launch` | ⚠️ **Seshat extension** — the "Select on Launch" preference — should firing a clip or scene select it? **Not** observable |
| `/live/song/get/session_automation_record` | `session_automation_record` | ⚠️ **Seshat extension** — is automation recording armed (Live's Automation Arm button)? Observable |
| `/live/song/get/session_record` | `session_record` | Session record enabled? |
| `/live/song/get/session_record_status` | `session_record_status` | Session record status |
| `/live/song/get/signature_denominator` | `denominator` | Time signature denominator |
| `/live/song/get/signature_numerator` | `numerator` | Time signature numerator |
| `/live/song/get/song_length` | `song_length` | Arrangement length (beats) |
| `/live/song/get/start_time` | `start_time` | ⚠️ **Seshat extension** — the Set's start time in beats. Observable |
| `/live/song/get/swing_amount` | `swing_amount` | Global swing amount (0.0-1.0); applied by MIDI record quantization and `/live/clip/quantize` |
| `/live/song/get/tempo` | `tempo_bpm` | Song tempo |
| `/live/song/get/tempo_follower_enabled` | `tempo_follower_enabled` | ⚠️ **Seshat extension** — is the Tempo Follower driving the tempo? Observable. Live's docstring notes the property has no effect unless the Tempo Follower toggle is made visible in preferences |
| `/live/song/get/visible_tracks` | `track_index, ...` | ⚠️ **Seshat extension** — the **indices into `song.tracks`** of every visible regular track, in track order, flattened with no count prefix — the tracks not hidden inside a collapsed group. Same index space as `num_tracks`, `track_names` and every `/live/track/*` address. An empty reply means nothing is visible. Observable — the listen pair pushes the same index tuple, so a group folding or unfolding arrives as one push |

**Four Song getters have no listen pair at all.** `exclusive_solo`,
`file_path`, `last_event_time` and `select_on_launch` are read-only *and*
non-observable: Live offers no `add_<name>_listener` for them, so
`/live/song/start_listen/file_path` and its three siblings are **not
registered**. A send to one is an unknown address — dropped with a log line,
**no `/live/error` comes back**, so don't wait on a reply there. This is the
same shape as `/live/application/get/current_dialog_message`, and the reason is
the same: a registered listen address that can only answer `AttributeError`
would be worse than no address. `num_visible_tracks` has no listen pair either,
for a different reason — it is a count derived from `visible_tracks`, which is
observable; subscribe to that.

### Song Setters

| Address | Query Params | Description |
|---|---|---|
| `/live/song/set/appointed_device` | `category, track_index, device_index` | ⚠️ **Seshat extension** — appoint a top-level device, by the same triple the getter replies. Every argument is validated: `"none"`, an unknown category, a negative or out-of-range index, or a master index other than `0` each answer on `/live/error` and change nothing. There is no un-appoint. Only `"track"` has been exercised against a running Live; whether Live accepts a return-track or master device as `appointed_device` is unmeasured |
| `/live/song/set/arrangement_overdub` | `arrangement_overdub` | Set arrangement overdub (1=on, 0=off) |
| `/live/song/set/back_to_arranger` | `back_to_arranger` | Set back to arranger (1=on, 0=off) |
| `/live/song/set/clip_trigger_quantization` | `clip_trigger_quantization` | Set clip trigger quantization |
| `/live/song/set/current_song_time` | `current_song_time` | Set song time (beats) |
| `/live/song/set/groove_amount` | `groove_amount` | Set Groove Pool amount (0.0-1.3); 0 = assigned grooves off. It scales *assigned* grooves only — assign one with `/live/clip/set/groove` |
| `/live/song/set/is_ableton_link_enabled` | `is_ableton_link_enabled` | Enable/disable Ableton Link (1=on, 0=off) |
| `/live/song/set/is_ableton_link_start_stop_sync_enabled` | `enabled` | ⚠️ **Seshat extension** — enable/disable Link Start/Stop Sync (1=on, 0=off). Distinct from `is_ableton_link_enabled` |
| `/live/song/set/loop` | `loop` | Set looping (1=on, 0=off) |
| `/live/song/set/loop_length` | `loop_length` | Set loop length |
| `/live/song/set/loop_start` | `loop_start` | Set loop start |
| `/live/song/set/metronome` | `metronome_on` | Set metronome (1=on, 0=off) |
| `/live/song/set/midi_recording_quantization` | `midi_recording_quantization` | Set MIDI recording quantization |
| `/live/song/set/nudge_down` | `nudge_down` | Set nudge down |
| `/live/song/set/nudge_up` | `nudge_up` | Set nudge up |
| `/live/song/set/overdub` | `overdub` | ⚠️ **Seshat extension** — set the legacy overdub hook. ⚠️ Its relationship to `session_record` is unmeasured — see the getter row |
| `/live/song/set/punch_in` | `punch_in` | Set punch in |
| `/live/song/set/punch_out` | `punch_out` | Set punch out |
| `/live/song/set/record_mode` | `record_mode` | Set record mode |
| `/live/song/set/root_note` | `root_note` | Set the song's root note (int; pairs with the documented getter) |
| `/live/song/set/scale_mode` | `scale_mode` | ⚠️ **Seshat extension** — turn Live's Scale Mode on/off (1=on, 0=off) |
| `/live/song/set/scale_name` | `scale_name` | Set the song's scale by name (string; pairs with the documented getter) |
| `/live/song/set/session_automation_record` | `session_automation_record` | ⚠️ **Seshat extension** — arm/disarm automation recording (1=on, 0=off) |
| `/live/song/set/session_record` | `session_record` | Set session record (1=on, 0=off) |
| `/live/song/set/signature_denominator` | `signature_denominator` | Set time sig denominator |
| `/live/song/set/signature_numerator` | `signature_numerator` | Set time sig numerator |
| `/live/song/set/start_time` | `start_time` | ⚠️ **Seshat extension** — set the Set's start time in beats. ⚠️ Live's docstring describes a quantization applied to the value on set and is truncated mid-sentence; the value is passed through unmodified, so read back after setting |
| `/live/song/set/swing_amount` | `swing_amount` | Set global swing amount (0.0-1.0) |
| `/live/song/set/tempo` | `tempo_bpm` | Set tempo |
| `/live/song/set/tempo_follower_enabled` | `enabled` | ⚠️ **Seshat extension** — hand the tempo to the Tempo Follower (1=on, 0=off). No effect unless the Tempo Follower toggle is visible in Live's preferences |

### Song: method queries (Seshat — not in upstream AbletonOSC)

Five `Song` methods that **return a value**. The generic `/live/song/<method>`
path discards return values, so each of these is a hand-written handler with a
reply, and the address is the LOM method name **verbatim** — `get_beats_loop_start`,
not `get/beats_loop_start`. None of them exists in stock AbletonOSC.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/song/get_beats_loop_start` | | `bars, beats, sub_division, ticks` | The loop brace's start, as a `BeatTime` decoded into four ints |
| `/live/song/get_beats_loop_length` | | `bars, beats, sub_division, ticks` | The loop brace's length, same shape |
| `/live/song/get_current_smpte_song_time` | `format` | `format, hours, minutes, seconds, frames` | The playhead as SMPTE. `format` is a `Live.Song.TimeFormat` int handed to Live **unmodified** and echoed back first so a burst of requests can be correlated. Sending no argument is a structured `/live/error`, not a default |
| `/live/song/move_device` | `device_category, device_track_index, device_index, target_category, target_track_index, position` | `target_category, target_track_index, result` | Move a device to `position` in another track's device chain |
| `/live/song/find_device_position` | (same six) | `target_category, target_track_index, result` | Where the same move would land the device |

**The two device-position methods take objects, so they take identities.** The
device arrives as the `(category, track_index, device_index)` triple every
object-valued read already replies, and the target as the
`(category, index)` track identity — `category` is `"track"`,
`"return_track"` or `"master"` (see **Object-valued reads**). The five identity
arguments — both categories, both track indices and `device_index` — are
*validated* rather than used as a subscript: `"none"` (reply-only), an unknown
category, a negative or out-of-range index, or a master index other than `0`
each answer on `/live/error` and call nothing. `-1` is an answer, never an
argument, for any of the five. `position`, the sixth argument, is not
validated — it is `int()`-coerced and passed straight to Live, so an
out-of-range value is Live's behaviour to define, not this handler's.

**Track-level targets only.** A device inside a rack chain has no address in
this fork (roadmap A-1), so neither the device argument nor the target can name
one — exactly as `/live/song/set/appointed_device` reaches top-level devices
only. The reply echoes the target identity before Live's return value so
several of these can be in flight at once.

> **Partially measured against Live 12.4.5 on 2026-08-29.** The `Song`
> remainder shipped without a measurement pass and one has since run.
> What it settled:
>
> - ✅ **The `SmpteTime` attribute names are right.**
>   `/live/song/get_current_smpte_song_time` answers a well-formed
>   `format, hours, minutes, seconds, frames` for `format` 0 through 4 with no
>   `AttributeError`, so the four SMPTE field names this fork reads exist under
>   those names. Wrong names fail loudly, which is what makes the silence
>   meaningful. The *values* were all zero (a stopped playhead at song time 0),
>   so the mapping from `Live.Song.TimeFormat` ints to frame rates is still
>   unmeasured — the ints are accepted and echoed, nothing more.
> - ✅ **Every scalar in this section answers**, including
>   `count_in_duration`, the scale members, the Link switches, the tempo
>   follower and the automation flags — no member name in the table is wrong.
>
> Still unmeasured and still ⚠️ in their rows: the `count_in_duration` index
> mapping (the preference read `0` throughout, so only "None" was observed),
> the `Live.Song.TimeFormat` int mapping as above, `overdub`'s relationship to
> `session_record`, and what `sync_parameter_changes` does at all.
>
> **`move_device` / `find_device_position` remain entirely unmeasured**, and
> deliberately so: exercising them needs a track carrying a device, and the
> set used for the run had none. Both what the returned int means and whether
> `find` is genuinely non-mutating are still open, and `find` should be
> treated as potentially mutating until someone checks. The reply *shapes* are
> pinned by `tests_unit/test_song_remainder.py` and depend on none of it. The
> measurement procedure is § "Measuring the Live API without building the
> feature first" above.

### Song: Track/Scene/Cue Queries

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/song/get/cue_points` | | `name, time, ...` | List cue points |
| `/live/song/get/num_scenes` | | `num_scenes` | Number of scenes |
| `/live/song/get/num_tracks` | | `num_tracks` | Number of regular tracks (excludes return and master tracks); see also `/live/song/get/num_visible_tracks` in § Song Getters |
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
| `/live/view/focus_view` | `view_name` | | ⚠️ **Seshat extension** — give a pane keyboard focus. Distinct from `show_view`, which only makes it visible. Live's menu-command validation reads focus: measured 2026-08-30, Create → Convert Melody to New MIDI Track stayed disabled after `show_view("Session")` with a verified audio clip selected over OSC, and enabled only after the Session grid was clicked. Same names as `show_view`. No reply |
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
| `/live/view/get/focused_document_view` | | `"ok", view_name` or `"error", message` | ⚠️ **Seshat extension** — which document view has focus. `view_name` is `Session` or `Arranger`, the only two values Live returns. Always replies, so silence means the extension is not installed. ⚠️ **Partial verification only:** it cannot report that the Browser or a Detail pane holds focus — it still answers `Session`. Measured 2026-08-30: `focus_view("Browser")` disabled the Convert commands while this read was unchanged. Use it to prove focus is on the *wrong* document view; never to prove focus is where you need it |
| `/live/view/start_listen/focused_document_view` | | `"ok", view_name` or `"error", message` | ⚠️ **Seshat extension** — listen for document-view focus changes; pushes the same envelope on the `get` address. The only pair in `/live/view` whose subject is `Application.View` rather than `Song.View` |
| `/live/view/stop_listen/focused_document_view` | | | ⚠️ **Seshat extension** — stop listening for document-view focus changes |
| `/live/view/get/highlighted_clip_slot` | | `track_index, scene_index` | ⚠️ **Seshat extension** — the highlighted Session clip slot, as the ordinary (track, scene) coordinate. **No listen pair** — `Song.View.highlighted_clip_slot` is not observable; it and `Track.group_track` are the two object-valued reads that could not have one. Live returns `None` for the Main and Send tracks: that is `-1, -1`, not an error. A slot that resolves to a return track or the master answers `-1, -1` too — no coordinate reaches it. A slot whose owning track resolves but which is absent from that track's `clip_slots` answers `(track_index, -1)`, the same shape `get/selected_device` uses for "the track is known, the second index is not". See **Object-valued reads** |
| `/live/view/set/highlighted_clip_slot` | `track_index, scene_index` | | ⚠️ **Seshat extension** — set the highlighted Session clip slot. **Not** one of this file's silent setters: a rejection comes back as a `"request"` error. Both indices are **validated, not subscripted** — a negative or out-of-range track or scene index is a `ValueError` on `/live/error`, never a Python wrap-around, so the `-1, -1` the getter answers for "nothing highlighted" cannot be sent back to silently highlight the last scene of the last track. Regular tracks only. Expected to be redundant with `set/selected_clip` — Live documents the slot as "defined via the selected track and scene" — and carried as insurance, not as a fix |

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
  *Conventions the address tables don't show*, which is the pattern all ten
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

  The three **legacy** setters are the whole of that hazard. The fork-added
  `set/highlighted_clip_slot` validates instead: a negative or out-of-range
  track or scene index is a `ValueError` on `/live/error`, never a wrap-around.
  New addresses have no upstream-compatibility reason to inherit the legacy
  behaviour, so none of them do — see `set/appointed_device` and `set/groove`.
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
Seshat's return_track extension (see below). A *regular* track's sends live
here; since A-3 a return track has its own sends too, on
`/live/return_track/get|set/send` — Live 12 gives returns a send section of
their own.

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
| `/live/track/<method> *`, `/live/track/delete_clip * <slot>` | Invoked on every regular track. No reply — **except `/live/track/create_audio_clip`**, which always replies, and so sends one reply datagram per regular track (see its row). |
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
| `/live/track/insert_device` | `track_id, device_name[, position]` | ⚠️ Seshat extension. Insert a device by name into the track's chain; `position` (default `-1`) is the `DeviceIndex` argument of `Track.insert_device`. **No reply on success**, like every other `/live/track/<method>` bar `/live/track/create_audio_clip`; a name Live rejects, or a Live older than 12.3 (where the LOM member does not exist), raises inside the callback and comes back as `/live/error ["request", "/live/track/insert_device", ...]`. Callers wanting the new device's index re-read `/live/track/get/devices/name`, or use the return/master forms below, which reply with it. ⚠️ Which `DeviceName` strings Live accepts is **unmeasured** — the LOM signature is known, the name semantics are not |
| `/live/track/stop_all_clips` | `track_id` | Stop all clips on track |
| `/live/track/create_audio_clip` | `track_id, name, position` | ⚠️ Seshat extension. Import an audio file onto the track's **Arrangement** at `position`. `name` is a path *relative to the import root* `~/.seshat/generated`, never an absolute path — see **Handlers that name a file to read**, which is also where the always-reply convention and the two failure channels are spelled out. Replies `track_index, "ok", position, length` on success, or `track_index, "error", message` on any refusal (a name the rule rejects, a malformed argument list, or an exception Live raised inside the call). The discriminator is always field 1; the two replies are deliberately different lengths and the refusal is not padded. A bad `track_id` is `/live/error` instead, not an `"error"` reply. ⚠️ `position` is passed to Live unmodified as a float; **beats in Arrangement time is inferred** from `/live/track/get/arrangement_clips/start_time`'s units, not measured. ⚠️ `length` is `clip.length` read back off the returned `Clip` immediately, and is `-1.0` if it cannot be read; whether the returned `Clip` is readable synchronously is **unmeasured**. The created clip is **not addressable** by any `/live/clip/*` address — find it again with `/live/track/get/arrangement_clips/start_time`. Under `track_id = "*"` this is attempted on **every regular track** — `song.tracks`, MIDI tracks included — and replies once per track; a refused name creates nothing, but a partial fan-out leaves clips already created in place. ⚠️ What Live raises for a non-audio or unreadable file, and for a **MIDI track**, is **unmeasured** — whatever it is, the worker catches it and returns it as this address's `"error"` reply, so a `*` fan-out over a mixed set can answer `"ok"` for some tracks and `"error"` for others |

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
| `/live/track/get/current_monitoring_state` | `track_id` | `track_id, state` | Monitoring state: `0` = In, `1` = Auto, `2` = Off (`Live.Track.Track.monitoring_states`). Measured 2026-08-30: track 0 answered `1`, and Auto is Live's default for a new track; the enum order is Live's own, from Push2 `routing.pyc`'s `_connect_monitoring_state_encoder` |
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
| `/live/track/set/current_monitoring_state` | `track_id, state` | Set monitoring state: `0` = In, `1` = Auto, `2` = Off (`Live.Track.Track.monitoring_states`) — *not* a boolean |
| `/live/track/set/fold_state` | `track_id, fold_state` | Set group fold (1=on, 0=off) |
| `/live/track/set/input_routing_channel` | `track_id, channel` | Set input routing channel. A name not present in the track's `/live/track/get/available_input_routing_channels` list is **silently ignored** — no reply, no `/live/error`, no change to the routing, indistinguishable from a dropped datagram or an unloaded extension. Validate against the available list before sending, or read the value back afterwards; there is no other way to notice the set failed. |
| `/live/track/set/input_routing_type` | `track_id, type` | Set input routing type. A name not present in the track's `/live/track/get/available_input_routing_types` list is **silently ignored** — no reply, no `/live/error`, no change to the routing, indistinguishable from a dropped datagram or an unloaded extension. Validate against the available list before sending, or read the value back afterwards; there is no other way to notice the set failed. |
| `/live/track/set/mute` | `track_id, mute` | Set mute (1=on, 0=off) |
| `/live/track/set/name` | `track_id, name` | Set track name |
| `/live/track/set/output_routing_channel` | `track_id, channel` | Set output routing channel. A name not present in the track's `/live/track/get/available_output_routing_channels` list is **silently ignored** — no reply, no `/live/error`, no change to the routing, indistinguishable from a dropped datagram or an unloaded extension. Validate against the available list before sending, or read the value back afterwards; there is no other way to notice the set failed. |
| `/live/track/set/output_routing_type` | `track_id, type` | Set output routing type. A name not present in the track's `/live/track/get/available_output_routing_types` list is **silently ignored** — no reply, no `/live/error`, no change to the routing, indistinguishable from a dropped datagram or an unloaded extension. Validate against the available list before sending, or read the value back afterwards; there is no other way to notice the set failed. |
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
| `/live/clip_slot/create_audio_clip` | `track_index, clip_index, name` | `track_index, clip_index, "ok", length` or `track_index, clip_index, "error", message` | ⚠️ **Seshat extension.** Import an audio file into this Session slot as an audio clip. `name` is a path *relative to the import root* `~/.seshat/generated`, never an absolute path — see **Handlers that name a file to read** for the rule, the always-reply convention and the two failure channels. Refusals (all with `"error"`, and none of which calls a Live *method* — the occupancy check does read `ClipSlot.has_clip`): the name fails the rule; `has_clip` raises before occupancy can be determined (the message carries the exception text); the slot already holds a clip (the fork's own check, on `has_clip`); Live raised inside `create_audio_clip`, whose message is carried through. The discriminator is always field 2. A bad `track_index`/`clip_index` is `/live/error` instead, not an `"error"` reply. ⚠️ `length` is `clip.length` in beats read back immediately, `-1.0` if it cannot be read; whether the returned `Clip` is readable synchronously, and what Live raises for a non-audio file or a MIDI track's slot, are **unmeasured**. Read back with `/live/clip/get/file_path` and `/live/clip/get/is_audio_clip`. **No listen pair** — a method, not a property |

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
| `/live/clip/remove_notes_by_id` | `track_id, clip_id, note_id, ...` | | Remove notes by Live note id. Ids come from `/live/clip/get/notes_extended` (or `get_notes_by_id` / `get/selected_notes_extended`) — see § "Extended notes (note ids)" below |
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
| `/live/clip/get/has_envelopes` | `track_id, clip_id` | `track_id, clip_id, has_envelopes` | ⚠️ **Seshat extension** — does this clip carry **any** envelope? (0=False, 1=True). The only way a client can see envelope data at all: no address authors envelopes, so importing a file through `/live/browser/load_item` is the only route by which expression data reaches a clip — and notes read back through `/live/clip/get/notes_extended` carry no expression field, so without this the difference between an import that carried pitch bend and one that carried only notes is invisible on the wire. **It says nothing more than "something is there"**: not which parameter owns the envelope, and not its values. Reading or writing contents would need `automation_envelope` / `create_automation_envelope`, which are in the LOM and unexposed (`FORK_GAPS.md`). Both are keyed by a `DeviceParameter`, i.e. device automation; whether any spelling of them reaches a MIDI clip's pitch-bend or CC lanes is **unmeasured** |
| `/live/clip/start_listen/has_envelopes` | `track_id, clip_id` | | ⚠️ **Seshat extension** — pushes on `/live/clip/get/has_envelopes`. Live's contract is that it notifies when the clip gains its first envelope or loses its last, not on every envelope edit |
| `/live/clip/stop_listen/has_envelopes` | `track_id, clip_id` | | ⚠️ **Seshat extension** — stop listening |
| `/live/clip/get/has_groove` | `track_id, clip_id` | `track_id, clip_id, has_groove` | Has groove? (0=False, 1=True). This is the flag `/live/clip/get/groove` is gated on — a clip whose `has_groove` is `0` reads `-1` there |
| `/live/clip/get/groove` | `track_id, clip_id` | `track_id, clip_id, groove_index` | ⚠️ **Seshat extension** — which Groove Pool groove is assigned to this clip, as its **index into `/live/song/get/groove_pool`**. Answers **`-1` when `Clip.has_groove` is false**, without consulting `Clip.groove` at all — that member always holds an object even for an ungrooved clip, so an `==` scan alone could not tell "no groove" from "pool index `0`". `-1` also if the groove is somehow not a pool member. ⚠️ **Unverified**: that `has_groove` is false for a clip Live's UI shows as ungrooved is Live's documented contract ("Returns true if a groove is associated with this clip", LOM, since Live 11.0), assumed rather than measured by this fork — see the **Groove API** and `FORK_GAPS.md`. See also **Object-valued reads** |
| `/live/clip/set/groove` | `track_id, clip_id, groove_index` | | ⚠️ **Seshat extension** — assign the groove at `groove_index` in the pool. **`groove_index` must be `>= 0`.** ⚠️ **`-1` is rejected, not a clear**: it answers a structured `/live/error` whose detail carries `cannot be cleared`, and the clip is untouched. **Assignment is one-way** — Live's setter is typed `None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)` and refuses `NoneType` (measured against Live 12.4.5 on 2026-08-29), and no other spelling for "no groove" is documented in the LOM, so a groove can only be un-assigned in Live's own Clip Groove chooser. `-2` and below, and an index past the end of the pool, answer on `/live/error` naming the pool's real size (`out of range`) and change nothing. See **Object-valued reads** and the **Groove API** |
| `/live/clip/start_listen/groove` | `track_id, clip_id` | | ⚠️ **Seshat extension** — `Clip.groove` is observable; pushes arrive on `/live/clip/get/groove` as `track_id, clip_id, groove_index`, produced by the same `has_groove` gate as the getter, so a push and a read of the same clip can never disagree (`-1` included). ⚠️ Whether a push fires when the *pool* renumbers (a groove removed above the assigned one changes the index but not the object) is unmeasured — `get/groove` stays correct either way, so treat the getter, not the push, as the source of truth. Unlike every other clip listener, the push value is re-resolved from `(track_id, clip_id)` at push time rather than from the originally-subscribed clip: if *track or clip* indices renumber between subscribe and push, the push reports the groove of whatever clip now sits at that identity, not the clip that was subscribed |
| `/live/clip/stop_listen/groove` | `track_id, clip_id` | | ⚠️ **Seshat extension** — stop listening |
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

### Extended notes (note ids)

**Seshat extension, added 2026-08-29** (SESHAT.md). `/live/clip/get/notes`
describes a note as five fields; Live describes it as nine. These addresses
carry the whole set — including the `note_id` Live assigns, which is what makes
the id-keyed half of Live's note API (`remove_notes_by_id`,
`apply_note_modifications`, `duplicate_notes_by_id`, `select_notes_by_id`)
usable from a client at all. **The five-field addresses are unchanged**: nothing
already written against `get/notes` / `add/notes` has to move, and a regression
test (`tests_unit/test_clip_notes.py`) pins their reply shape.

**The canonical group, in this order:**

    pitch, start_time, duration, velocity, mute, probability, velocity_deviation, release_velocity, note_id

The first five are exactly the order the old addresses use, so a client upgrades
by widening its stride rather than by re-reading the fields. `note_id` is last,
and the *add* form is the same group truncated to eight — Live assigns the id,
so it is never sent.

**Types.** `pitch` and `note_id` are ints; `start_time`, `duration`, `velocity`,
`probability`, `velocity_deviation` and `release_velocity` are floats; `mute`
goes **out** as an OSC boolean (`T`/`F`) and is accepted **in** as `0`/`1` — the
same request/reply asymmetry the old addresses have (§ "Note windows match by
start"). Requests are coerced field by field on the way in, so a client that
sends every number as a float (TouchOSC) needs no conversion of its own; a reply
still cannot be re-sent verbatim, because of `mute`.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/clip/get/notes_extended` | `track_id, clip_id, [start_pitch, pitch_span, start_time, time_span]` | `track_id, clip_id, <9 fields per note>, ...` | The extended read. Range args are all-or-nothing (0 or 4, as for `get/notes`); no args means the whole clip (`0, 127, -8192, 16384`). Notes are matched by their *start* time, as for `get/notes` |
| `/live/clip/add/notes_extended` | `track_id, clip_id, <8 fields per note>, ...` | | Add notes with probability, velocity deviation and release velocity. Argument count must be a non-zero multiple of 8. **No reply, ever** — read the new ids back with `get/notes_extended` |
| `/live/clip/get/selected_notes_extended` | `track_id, clip_id` | `track_id, clip_id, <9 fields per note>, ...` | The notes selected in the clip's editor. Empty selection replies just the two indices |
| `/live/clip/get/selected_notes` | `track_id, clip_id` | `track_id, clip_id, <5 fields per note>, ...` | The same selection, flattened to the old five fields |
| `/live/clip/get_notes_by_id` | `track_id, clip_id, note_id, ...` | `track_id, clip_id, <9 fields per note>, ...` | Fetch specific notes. At least one id required |
| `/live/clip/apply_note_modifications` | `track_id, clip_id, <9 fields per note>, ...` | | **Edit notes in place, keeping their ids.** Count must be a non-zero multiple of 9. The handler fetches the cited ids, checks that Live returned every one of them *before* mutating anything, sets the eight value fields and applies. An id the clip does not hold is a `/live/error` naming it, with nothing applied. Two groups citing the same id is not an error: the later group wins |
| `/live/clip/duplicate_notes_by_id` | `track_id, clip_id, destination_time, transposition_amount, note_id, ...` | `track_id, clip_id, new_note_id, ...` | Duplicate notes. `destination_time` **negative means "in place"** (Live's `None` default; `-1` is the documented spelling). `transposition_amount` is in semitones, `0` for none. At least one id required |
| `/live/clip/select_notes_by_id` | `track_id, clip_id, note_id, ...` | | Select notes in the clip editor |
| `/live/clip/select_all_notes` | `track_id, clip_id` | | Select every note in the clip |
| `/live/clip/deselect_all_notes` | `track_id, clip_id` | | Clear the note selection |
| `/live/clip/replace_selected_notes` | `track_id, clip_id, <5 fields per note>, ...` | | ⚠️ **Deprecated in Live**, exposed for parity. Count must be a non-zero multiple of 5 |
| `/live/clip/set_notes` | `track_id, clip_id, <5 fields per note>, ...` | | ⚠️ **Deprecated in Live**, exposed for parity. Prefer `add/notes` / `add/notes_extended` |

Every mutator is silent on success, per the fork norm; the getters always reply,
answering the two indices and nothing else when there are no notes to report. A
malformed argument count, a bad track/clip index, or a notes call against an
audio clip all arrive as the structured
`/live/error ["request", <address>, <message>, <argc>, *args]` envelope.

**Duplicating to a negative beat is unreachable.** Because OSC has no null,
`destination_time < 0` is the sentinel for Live's `None`, so `-1` and `-0.5`
both mean "duplicate in place". Notes *can* start before beat 0 in Live, but
duplicating *to* such a position is not expressible through this address.

**Large note ids go out int64-tagged.** The vendored pythonosc builder tags a
Python int as int32 only inside the *signed* int32 window `[-2^31, 2^31)`;
anything outside it, in either direction, goes out int64-tagged (`h`), which a
client's decoder must tolerate. That window is the fix for a real drop: the
builder used to test `bit_length() > 32`, which ignores the sign bit, so an id
in `[2^31, 2^32)` was tagged int32, failed `struct.pack(">i", …)`, and took the
whole datagram with it — `OSCServer.send` catches the `BuildError` and only
logs. Live's ids are small monotonic integers in practice, so this window is
unlikely to be reached; it is now encodable rather than silently fatal
(`tests_unit/test_int_encoding.py`).

**Unmeasured, and marked ⚠️ until a Live verification session runs**
(the checks are written out in the plan doc archived with this item):

- ✅ **Confirmed (measured against Live 12.4.5, 2026-08-29).** `Live.Clip.MidiNoteSpecification` **does** accept
  `probability`, `velocity_deviation` and `release_velocity` as constructor
  keywords: `/live/clip/add/notes_extended` with all eight fields builds and
  applies the note with no error, on a MIDI clip created for the check. A
  seven-field call is still rejected with the structured envelope, so the
  arity guard holds. This was the largest assumption in this section; the
  reply *values* were not read back (replies go to a port this fork cannot
  bind locally — see the Application section's measurement note), so what is
  pinned is that Live accepts the construction, not that each field
  round-trips.
- ⚠️ Whether a fetched `MidiNote`'s attributes are writable from Remote Script
  Python — what `apply_note_modifications` depends on. Assumed yes: Push's own
  note editor fetches, mutates and applies.
- ⚠️ Whether a `MidiNote` exposes `probability`, `velocity_deviation`,
  `release_velocity` and `note_id` under those names at all — four of the
  twelve addresses read them by attribute name (`abletonosc/clip.py`'s
  `EXTENDED_NOTE_FIELDS`), and that assumption is separate from the two above:
  even if the attributes are writable, a rename or absence here would drop or
  misname a field rather than raise.
- ⚠️ What `get_notes_by_id` does with an id the clip does not hold (raise, or a
  shorter vector), and whether its reply follows request order. The modify path
  is deterministic either way, because the handler checks the ids itself.
- ⚠️ What the deprecated `set_notes` and `replace_selected_notes` actually do —
  Live's docstrings carry no description, and the pre-Live-11 "set notes"
  *added* notes rather than replacing them.
- ⚠️ Whether the selection members need the clip open in Live's detail view.
- ⚠️ What `add_new_notes` returns. `add/notes_extended` is silent by design; if
  Live turns out to return the new notes, giving it a reply is a follow-up
  item, not a change to this contract.

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
- What the *five-field* round trip cannot preserve: `probability`,
  `velocity_deviation`, `release_velocity` — `get/notes` does not carry them,
  so notes re-added through `add/notes` get Live's defaults. Since 2026-08-29
  the fork answers all three (and the note id) on
  `/live/clip/get/notes_extended`, and takes them on
  `/live/clip/add/notes_extended`; editing a note **without** disturbing them
  at all is `/live/clip/apply_note_modifications`, which keeps the note's id.
  See § "Extended notes (note ids)".

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

### Conversions — audio to MIDI, Simpler and Drum Rack

⚠️ **Seshat extension.** None of these exists in stock AbletonOSC. They wrap
`Live.Conversions`, a Boost.Python module of module-level free functions —
Live's *Create → Convert Harmony/Melody/Drums to New MIDI Track*, *Slice to New
MIDI Track*, and the Simpler/Drum Rack conversions. It was invisible to this
fork's own gap inventory until the LOM walker was taught to record
module-level members; see `BLIND_SPOTS.md`.

| Address | Params | Response | Description |
|---|---|---|---|
| `/live/clip/get/is_convertible_to_midi` | `track_id, clip_id` | `track_id, clip_id, convertible` | Whether the clip can be converted to MIDI. **Always answers**; see the divergence below |
| `/live/clip/audio_to_midi` | `track_id, clip_id, type` | `track_id, clip_id, "ok", new_track_id` or `track_id, clip_id, "error", message` | Extract notes from an audio clip into a MIDI clip on a **new MIDI track**. `type` is a name: `harmony`, `melody` or `drums` |
| `/live/clip/create_midi_track_with_simpler` | `track_id, clip_id` | `track_id, clip_id, "ok", new_track_id` / `"error", message` | New MIDI track carrying a Simpler loaded with the audio clip |
| `/live/clip/create_drum_rack_from_audio_clip` | `track_id, clip_id` | `track_id, clip_id, "ok", new_track_id` / `"error", message` | New track with a Drum Rack, the audio clip on a Simpler on the first pad |
| `/live/device/sliced_simpler_to_drum_rack` | `track_id, device_id` | `track_id, device_id, "ok", new_track_id` / `"error", message` | Live's *Slice to New MIDI Track*: converts a **sliced** Simpler into a Drum Rack, one slice per pad. Top-level devices on a regular track only, like every other `/live/device/*` address |

**`type` is a name, never the enum integer.** Live's own signature declares
`(int)`, so Live would accept a bare positional value — and Boost.Python enum
values are positional, so a member added in a future Live would silently
reassign them. `harmony_to_midi`, `melody_to_midi` and `drums_to_midi` (Live's
own member names) are accepted too; matching is case-insensitive and
surrounding whitespace is ignored. An unrecognised name, or a missing one, is
refused with the `"error"` envelope and **Live is not called**.

⚠️ **`is_convertible_to_midi` diverges from the LOM member deliberately.**
Live's `Live.Conversions.is_convertible_to_midi` **raises** when handed a MIDI
clip rather than answering false. That makes it useless as the predicate a
client actually wants — "may I offer this conversion?" is asked *before*
mutating, and an exception is not an answer. This fork pre-checks
`Clip.is_audio_clip` and answers `false` for a MIDI clip, for an empty clip
slot, and on a Live with no `Live.Conversions` module, **without calling
Live**. It never raises and always replies.

**`new_track_id` is read back, not returned by Live.** Every one of these
members returns `None`, so the handler records the tracks before the call and
reports the index of the one that appeared. `-1` means the conversion was
accepted but **no new track had appeared by the time the handler returned** —
`-1` is an answer, never an argument, and it is **not** a failure.

⚠️ **`/live/clip/audio_to_midi` is asynchronous and therefore always answers
`-1`.** Measured against Live 12.4.5 on 2026-08-30 by calling it: the reply
came back `"ok", -1`, and the new track — named by Live, e.g.
`3-Melody to MIDI`, carrying a MIDI clip of the extracted notes — appeared
within about three seconds. **A client that treats `-1` as failure, or that
reads back immediately, will report a successful conversion as a failed one.**
The two Simpler/Drum Rack conversions are *not* asynchronous and do return the
index:

| Address | Behaviour | `new_track_id` |
|---|---|---|
| `/live/clip/audio_to_midi` | **asynchronous** | always `-1` |
| `/live/clip/create_midi_track_with_simpler` | synchronous | the new track's index |
| `/live/clip/create_drum_rack_from_audio_clip` | synchronous | the new track's index |
| `/live/device/sliced_simpler_to_drum_rack` | ⚠️ unmeasured | unmeasured |

**The pattern for the asynchronous one** is the fork's existing structure
listener, not polling: subscribe with `/live/song/start_listen/tracks`, fire
`/live/clip/audio_to_midi`, and take the new track from the push. Polling
`/live/song/get/num_tracks` also works and is what a client without a listener
should do; either way the answer is "wait for it", not "it failed".

**Where the new track lands.** `audio_to_midi_clip` inserts it **directly after
the source track**, measured against Live 12.4.5 on 2026-08-30 on a layout that
can tell the two orderings apart: source clip on track 1 of three, with a
marker track at index 2. The converted track took index 2 and pushed the marker
to 3; appending last would have given it index 3.

An earlier note here said all three conversions appended the new track *last*.
That was one observation each on a set whose source clip was on the **last**
track, where "appended last" and "inserted after the source" produce the same
index and cannot be distinguished. `create_midi_track_with_simpler` and
`create_drum_rack_from_audio_clip` have still only been measured on that
degenerate layout, so their ordering is **unknown**, not "last" — do not read
the corrected `audio_to_midi_clip` behaviour onto them either.

Treat the returned index as "which track appeared", never as a promise about
ordering: a client that resolves the converted track by taking the last index
gets the wrong track outright whenever the source is not the last track, and
gets no error to notice it by.

**The converted clip lands in the source's own scene row** — a source in slot 0
produced the MIDI clip in slot 0 of the new track.

**The whole asynchronous conversion undoes as a single step.** One
`/live/song/undo` removed the converted track and nothing else, leaving the
source clip untouched — measured both with the converted track last and with it
inserted mid-list. Because the conversion completes after the address has
replied, a client cannot tell from the wire whether Live grouped the later work
into the caller's undo step; measured, it does, so no second undo is needed.

**Every member takes the Song as its first argument** —
`audio_to_midi_clip( (Song)song, (Clip)audio_clip, (int)audio_to_midi_type)`.
Recorded here because it is not visible in Live's binary and was assumed
otherwise when these addresses were designed; the handlers pass `self.song`.

**On an older Live with no `Live.Conversions`**, the module still imports and
every address still answers: the mutations reply with the `"error"` envelope
naming the missing module, and the getter answers `false`.

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

## Groove API (Seshat extension — not in upstream AbletonOSC)

The Groove Pool: the grooves loaded into the open Set, their four amounts, and
the assignment of one to a clip. Upstream AbletonOSC has none of this — only
`/live/song/get|set/groove_amount`, the master dial that *scales* grooves
already assigned. Without an assignment that dial does nothing at all, which
is the gap this family closes.

Three address families, all keyed on one flat collection,
`song.groove_pool.grooves`:

| What | Address family |
|---|---|
| Enumerate the pool | `/live/song/get/groove_pool` (above, under Song Getters) |
| Read/write one groove | `/live/groove/*` (this section) |
| Assign one to a clip | `/live/clip/get|set/groove` (Clip API) |

**A groove is named by its index in the pool.** The index is positional and
**renumbers when a groove is removed from the pool**, exactly as track, scene
and clip indices renumber — the same caveat, with the same remedy: re-read
`/live/song/get/groove_pool` (or subscribe to it) rather than caching an index
across an edit. Listener bookkeeping survives renumbering the way every
indexed family's does: `_stop_listen` unbinds from the object actually
subscribed, not from whatever the index now names. `/live/groove/stop_listen/*`
therefore resolves nothing — it keys straight off the normalised index — so a
subscription still stops cleanly after the groove it named has been removed
from the pool and the index has fallen out of range. An index that carries no
subscription is silent rather than an error, on that address only; the getters
and setters still answer `/live/error` for an out-of-range index.

**The canonical field order**, shared by the pool dump and this section, is
Live's own Groove Pool column order (`GROOVE_FIELDS` in `abletonosc/groove.py`;
do not reorder without changing this document):

    name, quantization_amount, timing_amount, random_amount, velocity_amount

`base` is deliberately **not** in that tuple. The reasoning was that its wire
type was unverified and the OSC builder drops an entire reply it cannot encode,
so keeping `base` out of the dump means an encoding surprise breaks one address
instead of the whole pool read. That surprise did not materialise: `base` reads
as a plain string (measured against Live 12.4.5, 2026-08-29 — a stock "Swing 16ths 66" groove answers `gb_sixteen`)
and encodes without a `BuildError`. The exclusion is therefore now
conservatism rather than protection, and it is kept because moving a field
into the dump is a wire-contract change, not a documentation one. It has its
own get/set pair below.

**A subscription's identity is one int** — `groove_index` is normalised to an
int at the callback boundary and that int is the pool lookup, the
subscription's key and the value echoed in every push, so pushes carry
`groove_index, value` in exactly the query-reply shape whatever number type the
client sent. Float-sending clients (TouchOSC; upstream issue #33) can start and
stop interchangeably with int-sending ones, non-integral floats truncate toward
zero, and **arguments past the index are not part of the identity and are
ignored**. Sending no index at all is a malformed request and answers on
`/live/error`.

**Every index is validated, never used as a subscript.** A negative index or
one past the end of the pool is a `ValueError` arriving as a structured
`/live/error` that names the pool's real size — never a Python negative-index
wrap-around, which would make `-1` mean "the last groove" (see
**Object-valued reads**).

Listen via `/live/groove/start_listen/<property> <groove_index>`, stop via
`/live/groove/stop_listen/<property> <groove_index>`, and receive pushes on
`/live/groove/get/<property>`.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/groove/get/name` | `groove_index` | `groove_index, name` | The groove's name, as it reads in the Groove Pool. Observable |
| `/live/groove/set/name` | `groove_index, name` | | Rename the groove |
| `/live/groove/get/quantization_amount` | `groove_index` | `groove_index, quantization_amount` | How strongly the groove quantizes toward its grid. Observable. Range is **`0.0`–`100.0`**, matching the UI's 0–100% — *not* a 0–1 fraction (measured against Live 12.4.5, 2026-08-29) |
| `/live/groove/set/quantization_amount` | `groove_index, amount` | | Set it. Passed through **unclamped**: Live is the authority on the range, so read back after setting |
| `/live/groove/get/timing_amount` | `groove_index` | `groove_index, timing_amount` | How strongly the groove's timing offsets apply. Observable. Range is **`0.0`–`100.0`**, matching the UI (measured against Live 12.4.5, 2026-08-29: a stock "Swing 16ths 66" groove reads `timing_amount = 100.0`) |
| `/live/groove/set/timing_amount` | `groove_index, amount` | | Set it, unclamped |
| `/live/groove/get/random_amount` | `groove_index` | `groove_index, random_amount` | The groove's randomness. Observable. ⚠️ Range unmeasured — assumed `0.0`–`1.0` |
| `/live/groove/set/random_amount` | `groove_index, amount` | | Set it, unclamped |
| `/live/groove/get/velocity_amount` | `groove_index` | `groove_index, velocity_amount` | How strongly the groove's velocity offsets apply. Observable. ⚠️ Range unmeasured — Live's UI shows this column as −100…100%, so `-1.0`–`1.0` is assumed, **including the sign** |
| `/live/groove/set/velocity_amount` | `groove_index, amount` | | Set it, unclamped |
| `/live/groove/get/base` | `groove_index` | `groove_index, base` | The groove's base grid. ⚠️ **Wire type unverified** — assumed an int-encodable enum like `warp_mode`, and the value↔grid mapping (1/4, 1/8, 1/16, 1/32) is unmeasured. **Not** observable, so there is no listen pair |
| `/live/groove/set/base` | `groove_index, base` | | Set the base grid. ⚠️ Same caveat |

**`base` has no listen pair at all.** It is the one `Live.Groove.Groove` member
Live offers no `add_<name>_listener` for, so `/live/groove/start_listen/base` is
**not registered**: a send to it is an unknown address — dropped with a log
line, **no `/live/error` comes back**. This is the same shape as the four
`/live/song/get/*` reads with no listen pair, for the same reason.

⚠️ **Almost nothing in this section has been exercised against a running
Live.** The handlers are covered Live-free by `tests_unit/test_groove.py`,
which proves the registrations, the reply shapes, the validation and the
listener bookkeeping — not what a real `Live.Groove.Groove` does. The
exceptions are the readings recorded below and in the rows above (`base`,
`timing_amount`, `quantization_amount`). Whether `.agr` groove files can be
loaded into the pool through `/live/browser/load_item` at all is a separate
open question: the LOM has no groove browser root and `packs` is not an exposed
category, so a groove may still have to be dragged in by hand.

### Assignment is one-way

`/live/clip/set/groove` can assign a pool groove to a clip. **It cannot
un-assign one, and no address in this fork can.**

Two separate claims, at two different evidence tiers, hold that up:

- **Measured** (Live 12.4.5, 2026-08-29): `clip.groove = None` raises
  `Boost.Python.ArgumentError`. Live's setter is typed
  `None(TPyHandle<AClip>, TPyHandle<AAbstractGroove>)` and refuses `NoneType`.
- **Searched, not measured**: no spelling for "no groove" exists in any public
  source. Checked against the Cycling '74 LOM reference (`Clip`, `Groove`,
  `GroovePool`), the NSUSpray `Live_API_Doc` generated XML, the Ableton Live 12
  manual and the M4L forum threads on groove assignment. `GroovePool` has
  exactly one member, `grooves` — no add, no remove. `Clip` has no
  `remove_groove`, `clear_groove` or `commit`. `Groove` has `base`, `name` and
  the four amounts and nothing else. The only documented route to Groove = None
  is the UI's **Commit** button, which has no LOM equivalent.

So `/live/clip/set/groove <t> <c> -1` is a **rejected request**, answering
`/live/error` with `cannot be cleared` in the detail, and `-1` is an answer,
never an argument, everywhere in this fork with no exceptions. A client that
reads `-1` from `/live/clip/get/groove` must treat it as "no groove" and must
never replay it.

**This reopens only if a future Live adds a member.** The candidate probe, if
anyone wants to settle it beyond public sources, is the null-handle round trip
— `dst.groove = <an ungrooved clip's groove object>` — through a temporary
handler in the *installed* copy (see **Measuring the Live API without building
the feature first**). If that ever succeeds, the `-1` argument comes back.

### The clip↔groove readings

Measured against Live 12.4.5 on 2026-08-29, on a set with one MIDI track and a
pool holding a single stock groove ("Swing 16ths 66", `timing_amount = 100.0`,
`base` `gb_sixteen`):

| Request | Log line |
|---|---|
| `/live/clip/get/has_groove 0 0` | `Getting property for clip: has_groove = True` |
| `/live/clip/get/groove 0 0` | `Getting property for clip: groove = 0` |
| `/live/clip/start_listen/groove 0 0` | the immediate current-value push, `Property groove changed of clip (0, 0): (0,)` |
| `/live/clip/set/groove 0 0 0` | `Resolving groove pool index 0 of 1`, `Setting property for clip: groove = 0` — **and no subsequent push**, although the listener was still bound |

⚠️ **Read that carefully: it does not confirm the gate.** The clip had been
created one second earlier by `/live/clip_slot/create_clip`, and all three
signals are consistent with it genuinely holding pool groove `0` — under which
reading `has_groove` is honest and the fork's read is now correct. They are
equally consistent with `has_groove` being true for every clip. Separating the
two needs a pool holding **two** grooves and a clip whose Groove chooser reads
None in Live's UI; grooves cannot be added to the pool over this bridge (there
is no `Browser.grooves` root and `GroovePool` has no add), so that measurement
needs a human at Live's UI and has not been made. Until it is, treat
`/live/clip/get/groove`'s `-1` as **assumed reachable, not measured** — the
gate is Live's own documented flag, and is a strict improvement over the `==`
scan under either reading, but this fork has not seen it answer `False`.

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
| `/live/device/replace_sample` | `track_id, device_id, name` | `track_id, device_id, "ok", file_path` or `track_id, device_id, "error", message` | ⚠️ **Seshat extension.** Replace a **Simpler's** sample with a file from the import root. `name` is a path *relative to* `~/.seshat/generated`, never an absolute path — see **Handlers that name a file to read**. The discriminator is always field 2. `file_path` is `device.sample.file_path` read back after the call — the proof the swap landed — and `""` if it cannot be read, which does not change the arity. ⚠️ Whether the read-back reflects the new sample immediately is **unmeasured**. `SimplerDevice` only: on any other device the method binding raises `AttributeError`, which reaches the caller as `/live/error` and is a **silent skip** under an address-pattern request such as `/live/device/*`. Regular tracks and top-level devices only, like every other `/live/device/*` address; a Simpler inside a rack is not reachable |

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
- ⚠️ **A MIDI file loads onto a track Live creates, not the one you named.**
  Measured 2026-08-30 on Live 12.4.5 Suite (build `2026-08-19_225ce5e356`): a
  `.mid` dropped in the User Library appears in the browser immediately, with an
  ordinary URI (`query:UserLibrary#Clips:<name>.mid`), and `load_item` imports
  it — but **the `track_id` argument, the selected track and the selected scene
  are all ignored**. Live appends its own regular MIDI track, named by position
  (`5-MIDI` on a five-track set), and puts the clip there; it does *not* land in
  the selected clip slot. The clip is named after the **MIDI file's own track
  name** (`Track 1`), not the file name, so the reply's `device_name` and the
  clip's name are no guide to which file was loaded. Note timing is preserved
  exactly (a first note at beat `3.4818` reads back `start=3.4818`), as are
  durations and velocities; clip length read `84.0` beats for a file whose last
  note ended at ~`81.7` (one measurement — the rounding rule behind it is not
  established). **Pitch-bend data in the file survives the import as clip
  envelope(s)**, confirmed on screen — read `/live/clip/get/has_envelopes` to see
  that it arrived. Importing a file is currently the only route by which envelope
  data reaches a clip, since no address authors one. A caller that needs the clip
  somewhere specific must find the new track (the set's track count grows by one)
  and move the clip itself.

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

⚠️ These one hundred and nine addresses do **not** exist in stock AbletonOSC.
They are served by `abletonosc/return_track.py` in this repository, installed
with `mix abletonosc.install` (restart Live afterwards). Without that install all
one hundred and nine addresses are unknown and queries time out.

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

### Return Track & Master: `Track` parity

A return track and the master are `Live.Track.Track` objects, the same class as
every regular track — only the `song.tracks` lookup stood between them and most
of the Track API. These addresses (roadmap item **A-3**) close that difference
for the scalar properties, output routing, the returns' own sends and
`insert_device`.

Everything in this subsection follows the envelope rules of the section above,
with one deliberate addition: **every getter here carries the ok/error
envelope, the index-less master forms included** — unlike the shipped
`/live/master/get/{volume,panning,cue_volume,devices}`, which reply with the
bare value. The Main track refuses some members its class declares (reading
`mute` raises `RuntimeError`), so a master getter for a *new* member has a
failure path the fader getters do not, and an envelope is the only shape that
can report it. A read that raises comes back as
`["error", "could not read <prop>: <exception text>"]`, never as silence and
never as a bare `None`.

| Address | Query Params | Response Params | Description |
|---|---|---|---|
| `/live/return_track/get/color` | `return_index` | `return_index, "ok", color` | RGB colour as an int, same encoding as `/live/track/get/color` |
| | | `return_index, "error", message` | Index out of range, or the member was refused |
| `/live/return_track/set/color` | `return_index, color` | | Set the return's colour |
| `/live/return_track/start_listen/color` | `return_index` | | Push `/live/return_track/get/color [return_index, color]` on every change |
| `/live/return_track/stop_listen/color` | `return_index` | | |
| `/live/return_track/get/color_index` | `return_index` | `return_index, "ok", color_index` | Index into Live's colour palette |
| | | `return_index, "error", message` | Index out of range, or the member was refused |
| `/live/return_track/set/color_index` | `return_index, color_index` | | |
| `/live/return_track/start_listen/color_index` | `return_index` | | Push `[return_index, color_index]` |
| `/live/return_track/stop_listen/color_index` | `return_index` | | |
| `/live/return_track/get/has_audio_input` | `return_index` | `return_index, "ok", 0\|1` | Constant on a return; **`1`** (measured against Live 12.4.5, 2026-08-29). No setter, **no listen pair** |
| `/live/return_track/get/has_audio_output` | `return_index` | `return_index, "ok", 0\|1` | Constant; **`1`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/return_track/get/has_midi_input` | `return_index` | `return_index, "ok", 0\|1` | Constant; **`0`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/return_track/get/has_midi_output` | `return_index` | `return_index, "ok", 0\|1` | Constant; **`0`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/return_track/get/output_meter_level` | `return_index` | `return_index, "ok", level` | Output meter, 0.0 to 1.0 |
| `/live/return_track/start_listen/output_meter_level` | `return_index` | | Push `[return_index, level]` on every change — ⚠️ a *high-rate* subscription while audio plays |
| `/live/return_track/stop_listen/output_meter_level` | `return_index` | | |
| `/live/return_track/get/output_meter_left` | `return_index` | `return_index, "ok", level` | Left channel |
| `/live/return_track/start_listen/output_meter_left` | `return_index` | | Push `[return_index, level]` on every change — ⚠️ high-rate |
| `/live/return_track/stop_listen/output_meter_left` | `return_index` | | |
| `/live/return_track/get/output_meter_right` | `return_index` | `return_index, "ok", level` | Right channel |
| `/live/return_track/start_listen/output_meter_right` | `return_index` | | Push `[return_index, level]` on every change — ⚠️ high-rate |
| `/live/return_track/stop_listen/output_meter_right` | `return_index` | | |
| `/live/return_track/get/available_output_routing_types` | `return_index` | `return_index, "ok", count, name × count` | Output routing choices, `count` first |
| | | `return_index, "error", message` | Index out of range, or the read was refused |
| `/live/return_track/get/available_output_routing_channels` | `return_index` | `return_index, "ok", count, name × count` | |
| `/live/return_track/get/output_routing_type` | `return_index` | `return_index, "ok", display_name` | Current output route |
| `/live/return_track/set/output_routing_type` | `return_index, display_name` | | Resolved against `available_output_routing_types` by display name; an unmatched name is logged and changes nothing |
| `/live/return_track/get/output_routing_channel` | `return_index` | `return_index, "ok", display_name` | |
| `/live/return_track/set/output_routing_channel` | `return_index, display_name` | | Resolved against `available_output_routing_channels` |
| `/live/return_track/get/send` | `return_index, send_id` | `return_index, send_id, "ok", value` | One of the return's own sends, 0.0 to 1.0 |
| | | `return_index, send_id, "error", message` | Either index out of range; the message names the real send count |
| `/live/return_track/set/send` | `return_index, send_id, value` | | Set one of the return's sends |
| `/live/return_track/insert_device` | `return_index, device_name[, position]` | `return_index, "ok", device_index, count` | Insert a device by name; `device_index` is its position **re-read** from the chain, `count` the new chain length |
| | | `return_index, "error", message` | Index out of range, no name given, or the LOM call raised |
| `/live/master/get/color` | | `"ok", color` / `"error", message` | The Main track **does** have `color` (measured against Live 12.4.5, 2026-08-29; read back `16749734`) |
| `/live/master/set/color` | `color` | | ⚠️ If the Main track refuses the member the write raises and arrives on `/live/error`, not as silence |
| `/live/master/start_listen/color` | | | Push `/live/master/get/color [color]` on every change |
| `/live/master/stop_listen/color` | | | |
| `/live/master/get/color_index` | | `"ok", color_index` / `"error", message` | Same ⚠️ |
| `/live/master/set/color_index` | `color_index` | | |
| `/live/master/start_listen/color_index` | | | Push `[color_index]` |
| `/live/master/stop_listen/color_index` | | | |
| `/live/master/get/has_audio_input` | | `"ok", 0\|1` / `"error", message` | Constant; **`1`** (measured against Live 12.4.5, 2026-08-29). No setter, no listen pair |
| `/live/master/get/has_audio_output` | | `"ok", 0\|1` / `"error", message` | Constant; **`1`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/master/get/has_midi_input` | | `"ok", 0\|1` / `"error", message` | Constant; **`0`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/master/get/has_midi_output` | | `"ok", 0\|1` / `"error", message` | Constant; **`0`** (measured against Live 12.4.5, 2026-08-29) |
| `/live/master/get/output_meter_level` | | `"ok", level` / `"error", message` | Master output meter |
| `/live/master/start_listen/output_meter_level` | | | Push `[level]` — ⚠️ high-rate |
| `/live/master/stop_listen/output_meter_level` | | | |
| `/live/master/get/output_meter_left` | | `"ok", level` / `"error", message` | |
| `/live/master/start_listen/output_meter_left` | | | Push `[level]` — ⚠️ high-rate |
| `/live/master/stop_listen/output_meter_left` | | | |
| `/live/master/get/output_meter_right` | | `"ok", level` / `"error", message` | |
| `/live/master/start_listen/output_meter_right` | | | Push `[level]` — ⚠️ high-rate |
| `/live/master/stop_listen/output_meter_right` | | | |
| `/live/master/get/available_output_routing_types` | | `"ok", count, name × count` | |
| `/live/master/get/available_output_routing_channels` | | `"ok", count, name × count` | |
| `/live/master/get/output_routing_type` | | `"ok", display_name` / `"error", message` | Usually the hardware output |
| `/live/master/set/output_routing_type` | `display_name` | | |
| `/live/master/get/output_routing_channel` | | `"ok", display_name` / `"error", message` | |
| `/live/master/set/output_routing_channel` | `display_name` | | |
| `/live/master/insert_device` | `device_name[, position]` | `"ok", device_index, count` | Insert a device into the master chain |
| | | `"error", message` | No name given, or the LOM call raised |

- **`has_audio_input` / `has_audio_output` / `has_midi_input` /
  `has_midi_output` have no listen pair here**, unlike on a regular track. On a
  return and on the master they are constants — always audio in, audio out,
  never MIDI — so a subscription could only ever deliver the one immediate
  push. Regular tracks have those pairs because upstream's generic loop
  registers a pair for every property in its list, not because the values move.
- **There is no input routing on returns or the master.** Neither has an input
  section in Live's UI, so `input_routing_*` and `available_input_routing_*`
  are deliberately not offered. The output half is, because both do have an
  output chooser: a return routes to the Main track or elsewhere, the master to
  a hardware output.
- **The available-routing lists carry `count` first**, like `get/devices` —
  the flat tail then stays parseable, and a tail whose length disagrees with
  `count` is a shape error the caller rejects rather than truncating. Setting
  resolves a **display name** against the matching list, exactly as
  `/live/track/set/output_routing_type` does, and inherits that scheme's
  ambiguity: two routings that display the same name are indistinguishable on
  the wire (`FORK_GAPS.md` § "Routing — names, not objects").
- **Meter subscriptions are high-rate.** `output_meter_*` changes on every
  audio buffer while sound is passing, so `start_listen` on one is a stream,
  not an occasional notification. Subscribe deliberately and stop when the
  meter is no longer on screen.
- **Sends on returns are new in the LOM's usable form with Live 12**, which
  gives return tracks their own send section (return-to-return, disabled by
  default behind Live's feedback guard). ⚠️ Unmeasured: whether
  `len(mixer_device.sends)` on a return is the full return count and whether a
  *disabled* send accepts a value write. The error message on a bad `send_id`
  names whatever count Live reports. There is **no master form** (the master
  has no sends) and **no listen pair** — `Track.sends` is not observable, the
  same reason `/live/track/start_listen/send` doesn't exist.
- **`insert_device` replies**, for the same reason `delete_device` does: it is
  a method with a real failure path, and the caller's very next act is
  addressing the device it just created. `device_index` is **re-read** from
  `track.devices` after the call rather than assumed, because Live does not
  always append at the end (an instrument lands before existing audio
  effects); it is `-1` when the returned device is not on the chain yet, which
  is what an asynchronously instantiating VST/AU plugin looks like — the same
  convention `/live/browser/load_item` uses. The regular-track counterpart is
  `/live/track/insert_device`, which stays silent like every other
  `/live/track/<method>` bar `/live/track/create_audio_clip`. ⚠️ Which `DeviceName` strings Live accepts, and what
  a rejected one raises, are **unmeasured**; `position` maps to the LOM's
  `DeviceIndex` argument and defaults to `-1`.
- **Setters keep the section's split.** An argument or bounds error is logged
  in Live and answered with silence, as everywhere else here; the LOM write
  itself is unguarded, so a member the object refuses raises and arrives as a
  structured `/live/error` carrying the request. Silence therefore still means
  "bad index or not installed", and `/live/error` means "Live refused this".
- **Listener keys.** A return's colour and meter listeners are plain `Track`
  properties, keyed `(prop, (return_index,))` through the base class. The
  master's are keyed `(prop, ("master",))` through a hand-rolled helper —
  the base class derives its push address from `class_identifier`, which is
  `return_track` for this handler, so the master's pushes would otherwise go
  out on `/live/return_track/get/color`. Neither can collide with the mixer
  parameters' `("value", (index, "volume"))` / `("value", ("master",
  "cue_volume"))`.

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
- **The five *shipped* index-less getters reply with the bare value**, no
  envelope: `get/count`, `/live/master/get/volume`, `/live/master/get/panning`,
  `/live/master/get/cue_volume` and `/live/master/get/devices` take nothing to
  look up, so they have no failure to report. Every master getter added since
  (the `Track` parity subsection below) **does** carry the envelope: those read
  members the Main track may refuse outright, which is a failure path a fader
  read does not have.
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
- The sends that feed a return belong to the *regular* track, and stay on
  `/live/track/get|set/send [track_id, send_id, ...]` in the Track API above.
  A return's **own** sends (Live 12's return-to-return section) are a separate
  thing and live here, on `/live/return_track/get|set/send`.
- **The listeners push the bare value**, not the ok/error envelope — the one
  documented exception to the general listener rule in § "Listener pattern",
  which is cross-referenced there. A push has
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
