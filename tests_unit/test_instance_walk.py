"""
The instance walk and its read-shaped predicate, driven over synthetic objects
instead of Live.

introspection.py's second half is the only thing in this repository that
*calls* Live rather than reading its declarations, so its safety rules are the
whole contract: it must never call a listener member, never call a method it
has not proved takes no arguments, never abandon the walk because one read
raised, and never run away down a canonical_parent back-edge.

None of that can be tested against Live from here — nothing in tests_unit/
imports Live. So these tests hand the walk an object graph built in this file
with `__module__` set to "Live.Fake", which is what `_is_live_object` keys off.
What they prove is the *shape* of the walk's decisions, not that Live's own
objects behave as modelled. The first real run against Live is what tests that,
and its error map is the evidence.
"""

import pytest

from .conftest import load_module


@pytest.fixture
def introspection():
    return load_module("abletonosc.introspection")


class LomObject:
    """
    Stand-in for Live's own ``LomObject``, which is what the walk keys off.

    Measured 2026-08-30 against Live 12.4.5: every walkable Live object has
    ``LomObject.LomObject`` in its MRO and every vector has only
    ``Boost.Python.instance``, so the base class is the discriminator rather
    than the module name — Boost.Python sets ``__module__`` to the leaf
    ("Song", not "Live.Song"), and the walk's first run against Live recursed
    into nothing because of it.
    """


def _live(cls):
    """
    Make a synthetic class look like a Boost.Python class from Live: leaf
    __module__, and a __qualname__ equal to the bare name. A class defined
    inside a test function otherwise carries "<locals>" in its __qualname__,
    which no Boost.Python class ever does.
    """
    cls.__module__ = "Fake"
    cls.__qualname__ = cls.__name__
    return cls


#--------------------------------------------------------------------------------
# The predicate. The signatures below are real, copied from FORK_GAPS.md's
# generated inventory, because the whole point of rule 2 is that it parses what
# Boost.Python actually writes rather than what a test author imagines.
#--------------------------------------------------------------------------------

GET_DOCUMENT = "get_document( (Application)arg1) -> Song :"
GET_DATA = "get_data( (Song)arg1, (object)key, (object)default_value) -> object :"
IS_CUE_POINT_SELECTED = "is_cue_point_selected( (Song)arg1) -> bool :"


@pytest.mark.parametrize("name", ["get_thing", "is_thing", "has_thing", "can_thing"])
def test_every_read_prefix_is_accepted_at_arity_one(introspection, name):
    doc = "%s( (Song)arg1) -> bool :" % name
    assert introspection.is_read_shaped(name, doc) is True


def test_a_name_without_a_read_prefix_is_rejected(introspection):
    assert introspection.is_read_shaped("fire", "fire( (Clip)arg1) -> None :") is False


def test_the_real_get_document_signature_is_accepted(introspection):
    assert introspection.is_read_shaped("get_document", GET_DOCUMENT) is True


def test_the_real_is_cue_point_selected_signature_is_accepted(introspection):
    assert introspection.is_read_shaped("is_cue_point_selected", IS_CUE_POINT_SELECTED) is True


def test_the_real_get_data_signature_is_rejected_on_arity(introspection):
    #--------------------------------------------------------------------------------
    # Three arguments, and the commas that matter are at depth 0 while the
    # parenthesised type prefixes carry none. Calling this with no arguments
    # would raise, but the sweep must not get that far.
    #--------------------------------------------------------------------------------
    assert introspection._docstring_arity(GET_DATA) == 3
    assert introspection.is_read_shaped("get_data", GET_DATA) is False


def test_an_unparseable_docstring_is_rejected(introspection):
    assert introspection._docstring_arity("no signature here") is None
    assert introspection.is_read_shaped("get_thing", "no signature here") is False


def test_an_empty_docstring_is_rejected(introspection):
    assert introspection._docstring_arity("") is None
    assert introspection.is_read_shaped("get_thing", "") is False


