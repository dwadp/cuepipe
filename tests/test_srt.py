import json

import pytest

from cuepipe import srt
from cuepipe.srt import Kind, SubtitleError

LF = (
    "1\n00:00:01,000 --> 00:00:02,000\nHello there\n\n"
    "2\n00:00:03,000 --> 00:00:04,000\n<i>Two lines\nin one cue</i>\n\n"
    "3\n00:00:05,000 --> 00:00:06,000\n42"
)
CRLF_BOM = "﻿" + LF.replace("\n", "\r\n")


@pytest.mark.parametrize("content", [LF, CRLF_BOM, LF + "\n", LF + "\n\n\n"])
def test_tokens_rebuild_original(content):
    assert "".join(t.raw for t in srt.tokenize(content)) == content


@pytest.mark.parametrize("content", [LF, CRLF_BOM])
def test_roundtrip_without_edit_is_identical(content):
    assert srt.inject(content, srt.extract(content)) == content


def test_extract_texts():
    assert srt.extract(LF) == [
        {"id": 1, "start": "00:00:01,000", "end": "00:00:02,000", "text": "Hello there"},
        {"id": 2, "start": "00:00:03,000", "end": "00:00:04,000",
         "text": "<i>Two lines\nin one cue</i>"},
        # a number inside the text is not an index
        {"id": 3, "start": "00:00:05,000", "end": "00:00:06,000", "text": "42"},
    ]


def test_extract_keeps_timestamp_spelling_and_ignores_trailing_coordinates():
    content = "1\n00:00:01.500   -->   00:00:02.250 X1:100 X2:200\nhi\n"
    [cue] = srt.extract(content)
    assert (cue["start"], cue["end"]) == ("00:00:01.500", "00:00:02.250")
    assert srt.inject(content, [{**cue, "text": "hello"}]) == content.replace("hi", "hello")


def test_inject_accepts_texts_without_timestamps():
    texts = [{"id": c["id"], "text": c["text"]} for c in srt.extract(LF)]
    assert srt.inject(LF, texts) == LF


def test_inject_rejects_changed_timestamp():
    texts = srt.extract(LF)
    texts[1]["end"] = "00:00:09,999"
    with pytest.raises(SubtitleError, match=r"cue 2: end .* differs"):
        srt.inject(LF, texts)


def test_inject_rejects_timestamps_from_another_file():
    other = LF.replace("00:00:01,000", "00:10:01,000")
    with pytest.raises(SubtitleError, match=r"cue 1: start"):
        srt.inject(LF, srt.extract(other))


def test_inject_changes_only_text():
    texts = srt.extract(CRLF_BOM)
    texts[1]["text"] = "One\nTwo\nThree"
    out = srt.inject(CRLF_BOM, texts)
    assert out == CRLF_BOM.replace(
        "<i>Two lines\r\nin one cue</i>", "One\r\nTwo\r\nThree"
    )


def test_inject_matches_by_id_not_order():
    texts = list(reversed(srt.extract(LF)))
    assert srt.inject(LF, texts) == LF


def test_missing_blank_line_between_cues_uses_lookahead():
    content = (
        "1\n00:00:01,000 --> 00:00:02,000\nA\nB\n"
        "2\n00:00:03,000 --> 00:00:04,000\nC\n"
    )
    assert [(c["id"], c["text"]) for c in srt.extract(content)] == [
        (1, "A\nB"),
        (2, "C"),
    ]


def test_kinds_in_a_cue():
    kinds = [t.kind for t in srt.tokenize("1\n00:00:01,000 --> 00:00:02,000\nx\n\n")]
    assert kinds == [Kind.INDEX, Kind.TIME, Kind.TEXT, Kind.BLANK]


@pytest.mark.parametrize(
    "content, message",
    [
        ("hello\n", "line 1: expected an index number"),
        ("1\nnot a timestamp\n", "line 2: expected a timestamp"),
        ("1\n", "without a timestamp"),
        (LF + "\n\n1\n00:00:07,000 --> 00:00:08,000\nx", "duplicate cue indexes"),
    ],
)
def test_invalid_source(content, message):
    with pytest.raises(SubtitleError, match=message):
        srt.extract(content)


@pytest.mark.parametrize(
    "texts, message",
    [
        ("not a list", "must be a list"),
        ([{"id": "1", "text": "x"}], "is invalid"),
        ([{"id": 1, "text": "x", "start": 5}], "is invalid"),
        ([{"id": 1, "text": "x"}, {"id": 1, "text": "y"}], "duplicate id"),
        ([{"id": 1, "text": "x"}], "cues missing from the text data"),
        (
            [{"id": i, "text": "x"} for i in (1, 2, 3, 99)],
            "ids not found in the source file",
        ),
        (
            [{"id": 1, "text": ""}, {"id": 2, "text": "x"}, {"id": 3, "text": "x"}],
            "text is empty",
        ),
        (
            [{"id": 1, "text": "a\n\nb"}, {"id": 2, "text": "x"}, {"id": 3, "text": "x"}],
            "blank line",
        ),
    ],
)
def test_invalid_texts(texts, message):
    with pytest.raises(SubtitleError, match=message):
        srt.inject(LF, texts)


def test_extract_output_is_json_serialisable():
    json.dumps(srt.extract(LF), ensure_ascii=False)
