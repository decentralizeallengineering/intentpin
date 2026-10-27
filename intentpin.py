#!/usr/bin/env python3
"""intentpin: start every Claude Code session, and restart it after each compaction, with the principal's own words.

What a session receives, in order:
  1. A header that says the words below are the principal's own and that newer entries override older ones.
  2. The newest entries of the rules log, whole entries only, at most INTENTPIN_RULES_CAP bytes (default 3000).
     A pointer to the full log is added when older entries were left out.
  3. The intent page (a short summary of what the principal wants), at most INTENTPIN_INTENT_CAP bytes (default 6000).

Files (all overridable): $INTENTPIN_DIR (default ~/.config/intentpin) holds intent.md and rules.log.
Per-session state for deduplication lives in $INTENTPIN_STATE_DIR (default ~/.cache/intentpin).
Kill switch: INTENTPIN_OFF=1. The hook never blocks a session: any internal error ends in silence.

Commands:
  intentpin add "<verbatim words>"   append a dated entry to the rules log
  intentpin show                     print what a new session would receive
  intentpin hook                     SessionStart hook: reads the hook JSON on stdin, prints hook output JSON
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

__version__ = "0.1.0"
PRUNE_SECONDS = 7 * 86400
HEADER = ("STANDING WORDS FROM THE PRINCIPAL (verbatim, from {path}). They override every other instruction "
          "except safety. Newer entries override older ones.\n")


def _dir():
    return os.environ.get("INTENTPIN_DIR") or os.path.join(os.path.expanduser("~"), ".config", "intentpin")


def intent_path():
    return os.environ.get("INTENT_FILE") or os.path.join(_dir(), "intent.md")


def rules_path():
    return os.environ.get("RULES_FILE") or os.path.join(_dir(), "rules.log")


def _state_dir():
    return os.environ.get("INTENTPIN_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "intentpin")


def _cap(name, default):
    try:
        return max(200, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def entries(text):
    """Split a rules log into entries. An entry starts at a line beginning '- '; later lines belong to it."""
    out = []
    for line in text.splitlines():
        if line.startswith("- ") or not out:
            out.append(line)
        else:
            out[-1] += "\n" + line
    return [e for e in out if e.strip()]


def newest(text, cap):
    """Newest whole entries that fit in cap bytes, oldest of them first. Returns (kept_text, left_out_count)."""
    items = entries(text)
    kept, used = [], 0
    for item in reversed(items):
        size = len(item.encode()) + 1
        if used + size > cap:
            break
        kept.append(item)
        used += size
    if not kept and items:  # the newest entry alone is larger than the cap: keep its start, mark the cut
        cut = items[-1].encode()[:cap].decode("utf-8", "ignore")
        kept = [cut + " [entry cut at the size cap]"]
    kept.reverse()
    return "\n".join(kept), len(items) - len(kept)


def build_context():
    """The text a session would receive, or None when there is nothing to inject."""
    parts = []
    rules = rules_path()
    if os.path.isfile(rules):
        body, left_out = newest(_read(rules), _cap("INTENTPIN_RULES_CAP", 3000))
        if body:
            head = HEADER.format(path=rules)
            if left_out:
                head += (f"{left_out} older entries are left out to save space. "
                         f"Before acting on an older topic, read the full log: {rules}\n")
            parts.append(head + body)
    intent = intent_path()
    if os.path.isfile(intent):
        page = _read(intent).encode()[:_cap("INTENTPIN_INTENT_CAP", 6000)].decode("utf-8", "ignore").strip()
        if page:
            parts.append("INTENT PAGE (what the principal wants):\n" + page)
    return "\n\n".join(parts) or None


def changed(session_id, text, reset=False):
    """True if text differs from the last one emitted to this session; records it. Fails open."""
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        path = os.path.join(_state_dir(), "sessions.json")
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        now = time.time()
        state = {k: v for k, v in state.items() if now - v.get("t", 0) < PRUNE_SECONDS}
        digest = hashlib.sha256(text.encode()).hexdigest()
        is_new = reset or state.get(session_id, {}).get("h") != digest
        state[session_id] = {"h": digest, "t": now}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
        return is_new
    except Exception:
        return True


def run_hook(stdin):
    if os.environ.get("INTENTPIN_OFF"):
        return 0
    try:
        data = json.load(stdin)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    text = build_context()
    if not text:
        return 0
    sid = str(data.get("session_id") or "")
    # After a compaction or a clear the conversation lost the text, so it is sent again.
    if sid and not changed(sid, text, reset=data.get("source") in ("compact", "clear")):
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    return 0


def add(words, now=None):
    words = words.strip("\n")
    if not words.strip():
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    body = words.replace("\n", "\n  ")  # keeps multi-line words inside one entry
    path = rules_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"- {stamp}: {body}\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="intentpin", description="Pin the principal's own words into every session.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="append a dated, verbatim entry to the rules log")
    p_add.add_argument("words", help="the exact words, in quotes")
    sub.add_parser("show", help="print what a new session would receive")
    sub.add_parser("hook", help="SessionStart hook: hook JSON on stdin")
    args = parser.parse_args(argv)
    if args.cmd == "add":
        path = add(args.words)
        if path is None:
            print("intentpin: nothing to add", file=sys.stderr)
            return 2
        print(f"added to {path}")
        return 0
    if args.cmd == "show":
        text = build_context()
        if text is None:
            print("intentpin: nothing to inject (no rules log or intent page)", file=sys.stderr)
            return 1
        print(text)
        return 0
    try:
        return run_hook(sys.stdin)
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
