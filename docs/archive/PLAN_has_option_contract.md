> **Archived 2026-08-30 — shipped.** This is the plan as written *before*
> implementation; the code as merged may differ. The change lives in
> `abletonosc/application.py`'s `get_has_option` handler, documented in
> `API.md`'s Application table and its "Partially measured against Live
> 12.4.5" block, with the divergence recorded in `SESHAT.md`. Live
> verification checks 1-7 did not run (Live's installed copy was not this
> code); that result is recorded in this doc's own "Live verification"
> section rather than a follow-up elsewhere — whoever next installs and
> reloads can run them.

# Plan: `/live/application/get/has_option` — the real contract

Roadmap item: **#1 · `/live/application/get/has_option` documents a contract
Live does not implement**. A defect introduced by the Application dialogs and
versions item (PR #18, merged 2026-08-29), whose plan flagged "what form
`has_option` expects" as an open question and shipped the guess as
documentation.

## Context

`/live/application/get/has_option` was specified, implemented and documented as
an Options.txt query: hand Live the option name (`-_EnableFoo`), get back
`name, present`. The 2026-08-29 verification run against Live 12.4.5 found that
`Application.has_option` is not that function. It takes **exactly 64
hexadecimal characters** and rejects everything else before it looks anything
up. No Options.txt name is expressible, so every use the doc described fails
with a `/live/error`.

The roadmap's Goal offers two outcomes: the address answers a question a caller
can actually ask, or it is removed. Research settles which, and the answer
turned on two things — what the 64-hex key *is*, and whether a well-formed one
answers at all.

### What the key is (Live 12.4.5, read out of Live's own shipped Python)

- `Contents/App-Resources/Python/abl.live/_LiveApiMock/Live/Application.pyc`
  — Ableton's own mock of the Live API — models options as a plain set
  `_options` with three members: `has_option(key)`, `non_api_add_option(...)`
  and `non_api_remove_option(...)`. The `non_api_` prefix is Live's marker for
  "not exposed to scripts": a Remote Script can *ask* whether an option is
  present, and cannot enumerate, add or remove one.
- `Contents/App-Resources/Python/abl.live/abl/live/licensing/__init__.pyc`
  contains the only literal key found in Live's Python:
  `has_option("fbb8b6e2603b931b8fc884f09e56c4d9391d78105cbf2c711c9a22e0fb7152fd")`,
  guarding a property named `skip_unlock_file`.

So the key is a 32-byte digest of an internal option name, and Live's own error
text ("Key contains non-hex characters") calls it a key. The digest is not a
plain SHA-256 of the identifier it guards — `sha256("skip_unlock_file")` is
`ced382216adfa029ab2bfc232256a10283b96684a41499b3f8d8d7926700640f`, not the
key above — and Ableton publishes no name→key mapping. **A caller cannot derive
a key from an option name.** It can only use a key it obtained the way this
research did, from Live's own code.

### What a well-formed key does (measured 2026-08-29, Live 12.4.5)

Second measurement run of the day, by `API.md` § "The no-probe variant" — the
installed Remote Scripts copy was confirmed identical to this checkout
(`diff -rq`, ignoring `__pycache__`/test dirs), datagrams sent from a plain UDP
socket to `127.0.0.1:11000`, answers read out of the installed
`logs/abletonosc.log`, with an `/live/application/get/open_dialog_count` read
between every case as a marker so each log line correlates to one send. Nothing
was mutated, nothing installed, no reload, no restart, and 11001 was never
bound (Seshat was not running).

| Argument | Result |
|---|---|
| 64 hex chars (`"0" * 64`) | **No log output at all** — no error, no traceback. Live accepted the key and the handler replied normally |
| the licensing key, lower case | **No log output** — accepted |
| the licensing key, **upper case** | **No log output** — accepted, so the hex is case-insensitive |
| 63 hex chars | `IndexError: basic_string` → `/live/error` |
| empty string | `IndexError: basic_string` → `/live/error` |
| 64 non-hex chars (`"z" * 64`) | `RuntimeError: Key contains non-hex characters` → `/live/error` |
| `-_EnableExtendedFileFormat` (26 chars, non-hex) | `RuntimeError: Key contains non-hex characters` — the hex check fires before the length check |

Two facts this adds to the roadmap entry, both load-bearing:

1. **A well-formed key answers.** The address is not a dead end; it is a
   working lookup with an argument nobody documented. The Goal's first branch
   is reachable.
2. **The two rejections are different Python exception classes**, and the
   difference matters here: `IndexError` is in
   `OSCServer.WILDCARD_SKIP_EXCEPTIONS` and `RuntimeError` is not. Today's
   wildcard behaviour is therefore incoherent — `/live/application/get/*
   "somestring"` gets a `/live/error` from `has_option` for a non-hex argument
   but silence for a wrong-length hex one.

The returned boolean itself was **not** read: this handler logs nothing on its
ok-path and replies to `(sender, 11001)`, which this run may not bind. Part 1
fixes that permanently by logging the answer, the way `_get_property` does.

### The decision: keep it, validate it, document it truthfully

The roadmap's planner notes lean toward removal ("if a caller cannot construct
one, the address is not useful and removing it beats documenting a trap"). The
measurements above change that balance, and this plan keeps the address:

- **It answers.** With the key in hand a caller gets a real answer, and this
  repository's stated goal is full Live Object Model coverage with **safety**
  as the only sanctioned exclusion (`FORK_GAPS.md` preamble,
  `CLOSING_THE_GAPS.md` rule 5). "No consumer can currently think of a use" is
  explicitly *not* a reason to leave surface out — `FORK_GAPS.md` says so in
  its own words: "No gap is out of scope for want of a consumer asking for it."
- **Removal opens a documentation obligation this repository cannot currently
  discharge.** Deleting the registration turns `Application.has_option` back
  into a member gap: `FORK_GAPS.md`'s generated block would have to go from
  "21 members, 19 exposed, 2 gaps" to 18/3 with a new `has_option` row, and
  that block is machine-generated from a `/live/application/dump_lom` taken
  against a Live *running the new code*. Installing into Live is out of bounds
  for this work, so a removal ships a knowingly stale generated inventory plus
  a hand-written Declined entry inventing a third exclusion category. Keeping
  the address leaves the generated block correct and untouched.
- **The trap is the documentation, not the address.** What actually broke a
  caller is an `API.md` row that named the wrong argument. Replacing the row
  and validating the argument removes the trap without removing surface.
- **It stays reversible.** Deleting later is five lines; re-adding a deleted
  wire address after Seshat has tripwired its absence is not.

So: the argument is validated at the handler (64 hex characters, case
insensitive) instead of being passed through to a C++ exception, the answer is
logged so it is verifiable by the fork's own log-reading method, and `API.md`,
`SESHAT.md` and the unit tests describe an option-key lookup rather than an
Options.txt query.

## Wire contract

### Changed — `/live/application/get/has_option` (hand-written, `application.py`)

| | |
|---|---|
| Request | `/live/application/get/has_option <key: str>` |
| Reply | `/live/application/get/has_option <key: str> <present: bool>` |
| Address | **unchanged** — same name, same arity, same reply shape |
| `key` | **exactly 64 hexadecimal characters**, `[0-9a-fA-F]`, case preserved on the echo and case-insensitive to Live. This is a digest of an internal Live option name, not an Options.txt entry and not a name of any kind |
| Echo | `key` is echoed back verbatim, byte for byte as received, as the only discriminator on this address for a client firing a burst. **Unchanged** |
| Coercion | `str(params[0])`, as today — a non-string argument is stringified and then almost certainly rejected by the validator |

**Changed error behaviour.** A malformed key is now rejected by the handler
before Live is called:

- Rejected: any argument whose `str()` is not exactly 64 characters, or
  contains a character outside `[0-9a-fA-F]`.
- The handler raises `ValueError` with a message naming the requirement, which
  `OSCServer._dispatch` turns into the documented envelope:
  `/live/error ["request", "/live/application/get/has_option", "<message>", 1, "<the key sent>"]`.
- Live's own two errors (`RuntimeError: Key contains non-hex characters`,
  `IndexError: basic_string`) become unreachable through this address. Both
  used to arrive on `/live/error` with those opaque strings as the detail.
