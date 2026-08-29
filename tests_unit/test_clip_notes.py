"""
The extended-notes addresses (note ids), without Ableton Live.

`/live/clip/get/notes` describes a note as five numbers. The twelve addresses
exercised here describe it as Live does: with the `note_id` Live assigned and
the `probability`, `velocity_deviation` and `release_velocity` it carries, and
with the id-keyed members that only become usable once an id is on the wire —
fetch by id, modify in place, duplicate, select.

Everything under test is production code: conftest.load_clip_module() builds
the real ClipHandler on the real OSCServer, and every case goes in as a
datagram through `dispatch`. Only the LOM objects are fakes.

Two things the fakes model deliberately:

1. `FakeMidiNote` carries all nine fields, so the five-field addresses can be
   pinned against a note that *has* the extended ones. That is what makes
   "the old addresses are byte-identical by construction" checkable rather
   than merely asserted (case 9).
2. `Live.Clip.MidiNoteSpecification` is monkeypatched onto the process-global
   empty `Live` stub for the duration of a test — the image of the
   application.py seam pattern, for a name the production code dereferences
   at call time. This is the first test in the suite to dispatch an address
   that dereferences it; conftest's docstrings were updated in the same
   commit to stop claiming otherwise.

What this cannot prove: anything about real LOM objects. Whether
`MidiNoteSpecification` really accepts the three extended kwargs, whether a
real `MidiNote`'s attributes are writable, what `get_notes_by_id` does with an
unknown id, what the deprecated `set_notes` / `replace_selected_notes` mean,
and whether the selection API needs the clip in the detail view are all
unmeasured — they need the Live verification checks in the plan, and API.md
marks each with a ⚠️ until they run.
"""

import sys

import pytest

from .conftest import dispatch, load_clip_module, load_handler_module


class FakeManager:
    """`osc_server` is the only attribute AbletonOSCHandler reads off it."""

    def __init__(self, osc_server):
        self.osc_server = osc_server


class FakeMidiNote:
    """
    A `Live.Clip.MidiNote` stand-in: the five old fields, the three extended
    ones, and the id Live assigns. Attributes are plain and writable, which is
    the assumption `apply_note_modifications` is built on (unmeasured against a
    real MidiNote — see the module docstring).
    """

    def __init__(self, pitch, start_time, duration, velocity, mute,
                 probability=1.0, velocity_deviation=0.0,
                 release_velocity=64.0, note_id=0):
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute
        self.probability = probability
        self.velocity_deviation = velocity_deviation
        self.release_velocity = release_velocity
        self.note_id = note_id

    def fields(self):
        return (self.pitch, self.start_time, self.duration, self.velocity,
                self.mute, self.probability, self.velocity_deviation,
                self.release_velocity, self.note_id)


class FakeSpecification:
    """
    Records the kwargs the handler built a note specification from. Stands in
    for `Live.Clip.MidiNoteSpecification`, whose real constructor is
    unmeasured.
    """

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeSpecification.instances.append(self)


class FakeClip:
    """
    Every note member the extended block calls, recording its arguments.

    `get_notes_by_id` answers in *request* order and silently omits ids it does
    not hold — one plausible reading of an unmeasured member, and the one that
    makes the handler's own missing-id check the thing under test.
    """

    def __init__(self, notes=(), selected=(), new_ids=(901, 902)):
        self.notes = list(notes)
        self.selected = list(selected)
        self.new_ids = tuple(new_ids)
        self.calls = []

    def get_notes_extended(self, pitch_start, pitch_span, time_start, time_span):
        self.calls.append(("get_notes_extended", (pitch_start, pitch_span,
                                                  time_start, time_span)))
        return tuple(self.notes)

    def add_new_notes(self, specifications):
        self.calls.append(("add_new_notes", specifications))

    def get_selected_notes_extended(self):
        self.calls.append(("get_selected_notes_extended", ()))
        return tuple(self.selected)

    def get_notes_by_id(self, note_ids):
        self.calls.append(("get_notes_by_id", note_ids))
        by_id = dict((note.note_id, note) for note in self.notes)
        return tuple(by_id[note_id] for note_id in note_ids if note_id in by_id)

    def apply_note_modifications(self, notes):
        self.calls.append(("apply_note_modifications", tuple(notes)))

    def duplicate_notes_by_id(self, note_ids, destination_time,
                              transposition_amount):
        self.calls.append(("duplicate_notes_by_id",
                           (note_ids, destination_time, transposition_amount)))
        return self.new_ids

    def select_notes_by_id(self, note_ids):
        self.calls.append(("select_notes_by_id", note_ids))

    def select_all_notes(self):
        self.calls.append(("select_all_notes", ()))

    def deselect_all_notes(self):
        self.calls.append(("deselect_all_notes", ()))

    def replace_selected_notes(self, notes):
        self.calls.append(("replace_selected_notes", notes))

    def set_notes(self, notes):
        self.calls.append(("set_notes", notes))

    def calls_named(self, name):
        return [args for called, args in self.calls if called == name]


