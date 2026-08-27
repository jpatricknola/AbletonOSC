from ableton.v2.control_surface import ControlSurface
from _Framework.EncoderElement import EncoderElement
import Live

from . import abletonosc

import importlib
import traceback
import logging
import os

logger = logging.getLogger("abletonosc")

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
                abletonosc.ReturnTrackHandler(self),
                abletonosc.SongStructureHandler(self),
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
        try:
            importlib.reload(abletonosc.introspection)
            importlib.reload(abletonosc.application)
            importlib.reload(abletonosc.clip)
            importlib.reload(abletonosc.clip_slot)
            importlib.reload(abletonosc.device)
            importlib.reload(abletonosc.handler)
            importlib.reload(abletonosc.osc_server)
            importlib.reload(abletonosc.scene)
            importlib.reload(abletonosc.song)
            importlib.reload(abletonosc.track)
            importlib.reload(abletonosc.view)
            importlib.reload(abletonosc.browser)
            importlib.reload(abletonosc.return_track)
            importlib.reload(abletonosc.song_structure)
            importlib.reload(abletonosc)
        except Exception as e:
            exc = traceback.format_exc()
            logging.warning(exc)

        self.clear_api()
        self.init_api()
        logger.info("Reloaded code")

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