- **No argument at all is unchanged**: `params[0]` raises `IndexError` before
  validation runs, producing the same `["request", address, detail, 0]`
  envelope pinned by today's test.

**Changed wildcard behaviour**, a direct consequence of the class chosen:
`ValueError` is in `OSCServer.WILDCARD_SKIP_EXCEPTIONS` (`osc_server.py`), so
under a pattern send such as `/live/application/get/* "anything"` this endpoint
is now *skipped with a debug log* instead of contributing a `/live/error`. That
is the correct reading of the skip contract — "this matched endpoint does not
apply to this request" — and it removes an error datagram that today's
`RuntimeError` path produces for every non-hex string swept across the
application getters. `/live/application/get/*` **with no arguments** already
skipped this endpoint (`IndexError` with no params) and still does.

**New: an ok-path log line.** The handler logs the answer at `info`, on one
line carrying both the key and the answer — for example:

```
has_option for application: <key> = <True|False>
```

`AbletonOSCHandler._get_property` is the nearest precedent, and it logs
`"Getting property for %s: %s = %s" % (self.class_identifier, prop, value)` —
note it carries **no** `AbletonOSC: ` prefix. Do not add one in the name of
matching a house format that does not have one. Exact wording is the
implementer's, but it must contain the key and the answer on one line, and the
Live verification greps below are then read against whatever string is chosen.

