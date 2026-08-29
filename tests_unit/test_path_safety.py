"""
The fork's read-side path rule as a plain function.

`abletonosc/path_safety.py` imports only `os` and `typing`, so conftest's
synthetic-root loader reaches it with no stub at all — no Component, no empty
`Live`. That is the point of the module existing separately from the three
handlers that use it: the rule that decides which files Live is asked to open
is testable directly, exhaustively, with no handler in the way.

The three handlers that call it are driven end to end in
tests_unit/test_audio_clip_import.py.
"""

import os

import pytest

from .conftest import load_module


@pytest.fixture
def path_safety():
    return load_module("abletonosc.path_safety")


@pytest.fixture
def root(tmp_path):
    """
    A populated import root.

      kick.wav              a real file
      sub/snare.wav         a real file one level down
      inside.wav            a symlink to kick.wav, inside the root
      outside.wav           a symlink to a file outside the root
      dangling.wav          a symlink to nothing
      folder/               a directory

    Note that under macOS `tmp_path` is itself normally reached through a
    symlink (/tmp -> /private/tmp), so every test here also exercises the
    "root reached through a symlink" case by default.
    """
    (tmp_path / "root").mkdir()
    root = tmp_path / "root"
    (root / "kick.wav").write_bytes(b"RIFF")
    (root / "sub").mkdir()
    (root / "sub" / "snare.wav").write_bytes(b"RIFF")
    (root / "folder").mkdir()
    (tmp_path / "escape.wav").write_bytes(b"RIFF")
    os.symlink(str(root / "kick.wav"), str(root / "inside.wav"))
    os.symlink(str(tmp_path / "escape.wav"), str(root / "outside.wav"))
    os.symlink(str(root / "nothing-here.wav"), str(root / "dangling.wav"))
    return root


def resolve(path_safety, root, name):
    return path_safety.resolve_import_path(name, root=str(root))


def refuse(path_safety, root, name):
    with pytest.raises(path_safety.ImportPathError) as excinfo:
        resolve(path_safety, root, name)
    return str(excinfo.value)


#--------------------------------------------------------------------------------
# What the rule accepts
#--------------------------------------------------------------------------------

def test_a_bare_name_resolves_to_an_absolute_path(path_safety, root):
    resolved = resolve(path_safety, root, "kick.wav")
    assert os.path.isabs(resolved)
    assert os.path.isfile(resolved)
    assert os.path.basename(resolved) == "kick.wav"


def test_a_nested_relative_name_resolves(path_safety, root):
    resolved = resolve(path_safety, root, "sub/snare.wav")
    assert resolved == os.path.realpath(str(root / "sub" / "snare.wav"))


def test_the_root_may_itself_be_reached_through_a_symlink(path_safety, root, tmp_path):
    """
    The resolved path is compared against the *resolved* root, so a symlinked
    root does not make every name look like an escape. macOS makes this the
    default case under tmp_path (/tmp -> /private/tmp); assert it rather than
    rely on the accident.
    """
    link = tmp_path / "root-link"
    os.symlink(str(root), str(link))
    assert resolve(path_safety, link, "kick.wav") == \
        os.path.realpath(str(root / "kick.wav"))


def test_a_symlink_inside_the_root_to_a_file_inside_it_is_accepted(path_safety, root):
    """
    The rule is "resolves inside the root", not "is not a symlink" — the
    distinction Seshat must not assert the other way round in its tripwire.
    """
    assert resolve(path_safety, root, "inside.wav") == \
        os.path.realpath(str(root / "kick.wav"))


#--------------------------------------------------------------------------------
# What the rule refuses
#--------------------------------------------------------------------------------

def test_an_absolute_path_is_refused_and_the_message_names_the_root(path_safety, root):
    message = refuse(path_safety, root, str(root / "kick.wav"))
    assert str(root) in message
    #--------------------------------------------------------------------------------
    # The absolute-path refusal is the one a caller cannot diagnose without
    # being told where names resolve from, so it must be *this* refusal that
    # names the root, not the not-found one it would otherwise fall through to.
    #--------------------------------------------------------------------------------
    assert "absolute" in message


def test_an_absolute_path_outside_the_root_is_refused(path_safety, root, tmp_path):
    assert "absolute" in refuse(path_safety, root, str(tmp_path / "escape.wav"))


def test_a_parent_traversal_is_refused(path_safety, root):
    assert "outside" in refuse(path_safety, root, "../escape.wav")


def test_a_traversal_through_a_subdirectory_is_refused(path_safety, root):
    assert "outside" in refuse(path_safety, root, "sub/../../escape.wav")


def test_a_symlink_pointing_out_of_the_root_is_refused(path_safety, root):
    """
    The case the roadmap named, and the only one `realpath` is what catches:
    the joined path is inside the root by string, and its target is not.
    """
    assert "outside" in refuse(path_safety, root, "outside.wav")


def test_a_directory_is_refused(path_safety, root):
    assert "no such file" in refuse(path_safety, root, "folder")


def test_the_root_itself_is_refused(path_safety, root):
    assert refuse(path_safety, root, ".")


def test_a_dangling_symlink_is_refused(path_safety, root):
    assert "no such file" in refuse(path_safety, root, "dangling.wav")


def test_a_missing_file_is_refused(path_safety, root):
    assert "no such file" in refuse(path_safety, root, "nope.wav")


def test_the_empty_string_is_refused(path_safety, root):
    assert "empty" in refuse(path_safety, root, "")


def test_a_name_containing_a_null_byte_is_refused(path_safety, root):
    """
    Refused before anything touches the filesystem: os.path calls raise
    ValueError on an embedded NUL, which under a wildcard request would be a
    silent skip rather than a refusal.
    """
    assert "null" in refuse(path_safety, root, "kick\0.wav")


@pytest.mark.parametrize("name", [None, 3, 3.5, b"kick.wav", ["kick.wav"]])
def test_a_non_string_is_refused(path_safety, root, name):
    assert "string" in refuse(path_safety, root, name)


#--------------------------------------------------------------------------------
# The constant
#--------------------------------------------------------------------------------

def test_import_root_is_the_expanded_absolute_seshat_generated_directory(path_safety):
    assert path_safety.IMPORT_ROOT == \
        os.path.abspath(os.path.expanduser("~/.seshat/generated"))
    assert os.path.isabs(path_safety.IMPORT_ROOT)
    assert "~" not in path_safety.IMPORT_ROOT
    assert path_safety.IMPORT_ROOT.endswith(os.path.join(".seshat", "generated"))


def test_the_root_defaults_to_import_root_at_call_time(path_safety, root, monkeypatch):
    """
    `root=None` reads IMPORT_ROOT when it is called, not when the module was
    imported — which is what lets the handler tests point the whole rule at a
    tmp directory by monkeypatching one module attribute.
    """
    monkeypatch.setattr(path_safety, "IMPORT_ROOT", str(root))
    assert path_safety.resolve_import_path("kick.wav") == \
        os.path.realpath(str(root / "kick.wav"))


def test_the_module_imports_no_live_module(path_safety):
    """
    The property the whole design rests on: this module is reachable with no
    stub at all, so the rule under test is the shipped rule.
    """
    assert path_safety.__name__.endswith("abletonosc.path_safety")
    with open(path_safety.__file__) as f:
        source = f.read()
    assert "\nimport Live" not in source
    assert "from .handler" not in source
