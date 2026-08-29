"""
Integer width selection in the vendored `pythonosc` message builder, end to
end over the loopback socket the rest of `tests_unit/` uses.

The window this pins is `[2**31, 2**32)` and its negative mirror. Upstream's
builder chose int32 whenever `bit_length() <= 32`, but `bit_length()` ignores
the sign bit, so those values were tagged `i` and `struct.pack(">i", …)`
raised `BuildError` — and `OSCServer.send` catches `BuildError` and logs it,
so the *entire reply datagram* vanished with nothing on the wire to say so.

Live's note ids are the concrete case (`/live/clip/get/notes_extended` and
the id-keyed addresses reply with them, and API.md documents the width a
client's decoder must tolerate), but nothing about the failure was specific
to notes: any int-valued reply in that window dropped.
"""

import pytest

from .conftest import load_module

INT32_MIN = -2 ** 31
INT32_MAX = 2 ** 31 - 1


@pytest.fixture
def builder_module():
    return load_module("pythonosc.osc_message_builder")


#--------------------------------------------------------------------------------
# Tag selection, at the boundaries
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected_tag", [
    (0, "i"),
    (1, "i"),
    (-1, "i"),
    (INT32_MAX, "i"),
    (INT32_MIN, "i"),
    # The regression window: representable, previously tagged int32 and dropped.
    (INT32_MAX + 1, "h"),
    (INT32_MIN - 1, "h"),
    (2 ** 32 - 1, "h"),
    (-(2 ** 32) + 1, "h"),
    # Wider still — already int64 before the fix.
    (2 ** 32, "h"),
    (2 ** 40, "h"),
])
def test_int_tag_follows_the_signed_int32_window(builder_module, value, expected_tag):
    builder = builder_module.OscMessageBuilder("/x")
    assert builder._get_arg_type(value) == expected_tag


#--------------------------------------------------------------------------------
# The whole point: the datagram arrives, with the value intact
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    INT32_MIN,
    -1,
    0,
    INT32_MAX,
    INT32_MAX + 1,      # 2**31 — the first id the old check dropped
    2 ** 32 - 1,        # the last one
    2 ** 32,
    INT32_MIN - 1,
])
def test_reply_survives_the_wire_and_round_trips(server, receiver, value):
    server.add_handler("/live/clip/get/notes_extended", lambda _: (value,))
    server.send("/live/clip/get/notes_extended", (value,))
    assert receiver.drain() == [("/live/clip/get/notes_extended", (value,))]
