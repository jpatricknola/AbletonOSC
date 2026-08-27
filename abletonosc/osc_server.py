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

    #--------------------------------------------------------------------------------
    # Wildcard-only compatibility skips — see _dispatch and _is_wildcard_skip.
    # ValueError and AttributeError are upstream's original skip set;
    # IndexError is the one confirmed additional case (a matched endpoint
    # reading a positional argument the pattern request omitted), and it is
    # further qualified by argument count. Deliberately narrow: TypeError and
    # KeyError commonly indicate a real handler defect, and no broad exception
    # class proves an argument-shape mismatch. Widening this set waits on
    # per-route argument schemas (issues.md, endpoint contract inventory).
    #--------------------------------------------------------------------------------
    WILDCARD_SKIP_EXCEPTIONS = (ValueError, AttributeError, IndexError)

    def _is_wildcard_skip(self, exception, message) -> bool:
        """
        Does `exception` mean "this matched endpoint does not apply to this
        wildcard request", rather than "this request failed"?

        Exception class alone cannot answer that for IndexError, because
        both meanings raise it:

          - Argument-shape mismatch — the reproduced fan-out abort. A
            pattern request carrying no index reaches an endpoint that
            needs one, and the endpoint raises reading params[0].
          - A genuine rejection by Live, and the most common one there is:
            a LOM collection subscript with an out-of-range index raises
            IndexError("Index out of range") (e.g. track.py's
            self.song.tracks[track_index]).

        Skipping the second would make /live/track/get/* 99 answer with
        nothing at all — no reply and no error, indistinguishable from a
        pattern that matched no endpoint, on the single most common way a
        request is legitimately refused. Argument count separates the two:
        an out-of-range index always arrives as the argument that produced
        it, and the argument-shape case is precisely the endpoint asking
        for an argument the request did not send.

        The residual imprecision is one-sided by design. A multi-argument
        pattern reaching an endpoint that wants one argument more than it
        sent (e.g. /live/device/get/* 0 0 and an endpoint reading
        params[2]) is reported rather than skipped: a correlated error
        naming that endpoint, while every other match still replies. Loud
        and wrong beats silent and wrong here; per-route argument schemas
        (issues.md, endpoint contract inventory) are what removes the guess entirely.
        """
        if not isinstance(exception, self.WILDCARD_SKIP_EXCEPTIONS):
            return False
        if isinstance(exception, IndexError):
            return not message.params
        return True

    def _dispatch(self, callback, callback_address, message, remote_addr,
                  reply_address, error_address, wildcard=False):
        """
        Invoke one callback for `message` and handle its outcome: send the
        reply on `reply_address` (direct: the request address; wildcard: the
        concrete callback address), or report a failure on /live/error with
        `error_address` in the address slot (always the address the client
        actually sent, since that is the only address it can correlate a
        pending request against).

        Seshat divergence — see SESHAT.md.

        A callback that raises used to unwind to process()'s per-datagram
        catch, where the offending address and arguments are out of scope:
        the client saw only a formatted log line on /live/error, with
        nothing to correlate it against, and its query waited out a full
        timeout to learn what the error had already said. Catching here,
        where message.address and message.params are both in hand, lets the
        error carry the request that produced it:

          /live/error ["request", address, message, arg_count, *args]

        The extra= marker tells the log relay in manager.py that this
        record has already gone out structured, so it does not also send
        the legacy ["log", message] payload for the same failure.

        With wildcard=True, exceptions that _is_wildcard_skip accepts are
        treated as "this matched endpoint does not apply to this request"
        (e.g. /live/track/get/send with no args, or listening on a
        property that can't be listened for) and skipped with a debug log;
        everything else is a structured error. Either way the caller's
        fan-out loop continues: one bad match never silences the rest.
        """
        try:
            rv = callback(message.params)
            #--------------------------------------------------------------------------------
            # Reply-type validation. An explicit raise, not an assert: the
            # check must survive python -O, and it lands on the same
            # structured-error path as any other callback failure.
            #
            # A list means a multi-reply fan-out — one datagram per element,
            # which is how a track-index wildcard answers for every track
            # (see the argument-wildcard contract in API.md § Track API).
            # The whole list is validated here, before anything is sent, so
            # an invalid element never leaves a partial fan-out on the wire.
            #--------------------------------------------------------------------------------
            if rv is not None and not isinstance(rv, (tuple, list)):
                raise TypeError("callback for %s returned %s; handlers must "
                                "return a tuple, a list of tuples, or None"
                                % (callback_address, type(rv).__name__))
            if isinstance(rv, list):
                for element in rv:
                    if not isinstance(element, tuple):
                        raise TypeError("callback for %s returned a list "
                                        "containing %s; a list reply must "
                                        "contain only tuples"
                                        % (callback_address,
                                           type(element).__name__))
        except Exception as e:
            if wildcard and self._is_wildcard_skip(e, message):
                self.logger.debug("AbletonOSC: Wildcard %s: skipping %s (%s: %s)"
                                  % (error_address, callback_address,
                                     type(e).__name__, e))
                return
            detail = str(e) or type(e).__name__
            if callback_address != error_address:
                detail = "in %s: %s" % (callback_address, detail)
            self.logger.error("AbletonOSC: Error handling OSC message %s: %s"
                              % (error_address, detail),
                              extra={"osc_request_error": True})
            self.logger.warning("AbletonOSC: %s" % traceback.format_exc())
            self.send("/live/error",
                      ("request", error_address, detail,
                       len(message.params), *message.params))
            return

        if rv is not None:
            remote_hostname, _ = remote_addr
            response_addr = (remote_hostname, self._response_port)
            #--------------------------------------------------------------------------------
            # A tuple is one reply; a list is one reply per element, sent in
            # list order on the same reply address. An empty list sends
            # nothing, exactly as None does.
            #--------------------------------------------------------------------------------
            replies = rv if isinstance(rv, list) else [rv]
            for params in replies:
                self.send(address=reply_address,
                          params=params,
                          remote_addr=response_addr)

    def process_message(self, message, remote_addr):
        if message.address in self._callbacks:
            callback = self._callbacks[message.address]
            self._dispatch(callback, message.address, message, remote_addr,
                           reply_address=message.address,
                           error_address=message.address)
        elif "*" in message.address:
            #--------------------------------------------------------------------------------
            # Wildcard matching. `*` is the only supported metacharacter and
            # matches one or more non-`/` characters within a single address
            # segment; everything else in the pattern — including OSC's other
            # pattern characters and any regex character — is literal, and the
            # pattern must match a complete registered address. See SESHAT.md
            # for the contract this encodes.
            #--------------------------------------------------------------------------------
            pattern = re.compile("[^/]+".join(re.escape(part)
                                              for part in message.address.split("*")))
            for callback_address, callback in self._callbacks.items():
                if not pattern.fullmatch(callback_address):
                    continue
                self._dispatch(callback, callback_address, message, remote_addr,
                               reply_address=callback_address,
                               error_address=message.address,
                               wildcard=True)
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
