"""
Tripwire: importing tests/ must never touch Ableton Live.

tests/ is the opt-in live-integration suite. Upstream's tests/__init__.py
constructed an AbletonOSCClient at module scope and sent /live/api/reload from
it, so merely collecting tests from the repository root bound the OSC reply
port and reloaded the bridge under whatever session the user had open. That is
fixed by moving the client into a session-scoped fixture gated on
ABLETONOSC_LIVE_TESTS=1 (tests/conftest.py) - but the fix lives in files
upstream also edits, so a merge that takes upstream's tests/__init__.py would
silently restore the defect.

This test is the guard. It reads the files with `ast` and never imports them:
importing tests/ to check that importing tests/ is safe would defeat the
purpose, and would need the vendored pythonosc besides. It is deliberately
narrow - it proves nothing happens *at import time*, not that the tests
themselves are correct.

See SESHAT.md, "Merge hazards".
"""

import ast
from pathlib import Path

import pytest

#--------------------------------------------------------------------------------
# Constructing the client binds the reply port; the four send/query methods put
# datagrams on the wire. None of them may be reached by importing a module.
#--------------------------------------------------------------------------------
FORBIDDEN_CALLS = {
    "AbletonOSCClient",
    "send_message",
    "send_bundle",
    "query",
    "await_message",
}

LIVE_SUITE_DIR = Path(__file__).resolve().parent.parent / "tests"


def _live_suite_sources():
    return sorted(LIVE_SUITE_DIR.glob("*.py"))


def _import_time_nodes(node):
    """
    Yield the nodes that are evaluated when the module is imported: everything
    at module scope, plus decorators and argument defaults of the functions and
    classes defined there - but not the bodies of those functions and classes,
    which only run when something calls them.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in child.decorator_list:
                yield from ast.walk(decorator)
            if isinstance(child, ast.ClassDef):
                for base in child.bases:
                    yield from ast.walk(base)
            else:
                yield from ast.walk(child.args)
            continue
        yield child
        yield from _import_time_nodes(child)


def _called_name(node):
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def test_live_suite_directory_is_where_this_test_expects():
    #--------------------------------------------------------------------------------
    # Without this, renaming or moving tests/ would turn every assertion below into
    # a vacuous pass over an empty file list.
    #--------------------------------------------------------------------------------
    assert LIVE_SUITE_DIR.is_dir(), "%s not found" % LIVE_SUITE_DIR
    sources = _live_suite_sources()
    assert len(sources) >= 2
    names = {path.name for path in sources}
    assert "__init__.py" in names
    assert "conftest.py" in names


@pytest.mark.parametrize("path", _live_suite_sources(), ids=lambda path: path.name)
def test_live_suite_module_sends_nothing_at_import_time(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = []
    for node in _import_time_nodes(tree):
        if isinstance(node, ast.Call):
            name = _called_name(node)
            if name in FORBIDDEN_CALLS:
                offenders.append("%s() at line %d" % (name, node.lineno))
    assert not offenders, (
        "%s reaches Ableton Live at import time: %s. The live suite must be "
        "inert until the ABLETONOSC_LIVE_TESTS-gated client fixture in "
        "tests/conftest.py runs. If this fired after an upstream merge, the "
        "merge restored upstream's module-scope client - see SESHAT.md, "
        "\"Merge hazards\"." % (path.name, ", ".join(offenders))
    )


def test_live_suite_is_gated_on_the_opt_in_environment_variable():
    #--------------------------------------------------------------------------------
    # The gate itself: a conftest that no longer consults the variable would leave
    # every module import-inert and still fire on collection with Live running.
    #--------------------------------------------------------------------------------
    source = (LIVE_SUITE_DIR / "conftest.py").read_text()
    assert "ABLETONOSC_LIVE_TESTS" in source