`info` is deliberate, and it is **not** new wire traffic: the only log handler
that relays records onto OSC is `manager.py`'s `LiveOSCErrorLogHandler`, set to
`logging.ERROR`, so an info record reaches `logs/abletonosc.log` and nothing
else.

This exists so the address is verifiable by `API.md` § "The no-probe variant",
which reads `logs/abletonosc.log` because the reply port is not always
bindable. Without it the boolean is unreadable on a developer machine — which
is precisely why it shipped unmeasured.

### Unchanged but relied on

- `OSCServer._dispatch`'s structured `/live/error` envelope
  (`["request", address, detail, argc, *args]`) and its `str(e)` detail.
- `OSCServer.WILDCARD_SKIP_EXCEPTIONS = (ValueError, AttributeError,
  IndexError)` and `_is_wildcard_skip`'s extra qualification of `IndexError`
  by argument count. Nothing in this plan edits `osc_server.py`.
- The `get_application()` seam in `application.py` and
  `tests_unit/conftest.py`'s `load_application_module()`.
- Every other address in the application table, and their count: the
  registration table stays at exactly 21 addresses, so
  `test_registration_table_is_exactly_this` needs no membership change (one
  comment above the entry does).

## Numbered parts

### Part 1 — `abletonosc/application.py`: validate the key, log the answer

Replace the `get_has_option` callback and the comment block above it (currently
headed "Options.txt queries").

- New module-level constant beside the handler, or a local — implementer's
  call, but it must not be recomputed per request in a way that obscures the
  rule. `string.hexdigits` is the natural spelling (`0-9a-fA-F`, exactly the
  measured accepted set); if `string` is imported, it joins `os` at module
  scope.
- Shape:

  ```python
  def get_has_option(params: Tuple[Any] = ()) -> Tuple:
      key = str(params[0])
      if len(key) != 64 or not all(c in string.hexdigits for c in key):
          raise ValueError("has_option expects a 64-character hexadecimal "
                           "option key, not an Options.txt option name")
      present = application.has_option(key)
      self.logger.info("AbletonOSC: has_option for application: %s = %s"
                       % (key, present))
      return key, present
  ```

  `params[0]` stays first so the no-argument `IndexError` path is untouched.
  The key is **not** case-folded before being handed to Live or echoed.
