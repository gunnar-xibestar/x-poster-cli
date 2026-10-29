"""Rich markup rendering for the feed and status line. All dynamic text is escaped."""
import re
from rich.markup import escape
from rich.text import Text

URL_HINT_RE = re.compile(r"(https?://|www\.)\S+|\b[\w-]+\.(com|io|ai|dev|org|net|co)\b", re.I)

KIND_STYLE = {
    "found": "cyan", "mention": "bright_cyan", "search": "blue", "skip": "dim", "hidden": "magenta", "filter": "bold cyan", "topic": "bold cyan",
    "draft": "yellow", "edit": "yellow", "reject": "magenta", "sent": "bold green",
    "warn": "bold dark_orange", "error": "bold red", "ctl": "bright_blue", "align": "bright_magenta",
    "status": "white", "info": "dim cyan", "help": "white",
}
SOURCE_STYLE = {"search": "blue", "mention": "bright_magenta", "manual": "green", "bot": "yellow"}


def _hdr(rec):
    k = rec["kind"]
    st = KIND_STYLE.get(k, "white")
    return f"[dim]{escape(rec['ts'][11:19])}[/] [{st}]{escape(k.upper()):8}[/] "


def feed_markup(rec) -> str:
    k, msg = rec["kind"], rec.get("msg", "")
    h = _hdr(rec)
    if k == "found" and "author" in rec:
        src = rec.get("source") or "?"
        rep = " [green]✓replied[/]" if rec.get("replied") else ""
        if rec.get("tags"):
            rep = " " + " ".join(f"[magenta]#{escape(t)}[/]" for t in rec["tags"]) + rep
        replay = "[dim](replay) [/]" if rec.get("replay") else ""
        n = rec.get("n")
        media = " [bold yellow]\\[media][/]" if rec.get("media_url") else ""
        line = (f"{h}{replay}[bold underline]#{n}[/] [{SOURCE_STYLE.get(src, 'white')}]\\[{escape(src)}][/] "
                f"[bold bright_cyan]@{escape(str(rec['author']))}[/]: {escape(rec.get('snippet', ''))}{media}{rep}  "
                "[underline blue]\\[post][/]")
        if rec.get("blocked"):  # blocked author: mentions stay visible but dimmed
            line = f"[dim]{line} [italic grey62]blocked (local)[/][/]"
        return line
    if k == "filter" and "topics_on" in rec:
        G, Y, C, D = "bold green", "bold yellow", "bold cyan", "dim"
        st = "[bold black on green] ON [/]" if rec.get("on") else "[bold white on red] OFF [/] [dim](nothing below applies)[/]"
        def q(x): return chr(34) + x + chr(34) if " " in x else x
        def chips(xs, style, label="", lw=24, width=78):
            """Label + chips, wrapped with a hanging indent so continuation lines stay aligned."""
            pad = "  " + " " * lw
            if not xs:
                return [f"  {label}{' ' * max(1, lw - len(Text.from_markup(label).plain))}[dim](none)[/]"]
            lines, cur, curw = [], [], 0
            for x in xs:
                w = len(q(x)) + 2
                if cur and curw + w > width - len(pad):
                    lines.append(cur); cur, curw = [], 0
                cur.append(f"[{style}]{escape(q(x))}[/]"); curw += w
            lines.append(cur)
            head = f"  {label}{' ' * max(1, lw - len(Text.from_markup(label).plain))}"
            return [(head if i == 0 else pad) + "  ".join(l) for i, l in enumerate(lines)]
        def hint(verb, style, cmd, extra=""):
            return f"    [{D}]{verb:<7}[/][{style}]{cmd}[/]" + (f"  {extra}" if extra else "")
        V = "bold white"  # header values: readable on any theme
        words = list(rec.get('tags', [])) + list(rec['words'])
        out = [h + f"[bold]Filter[/] {st}"]
        out += chips(rec['topics_on'], V, f"[{C}]Broad topics hidden[/]")
        out += chips(rec['topics_off'], 'grey70', f"[{D}]available:[/]")
        out += [hint("add", G, "/filter hide war"), hint("remove", Y, "/filter show war"), ""]
        out += chips(words, V, f"[{C}]Excluded tags[/]")
        out += chips(rec.get('skipped', []), 'grey70', f"[{D}]skipped in search:[/]")
        out += [f"    [{D}](never fetched, never billed)[/]",
                hint("add", G, "/filter hide layoffs", f"[{D}]or a phrase[/] [{G}]/filter hide 'rug pull'[/]"),
                hint("remove", Y, "/filter show layoffs"), ""]
        ms = rec.get('mentioners', [])
        out += (chips(['@' + m for m in ms], V, f"[{C}]Filtered mentioners[/]") if ms else
                [f"  [{C}]Filtered mentioners[/]   [{D}](none yet: press[/] [{G}]q[/] [{D}]on a mention's card)[/]"])
        out += [f"    [{D}]edit list[/] [{G}]/mentioners[/]  [{D}](or[/] [{G}]m[/] [{D}]in the queue)[/]",
                hint("add", G, "/filter hide @someone", f"[{D}]or[/] [{G}]q[/] [{D}]on a mention's card[/]"),
                hint("remove", Y, "/filter show @someone"), "",
                f"  [{D}]see what got hidden and why:[/]  [{G}]/hidden[/]",
                f"  [{D}]pause all:[/]                    [{G}]/filter off[/]", "",
                "  [bold cyan]Edit a broad topic's words[/]",
                hint("pick", G, "/filter edit", f"[{D}]one topic[/] [{G}]/filter edit adult[/]"),
                hint("add", G, "/filter edit war +drone", f"[{D}]phrase[/] [{G}]/filter edit war +'drone strike'[/]"),
                hint("remove", Y, "/filter edit war -russia"),
                hint("undo", Y, "/filter reset war")]
        return "\n".join(out)
    if k == "topic" and "words" in rec:
        def q(x): return escape(chr(34) + x + chr(34) if " " in x else x)
        st = "[bold red]hidden[/]" if rec.get("on") else "[grey62]not hidden[/]"
        ws = "  ".join(f"[bold magenta]{q(w)}[/]" if w in rec.get("added", []) else f"[white]{q(w)}[/]" for w in rec["words"])
        out = [h + f"[bold cyan]Topic {escape(rec['topic'])}[/] ({st})",
               f"  [dim]matches:[/] {ws or '[dim](no words)[/]'}"]
        if rec.get("removed"):
            out.append("  [dim]you removed:[/] " + "  ".join(f"[strike grey62]{q(w)}[/]" for w in rec["removed"]))
        out += ["", f"    [dim]add    [/][bold green]/filter edit {escape(rec['topic'])} +drone[/]",
                f"    [dim]remove [/][bold yellow]/filter edit {escape(rec['topic'])} -russia[/]",
                f"    [dim]undo   [/][bold yellow]/filter reset {escape(rec['topic'])}[/]",
                f"    [dim]phrase [/][bold green]/filter edit {escape(rec['topic'])} +'drone strike'[/]"]
        return "\n".join(out)
    if k == "hidden":
        parts = msg.split("\n")
        head = parts[0]
        lbl, _, rest = head.partition(" ")
        out = [h + f"[bold magenta]{escape(lbl)}[/] {escape(rest)}"]
        for ln in parts[1:]:
            if "caught by:" in ln:
                pre, _, why = ln.partition("caught by:")
                out.append(f"{pre}[dim]caught by:[/] [bold yellow]{escape(why.strip())}[/]")
            else:
                out.append(f"[underline blue]{escape(ln)}[/]")
        return "\n".join(out)
    if k == "section":
        return f"[bold reverse cyan] {escape(msg)} [/]"
    if k == "help":
        lines = []
        for line in msg.split("\n"):
            if line.startswith("## "):
                lines.append(f"[bold cyan]{escape(line[3:])}[/]")
            elif line.lstrip().startswith("/"):
                m = re.match(r"(\s*)(/\S+)(.*)", line)
                rest = escape(m.group(3)).replace("e.g.", "[dim]e.g.[/]")
                lines.append(f"{m.group(1)}[bold green]{escape(m.group(2))}[/]{rest}")
            else:
                lines.append(escape(line))
        return h + "\n".join(lines)
    st = KIND_STYLE.get(k, "white")
    body = escape(msg)
    if k == "sent":
        body = body.replace("\\[DRY-SEND]", "[bold green on grey15]\\[DRY-SEND][/]").replace(
            "\\[LIVE]", "[bold white on red]\\[LIVE][/]").replace(
            "\\[DRY-MUTE]", "[bold green on grey15]\\[DRY-MUTE][/]")
        return h + f"[green]{body}[/]"
    if k == "error" and re.search(r"auth|credit|40[1-3]|forbidden|missing", msg, re.I):
        return h + f"[bold red reverse]{body}[/]"
    if k in ("warn", "error", "draft", "mention", "align", "reject", "edit", "info", "skip"):
        return h + f"[{st}]{body}[/]"
    return h + body


