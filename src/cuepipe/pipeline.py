"""Text-processing pipeline contract.

A processor is a function `list[Cue] -> list[Cue]`. A processor may only change `text`;
after every processor `run()` checks that the number, order, `id`, `start`, and `end`
of the cues are unchanged, so no processor can corrupt the SRT.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace


class PipelineError(Exception):
    """A processor failed or broke the contract; the message is safe to show to the user."""


@dataclass(frozen=True)
class Cue:
    id: int
    start: str
    end: str
    text: str


Processor = Callable[[list[Cue]], list[Cue]]


def per_cue(fn: Callable[[str], str]) -> Processor:
    """Wrap a `str -> str` function into a processor applied to every cue."""

    def processor(cues: list[Cue]) -> list[Cue]:
        return [replace(c, text=fn(c.text)) for c in cues]

    return processor


def run(
    cues: list[Cue],
    processors: Sequence[tuple[str, Processor]],
    on_processor: Callable[[int, int, str], None] | None = None,
) -> list[Cue]:
    """Run the processors in order; one processor's output is the next processor's input."""
    for n, (name, processor) in enumerate(processors, 1):
        if on_processor:
            on_processor(n, len(processors), name)
        try:
            out = processor(cues)
        except PipelineError as e:
            raise PipelineError(f"processor {name!r}: {e}") from e
        check_invariants(name, cues, out)
        cues = out
    return cues


def check_invariants(name: str, before: list[Cue], after: object) -> None:
    def fail(msg: str) -> PipelineError:
        return PipelineError(f"processor {name!r} violated the contract: {msg}")

    if not isinstance(after, list) or not all(isinstance(c, Cue) for c in after):
        raise fail("the result must be a list[Cue]")
    if len(after) != len(before):
        raise fail(f"cue count changed ({len(before)} -> {len(after)})")
    for b, a in zip(before, after):
        if a.id != b.id:
            raise fail(f"cue order/id changed (expected {b.id}, got {a.id})")
        if (a.start, a.end) != (b.start, b.end):
            raise fail(f"cue {b.id} timestamp changed")
        if not isinstance(a.text, str) or not a.text.strip():
            raise fail(f"cue {b.id} text is empty")