- The comment block above it is rewritten and is part of this part, not
  optional garnish. It must say: what the key is (a digest of an internal Live
  option name, sourced from Live's own code — cite the `abl.live.licensing`
  `skip_unlock_file` key as the known example), that it is **not** Options.txt,
  why the validation is here rather than passed through to Live (a C++
  exception whose text is `basic_string`), why `ValueError` specifically (it is
  a wildcard skip, and a malformed key genuinely means "this endpoint does not
  apply"), and why the answer is logged (the reply port is not always bindable;
  see `API.md` § "The no-probe variant").

### Part 2 — documentation, **same commit as Part 1**

- **`API.md`, Application API table.** Replace the `has_option` row entirely.
  The new row states: argument `key` = exactly 64 hex characters,
  case-insensitive; reply `key, present`; that it is a lookup in Live's
  internal option table and **not** an Options.txt query; that no public
  name→key mapping exists, with the `skip_unlock_file` key from
  `abl.live.licensing` given as the one known real key so a reader can try the
  address; that a malformed key gets a structured `/live/error` from the
  handler (Live is never called) and is a silent skip under a wildcard; and
  that the answer is written to `logs/abletonosc.log`. The ⚠️ "Broken as
  documented — do not use" banner goes.
- **`API.md`, the "Partially measured against Live 12.4.5 on 2026-08-29"
  block.** Replace the `has_option` bullet ("does not do what this document
  said") with the settled contract, and add the second run's evidence, dated
  and version-stamped, beside the measurements already there: the accept/reject
  table from this plan's Context (64 zeros accepted, licensing key accepted in
  both cases, 63 chars and empty → `IndexError: basic_string`, non-hex →
  `RuntimeError: Key contains non-hex characters` and hex-before-length
  ordering), and the method used (no-probe variant, marker reads between
  cases). Also update the "still unmeasured" list: `has_option`'s *returned
  boolean* remains unread on the wire, but is now readable from the log.
- **`API.md`, § "Measuring the Live API without building the feature first"
  → "The no-probe variant".** That section states "Ok-paths of the custom
  handlers (return_track getters, `browser/get/items`, `is_view_visible`) log
  **nothing**", which Part 1 makes untrue for this one address. Add the
  exception in the same commit, naming `has_option` as a custom handler whose
  ok path *does* log its answer. A future measurement run reads that bullet to
  decide whether an address is readable at all — leaving it stale reproduces
  the exact failure this item exists to fix.
- **`SESHAT.md`, § "Additions to upstream's code", the `application.py`
  entry.** Replace the ⚠️ `get/has_option` bullet with the real contract and
  the fork's divergence: handler-side validation of a 64-hex key, `ValueError`
  chosen so a wildcard sweep skips rather than errors, and an ok-path log line
  where the rest of the custom application getters log nothing. Note in one
  clause that the address was kept rather than removed, and why (coverage
  doctrine + it answers for a well-formed key) — that is the decision a future
  merge or audit will want to find.
- **`ROADMAP.md`** — no edit in the implementation commit beyond what
  `/plan` already added (the `**Plan:**` link). The entry is removed by
  `/ship`.
- **`FORK_GAPS.md` — deliberately untouched.** `Application.has_option` stays
  an exposed member; the generated inventory's `Live.Application.Application`
  block ("21 members, 19 exposed, 2 gaps") stays correct, and **no inventory
  regeneration is required by this change**. A reviewer should verify that
  claim by confirming no `add_handler` address string changes anywhere in the
  diff.
- **`README.md` — untouched.** Its tables are upstream's; `has_option` is not
  in them.

### Part 3 — `tests_unit/test_application.py`, same commit