class FakeClipSlot:
    def __init__(self, clip):
        self.clip = clip
        self.has_clip = clip is not None


class FakeTrack:
    def __init__(self, clip_slots):
        self.clip_slots = list(clip_slots)


class FakeSong:
    def __init__(self, tracks):
        self.tracks = list(tracks)


def make_notes():
    """
    Two notes whose extended fields are all distinct from Live's defaults, so
    a handler that dropped or reordered a field cannot pass by accident.
    """
    return [FakeMidiNote(60, 0.0, 0.5, 100.0, False,
                         probability=0.25, velocity_deviation=7.5,
                         release_velocity=33.0, note_id=11),
            FakeMidiNote(64, 1.5, 0.25, 80.0, True,
                         probability=0.75, velocity_deviation=-3.0,
                         release_velocity=48.0, note_id=22)]


@pytest.fixture
def clip():
    notes = make_notes()
    return FakeClip(notes=notes, selected=list(notes))


@pytest.fixture
def handler(server, clip):
    """
    The production ClipHandler on the production OSCServer. Track 0 slot 0
    holds the clip under test; slot 1 is empty so a wrong index is a different
    failure from a missing clip.
    """
    load_handler_module()
    clip_module = load_clip_module()
    h = clip_module.ClipHandler(FakeManager(server))
    h.song = FakeSong([FakeTrack([FakeClipSlot(clip), FakeClipSlot(None)])])
    return h


@pytest.fixture
def specifications(monkeypatch):
    """
    A recording `Live.Clip.MidiNoteSpecification` on the empty `Live` stub, for
    the two add addresses. `raising=False` because the stub carries no `Clip`
    attribute at all; monkeypatch removes it again at teardown, so the stub
    goes back to being empty for every other test in the session.
    """
    FakeSpecification.instances = []
    import types
    clip_namespace = types.ModuleType("Live.Clip")
    clip_namespace.MidiNoteSpecification = FakeSpecification
    monkeypatch.setattr(sys.modules["Live"], "Clip", clip_namespace,
                        raising=False)
    yield FakeSpecification.instances
    FakeSpecification.instances = []


def one_message(receiver):
    messages = receiver.drain()
    assert len(messages) == 1, messages
    return messages[0]


def assert_error(receiver, address, *request_args):
    error_address, params = one_message(receiver)
    assert error_address == "/live/error"
    assert params[0] == "request"
    assert params[1] == address
    assert params[3:] == (len(request_args), *request_args)
    return params[2]


def groups_of(params, stride):
    """Split a reply's note fields (the two indices dropped) into groups."""
    fields = params[2:]
    assert len(fields) % stride == 0, fields
    return [fields[offset:offset + stride]
            for offset in range(0, len(fields), stride)]


#--------------------------------------------------------------------------------
# 1. Every address in the item is registered, through the production loop
#--------------------------------------------------------------------------------

EXTENDED_ADDRESSES = [
    "/live/clip/get/notes_extended",
    "/live/clip/add/notes_extended",
    "/live/clip/get/selected_notes_extended",
    "/live/clip/get/selected_notes",
    "/live/clip/get_notes_by_id",
    "/live/clip/apply_note_modifications",
    "/live/clip/duplicate_notes_by_id",
    "/live/clip/select_notes_by_id",
    "/live/clip/replace_selected_notes",
    "/live/clip/set_notes",
    "/live/clip/select_all_notes",
    "/live/clip/deselect_all_notes",
]


@pytest.mark.parametrize("address", EXTENDED_ADDRESSES)
def test_every_extended_address_is_registered(handler, server, address):
    assert address in server._callbacks


