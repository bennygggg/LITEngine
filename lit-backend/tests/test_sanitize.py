"""StreamSanitizer: unissued citation handles never reach the screen; typographic spaces are normalised."""

import pytest

from services.agent.sanitize import StreamSanitizer


def stream(deltas, issued):
    s = StreamSanitizer(set(issued))
    out = "".join(s.feed(d) for d in deltas) + s.flush()
    return out, s.dropped


def test_issued_handles_pass_unissued_are_dropped():
    out, dropped = stream(["See [P1] and [P9], also [S2]."], {"P1", "S2"})
    assert out == "See [P1] and , also [S2]." and dropped == ["P9"]


@pytest.mark.parametrize("chunks", [["[", "P", "1", "]"], ["[P", "1]"], ["x [P1", "] y"], list("[P1]")])
def test_handles_split_across_stream_chunks_are_still_recognised(chunks):
    out, _ = stream(chunks, {"P1"})
    assert out.replace("x ", "").replace(" y", "") == "[P1]"


def test_spaced_handles_are_canonicalised():
    assert stream(["see [ P1 ] there"], {"P1"})[0] == "see [P1] there"


def test_ordinary_brackets_are_untouched():
    assert stream(["the [sic] and (a) [note: 1996] ok"], set())[0] == "the [sic] and (a) [note: 1996] ok"


def test_unclosed_bracket_is_flushed_not_swallowed():
    assert stream(["tail [P1"], {"P1"})[0] == "tail [P1"
    assert stream(["a [ very long unclosed bracket that never ends"], set())[0] == "a [ very long unclosed bracket that never ends"


def test_typographic_spaces_and_hyphens_are_normalised():
    assert stream(["Ramesh\N{NARROW NO-BREAK SPACE}Kumar\N{NARROW NO-BREAK SPACE}v.\N{NARROW NO-BREAK SPACE}State \N{NON-BREAKING HYPHEN} PW\N{NON-BREAKING HYPHEN}1"], set())[0] == "Ramesh Kumar v. State - PW-1"


def test_newline_ends_a_bracket_candidate():
    assert stream(["[\nP1]"], {"P1"})[0] == "[\nP1]"


def test_full_width_citation_brackets_are_normalised_and_checked_like_ordinary_ones():
    assert stream(["case\u3010S1\u3011 and \u3010S7\u3011."], {"S1"})[0] == "case[S1] and ."
