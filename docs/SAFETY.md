# Safety

- Every post and reply needs your approval; nothing is sent on its own.
- Reads are `auto`: live only when all four X keys are set. Live reads and sends cost X credits; set `/cap`.
- Mentions are never hidden by topic/word filters. Mentions from people you filter are hidden (and their pending
  drafts dropped). Manage that list with `q` on a mention's card, `/filter hide|show @someone`, or the
  pop-up editor `/filter mentioners`.
- Secret values are removed from logs. Keep `~/.config/xbot/env` at `chmod 600`.
- Follow X's automation rules. Don't spam replies.

## Secrets hardening

- xbot runs with `umask 077`; `~/.config/xbot` and `~/.local/state/xbot` are kept at 0700 and their files at 0600 (fixed automatically at startup; or run `xbot fix-perms`). Files are written atomically (0600 temp file + rename).
- xbot refuses to start if `~/.config/xbot/env` is group/world-readable, owned by someone else, a symlink, or on a Windows drive (`/mnt/...`). The message shows the exact fix (e.g. `chmod 600 ~/.config/xbot/env`); `--insecure-perms` overrides.
- Optional `XBOT_SECRET_CMD="pass show xbot"`: KEY=VALUE lines from the command's stdout are loaded (the env file stays the default; real env vars win).
- Every loaded secret is redacted (raw, base64, percent-encoded, Bearer/Basic) from actions.jsonl, crash.log, logging and tracebacks. HTTP header debug logging is silenced. mpv and browser openers get a minimal environment with no secret variables.
- Repo: `.gitignore` covers env/state/logs, `.env.example` is a placeholder, `.pre-commit-config.yaml` runs gitleaks, and `python3 scripts/check_tarball.py xbot.tar.gz` fails a deploy tarball containing env, *.jsonl or state files.
