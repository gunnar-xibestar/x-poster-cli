# Troubleshooting

| Symptom | Fix |
|---|---|
| `xbot: command not found` | add `~/.local/bin` to `PATH` (the installer prints the line to use) |
| xAI **429** `Too many requests for API key` | the key's requests-per-minute limit is below xbot's pacing (`llm_rpm`, default 5: 4/min auto + 1 kept for `g`). xbot shows one warning, waits (Retry-After, default 60 s) and retries by itself. Recommended: key limit **5/min or lower** with `xbot config llm_rpm <same number>` (see CONFIGURATION.md) |
| Pre-drafts appear slowly / F5 adds none | Grok pre-drafting is paced to `llm_rpm - 1` per minute (default 4); F5 says how many posts wait and when the next draft comes. Grok SKIPs use requests too |
| xAI **401** | wrong or expired `XAI_API_KEY`; the key is in `OPENAI_API_KEY` instead of `XAI_API_KEY`; or `XBOT_BASE_URL` points at a proxy you aren't running. Fix it, then restart xbot |
| xAI errors about credits / status PAUSED | add credits at console.x.ai, then `/resume` (or `p`) |
| X **401** | wrong X keys/tokens, or tokens generated before you set Read+Write. Generate new ones |
| X **403** replying to a search post | X blocks unsolicited API replies. Use `Ctrl+B` (editor), `o` (card) or `a` (queue) to post from the browser |
| X **402** | out of X API credits |
| `/open` does nothing | no browser opener found. xbot prints the URL; copy it |
| "env is readable by others" | `chmod 600 ~/.config/xbot/env` |
| `ensurepip`/venv error on install | `sudo apt install python3-venv`, then run `./install.sh` again |

| `xbot: config error in …config.json` | the file was hand-edited into invalid JSON or a bad value; xbot starts with defaults. Fix with `xbot config edit` or `xbot config reset` |
