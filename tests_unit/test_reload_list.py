"""
Tripwire: manager.reload_imports() and the abletonosc package cannot drift.

`/live/api/reload` is how every handler change is tested inside Live, and its
failure mode is silence — a module missing from the reload sequence keeps
answering with its previous code while the log says `Reloaded code`. Nothing
outside Live calls reload_imports(), so no behavioural test can reach it:
manager.py imports ableton.v2, _Framework and Live at module scope, and
stubbing those to drive the reload would mean stubbing the very import
machinery under test.

So this file reads manager.py and abletonosc/*.py with `ast` and never imports
them, in the manner of test_live_suite_inert.py. It proves the *shape* of the
reload sequence, not that a reload works.

Two real defects motivated it, both invisible to the other 800 tests:

1. `abletonosc.introspection` was in the sequence but was imported only inside
   the /live/application/dump_lom callback, so on a session where that address
   had never been fired the reload raised AttributeError on it and skipped
   every module after it.
2. `abletonosc.constants` was in the package and in nothing else — absent from
   the sequence with no record that a running OSCServer cannot adopt new port
   constants without a Remote Script restart.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANAGER = REPO / "manager.py"
PACKAGE = REPO / "abletonosc"


def _manager_tree():
    return ast.parse(MANAGER.read_text())


def _reload_sequence():
    """The module names passed to _reload(), in source order."""
    fn = next(node for node in ast.walk(_manager_tree())
              if isinstance(node, ast.FunctionDef) and node.name == "reload_imports")
    return [node.args[0].value for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == "_reload"]


def _reload_exempt():
    for node in _manager_tree().body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "RELOAD_EXEMPT" for t in node.targets):
            return set(ast.literal_eval(node.value.args[0]))
    raise AssertionError("manager.py defines no module-level RELOAD_EXEMPT")


def _package_modules():
    #--------------------------------------------------------------------------------
    # __init__ is excluded: the package itself is reloaded last, as
    # importlib.reload(abletonosc), which is what re-executes __init__.py.
    #--------------------------------------------------------------------------------
    return {path.stem for path in PACKAGE.glob("*.py")} - {"__init__"}


def test_reload_sequence_is_not_empty():
    #--------------------------------------------------------------------------------
    # Guards the parser itself: if _reload() were renamed or inlined, every
    # other test here would pass vacuously against an empty sequence.
    #--------------------------------------------------------------------------------
    assert len(_reload_sequence()) > 10


def test_every_package_module_is_reloaded_or_exempt():
    sequence, exempt = set(_reload_sequence()), _reload_exempt()
    missing = _package_modules() - sequence - exempt
    assert not missing, (
        "abletonosc/%s.py is reloaded by nothing and recorded nowhere. Either add it to "
        "reload_imports() in the position its `from` imports require, or add it to "
        "RELOAD_EXEMPT with the reason written down. A module in neither goes on "
        "answering with stale code after /live/api/reload while the log reports success."
        % ".py, abletonosc/".join(sorted(missing)))


def test_reload_sequence_names_only_real_modules():
    #--------------------------------------------------------------------------------
    # The sequence names modules by string, so a typo or a deleted module is
    # not a NameError at edit time — it is an AttributeError mid-reload, which
    # aborts every module after it. That is exactly what introspection did.
    #--------------------------------------------------------------------------------
    unknown = set(_reload_sequence()) - _package_modules()
    assert not unknown, "reload_imports() names modules that do not exist: %s" % sorted(unknown)


def test_reload_sequence_has_no_duplicates():
    sequence = _reload_sequence()
    assert len(sequence) == len(set(sequence)), "a module is reloaded twice: %s" % sequence


def test_exempt_modules_are_not_also_reloaded():
    assert not (_reload_exempt() & set(_reload_sequence()))


def test_port_constants_are_restart_only():
    #--------------------------------------------------------------------------------
    # OSCServer copies its listen and response ports into instance state and
    # binds its socket in __init__. reload_imports() never replaces the
    # Manager's existing server, so reloading constants.py would report a port
    # edit as live while both ports remained unchanged. Keep the module exempt
    # until reload_imports() owns a safe server-replacement lifecycle.
    #--------------------------------------------------------------------------------
    assert "constants" in _reload_exempt()


def _module_scope_from_imports(path):
    """`from .X import name` at module scope -> {X}. `from . import X` is excluded."""
    #--------------------------------------------------------------------------------
    # The two forms differ in exactly the way that matters here. `from .X import
    # name` binds the *object* at import time, so reloading X afterwards leaves
    # the importer calling the previous definition — the silent stale-binding
    # failure the ordering comments in manager.py describe. `from . import X`
    # binds the module object itself, which importlib.reload mutates in place,
    # so its position in the sequence is not load-bearing.
    #--------------------------------------------------------------------------------
    deps = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            deps.add(node.module.split(".")[0])
    return deps


def test_from_imports_are_reloaded_before_their_importers():
    #--------------------------------------------------------------------------------
    # Derived from the source rather than hard-coded, so a new `from .x import
    # y` in a handler is checked the day it is written. This is the machine
    # form of every ordering comment in reload_imports(): track_identity before
    # song/track/view, path_safety before clip_slot/device/track, groove before
    # clip/song, track_callback before track, osc_server before handler.
    #--------------------------------------------------------------------------------
    position = {module: index for index, module in enumerate(_reload_sequence())}
    violations = []
    for path in sorted(PACKAGE.glob("*.py")):
        importer = path.stem
        if importer not in position:
            continue
        for dependency in sorted(_module_scope_from_imports(path)):
            if dependency in position and position[dependency] > position[importer]:
                violations.append("%s is reloaded at %d but `from .%s import ...` at %d"
                                  % (importer, position[importer], dependency,
                                     position[dependency]))
    assert not violations, (
        "reload order breaks a `from` import — the importer would keep calling the "
        "previous edit's objects while the log reports success:\n  " + "\n  ".join(violations))


def test_package_is_reloaded_last():
    #--------------------------------------------------------------------------------
    # importlib.reload(abletonosc) re-executes __init__.py over the modules
    # reloaded above it. Anything after it would be reloaded twice, and
    # __init__'s `from .x import Handler` lines would rebind to the older
    # definitions.
    #--------------------------------------------------------------------------------
    fn = next(node for node in ast.walk(_manager_tree())
              if isinstance(node, ast.FunctionDef) and node.name == "reload_imports")
    calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call)]
    package_reloads = [node for node in calls
                       if isinstance(node.func, ast.Attribute) and node.func.attr == "reload"
                       and node.args and isinstance(node.args[0], ast.Name)
                       and node.args[0].id == "abletonosc"]
    assert len(package_reloads) == 1, "expected exactly one importlib.reload(abletonosc)"
    last_module_reload = max(node.lineno for node in calls
                             if isinstance(node.func, ast.Name) and node.func.id == "_reload")
    assert package_reloads[0].lineno > last_module_reload


def test_the_package_reload_is_covered_by_the_failure_flag():
    #--------------------------------------------------------------------------------
    # importlib.reload(abletonosc) is the one reload in the sequence that does
    # not go through _reload(), because _reload() takes a submodule name. If it
    # raises with `failed` still None, the failure is logged and then
    # contradicted by "Reloaded code" — the very defect this function was
    # rewritten to remove, reintroduced at the last statement.
    #--------------------------------------------------------------------------------
    fn = next(node for node in ast.walk(_manager_tree())
              if isinstance(node, ast.FunctionDef) and node.name == "reload_imports")
    body = next(node.body for node in ast.walk(fn) if isinstance(node, ast.Try))
    index = next(i for i, stmt in enumerate(body)
                 if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                 and isinstance(stmt.value.func, ast.Attribute)
                 and stmt.value.func.attr == "reload"
                 and isinstance(stmt.value.args[0], ast.Name)
                 and stmt.value.args[0].id == "abletonosc")
    previous = body[index - 1]
    assert (isinstance(previous, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "failed" for t in previous.targets)
            and isinstance(previous.value, ast.Constant)
            and previous.value.value is not None), (
        "importlib.reload(abletonosc) must be preceded by `failed = <name>`, or a failure "
        "in it is reported as a success")


def test_introspection_is_imported_by_the_package_init():
    #--------------------------------------------------------------------------------
    # The direct regression guard. introspection exports no handler, so nothing
    # else in __init__.py would ever import it, and its only other importer
    # (application.py) is free to stop needing it. Without a binding here the
    # reload aborts on it on any fresh session.
    #--------------------------------------------------------------------------------
    imported = set()
    for node in ast.parse((PACKAGE / "__init__.py").read_text()).body:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                imported.add(node.module.split(".")[0])
            else:
                imported.update(alias.name for alias in node.names)
    assert "introspection" in imported, (
        "abletonosc/__init__.py must import introspection so that "
        "manager.reload_imports() has an attribute to reload")


def test_introspection_is_never_imported_inside_a_function():
    #--------------------------------------------------------------------------------
    # A lazy `from . import introspection` inside a callback is how the defect
    # was introduced: the attribute existed only after that callback had run,
    # so the reload aborted on a fresh session. A module-scope import anywhere
    # in the package is fine; a function-scope one reintroduces the bug.
    #--------------------------------------------------------------------------------
    offenders = []
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom) and inner.level == 1:
                    names = {alias.name for alias in inner.names} | {
                        (inner.module or "").split(".")[0]}
                    if "introspection" in names:
                        offenders.append("%s:%d" % (path.name, inner.lineno))
    assert not offenders, (
        "introspection imported inside a function body at %s — see this module's "
        "docstring" % ", ".join(offenders))


def test_success_is_logged_only_when_no_module_failed():
    #--------------------------------------------------------------------------------
    # reload_imports() swallows the exception and re-registers the API either
    # way, which is correct: a partial reload still leaves a usable server.
    # What must not happen is reporting that mixture as a success, which is
    # what an unconditional logger.info("Reloaded code") did.
    #--------------------------------------------------------------------------------
    fn = next(node for node in ast.walk(_manager_tree())
              if isinstance(node, ast.FunctionDef) and node.name == "reload_imports")
    guarded = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        for inner in ast.walk(node.test):
            if isinstance(inner, ast.Name) and inner.id == "failed":
                guarded.extend(
                    call for call in ast.walk(node)
                    if isinstance(call, ast.Call) and call.args
                    and isinstance(call.args[0], ast.Constant)
                    and call.args[0].value == "Reloaded code")
    assert guarded, (
        'logger.info("Reloaded code") must be guarded by a test of `failed`, so a '
        "reload that aborted part-way is not reported as a success")
