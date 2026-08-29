#--------------------------------------------------------------------------------
# The fork's one rule for an address whose argument names a file to *read*.
#
# Seshat extension — see SESHAT.md. Upstream has no equivalent, because upstream
# exposes no address that opens a caller-named file at all.
#
# Three LOM members take a filesystem path and open it with Live's privileges:
# Track.create_audio_clip, ClipSlot.create_audio_clip and
# SimplerDevice.replace_sample. All three are reachable over OSC as of this
# module, and all three resolve their argument through resolve_import_path()
# below rather than handing the wire string to Live.
#
# The wire never carries a path. It carries a *name relative to IMPORT_ROOT*,
# and this module builds the absolute path itself. Given a fixed root an
# absolute argument could only ever name files the relative form already names,
# so accepting one buys the caller nothing while keeping exactly the
# "caller-supplied path opened with Live's privileges" shape the rule exists to
# remove. A bare `foo.wav` is the normal form; `sub/foo.wav` also resolves.
#
# Both sides are `realpath`ed, and this is deliberately the *opposite* of
# browser.py's EXPORT_ROOT, which is `abspath` + `expanduser` and explicitly not
# `realpath`. The two are not inconsistent, and a reader who "fixes" either to
# match the other breaks it:
#
#   - browser.py:122-130 must not resolve symlinks, because Seshat re-derives
#     that same root string in Elixir with Path.expand/1, which does not resolve
#     them; a symlinked ~/.seshat would put the exported file under the link
#     target and fail the consumer's root check on every reindex. The path it
#     produces is *published on the wire* and has to match, character for
#     character, a path derived elsewhere.
#   - here the resolved path is internal — it goes to Live and nowhere else,
#     and the reply echoes what the caller sent — so resolving both sides costs
#     nothing and is precisely what makes the escape check work: it is what
#     defeats a `..` component and a symlink inside the root pointing out of it.
#     Comparing an unresolved join against an unresolved root would accept both.
#
# This is the **read**-side rule. The write-side rule is browser/export's: take
# no destination from the wire at all, choose one inside a private root, and
# reply with the absolute path actually written. They differ because a read has
# to name *which* existing file, and a write does not.
#
# One known outstanding violation of the write-side rule remains, and this
# module does not cover it: /live/application/dump_lom still takes an arbitrary
# wire path and writes it with Live's privileges (issues.md, Low). It should
# adopt browser/export's pattern, not this one.
#
# The command socket is loopback-only (PR d863361), so a caller reaching any of
# these addresses is already local code running as the user and could read the
# file without Live. That is why the read-side answer can be a bounded root at
# all rather than export's no-argument form.
#
# Imports `os` and `typing` and nothing else — no Live, no .handler — so the
# rule is directly unit-testable as a plain function (tests_unit/
# test_path_safety.py) as well as through all three handlers
# (tests_unit/test_audio_clip_import.py), and is identical in all three rather
# than copied three times.
#--------------------------------------------------------------------------------

import os
from typing import Optional

#--------------------------------------------------------------------------------
# The one import root, on one line, deliberately: Seshat's
# vendored_addresses_test asserts this literal the way it asserts EXPORT_ROOT.
# The value is part of the fork/consumer contract — it is fixed by
# ~/seshat/docs/PLAN_generate_audio_clip.md, which states that changing the
# folder means changing this constant too. No environment variable redirects it.
#
# The root is never created here. browser/export creates its *write* root on
# demand; a read root that does not exist simply refuses everything, and
# creating directories in the user's home in order to read is unearned. The
# consumer creates it (mode 0700, alongside ~/.seshat/browser-exports).
#--------------------------------------------------------------------------------
IMPORT_ROOT = os.path.abspath(os.path.expanduser("~/.seshat/generated"))


class ImportPathError(Exception):
    """
    A wire-supplied name that the import rule refuses.

    Carries a caller-facing message: the handlers turn it into the `"error"`
    reply on the address the request arrived on, so the message is the only
    thing a caller ever learns about why the file was not opened.
    """


def resolve_import_path(name, root: Optional[str] = None) -> str:
    """
    Resolve a wire-supplied `name` to an absolute path inside the import root,
    or raise `ImportPathError`.

    Args:
        name: The name as it arrived on the wire — a path *relative to the
              root*. Not an absolute path; not a `Path`.
        root: The root to resolve against. `None` (the default) means
              `IMPORT_ROOT`, read at **call time** rather than bound at import
              time, so a test can point the rule at a tmp directory without
              monkeypatching module internals.

    Returns the absolute, symlink-resolved path to hand to Live. Nothing is
    opened here; the caller must not touch Live on a rejection.
    """
    if root is None:
        root = IMPORT_ROOT

    if not isinstance(name, str):
        raise ImportPathError("name must be a string, got %s" % type(name).__name__)
    if name == "":
        raise ImportPathError("name must not be empty")
    if "\0" in name:
        raise ImportPathError("name must not contain a null byte")
    if os.path.isabs(name):
        #--------------------------------------------------------------------------------
        # The root is named in this message on purpose: it is the one refusal a
        # caller cannot diagnose otherwise, because nothing else on the wire
        # tells it where names are resolved from.
        #--------------------------------------------------------------------------------
        raise ImportPathError(
            "name must be relative to the import root %s, not an absolute path: %s"
            % (root, name))

    resolved_root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(resolved_root, name))

    #--------------------------------------------------------------------------------
    # Strictly under the root: the root itself is a rejection (it is a
    # directory, and step 5 would refuse it anyway, but saying so here gives the
    # better message). Both sides are resolved, so a symlinked ~/.seshat
    # compares equal against itself, and a symlink *inside* the root has already
    # become its target — accepted when the target is also inside, refused when
    # it is not. That is "resolves inside the root", not "is not a symlink".
    #--------------------------------------------------------------------------------
    if not candidate.startswith(resolved_root + os.sep):
        raise ImportPathError(
            "name resolves outside the import root %s: %s" % (root, name))

    #--------------------------------------------------------------------------------
    # Already resolved, so this one check refuses a directory, a dangling
    # symlink, a missing file and a device node alike.
    #--------------------------------------------------------------------------------
    if not os.path.isfile(candidate):
        raise ImportPathError(
            "no such file in the import root %s: %s" % (root, name))

    return candidate
