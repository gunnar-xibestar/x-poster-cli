# xbot — Grok-powered X bot console (TUI)

Long-running terminal console: a Grok bot polls your X mentions, drafts replies and occasional
original posts, and puts **every draft in an approval queue**. Nothing is sent until you approve.
Reads and sends are separate:
- **reads** (mentions + search): `auto` by default = live when all four X keys are present, else fake. `/reads live|off|auto`.
- **send**: **dry by default** (approved posts are only logged). `/send live|dry` (`/dryrun on|off` is an alias).
Status shows `reads=… | send=…`. The X spend estimate counts live reads and live sends.

## Setup
```bash
cd xbot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p ~/.config/xbot && touch ~/.config/xbot/env && chmod 600 ~/.config/xbot/env
```
`~/.config/xbot/env` (KEY=VALUE; real env vars override):
```
XAI_API_KEY=...            # required for drafting
# only needed when /dryrun off (OAuth 1.0a user context, app needs Read+Write):
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
```
Optional env: `XBOT_BASE_URL` (default `http://127.0.0.1:8767/v1`, your usage proxy → api.x.ai;
use `https://api.x.ai/v1` to go direct), `XBOT_MODEL` (default `grok-4.7`).

## Run
```bash
.venv/bin/python -m xbot
```
Panes: action feed (left), pending drafts (right), status line, command input.
Keys (when the draft list is focused; F6 to switch focus; in the input, Tab completes commands / `/filter` subcommands / topic names and Up/Down browse command history persisted to `$XBOT_STATE_DIR/history.txt`, max 500 lines, secret-looking lines skipped): `a` approve+send, `r` reject,
`e` edit (loads text into input, Enter saves), `p` pause/resume, `f` found-post browser, `h` search history (past `/search` / `xbot search` queries, newest first, deduped, last 100, stored 0600 in `~/.local/state/xbot/search_history.json`; Enter or click fills the input with `/search <query>`, Esc closes; in a post card `h` still hides), `Ctrl+C` or `Ctrl+Q` quit (also SIGINT/SIGTERM): stops auto-search, saves queue/state, logs "stopped". Search runs automatically only while the app is open.

## Demo mode
```bash
xbot sample
```
Opens the real interactive TUI with fake sample posts, mentions and drafts: temp state, no network or API calls,
nothing sent or opened, your config/state untouched. Take your own screenshots. (Devs: `scripts/screenshots.py
[--out DIR]` regenerates the README screenshots; PNGs need `cairosvg`.)

## X-only mode (no xAI key yet)
If `XAI_API_KEY` is missing the bot keeps running in **X-only mode** (status: `grok=off (X-only)`):
mention polling and tech search continue, and every new post is shown in the feed as
`#n [search] …123456 @author: snippet  [post]` (clickable labels `[post]`, `[media]` (opens the mpv viewer); on cards also `[profile]`; raw URLs are not shown) instead of being drafted.
- `/found` lists the most recent 15; `/found N` shows full text + link.
- `/reply #N <text>` (or `/reply <tweet_id> <text>`) and `/post <text>` queue drafts for approval as usual.
- Add the key to `~/.config/xbot/env` (or the environment) and run `/grok on` — no restart needed. `/grok off` goes back to X-only.

Missing X credentials with `/dryrun off` are reported once in the feed (no crash); sends are marked failed.

## found.json (for hand replies)
Every found post is written atomically to `~/.local/state/xbot/found.json` whenever the list changes
(`/export` forces a write). Format: `{"updated": ..., "posts": [{"n", "id", "author", "text", "created_at",
"url", "source", "replied"}]}`. Only public post fields; no keys or tokens. `replied` flips to true when a reply
to that post is approved and sent. The list is reloaded on restart (last 200).

## Content tags (hide subtopics)
Every found post is tagged locally (no Grok needed) by keyword/hashtag match against a taxonomy:
ai, linux, python, rust, web, devops, security, opensource, hardware, crypto, business, jobs, gaming, mobile, news
(breaking, JUST IN, developing, "report:", "according to", headlines, 🚨, X News/Events topics), data. (The old
**untagged** pseudo-tag was removed: it mass-hid posts; it is dropped from existing configs.) Found posts are retagged with the current
taxonomy on startup.
X `context_annotations` (requested in the same search/mentions call) add hints when present. Tags appear on feed
lines (`#rust`), in post cards, and in found.json (`tags`).
- `/topics` opens a checkbox picker (tags with counts; **checked = hidden**; Space toggles, Enter saves, Esc cancels).
- `/exclude crypto jobs`, `/include crypto`, `/excluded` (shows tags, counts and the effective query).
- Excluded tags hide matching **search** posts from suggestions, `/found`, the `f` browser and replay
  (mentions are never hidden, except from filtered mentioners), and their keywords are appended as `-keyword` terms to the search query while
  staying within `search_query_limit` (512, X self-serve recent search) so reads aren't spent on them.