def test_a_zero_argument_signature_is_rejected(introspection):
    #--------------------------------------------------------------------------------
    # Arity 0 means no receiver, so it is not the bound-method shape the sweep
    # calls. Fail closed rather than guess.
    #--------------------------------------------------------------------------------
    assert introspection._docstring_arity("get_thing() -> int :") == 0
    assert introspection.is_read_shaped("get_thing", "get_thing() -> int :") is False


def test_the_denylist_is_matched_on_the_qualified_name(introspection):
    doc = "get_session_id( (PythonLicensingBridge)arg1) -> str :"
    owner = "Live.Licensing.PythonLicensingBridge"
    assert introspection.is_read_shaped("get_session_id", doc, owner) is False
    #--------------------------------------------------------------------------------
    # The same bare name on a different class is a different method and stays
    # callable — which is why the denylist holds qualified names.
    #--------------------------------------------------------------------------------
    assert introspection.is_read_shaped("get_session_id", doc, "Live.Song.Song") is True


def test_the_shipped_denylist_holds_the_three_measured_licensing_methods(introspection):
    #--------------------------------------------------------------------------------
    # Measured 2026-08-30 against Live 12.4.5: these three pass rules 1 and 2
    # and are shut by policy ("Reachable is not desirable. Live.Licensing is
    # reachable and stays shut" — BLIND_SPOTS.md). Losing them silently is the
    # regression this pins.
    #--------------------------------------------------------------------------------
    assert introspection.READ_METHOD_DENYLIST == frozenset([
        "Live.Licensing.PythonLicensingBridge.get_progress_dialog",
        "Live.Licensing.PythonLicensingBridge.get_session_id",
        "Live.Licensing.PythonLicensingBridge.get_trial_time_left",
    ])


#--------------------------------------------------------------------------------
# The walk.
#--------------------------------------------------------------------------------

def _walk(introspection, root, path="song", **kwargs):
    return introspection.walk_instances([(path, root)], **kwargs)


def test_a_property_is_read_and_its_actual_type_recorded(introspection):
    @_live
    class Track(LomObject):
        name = property(lambda self: "Drums")

    types, totals, _, _ = _walk(introspection, Track())

    record = types["Live.Fake.Track"]["members"]["name"]
    assert record["kind"] == "property"
    assert record["types"] == {"str": 1}
    assert record["repr"] == "'Drums'"
    assert totals["reads"] == 1


def test_a_property_that_raises_is_recorded_and_the_walk_continues(introspection):
    #--------------------------------------------------------------------------------
    # master_track.mute raises RuntimeError on every set there is. A failed
    # read is not falsy and hasattr is not a safe feature test, so the record
    # of the failure is the measurement.
    #--------------------------------------------------------------------------------
    def _boom(self):
        raise RuntimeError("Master track has no mute")

    @_live
    class Master(LomObject):
        mute = property(_boom)
        name = property(lambda self: "Master")

    types, totals, _, _ = _walk(introspection, Master())
    members = types["Live.Fake.Master"]["members"]

    assert members["mute"]["errors"] == {"RuntimeError: Master track has no mute": 1}
    assert members["mute"]["reads"] == 0
    assert members["name"]["types"] == {"str": 1}
    assert totals["errors"] == 1


def test_a_listener_member_is_recorded_and_never_called(introspection):
    #--------------------------------------------------------------------------------
    # The rule that keeps the walk clear of a running consumer's
    # subscriptions: Seshat subscribes to song tempo, tracks, return_tracks and
    # the master mixer params on this machine, and a stray stop_listen would
    # unsubscribe it silently. These members explode if called.
    #--------------------------------------------------------------------------------
    def _explode(self, *args):
        raise AssertionError("the walk called a listener member")

    @_live
    class Song(LomObject):
        add_tempo_listener = _explode
        remove_tempo_listener = _explode
        tempo_has_listener = _explode

    types, _, skipped, _ = _walk(introspection, Song())
    members = types["Live.Fake.Song"]["members"]

    assert members["add_tempo_listener"]["kind"] == "listener"
    assert members["remove_tempo_listener"]["kind"] == "listener"
    assert members["tempo_has_listener"]["kind"] == "listener"
    assert skipped["listeners_never_called"] == 3


