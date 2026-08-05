"""
Regression tests for OSCServer.process_message's dispatch core:
wildcard matching (#1), fan-out failure isolation (#2), and reply-type
validation (#5). All drive process_message directly via conftest.dispatch;
no Live, no fixed ports.
"""

import pytest

from .conftest import dispatch


def reply(*params):
    """A callback that replies with `params` regardless of its arguments."""
    return lambda _: tuple(params)


def raiser(exception):
    def callback(_):
        raise exception
    return callback


def addresses(messages):
    return [address for address, _ in messages]


#--------------------------------------------------------------------------------
# Wildcard matching (#1)
#--------------------------------------------------------------------------------

def test_wildcard_matches_whole_segment_only(server, receiver):
    # The confirmed live defect: an unanchored, unescaped pattern let
    # /live/*/get/tempo reach /live/scene/get/tempo_enabled.
    server.add_handler("/live/song/get/tempo", reply("song"))
    server.add_handler("/live/scene/get/tempo", reply("scene"))
    server.add_handler("/live/scene/get/tempo_enabled", reply("enabled"))
    dispatch(server, "/live/*/get/tempo")
    assert sorted(receiver.drain()) == [("/live/scene/get/tempo", ("scene",)),
                                        ("/live/song/get/tempo", ("song",))]


def test_trailing_wildcard_does_not_cross_slash(server, receiver):
    server.add_handler("/live/track/get/name", reply("name"))
    server.add_handler("/live/track/get/clips/name", reply("clips"))
    dispatch(server, "/live/track/get/*")
    assert receiver.drain() == [("/live/track/get/name", ("name",))]


def test_regex_metacharacters_are_literal(server, receiver):
    server.add_handler("/live/song/get/temp.", reply("dot"))
    server.add_handler("/live/song/get/tempo", reply("tempo"))
    dispatch(server, "/live/*/get/temp.")
    assert receiver.drain() == [("/live/song/get/temp.", ("dot",))]


def test_plus_is_literal(server, receiver):
    server.add_handler("/live/song/get/a+b", reply("plus"))
    server.add_handler("/live/song/get/aab", reply("aab"))
    dispatch(server, "/live/*/get/a+b")
    assert receiver.drain() == [("/live/song/get/a+b", ("plus",))]


def test_leading_wildcard_single_segment(server, receiver):
    server.add_handler("/alpha/get/x", reply("alpha"))
    server.add_handler("/beta/get/x", reply("beta"))
    server.add_handler("/a/b/get/x", reply("nested"))
    dispatch(server, "/*/get/x")
    assert sorted(receiver.drain()) == [("/alpha/get/x", ("alpha",)),
                                        ("/beta/get/x", ("beta",))]


def test_multiple_wildcards(server, receiver):
    server.add_handler("/live/song/get/tempo", reply("flat"))
    server.add_handler("/live/song/get/clips/name", reply("nested"))
    dispatch(server, "/live/*/get/*")
    assert receiver.drain() == [("/live/song/get/tempo", ("flat",))]


def test_consecutive_wildcards_require_two_characters(server, receiver):
    # "**" compiles to [^/]+[^/]+ — at least two non-/ characters, still
    # within one segment. Pinned so a rewrite doesn't silently change it.
    server.add_handler("/live/ab/tempo", reply("ab"))
    server.add_handler("/live/a/tempo", reply("a"))
    server.add_handler("/live/a/b/tempo", reply("crossed"))
    dispatch(server, "/live/**/tempo")
    assert receiver.drain() == [("/live/ab/tempo", ("ab",))]


def test_wildcard_matches_one_or_more_characters(server, receiver):
    # "*" never matches the empty string: /live/tra* must not match a
    # registered /live/tra.
    server.add_handler("/live/tra", reply("bare"))
    server.add_handler("/live/track", reply("track"))
    dispatch(server, "/live/tra*")
    assert receiver.drain() == [("/live/track", ("track",))]


def test_wildcard_with_no_match_sends_nothing(server, receiver):
    server.add_handler("/live/song/get/tempo", reply("song"))
    dispatch(server, "/live/*/get/nonexistent")
    assert receiver.drain() == []


def test_direct_lookup_is_byte_exact(server, receiver):
    calls = []
    server.add_handler("/live/song/get/tempo", lambda p: calls.append("exact") or ("t",))
    server.add_handler("/live/song/get/tempo_enabled", lambda p: calls.append("other") or ("e",))
    dispatch(server, "/live/song/get/tempo")
    assert receiver.drain() == [("/live/song/get/tempo", ("t",))]
    assert calls == ["exact"]


#--------------------------------------------------------------------------------
# Fan-out failure isolation (#2)
#--------------------------------------------------------------------------------

@pytest.fixture
def fan(server):
    """Three callbacks matched by /fan/*; the middle one is replaceable."""
    def install(middle_callback):
        server.add_handler("/fan/a", reply("a"))
        server.add_handler("/fan/b", middle_callback)
        server.add_handler("/fan/c", reply("c"))
    return install


def test_fanout_indexerror_is_skipped_silently(fan, server, receiver):
    # The confirmed defect: an endpoint needing an omitted positional
    # argument aborted the whole fan-out. It must be skipped — no error —
    # and the other matches must still reply.
    fan(raiser(IndexError("tuple index out of range")))
    dispatch(server, "/fan/*")
    assert receiver.drain() == [("/fan/a", ("a",)), ("/fan/c", ("c",))]


