from . import wait_one_tick, TICK_DURATION
from .conftest import (require, restored_song_property, find_tracks,
                       _find_empty_slot, _delete_clip_if_present)

#--------------------------------------------------------------------------------
# Test song start/stop
#--------------------------------------------------------------------------------

def test_song_play(client):
    client.send_message("/live/song/start_playing")
    wait_one_tick()
    assert client.query("/live/song/get/is_playing") == (True,)

    client.send_message("/live/song/stop_playing")
    wait_one_tick()
    assert client.query("/live/song/get/is_playing") == (False,)

def test_song_beat(client):
    client.send_message("/live/song/stop_playing")
    client.send_message("/live/song/start_listen/beat")
    try:
        client.send_message("/live/song/start_playing")
        wait_one_tick()
        wait_one_tick()
        assert client.await_message("/live/song/get/beat", timeout=1.0) == (1,)
        assert client.await_message("/live/song/get/beat", timeout=1.0) == (2,)
        client.send_message("/live/song/stop_playing")
        wait_one_tick()
        client.send_message("/live/song/continue_playing")
        assert client.await_message("/live/song/get/beat", timeout=1.0) == (3,)
    finally:
        #--------------------------------------------------------------------------------
        # Stop transport and listener even when an assertion above fails: a leaked
        # beat listener pushes to the reply port for the rest of the Live session.
        #--------------------------------------------------------------------------------
        client.send_message("/live/song/stop_playing")
        client.send_message("/live/song/stop_listen/beat")
        wait_one_tick()

def test_song_stop_all_clips(client, num_tracks, num_scenes):
    #--------------------------------------------------------------------------------
    # Fire a clip on every MIDI track we can (up to two, as upstream did) and check
    # that stop_all_clips stops all of them. Which tracks and slots those are is
    # discovered, not assumed.
    #--------------------------------------------------------------------------------
    require(num_scenes >= 1, "set has no scenes")
    tracks = find_tracks(client, "has_midi_input", num_tracks, limit=2)
    require(len(tracks) >= 1, "no MIDI track in this set")

    slots = []
    for track_id in tracks:
        scene_id = _find_empty_slot(client, track_id, num_scenes)
        if scene_id is not None:
            slots.append((track_id, scene_id))
    require(len(slots) >= 1, "no empty clip slot on any MIDI track")

    try:
        for track_id, scene_id in slots:
            client.send_message("/live/clip_slot/create_clip", (track_id, scene_id, 4))
        wait_one_tick()
        for track_id, scene_id in slots:
            client.send_message("/live/clip/fire", (track_id, scene_id))
        # Sometimes a wait >one tick is required here. Not sure why.
        wait_one_tick()
        wait_one_tick()
        for track_id, scene_id in slots:
            assert client.query("/live/clip/get/is_playing", (track_id, scene_id)) == \
                (track_id, scene_id, True,)

        client.send_message("/live/song/stop_playing")
        client.send_message("/live/song/stop_all_clips")
        wait_one_tick()
        wait_one_tick()
        for track_id, scene_id in slots:
            assert client.query("/live/clip/get/is_playing", (track_id, scene_id)) == \
                (track_id, scene_id, False,)
    finally:
        client.send_message("/live/song/stop_playing")
        client.send_message("/live/song/stop_all_clips")
        wait_one_tick()
        for track_id, scene_id in slots:
            _delete_clip_if_present(client, track_id, scene_id)

#--------------------------------------------------------------------------------
# Test song listeners
#--------------------------------------------------------------------------------

def test_song_listen_is_playing(client):
    client.send_message("/live/song/stop_playing")
    client.send_message("/live/song/start_listen/is_playing")
    try:
        assert client.await_message("/live/song/get/is_playing", TICK_DURATION * 2) == (False,)
        client.send_message("/live/song/start_playing")
        assert client.await_message("/live/song/get/is_playing", TICK_DURATION * 2) == (True,)
        client.send_message("/live/song/stop_playing")
        assert client.await_message("/live/song/get/is_playing", TICK_DURATION * 2) == (False,)
    finally:
        client.send_message("/live/song/stop_playing")
        client.send_message("/live/song/stop_listen/is_playing")

def test_song_listen_tempo(client):
    with restored_song_property(client, "tempo"):
        client.send_message("/live/song/set/tempo", [120])
        client.send_message("/live/song/start_listen/tempo")
        try:
            assert client.await_message("/live/song/get/tempo", TICK_DURATION * 2) == (120,)

            for value in [81, 120]:
                client.send_message("/live/song/set/tempo", [value])
                assert client.await_message("/live/song/get/tempo", TICK_DURATION * 2) == (value,)
        finally:
            client.send_message("/live/song/stop_listen/tempo")

#--------------------------------------------------------------------------------
# Test song properties
#--------------------------------------------------------------------------------

def _test_song_property(client, property, values):
    """
    Set and read back each of `values`, restoring the property's original value
    afterwards - including when an assertion fails part-way through, which
    otherwise strands the user's set at the last test value.
    """
    with restored_song_property(client, property):
        for value in values:
            client.send_message("/live/song/set/%s" % property, [value])
            wait_one_tick()
            assert client.query("/live/song/get/%s" % property) == (value,)

def test_song_property_arrangement_overdub(client):
    _test_song_property(client, "arrangement_overdub", [1, 0])

