# intentpin

Start every Claude Code session, and restart it after every compaction, with the principal's own words.

## The problem

Over a long session an agent drifts from what the person actually asked. Compaction replaces the conversation with a
summary, and the summary paraphrases: exact limits, vetoes and priorities soften or vanish. A rules file that is
re-read in full costs too much context, and one that is cut blindly loses the newest and most important lines.

## The fix

A `SessionStart` hook injects three things, in a fixed small budget:

1. A one-line header saying the words below are the principal's own and that newer entries override older ones.
2. The newest entries of a verbatim rules log (`rules.log`), whole entries only, at most 3000 bytes by default. If older
   entries were left out, a pointer to the full log is added so the agent can read it when a topic needs it.
3. A short intent page (`intent.md`, at most 6000 bytes): a one-page summary of what the person wants.

The same text is not injected twice into one session. After a compaction (or a clear) it is injected again, because the
conversation no longer holds it. Python 3.9+, standard library only.

## Install

    pip install .          # gives the `intentpin` command; or run python3 intentpin.py directly

## Configure

| Variable | Default | Meaning |
| --- | --- | --- |
| `INTENTPIN_DIR` | `~/.config/intentpin` | folder holding `intent.md` and `rules.log` |
| `RULES_FILE`, `INTENT_FILE` | inside `INTENTPIN_DIR` | explicit file paths |
| `INTENTPIN_RULES_CAP` | `3000` | byte cap for the rules tail |
| `INTENTPIN_INTENT_CAP` | `6000` | byte cap for the intent page |
| `INTENTPIN_STATE_DIR` | `~/.cache/intentpin` | per-session deduplication state (pruned after 7 days) |
| `INTENTPIN_OFF` | unset | set to `1` to switch the hook off |

Add this to `~/.claude/settings.json` (use the full path to `intentpin.py` if you did not install it):

    {
      "hooks": {
        "SessionStart": [
          {
            "matcher": "startup|compact",
            "hooks": [{"type": "command", "command": "intentpin hook"}]
          }
        ]
      }
    }

## Commands

- `intentpin add "<verbatim words>"` appends a line such as `- 2026-10-26 14:05 UTC: <words>` to the rules log.
  Multi-line words stay inside one entry. Quote the person exactly; do not summarize.
- `intentpin show` prints exactly what a new session would receive (no dedupe state is touched). It exits 1 when there
  is nothing to inject.
- `intentpin hook` is the hook entry point: hook JSON on stdin, hook output JSON on stdout.

## Example

    intentpin add "Never skip a failing test, and say which command you ran."
    intentpin show

prints the header, the entry above with its date, and the intent page if one exists.

## Limits

- It pins words; it does not make the agent obey them. It raises the odds by putting the words first in context.
- "Newest wins" is stated to the model and ordered by file position. It is not enforced and contradictions are not detected.
- The cap drops older entries from the injection (the full log stays on disk). Keep durable facts in `intent.md`.
- One global log by default. Per-project logs need a different `INTENTPIN_DIR` or `RULES_FILE` per launch.
- Deduplication is keyed on the session id and a hash of the text, so a resumed session with unchanged text gets nothing new.
- Resume and clear are not in the suggested matcher; add them (`startup|resume|clear|compact`) if you want them.
- Entries are plain text from whoever can write the log. Treat the log's directory as trusted input.
- The hook fails open: on any internal error it prints nothing and the session starts normally.

## License

Apache-2.0, see `LICENSE` and `NOTICE`. Related: leanagents (cheaper subagents), fleetwarden (more hooks).
