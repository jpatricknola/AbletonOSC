"""
Declaration contract of every AbletonOSCHandler subclass, checked statically.

`class_identifier` is wire identity: listener pushes go out on
"/live/<class_identifier>/get/<prop>" and every handler log line names it.
The shipped fix for the base constructor made it a *class* attribute set in
the class statement, so it is already correct when init_api() registers
routes, and deleted every subclass __init__ so the base's documented order
(Component.__init__ -> invariants -> init_state() -> init_api()) is the only
constructor that runs.

test_handler_lifecycle.py pins the base half of that by construction, but
not every production subclass is within the behavioural layer's reach: eight
of the twelve are loaded and driven end to end today (device, scene,
clip_slot, track, clip, song, view, application — see
test_device_listeners.py, test_listener_identity.py, test_object_reads.py,
test_song_object_reads.py, test_view_object_reads.py and
test_application.py), while browser.py, midimap.py, return_track.py and
song_structure.py have no conftest loader yet. So a
typo'd identifier in one of those four, or a merge that restores
upstream's `self.class_identifier = ...` inside a subclass __init__ - which
shadows the class attribute *after* init_api() ran - would pass the whole
suite green and surface only as listener pushes on the wrong address, in
Live, later.

This file closes that gap without importing anything. It parses
abletonosc/*.py with `ast`, resolves the subclasses of AbletonOSCHandler
transitively over the class names it collects, and pins their declarations:
the identifier map below, exactly one class-body assignment of it, no
__init__, and no assignment to self.class_identifier anywhere. It proves
nothing about behaviour - that is the behavioural layers' job - only that
the declarations still say what the wire contract assumes.

See SESHAT.md, "Merge hazards".
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "abletonosc"

BASE_CLASS = "AbletonOSCHandler"

#--------------------------------------------------------------------------------
# The expected identifier map, keyed by (module filename, class name).
#
# Each value is the "<class_identifier>" half of that handler's
# /live/<class_identifier>/get/<prop> listener-push addresses. Adding a
# handler module fails this test until its row is added here: that tripwire
# is the point, and API.md is where the new addresses get documented.
#
# Two rows are deliberately irregular and must not be "corrected":
#
#  - song_structure.py -> "song": SongStructureHandler shares SongHandler's
#    push namespace on purpose; its listeners push /live/song/get/...
#    (the class body carries a comment saying so).
#
#  - return_track.py -> "return_track": ReturnTrackHandler additionally
#    registers /live/master/* addresses as hand-built strings. The
#    identifier governs its log lines and identifier-derived pushes only;
#    this map is not a claim that one handler owns exactly one /live/<x>/
#    prefix.
#--------------------------------------------------------------------------------
EXPECTED_IDENTIFIERS = {
    ("application.py", "ApplicationHandler"): "application",
    ("browser.py", "BrowserHandler"): "browser",
    ("clip.py", "ClipHandler"): "clip",
    ("clip_slot.py", "ClipSlotHandler"): "clip_slot",
    ("device.py", "DeviceHandler"): "device",
    ("midimap.py", "MidiMapHandler"): "midimap",
    ("return_track.py", "ReturnTrackHandler"): "return_track",
    ("scene.py", "SceneHandler"): "scene",
    ("song.py", "SongHandler"): "song",
    ("song_structure.py", "SongStructureHandler"): "song",
    ("track.py", "TrackHandler"): "track",
    ("view.py", "ViewHandler"): "view",
}


def _base_names(class_def):
    """
    The terminal identifier of each base of `class_def`: "Foo" for both
    `class X(Foo)` and `class X(module.Foo)`. Anything more exotic (a
    subscripted generic, a call) contributes no name.
    """
    names = []
    for base in class_def.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _collect_classes():
    """
    Every top-level-or-nested ClassDef across abletonosc/*.py, as
    {class name: [(module filename, ClassDef), ...]}.

    Keyed by name only, and a name may have more than one occurrence - e.g. an
    unrelated private helper class of the same name in two different modules,
    nowhere near the handler hierarchy. Whether that duplication is actually a
    problem depends on whether the name ever enters the AbletonOSCHandler
    closure; `_handler_subclasses()` is where that is decided and asserted,
    not here.
    """
    classes = {}
    sources = sorted(PACKAGE_DIR.glob("*.py"))
    assert sources, "no sources found in %s" % PACKAGE_DIR

    for path in sources:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.setdefault(node.name, []).append((path.name, node))
    return classes


def _handler_subclasses():
    """
    The transitive subclasses of AbletonOSCHandler, as
    {(module filename, class name): ClassDef}.

    Transitive, not direct-base-only, so a future `class FooHandler(TrackHandler)`
    is held to the same invariants instead of escaping the walk.
    """
    classes = _collect_classes()
    assert BASE_CLASS in classes, (
        "%s not found in %s - has handler.py moved or been renamed?"
        % (BASE_CLASS, PACKAGE_DIR)
    )

    reachable = {BASE_CLASS}
    changed = True
    while changed:
        changed = False
        for name, occurrences in classes.items():
            if name in reachable:
                continue
            if any(base in reachable
                   for _filename, class_def in occurrences
                   for base in _base_names(class_def)):
                reachable.add(name)
                changed = True

    handler_names = reachable - {BASE_CLASS}
    for name in handler_names:
        occurrences = classes[name]
        assert len(occurrences) == 1, (
            "handler subclass %s is defined in more than one module (%s); "
            "the subclass contract needs one unambiguous definition per name "
            "to check invariants against" % (name, ", ".join(f for f, _ in occurrences))
        )

    return {
        (classes[name][0][0], name): classes[name][0][1]
        for name in handler_names
    }


SUBCLASSES = _handler_subclasses()


def _class_body_identifier_assignments(class_def):
    """
    The class-body statements assigning `class_identifier`, annotated
    (`x: T = ...`, the form the base uses) or plain. Only the class body
    itself - assignments inside methods are check 4's business.
    """
    found = []
    for statement in class_def.body:
        if isinstance(statement, ast.AnnAssign):
            target = statement.target
            if isinstance(target, ast.Name) and target.id == "class_identifier":
                found.append(statement.value)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id == "class_identifier":
                    found.append(statement.value)
    return found


def _self_identifier_assignments(class_def):
    """
    Every `self.class_identifier = ...` (or `+=`, or annotated) anywhere in
    the class body, as a list of line numbers.
    """
    lines = []

    def is_self_identifier(node):
        return (isinstance(node, ast.Attribute)
                and node.attr == "class_identifier"
                and isinstance(node.value, ast.Name)
                and node.value.id == "self")

    for node in ast.walk(class_def):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        if any(is_self_identifier(target) for target in targets):
            lines.append(node.lineno)
    return lines


def _init_definitions(class_def):
    """Line numbers of any `def __init__` in the class body."""
    return [node.lineno
            for node in ast.walk(class_def)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"]


#--------------------------------------------------------------------------------
# 1. Discovery matches the expected map, both directions. A vacuous walk -
#    zero or a handful of classes found - is this file's own failure mode,
#    and this two-way equality is what catches it.
#--------------------------------------------------------------------------------
def test_discovered_subclasses_match_expected_map():
    discovered = set(SUBCLASSES)
    expected = set(EXPECTED_IDENTIFIERS)

    unexpected = sorted(discovered - expected)
    missing = sorted(expected - discovered)

    assert not unexpected, (
        "handler subclasses found in abletonosc/ with no row in "
        "EXPECTED_IDENTIFIERS: %s. Add each with its class_identifier - the "
        "identifier is the /live/<x>/get/<prop> namespace its listener pushes "
        "use, and API.md must document its addresses." % unexpected
    )
    assert not missing, (
        "EXPECTED_IDENTIFIERS names handler subclasses that no longer exist "
        "in abletonosc/: %s. If they were renamed or removed deliberately, "
        "update this map, SESHAT.md and API.md together." % missing
    )
    assert len(discovered) == len(EXPECTED_IDENTIFIERS)


#--------------------------------------------------------------------------------
# 2. Each subclass declares class_identifier in its class body, exactly once,
#    as a plain string constant matching the map. A computed identifier would
#    defeat static verification; none exists today.
#--------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(EXPECTED_IDENTIFIERS), ids=lambda key: "%s::%s" % key)
def test_subclass_declares_expected_class_identifier(key):
    filename, class_name = key
    class_def = SUBCLASSES.get(key)
    assert class_def is not None, (
        "%s.%s was not found; test_discovered_subclasses_match_expected_map "
        "explains the mismatch" % (filename, class_name)
    )

    assignments = _class_body_identifier_assignments(class_def)
    assert len(assignments) == 1, (
        "%s.%s must assign class_identifier exactly once in its class body "
        "(found %d). It is set in the class statement so that it is already "
        "correct when init_api() registers routes."
        % (filename, class_name, len(assignments))
    )

    value = assignments[0]
    assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
        "%s.%s must assign class_identifier a plain string literal, not a "
        "computed value: a runtime-derived identifier cannot be verified "
        "statically, and this attribute is wire identity."
        % (filename, class_name)
    )
    assert value.value == EXPECTED_IDENTIFIERS[key], (
        "%s.%s declares class_identifier = %r, expected %r. Listener pushes "
        "go out on /live/<class_identifier>/get/<prop>, so this rename moves "
        "addresses: change API.md and Seshat's decoding with it, or fix the "
        "typo." % (filename, class_name, value.value, EXPECTED_IDENTIFIERS[key])
    )


#--------------------------------------------------------------------------------
# 3. No subclass defines __init__. The base's constructor order is the only
#    one that runs; init_state() is the documented home for subclass state.
#--------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(EXPECTED_IDENTIFIERS), ids=lambda key: "%s::%s" % key)
def test_subclass_defines_no_init(key):
    filename, class_name = key
    class_def = SUBCLASSES.get(key)
    assert class_def is not None, (
        "%s.%s was not found; test_discovered_subclasses_match_expected_map "
        "explains the mismatch" % (filename, class_name)
    )

    lines = _init_definitions(class_def)
    assert not lines, (
        "%s.%s defines __init__ (line(s) %s). Subclasses must not: the base "
        "AbletonOSCHandler.__init__ establishes listener_functions, "
        "listener_objects and class_identifier before calling init_state() "
        "then init_api(), and a subclass constructor either re-runs or "
        "pre-empts that order. Put subclass state in init_state()."
        % (filename, class_name, lines)
    )


#--------------------------------------------------------------------------------
# 4. No subclass assigns self.class_identifier, anywhere. This is the actual
#    merge hazard: upstream's shape sets it in __init__, where it shadows the
#    class attribute after init_api() has already read it - and the same line
#    pasted into init_state() shadows identity just as silently.
#--------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(EXPECTED_IDENTIFIERS), ids=lambda key: "%s::%s" % key)
def test_subclass_never_assigns_self_class_identifier(key):
    filename, class_name = key
    class_def = SUBCLASSES.get(key)
    assert class_def is not None, (
        "%s.%s was not found; test_discovered_subclasses_match_expected_map "
        "explains the mismatch" % (filename, class_name)
    )

    lines = _self_identifier_assignments(class_def)
    assert not lines, (
        "%s.%s assigns self.class_identifier (line(s) %s). That instance "
        "attribute shadows the class attribute, and any assignment reached "
        "after init_api() leaves routes registered against one identifier "
        "while pushes use another. Declare it in the class statement instead."
        % (filename, class_name, lines)
    )
