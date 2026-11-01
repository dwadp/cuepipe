"""Command line interface: `cuepipe extract|inject|run`."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from . import srt, processors
from .pipeline import Cue, PipelineError, run

EXIT_OK = 0
EXIT_ERROR = 1


class CliError(Exception):
    """Usage error (wrong path, destination exists, ...)."""


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-s", "--source", required=True, type=Path, metavar="FILE",
        help="path of the source file (never modified)",
    )
    common.add_argument(
        "-d", "--destination", type=Path, metavar="FILE",
        help="path of the output file (parent folders are created if missing)",
    )
    common.add_argument(
        "-f", "--force", action="store_true",
        help="overwrite the destination if it already exists",
    )
    common.add_argument(
        "-e", "--encoding", default="utf-8", metavar="ENC",
        help="encoding of the SRT file (default: %(default)s)",
    )

    parser = argparse.ArgumentParser(
        prog="cuepipe",
        description="Extract subtitle text from SRT files and put it back in place "
        "without changing indexes, timestamps, or any other formatting.",
    )
    parser.add_argument("-V", "--version", action="version",
                        version=f"%(prog)s {version('cuepipe')}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_extract = sub.add_parser(
        "extract", parents=[common],
        help="SRT -> JSON with the id, timestamps, and text of each cue",
        description="Read an SRT file and write each cue's text to a JSON file.",
    )
    p_extract.set_defaults(func=cmd_extract)

    p_inject = sub.add_parser(
        "inject", parents=[common],
        help="SRT + JSON -> new SRT with the text replaced",
        description="Copy the source SRT, replace each cue's text from the JSON "
        "file, and write the result to the destination.",
    )
    p_inject.add_argument(
        "-t", "--texts", required=True, type=Path, metavar="FILE",
        help="JSON file produced by extract (after processing)",
    )
    p_inject.set_defaults(func=cmd_inject)

    p_run = sub.add_parser(
        "run", parents=[common],
        help="SRT -> processors -> SRT in a single command",
        description="Extract the text, run the processors in order, then put "
        "the result back into a new SRT. A processor is written as name or "
        "name:key=value,key=value and may be repeated.",
        epilog=f"available processors: {', '.join(processors.names())}",
    )
    p_run.add_argument(
        "-p", "--processor", action="append", required=True, dest="processors",
        metavar="PROCESSOR",
        help="processor, e.g. translate:to=ID (repeat to chain processors)",
    )
    p_run.set_defaults(func=cmd_run)
    return parser


def cmd_extract(args: argparse.Namespace) -> None:
    content = read_text(args.source, args.encoding)
    dest = args.destination or args.source.with_suffix(".json")
    cues = srt.extract(content)
    write_text(dest, json.dumps(cues, ensure_ascii=False, indent=2) + "\n",
               "utf-8", args.force, protect=args.source)
    print(f"{len(cues)} cues: {args.source} -> {dest}")


def cmd_inject(args: argparse.Namespace) -> None:
    content = read_text(args.source, args.encoding)
    try:
        texts = json.loads(read_text(args.texts, "utf-8"))
    except json.JSONDecodeError as e:
        raise CliError(f"{args.texts}: not valid JSON ({e})") from e
    result = srt.inject(content, texts)
    dest = args.destination or args.source.with_name(f"{args.source.stem}.out.srt")
    write_text(dest, result, args.encoding, args.force, protect=args.source)
    print(f"{len(texts)} cues: {args.source} + {args.texts} -> {dest}")


def cmd_run(args: argparse.Namespace) -> None:
    content = read_text(args.source, args.encoding)
    dest = args.destination or args.source.with_name(f"{args.source.stem}.out.srt")
    # do every cheap check before any processor runs, because a processor may call a paid API
    check_destination(dest, args.force, protect=args.source)
    pipeline = [processors.build(spec) for spec in args.processors]
    cues = [Cue(**d) for d in srt.extract(content)]

    def announce(n: int, total: int, name: str) -> None:
        print(f"[{n}/{total}] {name}", file=sys.stderr)

    cues = run(cues, pipeline, on_processor=announce)
    result = srt.inject(content, [asdict(c) for c in cues])
    write_text(dest, result, args.encoding, args.force, protect=args.source)
    print(f"{len(cues)} cues: {args.source} -> {dest}")


def read_text(path: Path, encoding: str) -> str:
    try:
        # newline="" -> Python does not translate \r\n, so the original bytes survive
        with open(path, encoding=encoding, newline="") as f:
            return f.read()
    except FileNotFoundError:
        raise CliError(f"file not found: {path}") from None
    except IsADirectoryError:
        raise CliError(f"not a file: {path}") from None
    except UnicodeDecodeError as e:
        raise CliError(
            f"{path}: cannot be read as {encoding} ({e.reason}); "
            "try the --encoding option"
        ) from e


def check_destination(path: Path, force: bool, protect: Path) -> None:
    if path.resolve() == protect.resolve():
        raise CliError("the destination must not be the same as the source file")
    if path.exists() and not force:
        raise CliError(f"destination already exists: {path} (use --force to overwrite)")


def write_text(path: Path, content: str, encoding: str, force: bool, protect: Path) -> None:
    check_destination(path, force, protect)
    # all processing is finished before we get here, so a parse failure
    # never leaves a half-written file behind
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(content)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (CliError, srt.SubtitleError, PipelineError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK
