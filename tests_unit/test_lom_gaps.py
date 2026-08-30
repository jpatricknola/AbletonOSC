"""Regression coverage for the generated LOM gap report."""

from tools import lom_gaps


def _dump(classes):
    return {
        "live_version": "12.4.5",
        "classes": classes,
        "mxd": {"AVAILABLE_TYPE_PROPERTIES": {}},
        "osc_addresses": [],
    }


def test_members_renders_values_as_constants_with_their_repr():
    entry = {
        "members": {
            "SUITE": {"kind": "value", "repr": "'Suite'"},
        },
    }

    assert lom_gaps.members(entry) == {
        "SUITE": ("const", False, "'Suite'"),
    }


def test_render_reports_module_signatures_and_class_constants():
    classes = {
        "Live.Conversions": {
            "kind": "module",
            "doc": "Conversion helpers",
            "members": {
                "audio_to_midi_clip": {
                    "kind": "method",
                    "doc": "audio_to_midi_clip(Song, Clip) -> None | measured",
                },
            },
        },
        "Live.Application.Variants": {
            "doc": "Live editions",
            "members": {
                "SUITE": {"kind": "value", "repr": "'Suite'"},
            },
        },
    }

    rendered = lom_gaps.render(_dump(classes))

    assert "1 Live classes and 1 Live modules walked" in rendered
    assert "### `Live.Conversions` — 1 member (module)" in rendered
    assert "| `audio_to_midi_clip` | method | " \
           "audio_to_midi_clip(Song, Clip) -> None \\| measured |" in rendered
    assert "### `Live.Application.Variants` — 1 member (class)" in rendered
    assert "- **const:** `SUITE` = `'Suite'`" in rendered
    assert "plus 2 members across 2 entries" in rendered


def test_render_excludes_enum_and_vector_entries_by_the_named_rules():
    classes = {
        "Live.Mode.Mode": {
            "members": {
                "names": {"kind": "value", "repr": "{'one': 1}"},
                "values": {"kind": "value", "repr": "{1: one}"},
            },
        },
        "Live.Base.IntVector": {
            "members": {
                "append": {"kind": "method", "doc": "append(value) -> None"},
            },
        },
    }

    rendered = lom_gaps.render(_dump(classes))

    assert "2 Live classes and 0 Live modules walked" in rendered
    assert "### `Live.Mode.Mode`" not in rendered
    assert "### `Live.Base.IntVector`" not in rendered
    assert "plus 0 members across 0 entries" in rendered
