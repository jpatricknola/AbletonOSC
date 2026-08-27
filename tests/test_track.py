from . import wait_one_tick, TICK_DURATION
from .conftest import (require, restored_track_property, restored_song_property,
                       restored_send, find_tracks,
                       _delete_clip_if_present)

#--------------------------------------------------------------------------------
# Test track properties
#--------------------------------------------------------------------------------

def _test_track_property(client, track_id, property, values):
    """
    Set and read back each of `values`, restoring the property's original value
    afterwards - including when an assertion fails part-way through.
    """
    with restored_track_property(client, track_id, property):
        for value in values:
            print("Testing property %s, value: %s" % (property, value))
            client.send_message("/live/track/set/%s" % property, [track_id, value])
            wait_one_tick()
            assert client.query("/live/track/get/%s" % property, [track_id]) == (track_id, value,)

#--------------------------------------------------------------------------------
# None of these properties are specific to a track's input type, so they're
# tested against midi_track rather than audio_track - the latter would skip
# needlessly on a MIDI-only set.
#--------------------------------------------------------------------------------

def test_track_property_panning(client, midi_track):
    _test_track_property(client, midi_track, "panning", [0.5, 0.0])

def test_track_property_volume(client, midi_track):
    _test_track_property(client, midi_track, "volume", [0.5, 1.0])

def test_track_property_color(client, midi_track):
    # Only specific colors from the color picker can be used
    _test_track_property(client, midi_track, "color", [0x001AFF2F, 0x001A2F96])

def test_track_property_mute(client, midi_track):
    _test_track_property(client, midi_track, "mute", [1, 0])

def test_track_property_solo(client, midi_track):
    _test_track_property(client, midi_track, "solo", [1, 0])

def test_track_property_name(client, midi_track):
    _test_track_property(client, midi_track, "name", ["Test", "Track"])

#--------------------------------------------------------------------------------
# Test track properties - sends
#--------------------------------------------------------------------------------

def test_track_get_send(client, audio_track, num_return_tracks):
    #--------------------------------------------------------------------------------
    # Send 1 only exists if the set has at least two return tracks; upstream
    # assumed the default template's A and B.
    #--------------------------------------------------------------------------------
    require(num_return_tracks >= 2, "set has fewer than 2 return tracks")
    send_id = 1

    with restored_send(client, audio_track, send_id):
        for value in [0.5, 0.0]:
            client.send_message("/live/track/set/send", [audio_track, send_id, value])
            wait_one_tick()
            assert client.query("/live/track/get/send", (audio_track, send_id)) == \
                (audio_track, send_id, value,)

#--------------------------------------------------------------------------------
# Test track properties - clips
#--------------------------------------------------------------------------------

def test_track_clips(client, midi_track, num_scenes):
    #--------------------------------------------------------------------------------
    # The clips/* wildcard replies with one entry per scene, so the expected tuple
    # is built from the set's scene count rather than the default template's 8.
    # The reply describes every slot on the track, so the test needs a track with
    # no other clips on it - stated as a precondition instead of assumed.
    #--------------------------------------------------------------------------------
    require(num_scenes >= 2, "set has fewer than 2 scenes")
    occupied = [scene_id for scene_id in range(num_scenes)
                if client.query("/live/clip_slot/get/has_clip", (midi_track, scene_id))[2]]
    require(not occupied,
            "MIDI track %d already holds clips in slots %s; this test needs an "
            "empty track" % (midi_track, occupied))

    try:
        client.send_message("/live/clip_slot/create_clip", (midi_track, 0, 4))
        client.send_message("/live/clip_slot/create_clip", (midi_track, 1, 2))
        client.send_message("/live/clip/set/name", (midi_track, 0, "Alpha"))
        client.send_message("/live/clip/set/name", (midi_track, 1, "Beta"))

        wait_one_tick()
        empty = (None,) * (num_scenes - 2)
        assert client.query("/live/track/get/clips/name", (midi_track,)) == \
            (midi_track, "Alpha", "Beta") + empty
        assert client.query("/live/track/get/clips/length", (midi_track,)) == \
            (midi_track, 4, 2) + empty
    finally:
        _delete_clip_if_present(client, midi_track, 0)
        _delete_clip_if_present(client, midi_track, 1)

#--------------------------------------------------------------------------------
# Test track properties - devices
#--------------------------------------------------------------------------------

def test_track_devices(client, num_tracks):
    #--------------------------------------------------------------------------------
    # Assert the reply envelope, not the count: upstream asserted 0 devices, which
    # is only true of a track in the blank default set.
    #--------------------------------------------------------------------------------
    require(num_tracks >= 1, "set has no tracks")
    track_id = 0
    rv = client.query("/live/track/get/num_devices", (track_id,))
    assert len(rv) == 2
    assert rv[0] == track_id
    assert isinstance(rv[1], int) and rv[1] >= 0

#--------------------------------------------------------------------------------
# Test track properties - listeners
#--------------------------------------------------------------------------------

def test_track_listen_playing_slot_index(client, num_tracks, num_scenes):
    tracks = find_tracks(client, "has_midi_input", num_tracks, limit=2)
    require(len(tracks) >= 2, "set has fewer than 2 MIDI tracks")
    require(num_scenes >= 2, "set has fewer than 2 scenes")

    slots = []
    for track_id in tracks:
        free = [scene_id for scene_id in range(num_scenes)
                if not client.query("/live/clip_slot/get/has_clip", (track_id, scene_id))[2]]
        require(len(free) >= 2, "fewer than 2 empty clip slots on track %d" % track_id)
        slots.append((track_id, free[0], free[1]))

    (track_a, a0, a1), (track_b, b0, b1) = slots
    created = []
    listening = []

    #--------------------------------------------------------------------------------
    # 1/16th quantize, so that fired clips start within a tick. Restored afterwards:
    # upstream left the set quantized to 1/16 for good.
    #--------------------------------------------------------------------------------
    with restored_song_property(client, "clip_trigger_quantization"):
        client.send_message("/live/song/set/clip_trigger_quantization", (11,))
        try:
            for track_id, first, second in slots:
                for scene_id in (first, second):
                    client.send_message("/live/clip_slot/create_clip", (track_id, scene_id, 4))
                    created.append((track_id, scene_id))
            wait_one_tick()

            client.send_message("/live/track/start_listen/playing_slot_index", (track_a,))
            listening.append(track_a)
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_a, -1,)
            client.send_message("/live/track/start_listen/playing_slot_index", (track_b,))
            listening.append(track_b)
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_b, -1,)

            client.send_message("/live/clip_slot/fire", (track_a, a0))
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_a, a0,)

            client.send_message("/live/clip_slot/fire", (track_a, a1))
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_a, a1,)

            client.send_message("/live/clip_slot/fire", (track_b, b1))
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_b, b1,)

            client.send_message("/live/clip_slot/fire", (track_b, b0))
            assert client.await_message("/live/track/get/playing_slot_index", TICK_DURATION * 2) == (track_b, b0,)
        finally:
            #--------------------------------------------------------------------------------
            # Stop both listeners and delete the created clips even when an assertion
            # above fails: a leaked listener survives until the next /live/api/reload.
            #--------------------------------------------------------------------------------
            for track_id in listening:
                client.send_message("/live/track/stop_listen/playing_slot_index", (track_id,))
            client.send_message("/live/song/stop_playing")
            client.send_message("/live/song/stop_all_clips")
            wait_one_tick()
            for track_id, scene_id in created:
                _delete_clip_if_present(client, track_id, scene_id)