def test_the_old_note_addresses_are_still_registered(handler, server):
    for address in ("/live/clip/get/notes", "/live/clip/add/notes",
                    "/live/clip/remove/notes", "/live/clip/remove_notes_by_id"):
        assert address in server._callbacks


def test_select_all_and_deselect_all_call_the_clip(handler, server, receiver,
                                                   clip):
    dispatch(server, "/live/clip/select_all_notes", 0, 0)
    dispatch(server, "/live/clip/deselect_all_notes", 0, 0)

    assert [name for name, _ in clip.calls] == ["select_all_notes",
                                                "deselect_all_notes"]
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 2. get/notes_extended: nine fields per note, in canonical order
#--------------------------------------------------------------------------------

def test_get_notes_extended_replies_nine_fields_in_canonical_order(handler,
                                                                    server,
                                                                    receiver):
    address = "/live/clip/get/notes_extended"
    dispatch(server, address, 0, 0)

    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert params[:2] == (0, 0)

    first, second = groups_of(params, 9)
    assert first[0] == 60
    assert first[1] == pytest.approx(0.0)
    assert first[2] == pytest.approx(0.5)
    assert first[3] == pytest.approx(100.0)
    assert first[4] is False
    assert first[5] == pytest.approx(0.25)
    assert first[6] == pytest.approx(7.5)
    assert first[7] == pytest.approx(33.0)
    assert first[8] == 11

    assert second[0] == 64
    assert second[4] is True
    assert second[8] == 22
    #--------------------------------------------------------------------------------
    # The wire types the contract promises: int pitch, OSC boolean mute, int id.
    #--------------------------------------------------------------------------------
    assert [type(first[0]), type(first[4]), type(first[8])] == [int, bool, int]


def test_get_notes_extended_default_window(handler, server, receiver, clip):
    dispatch(server, "/live/clip/get/notes_extended", 0, 0)

    assert clip.calls_named("get_notes_extended") == [(0, 127, -8192, 16384)]


def test_get_notes_extended_forwards_a_four_argument_window(handler, server,
                                                            receiver, clip):
    dispatch(server, "/live/clip/get/notes_extended", 0, 0, 60, 1, 2.0, 1.0)

    (window,) = clip.calls_named("get_notes_extended")
    assert window[0] == 60
    assert window[1] == 1
    assert window[2] == pytest.approx(2.0)
    assert window[3] == pytest.approx(1.0)


@pytest.mark.parametrize("window", [(60,), (60, 1), (60, 1, 2.0)])
def test_get_notes_extended_range_args_are_all_or_nothing(handler, server,
                                                          receiver, clip,
                                                          window):
    address = "/live/clip/get/notes_extended"
    dispatch(server, address, 0, 0, *window)

    detail = assert_error(receiver, address, 0, 0, *window)
    assert "notes_extended" in detail
    assert clip.calls == []


def test_empty_clip_replies_only_the_indices(handler, server, receiver, clip):
    clip.notes = []

    dispatch(server, "/live/clip/get/notes_extended", 0, 0)

    assert one_message(receiver) == ("/live/clip/get/notes_extended", (0, 0))


#--------------------------------------------------------------------------------
# 3. add/notes_extended: eight fields per note, coerced, and silent
#--------------------------------------------------------------------------------

def test_add_notes_extended_builds_one_specification_per_group(handler, server,
                                                               receiver, clip,
                                                               specifications):
    #--------------------------------------------------------------------------------
    # Every argument float-typed, as TouchOSC would send them: the handler is
    # what turns them back into an int pitch and a real bool.
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/clip/add/notes_extended", 0, 0,
             60.0, 0.0, 0.5, 100.0, 0.0, 0.25, 7.5, 33.0,
             64.0, 1.5, 0.25, 80.0, 1.0, 0.75, -3.0, 48.0)

    assert len(specifications) == 2
    first = specifications[0].kwargs
    assert first["pitch"] == 60 and type(first["pitch"]) is int
    assert first["start_time"] == pytest.approx(0.0)
    assert first["duration"] == pytest.approx(0.5)
    assert first["velocity"] == pytest.approx(100.0)
    assert first["mute"] is False
    assert first["probability"] == pytest.approx(0.25)
    assert first["velocity_deviation"] == pytest.approx(7.5)
    assert first["release_velocity"] == pytest.approx(33.0)
    assert set(first) == {"pitch", "start_time", "duration", "velocity", "mute",
                          "probability", "velocity_deviation",
                          "release_velocity"}

    second = specifications[1].kwargs
    assert second["pitch"] == 64
    assert second["mute"] is True
    assert second["velocity_deviation"] == pytest.approx(-3.0)

    (added,) = clip.calls_named("add_new_notes")
    assert added == (specifications[0], specifications[1])
    assert receiver.drain() == []


