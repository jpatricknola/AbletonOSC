from ableton.v2.control_surface import ControlSurface
from _Framework.EncoderElement import EncoderElement
import Live

from . import abletonosc

import importlib
import traceback
import logging
import os

logger = logging.getLogger("abletonosc")

#--------------------------------------------------------------------------------
# Modules in abletonosc/ that Manager.reload_imports() deliberately does not
# reload. tests_unit/test_reload_list.py fails if a module is added to the
# package and appears in neither this set nor the ordered sequence in
# reload_imports(), so the two can never drift apart silently again — which
# they had, twice: `constants` was absent with no record (now explicitly
# restart-only, for the reason below) and `introspection` was present in the
# sequence but absent from the package until a callback happened to import it,
# which aborted every reload on a fresh session.
#
# midimap: never reloaded, so MidiMapHandler keeps subclassing whatever
#   AbletonOSCHandler was current at Live startup, across every reload.
#   Accepted rather than closed — ROADMAP.md "#2 - Make a failed live code
#   reload safe and reported" asks this item to decide, and this is the
#   decision. It is harmless because midimap's init_api() reads neither
#   class_identifier nor a listener dict, which is what the base-class reload
#   hazard acts through. Closing it would mean reloading midimap after
#   handler like every other subclass module; nothing prevents that, it is
#   simply not worth a behaviour change to a module with no such reads.
#
# constants: OSCServer copies both port constants into instance state and
#   binds its socket once, in Manager.__init__. Reloading constants.py and
#   osc_server.py cannot move that existing socket or change its response
#   port, so claiming success after a port edit would still be false. A port
#   change requires a Remote Script restart; keep that limitation explicit
#   instead of performing a reload that cannot affect running behaviour.
#
# __init__ is not listed: the package itself is reloaded last, as
#   importlib.reload(abletonosc), which is what re-executes __init__.py.
#--------------------------------------------------------------------------------
RELOAD_EXEMPT = frozenset(["constants", "midimap"])

