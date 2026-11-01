from dataclasses import replace

import pytest

from cuepipe.pipeline import Cue, PipelineError, per_cue, run
from cuepipe.processors import registry

CUES = [
    Cue(1, "00:00:01,000", "00:00:02,000", "hello"),
    Cue(2, "00:00:03,000", "00:00:04,000", "world"),
]


def test_per_cue_changes_only_text():
    out = run(CUES, [("up", per_cue(str.upper))])
    assert [(c.id, c.start, c.end, c.text) for c in out] == [
        (1, "00:00:01,000", "00:00:02,000", "HELLO"),
        (2, "00:00:03,000", "00:00:04,000", "WORLD"),
    ]
    assert CUES[0].text == "hello"  # the input is not mutated


def test_processors_are_chained_in_order():
    processors = [("a", per_cue(lambda t: t + "1")), ("b", per_cue(lambda t: t + "2"))]
    assert [c.text for c in run(CUES, processors)] == ["hello12", "world12"]


def test_on_processor_reports_progress():
    seen = []
    run(CUES, [("a", per_cue(str)), ("b", per_cue(str))], on_processor=lambda *a: seen.append(a))
    assert seen == [(1, 2, "a"), (2, 2, "b")]


@pytest.mark.parametrize(
    "processor, message",
    [
        (lambda cues: cues[:1], "cue count changed"),
        (lambda cues: list(reversed(cues)), "cue order/id changed"),
        (lambda cues: [replace(cues[0], id=9), cues[1]], "cue order/id changed"),
        (lambda cues: [replace(cues[0], end="00:00:09,000"), cues[1]], "cue 1 timestamp changed"),
        (lambda cues: [replace(cues[0], text="  "), cues[1]], "cue 1 text is empty"),
        (lambda cues: [c.text for c in cues], "must be a list"),
    ],
)
def test_contract_violations_name_the_processor(processor, message):
    with pytest.raises(PipelineError, match=rf"processor 'bad' violated the contract: .*{message}"):
        run(CUES, [("bad", processor)])


def test_processor_error_gets_processor_name():
    def boom(cues):
        raise PipelineError("broken")

    with pytest.raises(PipelineError, match="processor 'boom': broken"):
        run(CUES, [("boom", boom)])


def test_empty_cue_list_is_fine():
    assert run([], [("up", per_cue(str.upper))]) == []


class TestRegistry:
    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch):
        monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

    def test_build_with_params(self):
        @registry.register("suffix")
        def suffix(text, times="1"):
            return per_cue(lambda t: t + text * int(times))

        name, processor = registry.build("suffix:text=!,times=2")
        assert name == "suffix"
        assert processor(CUES)[0].text == "hello!!"

    def test_build_without_params(self):
        registry.register("noop")(lambda: per_cue(str))
        assert registry.build("noop")[0] == "noop"

    def test_unknown_processor_lists_available(self):
        with pytest.raises(PipelineError, match=r"unknown processor .*translate"):
            registry.build("nope")

    @pytest.mark.parametrize("spec", ["noop:extra=1", "noop:not-a-pair"])
    def test_bad_params(self, spec):
        registry.register("noop")(lambda: per_cue(str))
        with pytest.raises(PipelineError):
            registry.build(spec)