def test_a_read_shaped_method_is_called_and_a_wide_one_is_not(introspection):
    @_live
    class Song(LomObject):
        def get_beats_loop_start(self):
            """get_beats_loop_start( (Song)arg1) -> int :"""
            return 4

        def get_data(self, key, default):
            """get_data( (Song)arg1, (object)key, (object)default_value) -> object :"""
            raise AssertionError("the walk called a method taking arguments")

        def create_midi_track(self, index):
            """create_midi_track( (Song)arg1, (int)index) -> None :"""
            raise AssertionError("the walk called a mutator")

    types, totals, skipped, _ = _walk(introspection, Song())
    members = types["Live.Fake.Song"]["members"]

    assert members["get_beats_loop_start"]["types"] == {"int": 1}
    assert members["get_beats_loop_start"]["repr"] == "4"
    assert totals["calls"] == 1
    assert members["get_data"]["reads"] == 0
    assert members["create_midi_track"]["reads"] == 0
    assert skipped["methods_not_read_shaped"] == 2


def test_a_denylisted_method_is_not_called_and_is_reported(introspection):
    @_live
    class PythonLicensingBridge(LomObject):
        def get_session_id(self):
            """get_session_id( (PythonLicensingBridge)arg1) -> str :"""
            raise AssertionError("the walk called a denylisted method")

    PythonLicensingBridge.__module__ = "Live.Licensing"

    types, totals, skipped, _ = _walk(introspection, PythonLicensingBridge())
    record = types["Live.Licensing.PythonLicensingBridge"]["members"]["get_session_id"]

    assert record["reads"] == 0
    assert totals["calls"] == 0
    assert skipped["methods_denylisted"] == [
        "Live.Licensing.PythonLicensingBridge.get_session_id"]


def test_a_vector_records_its_element_type_and_length(introspection):
    #--------------------------------------------------------------------------------
    # The answer blind spot 4 could not reach statically. Song.tracks documents
    # its contents as prose and carries no type anywhere in the interpreter, so
    # this record is the only place a property's value type is written down.
    #--------------------------------------------------------------------------------
    @_live
    class Track(LomObject):
        name = property(lambda self: "T")

    @_live
    class Song(LomObject):
        tracks = property(lambda self: [Track(), Track(), Track()])

    types, _, _, _ = _walk(introspection, Song())
    record = types["Live.Fake.Song"]["members"]["tracks"]

    assert record["element_types"] == {"Live.Fake.Track": 1}
    assert record["length"] == 3
    assert types["Live.Fake.Track"]["instances"] == 3


def test_two_objects_of_one_type_merge_into_a_single_entry(introspection):
    @_live
    class Track(LomObject):
        name = property(lambda self: "T")

    @_live
    class Song(LomObject):
        tracks = property(lambda self: [Track(), Track()])

    types, _, _, _ = _walk(introspection, Song())

    assert types["Live.Fake.Track"]["instances"] == 2
    assert types["Live.Fake.Track"]["members"]["name"]["reads"] == 2


def test_devices_are_keyed_by_class_name_so_two_device_types_stay_apart(introspection):
    #--------------------------------------------------------------------------------
    # The whole reason the key is not just the type qualname.
    # Live.Device.Device is one class whose instances are different capability
    # surfaces; "which DeviceParameters does a Wavetable carry" is unanswerable
    # if Wavetable and Operator share one entry.
    #--------------------------------------------------------------------------------
    @_live
    class Device(LomObject):
        def __init__(self, class_name):
            self._class_name = class_name

        class_name = property(lambda self: self._class_name)

    @_live
    class Track(LomObject):
        devices = property(lambda self: [Device("Wavetable"), Device("Operator")])

    types, _, _, class_names = _walk(introspection, Track())

    assert "Live.Fake.Device/Wavetable" in types
    assert "Live.Fake.Device/Operator" in types
    assert class_names == ["Operator", "Wavetable"]


