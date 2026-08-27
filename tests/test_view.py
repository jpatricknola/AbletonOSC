from .conftest import require, restored_view_selection

#--------------------------------------------------------------------------------
# Test view features.
#
# Every test here snapshots the session view's selection first and restores it
# afterwards: upstream left the user's set on whatever track and scene the last
# test happened to select.
#--------------------------------------------------------------------------------

def test_selected_scene(client, num_scenes):
    require(num_scenes >= 2, "set has fewer than 2 scenes")
    with restored_view_selection(client):
        client.send_message("/live/view/set/selected_scene", (1, ))
        rv = client.query("/live/view/get/selected_scene")
        assert rv == (1, )

def test_selected_track(client, num_tracks):
    require(num_tracks >= 2, "set has fewer than 2 tracks")
    with restored_view_selection(client):
        track_id = num_tracks - 1
        client.send_message("/live/view/set/selected_track", (track_id, ))
        rv = client.query("/live/view/get/selected_track")
        assert rv == (track_id, )

def test_selected_clip(client, midi_clip):
    #--------------------------------------------------------------------------------
    # Select a clip that this test created, rather than assuming the set holds one
    # at (3, 4).
    #--------------------------------------------------------------------------------
    track_id, clip_id = midi_clip
    with restored_view_selection(client):
        client.send_message("/live/view/set/selected_clip", (track_id, clip_id))
        rv = client.query("/live/view/get/selected_clip")
        assert rv == (track_id, clip_id)
