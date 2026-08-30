import logging
logger = logging.getLogger("abletonosc")

logger.info("Reloading abletonosc...")

from .osc_server import OSCServer
from .application import ApplicationHandler
from .song import SongHandler
from .clip import ClipHandler
from .clip_slot import ClipSlotHandler
from .track import TrackHandler
from .device import DeviceHandler
from .scene import SceneHandler
from .view import ViewHandler
from .midimap import MidiMapHandler

#--------------------------------------------------------------------------------
# Seshat extensions — see SESHAT.md.
#--------------------------------------------------------------------------------
from .browser import BrowserHandler
from .groove import GrooveHandler
from .return_track import ReturnTrackHandler
from .song_structure import SongStructureHandler

#--------------------------------------------------------------------------------
# introspection exports no handler and registers no address: it is imported
# here for its side effect, which is binding `abletonosc.introspection` as an
# attribute of this package so that manager.reload_imports() has something to
# reload. It used to be imported only inside the /live/application/dump_lom
# callback, so on any session where that address had never been fired the
# reload aborted on it and silently skipped every handler module below it.
# Keeping the import here also makes the reload list self-evidently complete:
# every module manager.py reloads is imported by this file.
#--------------------------------------------------------------------------------
from . import introspection

from .constants import OSC_LISTEN_PORT, OSC_RESPONSE_PORT