def test_a_canonical_parent_back_edge_terminates_and_is_counted(introspection):
    #--------------------------------------------------------------------------------
    # The class walk never had to handle this: every device points back at its
    # track. The id() guard is what stops it, and the count is the proof the
    # guard fired rather than the graph happening to be a tree.
    #--------------------------------------------------------------------------------
    @_live
    class Track(LomObject):
        def __init__(self):
            self.device = None

        devices = property(lambda self: [self.device])

    @_live
    class Device(LomObject):
        def __init__(self, track):
            self._track = track

        canonical_parent = property(lambda self: self._track)

    track = Track()
    track.device = Device(track)

    types, _, skipped, _ = _walk(introspection, track)

    assert set(types) == {"Live.Fake.Track", "Live.Fake.Device"}
    assert skipped["cycle_hits"] == 1


def test_the_depth_bound_truncates_and_is_counted(introspection):
    @_live
    class Node(LomObject):
        def __init__(self, depth):
            self._depth = depth

        child = property(lambda self: Node(self._depth + 1))

    _, _, skipped, _ = _walk(introspection, Node(0), max_depth=3)

    assert skipped["depth_truncations"] == 1


def test_a_long_vector_is_truncated_for_recursion_but_typed_from_its_first(introspection):
    #--------------------------------------------------------------------------------
    # A note or warp-marker vector must not dominate the run. The element type
    # still comes from the first element, and the full length is recorded, so
    # the truncation is visible rather than silent.
    #--------------------------------------------------------------------------------
    @_live
    class Note(LomObject):
        pitch = property(lambda self: 60)

    limit = introspection.VECTOR_RECURSE_LIMIT

    @_live
    class Clip(LomObject):
        notes = property(lambda self: [Note() for _ in range(limit + 5)])

    types, _, skipped, _ = _walk(introspection, Clip())
    record = types["Live.Fake.Clip"]["members"]["notes"]

    assert record["length"] == limit + 5
    assert record["element_types"] == {"Live.Fake.Note": 1}
    assert types["Live.Fake.Note"]["instances"] == limit
    assert skipped["vector_truncations"] == 1


def test_a_class_constant_is_recorded_without_an_instance_read(introspection):
    @_live
    class Variants(LomObject):
        SUITE = "Suite"

    types, _, _, _ = _walk(introspection, Variants())
    record = types["Live.Fake.Variants"]["members"]["SUITE"]

    assert record["kind"] == "value"
    assert record["repr"] == "'Suite'"


def test_example_paths_name_where_each_type_was_reached(introspection):
    @_live
    class Track(LomObject):
        name = property(lambda self: "T")

    @_live
    class Song(LomObject):
        tracks = property(lambda self: [Track(), Track()])

    types, _, _, _ = _walk(introspection, Song())

    assert types["Live.Fake.Song"]["example_paths"] == ["song"]
    assert types["Live.Fake.Track"]["example_paths"] == ["song.tracks[0]",
                                                         "song.tracks[1]"]


def test_a_none_root_is_skipped_rather_than_walked(introspection):
    types, totals, _, _ = introspection.walk_instances([("song", None)])
    assert types == {}
    assert totals["objects"] == 0


#--------------------------------------------------------------------------------
# The record shape. Pinned the way test_lom_gaps.py pins the generated report:
# lom_instances.json is an artefact other sessions read, and a silent change to
# its shape should be a failing test here rather than a broken consumer there.
#--------------------------------------------------------------------------------

def test_the_walk_returns_the_documented_totals_and_skipped_keys(introspection):
    @_live
    class Song(LomObject):
        tempo = property(lambda self: 120.0)

    _, totals, skipped, _ = _walk(introspection, Song())

    assert set(totals) == {"objects", "reads", "errors", "calls"}
    assert set(skipped) == {
        "methods_not_read_shaped", "methods_denylisted", "listeners_never_called",
        "depth_truncations", "cycle_hits", "vector_truncations",
    }


