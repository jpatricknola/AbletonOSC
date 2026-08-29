# Plan: Create an audio clip from a file, and settle the path-safety shape for reads

Roadmap item: **#1 · Create an audio clip from a file, and settle the
path-safety shape for reads** — from `CLOSING_THE_GAPS.md` rule 4 and the
per-member rows in `FORK_GAPS.md` for `Track`, `ClipSlot` and
`SimplerDevice`. Closes three member gaps —
`Live.Track.Track.create_audio_clip`,
`Live.ClipSlot.ClipSlot.create_audio_clip`,
`Live.SimplerDevice.SimplerDevice.replace_sample` — and establishes the
fork's one answer for an address whose argument names a file to **read**.

## Context

Three LOM members take a filesystem path and open it with Live's
privileges. None is reachable over OSC today, and rule 4 of
`CLOSING_THE_GAPS.md` is the only rule on that page that *defers* a handler
shape rather than deciding it. The first of the three to ship therefore
sets the precedent for the other two, which is why they are one item.

Live's signatures, from the 2026-08-29 inventory:

    create_audio_clip( (Track)self, (object)path, (float)position ) -> Clip
    create_audio_clip( (ClipSlot)self, (object)path ) -> Clip
    replace_sample( (SimplerDevice)self, (object)path ) -> None

`path` is an absolute filesystem path. There is no URI-taking overload —
unlike `Browser.load_item`, which is why that address could take a `uri`
and these cannot.

**The consumer use case exists after all, and it decides the root set.**
`ROADMAP.md` and `CLOSING_THE_GAPS.md` both record that no consumer use
case is on file, and inside *this* repository that is exactly true: no
markdown or Python file here mentions rendered audio, a wav, or any
Seshat-owned audio directory. It is on file in the consumer's own
repository, in `~/seshat/docs/ROADMAP.md` (its **#1** item, "Generate audio
onto a track — Stable Audio 3, imported as a clip") and the 793-line
`~/seshat/docs/PLAN_generate_audio_clip.md` written against fork pin
`4186074`, which names this fork address as its blocker and specifies:

- The audio is a bar-exact WAV rendered locally by an MLX Stable Audio
  runtime, imported into a **named Session slot** — so the consumer needs
  `ClipSlot.create_audio_clip` and nothing else. It is explicitly
  Session-first; Arrangement placement is out of its scope, and the Simpler
  path is a separately gated future item.
- Files live in **`~/.seshat/generated/`**, append-only, uniquely named
  (`<slug>-<utc-timestamp>-<seed>.wav`), **deliberately outside the User
  Library** so that no browser indexing or URI lookup is involved. Its
  config note says the value "is part of the fork contract, not a
  user-facing setting; changing it requires changing `IMPORT_ROOT` in the
  fork too", and that no environment may redirect it.
- The call site is
  `Transport.query("/live/clip_slot/create_audio_clip", [track, slot,
  Path.basename(out_path)], 15_000)` — it sends a **basename**, not a path.
- Its scope section states the address exists "for Seshat's own files only,
  and its root guard says so".

That settles the open question the roadmap could not: **one root,
`~/.seshat/generated`**, alongside `browser.py`'s existing
`~/.seshat/browser-exports`. All three of the roadmap's candidates are
answered — the User Library is ruled out by the consumer explicitly, the
set's project folder implicitly (Live *references* the file rather than
copying it, so an imported clip pins the file wherever it already lives),
and the third candidate, "a Seshat-owned directory alongside
`~/.seshat/browser-exports`", is the answer. It also kills the optional URI
form outright: a URI reaches only Live's browser tree, which by the
consumer's own design excludes every file this address exists to import.
The `BrowserItem.source` measurement `CLOSING_THE_GAPS.md` parks against
this item is therefore not needed by it (it stays parked for the *Browser
tree* bucket).

**Research changed the shape of the check.** `ROADMAP.md`'s presumed answer
was a rooted allowlist over an absolute path: `realpath` the wire argument,
resolve symlinks before the root check, reject anything landing outside a
declared root set. This plan lands something strictly stronger and smaller:
the wire argument is a **name relative to the root**, never an absolute
path, and the handler constructs the absolute path itself. Given a fixed
root, an absolute argument can only ever name files the relative form
already names, so it buys the caller nothing while keeping the
"caller-supplied path opened with Live's privileges" shape that the whole
rule exists to remove. The escape checks the roadmap asked for do not go
away — `..` components and symlinks pointing out of the root are defeated by
resolving the joined path and comparing it against the resolved root, which
is the roadmap's "resolve symlinks *before* the root check" performed on a
path the fork built.

Two constraints from the existing code shape the parts below.

