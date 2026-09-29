import io

import pytest
from docx import Document

from core.parsing import TranscriptError, parse_transcript
from core.samples import SAMPLE_TRANSCRIPTS, sample_project, sample_transcript_path

VTT = """WEBVTT

1
00:00:04.000 --> 00:00:09.000
<v Priya Nair>First point.</v>

2
00:00:10.000 --> 00:00:12.000
<v Priya Nair>Still Priya.</v>

00:01:05.500 --> 00:01:09.000
<v Mei Chen>Second <b>speaker</b>.</v>
"""


def test_vtt_speakers_timestamps_and_merge():
    t = parse_transcript(filename="m.vtt", data=VTT.encode())
    assert t.source_format == "vtt"
    assert t.speakers == ["Priya Nair", "Mei Chen"]
    assert len(t.segments) == 2
    assert t.segments[0].text == "First point. Still Priya."
    assert t.segments[0].timestamp == "00:04"
    assert t.segments[1].text == "Second speaker."
    assert t.to_text().splitlines()[1] == "[01:05] Mei Chen: Second speaker."


def test_vtt_without_header_is_rejected():
    with pytest.raises(TranscriptError):
        parse_transcript(filename="m.vtt", data=b"00:00:01.000 --> 00:00:02.000\nhi")


def test_pasted_vtt_is_detected():
    assert parse_transcript(text=VTT).source_format == "vtt"


def test_inline_text_format():
    t = parse_transcript(text="[00:10] Priya Nair: Hello\nMei Chen: Hi there\ncontinued line")
    assert [(s.speaker, s.text, s.timestamp) for s in t.segments] == [
        ("Priya Nair", "Hello", "00:10"),
        ("Mei Chen", "Hi there continued line", None),
    ]


def test_teams_header_format_ignores_colons_in_speech():
    text = "Priya Nair   0:03\nOn the traveller identifier: it is email.\n\nMei Chen   0:15\nOk."
    t = parse_transcript(text=text)
    assert t.speakers == ["Priya Nair", "Mei Chen"]
    assert t.segments[0].text == "On the traveller identifier: it is email."


def test_text_without_speakers_is_kept():
    t = parse_transcript(text="just some notes\nmore notes")
    assert t.speakers == []
    assert t.segments[0].text == "just some notes more notes"


def test_docx():
    doc = Document()
    for line in ["Priya Nair   0:03", "Hello team.", "Raj Patel   0:10", "Parsing is done."]:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    t = parse_transcript(filename="notes.docx", data=buf.getvalue())
    assert t.source_format == "docx"
    assert t.speakers == ["Priya Nair", "Raj Patel"]


@pytest.mark.parametrize("kwargs", [
    {"text": "   "},
    {"filename": "a.txt", "data": b""},
    {"filename": "a.pdf", "data": b"x"},
    {"filename": "a.docx", "data": b"not a docx"},
    {},
])
def test_invalid_inputs(kwargs):
    with pytest.raises(TranscriptError):
        parse_transcript(**kwargs)


@pytest.mark.parametrize("filename", SAMPLE_TRANSCRIPTS)
def test_sample_transcripts_parse_and_match_roster(filename):
    path = sample_transcript_path(filename)
    t = parse_transcript(filename=path.name, data=path.read_bytes())
    roster = {p["name"] for p in sample_project()["people"]}
    unknown = set(t.speakers) - roster
    # The kickoff deliberately includes one speaker who is not on the roster.
    assert unknown == ({"Sam Ortiz"} if filename.startswith("01") else set())
    assert t.word_count > 500