@pytest.mark.parametrize("extra", [
    (60, 0.0, 0.5, 100.0, 0, 0.25, 7.5),                      # 7 — one short
    (60, 0.0, 0.5, 100.0, 0, 0.25, 7.5, 33.0, 1.0),           # 9 — one over
    (),                                                        # none at all
])
def test_add_notes_extended_stride_errors(handler, server, receiver, clip,
                                          specifications, extra):
    address = "/live/clip/add/notes_extended"
    dispatch(server, address, 0, 0, *extra)

    detail = assert_error(receiver, address, 0, 0, *extra)
    assert "multiple of 8" in detail
    assert clip.calls_named("add_new_notes") == []
    assert specifications == []


#--------------------------------------------------------------------------------
# 4. The selection getters flatten the same vector two ways
#--------------------------------------------------------------------------------

def test_selected_notes_extended_and_basic_flatten_the_same_vector(handler,
                                                                   server,
                                                                   receiver,
                                                                   clip):
    dispatch(server, "/live/clip/get/selected_notes_extended", 0, 0)
    address, params = one_message(receiver)
    assert address == "/live/clip/get/selected_notes_extended"
    extended = groups_of(params, 9)
    assert [group[8] for group in extended] == [11, 22]

    dispatch(server, "/live/clip/get/selected_notes", 0, 0)
    address, params = one_message(receiver)
    assert address == "/live/clip/get/selected_notes"
    basic = groups_of(params, 5)
    assert [group[0] for group in basic] == [60, 64]
    #--------------------------------------------------------------------------------
    # The five-field form is a prefix of the nine-field one, field for field.
    #--------------------------------------------------------------------------------
    for wide, narrow in zip(extended, basic):
        assert wide[:5] == narrow

    #--------------------------------------------------------------------------------
    # Both go through the extended member; the deprecated get_selected_notes is
    # never called.
    #--------------------------------------------------------------------------------
    assert [name for name, _ in clip.calls] == ["get_selected_notes_extended"] * 2


def test_empty_selection_replies_only_the_indices(handler, server, receiver,
                                                  clip):
    clip.selected = []

    dispatch(server, "/live/clip/get/selected_notes_extended", 0, 0)
    assert one_message(receiver) == ("/live/clip/get/selected_notes_extended",
                                     (0, 0))

    dispatch(server, "/live/clip/get/selected_notes", 0, 0)
    assert one_message(receiver) == ("/live/clip/get/selected_notes", (0, 0))


#--------------------------------------------------------------------------------
# 5. get_notes_by_id
#--------------------------------------------------------------------------------

def test_get_notes_by_id_forwards_int_ids_and_replies_nine_fields(handler,
                                                                   server,
                                                                   receiver,
                                                                   clip):
    address = "/live/clip/get_notes_by_id"
    #--------------------------------------------------------------------------------
    # Float-typed ids, the TouchOSC case: they truncate to ints before Live
    # sees them, the same rule the track/clip indices follow.
    #--------------------------------------------------------------------------------
    dispatch(server, address, 0, 0, 22.0, 11.0)

    (note_ids,) = clip.calls_named("get_notes_by_id")
    assert note_ids == (22, 11)
    assert [type(note_id) for note_id in note_ids] == [int, int]

    reply_address, params = one_message(receiver)
    assert reply_address == address
    assert [group[8] for group in groups_of(params, 9)] == [22, 11]


def test_get_notes_by_id_without_ids_is_an_error(handler, server, receiver,
                                                 clip):
    address = "/live/clip/get_notes_by_id"
    dispatch(server, address, 0, 0)

    detail = assert_error(receiver, address, 0, 0)
    assert "at least one note id" in detail.lower()
    assert clip.calls == []


#--------------------------------------------------------------------------------
# 6. apply_note_modifications: fetch by id, mutate, apply — or nothing at all
#--------------------------------------------------------------------------------

