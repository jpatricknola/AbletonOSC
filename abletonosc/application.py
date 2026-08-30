import Live
import os
import string
from functools import partial
from typing import Any, Tuple
from .handler import AbletonOSCHandler
#--------------------------------------------------------------------------------
# Module scope, not inside the dump_lom callback. A submodule becomes an
# attribute of its package only once something imports it, and while this was
# the only import of introspection anywhere it existed only after
# /live/application/dump_lom had been fired at least once — so on a fresh
# session manager.reload_imports() raised AttributeError on it and skipped
# every module after it while still logging "Reloaded code". introspection
# imports nothing from Live at module scope (both `import Live` statements are
# inside its functions), so importing it here costs nothing at startup.
#--------------------------------------------------------------------------------
from . import introspection

#--------------------------------------------------------------------------------
# Seshat extension — the module seam.
#
# Every address below needs the one application object, and it is resolved
# once at init_api() time. This one-line indirection exists so that
# tests_unit/ can substitute a fake application before constructing the
# handler: it is the application-object image of conftest.py's bind_song(),
# and it keeps conftest's deliberately *empty* Live stub empty. Giving that
# stub a Live.Application.get_application() would be the first piece of
# pretend Live *behaviour* in the suite, which the conftest docstring rules
# out on purpose.
#
# Resolving at init_api() time is safe in production: manager.py constructs
# every handler inside ControlSurface.component_guard(), with Live fully up,
# and ableton.v2's own components call Live.Application.get_application()
# during construction.
#--------------------------------------------------------------------------------
def get_application():
    return Live.Application.get_application()


#--------------------------------------------------------------------------------
# Seshat extension — the length Live requires of an option key. See the
# comment above get_has_option in init_api(); measured against Live 12.4.5 on
# 2026-08-29.
#--------------------------------------------------------------------------------
HAS_OPTION_KEY_LENGTH = 64


