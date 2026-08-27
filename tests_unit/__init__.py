#--------------------------------------------------------------------------------
# Live-free unit tests for the OSC dispatcher.
#
# The repository has two permanent test trees, and this is the default one:
#
#   tests_unit/  this package - the Live-free regression gate. Runs anywhere,
#                needs nothing but pytest, sends no datagrams, binds no port,
#                and never imports tests/. `pytest` with no arguments collects
#                only this tree (see pytest.ini), and CI runs it on every push.
#
#   tests/       the opt-in live-integration suite, which needs a running
#                Ableton Live with AbletonOSC installed and mutates the open
#                set. Gated on ABLETONOSC_LIVE_TESTS=1; inert without it.
#                test_live_suite_inert.py here is the tripwire that keeps it
#                inert at import time.
#
# Run with:  python3 -m pytest tests_unit/
# pytest is the only dependency beyond the standard library; see
# requirements-dev.txt. Last verified with CPython 3.12.7
# (/opt/anaconda3/bin/python3) and pytest 7.4.4.
#--------------------------------------------------------------------------------