def feed_text(rec) -> Text:
    t = Text.from_markup(feed_markup(rec))
    n = rec.get("n")
    if rec.get("kind") == "found" and isinstance(n, int):
        from rich.style import Style
        tag = f"#{n} "
        i = t.plain.find(tag)
        if i >= 0:  # clickable post number -> opens card
            t.stylize(Style(meta={"@click": f"app.show_post({n})"}), i, i + len(tag) - 1)
        k = t.plain.rfind("[post]")
        if k >= 0:  # clickable [post] label -> opens the post in the browser
            t.stylize(Style(meta={"@click": f"app.open_post({n})"}), k, k + 6)
        j = t.plain.find(" [media]")
        if rec.get("media_url") and j >= 0:  # clickable media link -> opens only the media
            t.stylize(Style(meta={"@click": f"app.open_media({n})"}), j + 1, j + 8)
    return t


def status_markup(bot) -> str:
    c = bot.cfg
    st = ("[bold red]STOPPED[/]" if bot.stopped else "[bold yellow]PAUSED[/]" if bot.paused
          else "[bold green]RUNNING[/]")
    reads = "[bold red]reads=LIVE[/]" if bot.reads_live() else "[green]reads=off[/]"
    send = "[green]send=dry[/]" if c.dry_run else "[bold white on red]send=LIVE[/]"
    grok = (f"[bright_magenta]grok=on[/] [dim]{escape(c.model)}[/]" if bot.grok_on
            else "[dark_orange]grok=off (X-only)[/]")
    pend = len(bot.queue.pending_capped())
    nm = len(bot.queue.pending()) - pend
    full = c.max_pending and pend >= c.max_pending
    q = (f"[bold red]pending={pend}/{c.max_pending} FULL[/]" if full else f"pending={pend}/{c.max_pending}") \
        + (f" [bright_magenta]+{nm} mentions[/]" if nm else "")
    spend = bot.state.spent_today()
    cap = ""
    if c.daily_cap_usd:
        cap = f"/${c.daily_cap_usd:.2f}" + (" [bold red]CAP HIT[/]" if bot.cap_hit() else "")
    srch = "[blue]search=on[/]" if c.search_enabled else "[dim]search=off[/]"
    return (f"{st} │ {reads} │ {send} │ {grok} │ found={len(bot.found)} │ {q} │ {srch} │ "
            f"replies/h={bot.state.reply_sends_last_hour()}/{c.max_replies_per_hour} │ "
            + " │ ".join(__import__("xbot.credits", fromlist=["x"]).spend_lines(bot))
            + (f" │ X today ${spend:.3f}{cap}" if c.daily_cap_usd else "")
            + f" │ last check {bot.last_check_str()} │ ticks={bot.ticks}")