- **`browser.py` is not the model, and it is also not testable.** It
  `import Live` at module scope, so `tests_unit/` has no loader for it
  (`tests_unit/conftest.py`'s docstring says so). `clip_slot.py`,
  `track.py` and `device.py` *are* all driven end to end by the Live-free
  suite. So the shared path check goes in a new module that imports only
  `os`/`typing` — the precedent `track_callback.py` and `track_identity.py`
  set — and is unit-tested directly as well as through all three handlers.
- **The command socket is loopback-only** since PR d863361, so a caller
  reaching these addresses is already local code running as the user and
  could read the file without Live. That lowers the marginal exposure of a
  read; it is why the answer can be a bounded root at all rather than
  `export`'s no-argument form.

## Wire contract

Three new addresses. **Nothing existing changes** — no reply shape, no
push, no error path, no rename.

All three **always reply**, on the address they were called on, including
on every refusal — the `browser.py` convention, not the silent-on-success
convention of the generic `/live/track/<method>` loop. Three reasons: a
path refusal is caller-fixable and undiagnosable from silence; the consumer
requires a positive `length` back; and an unknown address (an install that
predates this change) is otherwise indistinguishable from success.

`"ok"`/`"error"` is a **fixed slot** — index 2 for the clip-slot and device
addresses, index 1 for the track address — so a client switches on it
positionally. That is the invariant, not equal arity: clip slot and device
happen to reply four fields either way, but the track address's success
reply carries four and its refusal three. Do not pad the refusal to match.

### New — `/live/clip_slot/create_audio_clip` (hand-written, `clip_slot.py`)

| Direction | Arguments |
|---|---|
| Request | `track_index (i), clip_index (i), name (s)` |
| Reply, success | `track_index, clip_index, "ok", length (f)` |
| Reply, refusal | `track_index, clip_index, "error", message (s)` |

- `name` is a path **relative to the import root** (§ *The path rule*
  below). A bare `foo.wav` is the normal form.
- `length` is `clip.length` in beats, read back immediately after the call
  from the returned `Clip` (falling back to `clip_slot.clip`). ⚠️ If it
  cannot be read the reply carries `-1.0` rather than changing arity.
- Refusals, all with `"error"` and none of which touch Live: the name fails
  the path rule; the slot already holds a clip (`clip_slot.has_clip`);
  Live raised inside `create_audio_clip` (caught, `str(exception)` becomes
  the message).
- A bad `track_index`/`clip_index` raises in `create_clip_slot_callback`'s
  lookup *before* the worker runs, so it arrives as the structured
  `/live/error ["request", "/live/clip_slot/create_audio_clip", …]`
  envelope like every other clip-slot address — **not** as an `"error"`
  reply. This split is deliberate and must be documented: index errors are
  the wrapper's, everything else is the worker's.
- No listen pair (a method, not a property).

### New — `/live/track/create_audio_clip` (hand-written, `track.py`)

| Direction | Arguments |
|---|---|
| Request | `track_id (i or "*"), name (s), position (f)` |
| Reply, success | `track_index, "ok", position (f), length (f)` |
| Reply, refusal | `track_index, "error", message (s)` |

- Places the clip in the **Arrangement** at `position` (beats). The
  returned `Clip` is not addressable by any `/live/clip/*` address — that
  needs the Arrangement and take-lane clip resolver, which is unranked — so
  the reply carries back the position it was asked for plus the clip's
  length, and `/live/track/get/arrangement_clips/start_time` is how a
  caller finds it again.
- ⚠️ `position` is passed to Live unmodified as a float; beats is inferred
  from `arrangement_clips/start_time`'s units, not measured.
- Goes through `create_track_callback`, so `track_id` accepts `*` and fans
  out — **one clip created per regular track**, one reply datagram each.
  Two things must be written down rather than special-cased: the fan-out is
  all-or-nothing for *replies* (a raise at any track aborts the collection
  and produces one `/live/error`), but **not** for *effects* — clips
  created on earlier tracks stay created. A path refusal is not a raise, so
  a bad name under `*` produces N `"error"` replies and creates nothing,
  which is the well-behaved case.
  ⚠️ Note what that leaves reachable: because the worker catches every Live
  exception and answers `("error", str(e))`, and because `*` generates its
  indices with `range(len(tracks))` so the subscript cannot fail, the abort
  branch is **not reachable through this address** in normal operation — it
  is the wrapper's standing contract, inherited, not a path this handler
  exercises. The `API.md` row must not promise partial-effect cleanup or
  describe the abort as this address's behaviour; say the effects caveat
  (clips already created stay created) and leave it there.

### New — `/live/device/replace_sample` (hand-written, `device.py`)

| Direction | Arguments |
|---|---|
| Request | `track_index (i), device_index (i), name (s)` |
| Reply, success | `track_index, device_index, "ok", file_path (s)` |
| Reply, refusal | `track_index, device_index, "error", message (s)` |

- `file_path` is `device.sample.file_path` read back after the call — the
  proof the swap landed. ⚠️ `""` if it cannot be read; the arity does not
  change. Reading one attribute off `Sample` does not expose the class:
  `Sample` stays an unranked bucket.
- `SimplerDevice` only. On any other device the `getattr` raises
  `AttributeError`, which reaches the client as a structured `/live/error`
  (and is a silent skip under a wildcard, per `_is_wildcard_skip` — a
  correct outcome for `/live/device/*`).
- Regular tracks, top-level devices only, like every other `/live/device/*`
  address. Simpler inside a rack waits on the device path resolver.

### The path rule (new, shared by all three)

    IMPORT_ROOT = os.path.abspath(os.path.expanduser("~/.seshat/generated"))

Given the wire argument `name`, the handler:

1. rejects a non-string, an empty string, or one containing a NUL;
2. rejects `os.path.isabs(name)` — **the wire never carries a path**, with
   a message naming the root, since a caller cannot discover it otherwise;
3. computes `root = os.path.realpath(IMPORT_ROOT)` and
   `candidate = os.path.realpath(os.path.join(root, name))` — both sides
   resolved, so a symlinked `~/.seshat` compares equal against itself and a
   symlink *inside* the root resolves to its target before the check;
4. rejects unless `candidate` is strictly under `root`
   (`candidate.startswith(root + os.sep)`; the root itself is a rejection);
5. rejects unless `os.path.isfile(candidate)` — resolved already, so this
   also refuses a directory, a dangling symlink and a device node;
6. otherwise returns `candidate`, the absolute path handed to Live.

Every rejection logs at error level (`browser.py`'s precedent: the log is
the only evidence channel when another client holds the reply port) and
reaches the caller as that address's `"error"` reply. **Nothing is opened
and no Live method is called on a rejected request.**

Deliberately *not* in the rule, each with its reason:

- **No filename charset regex and no extension allowlist.** The consumer's
  draft proposed `^[a-z0-9][a-z0-9-]*\.wav$`; that would refuse
  `Drums_01.wav` and every aiff/flac/mp3 Live reads perfectly well, and it
  guards nothing the structural checks above do not. The fork's rule is a
  superset — the consumer's basenames pass unchanged.
- **No second root.** One root, one constant. Adding a root later is one
  line in the resolver plus an `API.md` row; the condition that would
  justify one is a *stated* second consumer, the same bar this one had to
  clear.
- **The root is never created.** `browser/export` creates its write root on
  demand; a read root that does not exist simply refuses everything, and
  creating directories in the user's home for a read is unearned. The
  consumer creates it.
- **`realpath` here, `abspath` in `browser.py`.** The two are not
  inconsistent: `browser.py:122-130` avoids `realpath` because Elixir
  re-derives that exact string with `Path.expand/1` and must match it. Here
  the resolved path is internal — the reply echoes what the caller sent —
  so resolving both sides is free and is what makes the symlink check work.
  Say this in the code comment; it is the first thing a reader will
  question.

### Unchanged but relied on

- `/live/clip/get/file_path` (`clip.py:243`) and `/live/clip/get/length` —
  the Live-verification read-backs for the clip-slot address.
- `/live/clip_slot/get/has_clip` — the same flag the handler refuses on.
- `/live/track/get/arrangement_clips/start_time` / `length` — how the
  Arrangement clip is found again.
- `/live/song/get/file_path` — *not* used by the rule, but the reason the
  "current set's project folder" candidate was even considerable. Recorded
  here so the next person does not re-derive it.
- `OSCServer._dispatch`'s structured `/live/error` envelope, and the
  list-of-tuples multi-reply contract the `*` fan-out depends on.

## Numbered parts

### Part 1 — `abletonosc/path_safety.py` (new): the rule, Live-free

- `IMPORT_ROOT`, the constant, spelled on **one line** exactly as in the
  contract above (Seshat's `vendored_addresses_test` asserts the literal
  the way it asserts `EXPORT_ROOT`).
- `class ImportPathError(Exception)` and
  `resolve_import_path(name, root=None) -> str`, raising `ImportPathError`
  with a caller-facing message on every rejection. `root=None` means
  `IMPORT_ROOT`, read **at call time**, so tests can point it at a
  `tmp_path` without monkeypatching internals.
- Imports `os` and `typing` and nothing else — no `Live`, no `.handler`.
  This is what makes it directly testable and what keeps the rule identical
  in all three handlers instead of copied three times.
- A header comment carrying: why the wire takes a name and not a path; why
  both sides are `realpath`ed here while `browser.py` deliberately does not;
  that this is the read-side rule and `browser/export` is the write-side
  one; and that `/live/application/dump_lom` is the known outstanding
  violation on the write side (`issues.md`, Low) which this rule does not
  cover.

### Part 2 — `abletonosc/clip_slot.py`: `/live/clip_slot/create_audio_clip`

- `from .path_safety import ImportPathError, resolve_import_path`.
- A hand-written worker registered through the existing
  `create_clip_slot_callback` (no `pass_clip_index` — the wrapper already
  prefixes both indices onto the reply).
- Order: resolve the path → refuse if `clip_slot.has_clip` → call
  `clip_slot.create_audio_clip(path)` inside `try` → read `length` back.
  The `has_clip` refusal is the fork's own, not Live's: what Live does with
  an occupied slot is unmeasured (open question 1) and the consumer wants an
  explicit refusal either way.

### Part 3 — `abletonosc/track.py`: `/live/track/create_audio_clip`

- Same import; a hand-written worker registered through
  `create_track_callback` (so `*` and index normalisation come for free).
- `name, position = params[0], float(params[1])` off the wrapper's tail;
  a missing `position` is a refusal, not an `IndexError`, so that a
  malformed request cannot masquerade as a wildcard skip.

### Part 4 — `abletonosc/device.py`: `/live/device/replace_sample`

- Same import; hand-written worker through `create_device_callback` with
  no `include_ids` (the wrapper prefixes both indices).
- **Order, and it is load-bearing for the wildcard case:** bind the method
  with `getattr(device, "replace_sample")` **first**, before resolving the
  path. A non-Simpler then raises `AttributeError` — which is what makes it
  a silent `_is_wildcard_skip` under an address-pattern request such as
  `/live/device/* 0 0 "x.wav"`, the behaviour the Testing section asserts.
  Resolving first would instead return an `"error"` triple from *every*
  matched device endpoint on a bad name. `getattr` is a bind, not a call, so
  the path rule's "no Live method is called on a rejected request" still
  holds. This is the one place among the three where the order is observable.

### Part 5 — `manager.py`: reload ordering

- `importlib.reload(abletonosc.path_safety)` beside
  `abletonosc.track_identity`, i.e. **before** `clip_slot`, `device` and
  `track`. All three do a `from` import of it, and `manager.py:152-195`
  documents exactly this hazard: a module reloaded before its `from`-imported
  dependency keeps calling the previous edit's functions, the reload logs
  success, and no Live-free test can catch it.
- No change to `abletonosc/__init__.py`: `path_safety` exports no handler.

### Part 6 — documentation, **same commit as Parts 1–5**

- **`API.md`**
  - A new subsection under § "Conventions the address tables don't show",
    after "Object-valued reads": **"Handlers that name a file to read"** —
    the root, the relative-name form, the six-step rule, the always-reply
    convention, the index-error-versus-`"error"`-reply split, and the
    statement that `browser/export` is the *write*-side rule and
    `dump_lom` the outstanding exception. The roadmap requires the root
    rule to be discoverable from the docs, because it cannot be discovered
    from an error alone.
  - Rows: `/live/track/create_audio_clip` in § Track Methods;
    `/live/clip_slot/create_audio_clip` in § Clip Slot API;
    `/live/device/replace_sample` in the Device section. Each row: exact
    arguments, both reply shapes, ⚠️ on every unmeasured claim, and a
    pointer to the new conventions subsection.
  - The Clip Slot section's "every `get/` property also has a listen pair"
    paragraph must not be read as covering a method — no edit needed, but
    check it.
- **`SESHAT.md`** § "Additions to upstream's code": one entry covering all
  three addresses and `path_safety.py`, stating that upstream has none of
  them, that the module is new, and that `clip_slot.py`, `track.py`,
  `device.py` and `manager.py` are upstream files this fork now edits. Add
  a **merge hazard** bullet: a merge that takes upstream's `clip_slot.py`,
  `track.py` or `device.py` `init_api` wholesale drops the registrations
  *and* the path rule silently — the addresses simply stop existing, which
  over fire-and-forget UDP looks like nothing at all; `tests_unit/` is the
  tripwire.
- **`FORK_GAPS.md`**
  - The three generated rows — `create_audio_clip` under
    `Live.Track.Track` (~:501) and `Live.ClipSlot.ClipSlot` (~:597), and
    `replace_sample` in the compact `Live.SimplerDevice.SimplerDevice`
    method list (~:859) — clear **by regeneration only, and regeneration
    cannot happen in this run** (open question 5). So: do not hand-edit the
    block between the `lom-gaps:begin`/`lom-gaps:end` markers, leave those
    three rows standing, and **say so in the PR body** — the precedent is
    `docs/archive/PLAN_object_valued_read_helpers.md` open question 6, which
    shipped the curated deletions in the code commit and let the next dump
    clear the generated rows. The curated hand-edits below are this commit's
    `FORK_GAPS.md` obligation.
  - Hand-edit the curated caution bullet (~:208-211) — it currently says
    "any handler must follow the fork's path-safety rule" as an open
    instruction. Replace with a pointer to the shipped rule in `API.md` and
    to `path_safety.py`, noting the two remaining members it still governs
    are none (all three ship here) and that `dump_lom` is the write-side
    exception.
  - Hand-edit the preamble (~:13-16), which lists "the path-safety rule for
    handlers taking a filesystem path" among the surface **deliberately left
    unaddressed**. That is no longer true and contradicts
    `CLOSING_THE_GAPS.md` rule 4 ("not an exclusion"); rule 5 alone remains.
  - Hand-edit the curated *`SimplerDevice` slicing* entry (~:165-185): its
    "**Shape to build:** `replace_sample`, `playback_mode` setter, `slices`
    getter" line is stale the moment this ships. Drop `replace_sample` from
    it and point at the new `API.md` row; leave the rest of the entry (the
    `Sample`-owns-the-slice-API finding) alone.
- **`CLOSING_THE_GAPS.md`**: rewrite rule 4 from a deferral into the
  shipped decision (one root, a relative name, resolve-and-compare, always
  reply, `export` is the write-side rule), and drop the "Ranked on the
  roadmap (rule 4 path handlers) | 1 | 3" row from the Count table,
  adjusting the totals: **27 → 26 PRs, and the member column stays at 419**.
  The PR column is exact and is this file's own decision; the member column
  is estimates that already do not sum (the file says so), and 419 is
  `FORK_GAPS.md`'s figure — which is not being regenerated in this commit,
  so moving it to 416 here would desync the two files. Say in the row's
  prose that three members ship with this item. Check the `Track` (~:169),
  `Clip/ClipSlot/Scene` (~:171) and `SimplerDevice` (~:188) bucket rows:
  each carries a parenthetical "ranked on the roadmap" note about these
  members that must become "shipped" or be deleted. Also the **Browser
  tree** bucket row, which says "`BrowserItem.source` is the member to
  measure for the roadmap's audio-clip item" — that item is shipping and has
  declined the URI form, so the sentence must stop citing it and either keep
  the measurement on the Browser bucket's own account or drop it.
- **`ROADMAP.md`**: **not** in this commit. `/ship` removes the entry.
- **`tools/lom_gaps.py`**: **one alias entry, not "no change".** The
  reasoning was checked against `covered_names()` (`tools/lom_gaps.py:142`)
  and holds for two of the three members, not all three. Coverage is
  `PREFIX_CLASSES[prefix]` × segment equality, so
  `/live/track/create_audio_clip` covers `Live.Track.Track`
  (`"track": ["Live.Track.Track", "Live.MixerDevice.MixerDevice"]`) and
  `/live/clip_slot/create_audio_clip` covers `Live.ClipSlot.ClipSlot` — both
  correct, and neither leaks to `Live.TakeLane.TakeLane`, which also has a
  `create_audio_clip` member (FORK_GAPS ~:744) but is not in any prefix's
  class list. `/live/device/replace_sample` does **not** reach
  `Live.SimplerDevice.SimplerDevice`: `"device"` maps only to
  `["Live.Device.Device", "Live.DeviceParameter.DeviceParameter"]`, so on
  the next regeneration `replace_sample` would still be counted a gap.
  Add, in the same commit:

      "Live.SimplerDevice.SimplerDevice": {
          "replace_sample": "/live/device/replace_sample",
      },

  to `ALIASES` — `class_block`'s `got = cov | set(ALIASES...)`
  (`tools/lom_gaps.py:211`) is what then counts it exposed, and the
  `_Reached under another address:_` line records why. This is exactly the
  case the tool's own comment calls an honest alias: the *capability* is
  reachable, under a prefix the class map does not associate with the class.
  Do **not** instead add `Live.SimplerDevice.SimplerDevice` to
  `PREFIX_CLASSES["device"]` — that would silently re-mark other members by
  name collision.

### Part 7 — `tests_unit/`: coverage (same commit)

New `tests_unit/test_path_safety.py` and
`tests_unit/test_audio_clip_import.py`; plus **four** docstrings in
`tests_unit/conftest.py`, not one — each enumerates the imports of the
modules it loads and each goes stale:

- the module docstring (~:60-70), "device.py, scene.py, clip_slot.py,
  track.py, return_track.py and groove.py import only
  logging/typing/functools/.handler and the Live-free .track_callback /
  .track_identity" — must now name `.path_safety`;
- `load_device_module()` (~:190), "imports nothing from Live — only `typing`
  and `.handler`";
- `load_clip_slot_module()` (~:229), "Like device.py it imports nothing from
  Live — only typing and .handler";
- `load_track_module()` (~:238), "only typing, .handler, .track_callback and
  .track_identity".

They are load-bearing prose, not decoration: they are the record of why each
loader needs no Live stub, and `path_safety.py` (os + typing) does not change
that conclusion for any of them — which is the sentence to add.

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` — 734 passing at `fd5b346`, the baseline to
beat. Everything below is Live-free and driven through `conftest.py`'s
`dispatch` fixture and the existing `load_clip_slot_module()`,
`load_track_module()` and `load_device_module()` loaders; no new loader is
needed, and `path_safety.py` is reachable with a bare
`load_module("abletonosc.path_safety")` because it imports no Live module.

**`test_path_safety.py`** — the rule as a pure function, with
`resolve_import_path(name, root=str(tmp_path))`:

- accepts a bare name for a real file in the root; returns an absolute path;
- accepts a nested relative name (`sub/kick.wav`);
- rejects an absolute path, with the root named in the message;
- rejects `../escape.wav` and `sub/../../escape.wav`;
- rejects a **symlink inside the root pointing at a file outside it** — the
  roadmap's named case, and the one only `realpath` catches;
- accepts a symlink inside the root pointing at another file *inside* it
  (proves the check is "resolves inside", not "is not a symlink");
- rejects a directory, a dangling symlink, a missing file, the empty
  string, a non-`str`, and a name containing `\0`;
- passes when the root itself is reached through a symlink (macOS
  `/tmp` → `/private/tmp` makes this the default under `tmp_path`, so it is
  worth an explicit assertion rather than an accident);
- `IMPORT_ROOT` is `~/.seshat/generated` expanded and absolute.

**`test_audio_clip_import.py`** — the three addresses end to end, fake LOM
objects only (the `FakeTrack`/`FakeClipSlot` style of
`tests_unit/test_object_reads.py`), with the module's `IMPORT_ROOT`
monkeypatched to a `tmp_path` holding one real file:

- clip slot: success replies `(t, c, "ok", length)` and the fake records the
  **absolute** path it was handed; a bad name replies `(t, c, "error", …)`
  and the fake records **no call at all**; an occupied slot replies
  `"error"` and makes no call; a Live-side exception is caught and replied
  as `"error"` carrying its text; a bad `track_index` produces a
  `/live/error` `("request", …)` envelope and **no** reply on the request
  address (the split contract);
- track: success replies `(t, "ok", position, length)`; `*` fans out to one
  reply per track; a refusal under `*` yields N `"error"` replies and zero
  calls into the fakes; a missing `position` is an `"error"` reply, not an
  `IndexError`;
- device: success replies `(t, d, "ok", file_path)`; a device with no
  `replace_sample` attribute produces the structured `/live/error`, and
  under `/live/device/*` is skipped silently (assert no datagram at all);
- all three: the `"ok"`/`"error"` discriminator sits at a **fixed index** on
  both paths — index 2 for clip slot and device, index 1 for track — so a
  client switches on it without counting arguments. Arity is equal across the
  two paths for clip slot and device (4 and 4); it is **not** for track
  (success 4: `track_index, "ok", position, length`; error 3:
  `track_index, "error", message`), which is why the invariant to assert is
  the discriminator's index, not the length.

**Not covered here, and the plan says so plainly.** No `tests_unit/` test
executes a real `ClipSlot.create_audio_clip`, so nothing below is Live-free
evidence: whether Live accepts the path, what it raises for a non-audio or
unreadable file, whether the returned `Clip` is readable synchronously,
whether an occupied slot or a MIDI track would have raised anyway, and what
`position` means. `tests/` (the live suite) mutates a running Live on
import-time opt-in, binds the reply port, and is **not** part of the gate;
adding cases there is optional and must stay behind `ABLETONOSC_LIVE_TESTS=1`.

## Live verification (deferred unless the precondition holds)

**Precondition, shared by every check:** the Remote Scripts copy at
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC` must equal this
checkout byte for byte (`diff -rq --exclude=__pycache__`) **and** Live must
have been restarted since it was copied. Files on disk are not code in
memory. This lifecycle run may not install or restart, so these checks are
expected to be **skipped, not failed** — record them as skipped and leave
every ⚠️ in `API.md` standing. Method: `API.md` § "The no-probe variant" —
send from a plain UDP socket to `127.0.0.1:11000` and read the new bytes of
the installed `logs/abletonosc.log`; the reply port 11001 may not be bound.
Wrap every mutating check in `/live/song/begin_undo_step` …
`/live/song/end_undo_step` and restore what changed.

Preparation: put one real WAV in `~/.seshat/generated/` (the folder does not
exist yet — `~/.seshat` currently holds `browser-exports/`, `audio-spike/`
and `stable-audio-3/` only; `audio-spike/` has 24 generated WAVs to copy
from).

1. **Happy path, clip slot.** `/live/clip_slot/create_audio_clip <audio
   track> <empty slot> "<name>.wav"` → log line `clip_slot t c -> ('ok',
   L)`; then `/live/clip/get/file_path t c` logs the absolute path under
   `~/.seshat/generated`, and `/live/clip/get/is_audio_clip t c` logs 1.
   Restore: `/live/clip_slot/delete_clip t c`.
2. **Path refusal.** Same address with `"../../etc/passwd"`, with
   `"/etc/passwd"`, and with `"nope.wav"` → three error-level log lines
   naming the root, and `/live/clip_slot/get/has_clip` unchanged at 0 after
   each. This is the check that proves nothing was opened.
3. **Occupied slot.** Repeat check 1 without deleting → `"error"` and the
   existing clip's `file_path` unchanged.
4. **MIDI track / bad file.** Check 1 against a MIDI track's slot, and
   against a text file renamed `.wav` placed in the root → record what Live
   raises and whether the handler caught it (an `"error"` reply and a
   handler log line) or it escaped to `/live/error`. **This decides open
   questions 1 and 2** and is the one whose answer changes `API.md`.
5. **Track / Arrangement.** `/live/track/create_audio_clip <audio track>
   "<name>.wav" 8.0` → reply logged; then
   `/live/track/get/arrangement_clips/start_time <t>` shows `8.0` and
   `.../length` shows the same `L` as check 1. Confirms the position units.
   Restore: `/live/song/undo` — **twice** if roadmap item "One
   `/live/song/undo` does not revert an OSC-created scene" is still open —
   and re-read `arrangement_clips/start_time` to prove it is gone. If it
   cannot be removed, say so in the PR rather than leaving it.
6. **`replace_sample`.** With a Simpler carrying a sample at a known
   top-level index: `/live/device/replace_sample t d "<name>.wav"` → reply
   carries the new `file_path`; restore by replacing the original sample
   (put its path in the root first, or accept and record that the set is
   left changed). If no Simpler is to hand, skip and say so — this is the
   member with no consumer waiting on it.

Remains uncovered afterwards: the wildcard fan-out of
`/live/track/create_audio_clip *` (creates N Arrangement clips that undo
must remove — deliberately not run against a real set), and the behaviour
of Live's importer on formats other than WAV.

Also at verification time: send `/live/application/dump_lom` and run
`tools/lom_gaps.py logs/lom_dump.json --write` to regenerate the inventory
(open question 5).

## Downstream

**Not "pin bump only" — pin bump plus a new tripwire, and a reconciliation
in the consumer's pending plan.** No existing address, reply shape,
listener push or error path changes, so nothing Seshat does today breaks.
What it must do:

1. Bump the submodule pin, `mix abletonosc.install`, restart Live.
2. **Create `~/.seshat/generated`** (mode 0700 alongside
   `~/.seshat/browser-exports`). The fork never creates it; until it exists
   every request is refused.
3. Add the `vendored_addresses_test` tripwire, modelled on the export block
   at that file's lines 958-1020 — but pointed at
   `priv/AbletonOSC/abletonosc/path_safety.py`, **not** `clip_slot.py`:
   assert the literal `IMPORT_ROOT = os.path.abspath(os.path.expanduser(
   "~/.seshat/generated"))` line; assert the refusal string; assert the
   `realpath` join is present; and `refute` any handler joining or opening
   an unvalidated `params` element. The three new addresses also flow
   through the test's existing "every address Python registers must be in
   the canonical address docs" check the moment they are registered — so
   `API.md` must carry all three rows in the same commit or Seshat's suite
   goes red on the pin bump.
4. Reconcile `~/seshat/docs/PLAN_generate_audio_clip.md` with what shipped.
   Its request and reply shapes are adopted as proposed and its call site
   needs no change (`Path.basename/1` output passes the fork's rule); what
   differs is the **name check** — the shipped rule is structural
   (relative, resolve, under-root, regular file), not the
   `^[a-z0-9][a-z0-9-]*\.wav$` regex it proposed, and the constant lives in
   `path_safety.py` rather than `clip_slot.py`. Anything in that plan
   asserting the regex or the file location is stale. **One further
   divergence to reconcile, because it is a refusal that will not happen:**
   that plan's contract row says the fork refuses "when … the resulting entry
   is a symlink". The shipped rule refuses a symlink only when it *resolves
   outside* `IMPORT_ROOT`; an in-root symlink to an in-root file is accepted
   deliberately (`realpath` both sides, compare — see § *The path rule*). A
   tripwire asserting a blanket symlink refusal would assert behaviour the
   fork does not have.

`Track.create_audio_clip` and `replace_sample` have no consumer and need no
Seshat work beyond the pin.

## Out of scope

- **`/live/application/dump_lom`'s write path.** It still takes an
  arbitrary wire path and *writes* it with Live's privileges. It is the
  genuine write-side inconsistency, it should adopt `browser/export`'s
  pattern rather than this one, and it stays in `issues.md` (Low). Folding
  it in here would let a write concern argue for a stricter read rule.
- **The Arrangement and take-lane clip resolver**, which would make
  `/live/track/create_audio_clip`'s result addressable. Unranked in
  `CLOSING_THE_GAPS.md`; this item explicitly does not wait for it.
- **The `Sample`, `SimplerDevice` and `SimplerDevice.View` buckets**
  (30 + 20 + a share of 17 members). `replace_sample` ships alone, as the
  third instance of the rule; reading `sample.file_path` for one reply
  field does not open the class.
- **A `BrowserItem.uri` second form**, and the `BrowserItem.source`
  measurement `CLOSING_THE_GAPS.md` parks against this item. Declined on
  the consumer's own design note — the files this address imports are
  deliberately outside the browser tree, so a URI form could never reach
  them. The measurement stays parked for the *Browser tree* bucket.
- **A second import root** (User Library, project folder). Both were
  weighed and answered by the consumer; see Context.
- **`.claude/skills/plan/SKILL.md:47` and its `.agents/skills/plan/SKILL.md`
  copy, which tell a planner that "`browser/export` is the model: reject a
  wire-supplied destination, write under a private root" for *any* handler
  taking a filesystem path.** That is the write-side rule and it now
  contradicts the shipped read-side rule; a planner or reviewer following it
  literally will mark this plan non-conformant. Out of scope because the
  lifecycle tooling is not this item's to edit — flagged for the user in the
  PR. (Those two files are the whole of it: `pr-review/SKILL.md` carries no
  such instruction — `grep -rn "browser/export" .claude/skills .agents`
  returns exactly the two `plan/SKILL.md` lines.)

## Open questions

1. ⚠️ **What Live raises for an unreadable or non-audio file, a MIDI
   track's slot, or an occupied slot.** Unmeasurable in this phase: Live
   12.4.5 is running, but the probe rig in `API.md` § "Measuring the Live
   API without building the feature first" needs a temporary handler
   written into the *installed* copy, and that write was refused by this
   environment's permission classifier. Meanwhile the plan assumes nothing:
   every Live call is wrapped and its exception text becomes the `"error"`
   message, so any of the possible answers produces a correct reply. Live
   verification check 4 decides what `API.md` records.
2. ⚠️ **Whether the returned `Clip` is readable synchronously.** Assumed
   yes — Stable Audio 3's own `AudioInserter.py` does
   `track.clip_slots[0].create_audio_clip(path)` then reads
   `slot.clip.length` immediately, which is prior art on this exact call,
   not a guess about Live in general. The fallback path (`clip_slot.clip`,
   then `-1.0`) means a "no" costs a `-1.0` in one field rather than a
   raise. Verification check 1.
3. ⚠️ **`position`'s units for `Track.create_audio_clip`.** Assumed beats
   in Arrangement time, from `arrangement_clips/start_time`'s units and
   Live's `(float)` signature. The handler passes it through unmodified, so
   a wrong assumption is a documentation error, not a code one.
   Verification check 5.
4. ⚠️ **Whether `SimplerDevice.replace_sample` returns anything and whether
   `device.sample.file_path` reflects the new sample immediately.** The
   inventory gives the signature as `-> None`. Assumed the read-back works;
   the reply carries `""` if it does not. Verification check 6, and this is
   the check most likely to be skipped for want of a Simpler in the set.
5. ⚠️ **The `FORK_GAPS.md` inventory cannot be regenerated in this
   lifecycle run.** `tools/lom_gaps.py` needs a `/live/application/dump_lom`
   taken from a Live *running the new code*, and this run may not install or
   restart. No `lom_dump*.json` exists in the repo or in the installed
   `logs/`. Plan: hand-edit the curated bullets (Part 6) in the code commit,
   leave the generated block untouched and **say so in the PR**, and
   regenerate at the first post-install dump. Recommendation, carried over
   from `docs/archive/PLAN_object_valued_read_helpers.md`: commit the dated
   dump (`tools/lom_dump_<date>.json`) when it is finally taken, so
   regeneration stops depending on a session nobody has.
6. ⚠️ **The root's value is fixed by a consumer document this repository
   does not contain.** `~/.seshat/generated` comes from
   `~/seshat/docs/PLAN_generate_audio_clip.md`, which states the value is
   part of the fork contract. If that plan changes the folder before it
   ships, `IMPORT_ROOT` and the tripwire change with it. The fork's side is
   one constant on one line, deliberately.
