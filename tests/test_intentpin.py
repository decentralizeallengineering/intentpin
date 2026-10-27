import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import intentpin  # noqa: E402


def env(tmp_path, **extra):
    base = {k: v for k, v in os.environ.items()
            if not k.startswith("INTENTPIN_") and k not in ("INTENT_FILE", "RULES_FILE")}
    base.update(INTENTPIN_DIR=str(tmp_path / "cfg"), INTENTPIN_STATE_DIR=str(tmp_path / "state"))
    base.update(extra)
    return base


def hook(tmp_path, payload, raw=None, **extra):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "intentpin.py"), "hook"],
                       input=raw if raw is not None else json.dumps(payload),
                       capture_output=True, text=True, env=env(tmp_path, **extra))
    assert r.returncode == 0
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else None


def test_add_appends_dated_line_and_show_prints_it(tmp_path, monkeypatch, capsys):
    for k, v in env(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert intentpin.main(["add", "Ann Example wants tests before every release."]) == 0
    assert intentpin.main(["add", "Line one\nline two"]) == 0
    log = (tmp_path / "cfg" / "rules.log").read_text()
    lines = log.splitlines()
    assert lines[0].startswith("- 20") and " UTC: Ann Example wants tests before every release." in lines[0]
    assert lines[2] == "  line two"  # multi-line words stay inside one entry
    capsys.readouterr()
    assert intentpin.main(["show"]) == 0
    shown = capsys.readouterr().out
    assert "Ann Example wants tests before every release." in shown and "Newer entries override older ones" in shown
    assert intentpin.main(["add", "   "]) == 2


def test_newest_entries_win_under_the_cap(tmp_path, monkeypatch):
    for k, v in env(tmp_path, INTENTPIN_RULES_CAP="400").items():
        monkeypatch.setenv(k, v)
    for i in range(30):
        intentpin.add(f"rule number {i:02d} " + "x" * 30)
    text = intentpin.build_context()
    assert "rule number 29" in text and "rule number 00" not in text
    assert "older entries are left out" in text and "read the full log" in text
    body = text.split("\n", 2)[2] if text.startswith("STANDING") else text
    assert all(line.startswith("- ") for line in body.splitlines() if "rule number" in line)  # whole entries only
    assert len(text.encode()) < 400 + 600  # header and pointer stay small


def test_intent_page_included_and_capped(tmp_path, monkeypatch):
    for k, v in env(tmp_path, INTENTPIN_INTENT_CAP="300").items():
        monkeypatch.setenv(k, v)
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "intent.md").write_text("Ship small, tested changes.\n" + "filler " * 400)
    intentpin.add("Never skip a failing test.")
    text = intentpin.build_context()
    assert text.index("Never skip a failing test.") < text.index("Ship small, tested changes.")
    assert len(text.split("INTENT PAGE", 1)[1].encode()) < 400
    assert intentpin.newest("- a\n- b", 5000) == ("- a\n- b", 0)


def test_hook_dedupes_per_session_and_repeats_after_compaction(tmp_path):
    intentpin_env = env(tmp_path)
    os.makedirs(intentpin_env["INTENTPIN_DIR"])
    with open(os.path.join(intentpin_env["INTENTPIN_DIR"], "rules.log"), "w") as fh:
        fh.write("- 2026-01-01 00:00 UTC: Always report the test command.\n")
    start = {"session_id": "s1", "source": "startup"}
    first = hook(tmp_path, start)
    assert first and "Always report the test command." in first
    assert hook(tmp_path, start) is None  # same session, unchanged text
    assert hook(tmp_path, {"session_id": "s2", "source": "startup"}) == first  # other session still gets it
    assert hook(tmp_path, {"session_id": "s1", "source": "compact"}) == first  # compaction resets
    with open(os.path.join(intentpin_env["INTENTPIN_DIR"], "rules.log"), "a") as fh:
        fh.write("- 2026-01-02 00:00 UTC: New rule.\n")
    assert "New rule." in hook(tmp_path, start)  # changed text is sent again


def test_hook_fails_open_and_kill_switch(tmp_path):
    assert hook(tmp_path, {"session_id": "s1"}) is None  # nothing configured
    os.makedirs(tmp_path / "cfg")
    (tmp_path / "cfg" / "rules.log").write_text("- 2026-01-01 00:00 UTC: Keep it.\n")
    assert hook(tmp_path, None, raw="not json") is not None  # bad stdin still injects, no crash
    assert hook(tmp_path, {"session_id": "s9"}, INTENTPIN_OFF="1") is None
    r = subprocess.run([sys.executable, os.path.join(ROOT, "intentpin.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "add" in r.stdout and "show" in r.stdout
