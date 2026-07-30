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

- **`handler.py` / `osc_server.py` — per-message resilience.** Hand-applied from
  upstream PR #208: `_call_method` and `_set_property` log a failure instead of
  raising through the dispatcher, and `process()` moves its try/except inside
  the recvfrom loop so one failing message no longer aborts the rest of that
  tick's queue. Seshat sends ordered multi-message sequences, which is exactly
  the shape that bug truncates.

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
  result is **unverified**; the bridge exposes no address to set it with.

  Seshat's `quantize_clip` never puts these integers in front of the model: it
  takes a string grid (`"1/16"`, `"1/8T"`, …) and maps it in one private
  function, `Seshat.Tools.Handlers.grid_quantization/1`, so a future
  correction is a one-line change. The address **never replies**, so a wrong
  integer is silent everywhere except in Live.

- **`view.py` — `/live/view/show_view` and `/live/view/set/detail_clip`.** The
  first Seshat addresses to live in an upstream file rather than in a handler of
  our own: they belong to the View API by every other measure, and splitting them
  into a fourth module would put two `ViewHandler`s in `manager.py`. Upstream can
  *select* a track, scene, clip or device but cannot bring the pane those live in
  into view — `Application.View.show_view` and `song.view.detail_clip` have no
  OSC address at all. Seshat's view steering (every mutating tool ends by showing
  what it changed) needs both: selecting a clip nobody can see is not
  confirmation that anything happened. Both are **silent**, like upstream's
  setters — an unknown view name or an empty clip slot is logged to `Log.txt` and
  nothing goes on the wire, because a steering send must never fail or delay the
  tool it follows.

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
  finished export alive — Seshat's transport does not serialize queries — while
  bounding how long an orphaned multi-megabyte file survives. The export root is
  derived with `expanduser` + `abspath`, **not** `realpath`, because the Elixir
  consumer derives the same string with `Path.expand/1` and validates the reply
  path against it.
- **`abletonosc/return_track.py`** — `/live/return_track/*` and `/live/master/*`.
  Upstream's track addresses resolve through `song.tracks` only, so return
  tracks and the master are unreachable. `/live/return_track/select` is the same
  gap one level up: `/live/view/set/selected_track` indexes `song.tracks` too, so
  no upstream address can select a return. `song.view.selected_track` itself
  accepts any track, so that handler is the lookup and nothing more — and it is
  silent, for the same reason as the two view addresses above.
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

- **Anything touching `_stop_listen`, `_start_listen`, or `listener_objects`.**
  The wrong-object unbind fix above is small and easy to lose in a merge. Its
  symptom is invisible — every address still answers, and the mirror just
  quietly reports one track's name under another's index.

## Contributing back

The base-class listener fix and the mixer-listener bookkeeping are general bugs,
not Seshat-specific, and would be worth filing upstream if it revives. Doing so
is a courtesy, never a dependency.
