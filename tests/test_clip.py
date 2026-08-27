import random

from . import wait_one_tick, TICK_DURATION
from .conftest import restored_clip_property, restored_song_property

#--------------------------------------------------------------------------------
# Clip tests take their clip from a fixture (see conftest.py). Upstream created
# one MIDI clip *and* recorded a snippet of audio in a single module-scoped
# autouse fixture, which made every test here - including the MIDI-only ones -
# depend on a configured audio input device. Only the three tests that need an
# audio clip request `audio_clip` now, and that fixture skips rather than fails
# when the recording does not happen.
#--------------------------------------------------------------------------------

#--------------------------------------------------------------------------------
# Test clip properties
#--------------------------------------------------------------------------------

def _test_clip_property(client, track_id, clip_id, property, values):
    with restored_clip_property(client, track_id, clip_id, property):
        for value in values:
            client.send_message("/live/clip/set/%s" % property, (track_id, clip_id, value))
            wait_one_tick()
            assert client.query("/live/clip/get/%s" % property, (track_id, clip_id)) == \
                (track_id, clip_id, value,)

def test_clip_property_name(client, midi_clip):
    _test_clip_property(client, *midi_clip, "name", ("Alpha", "Beta"))

def test_clip_property_color(client, midi_clip):
    _test_clip_property(client, *midi_clip, "color", (0x001AFF2F, 0x001A2F96))

def test_clip_property_gain(client, audio_clip):
    _test_clip_property(client, *audio_clip, "gain", (0.5, 1.0))

def test_clip_property_pitch_coarse(client, audio_clip):
    _test_clip_property(client, *audio_clip, "pitch_coarse", (4, 0))

def test_clip_property_pitch_fine(client, audio_clip):
    _test_clip_property(client, *audio_clip, "pitch_fine", (0.5, 0.0))

def test_clip_add_remove_notes(client, midi_clip):
    track_id, clip_id = midi_clip
    assert client.query("/live/clip/get/notes", (track_id, clip_id)) == (track_id, clip_id)

    client.send_message("/live/clip/add/notes", (track_id, clip_id,
                                                 60, 0.0, 0.25, 64, False,
                                                 67, -0.25, 0.5, 32, False))

    # Should return all notes, including those before time = 0
    assert client.query("/live/clip/get/notes", (track_id, clip_id)) == (track_id, clip_id,
                                                                        60, 0.0, 0.25, 64, False,
                                                                        67, -0.25, 0.5, 32, False)

    client.send_message("/live/clip/add/notes", (track_id, clip_id,
                                                 72, 0.0, 0.25, 64, False,
                                                 60, 3.0, 0.5, 32, False))

    # Query between t in [0..2] and pitch in [60, 71]
    # Should only return a single note
    assert client.query("/live/clip/get/notes", (track_id, clip_id, 60, 11, 0, 2)) == \
        (track_id, clip_id, 60, 0.0, 0.25, 64, False)

    client.send_message("/live/clip/remove/notes", (track_id, clip_id, 60, 11, 0, 2))
    assert client.query("/live/clip/get/notes", (track_id, clip_id)) == (track_id, clip_id,
                                                                        60, 3.0, 0.5, 32, False,
                                                                        67, -0.25, 0.5, 32, False,
                                                                        72, 0.0, 0.25, 64, False)
    client.send_message("/live/clip/remove/notes", (track_id, clip_id))
    assert client.query("/live/clip/get/notes", (track_id, clip_id)) == (track_id, clip_id)

def test_clip_add_many_notes(client, midi_clip):
    """
    Test adding large numbers of notes to a clip.
    Note that Ableton API's get_notes returns notes sorted by pitch, then time, so add notes
    in this same order.
    """
    track_id, clip_id = midi_clip
    random.seed(0)
    all_note_data = []
    pitch = 0
    for pitch_index in range(127):
        time = random.randrange(-32, 32) / 4
        duration = random.randrange(1, 4) / 4
        velocity = random.randrange(1, 128)
        # Create multiple instances of the same sequence, shifted in time.
        for timeshift in range(3):
            note = (pitch,
                    time + (timeshift * 8),
                    duration,
                    velocity,
                    False)
            all_note_data += note
        pitch += 1
    all_note_data = tuple(all_note_data)

    # Check clip is initially empty
    assert client.query("/live/clip/get/notes", (track_id, clip_id)) == (track_id, clip_id)

    try:
        # Populate clip and check return value
        client.send_message("/live/clip/add/notes", (track_id, clip_id) + all_note_data)
        assert client.query("/live/clip/get/notes", (track_id, clip_id)) == \
            (track_id, clip_id) + all_note_data
    finally:
        # Clear clip
        client.send_message("/live/clip/remove/notes", (track_id, clip_id))

def test_clip_playing_position_listen(client, midi_clip):
    track_id, clip_id = midi_clip

    #--------------------------------------------------------------------------------
    # Fire on the next 1/16th rather than waiting for the set's own quantization,
    # which may be a whole bar. Restored afterwards.
    #--------------------------------------------------------------------------------
    with restored_song_property(client, "clip_trigger_quantization"):
        client.send_message("/live/song/set/clip_trigger_quantization", (11,))
        client.send_message("/live/clip/start_listen/playing_position", [track_id, clip_id])
        try:
            client.send_message("/live/clip/fire", [track_id, clip_id])

            rv = client.await_message("/live/clip/get/playing_position", TICK_DURATION * 2)
            assert rv == (track_id, clip_id, 0)

            rv = client.await_message("/live/clip/get/playing_position", TICK_DURATION * 2)
            assert rv[0] == track_id
            assert rv[1] == clip_id
            assert rv[2] > 0
        finally:
            #--------------------------------------------------------------------------------
            # Stop with the same key the listener was started with, and stop even when
            # an assertion above fails - otherwise the listener leaks until reload.
            #--------------------------------------------------------------------------------
            client.send_message("/live/clip/stop_listen/playing_position", (track_id, clip_id))
            client.send_message("/live/song/stop_playing")
            client.send_message("/live/song/stop_all_clips")
            wait_one_tick()

def test_clip_listen_lifecycle(client, midi_clip):
    track_id, clip_id = midi_clip

    client.send_message("/live/clip/set/name", [track_id, clip_id, "Alpha"])
    wait_one_tick()
    client.send_message("/live/clip/start_listen/name", [track_id, clip_id])
    try:
        assert client.await_message("/live/clip/get/name", TICK_DURATION * 2) == (track_id, clip_id, "Alpha")
        client.send_message("/live/clip/set/name", [track_id, clip_id, "Beta"])
        assert client.await_message("/live/clip/get/name", TICK_DURATION * 2) == (track_id, clip_id, "Beta")

        #--------------------------------------------------------------------------------
        # Replacing the clip in the slot must re-bind the listener to the new object.
        #--------------------------------------------------------------------------------
        client.send_message("/live/clip_slot/delete_clip", [track_id, clip_id])
        client.send_message("/live/clip_slot/create_clip", [track_id, clip_id, 8.0])
        client.send_message("/live/clip/start_listen/name", [track_id, clip_id])
        assert client.await_message("/live/clip/get/name", TICK_DURATION * 2) == (track_id, clip_id, "")
        client.send_message("/live/clip/set/name", [track_id, clip_id, "Alpha"])
        assert client.await_message("/live/clip/get/name", TICK_DURATION * 2) == (track_id, clip_id, "Alpha")
    finally:
        client.send_message("/live/clip/stop_listen/name", [track_id, clip_id])
