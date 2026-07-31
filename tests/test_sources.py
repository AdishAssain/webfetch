from webfetch.sources import _feed_to_text, _vtt_to_text, host_of, route


def test_route_returns_none_for_ordinary_hosts():
    assert route("https://example.com/page") is None


def test_host_of_lowercases_and_handles_missing_host():
    assert host_of("https://WWW.YouTube.com/watch?v=x") == "www.youtube.com"
    assert host_of("not a url") == ""


def test_vtt_drops_headers_timestamps_and_cue_numbers():
    vtt = (
        "WEBVTT\n"
        "Kind: captions\n"
        "Language: en\n"
        "\n"
        "1\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "the first line\n"
        "\n"
        "2\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "the second line\n"
    )
    assert _vtt_to_text(vtt) == "the first line\nthe second line"


def test_vtt_collapses_consecutive_duplicates():
    # Auto-captions repeat each line as the next cue scrolls in. Without the
    # collapse a transcript roughly triples in size.
    vtt = (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:02.000\n"
        "same line\n\n"
        "00:00:02.000 --> 00:00:04.000\n"
        "same line\n\n"
        "00:00:04.000 --> 00:00:06.000\n"
        "next line\n"
    )
    assert _vtt_to_text(vtt) == "same line\nnext line"


def test_vtt_strips_inline_timing_tags():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<00:00:00.500><c>hello</c> there\n"
    assert _vtt_to_text(vtt) == "hello there"


def test_feed_extracts_title_author_and_link():
    xml = (
        "<feed><entry>"
        "<title>A post title</title>"
        "<author><name>/u/somebody</name></author>"
        "<updated>2026-07-25T07:00:32+00:00</updated>"
        '<link href="https://www.reddit.com/r/x/comments/1/a/"/>'
        "<content>&lt;p&gt;body text&lt;/p&gt;</content>"
        "</entry></feed>"
    )
    text = _feed_to_text(xml)
    assert "## A post title" in text
    assert "/u/somebody" in text
    assert "https://www.reddit.com/r/x/comments/1/a/" in text
    assert "body text" in text


def test_feed_returns_empty_string_without_entries():
    assert _feed_to_text("<feed></feed>") == ""