class Manager(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)

        self.log_level = "info"

        self.handlers = []
        self.midi_mappings = {}

        try:
            self.osc_server = abletonosc.OSCServer()
            self.schedule_message(0, self.tick)

            self.start_logging()
            self.init_api()

            self.show_message("AbletonOSC: Listening for OSC on port %d" % abletonosc.OSC_LISTEN_PORT)
            logger.info("Started AbletonOSC on address %s" % str(self.osc_server._local_addr))
        except OSError as msg:
            self.show_message("AbletonOSC: Couldn't bind to port %d (%s)" % (abletonosc.OSC_LISTEN_PORT, msg))
            logger.info("Couldn't bind to port %d (%s)" % (abletonosc.OSC_LISTEN_PORT, msg))


    def start_logging(self):
        """
        Start logging to a local logfile (logs/abletonosc.log),
        and relay error messages via OSC.
        """
        module_path = os.path.dirname(os.path.realpath(__file__))
        log_dir = os.path.join(module_path, "logs")
        if not os.path.exists(log_dir):
            os.mkdir(log_dir, 0o755)
        log_path = os.path.join(log_dir, "abletonosc.log")
        self.log_file_handler = logging.FileHandler(log_path)
        self.log_file_handler.setLevel(self.log_level.upper())
        formatter = logging.Formatter('(%(asctime)s) [%(levelname)s] %(message)s')
        self.log_file_handler.setFormatter(formatter)
        logger.addHandler(self.log_file_handler)

        class LiveOSCErrorLogHandler(logging.StreamHandler):
            def emit(handler, record):
                #--------------------------------------------------------------------------------
                # Seshat divergence — see SESHAT.md.
                #
                # A record marked osc_request_error has already been sent as a
                # structured /live/error ["request", address, ...] by
                # osc_server.process_message, which is the only place the failing
                # request's address and arguments are still in scope. Relaying it
                # again as an uncorrelatable log line would just duplicate it.
                #--------------------------------------------------------------------------------
                if getattr(record, "osc_request_error", False):
                    return

                message = record.getMessage()
                #--------------------------------------------------------------------------------
                # Strip the "AbletonOSC: " prefix when there is one. Upstream sliced
                # from message.index(":"), which raises ValueError on any error
                # message with no colon in it — swallowed by logging, so the relay
                # silently dropped that error instead of sending it.
                #--------------------------------------------------------------------------------
                _prefix, separator, remainder = message.partition(": ")
                if separator:
                    message = remainder

                try:
                    self.osc_server.send("/live/error", ("log", message))
                except OSError:
                    # If the connection is dead, silently ignore errors as there's not much more we can do
                    pass
        self.live_osc_error_handler = LiveOSCErrorLogHandler()
        self.live_osc_error_handler.setLevel(logging.ERROR)
        logger.addHandler(self.live_osc_error_handler)

    def stop_logging(self):
        logger.removeHandler(self.log_file_handler)
        logger.removeHandler(self.live_osc_error_handler)

    def init_api(self):
        def test_callback(params):
            self.show_message("Received OSC OK")
            self.osc_server.send("/live/test", ("ok",))
        def reload_callback(params):
            self.reload_imports()
        def get_log_level_callback(params):
            return (self.log_level,)
        def set_log_level_callback(params):
            log_level = params[0]
            assert log_level in ("debug", "info", "warning", "error", "critical")
            self.log_level = log_level
            self.log_file_handler.setLevel(self.log_level.upper())
        def show_message_callback(params):
            self.show_message(params[0])

        self.osc_server.add_handler("/live/test", test_callback)
        self.osc_server.add_handler("/live/api/reload", reload_callback)
        self.osc_server.add_handler("/live/api/get/log_level", get_log_level_callback)
        self.osc_server.add_handler("/live/api/set/log_level", set_log_level_callback)
        self.osc_server.add_handler("/live/api/show_message", show_message_callback)

        with self.component_guard():
            self.handlers = [
                abletonosc.SongHandler(self),
                abletonosc.ApplicationHandler(self),
                abletonosc.ClipHandler(self),
                abletonosc.ClipSlotHandler(self),
                abletonosc.TrackHandler(self),
                abletonosc.DeviceHandler(self),
                abletonosc.ViewHandler(self),
                abletonosc.SceneHandler(self),
                abletonosc.MidiMapHandler(self),
                #--------------------------------------------------------------------------------
                # Seshat extensions — see SESHAT.md. Each registers addresses of its
                # own; none overrides another handler's, so position in this list is
                # not load-bearing.
                #--------------------------------------------------------------------------------
                abletonosc.BrowserHandler(self),
                abletonosc.GrooveHandler(self),
                abletonosc.ReturnTrackHandler(self),
                abletonosc.SongStructureHandler(self),
                abletonosc.ConversionsHandler(self),
            ]

    def clear_api(self):
        self.osc_server.clear_handlers()
        for handler in self.handlers:
            handler.clear_api()

    def tick(self):
        """
        Called once per 100ms "tick".
        Live's embedded Python implementation does not appear to support threading,
        and beachballs when a thread is started. Instead, this approach allows long-running
        processes such as the OSC server to perform operations.
        """
        logger.debug("Tick...")
        self.osc_server.process()
        self.schedule_message(1, self.tick)

    def reload_imports(self):
        #--------------------------------------------------------------------------------
        # The ordered reload list. Every module is named by string rather than
        # by attribute so that a module missing from the package is reported
        # by name instead of raising an opaque AttributeError from the middle
        # of the sequence — which is what used to happen, and what silently
        # skipped every module after it. See _reload() below.
        #
        # Base modules before the subclass modules, so a reload of any
        # module in this list never constructs its handler on a stale
        # AbletonOSCHandler: application, clip, clip_slot and device used
        # to reload *before* handler, and a handler built on the previous
        # base skips init_state() entirely and has its class-level
        # class_identifier shadowed back to None — an AttributeError on
        # one side, listener pushes silently addressed to
        # /live/None/get/<prop> on the other. osc_server first, because
        # handler.py does a `from` import of OSCServer.
        #
        # tests_unit/test_reload_list.py derives every ordering rule below
        # from the modules' own `from .x import y` statements and fails if one
        # is broken, so a new `from` import is checked the day it is written.
        #--------------------------------------------------------------------------------
        failed = None

        def _reload(name):
            #--------------------------------------------------------------------------------
            # `failed` is set *before* the reload and cleared after it, so it
            # names the module in flight even when the failure is the getattr
            # itself (a module absent from the package, which is how
            # abletonosc.introspection used to abort this sequence).
            #--------------------------------------------------------------------------------
            nonlocal failed
            failed = name
            importlib.reload(getattr(abletonosc, name))
            failed = None

        try:
            _reload("osc_server")
            _reload("handler")
            #--------------------------------------------------------------------------------
            # introspection is imported eagerly by abletonosc/__init__.py so
            # that this line has an attribute to reload. It used to be
            # imported only inside the /live/application/dump_lom callback,
            # which meant that on a session where dump_lom had never been
            # fired this line raised AttributeError and every module below it
            # was silently skipped while the log still said "Reloaded code".
            # Do not make its import lazy again.
            #--------------------------------------------------------------------------------
            _reload("introspection")
            #--------------------------------------------------------------------------------
            # track_identity before every module that `from`-imports it —
            # song, track and view all do. A `from` import binds the function
            # objects at import time, so a module reloaded *before*
            # track_identity keeps calling the previous edit's resolvers: the
            # reload logs success and the old code goes on answering, which is
            # the same silent stale-binding failure documented for
            # track_callback below, and no Live-free test can catch it.
            #--------------------------------------------------------------------------------
            _reload("track_identity")
            #--------------------------------------------------------------------------------
            # path_safety before clip_slot, device and track, for the same
            # `from`-import reason as track_identity above: all three do
            # `from .path_safety import ...`, so an edit to the import rule
            # reloaded *after* them would log success while the previous edit's
            # resolver went on deciding which files /live/clip_slot/create_audio_clip,
            # /live/track/create_audio_clip and /live/device/replace_sample open.
            # No Live-free test can catch that.
            #--------------------------------------------------------------------------------
            _reload("path_safety")
            #--------------------------------------------------------------------------------
            # groove before clip and song, for the same `from`-import reason as
            # track_identity above: both of them `from .groove import ...` the
            # pool resolvers, so a groove.py edit reloaded *after* them would
            # log success while the previous edit's functions went on answering
            # /live/clip/get/groove and /live/song/get/groove_pool.
            #--------------------------------------------------------------------------------
            _reload("groove")
            _reload("application")
            _reload("clip")
            _reload("clip_slot")
            _reload("device")
            _reload("scene")
            _reload("song")
            #--------------------------------------------------------------------------------
            # track_callback before track: track.py does a `from` import of the
            # factory, so reloading it afterwards rebinds the new function.
            #--------------------------------------------------------------------------------
            _reload("track_callback")
            _reload("track")
            #--------------------------------------------------------------------------------
            # view after track_identity (reloaded above, before song and
            # track, which `from`-import it too): view.py does a `from` import
            # of the selection and object-read resolvers, so reloading it
            # afterwards rebinds the new functions.
            #--------------------------------------------------------------------------------
            _reload("view")
            _reload("browser")
            _reload("return_track")
            _reload("song_structure")
            #--------------------------------------------------------------------------------
            # conversions after handler, which it `from`-imports. It imports
            # nothing else from the package, so its position is otherwise free.
            #--------------------------------------------------------------------------------
            _reload("conversions")
            #--------------------------------------------------------------------------------
            # The package itself last, so __init__.py re-executes its own
            # imports over the modules reloaded above. Its
            # `logger.info("Reloading abletonosc...")` line is the visible
            # marker in the log that the sequence got this far.
            #
            # `failed` is set around it by hand rather than through _reload(),
            # which takes a submodule name. Without this the one statement that
            # can still fail after every _reload() has succeeded would leave
            # `failed` at None and be reported as "Reloaded code" — the exact
            # false success this function exists to stop.
            #--------------------------------------------------------------------------------
            failed = "__init__"
            importlib.reload(abletonosc)
            failed = None
        except Exception:
            #--------------------------------------------------------------------------------
            # error, not warning, and on the abletonosc logger rather than the
            # root one. start_logging() attaches LiveOSCErrorLogHandler to this
            # logger at ERROR level, so logging the failure here is also what
            # relays it to the client over /live/error: the caller who sent
            # /live/api/reload learns that the reload failed instead of having
            # to notice a traceback in the log file. That is the "failure
            # reaches the client" half of ROADMAP.md "#2 - Make a failed live
            # code reload safe and reported", with no change to the wire
            # contract of /live/api/reload itself.
            #--------------------------------------------------------------------------------
            logger.error("Live code reload FAILED at abletonosc.%s. Every module after it "
                         "in the reload sequence was skipped and is still running its "
                         "previous code:\n%s" % (failed, traceback.format_exc()))

        #--------------------------------------------------------------------------------
        # Re-registered either way: a partial reload still leaves a usable API,
        # built from whatever mixture of new and stale modules survived, and
        # that is better than an unregistered server. What must not happen is
        # reporting the mixture as a success.
        #--------------------------------------------------------------------------------
        self.clear_api()
        self.init_api()
        if failed is None:
            logger.info("Reloaded code")
        else:
            logger.error("Reloaded code PARTIALLY: stopped at abletonosc.%s, so the API "
                         "has been rebuilt from stale modules. Fix the error above and "
                         "send /live/api/reload again." % failed)

    def disconnect(self):
        self.show_message("Disconnecting...")
        logger.info("Disconnecting...")
        self.stop_logging()
        self.osc_server.shutdown()
        super().disconnect()

    def build_midi_map(self, midi_map_handle):
        """
        Called by Live to build the MIDI map.
        """
        logger.debug("Building MIDI map...")

        for channel, cc in self.midi_mappings.keys():
            parameter = self.midi_mappings[(channel, cc)]
            Live.MidiMap.map_midi_cc(midi_map_handle, parameter, channel, cc, Live.MidiMap.MapMode.absolute, 1)
            logger.debug("Mapped CC %d on channel %d to parameter %s" % (cc, channel, parameter.name))
