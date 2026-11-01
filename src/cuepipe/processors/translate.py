"""Processor `translate`: translate each cue's text with the DeepL API.

  -p translate:to=ID
  -p translate:to=ID,source=EN,formality=prefer_less,tags=html

The API key is read from the DEEPL_AUTH_KEY environment variable (not from a CLI
argument, so it does not end up in shell history).
"""

import html
import os
import sys
from dataclasses import replace

import deepl

from ..pipeline import Cue, PipelineError, Processor
from .registry import register

ENV_KEY = "DEEPL_AUTH_KEY"
BATCH_SIZE = 50  # DeepL limit: at most 50 texts per request
TAG_MODES = ("html", "xml", "none")


@register("translate")
def translate(
    to: str,
    source: str | None = None,
    formality: str | None = None,
    tags: str = "html",
) -> Processor:
    """to: target language (e.g. ID, DE, EN-US); source: source language (default:
    auto-detect); formality: default/more/less/prefer_more/prefer_less; tags: how
    DeepL treats markup such as <i> (html/xml/none)."""
    return make_processor(_make_client(), to, source, formality, tags)


def _make_client() -> "deepl.DeepLClient":
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        raise PipelineError(f"environment variable {ENV_KEY} is not set")
    return deepl.DeepLClient(key)


def _decode(text: str, tags: str) -> str:
    """With tag handling on, DeepL returns HTML-escaped text (&quot; &amp; &#39;
    ...). Subtitles are plain text, so turn the entities back into characters."""
    return text if tags == "none" else html.unescape(text)


def make_processor(
    client,
    to: str,
    source: str | None = None,
    formality: str | None = None,
    tags: str = "html",
) -> Processor:
    """Build the processor from an existing client (tests pass a fake client)."""
    if tags not in TAG_MODES:
        raise PipelineError(f"invalid tags={tags!r} (choose from: {', '.join(TAG_MODES)})")
    options = dict(
        target_lang=to.upper(),
        source_lang=source.upper() if source else None,
        formality=formality,
        tag_handling=None if tags == "none" else tags,
        preserve_formatting=True,
        split_sentences="nonewlines",  # do not split sentences at line breaks
    )

    def processor(cues: list[Cue]) -> list[Cue]:
        # identical texts (e.g. "Thank you.") only need to be translated once
        unique = list(dict.fromkeys(c.text for c in cues))
        translated: dict[str, str] = {}
        billed = 0
        for i in range(0, len(unique), BATCH_SIZE):
            batch = unique[i:i + BATCH_SIZE]
            try:
                results = client.translate_text(batch, **options)
            except (deepl.DeepLException, ValueError) as e:
                raise PipelineError(f"DeepL: {e}") from e
            if len(results) != len(batch):
                raise PipelineError(
                    f"DeepL returned {len(results)} results for {len(batch)} texts"
                )
            for original, result in zip(batch, results):
                text = _decode(result.text, tags)
                # an empty result must never replace the original text
                translated[original] = text if text.strip() else original
                billed += getattr(result, "billed_characters", 0)
            print(
                f"  translate: {min(i + BATCH_SIZE, len(unique))}/{len(unique)} texts",
                file=sys.stderr,
            )
        print(f"  translate: {billed} characters billed", file=sys.stderr)
        return [replace(c, text=translated[c.text]) for c in cues]

    return processor
