from types import SimpleNamespace

import deepl
import pytest

from cuepipe.pipeline import Cue, PipelineError, run
from cuepipe.processors import build
from cuepipe.processors import translate as tr


class FakeClient:
    """Mimics DeepLClient.translate_text without any network access."""

    def __init__(self, fn=lambda t: f"<{t}>", fail=None, short=False):
        self.fn, self.fail, self.short, self.calls = fn, fail, short, []

    def translate_text(self, texts, **options):
        self.calls.append((list(texts), options))
        if self.fail:
            raise self.fail
        results = [SimpleNamespace(text=self.fn(t), billed_characters=len(t)) for t in texts]
        return results[:-1] if self.short else results


def cues(*texts):
    return [Cue(i, f"00:00:{i:02d},000", f"00:00:{i:02d},500", t) for i, t in enumerate(texts, 1)]


def test_translates_text_and_keeps_everything_else():
    client = FakeClient()
    out = run(cues("Hello", "Two\nlines"), [("translate", tr.make_processor(client, "id"))])
    assert [c.text for c in out] == ["<Hello>", "<Two\nlines>"]
    assert [c.start for c in out] == ["00:00:01,000", "00:00:02,000"]


def test_options_sent_to_deepl():
    client = FakeClient()
    tr.make_processor(client, "id", source="en", formality="prefer_less")(cues("x"))
    [(_, options)] = client.calls
    assert options == dict(
        target_lang="ID", source_lang="EN", formality="prefer_less",
        tag_handling="html", preserve_formatting=True, split_sentences="nonewlines",
    )


def test_tags_none_disables_tag_handling():
    client = FakeClient()
    tr.make_processor(client, "id", tags="none")(cues("x"))
    assert client.calls[0][1]["tag_handling"] is None


def test_duplicate_texts_are_translated_once():
    client = FakeClient()
    out = tr.make_processor(client, "id")(cues("Thank you.", "Hi", "Thank you."))
    assert client.calls[0][0] == ["Thank you.", "Hi"]
    assert [c.text for c in out] == ["<Thank you.>", "<Hi>", "<Thank you.>"]


def test_batches_of_50():
    client = FakeClient()
    tr.make_processor(client, "id")(cues(*[f"t{i}" for i in range(120)]))
    assert [len(texts) for texts, _ in client.calls] == [50, 50, 20]


@pytest.mark.parametrize("tags", ["html", "xml"])
def test_html_entities_in_the_result_are_decoded(tags):
    client = FakeClient(fn=lambda t: "&quot;Hi&quot; &amp; it&#39;s &lt;ok&gt;")
    out = tr.make_processor(client, "id", tags=tags)(cues("x"))
    assert out[0].text == "\"Hi\" & it's <ok>"


def test_entities_are_left_alone_when_tag_handling_is_off():
    client = FakeClient(fn=lambda t: "&quot;Hi&quot;")
    out = tr.make_processor(client, "id", tags="none")(cues("x"))
    assert out[0].text == "&quot;Hi&quot;"


def test_real_tags_survive_decoding():
    client = FakeClient(fn=lambda t: "<i>&quot;Hai&quot;</i>")
    out = tr.make_processor(client, "id")(cues("x"))
    assert out[0].text == '<i>"Hai"</i>'


def test_blank_translation_falls_back_to_original():
    client = FakeClient(fn=lambda t: "")
    out = tr.make_processor(client, "id")(cues("♪"))
    assert out[0].text == "♪"


def test_deepl_error_becomes_pipeline_error():
    client = FakeClient(fail=deepl.QuotaExceededException("quota used up"))
    with pytest.raises(PipelineError, match="DeepL: quota used up"):
        tr.make_processor(client, "id")(cues("x"))


def test_count_mismatch_is_detected():
    with pytest.raises(PipelineError, match="1 results for 2 texts"):
        tr.make_processor(FakeClient(short=True), "id")(cues("a", "b"))


def test_invalid_tags_mode():
    with pytest.raises(PipelineError, match="tags"):
        tr.make_processor(FakeClient(), "id", tags="markdown")


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv(tr.ENV_KEY, raising=False)
    with pytest.raises(PipelineError, match="DEEPL_AUTH_KEY is not set"):
        build("translate:to=id")


def test_registered_and_requires_target_language(monkeypatch):
    monkeypatch.setenv(tr.ENV_KEY, "dummy:fx")
    with pytest.raises(PipelineError, match="invalid parameters"):
        build("translate")
    name, _ = build("translate:to=id,source=en")
    assert name == "translate"
