# Commands (most used)

| Command | What it does |
|---|---|
| `/help [cmd]` | full grouped help, or details for one command |
| `/tick` | fetch new mentions + one search (10 posts) |
| `/clear` | clear the top-left feed pane and pause Grok auto-drafting + prefill until F5 (title shows `drafting paused`; manual `g` still works; queues and state unchanged) |
| `/clear mentions\|suggested` | reject all pending mention / suggested drafts (posts stay in the feed) |
| `/maxmentions n` | cap on pending mention-reply drafts (default 10, 0 = unlimited); extra mentions wait undrafted |
| `/maxpending n` | cap on pending suggested-reply drafts (default 10; mentions not counted) |
| `/share` | open X's compose page in your browser with a prefilled post sharing xbot; you review and post it (nothing goes through the API) |
| `/found [n\|mentions\|search]`, `/show n`, `/open [n]` | list / show card / open in browser |
| `/search <query>` | set the X search query (v2 syntax) |
| `/backfill on\|off` | when a search finds few new posts, fetch older ones too (last 7 days; default on) |
| `/filter` | show what's filtered; `/filter hide war`, `/filter show politics`, `/filter show <word>`, `/filter why 12`, `/filter on\|off` |
| `/filter edit <topic> +word -word`, `/filter reset <topic>` | add/remove words in a topic, or undo your edits |
| `/filter hide @someone`, `/filter show @someone` | filter / un-filter a mentioner |
| `/filter mentioners` (or `/mentioners`) | pop-up editor for filtered mentioners: `space` toggle, `tab` add @handle, `enter` save |
| `/filter edit` | topic picker: `space` toggle, `e` edit words, `r` apply + refresh, `enter` save, `esc` cancel |
| `/hidden`, `/hidden all` | pop-up of hidden posts with reasons: `a` last check/all, `Enter` open, `u` restore a post you hid / stop filtering that word |
| `/topics`, `/exclude <tag>`, `/include <tag>`, `/excluded` | content-tag hiding |
| `/block`, `/unblock`, `/mute`, `/unmute` `@handle`; `/blocked`, `/muted` | author control |
| `/approve n`, `/reject n`, `/edit n <text>` | manage the draft queue |
| `/post <text>`, `/reply #n <text>` | queue an original post / reply |
| `/grok on\|off`, `/model <name>`, `/align <persona>` | Grok drafting settings (see [Grok drafting](GROK_DRAFTING.md)) (`/grok on` reloads the env file) |
| `/reads live\|off\|auto`, `/cap <usd>` | cost controls |
| `/limit [<usd>]` | per-session API spend limit (X + Grok) (always on, default $5; every start at $0): `/limit 5`, `/limit $5`; alone shows limit, spend, left and the rolling last-5-days X + Grok total (not part of the limit). At the limit xbot saves and exits; any exit resets session spend to $0 and prints a session summary |
| `/pause`, `/resume`, `/status`, `/stop` | bot control |

- `/style` shows how many style examples are stored; `/style clear` deletes them (`~/.local/state/xbot/style_examples.jsonl`). `xbot config style_examples 0` stops using them.


## Shell: `xbot search "query" [--play N]`

Lists recent search results (posts with media marked `[media k: n items]`); `--play N` shows all photos, videos and GIFs of the Nth one in the terminal mpv viewer (`A`/`D` browse, continuing into the other results with media; `q`/`Esc` quit). Without mpv it prints a notice and exits 1; it never opens a browser.


## Shell: `xbot login`

OAuth 2.0 Authorization Code + PKCE (scopes `tweet.read users.read like.write offline.access`). Needs `X_CLIENT_ID` in `~/.config/xbot/env` and the app callback `http://127.0.0.1:8765/callback`; opens the browser, listens on 127.0.0.1:8765, saves `~/.config/xbot/tokens.json` (0600, auto-refreshed, redacted). Without `X_CLIENT_ID` it prints the setup steps.

## Shell: `xbot secrets`

Opens `~/.config/xbot/env` in nano (`nano -I -R`: ignores nanorc, restricted mode, no backup or lock files);
`$EDITOR` only if nano is missing; if neither exists it prints the path. Creates the folder (0700) and file (0600,
umask 077) if missing, with a commented template of the supported names (`XAI_API_KEY`, `XAI_MANAGEMENT_KEY`,
`XAI_TEAM_ID`, `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`, `X_BEARER_TOKEN`, `X_CLIENT_ID`,
`X_CLIENT_SECRET`) and placeholders only. The editor runs with a minimal environment. Afterwards xbot re-applies 0600
and prints which names are set (never values) and the line numbers that don't parse. Shell only (no `/secrets` in the
TUI); restart xbot to load the changes.

## Draft queue numbering

Each queue section (Mentions, Suggested replies) numbers its drafts 1, 2, 3, 4 from the top; numbers shift as drafts
are approved/rejected. `/approve 2`, `/reject 2`, `/edit 2 text` act on Suggested replies #2; prefix `m` for Mentions
(`/approve m1`). Keys `a`/`r`/`e` act on the selected draft. Rejecting is instant and hides the source post (listed in
`/hidden`; mentions: only that post, the author isn't muted or blocked).
