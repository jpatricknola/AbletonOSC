from . import wait_one_tick, TICK_DURATION
from .conftest import require, _find_empty_slot, _delete_clip_if_present

def test_clip_slot_has_clip(client, empty_midi_slot):
    track_id, scene_id = empty_midi_slot
    assert client.query("/live/clip_slot/get/has_clip", (track_id, scene_id)) == \
        (track_id, scene_id, False)
    client.send_message("/live/clip_slot/create_clip", (track_id, scene_id, 4.0))
    wait_one_tick()
    assert client.query("/live/clip_slot/get/has_clip", (track_id, scene_id)) == \
        (track_id, scene_id, True)
    # The fixture deletes whatever is left in the slot.

def test_clip_slot_duplicate(client, midi_clip, num_scenes):
    track_id, source_id = midi_clip
    dest_id = _find_empty_slot(client, track_id, num_scenes, exclude=(source_id,))
    require(dest_id is not None, "no second empty clip slot on the MIDI track")

    try:
        assert client.query("/live/clip/get/notes", (track_id, source_id)) == (track_id, source_id)

        client.send_message("/live/clip/add/notes", (track_id, source_id,
                                                     60, 0.0, 0.25, 64, False))

        client.send_message("/live/clip_slot/duplicate_clip_to", (track_id, source_id, track_id, dest_id))
        wait_one_tick()
        assert client.query("/live/clip/get/notes", (track_id, dest_id)) == \
            (track_id, dest_id, 60, 0.0, 0.25, 64, False)
    finally:
        _delete_clip_if_present(client, track_id, dest_id)

def test_clip_slot_property_listen(client, empty_midi_slot):
    track_id, scene_id = empty_midi_slot
    client.send_message("/live/clip_slot/start_listen/has_clip", (track_id, scene_id))
    try:
        assert client.await_message("/live/clip_slot/get/has_clip", TICK_DURATION * 2) == \
            (track_id, scene_id, False)
        client.send_message("/live/clip_slot/create_clip", [track_id, scene_id, 4.0])
        assert client.await_message("/live/clip_slot/get/has_clip", TICK_DURATION * 2) == \
            (track_id, scene_id, True)
        client.send_message("/live/clip_slot/delete_clip", [track_id, scene_id])
        assert client.await_message("/live/clip_slot/get/has_clip", TICK_DURATION * 2) == \
            (track_id, scene_id, False)
    finally:
        #--------------------------------------------------------------------------------
        # Stop with the same (track, scene) key the listener was started with —
        # a mismatched key fails the stop and leaks the listener until reload —
        # and stop even when an assertion above fails, for the same reason.
        #--------------------------------------------------------------------------------
        client.send_message("/live/clip_slot/stop_listen/has_clip", (track_id, scene_id))