# ---- post card -------------------------------------------------------------
from datetime import datetime
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")


def fmt_time(iso):
    if not iso:
        return "time unknown"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LA)
        return dt.strftime("%a %b %-d %Y, %-I:%M %p ") + dt.tzname()
    except ValueError:
        return iso


def _metrics(p):
    m = p.get("public_metrics") or {}
    parts = [("replies", m.get("reply_count")), ("reposts", m.get("retweet_count")),
             ("likes", m.get("like_count")), ("quotes", m.get("quote_count"))]
    return [(k, v) for k, v in parts if v is not None]


def card_plain(n, p):
    handle = p.get("username") or p.get("author_id", "?")
    name = p.get("name") or handle
    met = "  ".join(f"{k} {v}" for k, v in _metrics(p)) or "metrics n/a"
    tg = (" tags: " + ",".join(p.get("tags", []))) if p.get("tags") else ""
    return (f"#{n} [{p.get('source')}]{tg} {name} @{handle} · {fmt_time(p.get('created_at'))}\n{p['text']}\n"
            f"{met}{'  ✓replied' if p.get('replied') else ''}\nhttps://x.com/i/status/{p['id']}")


def drafts_title(bot):
    c = bot.cfg
    pend = len(bot.queue.pending_capped())
    nm = len(bot.queue.pending()) - pend
    cap = f"{pend}/{c.max_pending}" if c.max_pending else str(pend)
    mc = c.max_mention_drafts
    w = bot.catalog_size()
    cap += f" · waiting {w}" if w else ""
    st = bot.drafting_status() if hasattr(bot, "drafting_status") else ""
    cap += f" · {st}" if st else ""
    return "Auto replies (Grok drafts) " + (f"{nm}/{mc} mentions · " if nm and mc else f"{nm} mentions · " if nm else "") + cap


