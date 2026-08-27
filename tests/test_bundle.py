from . import wait_one_tick

#--------------------------------------------------------------------------------
# OSC bundles
#--------------------------------------------------------------------------------

def test_bundle(client):
    reply_count = 0
    def count_replies(address, params):
        nonlocal reply_count
        reply_count += 1
    client.set_handler("/live/song/get/tempo", count_replies)

    try:
        client.send_bundle([
            ("/live/song/get/tempo", tuple()),
            ("/live/song/get/tempo", tuple()),
            ("/live/song/get/tempo", tuple())
        ])

        wait_one_tick()
        assert reply_count == 3
    finally:
        client.remove_handler("/live/song/get/tempo")
