# cuepipe: project context

CLI that extracts the text of SRT subtitles, runs it through a chain of processors
(e.g. DeepL translation), and writes it back. See `README.md` for usage.

The core requirement: **only cue text may change.** Indexes, timestamps, blank lines, the
BOM, and the newline style must survive byte for byte.

## Commands

```bash
uv sync
uv run pytest
uv run cuepipe run -s movie.srt -d movie.id.srt -p translate:to=ID
```

`uv` is the only runner and package manager. The `translate` processor reads its API key
from `DEEPL_AUTH_KEY`.

## Layout

- `src/cuepipe/srt.py`: lossless lexer + state machine, `extract()`, `inject()`
- `src/cuepipe/pipeline.py`: `Cue`, the `Processor` contract, `per_cue()`, `run()`, `check_invariants()`
- `src/cuepipe/processors/registry.py`: `@register`, `build()` for `name:key=value,key=value`
- `src/cuepipe/processors/translate.py`: DeepL processor
- `src/cuepipe/cli.py`: argparse commands `extract`, `inject`, `run`, and file I/O

## Design decisions

- **Lexer, not parse-and-rewrite.** Every line becomes a token that keeps its raw text, so
  the original is `"".join(t.raw ...)`. Libraries such as `pysrt` and `srt` rewrite the
  file, which breaks the core requirement. A regex-only version swallowed the next cue when
  a separating blank line was missing, so the lexer uses a lookahead for that case.
- **Files are opened with `newline=""`** so `\r\n` is not translated.
- **A processor is `list[Cue] -> list[Cue]`.** `run()` checks count, order, `id`, `start`,
  `end`, and non-empty text after each processor, so the pipeline enforces the core
  requirement rather than each processor author. Use `per_cue()` for `str -> str` work;
  take the whole list when context is needed.
- **`start`/`end` in the JSON are metadata.** `inject` never writes them. It rejects values
  that differ from the source (edited timestamps or JSON from another file) and accepts
  JSON without them.
- **Cheap checks run before the first processor** (destination exists, unknown processor,
  missing key), because a processor may call a paid API. Nothing is written if a run fails.
- **The source file is never modified**, and the destination may not equal the source.
- **The API key comes only from the environment**, never a CLI argument (shell history).
- **Registry first, entry points later.** The contract stays the same if plugins move to
  separate packages through Python entry points.

## DeepL behavior

- `tags=html` (the default) makes DeepL return HTML-escaped text such as `&quot;`. The
  processor decodes results with `html.unescape`. Covered by fake-client tests only; a real
  run on text containing quotes has not been confirmed yet.
- A real run on a small sample kept line breaks, `<i>` tags, `{\an8}`, `♪`, and a speaker
  label (`ANNA:`) intact, so a `protect` processor (masking markup with placeholders) is
  not needed so far. Add it if real files show damage.
- Identical texts are translated once. Requests carry at most 50 texts.
- Each cue is translated separately, so sentences spanning cues can lose quality. DeepL's
  `context` parameter is a possible improvement.

## Naming

- **cuepipe**: a cue is one subtitle unit (text plus a time range), and the word stays valid
  if other formats are added. `srtpipe` would lock the name to SRT.
- **processor**: the unit in a pipeline. Not `step` (only a position), `pipe` (the connector
  in pipes-and-filters), or `filter` (implies removal).

## Possible future work

- stdin/stdout through `-` so external tools can act as a Unix pipe
- A TOML pipeline config, and a translation cache to avoid paying twice on reruns
- Other formats (WebVTT, ASS, TTML): split the lexer per format behind the same
  `extract`/`inject`, keep format-specific metadata in tokens rather than `Cue`, normalize
  line breaks to `\n`, and stop assuming an integer `Cue.id` (ASS has none, WebVTT allows text)
- Add a license before the repository goes public (none has been chosen yet)

## Conventions

- All code, comments, CLI messages, tests, and docs are in English. The maintainer usually
  discusses the project in Indonesian.
- Commits use `Adi Perdana <dewaadiperdana@gmail.com>` as author, with no co-author lines.
  The machine's default git identity is a work email, so pass the identity explicitly unless
  the repository config has been changed.
- Never commit API keys.
