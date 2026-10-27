# Features

- **Mentions + search suggestions** shown as cards in the feed (author, time, full text, metrics, link).
- **Reply drafting** in an editor, with an optional Grok-written first draft (`g` on a card).
- **Auto-reply queue:** with Grok on, mentions get drafted replies, listed first, with their **own cap of 4** pending
  drafts (`/maxmentions n`, 0 = unlimited), separate from the 4-suggestion limit (panel title `N/4 mentions · x/4`,
  status `pending=x/4 | mentions=N/4`). Extra mentions still show in the feed, numbered, and wait undrafted
  (`N shown · M waiting`). **Catalog:** the waiting pool is everything in the main feed that has no draft yet (not
  replied, rejected or hidden); the panel shows/drafts at most 4 per section and, as you approve, reject or clear
  drafts, the next catalog items are drafted right away (no new fetch). `F5` (**Refresh feed + catalog**, = `/tick`)
  fetches new mentions and search posts into the feed/catalog. Without an xAI key (X-only) F5 only grows the catalog;
  once Grok is on (`/grok on`, or the next F5) the queue fills from it. In the queue, `x` clears all suggested drafts and
  `X` all mention drafts (y/n confirm; posts stay in the feed and cleared ones aren't redrafted). Open a mention's card and
  press `q` to filter that person: their future mentions are hidden and their pending drafts are dropped.
- **Manual approval for everything.** Nothing posts without you.
- **Two ways to send replies:**
  - Replies to **mentions** are sent through the API (`Ctrl+S`, or `a` to approve in the queue).
  - Replies to **search posts** (people who didn't mention you) are posted **by you in the browser**, because X
    restricts automated replies to people who didn't mention you. `Ctrl+B` in the editor (`o` on the card after saving), or `a` on the draft in the
    queue, opens X's reply page with your text filled in; xbot reminds you to add your own flavor, then you press Post.
- **Links are short labels:** `[post]`, `[profile]` and `[media]` (photos/videos) in the feed and on cards are
  clickable (`[post]`/`[profile]` open your browser, `[media]` opens the in-terminal mpv viewer); raw URLs aren't shown. `v` on a card shows all its media in mpv (`A`/`D` browse).
- **Filters:** broad topics (adult and spam are on by default; also war, politics, crime, disaster,
  celebrity, sports, crypto-shill), plus **x-flags** (posts X marks `possibly_sensitive` or `withheld`), excluded
  content tags, and custom words/phrases. Every topic's word list is editable — including adult, spam and x-flags.
  Filtered words are added to the search query as `-word` so you don't pay to read those posts.
  - `/filter edit` opens the topic picker; `e` opens a topic's word editor (`space` toggles a word, `tab` jumps to the
    add-word box, `ctrl+s` saves). `r` applies your changes and refreshes — if fewer than 20 suggestions are left it
    searches for more.
  - Or type it: `/filter edit war +drone -russia`, and `/filter reset war` to undo your edits.
  - `/filter show <word>` un-hides one word even if it's part of a broad topic (it's removed from whichever topic caught it).
  - `/hidden` lists what got filtered; `u` on a post stops filtering the word that caught it.
  - `/filter hide @someone` / `/filter show @someone` filter or un-filter a mentioner; `/filter mentioners` opens a
    pop-up editor for the list (`space` toggle, `tab` add @handle, `enter` save).
- **Authors:** block (`b`: opens their X profile so you press Block, and hides them in xbot) or really mute on X (`m`).
- **Manual checks only:** one check at startup, then `/tick` when you want more (keeps API costs down).
- Optional daily spend cap (`/cap`).
