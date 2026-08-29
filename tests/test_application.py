import threading

from . import TICK_DURATION
from .conftest import require

#--------------------------------------------------------------------------------
# Test generic application features
#--------------------------------------------------------------------------------

def capture_after_send(client, address, send, timeout=TICK_DURATION):
    """
    Install a capture handler for `address` *before* calling `send`, so a
    reply that arrives faster than a subsequent await_message() could
    subscribe is not lost.
    """
    rv = None
    _event = threading.Event()

    def received_response(address, params):
        nonlocal rv
        rv = params
        _event.set()

    client.set_handler(address, received_response)
    try:
        send()
        if not _event.wait(timeout):
            raise RuntimeError("No response received on: %s" % address)
    finally:
        client.remove_handler(address)
    return rv

def test_application_test(client):
    assert client.query("/live/test")

def test_application_get_version(client):
    rv = client.query("/live/application/get/version")
    assert len(rv) == 2 and rv[0] in (11, 12)

def test_application_get_version_string(client):
    #--------------------------------------------------------------------------------
    # The fork's exact-version read. Asserts the shape rather than a literal,
    # so it does not re-stale on every Live point release: "12.4.3" and the
    # major half agreeing with get/version is all that can be known here.
    #--------------------------------------------------------------------------------
    rv = client.query("/live/application/get/version_string")
    assert len(rv) == 1
    version_string = rv[0]
    assert isinstance(version_string, str) and len(version_string) > 0

    major, _minor = client.query("/live/application/get/version")
    assert version_string.split(".")[0] == str(major)


def test_application_get_open_dialog_count(client):
    #--------------------------------------------------------------------------------
    # Read-only, and deliberately not paired with a show_message test: this
    # suite must never raise a dialog it cannot dismiss, and there is no
    # press_current_dialog_button address by design.
    #
    # Asserting exactly 0 would assume a modal Live dialog blocks the tick
    # loop this client is talking to, so the query would time out rather than
    # reach here if one were open. That assumption is unverified — it is
    # docs/archive/PLAN_application_dialogs_and_versions.md's Open question 3, and
    # Live verification for this item was skipped by environment (see the
    # plan's "Live verification" section). If dialogs are queued and
    # asynchronous instead, a stray dialog left open by something else in the
    # set makes an exact-0 assertion flake here rather than time out, so
    # assert only the reply's shape until that question is settled.
    #--------------------------------------------------------------------------------
    rv = client.query("/live/application/get/open_dialog_count")
    assert isinstance(rv[0], int)


def test_application_error(client, num_tracks, num_scenes):
    #--------------------------------------------------------------------------------
    # A deliberately out-of-range clip index, derived from the set rather than
    # assumed: the reply under test is the structured /live/error envelope, and
    # the request itself is read-only.
    #--------------------------------------------------------------------------------
    require(num_tracks >= 1, "set has no tracks")
    bad_scene_id = num_scenes + 1

    response = capture_after_send(
        client, "/live/error",
        lambda: client.send_message("/live/clip/get/color", (0, bad_scene_id)))
    assert response[0] == "request"
    assert response[1] == "/live/clip/get/color"
    # The human-readable detail: assert presence, not exact wording, so the
    # test does not re-stale when messages improve.
    assert isinstance(response[2], str) and len(response[2]) > 0
    assert response[3] == 2
    assert response[4:] == (0, bad_scene_id)
