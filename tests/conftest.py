#--------------------------------------------------------------------------------
# Shared harness for the opt-in live-integration suite.
#
# Everything in tests/ reaches the network through the `client` fixture below,
# and the fixture refuses to exist unless ABLETONOSC_LIVE_TESTS=1 is set. That
# single gate is what makes importing and collecting this package inert: with
# the variable unset, `pytest tests/` skips every test without sending a byte,
# which is safe to run against a live session.
#
# The rest of this file exists so that the tests discover the set they are
# given instead of assuming upstream's blank default template (4 tracks, 8
# scenes, no clips, no devices), and so that a failing assertion cannot strand
# the user's set at a test value.
#--------------------------------------------------------------------------------

import os
import contextlib

import pytest

from . import AbletonOSCClient, TICK_DURATION, wait_one_tick

LIVE_TESTS_ENV_VAR = "ABLETONOSC_LIVE_TESTS"
REPLY_PORT = 11001

#--------------------------------------------------------------------------------
# Live answers on the tick after a datagram arrives, and /live/api/reload tears
# the server down and rebinds, so the post-reload probe needs a budget of many
# ticks rather than one.
#--------------------------------------------------------------------------------
LIVENESS_TIMEOUT = TICK_DURATION * 10
RELOAD_ATTEMPTS = 10

SKIP_NOT_OPTED_IN = (
    "live-integration suite is opt-in: set %s=1 to run it. It needs Ableton "
    "Live running with the *installed* copy of AbletonOSC loaded, a set you "
    "are willing to have mutated, and reply port %d free." % (LIVE_TESTS_ENV_VAR, REPLY_PORT)
)

SKIP_PORT_BUSY = (
    "reply port %d is in use, so no reply can be received - stop whatever "
    "holds it and retry. Seshat's e2e suite owns this port whenever Seshat is "
    "running; that collision is deliberate, it stops this suite from stealing "
    "Seshat's listeners. (%%s)" % REPLY_PORT
)

SKIP_NO_LIVE = (
    "no reply to /live/test: Ableton Live is not running, or AbletonOSC is "
    "not installed in its Remote Scripts directory, or Live has not been "
    "restarted since it was installed."
)


def _probe_live(client, attempts=1):
    """
    Return True if AbletonOSC answers /live/test within `attempts` tries.
    """
    for _ in range(attempts):
        try:
            if client.query("/live/test", timeout=LIVENESS_TIMEOUT):
                return True
        except RuntimeError:
            pass
    return False


@pytest.fixture(scope="session")
def client() -> AbletonOSCClient:
    if os.environ.get(LIVE_TESTS_ENV_VAR) != "1":
        pytest.skip(SKIP_NOT_OPTED_IN)

    try:
        osc_client = AbletonOSCClient()
    except OSError as exc:
        #--------------------------------------------------------------------------------
        # AbletonOSC replies to 127.0.0.1:11001 unconditionally, so a client that
        # cannot bind that port cannot hear anything. Skip rather than error: a
        # busy port is an environment fact, not a defect in the code under test.
        #--------------------------------------------------------------------------------
        pytest.skip(SKIP_PORT_BUSY % exc)

    try:
        if not _probe_live(osc_client):
            pytest.skip(SKIP_NO_LIVE)

        #--------------------------------------------------------------------------------
        # Reload once per opted-in session, from here rather than at import time,
        # so that the handler modules under test are the ones on disk. The reload
        # rebinds the server, so wait for it to answer again before yielding.
        #--------------------------------------------------------------------------------
        osc_client.send_message("/live/api/reload")
        if not _probe_live(osc_client, attempts=RELOAD_ATTEMPTS):
            pytest.skip("AbletonOSC did not answer /live/test after /live/api/reload")

        yield osc_client
    finally:
        osc_client.stop()


#--------------------------------------------------------------------------------
# Set discovery. These replace the hard-coded blank-set shape upstream assumed.
#--------------------------------------------------------------------------------

@pytest.fixture(scope="session")
def num_tracks(client) -> int:
    return client.query("/live/song/get/num_tracks")[0]


@pytest.fixture(scope="session")
def num_scenes(client) -> int:
    return client.query("/live/song/get/num_scenes")[0]


@pytest.fixture(scope="session")
def num_return_tracks(client) -> int:
    return client.query("/live/return_track/get/count")[0]


def require(condition, reason):
    """
    State a test's precondition on the set. Skips instead of failing when the
    set does not meet it - these tests run against whatever the user has open.
    """
    if not condition:
        pytest.skip(reason)


#--------------------------------------------------------------------------------
# Self-restoration. Each of these reads the current value before yielding and
# writes it back in `finally`, so an assertion failure inside the block leaves
# the set as it was found rather than at the last test value.
#--------------------------------------------------------------------------------

@contextlib.contextmanager
def restored_song_property(client, name):
    original = client.query("/live/song/get/%s" % name)[0]
    try:
        yield original
    finally:
        client.send_message("/live/song/set/%s" % name, [original])
        wait_one_tick()


@contextlib.contextmanager
def restored_track_property(client, track_id, name):
    original = client.query("/live/track/get/%s" % name, [track_id])[1]
    try:
        yield original
    finally:
        client.send_message("/live/track/set/%s" % name, [track_id, original])
        wait_one_tick()