def drafts_placeholder(bot):
    if bot.queue.pending():
        return ""
    if not bot.grok_on:
        return ("Grok off - add XAI_API_KEY to ~/.config/xbot/env and /grok on to fill this.\n\n"
                "Meanwhile: open a post (click #n or press f), press g to write a reply, Ctrl+E saves it here.")
    return "No drafts yet - /tick or press g on a post."


def _key(k, bg="bright_white"):
    return f"[bold black on {bg}] {escape(k)} [/]"


def card_renderable(n, p, bot=None, part="all"):
    """Post detail panel. part='body' -> scrollable body only (no hints, no border), 'hints' -> key help
    Text, 'title' -> (title markup, border style); 'all' -> the full bordered Panel."""
    from rich.panel import Panel
    from rich.console import Group
    from rich.padding import Padding
    from rich.rule import Rule
    src = p.get("source") or "?"
    sstyle = SOURCE_STYLE.get(src, "white")
    # header row
    if p.get("username"):
        handle = escape(str(p["username"]))
        name = escape(str(p.get("name") or handle))
        who = f"[bold bright_white]{name}[/]  [bold bright_cyan]@{handle}[/]"
    else:
        aid = p.get("author_id")
        state = "[dim italic]looking up author…[/]" if p.get("author_lookup") is None else "[dim italic](author lookup failed)[/]"
        who = f"[bold]{'author ' + escape(str(aid)) if aid else 'unknown author'}[/] {state}"
    pos = ""
    if bot is not None:
        order = bot.nav_order()
        pos = f"{order.index(n) + 1}/{len(order)}" if n in order else f"hidden/{len(order)}"
    header = f"{who}   [dim]{escape(fmt_time(p.get('created_at')))}[/]"
    # metrics row
    icons = {"replies": ("💬", "bright_blue"), "reposts": ("🔁", "green"), "likes": ("♥", "bright_red"),
             "quotes": ("❝", "yellow")}
    met = "    ".join(f"[{icons[k][1]}]{icons[k][0]} [bold]{v}[/][/] [dim]{k}[/]" for k, v in _metrics(p)) \
        or "[dim]metrics n/a[/]"
    # status row
    st = [f"[{sstyle}]● {escape(src)}[/]"]
    if p.get("replied"):
        st.append("[bold green]✓ replied[/]")
    if bot is not None:
        h = (p.get("username") or "").lower()
        if h and h in bot.cfg.muted_authors:
            st.append("[bold orange_red1]🔇 muted (real)" + ("" if bot.cfg.muted_authors[h].get("live") else " [dim](dry run)[/]") + "[/]")
        elif bot.is_blocked(p):
            st.append("[grey62]⛔ blocked (local)[/]")
        if bot.hidden(p):
            st.append("[dim]hidden from suggestions[/]")
    status = "   ".join(st)
    link = f"[@click=app.open_post({n})][underline blue]\\[post][/][/] [dim]o[/]"
    if p.get("username"):
        link += f"   [@click=app.open_profile({n})][underline blue]\\[profile][/][/]"
    if p.get("media"):
        k = len(p["media"])
        link += (f"   [@click=app.open_media({n})][bold yellow]\\[media][/][/]" + (f" [dim]({k} items)[/]" if k > 1 else "")
                 + " [dim]v[/]")
    N, A, F = "bright_cyan", "bright_green", "bold yellow"
    hints = (f"[bold {N}]Navigate[/] " + _key("←/→", N) + " " + _key("j/k", N) + f" [{N}]prev/next[/]  "
             + _key("Esc", N) + f" [{N}]esc to back[/]\n"
             f"[bold {A}]Act[/]      " + _key("g", A) + f" [{A}]draft reply[/]  " + _key("r", A) + f" [{A}]reply[/]  "
             + _key("o", A) + f" [{A}]open in browser[/]" + "  " + _key("l", A) + f" [{A}]like[/]"
             + (("  " + _key("v", A) + f" [{A}]view media[/]") if p.get("media") else "") + "\n"
             f"[bold {F}]Filter[/]   " + _key("t", F) + f" [{F}]filter like this[/]  " + _key("h", F) + f" [{F}]hide for good[/]  " + _key("b", F)
             + f" [{F}]block[/] [grey62](verify)[/]  " + _key("m", F) + f" [{F}]mute[/] [bold orange_red1](real)[/]"
             + (("\n         " + _key("q", F) + f" [{F}]filter this mentioner[/] [grey62](hide their mentions)[/]")
                if p.get("source") == "mention" else ""))
    parts = [
        Text.from_markup(header),
        Text(""),
        Padding(Text(p["text"]), (0, 0, 0, 2)),  # indent only: the text wraps right up to the border
        Text(""),
        Text.from_markup(met),
        Text(""),
        Text.from_markup(label_block(p, bot).strip("\n")),
        Text(""),
        Text.from_markup(status),
        Text.from_markup(link),
    ]
    if part == "hints":
        return Padding(Text.from_markup(hints), (0, 1))  # renderable wrapper: Static keeps rich styles as-is
    if part == "body":
        return Padding(Group(*parts), (0, 1, 0, 1))
    parts += [Rule(style="dim"), Text.from_markup(hints)]
    title = f"[bold]#{n}[/] [{sstyle}]{escape(src)}[/]" + (f" [dim]·[/] [bold]{pos}[/]" if pos else "")
    if part == "title":
        return title, sstyle
    return Panel(Group(*parts), title=title, title_align="left", border_style=sstyle, padding=(1, 1, 1, 2), expand=True)


def label_block(p, bot=None):
    """Grouped label sections: Tags, X topics, Entities, Cashtags, Links. Hidden ones struck."""
    from .tags import LABEL_KINDS
    exc = set(bot.cfg.excluded_tags) if bot else set()

    def chip(lid, shown, style):
        if lid in exc:
            return f"[strike dim]{escape(shown)}[/] [dim](hidden)[/]"
        return f"[{style}]{escape(shown)}[/]"
    rows = []
    tags = p.get("tags") or []
    rows.append("[bold magenta]Tags[/]       " + ("  ".join(chip(t, " #" + t + " ", "bold white on magenta") for t in tags)
                                            if tags else "[dim]none[/]"))
    xl = p.get("xlabels") or {}
    names = {"topics": ("X topics", "cyan"), "entities": ("Entities", "yellow"), "cashtags": ("Cashtags", "green"),
             "links": ("Links", "blue")}
    for group, prefix in LABEL_KINDS:
        vals = xl.get(group) or []
        if vals:
            title, style = names[group]
            rows.append(f"[bold {style}]{title:<10}[/] " + "  ".join(chip(f"{prefix}:{v}", v, style) for v in vals))
    return "\n" + "\n".join(rows)