def test_fanout_indexerror_with_arguments_is_reported(fan, server, receiver):
    # Live's most common genuine rejection is IndexError("Index out of
    # range") from a LOM collection subscript, and the offending index
    # arrives as an argument. Skipping it would answer /live/track/get/* 99
    # with silence. Only the argument-less shape is a skip.
    fan(raiser(IndexError("Index out of range")))
    dispatch(server, "/fan/*", 99)
    messages = receiver.drain()
    assert [m for m in messages if m[0] != "/live/error"] == [("/fan/a", ("a",)),
                                                              ("/fan/c", ("c",))]
    errors = [params for address, params in messages if address == "/live/error"]
    assert len(errors) == 1
    assert errors[0][0] == "request"
    assert errors[0][1] == "/fan/*"
    assert "/fan/b" in errors[0][2]
    assert "Index out of range" in errors[0][2]
    assert errors[0][3] == 1
    assert errors[0][4:] == (99,)


@pytest.mark.parametrize("exception", [ValueError("bad"), AttributeError("no attr")])
@pytest.mark.parametrize("args", [(), (0,)])
def test_fanout_legacy_skips_preserved(fan, server, receiver, exception, args):
    # The argument-count qualification is IndexError's alone: upstream's
    # original skips stay unconditional, so a pattern that does carry
    # arguments still skips an endpoint they don't fit.
    fan(raiser(exception))
    dispatch(server, "/fan/*", *args)
    assert receiver.drain() == [("/fan/a", ("a",)), ("/fan/c", ("c",))]


def test_fanout_runtimeerror_is_structured_and_isolated(fan, server, receiver):
    fan(raiser(RuntimeError("boom")))
    dispatch(server, "/fan/*", 5)
    messages = receiver.drain()
    assert [m for m in messages if m[0] != "/live/error"] == [("/fan/a", ("a",)),
                                                              ("/fan/c", ("c",))]
    errors = [params for address, params in messages if address == "/live/error"]
    assert len(errors) == 1
    error = errors[0]
    assert error[0] == "request"
    assert error[1] == "/fan/*"          # the pattern the client sent
    assert "/fan/b" in error[2]          # concrete callback in the detail
    assert "boom" in error[2]
    assert error[3] == 1
    assert error[4:] == (5,)


@pytest.mark.parametrize("exception", [TypeError("bad call"), KeyError("missing")])
def test_fanout_typeerror_keyerror_are_structured_not_skipped(fan, server, receiver, exception):
    fan(raiser(exception))
    dispatch(server, "/fan/*")
    messages = receiver.drain()
    assert [m for m in messages if m[0] != "/live/error"] == [("/fan/a", ("a",)),
                                                              ("/fan/c", ("c",))]
    errors = [params for address, params in messages if address == "/live/error"]
    assert len(errors) == 1
    assert errors[0][0] == "request"
    assert errors[0][1] == "/fan/*"
    assert "/fan/b" in errors[0][2]


def test_fanout_replies_carry_concrete_addresses(server, receiver):
    server.add_handler("/live/song/get/tempo", reply(120))
    server.add_handler("/live/scene/get/tempo", reply(-1))
    dispatch(server, "/live/*/get/tempo")
    assert sorted(addresses(receiver.drain())) == ["/live/scene/get/tempo",
                                                   "/live/song/get/tempo"]


#--------------------------------------------------------------------------------
# Reply-type validation (#5)
#--------------------------------------------------------------------------------

def test_direct_non_tuple_return_is_structured_error(server, receiver):
    server.add_handler("/live/song/get/tempo", lambda p: [120])
    dispatch(server, "/live/song/get/tempo", 1, "x")
    messages = receiver.drain()
    assert addresses(messages) == ["/live/error"]
    error = messages[0][1]
    assert error[0] == "request"
    assert error[1] == "/live/song/get/tempo"
    assert "list" in error[2]
    assert error[3] == 2
    assert error[4:] == (1, "x")

    # The server keeps dispatching subsequent messages.
    server.add_handler("/live/song/get/name", reply("ok"))
    dispatch(server, "/live/song/get/name")
    assert receiver.drain() == [("/live/song/get/name", ("ok",))]


def test_wildcard_non_tuple_return_is_structured_and_isolated(fan, server, receiver):
    fan(lambda p: "not a tuple")
    dispatch(server, "/fan/*")
    messages = receiver.drain()
    assert [m for m in messages if m[0] != "/live/error"] == [("/fan/a", ("a",)),
                                                              ("/fan/c", ("c",))]
    errors = [params for address, params in messages if address == "/live/error"]
    assert len(errors) == 1
    assert errors[0][1] == "/fan/*"
    assert "/fan/b" in errors[0][2]
    assert "str" in errors[0][2]


def test_none_return_sends_nothing(server, receiver):
    server.add_handler("/live/song/stop", lambda p: None)
    dispatch(server, "/live/song/stop")
    assert receiver.drain() == []


def test_empty_tuple_return_sends_empty_reply(server, receiver):
    server.add_handler("/live/song/get/nothing", reply())
    dispatch(server, "/live/song/get/nothing")
    assert receiver.drain() == [("/live/song/get/nothing", ())]
