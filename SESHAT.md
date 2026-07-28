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

### Additions to upstream's code

- **`clip.py` — `quantize` in the generic methods list.** From upstream PR #198
  (that PR's warp-marker and extended-note work is not taken). Gives
  `/live/clip/quantize track_id, clip_id, grid, amount` via the existing
  `_call_method` path. `grid` is Live's `GridQuantization` enum — **not**
  `RecordingQuantization`: `no_grid=0, g_8_bars=1, g_4_bars=2, g_2_bars=3,
  g_bar=4, g_half=5, g_quarter=6, g_eighth=7, g_sixteenth=8, g_thirtysecond=9`.
  So sixteenths is `8`.

### Seshat's own handlers

Three modules that upstream has no equivalent of. Each carries its own header
comment explaining what it adds and why. They are registered at the end of
`manager.py`'s handler list; position is not load-bearing.

- **`abletonosc/browser.py`** — `/live/browser/*`. Upstream exposes no browser
  API at all. Indexing, search, load-onto-track, bulk export to JSON, and
  preview.
- **`abletonosc/return_track.py`** — `/live/return_track/*` and `/live/master/*`.
  Upstream's track addresses resolve through `song.tracks` only, so return
  tracks and the master are unreachable.
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

- **Anything touching `_stop_listen`, `_start_listen`, or `listener_objects`.**
  The wrong-object unbind fix above is small and easy to lose in a merge. Its
  symptom is invisible — every address still answers, and the mirror just
  quietly reports one track's name under another's index.

## Contributing back

The base-class listener fix and the mixer-listener bookkeeping are general bugs,
not Seshat-specific, and would be worth filing upstream if it revives. Doing so
is a courtesy, never a dependency.
