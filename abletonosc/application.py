import Live
import os
from functools import partial
from typing import Any, Tuple
from .handler import AbletonOSCHandler

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
            from . import introspection
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
        # Options.txt queries. The option string is handed to Live unmodified
        # and echoed back beside the answer, so a client firing a burst of
        # has_option requests can correlate the replies — there is no other
        # discriminator on this address.
        #
        # No-args is deliberately an error rather than a silent default:
        # params[0] raises IndexError, and OSCServer._dispatch turns that into
        # the structured /live/error ("request", address, detail, argc) reply.
        #--------------------------------------------------------------------------------
        def get_has_option(params: Tuple[Any] = ()) -> Tuple:
            option = str(params[0])
            return option, application.has_option(option)
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