- Saved in config.json as `excluded_tags`; override the taxonomy with `"taxonomy": {"tag": ["kw", ...]}`.
- Grok post topics moved from `/topics` to `/posttopics`.

## Broad topics, word edits and mentioners
- Broad topics: adult, spam (on by default), war, politics, crime, disaster, celebrity, sports, crypto-shill, and
  **x-flags** (X's own `possibly_sensitive` / `withheld` flags). All word lists are editable.
- `/filter mentioners` (or `/mentioners`): pop-up list of filtered mentioners (checked = their mentions hidden); `space` toggle, `tab` to the box to add `@handle`, `enter`/`ctrl+s` save (unchecked are removed), `esc` cancel.
- `/filter edit` picker: `space` toggle, `e` edit words (word editor: `space` toggles, `tab` to the add-word box,
  `ctrl+s` save), `r` apply + refresh (searches again when fewer than 20 suggestions remain), `enter` save, `esc` cancel.
- Typed: `/filter edit <topic> +word -word`, `/filter reset <topic>`. `/filter show <word>` removes a sub-word from
  whichever broad topic caught it.
- `/hidden` pop-up: `a` toggles last check / all, `Enter` opens, `u` stops filtering that word.
- Auto-reply queue: mention replies are always drafted, listed first and not counted toward the 10-suggestion limit
  (title `N mentions · x/10`, status `pending=x/10 +N mentions`). `q` on a mention's post card filters that mentioner
  (future mentions hidden, pending drafts dropped); `/filter hide|show @someone`; saved as `filtered_mentioners`.

## Block (local)
`/block @handle`, `/unblock @handle`, `/blocked`, or `b` in a post card (`Block @x? y/n`). `/block` is **local** (xbot only, nothing sent to X). The card key `b` also opens `https://x.com/<handle>` in your browser so you can press Block on X yourself (the X API has no block-write endpoint for xbot). Blocked authors' search
posts are hidden from suggestions, `/found`, the `f` browser and replay; mentions stay visible but dimmed.
`-from:handle` is added to the search query (before tag terms, within the length limit). Saved in config.json as
`blocked_authors`; also listed in the `/topics` picker (uncheck to unblock).

## Mute (real)
Mute is **real**: it mutes on your X account. `m` in a post card (`Mute @x (real)? y/n`) or `/mute @handle`; `/unmute @handle`; `/muted`
(local record). Uses `POST /2/users/:id/muting` / `DELETE /2/users/:id/muting/:target` (docs.x.com; OAuth 1.0a user
context or OAuth 2.0 user token; the app needs Read+Write). Pricing page lists "User Interaction: Create" $0.015 and
"Interaction: Delete" $0.010 per request (assumed to cover mute/unmute); if the author id isn't known from a found
post, a `GET /2/users/by/username` user read (~$0.010) is used. Muting always also blocks locally.
With `send=dry` it only logs `[DRY-MUTE]` and blocks locally. 403/402/401 errors are reported plainly and the author
stays blocked locally. Your own user id is cached in state.json (`me_id`).

## Drafts panel
The right panel is titled **Auto replies (Grok drafts) n/10**; its footer shows `o open · a approve · e edit · r reject …`. Clicking a draft only highlights it; `o` (or Enter) opens its post. The highlighted card expands just enough to show the full original post and the full drafted reply (other cards stay compact, reply clipped). `e` on it swaps the reply for a wrapped editor in the same spot, prefilled; Enter or Ctrl+S saves (same `/edit` path, so style learning still applies), Esc cancels; the card then shows the expanded text again.
When empty it explains why (Grok off → add XAI_API_KEY and `/grok on`; Grok on → `/tick` or `g` on a post).

## X labels
Besides our keyword tags, each found post keeps X's own labels (requested in the same search/mentions call):
**X topics** (`context_annotations` as `Domain › Entity`), **entities** (Person/Organization/Product/Place with
probability ≥ 0.5), **cashtags** and **link domains**. They show grouped in the post card, in `/topics` and the card
`t` picker, and in found.json (`xlabels`). Hide one with the pickers or `/exclude link:github.com`,
`/exclude entity:Person: Elon Musk`, `/exclude cashtag:$TSLA`, `/exclude topic:Technology › …`.
Hidden labels filter locally; links (`-url:domain`) and entities (`-"Name"`) are also added to the search query.

## Reply from the card
In a post card press `g`: a reply editor opens. With Grok on it is pre-filled by Grok in the background
(context: post text, author, tags/labels; "drafting…" shown); with Grok off it opens empty. Live 280-char count and
URL cost warning. **Ctrl+S** send (through the normal path: send=dry/live, daily cap; marks `replied` in found.json),
**Ctrl+E** save to the approval queue instead, **Ctrl+G** regenerate (Grok only), **Esc** cancel.
For search posts X may reject API replies with 403 (only summoned replies are allowed on self-serve); the feed
then suggests `/open N` to reply by hand.

## Post cards & opening in the browser
- Click a post number (`#n`) in the feed, press `f` (arrows + Enter in the found list), or `/show N` to open a
  **post card**: name/@handle, time in America/Los_Angeles, full text, replies/reposts/likes/quotes
  (from `public_metrics`, fetched in the same search/mentions call), source tag and link.
  In the card: `←/→`, `↑/↓` or `j/k` previous/next post (mentions, then suggestions; hidden posts skipped; stops at the ends; header shows `n/total`), `g` draft reply, `o` open in browser, `r` start `/reply #N `, `t` filter posts like this: checklist of its author (local block list), tags, broad topics and key words; `Enter` applies the checked ones, hides the post (in `/hidden` as "hidden by you: …", `u` restores) and refills suggestions, `Esc` back; `h` hides this post for good immediately (toast `#N hidden for good`, drafts dropped), `v` views all of the post's media (photos, videos, GIFs) in the terminal with mpv: `A`/`D` previous/next item, `l` like, `q`/`Esc` back; videos also `←/→` seek, `↑/↓` volume, `space` pause, `m` mute. The controls line and an item counter (`2/4`) sit in rows reserved below the picture; photos show only the controls that apply. Media never opens a browser or external player. `A`/`D` keep going past the post's last/first item into the next/previous post with media in the same list (feed order, or the search results for `--play`); posts without media are skipped. The controls line shows `post 3/12 · @handle · 2/4 · photo …`, `l` likes the post on screen (once per post), and `q`/`Esc` returns with the card moved to the post you viewed last. Hidden tags show struck through on the card.
- `/open N` opens the post in your browser without blocking the UI. It tries `wslview` (install with
  `sudo apt install wslu` on WSL2), `explorer.exe`, `cmd.exe /c start`, `xdg-open`, then Python `webbrowser`;
  if none works the URL is printed in the feed.

## Polling
The app does **one mention check + one search on startup** and then nothing automatic; run `/tick` to check
again (one mention check + one search). There is no automatic polling. Status shows `last check HH:MM:SS`.

Each check prints a **Mentions (N new)** block (all new mentions, following `next_token` pages, safety cap 100)
followed by a **Suggested replies (N)** block from one search of `max_results` (10). N can be below 10 when
results were already seen, are your own, or are threads you already replied to. On startup the whole found
list is replayed (mentions first, then suggestions); `/found` lists everything, `/found mentions` / `/found search` filter.

## Tech search mode
Every `search_every_n_ticks` polls (default 5, i.e. ~10 min at 120 s) the bot calls
`GET /2/tweets/search/recent` with `search_query` (default: AI/LLM/programming/Linux/open source/devops/rust/python,
`-is:retweet -is:reply -is:quote lang:en min_likes:20`) and `max_results` 10. Seen post ids and replied
threads are persisted (`state.json`); own posts are skipped. Grok gets the text + @author and may answer `SKIP`.
At most `max_replies_per_hour` (6) live replies are SENT per hour (drafts are not counted). A background worker keeps drafting (no F5 needed; the queue title shows `drafting… next in Ns`), up to `draft_batch` (4) posts per Grok request as JSON, each request going to the emptier of the mention / suggested queues (ties alternate; mentions are prefilled too, sharing the pool) (fills free slots, the rest go to a stored prefill pool up to `prefill_max`, 20; freed slots promote from the pool with no API call; title shows `prefilled N` and `drafts full` when nothing needs Grok), and drafting stops when
`max_pending` (4) suggested drafts are waiting. Mention replies have their own cap, `max_mention_drafts` (4, `/maxmentions n`, 0 = unlimited): extra mentions stay in the feed undrafted (status `+N waiting`) and the oldest waiting one is drafted on the next check after you approve/reject/filter one. `F5` (anywhere, even while typing) = `/tick` ("Refresh feed + catalog"): fetches into the feed. The **catalog** (waiting pool) is every feed post/mention without a draft that is not replied, rejected, SKIPped or hidden; status shows `waiting=N`, panel section headers `N shown · M waiting`. Approve/reject/`/clear` and `/grok on` draw from the catalog immediately (no network) up to `max_mention_drafts` + `max_pending`. X-only mode only fills the catalog. `/clear mentions|suggested` (queue keys `X` / `x`, y/n confirm) rejects all pending drafts of that kind.

### Search operator tips
`/search help` (or bare `/search`, or `/help search`) prints these without changing the query or calling X.
Verified against [X API search operators](https://docs.x.com/x-api/posts/search/integrate/operators):
- space = AND; `OR` + parentheses: `(rust OR golang OR "zig lang")`; `"quotes"` = exact phrase
- exclude with `-`: `-is:retweet -is:reply -is:quote`, `-giveaway -airdrop -crypto`
- type: `has:media has:images has:video_link has:links` (`has:videos` is not an API operator); `is:`/`has:`/`lang:` need another term in the query
- language: `lang:en` (exclude: `-lang:ja`)
- people: `from:user`, `-from:user`, `is:verified`; hashtag/mention: `#rustlang`, `@rustlang`
- engagement: `min_likes:`, `min_reposts:`, `min_replies:` (web-only `min_faves:`/`min_retweets:` are rejected with 400)
- example: `(rust OR "rust lang" OR #rustlang) has:media lang:en -is:retweet -is:reply -giveaway -crypto`
- narrower queries cost less: each returned post is billed

**Important:** since Feb 23 2026 X only allows API replies on self-serve tiers when the author *summoned*
you (mention/quote). Search-sourced replies will likely be rejected (403) when live; treat them as suggestions to
approve the draft (`a`) or press `Ctrl+B` in the editor (or `o` on the card) to open X's reply page prefilled in your browser and post it there yourself (add your own flavor first), or use search drafts as inspiration for original posts.

## Cost
Status shows an estimated X spend for today (UTC day, live mode only): reads $0.005/post (mentions $0.001
owned reads), posts $0.015, summoned replies $0.010, any URL $0.20 (drafts with URLs get a warning).
`/cap <usd>` sets a daily cap (0=off); when hit, sending and searching stop.

Commands: `/pause /resume /stop /status /help /tick` (poll now), `/align <persona text>`,
`/posttopics a, b, c`, `/model <name>`, `/post <text>`, `/reply <tweet_id> <text>`,
`/approve <n> /reject <n> /edit <n> <text>`, `/dryrun on|off`, `/search <query>`, `/searchon`, `/searchoff`, `/backfill on|off` (fill short searches with older posts via `until_id`; last 7 days only),
`/found [N|mentions|search]`, `/topics`, `/exclude <tag>`, `/include <tag>`, `/excluded`, `/block @h`, `/unblock @h`, `/blocked`, `/mute @h`, `/unmute @h`, `/muted`, `/show N`, `/open N`, `/export`, `/reads live|off|auto`, `/send live|dry`, `/grok on|off`, `/maxresults N` (10-100), `/maxpending N`, `/cap <usd>`.
`/post` and `/reply` also go into the approval queue.

## Help & colors
`/help` prints grouped sections (Bot control, Search & found, Drafts & approval, Posting, Settings & costs, Keys)
with args, a description and an example per command; `/help <command>` gives details; typos get
"did you mean". The feed is colored (found posts: source tag, @author, link; drafts yellow; sends green with
DRY-SEND/LIVE badges; warnings orange; auth/credit/403 errors red), and the status line flags LIVE in red.
Post text is escaped, so markup inside posts can't break rendering. On startup all found posts are replayed (mentions, then suggestions).

## Author names (free, via oEmbed)
Search and mentions requests do **not** request author expansions/user.fields (those would be billed as User
reads, $0.010 each). Instead the name and @handle come from X's public oEmbed endpoint
(`https://publish.x.com/oembed?url=https://twitter.com/i/status/<id>&omit_script=1&dnt=true`; returns
`author_name` and `author_url`). New posts are prefetched (3 at a time, 5 s timeout, one attempt, xbot User-Agent;
`oembed_prefetch: false` to disable); otherwise the lookup runs in the background when a card opens. Results are
cached in found.json (`username`, `name`, `author_lookup`). If oEmbed fails the author_id (or "unknown author") is
shown and it isn't retried. There is no paid fallback. The spend estimate has no user reads (only the one-time
`/users/me` id lookup when reading mentions live, ~$0.010 per session).

## Roadmap / TODO
- Card flow polish: edit our tags manually in the card; reply threads; quote-posts.

## Files
- `~/.config/xbot/config.json` — model, base_url, persona, topics, post_every_n_ticks, dry_run
- `~/.config/xbot/env` — secrets (chmod 600; warned in feed if not)
- `~/.local/state/xbot/actions.jsonl` — action log (secrets redacted)
- `~/.local/state/xbot/queue.json` — draft queue (survives restarts)
- `~/.local/state/xbot/state.json` — seen ids, replied threads, spend, hourly counter

## Errors
xAI auth / permission / out-of-credit errors **pause the bot** with a red-flag feed line — no retry loop.
Fix the key/credits and `/resume`. Transient errors (proxy down, 5xx) are logged and retried next poll.
X API errors (401/402 credits/403 tier/429) are logged per call.

## Tests
`.venv/bin/pytest -q` (FakeLLM + DryRunX; TUI tested headless with Textual pilot).