def test_apply_note_modifications_sets_every_field_on_the_fetched_notes(
        handler, server, receiver, clip):
    dispatch(server, "/live/clip/apply_note_modifications", 0, 0,
             62.0, 2.0, 1.0, 90.0, 1.0, 0.5, 4.0, 40.0, 11.0)

    note = clip.notes[0]
    assert note.note_id == 11
    assert note.pitch == 62 and type(note.pitch) is int
    assert note.start_time == pytest.approx(2.0)
    assert note.duration == pytest.approx(1.0)
    assert note.velocity == pytest.approx(90.0)
    assert note.mute is True
    assert note.probability == pytest.approx(0.5)
    assert note.velocity_deviation == pytest.approx(4.0)
    assert note.release_velocity == pytest.approx(40.0)

    #--------------------------------------------------------------------------------
    # The objects handed to apply are the ones Live returned, not copies.
    #--------------------------------------------------------------------------------
    (applied,) = clip.calls_named("apply_note_modifications")
    assert applied == (note,)
    assert clip.notes[1].pitch == 64
    assert receiver.drain() == []


def test_apply_note_modifications_rejects_an_unknown_id_before_mutating(
        handler, server, receiver, clip):
    address = "/live/clip/apply_note_modifications"
    before = [note.fields() for note in clip.notes]

    #--------------------------------------------------------------------------------
    # Two groups, the second citing an id the clip does not hold. The first
    # group must not be applied either: the check runs before any mutation.
    #--------------------------------------------------------------------------------
    dispatch(server, address, 0, 0,
             62.0, 2.0, 1.0, 90.0, 1.0, 0.5, 4.0, 40.0, 11.0,
             65.0, 3.0, 1.0, 90.0, 0.0, 1.0, 0.0, 64.0, 999.0)

    detail = assert_error(receiver, address, 0, 0,
                          62.0, 2.0, 1.0, 90.0, 1.0, 0.5, 4.0, 40.0, 11.0,
                          65.0, 3.0, 1.0, 90.0, 0.0, 1.0, 0.0, 64.0, 999.0)
    assert "999" in detail
    assert clip.calls_named("apply_note_modifications") == []
    assert [note.fields() for note in clip.notes] == before


@pytest.mark.parametrize("extra", [
    (62.0, 2.0, 1.0, 90.0, 1.0, 0.5, 4.0, 40.0),   # 8 — the add form, one short
    (),                                             # none at all
])
def test_apply_note_modifications_stride_errors(handler, server, receiver,
                                                clip, extra):
    address = "/live/clip/apply_note_modifications"
    dispatch(server, address, 0, 0, *extra)

    detail = assert_error(receiver, address, 0, 0, *extra)
    assert "multiple of 9" in detail
    assert clip.calls == []


#--------------------------------------------------------------------------------
# 7. duplicate_notes_by_id, and the negative-destination sentinel
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("destination", [-1.0, -0.5])
def test_duplicate_notes_by_id_treats_any_negative_destination_as_none(
        handler, server, receiver, clip, destination):
    address = "/live/clip/duplicate_notes_by_id"
    dispatch(server, address, 0, 0, destination, 0, 11.0, 22.0)

    (call,) = clip.calls_named("duplicate_notes_by_id")
    note_ids, destination_time, transposition_amount = call
    assert note_ids == (11, 22)
    assert destination_time is None
    assert transposition_amount == 0 and type(transposition_amount) is int

    assert one_message(receiver) == (address, (0, 0, 901, 902))


def test_duplicate_notes_by_id_passes_a_non_negative_destination_through(
        handler, server, receiver, clip):
    dispatch(server, "/live/clip/duplicate_notes_by_id", 0, 0, 4.0, 12, 11)

    (call,) = clip.calls_named("duplicate_notes_by_id")
    note_ids, destination_time, transposition_amount = call
    assert note_ids == (11,)
    assert destination_time == pytest.approx(4.0)
    assert transposition_amount == 12


@pytest.mark.parametrize("args", [(), (-1.0,), (-1.0, 0)])
def test_duplicate_notes_by_id_needs_a_destination_and_an_id(handler, server,
                                                             receiver, clip,
                                                             args):
    address = "/live/clip/duplicate_notes_by_id"
    dispatch(server, address, 0, 0, *args)

    assert_error(receiver, address, 0, 0, *args)
    assert clip.calls == []