Rewrite the three `has_option` tests and the two docstring passages that
describe the address as an Options.txt query. Detail in Testing below.

## Testing (`tests_unit/`, the only gate)

`python3 -m pytest tests_unit/` is the Live-free gate; `tests/` mutates a
running Live and is not part of it. Everything below drives the real
`ApplicationHandler` through `conftest.py`'s `dispatch` fixture, with
`FakeApplication` substituted at the `get_application()` seam.

Tests to change or add in `tests_unit/test_application.py`:

1. **`test_has_option_echoes_the_option_it_was_asked_about`** — rename to speak
   of a key. Seed `FakeApplication(options=("a"*64,))`; assert
   `dispatch(..., "a"*64)` replies `("a"*64, True)` and a different valid
   64-hex key replies `(..., False)`. The echo is still the point.
2. **`test_has_option_passes_the_key_to_live_unmodified`** — assert
   `application.has_option_calls == [key]` for a mixed-case key, pinning that
   the handler neither case-folds nor otherwise rewrites it (Live accepts both
   cases; the echo must match what the client sent).
3. **New `test_has_option_rejects_a_malformed_key`** — parametrised over 63
   hex chars, 65 hex chars, `""`, `"z"*64`, and `"-_EnableExtendedFileFormat"`.
   Each must produce exactly one message, on `/live/error`, with
   `params[0] == "request"`, `params[1]` the address, a non-empty `params[2]`
   mentioning 64 and hexadecimal, `params[3] == 1`, and `params[4]` the
   argument sent. **And `application.has_option_calls == []`** — that is the
   assertion that proves validation happens before Live is reached, which is
   the whole substance of the fix and is not visible from the reply alone.
4. **`test_has_option_with_no_argument_is_a_structured_error`** — keep as is
   (`params[3] == 0`); it pins that validation did not move ahead of
   `params[0]`.
5. **New `test_has_option_is_skipped_by_a_wildcard_sweep`** — dispatch
   `/live/application/get/*` with one non-key string argument; assert no
   message on `/live/error` and no message on
   `/live/application/get/has_option`, while the sweep's other replies still
   arrive. This pins the `ValueError`-as-wildcard-skip choice, which is
   invisible in direct dispatch and is a real behaviour change from today.
6. **Docstrings.** The module docstring's "what `has_option` actually matches"
   (listed under "what no test here can reach") is now known — replace with the
   one thing still out of reach: whether any given key is present in a
   particular Live installation. The `# Options.txt.` comment in
   `REGISTERED_ADDRESSES` becomes something like `# The 64-hex option-key
   lookup.`

What `tests_unit/` cannot cover, and the plan says so plainly: whether Live
accepts a key this validator accepts. `FakeApplication.has_option` is a set
membership test on whatever string it is handed — it models the fork's contract,
not Live's C++ one. The evidence that the validator matches Live is the
measurement table in Context, and the re-check in Live verification below.

## Live verification