def test_a_type_entry_has_the_documented_shape(introspection):
    @_live
    class Song(LomObject):
        tempo = property(lambda self: 120.0)

    types, _, _, _ = _walk(introspection, Song())
    entry = types["Live.Fake.Song"]

    assert set(entry) == {"instances", "example_paths", "members"}
    assert set(entry["members"]["tempo"]) == {"kind", "reads", "types", "repr"}


#--------------------------------------------------------------------------------
# The two facts the first live run corrected. Both were wrong in the first
# implementation and the walk still "succeeded": it reported 2 objects, 0
# errors and a 4ms runtime, because a discriminator that matches nothing
# produces a clean empty result rather than a failure. These pin it.
#--------------------------------------------------------------------------------

def test_a_boost_python_leaf_module_name_still_yields_a_live_qualname(introspection):
    #--------------------------------------------------------------------------------
    # type(song).__module__ is "Song", not "Live.Song". Without the prefix the
    # keys here read "Song.Song" and cannot be compared against
    # lom_dump.json's "Live.Song.Song", which is the reason both dumps exist.
    #--------------------------------------------------------------------------------
    @_live
    class Song(LomObject):
        tempo = property(lambda self: 120.0)

    Song.__module__ = "Song"
    types, _, _, _ = _walk(introspection, Song())

    assert list(types) == ["Live.Song.Song"]


def test_an_already_qualified_module_is_not_prefixed_twice(introspection):
    @_live
    class Bridge(LomObject):
        pass

    Bridge.__module__ = "Live.Licensing"
    types, _, _, _ = _walk(introspection, Bridge())

    assert list(types) == ["Live.Licensing.Bridge"]


def test_an_object_without_lomobject_in_its_mro_is_not_walked_into(introspection):
    #--------------------------------------------------------------------------------
    # Base.Vector derives from Boost.Python.instance and nothing else. It is a
    # container to sample, never an object to walk, and the MRO check is what
    # keeps the two apart.
    #--------------------------------------------------------------------------------
    @_live
    class NotLive:
        pass

    @_live
    class Song(LomObject):
        thing = property(lambda self: NotLive())

    types, _, _, _ = _walk(introspection, Song())

    assert list(types) == ["Live.Fake.Song"]
    assert types["Live.Fake.Song"]["members"]["thing"]["types"] == {"NotLive": 1}


def test_a_fresh_wrapper_with_the_same_live_ptr_is_recognised_as_already_seen(introspection):
    #--------------------------------------------------------------------------------
    # The defect the second live run found. Boost.Python returns a *new* Python
    # wrapper on every property access, so `song.groove_pool.canonical_parent
    # is song` is False and an id()-keyed guard never fires. The first run
    # recorded one Song 11 times, spent its depth budget walking
    # groove_pool.canonical_parent in a circle, and never reached Song.tracks —
    # while reporting 0 errors, because a walk going in circles looks exactly
    # like a walk that worked.
    #
    # _live_ptr is Live's pointer to the underlying C++ object: stable across
    # wrappers, and the identity that actually terminates the walk.
    #--------------------------------------------------------------------------------
    @_live
    class Song(LomObject):
        _live_ptr = property(lambda self: 13434261240)
        #--------------------------------------------------------------------------------
        # A different Python object every access, exactly like Boost.Python.
        #--------------------------------------------------------------------------------
        canonical_parent = property(lambda self: Song())
        name = property(lambda self: "Song")

    types, _, skipped, _ = _walk(introspection, Song())

    assert types["Live.Fake.Song"]["instances"] == 1
    assert skipped["cycle_hits"] == 1
    assert skipped["depth_truncations"] == 0


def test_objects_without_a_live_ptr_still_fall_back_to_id(introspection):
    @_live
    class Leaf(LomObject):
        name = property(lambda self: "leaf")

    @_live
    class Holder(LomObject):
        first = property(lambda self: Holder._shared)
        second = property(lambda self: Holder._shared)

    Holder._shared = Leaf()
    types, _, skipped, _ = _walk(introspection, Holder())

    assert types["Live.Fake.Leaf"]["instances"] == 1
    assert skipped["cycle_hits"] == 1