def test_select_notes_by_id_passes_through_and_says_nothing(handler, server,
                                                            receiver, clip):
    dispatch(server, "/live/clip/select_notes_by_id", 0, 0, 11.0, 22.0)

    assert clip.calls_named("select_notes_by_id") == [(11, 22)]
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 8. The deprecated tuple pass-throughs
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("member", ["set_notes", "replace_selected_notes"])
def test_deprecated_pass_throughs_build_the_nested_tuple(handler, server,
                                                         receiver, clip,
                                                         member):
    address = "/live/clip/%s" % member
    dispatch(server, address, 0, 0,
             60.0, 0.0, 0.5, 100.0, 0.0,
             64.0, 1.5, 0.25, 80.0, 1.0)

    (notes,) = clip.calls_named(member)
    assert len(notes) == 2
    assert notes[0][0] == 60 and type(notes[0][0]) is int
    assert notes[0][1] == pytest.approx(0.0)
    assert notes[0][2] == pytest.approx(0.5)
    assert notes[0][3] == pytest.approx(100.0)
    assert notes[0][4] is False
    assert notes[1][0] == 64
    assert notes[1][4] is True
    assert [type(field) for field in notes[1]] == [int, float, float, float,
                                                   bool]
    assert receiver.drain() == []


@pytest.mark.parametrize("member", ["set_notes", "replace_selected_notes"])
@pytest.mark.parametrize("extra", [(60, 0.0, 0.5, 100.0), ()])
def test_deprecated_pass_throughs_stride_errors(handler, server, receiver,
                                                clip, member, extra):
    address = "/live/clip/%s" % member
    dispatch(server, address, 0, 0, *extra)

    detail = assert_error(receiver, address, 0, 0, *extra)
    assert "multiple of 5" in detail
    assert clip.calls == []


#--------------------------------------------------------------------------------
# 9. The old five-field addresses did not move
#--------------------------------------------------------------------------------

def test_get_notes_still_replies_exactly_five_fields(handler, server, receiver,
                                                     clip):
    #--------------------------------------------------------------------------------
    # Against notes that carry ids and the three extended fields — the whole
    # point of the pin. If get/notes ever grew a field, this is what fails.
    #--------------------------------------------------------------------------------
    dispatch(server, "/live/clip/get/notes", 0, 0)

    reply_address, params = one_message(receiver)
    assert reply_address == "/live/clip/get/notes"
    assert params[:2] == (0, 0)
    assert len(params) == 2 + 5 * 2
    groups = groups_of(params, 5)
    assert groups[0][0] == 60
    assert groups[0][4] is False
    assert groups[1][0] == 64
    assert groups[1][4] is True


def test_add_notes_still_builds_five_kwarg_specifications(handler, server,
                                                          receiver, clip,
                                                          specifications):
    dispatch(server, "/live/clip/add/notes", 0, 0, 60, 0.0, 0.5, 100, 0)

    assert len(specifications) == 1
    assert set(specifications[0].kwargs) == {"pitch", "start_time", "duration",
                                             "velocity", "mute"}
    #--------------------------------------------------------------------------------
    # Upstream's handler coerces nothing — it hands Live whatever the wire
    # carried. Pinned here so the extended parser's coercions cannot be
    # "tidied" into it and change what old clients send.
    #--------------------------------------------------------------------------------
    assert specifications[0].kwargs["pitch"] == 60
    assert specifications[0].kwargs["mute"] == 0
    assert clip.calls_named("add_new_notes") == [(specifications[0],)]
    assert receiver.drain() == []


#--------------------------------------------------------------------------------
# 10. Bad indices are structured errors at the callback boundary
#--------------------------------------------------------------------------------

@pytest.mark.parametrize("address, args", [
    ("/live/clip/get/notes_extended", ()),
    ("/live/clip/get_notes_by_id", (11,)),
    ("/live/clip/select_notes_by_id", (11,)),
])
def test_out_of_range_track_index_is_an_error(handler, server, receiver,
                                              address, args):
    dispatch(server, address, 99, 0, *args)

    assert_error(receiver, address, 99, 0, *args)


def test_an_empty_clip_slot_is_an_error(handler, server, receiver):
    #--------------------------------------------------------------------------------
    # `.clip` is None on an empty slot, so the member call raises inside the
    # callback — the same failure /live/clip/get/notes has always had.
    #--------------------------------------------------------------------------------
    address = "/live/clip/get/notes_extended"
    dispatch(server, address, 0, 1)

    assert_error(receiver, address, 0, 1)
