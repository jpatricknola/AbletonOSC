# Contributing

## Tests

There are two test suites, with deliberately different characters.

Both need only pytest:

```
pip3 install -r requirements-dev.txt
```

### `tests_unit/` — the default, Live-free gate

Drives the real dispatcher, handler base class and track callbacks without
Ableton Live: no sockets, no fixed ports, nothing that can touch a running
session. Run it before every commit, and on every merge from upstream:

```
python3 -m pytest tests_unit/
```

Bare `pytest` from the repository root runs this suite and only this suite
(`pytest.ini` sets `testpaths`). CI runs it on every push and pull request.

### `tests/` — the opt-in live-integration suite

Sends real OSC to a real Live and **mutates the set that is open**. It is inert
unless you ask for it:

```
ABLETONOSC_LIVE_TESTS=1 python3 -m pytest tests/
```

Without `ABLETONOSC_LIVE_TESTS=1` every test skips and nothing is sent, so
collecting it is harmless.

Preconditions — anything unmet makes tests skip, not fail:

- Ableton Live is running with AbletonOSC installed in its Remote Scripts
  directory. Files on disk are not code in memory: after copying, restart Live
  or send `/live/api/reload` (the suite sends it once per session).
- The OSC reply port **11001 is free**. AbletonOSC replies there
  unconditionally, so anything else holding it — another client, or Seshat's
  own e2e suite — makes the whole suite skip rather than run half-deaf.
- A set you are willing to have mutated. The tests create and delete tracks,
  scenes and clips, and set properties. They discover the set's shape rather
  than assuming the blank default template, and restore what they change, but
  a scratch set is still the right thing to point them at.
- For the three audio-clip tests only: a configured default audio input
  device, and `Preferences > Record, Warp & Launch > Count-In` set to `None`.
  Without them the recording fixture skips those three tests.

## Live reloading

AbletonOSC supports dynamic reloading of the handler code modules so that it's not necessary to restart Live each time the code is modified.

To reload the codebase, send an OSC message to `/live/api/reload`.

## Logging

Logging can be performed from any of the AbletonOSCHandler classes via the `self.logger` property.

AbletonOSC logs internal events to `logs/abletonosc.log` relative to the AbletonOSC directory.

## Debugging compile-time issues

To view the Live boot log:

```
LOG_DIR="$HOME/Library/Application Support/Ableton/Live Reports/Usage"
LOG_FILE=$(ls -atr "$LOG_DIR"/*.log | tail -1)
echo "Log path: $LOG_FILE"
tail -5000f "$LOG_FILE" | grep AbletonOSC
```
