# Keys

| Key | Where | Action |
|---|---|---|
| `a` / `r` / `e` | draft list | approve / reject / edit selected draft (drafts are numbered 1..4 per section). `r` is instant and hides the source post (listed in `/hidden`; for mentions only that post, no mute/block). `a` on a **non-mention** reply opens X's reply page in your browser prefilled with the current (edited) text (X blocks API replies to posts that didn't mention you); `a` on a **mention** reply sends it through the API (dry/live per `send=`). The queue tip line stays short: `o open · a approve · e edit · r reject · m mentioners · x clear suggested · X clear mentions` |
| `o` / `Enter` | draft list | open the highlighted draft's post (its card). A mouse click on a draft only focuses the list and highlights it, it never opens it |
| `m` | draft list | **mentioners list**: see/edit everyone whose mentions you filtered (same as `/mentioners`) |
| `p` | main | pause / resume |
| `f` | main | browse found posts (arrows + Enter opens a card) |
| click `#n` | feed | open that post's card |
| `←/→` `a/d` `j/k` | card | previous / next post (also in the search / `f` card) |
| `g` | card | open the reply editor (Grok prefill if on) |
| `r` | card | open the reply editor blank (no Grok prefill), cursor in the text box |
| `o` | card | open in your browser: X's reply page prefilled with your queued draft if there is one (e.g. after `g` → `Ctrl+E`), otherwise the post |
| `v` | card | all of the post's photos, videos and GIFs in this terminal with mpv, as one playlist (Textual is suspended; muted unless `video_audio on`; sixel output when detected, else tct; photos stay up until you move on). `←`/`→` previous/next item (always shown; at the very ends they do nothing and the line says `no more media` / `first item`), `z` large (photos only: toggles between the normal fit and the largest fit using every column and every row but the controls line, never cropped; shown as `large`, back to normal on `←`/`→`; hidden and a no-op when the normal fit is already the largest), `l` like (same API like, once per post), `r` remove (mute the author on X like `m`, respects send=dry, and hide the post for good; the viewer moves to the next post with media at once and the mute finishes in the background, result on the controls line), `t` tags (pauses the viewer and opens the same filter popup as the card's `t` (space toggle, Enter apply, Esc cancel); Enter applies the checked filters, hides the post and reopens the viewer at the next post with media, Esc reopens it at the same item), `q`/`Esc` back to the same post. `←`/`→` keep going past the post's last/first item into the next/previous post with media in the same list (feed order, or the search results for `--play`); posts without media are skipped. The controls line shows `post 3/12 · @handle · 2/4 · photo …`, `l` likes the post on screen (once per post), and `q`/`Esc` returns with the card moved to the post you viewed last. Videos also: `a`/`d` seek 5 s (on photos `a`/`d` do nothing), `↑/↓` volume, `space` pause, `m` mute. The controls line sits in two rows reserved below the picture (never drawn over it) with an item counter like `2/4`; on photos it shows only `←/→`, `z`, `l`, `r`, `t` and `q/Esc`. Never opens a browser or external player; without mpv you get a notice |
| `l` | card | like via the X API (`POST /2/users/:id/likes`), once per post (liked ids in `state.json`, rolled back if X refuses); never the browser. Also works inside the `v` media viewer. Every press plays the heart animation. Uses the `xbot login` OAuth 2.0 token (`like.write`) if present, else the OAuth 1.0a token (app must be Read and write). Likes are live even with send=dry |
| `PgUp`/`PgDn` | card | scroll long post text |
| `t` | card | filter posts like this: checklist of its tags, broad topics, words and author; `Enter` applies the checked filters and hides it, `Esc` cancels |
| `q` | mention card | filter this mentioner (hides their mentions, drops their pending drafts) |
| `h` | card | hide this post for good, immediately (toast shows `#N hidden for good`); use `t` for filters |
| `b` | card | block (verify): confirm `y` opens their x.com profile so you press **Block** on X (the API can't block), and hides them in xbot right away |
| `m` | card | mute author (real, on X), confirm `y` |
| `Ctrl+S` | reply editor | send through the API (mention replies) |
| `Ctrl+B` | reply editor | open X's reply page with your current text filled in (search-post replies). Not `Ctrl+O`: Windows Terminal grabs it for File Explorer |
| `Ctrl+E` / `Ctrl+G` / `Esc` | reply editor | save to queue / regenerate / cancel |
| `F5` | anywhere | Refresh feed + catalog (= `/tick`): fetch new mentions + search posts into the feed; with Grok on, free queue slots (4 mention + 4 suggested, `/maxmentions`, `/maxpending`) are drafted from it |
| `x` / `X` | queue | clear all pending suggested / mention drafts (y/n; posts stay in the feed) |
| `F3` | main | hide / show the lower console (output, errors, `/help`, command input); the feed grows into the space. Also clickable in the footer |
| `/` | main | show the console (if hidden) and start typing a command |
| `Esc` | any popup | back (hint shown at each popup's top-left) |
| `F2` | anywhere | open the `/filter` view |
| `F6` | main | switch focus between input and draft list |
| `Tab` | input | complete command names, `/filter` subcommands and topics |
| `↑` / `↓` | input | command history (kept in `history.txt` in the state dir; secret-looking lines are not saved) |
| `Ctrl+C` / `Ctrl+Q` | anywhere | save and quit |

## Editing your API keys

Run `xbot secrets` from the shell (not inside the TUI): it opens `~/.config/xbot/env` in nano, keeps it 0600 and afterwards lists which key names are set, never their values. See COMMANDS.md.
