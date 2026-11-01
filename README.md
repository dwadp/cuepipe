# cuepipe

Extract the text of an SRT subtitle, process it (translate, fix, clean up, ...), and put
it back in its original position. Indexes, timestamps, blank lines, the BOM, and the
newline style (`\n` / `\r\n`) are never changed; only the cue text is replaced.

It is built on a lexer + state machine (`src/cuepipe/srt.py`): every line becomes
a token that keeps its original text, so the file can be rebuilt byte for byte. There are
no runtime dependencies besides the `deepl` client used by the `translate` processor.

## Usage

```bash
# 1. SRT -> JSON with the id, timestamps, and text of each cue
uv run cuepipe extract -s movie.srt -d work/texts.json

# 2. edit "text" in texts.json (do not touch "id")

# 3. original SRT + JSON -> new SRT
uv run cuepipe inject -s movie.srt -t work/texts.json -d result/movie.new.srt
```

| Option | Command | Description |
|---|---|---|
| `-s, --source FILE` | all | source file, never modified (required) |
| `-d, --destination FILE` | all | output file; parent folders are created. Default: `<source>.json` (extract), `<source>.out.srt` (inject, run) |
| `-t, --texts FILE` | inject | JSON from extract, after processing (required) |
| `-p, --processor PROCESSOR` | run | processor, repeat to chain (required) |
| `-f, --force` | all | overwrite an existing destination |
| `-e, --encoding ENC` | all | encoding of the SRT file, default `utf-8` |

Exit code `0` on success, `1` on failure (message on stderr), `2` on invalid arguments.

JSON format:

```json
[
  {"id": 1, "start": "00:00:02,567", "end": "00:00:04,178", "text": "line 1"},
  {"id": 2, "start": "00:00:04,221", "end": "00:00:06,702", "text": "line 1\nline 2"}
]
```

`start` and `end` are metadata, written exactly as in the source file. They are only
read as a safeguard: `inject` never writes them to the SRT, and it refuses to run if they
differ from the source file (an edited timestamp, or JSON that belongs to another file).
Both may be removed from the JSON.

`inject` matches cues by `id` (not by order) and rejects missing cues, unknown or
duplicate `id`s, empty text, and text containing a blank line.

## Processing pipeline (`run`)

`run` does the whole job in one command: extract, a chain of processors, then inject into a
new SRT. A processor is written as `name` or `name:key=value,key=value`, and `-p` can be
repeated to chain processors (one processor's output is the next processor's input).

```bash
export DEEPL_AUTH_KEY="..."   # DeepL API key (a :fx suffix means a Free account)
uv run cuepipe run -s movie.srt -d movie.id.srt -p translate:to=ID
```

All cheap checks (destination already exists, unknown processor, missing API key) run
**before** the first processor starts, so no paid API call is wasted.

### The `translate` processor (DeepL)

| Parameter | Description |
|---|---|
| `to` | target language, required (e.g. `ID`, `DE`, `EN-US`) |
| `source` | source language; auto-detected by default |
| `formality` | `default`, `more`, `less`, `prefer_more`, `prefer_less` |
| `tags` | `html` (default), `xml`, `none`: how DeepL treats markup such as `<i>` |

Identical texts are translated once, texts are sent 50 per request, and the number of
billed characters is printed to stderr. With `tags=html` or `xml` DeepL returns
HTML-escaped text (`&quot;`, `&amp;`, ...); the processor decodes it back into plain
characters. The API key is only read from the `DEEPL_AUTH_KEY` environment variable,
never from a CLI argument.

### Writing your own processor

A processor is a function `list[Cue] -> list[Cue]`. After every processor the pipeline checks that
the number, order, `id`, `start`, and `end` of the cues are unchanged and that no text is
empty, so no processor can corrupt the SRT.

```python
from cuepipe.pipeline import per_cue
from cuepipe.processors import register

@register("shout")                       # used as: -p shout:mark=!
def shout(mark: str = "!"):              # every CLI parameter is a str
    return per_cue(lambda text: text.upper() + mark)
```

A processor that needs context (it looks at the surrounding cues) receives the whole list
instead of one cue at a time. See `src/cuepipe/processors/translate.py` for a complete
example.

## Development

```bash
uv sync
uv run pytest
```
