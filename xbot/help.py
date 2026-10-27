"""Command reference: grouped help, per-command detail, did-you-mean."""
import difflib

# section -> [(name, args, description, example, detail)]
SECTIONS = {
    "Bot control": [
        ("pause", "", "Pause polling/drafting (sends still need approval)", "/pause", "Stops the poll loop from doing work; the app stays open. Key: p."),
        ("resume", "", "Resume after /pause or after an auth/credit pause", "/resume", "Also clears a pause caused by an xAI auth/credit error."),
        ("stop", "", "Save queue/state and quit (same as Ctrl+C / Ctrl+Q)", "/stop", "Persists queue.json, state.json, logs 'stopped' and exits."),
        ("tick", "", "Fetch all new mentions + 10 search suggestions", "/tick", "All new mentions (paged, up to 100) then one search of max_results (10) (unless /searchoff); drafts if Grok is on. This is the only way to check again after startup (there is no automatic polling)."),
        ("mentioners", "", "Filtered mentioners list: see and edit whose mentions are hidden (m in the queue)", "/mentioners", "Checked = that person's mentions are hidden. space toggles, Tab jumps to the box to add @handle, Enter or Ctrl+S saves (unchecked are removed), Esc cancels. Also: q on a mention's post card, /filter hide|show @someone."),
        ("status", "", "Print the full status line to the feed", "/status", "Shows run state, reads/send mode, grok, queue, spend."),
        ("grok", "on|off", "Enable/disable Grok drafting (X-only when off)", "/grok on", "on re-reads ~/.config/xbot/env, so a newly added XAI_API_KEY works without restart."),
        ("align", "<persona text>", "Replace Grok's persona/instructions", "/align dry wit, practical Linux tips, no hype", "Saved to config.json; affects all future drafts."),
        ("posttopics", "<a, b, c>", "Set topics Grok writes original posts about", "/posttopics AI, Linux, open source", "Comma separated. Saved to config.json. (Was /topics.)"),
        ("model", "<name>", "Switch the xAI model", "/model grok-4.7", "Saved to config.json; used on the next draft."),
    ],
    "Search & found": [
        ("search", "<query>", "Set the X recent-search query", '/search (rust OR golang) -is:retweet lang:en', "X v2 search syntax. Resets since_id. Costs $0.005 per returned post when reads are live."),
        ("searchon", "", "Turn auto-search on", "/searchon", "Search runs every search_every_n_ticks polls while the app is open."),
        ("searchoff", "", "Turn auto-search off", "/searchoff", "Mentions are still polled."),
        ("backfill", "on|off", "Fill short searches with older posts", "/backfill on", "When a search returns fewer than max_results new usable posts, one extra call fetches older posts (until_id = oldest seen). Same filters and read cost; header shows ' · N older'. X recent search only covers the last 7 days. Default on."),
        ("maxresults", "<10-100>", "Results per search call", "/maxresults 10", "X minimum is 10. Higher = more read cost."),
        ("found", "[n|mentions|search]", "List all found posts, a filtered group, or #n in detail", "/found mentions", "Without args: all mentions, then all suggested replies. With n: full text, time, link and reply hint."),
        ("show", "<n>", "Show found post #n as a post card", "/show 3", "Card: name/@handle, time (America/Los_Angeles), full text, likes/reposts/replies/quotes, source, link. Keys: ←/→ ↑/↓ a/d j/k previous/next post (mentions then suggestions, hidden skipped; header shows n/total), g draft reply (editor: Ctrl+S send, Ctrl+E queue, Ctrl+G regenerate, Esc cancel), Esc close, o open in browser, r reply, t pick this post's tags to hide (same exclusion as /topics)."),
        ("share", "", "Open X compose in your browser with a post sharing xbot (you review and post it)", "/share", "Nothing is posted through the API."),
        ("open", "<n>", "Open found post #n in your browser", "/open 3", "WSL: wslview, then powershell.exe Start-Process, then cmd.exe start (never explorer.exe, which opens Documents for URLs with &); Linux: xdg-open; then Python webbrowser; prints the URL if none works."),
        ("topics", "", "Pick content tags to hide (checkbox picker)", "/topics", "TUI modal listing every tag with counts of found posts. Space toggles, Enter saves, Esc cancels. Checked = hidden."),
        ("exclude", "<tag> [tag...]", "Hide search posts with these tags", "/exclude crypto jobs", "Also adds -keyword terms to the search query (within the length limit) so reads aren't spent on them. Mentions are never hidden."),
        ("include", "<tag> [tag...]", "Un-hide tags", "/include crypto", "Tags include 'news' (breaking, JUST IN, 🚨 …)."),
        ("filter", "[hide|show <topic or word>] [why <n>] [on|off]", "Hide search posts by topic or word, not whole tags", '/filter hide war', 'Topics: adult, spam (on by default), war, politics, crime, disaster, celebrity, sports, crypto-shill. Anything else is a word or "quoted phrase" (also added to the search query as -word so you are not billed to read it). /filter alone shows what is hidden; /filter why 12 tells you why post #12 is hidden; /filter off pauses all of it. Mentions are never filtered.'),
        ("hidden", "[all]", "Posts the filter hid in the last check, with reasons (all = everything)", "/hidden all", "#n = saved posts now hidden; hN = posts dropped when fetched (kept in filtered.json, last 200). Blocked authors are not listed here (see /blocked)."),
        ("block", "@handle", "Block (local): hide an author in xbot", "/block @exampleuser", "Search posts hidden; mentions stay visible but dimmed; adds -from:handle to the search query. Card key b also opens their x.com profile so you can block them on X."),
        ("unblock", "@handle", "Undo a block (local)", "/unblock @exampleuser", ""),
        ("mute", "@handle", "Mute (real) on your X account + block (local)", "/mute @spammer", "POST /2/users/:id/muting (~$0.015; +$0.010 user lookup if the author id isn't known). send=dry: logs [DRY-MUTE], blocks locally only. Card key: m (confirm y)."),
        ("unmute", "@handle", "Unmute (real) + undo block (local)", "/unmute @spammer", "DELETE /2/users/:id/muting/:target (~$0.010)."),
        ("muted", "", "List mute (real) authors", "/muted", "(dry) marks mutes that only happened locally."),
        ("blocked", "", "List block (local) authors", "/blocked", "Also shown (uncheck to unblock) in the /topics picker."),
        ("excluded", "", "List tags, counts, which are excluded, and the effective query", "/excluded", ""),
        ("export", "", "Force-write found.json", "/export", "~/.local/state/xbot/found.json; written automatically on every change."),
    ],
    "Drafts & approval": [
        ("approve", "<n>|m<n>", "Approve the draft at position n (Suggested replies) or m<n> (Mentions)", "/approve 2", "Positions are the 1..4 numbers shown in each queue section and renumber as drafts change. Key: a on the selected draft."),
        ("reject", "<n>|m<n>", "Reject the draft at that position and hide its post for good", "/reject 2", "Instant (no network). The source post is hidden like h on a card and listed in /hidden (u restores); for mentions only that post is hidden, the author is not muted or blocked. A replacement draft comes from stored prefill or the background drafter. Key: r on the selected draft."),
        ("edit", "<n>|m<n> <text>", "Replace the text of the draft at that position", "/edit 2 Shorter, better reply", "Key: e loads the draft into the input; Enter saves."),
        ("maxpending", "<n>", "Max pending suggested-reply drafts (mentions not counted)", "/maxpending 10", "0 = unlimited."),
        ("style", "[clear]", "Show / forget style examples learned from your edits", "/style clear", "Edited Grok drafts you approve or save are kept (last 50, ~/.local/state/xbot/style_examples.jsonl); the newest style_examples (8) go into the prompt as replies in your voice. xbot config style_examples 0 disables."),
        ("clear", "[mentions|suggested]", "No argument: clear the feed pane and pause auto-drafting until F5. mentions/suggested: reject all pending mention (or suggested) drafts", "/clear suggested", "Posts stay in the feed; cleared ones are not redrafted, other waiting catalog items fill the slots."),
        ("maxmentions", "<n>", "Max pending mention-reply drafts (default 10)", "/maxmentions 10", "Extra mentions stay in the feed undrafted; the next one is drafted on the next check after you approve/reject/filter one. 0 = unlimited."),
    ],
    "Posting": [
        ("post", "<text>", "Queue an original post for approval", "/post Shipping a tiny TUI today", "Goes to the draft queue; approve to send."),
        ("reply", "<id|#n> <text>", "Queue a reply to a post id or found #n", "/reply #2 Great point about cgroups", "#n refers to /found numbering."),
    ],
    "Settings & costs": [
        ("reads", "live|off|auto", "Live X reads (search/mentions) or fake", "/reads live", "auto = live when all four X keys are set. Live reads cost X credits."),
        ("send", "live|dry", "Really post approved drafts, or only log them", "/send dry", "LIVE posts cost $0.015 ($0.20 with a URL, $0.01 summoned reply)."),
        ("dryrun", "on|off", "Alias: on = /send dry, off = /send live", "/dryrun on", ""),
        ("cap", "<usd>", "Daily X spend cap (0 = off)", "/cap 1.50", "When hit, live sends and searches stop until the next UTC day."),
        ("limit", "[<usd>]", "Per-session API spend limit (X + Grok combined) (always on, default $5); alone shows limit, spend, left, last 5 days", "/limit 5", "Accepts 5, $5, 5.00; positive amounts only (it can't be turned off). Saved to config.json at once (same as xbot config spend_limit 5). Every start begins at $0. When combined X + Grok API spend this session reaches it, xbot sends no further X or xAI request, saves queue/state and exits; on any exit the session spend resets to $0 (limit unchanged, per-day totals kept) and a summary like 'xbot session: 1h 23m · API spent $0.42 of $5.00 limit (X $0.10 + Grok $0.32)' is printed. Status bar shows 'API $0.42 / $5.00 limit (X $0.10 + Grok $0.32)' and credits: real balance with XAI_MANAGEMENT_KEY, else est. credits left from xbot config credits_start."),
        ("help", "[command]", "This help, or details for one command", "/help reply", ""),
    ],
}
KEYS = [("a", "approve selected draft (mention replies send via API; other replies open X in your browser prefilled, you add your flavor and press Post)"), ("r", "reject selected draft (instant) and hide its post (in /hidden; mentions: that post only)"), ("e", "edit selected draft"),
        ("F5", "refresh feed + catalog (= /tick): fetch new mentions and up to 10 search posts into the feed/catalog; with Grok on, free queue slots (10 mention + 10 suggested) are drafted from the catalog; works even while typing"),
        ("x / X (queue)", "clear all pending suggested / mention drafts (asks y/n; posts stay in the feed)"),
        ("F2", "open the /filter view (what is hidden and how to change it); works even while typing"),
        ("m", "mentioners list: pop-up to see/edit filtered mentioners (same as /mentioners)"),
        ("p", "pause/resume"), ("f", "browse found posts (arrows + Enter = card)"),
        ("click #n", "click a found post number in the feed to open its card"),
        ("q (in mention card)", "filter this mentioner: hide their future mentions, drop their pending drafts (edit the list with m or /mentioners)"),
        ("v (in card)", "view all of the post's media (photos, videos, GIFs) in the terminal with mpv; ←/→ previous/next item (always shown; continues into the next/previous post with media), z large photo (toggle normal fit / largest fit, never cropped), l like the post on screen, r remove (mute the author on X + hide the post, then the next post), t tags (opens the card's filter popup; Enter applies + hides the post and resumes at the next post, Esc resumes at the same item), q/Esc back; on videos also a/d seek 5s, ↑/↓ volume, space pause, m mute"),
        ("h (in card)", "hide this post for good right away (drafts dropped, never returns); a toast shows #N"),
        ("t (in card)", "filter posts like this: checklist of its author, tags, broad topics and key words; Enter applies them, hides the post (in /hidden, u restores) and refills suggestions"),
        ("t (in card)", "hide subtopics/X labels: checkbox picker of that post's labels"),
        ("←/→ a/d j/k (in card)", "previous/next post"),
        ("b (in card)", "block (verify): confirm y opens the author's x.com profile so you press Block on X (the API can't), and blocks them in xbot (local) right away"),
        ("m (in card)", "mute (real) — confirm y; send=dry only logs"),
        ("g (in card)", "draft reply editor (Grok prefill if on); Ctrl+S send, Ctrl+E queue, Ctrl+G regen"), ("F6", "move focus between input and draft list"), ("Tab (input)", "complete command, /filter subcommand or topic"), ("Up/Down (input)", "command history (saved to history.txt, secrets never stored)"),
        ("Ctrl+C / Ctrl+Q", "save and quit")]