**Precondition shared by every check:** the Remote Scripts copy at
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/` equals this checkout
byte for byte, and the running Live has the new `application.py` *in memory*.
This change adds no new module and `abletonosc.application` is on
`manager.reload_imports`' list, so `/live/api/reload` is sufficient here rather
than a Live restart — with `API.md`'s standing warning that a failed reload can
leave the script with zero handlers until Live is restarted. Files on disk are
not code in memory either way.

Method: `API.md` § "The no-probe variant" — send from a plain UDP socket to
`127.0.0.1:11000`, read new bytes of `logs/abletonosc.log` after each send,
interleave `/live/application/get/open_dialog_count` between cases as a marker
so each line correlates to one send. Every check below is a **read**; nothing
mutates the set, so no `begin_undo_step` wrapper is needed. Do not bind 11001.

| # | Send | Evidence that decides it |
|---|---|---|
| 1 | `has_option "0"*64` | One new log line `has_option for application: 000… = False` (or `True`), and **no** `[ERROR]` line. Proves a well-formed key still reaches Live after validation, and that the new ok-path log works |
| 2 | `has_option fbb8b6e2603b931b8fc884f09e56c4d9391d78105cbf2c711c9a22e0fb7152fd` | One log line ending `= True` or `= False`. Either answer passes; **record which** in `API.md` beside the key, since it is the first observed value this address has ever returned |
| 3 | same key, upper case | One log line, no `[ERROR]`, and the key echoed in the log in **upper** case. Proves the validator accepts `A-F` and does not case-fold |
| 4 | `has_option "-_EnableExtendedFileFormat"` | One `[ERROR]` line whose detail is the handler's own message naming the 64-hex requirement, and a traceback raised in `get_has_option` — **not** in `application.has_option`. That last distinction is the proof Live was never called |
| 5 | `has_option "0"*63` | Same as #4: the handler's message, not `IndexError: basic_string` |
| 6 | `/live/application/get/* "notakey"` | The other application getters log/answer as normal and there is **no** `[ERROR]` line for `has_option`. Proves the `ValueError` skip. (Today this send produces `RuntimeError: Key contains non-hex characters`.) Only the five generic-loop getters log on their ok path, so "as normal" is read off those; the missing `has_option` error is the decisive part. This sweep also emits one reply datagram per matching getter (~15) to the response port — run it under the same "Seshat not running, keep the volume low" caution as the rest of the run |
| 7 | `has_option` with no arguments | One `[ERROR]` line with an `IndexError` from `params[0]`, unchanged from today |

**Uncovered, and why.** The reply *datagram* — that `(key, present)` actually
reaches a client with `present` as an OSC boolean — needs a listener on 11001,
which this work may not bind. The reply shape is pinned Live-free by
`tests_unit/`, and the value now appears in the log, so what remains unverified
is only the encoding of a bool by `pythonosc`'s builder, which every other
boolean-valued getter in this fork already exercises. Also uncovered: whether
any key other than the licensing one exists in this installation — there is no
enumeration API (`non_api_add_option` / `non_api_remove_option` are not exposed
to scripts), so "which options exist" is unanswerable from a Remote Script by
construction, not by omission.

### Results — checks 1-7 **skipped by environment** (`/pr-review`, 2026-08-29)

The shared precondition fails. Live 12.4.5 is running (PID 83844), but the
installed copy is **not** this checkout:

```
diff -rq --exclude=__pycache__ abletonosc \
  "$HOME/Music/Ableton/User Library/Remote Scripts/AbletonOSC/abletonosc"
Files .../abletonosc/application.py and .../AbletonOSC/abletonosc/application.py differ
```

The installed `application.py` is byte-identical to `fe6730e`, this branch's
base — the pre-change handler, with no `HAS_OPTION_KEY_LENGTH` and no
validation. Installing it, reloading and restarting Live are all out of bounds
for a review, so nothing on the wire or in `logs/abletonosc.log` can say
anything about the code under review; a run against the installed copy would
be measuring the defect this branch fixes.

| # | Send | Result | Missing |
|---|---|---|---|
| 1 | `has_option "0"*64` | skipped by environment | installed copy is the pre-change code (`fe6730e`) |
| 2 | `has_option <licensing key>` | skipped by environment | as above — **Open question 1 stays open**; no value recorded for the licensing key |
| 3 | same key, upper case | skipped by environment | as above |
| 4 | `has_option "-_EnableExtendedFileFormat"` | skipped by environment | as above |
| 5 | `has_option "0"*63` | skipped by environment | as above |
| 6 | `/live/application/get/* "notakey"` | skipped by environment | as above |
| 7 | `has_option` with no arguments | skipped by environment | as above |

What *was* verified without Live: `python3 -m pytest tests_unit/` — **791
passed**, including the five-case malformed-key rejection with
`has_option_calls == []` and the wildcard-skip case. Checks 1-7 remain the
outstanding evidence that the fork's validator matches Live's, and they are
runnable by whoever next installs and reloads: the ok-path log line the greps
in checks 1-3 read is `has_option for application: <key> = <bool>`, which is
what `application.py:183` emits.

## Downstream

**Pin bump only.** Verified, not assumed:

- `grep -rn "/live/application" /Users/patrick/seshat/lib /Users/patrick/seshat/test` returns
  **nothing** — Seshat's Elixir sends no address in this family at all, wildcard
  or literal. The only `has_option` hits in Seshat are inside the vendored
  submodule copy at `priv/AbletonOSC/`.
- `test/seshat/osc/vendored_addresses_test.exs` checks (a) every vendored
  address the Elixir code sends is registered in Python and (b) every address
  Python registers appears in the canonical address docs. This change
  registers and documents the same address string it does today, so both
  directions still hold and no new tripwire entry is needed. Direction (b) is a
  **literal-string scan**: the test reads
  `priv/AbletonOSC/abletonosc/application.py` for registered address literals
  and requires each to appear in `priv/AbletonOSC/API.md`. The rewritten
  `API.md` row must therefore keep the literal
  `/live/application/get/has_option` in the Application table — a row rewritten
  into prose that drops the address string breaks Seshat's suite at the next
  pin bump, and it breaks there rather than here.
- No reply shape, arity, address name or listener push changes. The only
  observable differences to a client are the *text* of the error for a
  malformed key and the disappearance of one error datagram from a wildcard
  sweep — neither reachable from Seshat's current code.

Seshat's action: bump the submodule pin, `mix abletonosc.install`, restart Live.

## Out of scope

- **Deleting the address.** Weighed and declined above; if a future audit
  disagrees, it is a five-line PR plus a `FORK_GAPS.md` Declined entry and an
  inventory regeneration, and it needs an argument that overrides the coverage
  doctrine rather than a preference.
- **Deriving keys from option names.** No public mapping exists and the digest
  is not a plain SHA-256 of the guarded identifier. Nothing in this plan
  hashes anything; the caller supplies the key.
- **Exposing `non_api_add_option` / `non_api_remove_option`.** They are not on
  the LOM surface `dump_lom` walks and are marked non-API by Ableton. Not a
  fork gap.
- **The other ⚠️ markers in the Application section** — `get/variant`'s exact
  strings, `unavailable_features` element types, `control_surfaces` empty-slot
  representation, whether `show_message` blocks. All need a reply port or a
  logging patch of their own; they stay marked. (An implementer who finds the
  ok-path logging of Part 1 cheap may be tempted to log those too — don't:
  that is address surface this item did not review, and log growth is its own
  roadmap item, "Add bounded log retention".)
- **`ROADMAP.md` entry removal and plan archival** — `/ship`'s job.

## Open questions

1. **What the licensing key's answer is on this installation.** Not knowable
   without either the log line this plan adds or a free reply port, so it is
   answered by Live verification check #2 rather than at planning time.
   Meanwhile the plan assumes nothing about it: both `True` and `False` are
   passing outcomes, and the contract is the same either way.
2. **Whether Live's 64-hex requirement is version-stable.** Measured on 12.4.5
   only. Live's `has_option` is a C++ builtin with no docstring in the apiref,
   so there is no version history to read. The plan assumes it is stable and
   the validator's message names the requirement rather than a Live version;
   if a later Live widens it, the symptom is a rejected key that Live would
   have accepted, which is a loud, correctable failure rather than a silent
   one. ⚠️
3. **Whether any caller will ever have a key.** Genuinely unknown — it depends
   on whether a consumer ever needs to probe an internal Live flag, and the
   only key we can name comes from Live's licensing code. The plan does not
   assume one will: it keeps the address because the surface exists and
   answers, not because a use case is identified, which is exactly the
   `FORK_GAPS.md` doctrine. This is the question a reviewer who prefers
   deletion should attack.