def test_song_property_back_to_arranger(client):
    # Can't really test back_to_arranger without making some modifications
    # in the arrangement view to reset (it's not possible to set back_to_arranger = 1)
    _test_song_property(client, "back_to_arranger", [0])

def test_song_property_clip_trigger_quantization(client):
    _test_song_property(client, "clip_trigger_quantization", [0, 4])

def test_song_property_current_song_time(client):
    _test_song_property(client, "current_song_time", [4, 1])

def test_song_property_groove_amount(client):
    _test_song_property(client, "groove_amount", [0.5, 0])

def test_song_property_loop(client):
    _test_song_property(client, "loop", [1, 0])

def test_song_property_loop_length(client):
    _test_song_property(client, "loop_length", [2, 4])

def test_song_property_loop_start(client):
    _test_song_property(client, "loop_start", [2, 1])

def test_song_property_metronome(client):
    _test_song_property(client, "metronome", [1, 0])

def test_song_property_midi_recording_quantization(client):
    _test_song_property(client, "midi_recording_quantization", [1, 0])

def test_song_property_nudge_down(client):
    _test_song_property(client, "nudge_down", [1, 0])

def test_song_property_nudge_up(client):
    _test_song_property(client, "nudge_up", [1, 0])

def test_song_property_punch_in(client):
    _test_song_property(client, "punch_in", [1, 0])

def test_song_property_punch_out(client):
    _test_song_property(client, "punch_out", [1, 0])

def test_song_property_record_mode(client):
    _test_song_property(client, "record_mode", [1, 0])
    client.send_message("/live/song/stop_playing")

def test_song_property_tempo(client):
    _test_song_property(client, "tempo", [125.5, 120])

#--------------------------------------------------------------------------------
# Test song properties - tracks
#--------------------------------------------------------------------------------

def test_song_tracks(client):
    #--------------------------------------------------------------------------------
    # Relative to whatever the set already holds: upstream asserted the blank
    # default template's 4 tracks, which made the test unrunnable on a real set.
    #--------------------------------------------------------------------------------
    baseline = client.query("/live/song/get/num_tracks")[0]
    created = False
    try:
        client.send_message("/live/song/create_midi_track", [-1])
        wait_one_tick()
        wait_one_tick()
        wait_one_tick()
        created = True
        assert client.query("/live/song/get/num_tracks") == (baseline + 1,)
    finally:
        if created:
            client.send_message("/live/song/delete_track", [baseline])
            wait_one_tick()
            wait_one_tick()
            wait_one_tick()
    assert client.query("/live/song/get/num_tracks") == (baseline,)

#--------------------------------------------------------------------------------
# Test song properties - scenes
#--------------------------------------------------------------------------------

def test_song_scenes(client):
    baseline = client.query("/live/song/get/num_scenes")[0]
    created = False
    try:
        client.send_message("/live/song/create_scene", [-1])
        wait_one_tick()
        created = True
        assert client.query("/live/song/get/num_scenes") == (baseline + 1,)
    finally:
        if created:
            client.send_message("/live/song/delete_scene", [baseline])
            wait_one_tick()
    assert client.query("/live/song/get/num_scenes") == (baseline,)

def test_song_duplicate_scene(client, midi_track):
    #--------------------------------------------------------------------------------
    # Duplicate the last scene, whichever that is, rather than assuming scene 7 is
    # the last one and is empty.
    #--------------------------------------------------------------------------------
    baseline = client.query("/live/song/get/num_scenes")[0]
    require(baseline >= 1, "set has no scenes")
    scene_id = baseline - 1
    require(not client.query("/live/clip_slot/get/has_clip", (midi_track, scene_id))[2],
            "last clip slot on the MIDI track is occupied")

    duplicated = False
    try:
        client.send_message("/live/clip_slot/create_clip", [midi_track, scene_id, 4])
        wait_one_tick()
        client.send_message("/live/song/duplicate_scene", [scene_id])
        wait_one_tick()
        duplicated = client.query("/live/song/get/num_scenes")[0] == baseline + 1
        assert duplicated
        assert client.query("/live/clip/get/is_midi_clip", (midi_track, scene_id + 1)) == \
            (midi_track, scene_id + 1, True,)
    finally:
        if duplicated:
            client.send_message("/live/song/delete_scene", [scene_id + 1])
            wait_one_tick()
        _delete_clip_if_present(client, midi_track, scene_id)

#--------------------------------------------------------------------------------
# Test song - undo/redo
#--------------------------------------------------------------------------------

def test_song_undo_redo(client):
    baseline = client.query("/live/song/get/num_scenes")[0]
    try:
        client.send_message("/live/song/create_scene", [-1])
        wait_one_tick()
        assert client.query("/live/song/get/num_scenes") == (baseline + 1,)

        wait_one_tick()
        client.send_message("/live/song/undo")
        wait_one_tick()
        assert client.query("/live/song/get/num_scenes") == (baseline,)

        client.send_message("/live/song/redo")
        wait_one_tick()
        assert client.query("/live/song/get/num_scenes") == (baseline + 1,)
    finally:
        #--------------------------------------------------------------------------------
        # Delete only what is actually there: undo/redo may have left the set at
        # either count depending on where an assertion failed.
        #--------------------------------------------------------------------------------
        if client.query("/live/song/get/num_scenes")[0] > baseline:
            client.send_message("/live/song/delete_scene", [baseline])
            wait_one_tick()