INDEX = {c[0]: c for cmds in SECTIONS.values() for c in cmds}


def suggest(name):
    m = difflib.get_close_matches(name, INDEX.keys(), n=1, cutoff=0.5)
    return m[0] if m else None


def render_help():
    out = []
    for sec, cmds in SECTIONS.items():
        out.append(f"## {sec}")
        for n, a, d, ex, _ in cmds:
            out.append(f"  /{n} {a}".rstrip().ljust(30) + f" {d}   e.g. {ex}")
    out.append("## Keys")
    out += [f"  {k}".ljust(30) + f" {d}" for k, d in KEYS]
    out.append("## Shell")
    out.append("  xbot sample".ljust(30) + " demo mode: the TUI with fake data (no network, nothing sent)")
    out.append("  xbot secrets".ljust(30) + " edit keys in ~/.config/xbot/env with nano (0600; lists names set, never values)")
    out.append("  /help <command> for details")
    return "\n".join(out)


def render_cmd(name):
    name = name.lstrip("/").lower()
    if name not in INDEX:
        s = suggest(name)
        return f"unknown command /{name}" + (f" -- did you mean /{s}?" if s else "")
    n, a, d, ex, detail = INDEX[name]
    return "\n".join(x for x in [f"## /{n} {a}".rstrip(), f"  {d}", f"  {detail}" if detail else "", f"  example: {ex}"] if x)
