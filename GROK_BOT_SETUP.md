# Setup guide for AI assistants (e.g. a user's Grok Bot)

You're helping a user install **x-poster-cli** (launcher command `xbot`) on Linux. Follow these steps in order and follow the safety rules.
## Safety rules (always)
1. **Never ask for, print, echo, log, or repeat API keys or tokens.** Don't `cat` the env file. To check it, only
   report whether each key name has a value:
   `awk -F= '/^[A-Z_]+=/{print $1, ($2==""?"EMPTY":"set")}' ~/.config/xbot/env`
2. If the user pastes a key in chat, tell them to revoke/regenerate it, and don't use the pasted value.
3. **Dry-run first.** Don't run `/send live` or `/dryrun off` unless the user asks for it.
4. Every post/reply must be approved by the user by hand. Never approve drafts for them, and never write scripts that auto-approve.
5. Never use sudo without the user's consent. If something needs sudo, show them the command to run.
6. **Never commit or push the env file** (`~/.config/xbot/env`, `.env`) or any key. Check `git status` before every commit.

## Steps
1. Check prerequisites: `python3 --version` (needs 3.10+), `git --version`.
2. Clone: `git clone https://github.com/gunnar-xibestar/x-poster-cli.git && cd x-poster-cli`
   (private repo: the user needs access, and you'll need `gh auth login` or an SSH key).
3. Install: `./install.sh`. If it reports that venv is missing, tell the user to run `sudo apt install python3-venv` and then run it again.
4. Keys: tell the user to open `~/.config/xbot/env` **in their own editor** (`nano ~/.config/xbot/env`) and fill in:
   - `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` (from developer.x.com, app permissions Read and Write, OAuth 1.0a)
   - optional `XAI_API_KEY` (console.x.ai, needs credits). Keep `XBOT_BASE_URL=https://api.x.ai/v1` unless they run a local proxy.
   If the file doesn't exist yet: `mkdir -p ~/.config/xbot && cp .env.example ~/.config/xbot/env` (inside the clone).
   Then: `chmod 600 ~/.config/xbot/env`. Check it with the awk command above.
   The xAI fields may stay empty: xbot then runs X-only (search, mentions, feed, cards, opening posts, manual replies; no Grok drafts).
5. PATH: if `command -v xbot` finds nothing, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`.
6. Verify:
   - Tests: `.venv/bin/python -m pytest -q` (all should pass; no network or keys needed).
   - Run `xbot`. The status line should show `send=dry`. `/status` and `/help` should work. Without X keys it runs on fake data.
   - Quit with `Ctrl+Q`.

## Customizing the code
If the user wants to change xbot, suggest they work in **their own private fork** rather than the original repo:
- With GitHub CLI: `gh repo fork gunnar-xibestar/x-poster-cli --clone`, then make it private with
  `gh repo edit <user>/x-poster-cli --visibility private --accept-visibility-change-consequences`
  (if GitHub doesn't allow a private fork, create a new private repo instead, e.g.
  `gh repo create <user>/x-poster-cli --private --source . --remote origin --push` after renaming the old remote to `upstream`).
- Pull updates later with `git pull upstream main`.
- Run `.venv/bin/python -m pytest -q` after changes, and never commit `.env` / `~/.config/xbot/env` or any key.

## Common errors
- `xbot: command not found`: PATH (step 5).
- xAI 401: wrong key, the key was put in `OPENAI_API_KEY` instead of `XAI_API_KEY`, or the base URL points at a proxy that isn't running. Fix it and run `/grok on`.
- No xAI credits: add credits, then `/resume`.
- X 401: generate new access tokens after setting Read and Write.
- X 403 on search-post replies: expected. Use `Ctrl+B` in the editor, `o` on the card, or `a` in the queue (browser reply) instead of `Ctrl+S`.
- X 402: out of X API credits.

## Uninstall
Ask before each destructive step and run them from inside the clone.
1. Remove the launcher and virtualenv (keeps keys and state):
   `./install.sh --uninstall`
2. Keys and history: `~/.config/xbot` holds the env file with the user's keys, and `~/.local/state/xbot` holds
   the queue, found posts, logs and command history. Delete them **only if the user says so**:
   `./install.sh --uninstall --purge` (same as step 1 plus deleting both folders).
   Suggest they revoke the X and xAI keys in the consoles if they won't use them again.
3. Delete the cloned folder (e.g. `cd .. && rm -rf x-poster-cli`) only after the user confirms they have no
   uncommitted changes they want to keep (`git status`).

### Separating from a fork
If the user forked the repo, explain the options and do nothing destructive unasked:
- **Keep the fork** as it is; uninstalling locally doesn't touch it.
- **Detach from upstream locally:** `git remote remove upstream` (it stops pulling updates; the fork stays on GitHub).
- **Detach on GitHub:** a fork's link to the original can be removed by contacting GitHub Support, or by creating a
  fresh private repo and pushing to it (`gh repo create <user>/<name> --private --source . --remote origin --push`
  after renaming the old remote).
- **Delete the fork** only if the user explicitly confirms: `gh repo delete <user>/x-poster-cli` (it asks for
  confirmation; never pass `--yes` for them). This can't be undone.
