"""Turn pasted text, .txt, .docx or .vtt transcripts into a common Transcript."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".docx", ".vtt"}


class TranscriptError(ValueError):
    """Raised when a transcript is empty or in an unsupported format."""


@dataclass
class Segment:
    speaker: str | None
    text: str
    timestamp: str | None = None


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    source_format: str = "text"

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in self.segments:
            if s.speaker:
                seen.setdefault(s.speaker, None)
        return list(seen)

    def to_text(self) -> str:
        """Render as '[timestamp] Speaker: text' lines, the form sent to the model."""
        lines = []
        for s in self.segments:
            prefix = f"[{s.timestamp}] " if s.timestamp else ""
            who = f"{s.speaker}: " if s.speaker else ""
            lines.append(f"{prefix}{who}{s.text}")
        return "\n".join(lines)

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)


# --- VTT -----------------------------------------------------------------

_VTT_TIME = re.compile(r"^(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+")
_VTT_VOICE = re.compile(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$", re.DOTALL)


def parse_vtt(content: str) -> Transcript:
    lines = content.replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].lstrip("﻿").startswith("WEBVTT"):
        raise TranscriptError("Not a valid .vtt file (missing WEBVTT header).")

    segments: list[Segment] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if _VTT_TIME.match(line):
            timestamp = _short_time(line.split("-->")[0].strip())
            i += 1
            cue_lines = []
            while i < len(lines) and lines[i].strip():
                cue_lines.append(lines[i].strip())
                i += 1
            cue = " ".join(cue_lines)
            speaker = None
            m = _VTT_VOICE.match(cue)
            if m:
                speaker, cue = m.group(1).strip(), m.group(2)
            text = re.sub(r"<[^>]+>", "", cue).strip()
            if text:
                _append(segments, Segment(speaker, text, timestamp))
        i += 1
    return _finish(segments, "vtt")


def _short_time(t: str) -> str:
    """'00:01:05.120' -> '01:05'; '01:02:03.000' -> '1:02:03'."""
    t = t.replace(",", ".").split(".")[0]
    parts = t.split(":")
    if len(parts) == 3 and parts[0] in ("0", "00"):
        return f"{parts[1]}:{parts[2]}"
    if len(parts) == 3:
        return f"{int(parts[0])}:{parts[1]}:{parts[2]}"
    return t


def _append(segments: list[Segment], seg: Segment) -> None:
    """Merge consecutive cues from the same speaker (Teams splits long turns)."""
    if segments and segments[-1].speaker == seg.speaker and seg.speaker is not None:
        segments[-1].text = f"{segments[-1].text} {seg.text}"
    else:
        segments.append(seg)


# --- Plain text / docx -------------------------------------------------------

# A speaker name: one to four capitalised words ("Priya Nair", "Dr. Mei Chen").
_NAME = r"[A-Z][\w.'\-]*(?: [A-Z][\w.'\-]*){0,3}"
# Teams .docx export: "Priya Nair   0:05" on its own line, text on the next lines.
_HEADER = re.compile(rf"^(?P<speaker>{_NAME})\s{{2,}}(?P<ts>\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*$")
# "[00:05] Priya Nair: text" or "Priya Nair: text"
_INLINE = re.compile(
    rf"^(?:\[(?P<ts>\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\]\s*)?(?P<speaker>{_NAME}):\s+(?P<text>.+)$"
)


def parse_text(content: str, source_format: str = "text") -> Transcript:
    lines = [ln.strip() for ln in content.replace("\r\n", "\n").split("\n") if ln.strip()]
    # If the file uses "Name   0:05" headers, don't also treat "Word: ..." inside
    # the spoken text as a new speaker.
    header_mode = any(_HEADER.match(ln) for ln in lines)
    segments: list[Segment] = []
    current: Segment | None = None
    for line in lines:
        if m := _HEADER.match(line):
            current = Segment(m["speaker"].strip(), "", m["ts"])
            segments.append(current)
        elif not header_mode and (m := _INLINE.match(line)):
            current = Segment(m["speaker"].strip(), m["text"].strip(), m["ts"])
            segments.append(current)
        elif current is not None:
            current.text = f"{current.text} {line}".strip()
        else:
            current = Segment(None, line)
            segments.append(current)
    return _finish([s for s in segments if s.text], source_format)


def parse_docx(data: bytes) -> Transcript:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several types for bad files
        raise TranscriptError(f"Could not read .docx file: {exc}") from exc
    text = "\n".join(p.text for p in doc.paragraphs)
    return parse_text(text, "docx")


def _finish(segments: list[Segment], source_format: str) -> Transcript:
    if not segments:
        raise TranscriptError("The transcript is empty.")
    return Transcript(segments, source_format)


# --- Entry point ---------------------------------------------------------------

def parse_transcript(*, text: str | None = None, filename: str | None = None, data: bytes | None = None) -> Transcript:
    """Parse pasted text, or an uploaded file given its name and bytes."""
    if text is not None:
        text = text.strip()
        if not text:
            raise TranscriptError("The transcript is empty.")
        return parse_vtt(text) if text.startswith("WEBVTT") else parse_text(text, "text")

    if filename is None or data is None:
        raise TranscriptError("Provide pasted text or a file.")
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise TranscriptError(f"Unsupported file type '{ext}'. Use .txt, .docx or .vtt.")
    if not data:
        raise TranscriptError("The file is empty.")
    if ext == ".docx":
        return parse_docx(data)
    content = data.decode("utf-8-sig", errors="replace")
    return parse_vtt(content) if ext == ".vtt" else parse_text(content, "txt")