@contextlib.contextmanager
def restored_clip_property(client, track_id, clip_id, name):
    original = client.query("/live/clip/get/%s" % name, (track_id, clip_id))[2]
    try:
        yield original
    finally:
        client.send_message("/live/clip/set/%s" % name, (track_id, clip_id, original))
        wait_one_tick()


@contextlib.contextmanager
def restored_send(client, track_id, send_id):
    original = client.query("/live/track/get/send", (track_id, send_id))[2]
    try:
        yield original
    finally:
        client.send_message("/live/track/set/send", (track_id, send_id, original))
        wait_one_tick()


@contextlib.contextmanager
def restored_view_selection(client):
    """
    Snapshot and restore the session view's selected track and scene.
    selected_clip is not restored: it isn't queried or reset here at all.
    """
    scene = client.query("/live/view/get/selected_scene")[0]
    track = client.query("/live/view/get/selected_track")[0]
    try:
        yield (track, scene)
    finally:
        client.send_message("/live/view/set/selected_track", (track,))
        client.send_message("/live/view/set/selected_scene", (scene,))
        wait_one_tick()


#--------------------------------------------------------------------------------
# Clip fixtures. Upstream created a MIDI clip and recorded a snippet of audio in
# one module-scoped autouse fixture, which made every clip test depend on a
# working audio input. These split the two, discover the tracks and slots to use
# rather than hard-coding 0 and 2, and clean up in teardown.
#--------------------------------------------------------------------------------

def find_tracks(client, prop, num_tracks, limit=None):
    """
    Indices of the tracks whose read-only property `prop` is true, e.g.
    has_midi_input. `limit` stops the scan early once enough are found.
    """
    found = []
    for track_id in range(num_tracks):
        if client.query("/live/track/get/%s" % prop, (track_id,))[1]:
            found.append(track_id)
            if limit is not None and len(found) >= limit:
                break
    return found


def _find_track(client, prop, num_tracks):
    found = find_tracks(client, prop, num_tracks, limit=1)
    return found[0] if found else None


def _find_empty_slot(client, track_id, num_scenes, exclude=()):
    for scene_id in range(num_scenes):
        if scene_id in exclude:
            continue
        if not client.query("/live/clip_slot/get/has_clip", (track_id, scene_id))[2]:
            return scene_id
    return None


def _delete_clip_if_present(client, track_id, scene_id):
    try:
        has_clip = client.query("/live/clip_slot/get/has_clip", (track_id, scene_id))[2]
    except RuntimeError:
        return
    if has_clip:
        client.send_message("/live/clip_slot/delete_clip", (track_id, scene_id))
        wait_one_tick()


@pytest.fixture(scope="session")
def midi_track(client, num_tracks) -> int:
    track_id = _find_track(client, "has_midi_input", num_tracks)
    require(track_id is not None, "no MIDI track in this set")
    return track_id


@pytest.fixture(scope="session")
def audio_track(client, num_tracks) -> int:
    track_id = _find_track(client, "has_audio_input", num_tracks)
    require(track_id is not None, "no audio track in this set")
    return track_id


@pytest.fixture
def empty_midi_slot(client, midi_track, num_scenes):
    """
    An empty clip slot on a MIDI track, as (track_id, scene_id). Anything left
    in the slot is deleted in teardown, whether this test created it or not.
    """
    scene_id = _find_empty_slot(client, midi_track, num_scenes)
    require(scene_id is not None, "no empty clip slot on the MIDI track")
    try:
        yield (midi_track, scene_id)
    finally:
        _delete_clip_if_present(client, midi_track, scene_id)


@pytest.fixture
def midi_clip(client, empty_midi_slot):
    """
    A freshly created, empty 8-beat MIDI clip, as (track_id, clip_id).
    """
    track_id, clip_id = empty_midi_slot
    client.send_message("/live/clip_slot/create_clip", [track_id, clip_id, 8.0])
    wait_one_tick()
    require(client.query("/live/clip_slot/get/has_clip", (track_id, clip_id))[2],
            "could not create a MIDI clip on track %d, slot %d" % (track_id, clip_id))
    yield (track_id, clip_id)


@pytest.fixture(scope="session")
def audio_clip(client, audio_track, num_scenes):
    """
    A short recorded audio clip, as (track_id, clip_id).

    Whether arming an audio track and firing an empty slot actually records
    depends on the user's audio input device and their Count-In preference, so
    this verifies the clip exists afterwards and skips - rather than failing
    the dependent tests with an unrelated-looking error - when it does not.
    """
    scene_id = _find_empty_slot(client, audio_track, num_scenes)
    require(scene_id is not None, "no empty clip slot on the audio track")

    armed = client.query("/live/track/get/arm", (audio_track,))[1]
    try:
        client.send_message("/live/track/set/arm", [audio_track, True])
        client.send_message("/live/clip_slot/fire", [audio_track, scene_id])
        wait_one_tick()
        client.send_message("/live/song/stop_playing")
        client.send_message("/live/song/stop_all_clips")
        wait_one_tick()
    finally:
        client.send_message("/live/track/set/arm", [audio_track, armed])
        wait_one_tick()

    recorded = client.query("/live/clip_slot/get/has_clip", (audio_track, scene_id))[2]
    if not recorded:
        pytest.skip("audio recording did not produce a clip on track %d, slot %d - "
                    "check that a default audio input device is set and that "
                    "Preferences > Record, Warp & Launch > Count-In is None"
                    % (audio_track, scene_id))

    try:
        yield (audio_track, scene_id)
    finally:
        _delete_clip_if_present(client, audio_track, scene_id)
