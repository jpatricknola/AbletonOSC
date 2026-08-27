import os
import sys
import time

#--------------------------------------------------------------------------------
# Put the repository root on sys.path so that `client` and the vendored
# `pythonosc` it imports both resolve. Derived from __file__ rather than the
# process's working directory: pytest may be invoked from anywhere, and the old
# `sys.path.append(".")` silently produced an ImportError from any other cwd.
#
# This lives here rather than in conftest.py deliberately: pytest imports
# tests/conftest.py as a submodule of the `tests` package, so this __init__ --
# and the client import below, which pulls in pythonosc -- runs first.
#
# The import is absolute for the same reason. Upstream's `from ..client import`
# resolves only when the checkout directory is itself an importable package,
# which pytest requires to be a valid Python identifier; this fork's working
# copy is `ableton-osc`, so the relative form raises "attempted relative import
# beyond top-level package" before any test runs. run-console.py already
# imports the client this way.
#--------------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from client import AbletonOSCClient, TICK_DURATION

#--------------------------------------------------------------------------------
# NOTHING IN THIS MODULE MAY TOUCH THE NETWORK.
#
# This package is the opt-in live-integration suite: every test in it needs a
# running Ableton Live with AbletonOSC loaded, and mutates the open set.
# Importing it -- which `pytest --collect-only` from the repository root used
# to do -- must therefore be completely inert. Upstream constructed an
# AbletonOSCClient at module scope here and sent /live/api/reload, so mere
# collection reloaded the bridge under a live session and bound the reply port.
#
# The client now lives in a session-scoped fixture in conftest.py, gated on
# ABLETONOSC_LIVE_TESTS=1. tests_unit/test_live_suite_inert.py fails if any
# module in this package regains module-scope client construction or sends.
#--------------------------------------------------------------------------------

def wait_one_tick():
    """
    Sleep for one Ableton Live tick (100ms).
    """
    time.sleep(TICK_DURATION)
