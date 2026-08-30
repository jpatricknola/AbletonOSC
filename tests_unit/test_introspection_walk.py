"""
The LOM walker, driven over synthetic modules instead of Live.

introspection.py is what produces lom_dump.json, which is what FORK_GAPS.md is
generated from, so a member the walker drops is a member the fork's own gap
inventory cannot see. It used to drop every member registered directly on a
module — Boost.Python free functions — which is why Live.Conversions appeared
in the dump as nothing but its AudioToMidiType enum while the seven members
that carry Live's audio-to-MIDI conversion were invisible. See BLIND_SPOTS.md.

The walker takes its root module as an argument, so these tests hand it a
module tree built here and never import Live. What they prove is the shape of
the recorded dump, not that Live's own modules contain anything in particular.
"""

import types

import pytest

from .conftest import load_module


@pytest.fixture
def introspection():
    return load_module("abletonosc.introspection")


def _module(name, **members):
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    return module


def _walk(introspection, root, root_name="Live"):
    classes, seen = {}, set()
    introspection._visit_module(root, root_name, classes, seen)
    return classes


def test_module_level_function_is_recorded_with_its_docstring(introspection):
    #--------------------------------------------------------------------------------
    # The regression this file exists for. Boost.Python keeps the signature in
    # the docstring, so the docstring is the whole value of the record.
    #--------------------------------------------------------------------------------
    def audio_to_midi_clip(clip, kind):
        """audio_to_midi_clip( (Clip)arg1, (AudioToMidiType)arg2) -> None :"""

    conversions = _module("Conversions", audio_to_midi_clip=audio_to_midi_clip)
    live = _module("Live", Conversions=conversions)

    walked = _walk(introspection, live)

    assert "Live.Conversions" in walked
    member = walked["Live.Conversions"]["members"]["audio_to_midi_clip"]
    assert member["kind"] == "method"
    assert member["doc"].startswith("audio_to_midi_clip(")


def test_module_entries_are_marked_as_modules(introspection):
    #--------------------------------------------------------------------------------
    # Module and class entries share one dict, so the consumer needs to tell
    # them apart: tools/lom_gaps.py reports them in a separate section.
    #--------------------------------------------------------------------------------
    live = _module("Live", Conversions=_module("Conversions", f=lambda: None))
    walked = _walk(introspection, live)
    assert walked["Live.Conversions"].get("kind") == "module"


def test_class_entries_are_not_marked_as_modules(introspection):
    class Clip:
        pass

    walked = _walk(introspection, _module("Live", Clip=Clip))
    assert "kind" not in walked["Live.Clip"]


def test_module_with_no_members_of_its_own_is_not_recorded(introspection):
    #--------------------------------------------------------------------------------
    # Most Live submodules carry only classes. Recording an empty entry for
    # each would inflate the walked count and the generated header line.
    #--------------------------------------------------------------------------------
    class Clip:
        pass

    walked = _walk(introspection, _module("Live", Clip_=_module("Clip", Clip=Clip)))
    assert "Live.Clip_" not in walked
    assert "Live.Clip_.Clip" in walked


def test_classes_are_still_walked_alongside_module_members(introspection):
    #--------------------------------------------------------------------------------
    # The fix adds a branch; it must not cost the branches that were there.
    # Live.Conversions is exactly this shape: an enum class beside free
    # functions, and only the enum used to survive.
    #--------------------------------------------------------------------------------
    class AudioToMidiType:
        harmony_to_midi = 0

    conversions = _module("Conversions",
                          AudioToMidiType=AudioToMidiType,
                          is_convertible_to_midi=lambda clip: True)
    walked = _walk(introspection, _module("Live", Conversions=conversions))

    assert "Live.Conversions.AudioToMidiType" in walked
    assert "harmony_to_midi" in walked["Live.Conversions.AudioToMidiType"]["members"]
    assert "is_convertible_to_midi" in walked["Live.Conversions"]["members"]


def test_module_constants_are_recorded_as_values(introspection):
    #--------------------------------------------------------------------------------
    # Not every module-level member is callable. Live.Application.Variants is
    # a class of six such constants, and the value set of
    # /live/application/get/variant is still marked unmeasured in API.md
    # partly because they were never recorded.
    #--------------------------------------------------------------------------------
    walked = _walk(introspection, _module("Live", Mod=_module("Mod", SUITE="Suite")))
    member = walked["Live.Mod"]["members"]["SUITE"]
    assert member["kind"] == "value"
    assert member["type"] == "str"


def test_dunder_members_are_skipped(introspection):
    walked = _walk(introspection, _module("Live", Mod=_module("Mod", f=lambda: None)))
    assert all(not name.startswith("__") for name in walked["Live.Mod"]["members"])


def test_a_member_that_raises_on_access_is_recorded_as_an_error(introspection):
    #--------------------------------------------------------------------------------
    # A Live property can raise rather than return; the walk must record that
    # and continue rather than abandoning the rest of the module.
    #--------------------------------------------------------------------------------
    class Exploding(types.ModuleType):
        #--------------------------------------------------------------------------------
        # dir() on a module reads its __dict__, so an attribute that raises has
        # to be advertised by __dir__ and withheld by __getattr__ — which is
        # the shape a Boost.Python module presents when a member is registered
        # but unreadable in the current session.
        #--------------------------------------------------------------------------------
        def __dir__(self):
            return ["boom", "fine"]

        def __getattr__(self, name):
            if name == "boom":
                raise RuntimeError("no")
            raise AttributeError(name)

    module = Exploding("Mod")
    module.fine = lambda: None
    walked = _walk(introspection, _module("Live", Mod=module))

    assert walked["Live.Mod"]["members"]["boom"]["kind"] == "error"
    assert "fine" in walked["Live.Mod"]["members"]


def test_a_module_cycle_terminates(introspection):
    #--------------------------------------------------------------------------------
    # Live's submodules import each other. The `seen` set is what stops the
    # walk; the fix must not reach a module twice by a second path either.
    #--------------------------------------------------------------------------------
    a = _module("A", f=lambda: None)
    b = _module("B", A=a, g=lambda: None)
    a.B = b
    walked = _walk(introspection, _module("Live", A=a))
    assert set(walked) == {"Live.A", "Live.A.B"}


def test_the_same_class_is_recorded_once_under_its_first_qualname(introspection):
    class Shared:
        pass

    walked = _walk(introspection, _module("Live", Alpha=Shared, Beta=Shared))
    assert ("Live.Alpha" in walked) != ("Live.Beta" in walked)
