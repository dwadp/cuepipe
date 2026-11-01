import json

import pytest

from cuepipe.cli import main

SRT = (
    "1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n\r\n"
    "2\r\n00:00:03,000 --> 00:00:04,000\r\nWorld\r\nAgain\r\n"
)


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "film.srt"
    p.write_bytes(SRT.encode())
    return p


def test_extract_then_inject_end_to_end(src, tmp_path, capsys):
    texts = tmp_path / "out" / "texts.json"  # folder does not exist yet -> created
    assert main(["extract", "-s", str(src), "-d", str(texts)]) == 0
    data = json.loads(texts.read_text())
    assert data == [
        {"id": 1, "start": "00:00:01,000", "end": "00:00:02,000", "text": "Hello"},
        {"id": 2, "start": "00:00:03,000", "end": "00:00:04,000", "text": "World\nAgain"},
    ]

    data[0]["text"] = "Hi"
    texts.write_text(json.dumps(data))

    dest = tmp_path / "film.new.srt"
    assert main(["inject", "-s", str(src), "-t", str(texts), "-d", str(dest)]) == 0
    assert dest.read_bytes() == SRT.replace("Hello", "Hi").encode()
    assert src.read_bytes() == SRT.encode()  # the source is never modified


def test_default_destinations(src, tmp_path):
    assert main(["extract", "-s", str(src)]) == 0
    assert (tmp_path / "film.json").exists()
    assert main(["inject", "-s", str(src), "-t", str(tmp_path / "film.json")]) == 0
    assert (tmp_path / "film.out.srt").read_bytes() == SRT.encode()


def test_refuses_to_overwrite_without_force(src, tmp_path, capsys):
    dest = tmp_path / "texts.json"
    dest.write_text("old")
    assert main(["extract", "-s", str(src), "-d", str(dest)]) == 1
    assert "--force" in capsys.readouterr().err
    assert dest.read_text() == "old"

    assert main(["extract", "-s", str(src), "-d", str(dest), "--force"]) == 0
    assert dest.read_text() != "old"


def test_destination_cannot_be_source(src, capsys):
    assert main(["extract", "-s", str(src), "-d", str(src), "--force"]) == 1
    assert "same as the source file" in capsys.readouterr().err
    assert src.read_bytes() == SRT.encode()


def test_missing_source(tmp_path, capsys):
    assert main(["extract", "-s", str(tmp_path / "nope.srt")]) == 1
    assert "file not found" in capsys.readouterr().err


def test_invalid_json(src, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    assert main(["inject", "-s", str(src), "-t", str(bad)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_failed_inject_leaves_no_destination(src, tmp_path):
    texts = tmp_path / "t.json"
    texts.write_text(json.dumps([{"id": 1, "text": "x"}]))  # cue 2 is missing
    dest = tmp_path / "out.srt"
    assert main(["inject", "-s", str(src), "-t", str(texts), "-d", str(dest)]) == 1
    assert not dest.exists()


def test_wrong_encoding_message(tmp_path, capsys):
    p = tmp_path / "latin.srt"
    p.write_bytes("1\n00:00:01,000 --> 00:00:02,000\ncaf\xe9\n".encode("latin-1"))
    assert main(["extract", "-s", str(p)]) == 1
    assert "--encoding" in capsys.readouterr().err
    assert main(["extract", "-s", str(p), "-e", "latin-1"]) == 0


def test_requires_subcommand_and_source():
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main(["extract"])
    assert e.value.code == 2


class TestRun:
    @pytest.fixture(autouse=True)
    def _processors(self, monkeypatch):
        from cuepipe.pipeline import per_cue
        from cuepipe.processors import registry

        self.calls = []
        monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

        @registry.register("upper")
        def upper():
            def processor(cues):
                self.calls.append(len(cues))
                return per_cue(str.upper)(cues)
            return processor

        registry.register("tag")(lambda mark="!": per_cue(lambda t: t + mark))

    def test_chain_end_to_end(self, src, tmp_path, capsys):
        dest = tmp_path / "result" / "film.up.srt"
        assert main(["run", "-s", str(src), "-d", str(dest),
                     "-p", "upper", "-p", "tag:mark=?"]) == 0
        # `tag` appends the mark once at the end of each cue's text
        assert dest.read_bytes() == SRT.replace("Hello", "HELLO?").replace(
            "World\r\nAgain", "WORLD\r\nAGAIN?"
        ).encode()
        assert src.read_bytes() == SRT.encode()
        assert "[1/2] upper" in capsys.readouterr().err

    def test_default_destination(self, src, tmp_path):
        assert main(["run", "-s", str(src), "-p", "upper"]) == 0
        assert (tmp_path / "film.out.srt").exists()

    def test_existing_destination_is_checked_before_any_processor_runs(self, src, tmp_path, capsys):
        dest = tmp_path / "exists.srt"
        dest.write_text("old")
        assert main(["run", "-s", str(src), "-d", str(dest), "-p", "upper"]) == 1
        assert self.calls == []  # the processor (which may be paid) never ran
        assert "--force" in capsys.readouterr().err

    def test_unknown_processor_fails_before_writing(self, src, tmp_path, capsys):
        dest = tmp_path / "out.srt"
        assert main(["run", "-s", str(src), "-d", str(dest), "-p", "upper", "-p", "nope"]) == 1
        assert "unknown processor" in capsys.readouterr().err
        assert self.calls == [] and not dest.exists()

    def test_requires_at_least_one_processor(self, src):
        with pytest.raises(SystemExit) as e:
            main(["run", "-s", str(src)])
        assert e.value.code == 2
