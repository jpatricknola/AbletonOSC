from typing import Tuple, Any, Callable
from .constants import OSC_LISTEN_PORT, OSC_RESPONSE_PORT
from ..pythonosc.osc_message import OscMessage, ParseError
from ..pythonosc.osc_bundle import OscBundle
from ..pythonosc.osc_message_builder import OscMessageBuilder, BuildError

import re
import errno
import socket
import logging
import traceback

class OSCServer:
    def __init__(self,
                 local_addr: Tuple[str, int] = ('127.0.0.1', OSC_LISTEN_PORT),
                 remote_addr: Tuple[str, int] = ('127.0.0.1', OSC_RESPONSE_PORT)):
        """
        Class that handles OSC server responsibilities, including support for sending
        reply messages.

        Implemented because pythonosc's OSC server causes a beachball when handling
        incoming messages. To investigate, as it would be ultimately better not to have
        to roll our own.

        This fork is **local-only by default**: every OSC address here can control
        Live, and there is no authentication on the wire, so upstream's wildcard
        bind exposed full remote control of the user's session to anything the
        machine's network boundary allowed through. Seshat's only client runs on
        the same machine. Do not restore the wildcard default — a networked
        controller needs an explicit opt-in bind plus a security design of its own
        (see SESHAT.md).

        Args:
            local_addr: Local address and port to listen on.
                        By default, binds to IPv4 loopback (127.0.0.1), so only
                        processes on this machine can reach the OSC API.
            remote_addr: Remote address to send replies to, by default. Can be overridden in send().
        """

        self._local_addr = local_addr
        self._remote_addr = remote_addr
        self._response_port = remote_addr[1]

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setblocking(0)
        self._socket.bind(self._local_addr)
        self._callbacks = {}

        self.logger = logging.getLogger("abletonosc")
        self.logger.info("Starting OSC server (local %s, response port %d)",
                         str(self._local_addr), self._response_port)

    def add_handler(self, address: str, handler: Callable) -> None:
        """
        Add an OSC handler.

        Args:
            address: The OSC address string
            handler: A handler function, with signature:
                     params: Tuple[Any, ...]
        """
        self._callbacks[address] = handler

    def clear_handlers(self) -> None:
        """
        Remove all existing OSC handlers.
        """
        self._callbacks = {}

    def send(self,
             address: str,
             params: Tuple = (),
             remote_addr: Tuple[str, int] = None) -> None:
        """
        Send an OSC message.

        Args:
            address: The OSC address (e.g. /frequency)
            params: A tuple of zero or more OSC params
            remote_addr: The remote address to send to, as a 2-tuple (hostname, port).
                         If None, uses the default remote address.
        """
        msg_builder = OscMessageBuilder(address)
        for param in params:
            msg_builder.add_arg(param)

        try:
            msg = msg_builder.build()
            if remote_addr is None:
                remote_addr = self._remote_addr
            self._socket.sendto(msg.dgram, remote_addr)
        except BuildError:
            self.logger.error("AbletonOSC: OSC build error: %s" % (traceback.format_exc()))

    def process_message(self, message, remote_addr):
        if message.address in self._callbacks:
            callback = self._callbacks[message.address]
            rv = callback(message.params)

            if rv is not None:
                assert isinstance(rv, tuple)
                remote_hostname, _ = remote_addr
                response_addr = (remote_hostname, self._response_port)
                self.send(address=message.address,
                          params=rv,
                          remote_addr=response_addr)
        elif "*" in message.address:
            regex = message.address.replace("*", "[^/]+")
            for callback_address, callback in self._callbacks.items():
                if re.match(regex, callback_address):
                    try:
                        rv = callback(message.params)
                    except ValueError:
                        #--------------------------------------------------------------------------------
                        # Don't throw errors for queries that require more arguments
                        # (e.g. /live/track/get/send with no args)
                        #--------------------------------------------------------------------------------
                        continue
                    except AttributeError:
                        #--------------------------------------------------------------------------------
                        # Don't throw errors when trying to create listeners for properties that can't
                        # be listened for (e.g. can_be_armed, is_foldable)
                        #--------------------------------------------------------------------------------
                        continue
                    if rv is not None:
                        assert isinstance(rv, tuple)
                        remote_hostname, _ = remote_addr
                        response_addr = (remote_hostname, self._response_port)
                        self.send(address=callback_address,
                                  params=rv,
                                  remote_addr=response_addr)
        else:
            self.logger.error("AbletonOSC: Unknown OSC address: %s" % message.address)

    def process_bundle(self, bundle, remote_addr):
        for i in bundle:
            if OscBundle.dgram_is_bundle(i.dgram):
                self.process_bundle(i, remote_addr)
            else:
                self.process_message(i, remote_addr)

    def parse_bundle(self, data, remote_addr):
        if OscBundle.dgram_is_bundle(data):
            try:
                bundle = OscBundle(data)
                self.process_bundle(bundle, remote_addr)
            except ParseError:
                self.logger.error("AbletonOSC: Error parsing OSC bundle: %s" % (traceback.format_exc()))
        else:
            try:
                message = OscMessage(data)
                self.process_message(message, remote_addr)
            except ParseError:
                self.logger.error("AbletonOSC: Error parsing OSC message: %s" % (traceback.format_exc()))

    def process(self) -> None:
        """
        Synchronously process all data queued on the OSC socket.

        Error handling is per-message: a message that throws is logged and the
        loop moves on to the next one. Anything wider would let one bad message
        discard the rest of this tick's queue, which breaks clients that send
        ordered multi-message sequences.
        """
        while True:
            #--------------------------------------------------------------------------------
            # Loop until no more data is available.
            #--------------------------------------------------------------------------------
            try:
                data, remote_addr = self._socket.recvfrom(65536)
            except socket.error as e:
                if e.errno == errno.ECONNRESET:
                    #--------------------------------------------------------------------------------
                    # This benign error seems to occur on startup on Windows
                    #--------------------------------------------------------------------------------
                    self.logger.warning("AbletonOSC: Non-fatal socket error: %s" % (traceback.format_exc()))
                elif e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                    #--------------------------------------------------------------------------------
                    # Another benign networking error, throw when no data is received
                    # on a call to recvfrom() on a non-blocking socket
                    #--------------------------------------------------------------------------------
                    pass
                else:
                    #--------------------------------------------------------------------------------
                    # Something more serious has happened
                    #--------------------------------------------------------------------------------
                    self.logger.error("AbletonOSC: Socket error: %s" % (traceback.format_exc()))
                break

            try:
                #--------------------------------------------------------------------------------
                # The default reply address is fixed at construction and is never
                # retargeted from the last datagram's source: listener updates,
                # /live/startup and /live/error always go to loopback on the
                # response port. Upstream rewrote it per message here.
                #--------------------------------------------------------------------------------
                self.parse_bundle(data, remote_addr)
            except Exception as e:
                self.logger.error("AbletonOSC: Error handling OSC message: %s" % e)
                self.logger.warning("AbletonOSC: %s" % traceback.format_exc())

    def shutdown(self) -> None:
        """
        Shutdown the server network sockets.
        """
        self._socket.close()
