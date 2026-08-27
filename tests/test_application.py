import threading

from . import wait_one_tick, TICK_DURATION
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