class ApplicationHandler(AbletonOSCHandler):
    class_identifier = "application"

    def init_api(self):
        #--------------------------------------------------------------------------------
        # Generic callbacks
        #--------------------------------------------------------------------------------
        def get_version(_) -> Tuple:
            application = Live.Application.get_application()
            return application.get_major_version(), application.get_minor_version()
        self.osc_server.add_handler("/live/application/get/version", get_version)
        self.osc_server.send("/live/startup")

        def get_average_process_usage(_) -> Tuple:
            application = Live.Application.get_application()
            return application.average_process_usage,
        self.osc_server.add_handler("/live/application/get/average_process_usage", get_average_process_usage)

        #--------------------------------------------------------------------------------
        # Seshat extension — see SESHAT.md and FORK_GAPS.md.
        # /live/application/dump_lom [path] writes the installed Live API's full
        # class/member surface plus this server's registered addresses to a JSON
        # file (default logs/lom_dump.json). client/lom_gaps.py diffs the two.
        #--------------------------------------------------------------------------------
        def dump_lom(params: Tuple[Any] = ()) -> Tuple:
            if len(params) >= 1 and params[0]:
                path = params[0]
            else:
                module_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
                path = os.path.join(module_path, "logs", "lom_dump.json")
            return introspection.dump_lom(path, self.osc_server)
        self.osc_server.add_handler("/live/application/dump_lom", dump_lom)

        #--------------------------------------------------------------------------------
        # Seshat extension — the rest of the application-level surface.
        # See SESHAT.md ("Additions to upstream's code") and API.md
        # § "Application API". Everything here is read-only except the two
        # show_* message methods, and none of it takes an index or a wildcard.
        #--------------------------------------------------------------------------------
        application = get_application()

        #--------------------------------------------------------------------------------
        # Plain scalars, through the base class's generic property loop. Two
        # lists, not one: only open_dialog_count and peak_process_usage are
        # observable (Live offers add_<name>_listener for them and not for the
        # two current_dialog_* members), so registering a listen pair for the
        # rest would only manufacture /live/error AttributeErrors. The
        # dialog-detection pattern is therefore "listen on the count, read the
        # message and button count when it changes" — documented in API.md.
        #--------------------------------------------------------------------------------
        properties_r = [
            "open_dialog_count",
            "current_dialog_message",
            "current_dialog_button_count",
            "peak_process_usage",
            "number_of_push_apps_running",
        ]
        properties_listen = [
            "open_dialog_count",
            "peak_process_usage",
        ]

        for prop in properties_r:
            self.osc_server.add_handler("/live/application/get/%s" % prop,
                                        partial(self._get_property, application, prop))
        for prop in properties_listen:
            self.osc_server.add_handler("/live/application/start_listen/%s" % prop,
                                        partial(self._start_listen, application, prop))
            self.osc_server.add_handler("/live/application/stop_listen/%s" % prop,
                                        partial(self._stop_listen, application, prop))

        #--------------------------------------------------------------------------------
        # The exact version identity. Upstream's get/version answers
        # (major, minor) only, so a client knows "12.4" but not "12.4.3", the
        # build it is talking to, or Suite vs Standard — all of which decide
        # whether a given LOM member exists at all.
        #--------------------------------------------------------------------------------
        def get_bugfix_version(_) -> Tuple:
            return application.get_bugfix_version(),
        self.osc_server.add_handler("/live/application/get/bugfix_version", get_bugfix_version)

        def get_build_id(_) -> Tuple:
            return application.get_build_id(),
        self.osc_server.add_handler("/live/application/get/build_id", get_build_id)

        def get_variant(_) -> Tuple:
            return application.get_variant(),
        self.osc_server.add_handler("/live/application/get/variant", get_variant)

        def get_version_string(_) -> Tuple:
            return application.get_version_string(),
        self.osc_server.add_handler("/live/application/get/version_string", get_version_string)

        #--------------------------------------------------------------------------------
        # The option-key lookup. NOT an Options.txt query — it shipped
        # documented as one on 2026-08-29 and was measured not to be one the
        # same day; see API.md's "Partially measured against Live 12.4.5"
        # note for the accept/reject table this validator encodes.
        #
        # Live's Application.has_option takes a *key*: exactly 64 hexadecimal
        # characters, case-insensitive, which is a digest of an internal Live
        # option name. Ableton publishes no name-to-key mapping, and the
        # digest is not a plain SHA-256 of the identifier it guards. The one
        # real key readable anywhere is in Live's own shipped Python —
        # abl/live/licensing/__init__.pyc calls
        # has_option("fbb8b6e2...52fd") to guard a `skip_unlock_file`
        # property (API.md's row carries the key in full). A caller can only
        # use a key it obtained that way.
        #
        # The key is validated here rather than passed through to Live because
        # Live's rejections are C++ exceptions with no usable text: a non-hex
        # argument raises RuntimeError("Key contains non-hex characters") and
        # a hex argument of the wrong length raises IndexError("basic_string").
        # Neither names the requirement, and the second is indistinguishable
        # from the no-argument case.
        #
        # ValueError specifically, because it is in
        # OSCServer.WILDCARD_SKIP_EXCEPTIONS: under /live/application/get/*
        # a malformed key genuinely means "this endpoint does not apply to
        # this request", so the sweep skips this address instead of emitting
        # a /live/error that no sender asked for. Live's own RuntimeError is
        # not a skip, which is what made the pass-through behaviour
        # incoherent under a wildcard.
        #
        # The answer is logged because the reply port is not always bindable
        # on a development machine — see API.md § "The no-probe variant".
        # Without a log line this address is unverifiable, which is precisely
        # why the wrong contract shipped in the first place.
        #
        # The key is echoed back verbatim, neither case-folded nor otherwise
        # rewritten, so a client firing a burst of has_option requests can
        # correlate the replies — there is no other discriminator on this
        # address.
        #
        # No-args is deliberately an error rather than a silent default:
        # params[0] raises IndexError *before* validation, and
        # OSCServer._dispatch turns that into the structured /live/error
        # ("request", address, detail, argc) reply.
        #--------------------------------------------------------------------------------
        def get_has_option(params: Tuple[Any] = ()) -> Tuple:
            key = str(params[0])
            if len(key) != HAS_OPTION_KEY_LENGTH or not all(c in string.hexdigits for c in key):
                raise ValueError("has_option expects a %d-character hexadecimal option key, "
                                 "not an Options.txt option name" % HAS_OPTION_KEY_LENGTH)
            present = application.has_option(key)
            self.logger.info("has_option for %s: %s = %s" % (self.class_identifier, key, present))
            return key, present
        self.osc_server.add_handler("/live/application/get/has_option", get_has_option)

        #--------------------------------------------------------------------------------
        # The two list-valued reads, flattened into a single reply with no
        # count prefix, exactly like /live/track/get/available_input_routing_types.
        #
        # unavailable_features: str() on each element unconditionally, so the
        # reply is well-formed whether Live hands back strings or enum objects
        # (unmeasured — see API.md).
        #
        # control_surfaces: names only, by design. The audit found the control
        # surface *objects* have no value to Seshat, and naming them keeps the
        # reply encodable — an object-valued element could not go on the wire
        # at all. The list mirrors the preferences slots in order, so an
        # unassigned slot has to keep its position: it goes out as the empty
        # string rather than being dropped, which would silently renumber
        # every slot after it.
        #--------------------------------------------------------------------------------
        def get_unavailable_features(_) -> Tuple:
            return tuple(str(feature) for feature in application.unavailable_features)
        self.osc_server.add_handler("/live/application/get/unavailable_features", get_unavailable_features)

        def get_control_surfaces(_) -> Tuple:
            return tuple("" if surface is None else type(surface).__name__
                         for surface in application.control_surfaces)
        self.osc_server.add_handler("/live/application/get/control_surfaces", get_control_surfaces)

        #--------------------------------------------------------------------------------
        # The two message methods. Both are called with the text and nothing
        # else, so every other Live parameter keeps its default — in
        # particular `buttons`, which defaults to
        # Application.MessageButtons.OK_BUTTON.
        #
        # That single positional argument is the OK-only guarantee, and it is
        # deliberate: press_current_dialog_button is not exposed on the wire
        # (a current dialog may guard unsaved work), so the bridge must never
        # raise a remote dialog offering choices the remote has no way to
        # make. Widening this call reopens that decision — see API.md and the
        # roadmap entry, not just this comment.
        #--------------------------------------------------------------------------------
        def show_message(params: Tuple[Any] = ()) -> Tuple:
            return application.show_message(str(params[0])),
        self.osc_server.add_handler("/live/application/show_message", show_message)

        def show_on_the_fly_message(params: Tuple[Any] = ()) -> Tuple:
            return application.show_on_the_fly_message(str(params[0])),
        self.osc_server.add_handler("/live/application/show_on_the_fly_message", show_on_the_fly_message)
