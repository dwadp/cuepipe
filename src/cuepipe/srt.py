"""Lossless lexer + state machine for SRT.

Every line of the file becomes one `Token` that keeps `raw` (the line content
including its line ending), so `"".join(t.raw for t in tokenize(x)) == x`.
Injecting only replaces TEXT tokens; every other token is copied as-is.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto


class SubtitleError(ValueError):
    """Invalid subtitle file or text data; the message is safe to show to the user."""


class Kind(Enum):
    BOM = auto()
    BLANK = auto()
    INDEX = auto()
    TIME = auto()
    TEXT = auto()


@dataclass(frozen=True)
class Token:
    kind: Kind
    raw: str  # line content + line ending, exactly as in the file

    @property
    def body(self) -> str:
        return self.raw.rstrip("\r\n")

    @property
    def eol(self) -> str:
        return self.raw[len(self.body):]


@dataclass(frozen=True)
class Cue:
    id: int
    start: int  # index of the first TEXT token
    end: int  # exclusive


_TIME_LINE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})[ \t]*-->[ \t]*"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3}).*"
)
_BLANK_INSIDE = re.compile(r"\n[ \t]*\n")


def _is_index(line: str) -> bool:
    return line.strip().isdigit()


def _is_time(line: str) -> bool:
    return _TIME_LINE.fullmatch(line.strip()) is not None


def tokenize(content: str) -> list[Token]:
    """Split the file into tokens. The context (state) decides each line's kind."""
    tokens: list[Token] = []
    if content.startswith("﻿"):
        tokens.append(Token(Kind.BOM, "﻿"))
        content = content[1:]

    lines = content.splitlines(keepends=True)
    state = "INDEX"  # INDEX -> TIME -> TEXT -> (BLANK) -> INDEX ...
    for i, raw in enumerate(lines):
        body = raw.rstrip("\r\n")
        nxt = lines[i + 1].rstrip("\r\n") if i + 1 < len(lines) else ""

        if not body.strip():
            tokens.append(Token(Kind.BLANK, raw))
            state = "INDEX"
        elif state == "INDEX" and _is_index(body):
            tokens.append(Token(Kind.INDEX, raw))
            state = "TIME"
        elif state == "TIME" and _is_time(body):
            tokens.append(Token(Kind.TIME, raw))
            state = "TEXT"
        elif state == "TEXT" and _is_index(body) and _is_time(nxt):
            # lookahead: a number with a timestamp below it starts a new cue,
            # even when the separating blank line is missing
            tokens.append(Token(Kind.INDEX, raw))
            state = "TIME"
        elif state == "TEXT":
            tokens.append(Token(Kind.TEXT, raw))
        else:
            expected = {"INDEX": "an index number", "TIME": "a timestamp"}[state]
            raise SubtitleError(f"line {i + 1}: expected {expected}, found {body!r}")

    if state == "TIME":
        raise SubtitleError("file ends after an index number without a timestamp")
    return tokens


def find_cues(tokens: list[Token]) -> list[Cue]:
    cues: list[Cue] = []
    i = 0
    while i < len(tokens):
        if tokens[i].kind is Kind.INDEX:
            cue_id = int(tokens[i].body)
            start = end = i + 2  # skip the INDEX and TIME tokens
            while end < len(tokens) and tokens[end].kind is Kind.TEXT:
                end += 1
            cues.append(Cue(cue_id, start, end))
            i = end
        else:
            i += 1

    ids = [c.id for c in cues]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        raise SubtitleError(f"duplicate cue indexes in file: {dupes}")
    return cues


def _cue_times(tokens: list[Token], cue: Cue) -> tuple[str, str]:
    """Start and end timestamps of a cue, spelled exactly as in the file."""
    m = _TIME_LINE.fullmatch(tokens[cue.start - 1].body.strip())
    return m["start"], m["end"]


def extract(content: str) -> list[dict]:
    """Return every cue as [{"id", "start", "end", "text"}, ...].

    `start` and `end` are metadata only; `inject` never writes them to the SRT.
    """
    tokens = tokenize(content)
    cues = []
    for c in find_cues(tokens):
        start, end = _cue_times(tokens, c)
        text = "\n".join(t.body for t in tokens[c.start:c.end])
        cues.append({"id": c.id, "start": start, "end": end, "text": text})
    return cues


def inject(content: str, texts: list[dict]) -> str:
    """Replace each cue's text with `texts`; everything else stays untouched.

    If `texts` contains `start`/`end`, they must equal the source file's values
    (a safeguard against JSON from another file or accidentally edited timestamps).
    """
    new = _validate_texts(texts)
    tokens = tokenize(content)
    cues = find_cues(tokens)

    known = {c.id for c in cues}
    if unknown := sorted(set(new) - known):
        raise SubtitleError(f"ids not found in the source file: {unknown}")
    if missing := sorted(known - set(new)):
        raise SubtitleError(f"cues missing from the text data: {missing}")

    default_eol = next((t.eol for t in tokens if t.eol), "\n")
    out: list[str] = []
    pos = 0
    for c in cues:
        item = new[c.id]
        for key, expected in zip(("start", "end"), _cue_times(tokens, c)):
            if key in item and item[key] != expected:
                raise SubtitleError(
                    f"cue {c.id}: {key} in the text data ({item[key]}) differs from "
                    f"the source file ({expected}); inject does not change timestamps"
                )
        text = item["text"]
        if not text.strip() or _BLANK_INSIDE.search(text):
            raise SubtitleError(
                f"cue {c.id}: text is empty or contains a blank line "
                "(this would break the SRT structure)"
            )
        out.extend(t.raw for t in tokens[pos:c.start])
        old = tokens[c.start:c.end]
        eol = old[0].eol or default_eol
        lines = text.split("\n")
        # the last line inherits the original ending (e.g. "" at end of file)
        ends = [eol] * (len(lines) - 1) + [old[-1].eol]
        out.extend(line + end for line, end in zip(lines, ends))
        pos = c.end
    out.extend(t.raw for t in tokens[pos:])
    return "".join(out)


def _validate_texts(texts) -> dict[int, dict]:
    if not isinstance(texts, list):
        raise SubtitleError('text data must be a list: [{"id": 1, "text": "..."}]')
    result: dict[int, dict] = {}
    for n, item in enumerate(texts, 1):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), int)
            or not isinstance(item.get("text"), str)
            or not all(isinstance(item.get(k, ""), str) for k in ("start", "end"))
        ):
            raise SubtitleError(
                f'item #{n} is invalid, expected {{"id": 1, "text": "..."}} '
                "(start/end are optional strings)"
            )
        if item["id"] in result:
            raise SubtitleError(f"duplicate id in text data: {item['id']}")
        result[item["id"]] = {**item, "text": item["text"].replace("\r\n", "\n")}
    return result
