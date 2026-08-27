import Live
import os
from typing import Any, Tuple
from .handler import AbletonOSCHandler

class ApplicationHandler(AbletonOSCHandler):
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
        self.osc_server.send("/live/application/get/average_process_usage")
