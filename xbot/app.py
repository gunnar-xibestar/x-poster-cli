"""Textual TUI: feed | draft queue | console | post cards | filter popups | media viewer.

Key bindings and mouse clicks live here. Heavy work (polling, drafting, X API, mpv) is
delegated to Bot / video.py so the UI stays responsive. `xbot sample` subclasses this
as DemoApp with fake data and a temp state dir.
"""
from pathlib import Path
import asyncio
import signal
import threading
from .textutil import clip
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import SelectionList, TextArea
from .render import URL_HINT_RE
from textual.widgets import Header, Footer, Input, RichLog, ListView, ListItem, Label, Static

from .commands import parse, CommandError
from .render import feed_text, status_markup, card_renderable, drafts_title, drafts_placeholder
from .opener import open_url_async
from .config import Config, load_env_file
from .log import ActionLog
from .xapi import DryRunX, RealX


ESC_HINT = "[bold bright_red]esc[/] to back"


class EscModal(ModalScreen):
    """Every popup shows 'esc to back' at its window's top-left (border title, left-aligned)."""
    ESC_IN_CONTENT = False  # True: the content itself already shows the esc hint inside the box

    def on_mount(self):
        if not self.children or self.ESC_IN_CONTENT:
            return
        w = self.children[0]
        t = w.border_title
        if not (t and "esc" in str(t)):
            w.border_title = ESC_HINT + (f" · {t}" if t else "")
        w.styles.border_title_align = "left"


def pick_renderer(setting="auto", env=None):
    """Terminal graphics guess used to pick mpv's sixel output: 'tgp' (kitty/Ghostty), 'sixel' (Windows Terminal,
    WezTerm, Konsole, foot, xterm, mlterm, iTerm2), else 'halfblock'. Env hints only (plus the startup probe)."""
    import os
    s = (setting or "auto").lower()
    if s != "auto":
        return s if s in ("sixel", "tgp", "halfblock", "off") else "halfblock"
    e = os.environ if env is None else env
    term, prog = e.get("TERM", "").lower(), e.get("TERM_PROGRAM", "").lower()
    if e.get("TMUX") or term.startswith(("screen", "tmux")):
        return "halfblock"  # multiplexers mangle graphics passthrough
    if e.get("KITTY_WINDOW_ID") or "kitty" in term or "ghostty" in term or prog == "ghostty":
        return "tgp"
    caps = graphics_probed() if env is None else None
    if (e.get("WT_SESSION") or e.get("WEZTERM_PANE") or prog in ("wezterm", "iterm.app") or e.get("KONSOLE_VERSION")
            or term.startswith(("foot", "mlterm")) or e.get("XTERM_VERSION")):
        if caps is not None and not caps.sixel:
            return "halfblock"  # the startup probe says this terminal can't draw sixel
        return "sixel"
    return "halfblock"


def probe_graphics():
    """Run textual-image's one-time terminal probe (cell size + sixel/TGP support) while we still own the tty.
    Importing textual_image.widget probes; done lazily under Textual, the terminal's replies (e.g. ESC[6;20;10t)
    were read as keys: the trailing 't' opened the 'filter posts like this' popup and the image came out blank."""
    try:
        import textual_image.widget  # noqa: F401  (probe is cached)
        from textual_image._terminal import probe_terminal
        return probe_terminal()
    except Exception:
        return None


def graphics_probed():
    try:
        from textual_image._terminal import probe_terminal
        return getattr(probe_terminal, "_result", None)
    except Exception:
        return None


def large_media_url(url):
    from .video import large_photo_url
    return large_photo_url(url)


def pick_after_hide(old_order, new_order, cur, prefer=None):
    """Where a post list should land after posts were hidden: `prefer` (the post the viewer last showed) if
    still visible, else `cur` if still visible, else the next visible post after `cur` in the old order, else
    the previous one; None when nothing is left."""
    vis = set(new_order)
    if not new_order:
        return None
    for k in (prefer, cur):
        if k is not None and k in vis:
            return k
    if cur in old_order:
        i = old_order.index(cur)
        for k in old_order[i + 1:]:
            if k in vis:
                return k
        for k in reversed(old_order[:i]):
            if k in vis:
                return k
    return new_order[0]


class PostCard(EscModal):
    ESC_IN_CONTENT = True  # card panel's key legend has "Esc to back"
    BINDINGS = [("escape", "dismiss", "Close"), ("o", "open", "Open in browser"), ("r", "reply", "Reply"),
                ("t", "tags", "Filter posts like this"), ("h", "hide", "Hide for good"), ("v", "media", "View media (mpv)"), ("l", "like", "Like"), ("q", "filter_mentioner", "Filter mentioner"), ("g", "draft", "Draft reply"), ("b", "block", "Block author"), ("m", "mute", "Mute on X"),
                ("left,up,k,a", "nav(-1)", "Prev"), ("right,down,j,d", "nav(1)", "Next"),
                Binding("pageup", "scroll_text(-1)", "Scroll text", show=False), Binding("pagedown", "scroll_text(1)", "Scroll text", show=False),
                Binding("home", "scroll_edge(-1)", "Top", show=False), Binding("end", "scroll_edge(1)", "Bottom", show=False)]

    def action_scroll_edge(self, d):
        sc = self.query_one("#card-scroll")
        (sc.scroll_end if d > 0 else sc.scroll_home)(animate=False)

    def action_scroll_text(self, d):
        sc = self.query_one("#card-scroll")
        (sc.scroll_page_down if d > 0 else sc.scroll_page_up)(animate=False)

    def action_nav(self, step):
        bot = self.app.bot
        order = bot.nav_order()
        if not order:
            return
        if self.n in order:
            i = order.index(self.n) + step
        else:  # current post got hidden: jump to nearest
            i = 0 if step > 0 else len(order) - 1
        if not 0 <= i < len(order):
            self.app.edge_notify("first post" if i < 0 else "last post")
            return
        self.n = order[i]
        self.post = bot.found_post(self.n)
        self._redraw()
        self._lookup()

    def _redraw(self):
        bot = self.app.bot
        self.query_one("#card", Static).update(card_renderable(self.n, self.post, bot, part="body"))
        self.query_one("#card-hints", Static).update(card_renderable(self.n, self.post, bot, part="hints"))
        title, style = card_renderable(self.n, self.post, bot, part="title")
        box = self.query_one("#card-box")
        box.border_title = title
        try:
            from textual.color import Color
            Color.parse(style)
            box.styles.border = ("round", style)
        except Exception:
            box.styles.border = ("round", "white")
    DEFAULT_CSS = ("PostCard { align: center middle; } PostCard > #card-box { width: 90%; max-width: 130; height: auto; max-height: 95%; "
                   "border: round $primary; border-title-align: left; background: $panel; padding: 1 1 0 1; } "
                   "#card-scroll { width: 100%; height: auto; max-height: 1fr; background: $panel; } "
                   "#card { width: 100%; height: auto; background: $panel; } "
                   "#card-hints { width: 100%; height: auto; background: $panel; border-top: solid $panel-lighten-2; } "
                   "PostCard { layers: base heart; } #heart { layer: heart; display: none; width: auto; height: auto; "
                   "background: $panel 0%; } #heart.on { display: block; }")

    def __init__(self, n, post):
        super().__init__()
        self.n, self.post = n, post

    def compose(self):
        with Vertical(id="card-box"):
            with VerticalScroll(id="card-scroll"):  # tall posts scroll here (wheel, PgUp/PgDn, Home/End)
                yield Static(card_renderable(self.n, self.post, self.app.bot, part="body"), id="card")
            yield Static(card_renderable(self.n, self.post, self.app.bot, part="hints"), id="card-hints")  # pinned
        yield Static("", id="heart")

    def _layout(self):
        """Body scroll gets the card height minus the pinned key-help footer, border and padding."""
        sc = self.query_one("#card-scroll")
        hints = self.query_one("#card-hints")
        hh = (hints.virtual_size.height or hints.region.height or 4) + 1
        sc.styles.max_height = max(3, int(self.app.size.height * 0.95) - hh - 3)

    def on_resize(self, ev):
        self._layout()

    def on_mount(self):
        self._redraw()
        self._lookup()

    def _lookup(self):
        p = self.post
        if not p.get("username") and p.get("author_lookup") != "failed":
            n = self.n
            async def work():
                import asyncio
                await asyncio.to_thread(self.app.bot.lookup_author, n)
                if self.n == n:
                    self._redraw()
            self.run_worker(work(), group="author")

    def queued_draft(self):
        """Latest pending queued reply to this post, if any."""
        pid = str(self.post.get("id"))
        ds = [d for d in self.app.bot.queue.pending() if d.kind == "reply" and str(d.in_reply_to) == pid]
        return ds[-1] if ds else None

    def action_open(self):
        d = self.queued_draft()
        if d is None:
            self.app._run(f"/open {self.n}"); return
        url = self.app.bot.intent_url(d.in_reply_to, d.text)
        self.app.bot.log.event("info", f"opened X reply page for #{self.n} with draft #{d.id} filled in")
        (self.app.bot.opener or open_url_async)(url, lambda how: None)

    HEART_FRAMES = ("♥", " ♥ ♥\n♥♥♥♥♥\n ♥♥♥\n  ♥",
                    " ♥♥♥   ♥♥♥\n♥♥♥♥♥ ♥♥♥♥♥\n♥♥♥♥♥♥♥♥♥♥♥\n ♥♥♥♥♥♥♥♥♥\n   ♥♥♥♥♥\n     ♥",
                    " ♥ ♥\n♥♥♥♥♥\n ♥♥♥\n  ♥", "♥")

    def action_like(self):
        """l (card, and in the mpv viewer): like through the X API once per post (liked set in state.json; rolled
        back if X refuses); the heart animation plays on every press. Never opens the browser."""
        n = self.n
        if str(self.post.get("id")) not in self.app.bot.state.liked:
            async def work():
                ok, msg = await asyncio.to_thread(self.app.like_once, n)
                self.app.notify(msg, severity="information" if ok else "warning", timeout=4)
            self.run_worker(work(), group="like")
        self.heart()

    def heart(self, interval=0.07):
        h = self.query_one("#heart", Static)
        frames = list(self.HEART_FRAMES)
        self.heart_frames_shown = []
        def step():
            if not frames:
                h.remove_class("on"); return
            f = frames.pop(0); self.heart_frames_shown.append(f)
            h.update(Text(f, style="bold red", justify="center")); h.add_class("on")
            self.set_timer(interval, step)
        step()

    def action_tags(self):
        """t: filter picker for posts like this (tags, broad topics, words, author); Enter applies and hides it."""
        n = self.n
        self._old_order = list(self.app.bot.nav_order())
        self.app.push_screen(FilterOptions(self.app.bot, n),
                             lambda r: None if r == "cancel" else self._after_hide(n, r))

    def action_filter_mentioner(self):
        """q on a mention's card: filter this mentioner (non-mention cards: nothing)."""
        if self.post.get("source") != "mention":
            return
        try:
            who = self.app.bot.filter_mentioner_post(self.n)
        except KeyError as e:
            self.app.notify(str(e).strip("'"), timeout=2); return
        self.app.notify(f"@{who} filtered. m or /mentioners to edit the list", timeout=4)
        self._redraw(); self.app.refresh_ui()

    def action_media(self):
        """v: every photo, video and GIF of the post in the terminal mpv viewer (A/D browse, q/Esc back).
        Never opens a browser or an external player."""
        if not self.post.get("media"):
            self.app.notify("no media on this post", timeout=2); return
        self.app.guarded("view media", self.app.play_media, self.n)

    def action_hide(self):
        """h: hide this post for good, right away (filters live under t)."""
        n = self.n
        self._old_order = list(self.app.bot.nav_order())
        self.app.bot.hide_post(n, forever=True)
        self.app.notify(f"#{n} hidden for good", timeout=2)
        self._after_hide(n, None)

    def _after_hide(self, n, applied):
        self.app.call_after_refresh(self._after_hide_now, n, applied)

    def _after_hide_now(self, n, applied):
        self.app.refresh_ui()
        if applied:
            self.app.apply_filters_and_refill()
        self.app.resync_after_hide(getattr(self, "_old_order", None) or [n])

    def resync(self, old_order, prefer=None):
        """Posts were hidden (h, t, or r/t in the viewer): move to the right visible post, or close."""
        bot = self.app.bot
        new = list(bot.nav_order())
        k = pick_after_hide(old_order, new, self.n, prefer)
        if k is None:
            self.dismiss(); self.app.notify("no posts left in this list", timeout=3); return
        if k != self.n:
            self.n, self.post = k, bot.found_post(k)
            self._lookup()
        self._redraw()

    def action_block(self):
        h = (self.post.get("username") or "").lower()
        if not h:
            self.app.notify("author handle unknown; can't block", timeout=2); return
        def after(ok):
            if ok:
                self.app.bot.open_profile_to_block(h)
                self._redraw(); self.app.refresh_ui()
        self.app.push_screen(Confirm(f"Block @{h}? y/n\nOpens x.com/{h} so you can press Block on X "
                                     "(the API can't block for you) and hides them in xbot now."), after)

    def action_mute(self):
        h = (self.post.get("username") or "").lower()
        if not h:
            self.app.notify("author handle unknown; can't mute", timeout=2); return
        bot = self.app.bot
        mode = "send=dry: logged only, blocks (local)" if bot.cfg.dry_run else "LIVE ~$0.015"
        aid = self.post.get("author_id")
        def after(ok):
            if ok:
                bot.mute(h, author_id=aid)
                self._redraw(); self.app.refresh_ui()
        self.app.push_screen(Confirm(f"Mute @{h} (real)? y/n  ({mode})"), after)

    def _editor_after(self):
        bot = self.app.bot
        order = [str(bot.found_post(m)["id"]) for m in bot.nav_order()]  # ids: numbers shift when a post is removed
        def after(r):
            if r == "browser" or not any(str(p["id"]) == str(self.post["id"]) for p in bot.found):
                self.next_after_browser(order)  # replied (browser or Ctrl+S): post removed, show the next
            else:
                self._redraw()
        return after

    def next_after_browser(self, old_order):
        """Reply posted via the browser: close this card and open the next post in the list (none: back to list)."""
        bot = self.app.bot
        cur = str(self.post["id"])
        now = {str(bot.found_post(m)["id"]): m for m in bot.nav_order()}
        rest = old_order[old_order.index(cur) + 1:] if cur in old_order else []
        nxt = next((now[i] for i in rest if i in now and i != cur), None)
        app = self.app
        self.dismiss()
        if nxt is not None:
            app.push_screen(PostCard(nxt, bot.found_post(nxt)))
        def lists():  # open Found posts lists drop the replied post (and renumber)
            for s in list(app.screen_stack):
                if isinstance(s, FoundPicker):
                    try:
                        s.rebuild()
                    except Exception as e:
                        _crash_log(e)
        app.call_after_refresh(lists)

    def action_draft(self):
        self.app.push_screen(ReplyEditor(self.n, self.post), self._editor_after())

    def action_reply(self):
        """r: the reply editor like g, but blank (no Grok prefill), focus in its text box."""
        self.app.push_screen(ReplyEditor(self.n, self.post, blank=True), self._editor_after())


class Confirm(EscModal):
    DEFAULT_CSS = "Confirm { align: center middle; } Confirm > Static { width: 60; border: round red; padding: 1; background: $panel; }"

    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    def compose(self):
        yield Static(Text(self.msg))

    def on_key(self, ev):
        ev.stop()
        self.dismiss(ev.key.lower() == "y")


class HideConfirm(EscModal):
    """y / n / esc (esc = cancel everything)."""
    DEFAULT_CSS = Confirm.DEFAULT_CSS.replace("Confirm", "HideConfirm")

    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    def compose(self):
        s = Static(Text.from_markup(self.msg))
        yield s

    def on_key(self, ev):
        ev.stop()
        if ev.key in ("y", "n", "escape"):
            self.dismiss(ev.key)


class ReplyEditor(EscModal):
    """Multi-line reply editor for a found post. Grok pre-fills when on."""
    BINDINGS = [Binding("ctrl+s", "send", "Send", priority=True),
                Binding("ctrl+g", "regen", "Regenerate", priority=True),
                Binding("ctrl+e", "queue", "Save to queue", priority=True),
                Binding("ctrl+b", "open_browser", "Post in browser", priority=True),
                # Windows Terminal grabs Ctrl+O (File Explorer); kept as a hidden alias for other terminals
                Binding("ctrl+o", "open_browser", "Post in browser", show=False, priority=True),
                Binding("escape", "cancel", "Cancel", priority=True)]
    DEFAULT_CSS = ("ReplyEditor { align: center middle; } #ed-box { width: 90; max-width: 95%; height: auto; "
                   "background: $panel; border: round green; padding: 0 1; } #ed { height: 10; } #ed-info { height: 3; }")

    def __init__(self, n, post, blank=False):
        super().__init__()
        self.n, self.post, self.blank = n, post, blank
        self.grok_text = None  # last Grok draft shown (style learning)

    def compose(self):
        from textual.containers import Vertical
        who = self.post.get("username") or self.post.get("author_id", "?")
        with Vertical(id="ed-box"):
            yield Static(Text(f"Reply to #{self.n} @{who}: {clip(self.post['text'], 400)}"), id="ed-ctx")
            yield TextArea(id="ed")
            yield Static("", id="ed-info")

    def on_mount(self):
        self.query_one("#ed", TextArea).focus()
        self._update_info()
        if self.app.bot.grok_on and not self.blank:
            self.action_regen()

    @property
    def is_mention(self):
        return self.post.get("source") == "mention"

    @property
    def text(self):
        return self.query_one("#ed", TextArea).text.strip()

    def _update_info(self, extra=""):
        b = self.app.bot
        n = len(self.text)
        cnt = f"[bold red]{n}/280 too long[/]" if n > 280 else f"[green]{n}/280[/]"
        url = "  [bold dark_orange]contains a URL: $0.20 instead of $0.015[/]" if URL_HINT_RE.search(self.text) else ""
        mode = "[green]send=dry[/]" if b.cfg.dry_run else "[bold white on red]send=LIVE[/]"
        hint = ""
        send = "[bold green]Ctrl+S[/] [green]send[/]   "
        if not self.is_mention:
            send = ""
            hint = "\n[dim]Search post: X blocks API replies to posts that didn't mention you, so press [bold cyan]Ctrl+B[/] to post it in the browser with this reply filled in.[/]"
        grok = "[bold magenta]Ctrl+G[/] [magenta]regenerate[/]   " if b.grok_on else "[dim]grok off[/]   "
        self.query_one("#ed-info", Static).update(Text.from_markup(
            f"{cnt}{url}  {mode}  {extra}\n{send}[bold yellow]Ctrl+E[/] [yellow]save to queue[/]   [bold cyan]Ctrl+B[/] [cyan]post in browser[/]   {grok}{hint}"))

    def on_text_area_changed(self, ev):
        self._update_info()

    def action_regen(self):
        if not self.app.bot.grok_on:
            return
        self._update_info("[yellow]drafting…[/]")
        self.run_worker(self._draft(), exclusive=True, group="draft")

    async def _draft(self):
        import asyncio
        from rich.markup import escape
        t = await asyncio.to_thread(self.app.bot.draft_for_post, self.n)
        if t:
            self.grok_text = t
            self.query_one("#ed", TextArea).text = t
            self._update_info("[green]draft ready[/]")
        else:
            why = self.app.bot.last_draft_error
            self._update_info(f"[bold red]no draft: {escape(why)}[/]" if why else "[red]no draft (see feed)[/]")

    def action_send(self):
        if not self.is_mention:
            self._update_info("[yellow]API send is for mentions only. Press Ctrl+B to post this in the browser (or Ctrl+E, then o on the card / a in the queue).[/]"); return
        if not self.text:
            self._update_info("[red]empty[/]"); return
        if len(self.text) > 280:
            self._update_info("[red]over 280[/]"); return
        tid = self.app.bot.send_reply_to_found(self.n, self.text, grok_text=self.grok_text)
        if tid:
            self.dismiss(tid); self.app.refresh_ui()
        else:
            self._update_info("[red]send failed (see feed)[/]")

    def action_queue(self):
        if not self.text:
            self._update_info("[red]empty[/]"); return
        self.app.bot.queue_reply_to_found(self.n, self.text, grok_text=self.grok_text)
        self.dismiss(None); self.app.refresh_ui()

    def intent_url(self):
        from urllib.parse import quote
        return f"https://x.com/intent/post?in_reply_to={self.post['id']}&text={quote(self.text, safe='')}"

    def action_open_browser(self):
        if not self.text:
            self.app._run(f"/open {self.n}")
            self._update_info("[cyan]opened post in browser[/]")
            return
        from .opener import open_url_async
        url = self.intent_url()
        self.app.bot.log.event("info", f"opened X reply page for #{self.n} with draft filled in")
        open_url_async(url, lambda how: None)
        self.app.bot.browser_reply_to_found(self.n, self.text, grok_text=self.grok_text)
        self.app.notify("Reply opened in browser and saved; showing the next post.", timeout=4)
        self.dismiss("browser"); self.app.refresh_ui()

    def action_cancel(self):
        self.dismiss(None)


class TagPicker(EscModal):
    """Checkbox list of tags; checked = hidden. Space toggles, Enter saves, Esc cancels."""
    BINDINGS = [Binding("escape", "dismiss", "Cancel"), Binding("enter", "save", "Save", priority=True)]
    DEFAULT_CSS = ("TagPicker { align: center middle; } TagPicker > SelectionList { width: 60; height: 80%; "
                   "border: round magenta; background: $panel; }")

    def __init__(self, bot, only=None, title="Check tags to HIDE · space toggle · enter save", subtitle=""):
        super().__init__()
        self.bot, self.only, self.title_, self.subtitle_ = bot, only, title, subtitle

    def compose(self):
        cnt = self.bot.tag_counts()
        if self.only is not None:
            tags = list(self.only)
        else:
            tags = list(self.bot.taxonomy) + sorted(t for t in cnt if t not in self.bot.taxonomy and t != "untagged")
        self.tags = tags
        opts = [(f"{t}  ({cnt.get(t, 0)})", t, t in self.bot.cfg.excluded_tags) for t in tags]
        if self.only is None:
            self.authors = list(self.bot.cfg.blocked_authors)
            opts += [(f"@{h}  block (local) — uncheck to unblock", "@" + h, True) for h in self.authors]
        else:
            self.authors = []
        sl = SelectionList(*opts, id="tags")
        sl.border_title = self.title_
        sl.border_subtitle = self.subtitle_
        yield sl

    def on_mount(self):
        self.query_one(SelectionList).focus()

    def action_save(self):
        allsel = set(self.query_one(SelectionList).selected)
        sel = {t for t in allsel if not t.startswith("@")}
        # only touch the tags shown in this picker; keep other exclusions as they are
        new = (set(self.bot.cfg.excluded_tags) - set(self.tags)) | sel
        self.bot.set_excluded(new)
        if self.authors:
            keep = {t[1:] for t in allsel if t.startswith("@")}
            if keep != set(self.authors):
                self.bot.set_blocked(keep)
        self.dismiss(sel)
        self.app.refresh_ui()


class TopicPicker(EscModal):
    """Broad topics: checked = hidden. Space toggles, e edits the highlighted topic's words, Enter saves."""
    BINDINGS = [Binding("escape", "dismiss", "Cancel"), Binding("enter", "save", "Save", priority=True),
                Binding("e", "edit", "Edit words"), Binding("r", "apply", "Apply + refresh")]
    DEFAULT_CSS = ("TopicPicker { align: center middle; } TopicPicker > SelectionList { width: 72; height: 70%; "
                   "border: round red; background: $panel; }")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def compose(self):
        from .safety import ALL_TOPICS, topic_words
        opts = [(f"{t}  ({len(topic_words(t))} words" + (", edited)" if t in self.bot.cfg.topic_edits else ")"),
                 t, t in self.bot.cfg.filter_topics) for t in ALL_TOPICS]
        sl = SelectionList(*opts, id="topics")
        sl.border_title = "Check topics to HIDE"
        sl.border_subtitle = "space toggle · e edit words · r apply+refresh · enter save"
        yield sl

    def on_mount(self):
        self.query_one(SelectionList).focus()

    async def action_edit(self):
        sl = self.query_one(SelectionList)
        if sl.highlighted is None:
            return
        t = sl.get_option_at_index(sl.highlighted).value
        self.app.push_screen(TopicWords(self.bot, t))

    def action_save(self):
        self.bot.set_filter_topics(self.query_one(SelectionList).selected)
        self.dismiss(); self.app.refresh_ui()

    def action_apply(self):
        """Save, re-apply filters to the list, and fetch more posts if fewer than 20 suggestions remain."""
        self.bot.set_filter_topics(self.query_one(SelectionList).selected)
        self.dismiss()
        self.app.apply_filters_and_refill()


class TopicWords(EscModal):
    """A topic's words: checked = matched. Type in the box + Enter to add; Ctrl+S saves."""
    BINDINGS = [Binding("escape", "dismiss", "Cancel"), Binding("ctrl+s", "save", "Save", priority=True),
                Binding("tab", "swap", "Switch box", priority=True)]
    DEFAULT_CSS = ("TopicWords { align: center middle; } TopicWords > Vertical { width: 64; height: 80%; "
                   "border: round magenta; background: $panel; } TopicWords SelectionList { height: 1fr; } "
                   "TopicWords Input { border: tall green; }")

    def __init__(self, bot, topic):
        super().__init__()
        self.bot, self.topic = bot, topic

    def compose(self):
        from .safety import BASE_WORDS, topic_words
        cur = topic_words(self.topic)
        words = list(dict.fromkeys(list(BASE_WORDS.get(self.topic, [])) + cur))
        with Vertical() as v:
            v.border_title = f"Topic {self.topic}: checked words get hidden"
            v.border_subtitle = "space toggle · tab switch box · ctrl+s save"
            yield SelectionList(*[(w, w, w in cur) for w in words], id="words")
            if self.topic == "x-flags":
                yield Static("[dim]These are flags X puts on posts: possibly_sensitive = marked sensitive by X, "
                             "withheld = blocked in some countries. Uncheck one to stop hiding posts X flags that way.[/]")
            else:
                yield Input(placeholder="add a word or phrase, then Enter", id="newword")

    def on_mount(self):
        self.query_one(SelectionList).focus()

    def action_swap(self):
        if not self.query(Input):
            return
        inp = self.query_one(Input)
        (self.query_one(SelectionList) if inp.has_focus else inp).focus()

    def on_input_submitted(self, event):
        w = event.value.strip().lower().strip(chr(34) + chr(39))
        event.input.value = ""
        if not w or self.topic == "x-flags":
            return
        sl = self.query_one(SelectionList)
        vals = [sl.get_option_at_index(i).value for i in range(sl.option_count)]
        if w in vals:
            sl.select(w)
        else:
            sl.add_option((w, w, True))

    def action_save(self):
        sl = self.query_one(SelectionList)
        sel = set(sl.selected)
        order = [sl.get_option_at_index(i).value for i in range(sl.option_count)]
        self.bot.set_topic_words(self.topic, [w for w in order if w in sel])
        self.dismiss(); self.app.refresh_ui()


class FilterOptions(EscModal):
    """'Posts like this' filters for one post: checked options are applied, then the post is hidden."""
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True), Binding("enter", "apply", "Apply", priority=True)]
    DEFAULT_CSS = ("FilterOptions { align: center middle; } FilterOptions > SelectionList { width: 64; height: 60%; "
                   "border: round magenta; background: $panel; }")

    def __init__(self, bot, n):
        super().__init__()
        self.bot, self.n = bot, n

    def compose(self):
        opts = self.bot.filter_options(self.bot.found_post(self.n))
        sl = SelectionList(*[(label, v, False) for v, label in opts])
        sl.border_title = f"Filter posts like #{self.n}: check what to hide"
        sl.border_subtitle = "space toggle · enter apply + hide post"
        yield sl

    def on_mount(self):
        self.query_one(SelectionList).focus()

    def action_cancel(self):
        """Esc: apply nothing, back one step (to the post card)."""
        self.dismiss("cancel")

    def action_apply(self):
        vals = list(self.query_one(SelectionList).selected)
        why = self.bot.apply_filter_options(vals) if vals else []
        self.bot.hide_post(self.n, forever=not why, why=why or None)
        self.dismiss(bool(why))


class MentionersEditor(EscModal):
    """Filtered mentioners: checked = their mentions are hidden. Tab to the box to add @handle; Enter/Ctrl+S saves."""
    BINDINGS = [Binding("escape", "dismiss", "Cancel"), Binding("ctrl+s", "save", "Save", priority=True),
                Binding("enter", "enter", "Save", priority=True), Binding("tab", "swap", "Switch box", priority=True)]
    DEFAULT_CSS = ("MentionersEditor { align: center middle; } MentionersEditor > Vertical { width: 64; height: 70%; "
                   "border: round magenta; background: $panel; } MentionersEditor SelectionList { height: 1fr; } "
                   "MentionersEditor Input { border: tall green; }")

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def compose(self):
        with Vertical() as v:
            v.border_title = "Filtered mentioners: checked = mentions hidden"
            v.border_subtitle = "space toggle · tab add box · enter/ctrl+s save"
            yield SelectionList(*[("@" + h, h, True) for h in self.bot.cfg.filtered_mentioners], id="ments")
            yield Input(placeholder="add @handle, then Enter", id="newment")

    def on_mount(self):
        self.query_one(SelectionList).focus()

    def action_swap(self):
        inp = self.query_one(Input)
        (self.query_one(SelectionList) if inp.has_focus else inp).focus()

    def _add(self, raw):
        import re
        h = raw.strip().lstrip("@").lower()
        if not re.fullmatch(r"\w{1,15}", h):
            if raw.strip():
                self.notify(f"not a valid handle: {raw.strip()}", severity="warning")
            return
        sl = self.query_one(SelectionList)
        vals = [sl.get_option_at_index(i).value for i in range(sl.option_count)]
        if h in vals:
            sl.select(h)
        else:
            sl.add_option(("@" + h, h, True))

    def action_enter(self):
        inp = self.query_one(Input)
        if inp.has_focus and inp.value.strip():
            self._add(inp.value); inp.value = ""; return
        self.action_save()

    def action_save(self):
        inp = self.query_one(Input)
        if inp.value.strip():
            self._add(inp.value); inp.value = ""
        sl = self.query_one(SelectionList)
        sel = set(sl.selected)
        order = [sl.get_option_at_index(i).value for i in range(sl.option_count)]
        self.bot.set_filtered_mentioners([h for h in order if h in sel])
        self.dismiss(); self.app.refresh_ui()


class HiddenPicker(EscModal):
    """Posts hidden by the filter and why. Enter opens it; a toggles last check / all."""
    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("a", "toggle_all", "Recent/all"),
                Binding("u", "unhide", "Stop filtering this word")]
    DEFAULT_CSS = ("HiddenPicker { align: center middle; } HiddenPicker > ListView { width: 95%; height: 85%; "
                   "border: round magenta; background: $panel; } HiddenPicker ListItem { padding: 0 1 1 1; }")

    def __init__(self, bot, all_=False):
        super().__init__()
        self.bot, self.all_ = bot, all_

    def compose(self):
        yield ListView(id="hidden")

    def on_mount(self):
        self.fill()

    def fill(self):
        from rich.markup import escape
        lv = self.query_one(ListView)
        lv.clear()
        items = self.bot.hidden_items(self.all_)
        self.items = items
        lv.border_title = f"Hidden by filter ({len(items)}) · " + ("all" if self.all_ else "last check")
        lv.border_subtitle = ("enter open · u restore / stop filtering that word · a " + ("last check only" if self.all_ else "show all")
                              + " · /filter show <topic> brings a group back")
        if not items:
            lv.append(ListItem(Label(Text.from_markup(
                "[dim]Nothing hidden" + ("" if self.all_ else " in the last check, press a to see all") + ".[/]"))))
        for i, (label, p, why) in enumerate(items):
            who = p.get("username") or p.get("author_id", "?")
            line = (f"[bold magenta]{escape(label)}[/]  [bold bright_cyan]@{escape(str(who))}[/]  "
                    f"{escape(clip(p.get('text', ''), 140))}\n"
                    f"   [dim]caught by:[/] [bold yellow]{escape('; '.join(why))}[/]")
            lv.append(ListItem(Label(Text.from_markup(line)), name=str(i)))
        if items:
            lv.index = 0
        lv.focus()

    def action_toggle_all(self):
        self.all_ = not self.all_
        self.fill()

    def action_unhide(self):
        """Stop filtering by the word(s) that caught the highlighted post, then refresh the list."""
        import re
        lv = self.query_one(ListView)
        item = lv.highlighted_child
        if item is None or item.name is None:
            return
        label, p, why = self.items[int(item.name)]
        if p.get("user_hidden") and label.startswith("#"):
            self.bot.unhide_post(int(label[1:])); self.fill(); self.app.refresh_ui(); return
        words = []
        for w in why:
            m = re.search(r'"([^"]+)"', w)
            if m:
                words.append(m.group(1).lower())
            elif w.startswith("tag "):
                self.bot.set_excluded(set(self.bot.cfg.excluded_tags) - {w[4:].strip()})
        for w in dict.fromkeys(words):
            try:
                self.bot.filter_cmd(f"show '{w}'" if "'" not in w else f'show "{w}"')
            except KeyError as e:
                self.bot.log.event("error", str(e))
        if not words and not any(w.startswith("tag ") for w in why):
            self.bot.log.event("info", f"{label}: caught by {'; '.join(why)}, which isn't a single word; use /filter show <topic>")
        self.fill(); self.app.refresh_ui()

    def on_list_view_selected(self, ev):
        if ev.item.name is None:
            return
        label, p, _ = self.items[int(ev.item.name)]
        if label.startswith("#"):
            self.dismiss(); self.app.action_show_post(int(label[1:]))
        else:
            open_url_async(f"https://x.com/i/status/{p['id']}", lambda how: None)
            self.bot.log.event("info", f"opened hidden post {label} in browser")


class SearchHistoryPicker(EscModal):
    """h: past searches (newest first). Enter/click picks one, Esc closes."""
    BINDINGS = [Binding("escape", "dismiss", "Close")]
    DEFAULT_CSS = ("SearchHistoryPicker { align: center middle; } SearchHistoryPicker > ListView { width: 80%; height: 70%; "
                   "border: round $accent; background: $panel; }")

    def __init__(self, bot):
        super().__init__()
        from . import search_history
        self.items = search_history.load(bot.state_dir)

    def compose(self):
        yield ListView(id="search-history")

    def on_mount(self):
        from rich.markup import escape
        lv = self.query_one(ListView)
        lv.border_title = f"Search history ({len(self.items)})"
        lv.border_subtitle = "enter/click use · esc close"
        if not self.items:
            lv.append(ListItem(Label(Text.from_markup("[dim]No searches yet. Use /search <query>.[/]"))))
        for i, q in enumerate(self.items):
            lv.append(ListItem(Label(escape(q)), name=str(i)))
        if self.items:
            lv.index = 0
        lv.focus()

    def on_list_view_selected(self, ev):
        ev.stop()
        if ev.item is not None and ev.item.name is not None:
            self.dismiss(self.items[int(ev.item.name)])


class FoundPicker(EscModal):
    BINDINGS = [("escape", "dismiss", "Close")]
    DEFAULT_CSS = ("FoundPicker { align: center middle; } FoundPicker > ListView { width: 90%; max-width: 160; height: 85%; "
                   "border: round cyan; background: $panel; } FoundPicker ListItem { padding: 0 1 1 1; width: 100%; } "
                   "FoundPicker ListItem Label { width: 100%; } "
                   "FoundPicker .hdr { padding: 1 1 1 1; }")

    def __init__(self, found):
        super().__init__()
        self.found = found

    def compose(self):
        from rich.markup import escape
        items = []
        for src, title, style in (("mention", "Mentions", "bright_magenta"), ("search", "Suggested replies", "blue")):
            grp = [(n, p) for n, p in self.found if p.get("source") == src]
            if not grp:
                continue
            items.append(ListItem(Label(Text.from_markup(f"[bold reverse {style}] {title} ({len(grp)}) [/]")),
                                  classes="hdr", disabled=True))
            for n, p in grp:
                who = p.get("username") or p.get("author_id", "?")
                tags = " ".join(f"[magenta]#{escape(t)}[/]" for t in p.get("tags", [])) or "[dim]no tags[/]"
                rep = "  [green]✓ replied[/]" if p.get("replied") else ""
                m = (p.get("public_metrics") or {})
                met = f"  [dim]♥ {m['like_count']}[/]" if "like_count" in m else ""
                txt = escape(clip(p["text"], 400))  # wraps to the full list width
                line = (f"[bold]#{n}[/]  [bold bright_cyan]@{escape(str(who))}[/]  {tags}{met}{rep}\n"
                        f"   {txt}")
                items.append(ListItem(Label(Text.from_markup(line)), name=str(n)))
        lv = ListView(*items, id="picker")
        lv.border_title = "Found posts"
        lv.border_subtitle = "[bold cyan]↑↓[/] move · [bold green]enter[/] open"
        yield lv

    def rebuild(self):
        """Posts were hidden: list only the visible ones again (or close when none are left)."""
        self.found = self.app.bot.feed_found()
        if not self.found:
            if self.app.screen is self:
                self.dismiss()
            elif getattr(self, "_close_tries", 0) < 20:
                self._close_tries = getattr(self, "_close_tries", 0) + 1
                self.app.call_after_refresh(self.rebuild)
            return
        self.refresh(recompose=True)

    def on_list_view_selected(self, ev):
        """Open the card on top of this list, so esc from the card comes back here (one step)."""
        self.app.action_show_post(int(ev.item.name))


SECRET_HINTS = ("xai-", "key=", "secret", "token=", "password", "bearer ")
FILTER_SUBS = ["hide", "show", "edit", "reset", "why", "mentioners", "on", "off"]


class QueueList(ListView):
    """Draft queue: a mouse click only focuses the pane and highlights the clicked draft (never opens it;
    `o` or Enter opens the highlighted draft's post). Clicks inside an open in-place editor (#qedit) stay
    with the editor."""

    def _on_list_item__child_clicked(self, event):
        event.stop(); event.prevent_default()
        ed = next(iter(event.item.query("#qedit")), None)
        if ed is not None:  # click in the open editor: keep editing
            if not ed.has_focus:
                ed.focus()
            return
        self.focus()
        try:
            self.index = self._nodes.index(event.item)
        except ValueError:
            pass


class QEdit(TextArea):
    """In-place reply editor inside the highlighted queue card (wraps, multi-line display).
    Enter or Ctrl+S saves, Esc cancels. `.value` aliases `.text` (same API as the old Input editor)."""
    BINDINGS = [Binding("enter", "save", "Save", priority=True), Binding("ctrl+s", "save", "Save", priority=True),
                Binding("escape", "cancel", "Cancel", priority=True)]
    DEFAULT_CSS = "QEdit { height: auto; min-height: 3; max-height: 14; border: round $accent; }"

    COMPONENT_CLASSES = set(TextArea.COMPONENT_CLASSES)  # keep TextArea's (gutter, cursor, selection, ...)

    def __init__(self, value="", **kw):
        super().__init__(value, soft_wrap=True, show_line_numbers=False, **kw)

    def get_component_rich_style(self, *names, partial=False, default=None):
        """Textual clears _component_styles when the editor is removed (save/cancel) but a frame already queued
        can still render it: TextAreaTheme.apply_css then raised KeyError 'text-area--gutter' and killed the app.
        Missing component styles fall back to a plain Style instead."""
        from rich.style import Style
        try:
            return super().get_component_rich_style(*names, partial=partial, default=default)
        except KeyError:
            return default if default is not None else Style()

    @property
    def value(self):
        return self.text

    @value.setter
    def value(self, v):
        self.text = v

    def action_save(self):
        self.app._qedit_save(self.text)

    def action_cancel(self):
        self.app._qedit_cancel()


class CmdInput(Input):
    """Main command line: Up/Down history (persisted), Tab completion."""
    BINDINGS = [Binding("up", "hist(-1)", "History", show=False), Binding("down", "hist(1)", "History", show=False),
                Binding("tab", "complete", "Complete", show=False)]
    HIST_CAP = 500

    def __init__(self, *a, history_path=None, **k):
        super().__init__(*a, **k)
        self.history_path = Path(history_path) if history_path else None
        self.history = []
        if self.history_path and self.history_path.exists():
            try:
                self.history = [l for l in self.history_path.read_text(encoding="utf-8").splitlines() if l][-self.HIST_CAP:]
            except OSError:
                pass
        self._hpos = None  # index into history while browsing; None = at bottom
        self._draft_line = ""

    @staticmethod
    def looks_secret(line):
        low = line.lower()
        return any(h in low for h in SECRET_HINTS)

    def remember(self, line):
        self._hpos = None
        line = line.strip()
        if not line or self.looks_secret(line) or (self.history and self.history[-1] == line):
            return
        self.history = (self.history + [line])[-self.HIST_CAP:]
        if self.history_path:
            try:
                self.history_path.parent.mkdir(parents=True, exist_ok=True)
                from .secure import write_private
                write_private(self.history_path, "\n".join(self.history) + "\n")
            except OSError:
                pass

    def action_hist(self, d):
        if not self.history:
            return
        if self._hpos is None:
            if d > 0:
                return
            self._draft_line = self.value
            self._hpos = len(self.history)
        self._hpos = max(0, self._hpos + d)
        if self._hpos >= len(self.history):
            self._hpos = None; self.value = self._draft_line
        else:
            self.value = self.history[self._hpos]
        self.cursor_position = len(self.value)

    def completions(self, text):
        """Return (completed_text, options) for the current input."""
        from .commands import COMMANDS
        from .safety import BASE_WORDS
        if not text.startswith("/"):
            return text, []
        if " " not in text:
            pre, pool, base = text[1:].lower(), sorted(COMMANDS), "/"
        else:
            head, _, rest = text.partition(" ")
            if head.lower() != "/filter":
                return text, []
            if rest.lower().startswith("edit ") and " " not in rest[5:]:
                pre, pool, base = rest[5:].lower(), sorted(BASE_WORDS), f"{head} edit "
            elif rest.lower().startswith("reset ") and " " not in rest[6:]:
                pre, pool, base = rest[6:].lower(), sorted(BASE_WORDS), f"{head} reset "
            elif " " not in rest:
                pre, pool, base = rest.lower(), FILTER_SUBS, f"{head} "
            else:
                return text, []
        opts = [c for c in pool if c.startswith(pre)]
        if len(opts) == 1:
            return base + opts[0] + " ", opts
        if opts:
            import os.path
            return base + os.path.commonprefix(opts), opts
        return text, []

    def action_complete(self):
        new, opts = self.completions(self.value)
        self.value = new; self.cursor_position = len(new)
        app = self.app
        if len(opts) > 1 and getattr(app, "bot", None):
            app.bot.log.event("info", "tab: " + "  ".join(opts))


class FeedLog(RichLog):
    """RichLog that wraps at its real width: keeps the written renderables and re-wraps them when its width changes."""
    KEEP = 2000

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._items, self._posts, self._wrapped_at = [], [], None
        from .config import FEED_MAX
        self.max_posts = FEED_MAX  # post lines kept in the feed; the oldest drop off as new ones arrive

    def _drop_oldest_posts(self):
        """More than max_posts post lines: drop the oldest ones and redraw the kept lines."""
        extra = sum(self._posts) - self.max_posts
        keep_i, keep_p = [], []
        for it, p in zip(self._items, self._posts):
            if p and extra > 0:
                extra -= 1; continue
            keep_i.append(it); keep_p.append(p)
        self._items, self._posts = keep_i, keep_p
        self._redraw()

    def _redraw(self):
        w = self.scrollable_content_region.width if self._size_known else 0
        items, end = list(self._items), self.is_vertical_scroll_end
        super().clear()
        self._rewrapping = True
        try:
            for it in items:
                super().write(it, scroll_end=False, **({"width": w} if w > 0 else {}))
        finally:
            self._rewrapping = False
        if end:
            self.scroll_end(animate=False)
        return self

    def write(self, content, *a, post=False, **k):
        if not getattr(self, "_rewrapping", False):
            self._items.append(content); self._posts.append(post)
            self._items, self._posts = self._items[-self.KEEP:], self._posts[-self.KEEP:]
            if post and sum(self._posts) > self.max_posts > 0:
                return self._drop_oldest_posts()
            w = self.scrollable_content_region.width
            if self._size_known and w > 0 and not a and "width" not in k:
                k["width"] = w  # wrap at the pane's real width (not the 80-col default measure)
        return super().write(content, *a, **k)

    def clear(self):
        self._items, self._posts = [], []
        return super().clear()

    def on_resize(self, ev):
        w = self.scrollable_content_region.width
        if w and w != self._wrapped_at:
            self._wrapped_at = w
            items, end = list(self._items), self.is_vertical_scroll_end
            super().clear()
            self._rewrapping = True
            try:
                for it in items:
                    super().write(it, width=w, scroll_end=False)
            finally:
                self._rewrapping = False
            if end:
                self.scroll_end(animate=False)


class XBotApp(App):
    CSS = """
    #feed { width: 2fr; border: round green; overflow-x: hidden; }
    #drafts { width: 1fr; border: round yellow; }
    #queue { height: auto; max-height: 100%; }
    #queue ListItem { padding: 0 1 1 1; }
    #queue ListItem Label { width: 100%; }
    #queue ListItem .qfull, #queue ListItem .qreply { display: none; }
    #queue ListItem.-highlight .qcompact { display: none; }
    #queue ListItem.-highlight .qfull, #queue ListItem.-highlight .qreply { display: block; }
    #queue ListItem.editing .qreply { display: none; }
    #queue .qhdr { opacity: 100%; }
    #queue .qhdr { padding: 1 0 0 0; }
    #queue-empty { color: $text-muted; padding: 1; }
    #status { height: 1; background: $boost; }
    #main { height: 1fr; }
    #left { width: 2fr; }
    #left > #feed { width: 100%; height: 1fr; }
    #console-box { height: 24; max-height: 45%; min-height: 6; border: round $accent; }
    #console-box.hidden { display: none; }
    #console { height: 1fr; overflow-x: hidden; }
    """
    BINDINGS = [("a", "approve", "Approve"), ("r", "reject", "Reject"), ("e", "edit", "Edit"),
                ("m", "mentioners", "Mentioners list"), ("o", "open_queued", "Open post"),
                Binding("x", "clear_suggested", "Clear suggested", show=False), Binding("X", "clear_mentions", "Clear mentions", show=False),
                ("p", "toggle_pause", "Pause/Resume"), ("f", "found", "Found posts"), ("h", "search_history", "Search history"),
                Binding("f3", "toggle_console", "Console"),
                Binding("slash", "slash", "Command", show=False),
                Binding("f5", "tick", "Refresh feed + catalog"), Binding("f2", "filter_view", "Filters"), Binding("f6", "switch_focus", "Switch pane"),
                Binding("ctrl+c", "quit", "Quit", priority=True), Binding("ctrl+q", "quit", "Quit", priority=True)]

    def __init__(self, bot=None, autostart=True):
        super().__init__()
        self.bot = bot
        self.autostart = autostart
        self._editing = None
        self._edge_last = -1e9

    EDGE_NOTIFY_EVERY = 10.0  # seconds between "first/last post" toasts

    def edge_notify(self, msg, now=None):
        """At most one first/last-post toast per 10 s, however often the arrow is pressed."""
        import time
        now = time.monotonic() if now is None else now
        if now - self._edge_last < self.EDGE_NOTIFY_EVERY:
            return False
        self._edge_last = now
        self.notify(msg, timeout=1.5)
        return True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                feed = FeedLog(id="feed", wrap=True, markup=False, highlight=False, min_width=20)
                feed.border_title = "X posts"
                yield feed
                with Vertical(id="console-box") as cb:
                    cb.border_title = "Console"
                    cb.border_subtitle = "F3 hide · / type a command"
                    yield FeedLog(id="console", wrap=True, markup=False, highlight=False, min_width=20)
                    hp = (Path(self.bot.log.dir) / "history.txt") if self.bot is not None else None
                    yield CmdInput(placeholder="/help  |  /post text  |  ↑↓ history  |  Tab completes", id="cmd", history_path=hp)
            with Vertical(id="drafts"):
                yield Static("", id="queue-empty")
                yield QueueList(id="queue")
        yield Static(id="status")
        yield Footer()

    FEED_KINDS = ("found",)

    def _ui(self, fn, *a):
        """Run a widget mutation on the Textual loop thread (direct when already there or app not running)."""
        if not self.is_running or getattr(self, "_thread_id", None) in (None, threading.get_ident()):
            return fn(*a)
        try:
            return self.call_from_thread(fn, *a)
        except RuntimeError:  # loop shutting down
            return None

    def _route(self, rec):
        """X posts go to the top feed; everything else (output, errors, /help) to the console (thread-safe)."""
        if self.is_running and getattr(self, "_thread_id", None) not in (None, threading.get_ident()):
            return self._ui(self._route, rec)
        w = self._feed_log if rec.get("kind") in self.FEED_KINDS else self._console_log
        if w is self._feed_log and isinstance(w, FeedLog):
            w.write(feed_text(rec), post=rec.get("kind") == "found" and bool(rec.get("tweet_id")))
        else:
            w.write(feed_text(rec))

    @property
    def console_visible(self):
        return not self._base().query_one("#console-box").has_class("hidden")

    def show_console(self, show=True):
        base = self._base()
        base.query_one("#console-box").set_class(not show, "hidden")
        inp = base.query_one("#cmd", Input)
        if show:
            inp.focus()
        elif inp.has_focus or self.focused is None:
            base.query_one("#queue", ListView).focus()

    def _base(self):
        """Main screen, even while a modal is on top."""
        return self.screen_stack[0] if self.screen_stack else self.screen

    def action_toggle_console(self):
        self.show_console(not self.console_visible)

    def action_slash(self):
        """'/' while not typing: show the console (if hidden) and start a command."""
        if not self._not_typing():
            return
        self.show_console(True)
        inp = self.query_one("#cmd", Input)
        inp.value = "/"; inp.cursor_position = 1

    def on_mount(self):
        self.title = "xbot - Grok X console"
        self._feed_log = self.query_one("#feed", RichLog)
        feed = self._console_log = self.query_one("#console", RichLog)
        if self.bot is None:
            from .bot import Bot
            from .llm import GrokLLM, LLMFatal
            warns = load_env_file()
            cfg = Config.load()
            log = ActionLog(sink=lambda t: self._ui(feed.write, t))
            log.rich_sink = self._route
            for w in warns: log.event("warn", w)
            if cfg.load_error: log.event("error", cfg.load_error)
            for w in cfg.load_warnings: log.event("warn", w)
            def llm_factory():
                load_env_file()  # pick up a key added to ~/.config/xbot/env while running
                return GrokLLM(self.bot.cfg.model if self.bot else cfg.model, cfg.base_url)
            try:
                llm = llm_factory()
            except LLMFatal:
                llm = None  # X-only mode
            self.bot = Bot(cfg, llm, DryRunX(), log, real_x_factory=RealX, save_config=cfg.save,
                           llm_factory=llm_factory)
        else:
            self.bot.log.sink = lambda t: self._ui(feed.write, t)
            self.bot.log.rich_sink = self._route
        self.bot.on_clear_feed = lambda: self._ui(self._on_clear_feed)
        self.bot.on_limit_exit = self._limit_exit
        if getattr(self.bot, "limit_exit", None):
            self._limit_exit(self.bot.limit_exit)
        if __import__("os").environ.get("XAI_MANAGEMENT_KEY"):
            from .credits import REFRESH_S
            self._credits_refresh(); self.set_interval(REFRESH_S, self._credits_refresh)
        if self.bot.opener is None:
            self.bot.opener = lambda url, done: open_url_async(url, lambda m: self.call_from_thread(done, m))
        self.bot.replay_found()
        self.bot.log.event("ctl", "started. " + self.bot.status() + "  (/help for commands)")
        self.refresh_ui()
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: self.call_later(self.action_quit))
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        if self.autostart:
            self.run_worker(self.loop(), exclusive=True)

    async def loop(self):
        # startup: exactly one mention check + one search
        await self._safe(self.bot.tick, True)
        self.bot.log.event("info", "startup check done; use /tick to check again")
        self.refresh_ui()
        last = None
        while not self.bot.stopped:  # X checks only on F5; Grok drafting keeps filling free slots in the background
            await asyncio.sleep(1)
            b = self.bot
            if b.wants_drafting() and not b.rate_limited():
                if await self._safe(b.refill_from_catalog):
                    self.refresh_ui(); last = None
            title = drafts_title(b)
            if title != last:  # cheap: only the queue title ("drafting… next in Ns")
                last = title
                try:
                    self.query_one("#drafts").border_title = title
                except Exception:
                    pass
        self.shutdown(); self.exit()

    async def _safe(self, fn, *a):
        """Run a bot call in a thread; log a one-line warning instead of crashing the worker."""
        try:
            return await asyncio.to_thread(fn, *a)
        except Exception as e:
            self.bot.log.event("warn", f"{getattr(fn, '__name__', 'check')} failed: {type(e).__name__}: {str(e)[:120]}; try F5 again")

    REFILL_MIN = 20

    def apply_filters_and_refill(self):
        self.bot.prune_prefill()
        vis = [p for _, p in self.bot.visible_found() if p.get("source") != "mention"]
        hid = sum(1 for p in self.bot.found if self.bot.hidden(p))
        self.bot.log.event("info", f"filters applied: {len(vis)} suggestions showing, {hid} hidden")
        self.refresh_ui()
        if len(vis) < self.REFILL_MIN:
            self.bot.log.event("info", f"under {self.REFILL_MIN} suggestions, searching for more…")

            async def go():
                await self._safe(self.bot.tick, True)
                self.refresh_ui()
            self.run_worker(go(), group="refill", exclusive=True)

    def refresh_ui(self):
        if not self.is_running:
            return
        self.run_worker(self._refresh(), group="ui", exclusive=True)

    async def _refresh(self):
        lv = self.query_one("#queue", ListView)
        idx = lv.index
        await lv.clear()
        await lv.extend(self._queue_items())
        if lv.children:
            i = min(idx or 0, len(lv.children) - 1)
            while i < len(lv.children) - 1 and lv.children[i].disabled:
                i += 1
            lv.index = i
        box = self.query_one("#drafts")
        box.border_title = drafts_title(self.bot)
        box.border_subtitle = "o open · a approve · e edit · r reject · m mentioners · x clear suggested · X clear mentions"
        ph = self.query_one("#queue-empty", Static)
        ph.update(drafts_placeholder(self.bot))
        ph.display = not self.bot.queue.pending()
        self.query_one("#status", Static).update(Text.from_markup(status_markup(self.bot)))

    def _queue_items(self):
        """Drafts panel: Mentions then Suggested replies sections, each draft a spaced block."""
        from rich.markup import escape
        by_id = {p["id"]: (n, p) for n, p in enumerate(self.bot.found, 1)}
        pend = self.bot.queue.pending()
        out = []
        for src, title, style in (("mention", "Mentions", "bright_magenta"), (None, "Suggested replies", "blue")):
            grp = [d for d in pend if (d.source == "mention") == (src == "mention")]
            if not grp:
                continue
            w = len(self.bot.mentions_waiting()) if src == "mention" else len(self.bot.search_catalog())
            cnt = f"{len(grp)} shown · {w} waiting" if w else f"{len(grp)}"
            out.append(ListItem(Label(Text.from_markup(f"[bold reverse {style}] {title} ({cnt}) [/]")),
                                classes="qhdr", disabled=True))
            for pos, d in enumerate(grp, 1):
                n, p = by_id.get(d.in_reply_to, (None, {}))
                who = p.get("username") or p.get("author_id")
                head = f"[bold]{pos}[/]  [{style}]{escape(d.source)} {escape(d.kind)}[/]"
                if who:
                    head += f"  [dim]to[/] [bold bright_cyan]@{escape(str(who))}[/]"
                if n:
                    head += f"  [dim]post #{n}[/]"
                compact, full = [head], [head]
                if d.context:
                    compact.append(f"[dim]re:[/] [grey62]{escape(clip(d.context, 90))}[/]")
                    full.append(f"[dim]re:[/] [grey70]{escape(d.context)}[/]")
                compact.append(f"[bold green]›[/] {escape(clip(d.text, 140))}")
                # selected card expands (CSS on -highlight): full post text + full reply; `e` edits the reply in place
                out.append(ListItem(Label(Text.from_markup("\n".join(compact)), classes="qcompact"),
                                    Label(Text.from_markup("\n".join(full)), classes="qfull"),
                                    Label(Text.from_markup(f"[bold green]›[/] {escape(d.text)}"), classes="qreply"),
                                    name=str(d.id)))
        return out

    def _selected(self):
        lv = self.query_one("#queue", ListView)
        item = lv.highlighted_child
        return int(item.name) if item is not None and item.name else None

    def _run(self, line):
        try:
            c = parse(line)
            if c.name == "topics":
                self.push_screen(TagPicker(self.bot)); return
            if c.name == "mentioners":
                self.push_screen(MentionersEditor(self.bot)); return
            if c.name == "hidden":
                self.push_screen(HiddenPicker(self.bot, all_=(c.text or "").strip().lower() == "all")); return
            if c.name == "filter":
                from .safety import ALL_TOPICS
                fa = (c.text or "").split()
                if fa and fa[0].lower() in ("mentioners", "mentions"):
                    self.push_screen(MentionersEditor(self.bot)); return
                if fa and fa[0].lower() == "edit":
                    if len(fa) == 1:
                        self.push_screen(TopicPicker(self.bot)); return
                    if len(fa) == 2 and fa[1].lower() in ALL_TOPICS:
                        self.push_screen(TopicWords(self.bot, fa[1].lower())); return
            if c.name == "show":
                self.bot.found_post(c.args[0]); self.action_show_post(c.args[0]); return
            if c.name == "tick" and self.is_running:
                # /tick (F5) hits X and Grok (sync HTTP, up to 60s per call): never on the event loop
                self._tick_in_thread(c); return
            self.bot.handle(c)
        except (CommandError, KeyError, ValueError) as e:
            self.bot.log.event("error", f"{line!r}: {e}")
        except Exception as e:  # never crash the TUI (e.g. network error escaping a command)
            self.bot.log.event("warn", f"{line.split()[0]} failed: {type(e).__name__}: {str(e)[:120]}; try again")
        if self.bot.stopped:
            self.shutdown(); self.exit()
        self.refresh_ui()

    def _tick_in_thread(self, c):
        if getattr(self, "_tick_running", False):
            self.notify("check already running…", timeout=2); return
        self._tick_running = True
        self.bot.log.event("info", "refreshing (F5)…")

        async def go():
            try:
                await asyncio.to_thread(self.bot.handle, c)
            except (CommandError, KeyError, ValueError) as e:
                self.bot.log.event("error", f"/tick: {e}")
            except Exception as e:  # never crash the TUI (network error escaping a check)
                self.bot.log.event("warn", f"/tick failed: {type(e).__name__}: {str(e)[:120]}; try again")
            finally:
                self._tick_running = False
            if self.bot.stopped:
                self.shutdown(); self.exit(); return
            self.refresh_ui()
        self.run_worker(go(), group="tick", exclusive=True)
        self.refresh_ui()

    def on_list_view_selected(self, ev):
        """Click/Enter on a queue draft = click its post's #n in the feed (opens the post card)."""
        if ev.list_view.id != "queue" or not ev.item.name or self._editing is not None:
            return
        n = self.post_number_for_draft(int(ev.item.name))
        if n:
            self.action_show_post(n)

    def post_number_for_draft(self, did):
        d = self.bot.queue.get(did)
        for n, p in enumerate(self.bot.found, 1):
            if d.in_reply_to and str(p["id"]) == str(d.in_reply_to):
                return n
        return None

    def on_input_submitted(self, ev: Input.Submitted):
        if ev.input.id == "qedit":
            ev.stop()
            did, self._editing = self._editing, None
            val = ev.value.strip()
            self._drop_qedit()
            if did is not None and val:
                self._run(f"/edit @{did} {val}")
            else:
                self.refresh_ui()
            self.query_one("#queue", ListView).focus()
            return
        val = ev.value.strip()
        ev.input.value = ""
        if self._editing is not None:
            did, self._editing = self._editing, None
            if val:
                self._run(f"/edit @{did} {val}")
            ev.input.placeholder = "/help"
            return
        if val:
            if isinstance(ev.input, CmdInput):
                ev.input.remember(val)
            self._run(val)

    def action_open_post(self, n):
        self._run(f"/open {int(n)}")

    def action_open_profile(self, n):
        try:
            self.bot.open_profile(int(n))
        except KeyError as e:
            self.bot.log.event("error", str(e))

    def action_open_media(self, n):
        """Click on [media]: the same in-terminal mpv viewer as v (never the browser)."""
        try:
            self.bot.found_post(int(n))
        except KeyError as e:
            self.bot.log.event("error", str(e)); return
        # Never suspend from inside the click handler: Textual is mid mouse-event / mid-repaint of the hovered
        # link, so mpv started there saw a half-restored terminal (wrong sixel box: frame clipped to the top-left,
        # not centred). Run the exact same path as v once the event is done and the screen has repainted.
        n = int(n)
        self.set_timer(0.15, lambda: self.guarded("view media", self.play_media, n))

    def guarded(self, what, fn, *a):
        """Run a media action; any failure goes to crash.log plus a one-line notice, never exits the app."""
        try:
            return fn(*a)
        except Exception as e:
            line = _crash_log(e)
            try:
                self.bot.log.event("error", f"{what} failed: {line}")
                self.notify(f"{what} failed: {type(e).__name__} (see crash.log)", severity="error", timeout=5)
            except Exception:
                pass
            return None

    def _handle_exception(self, error):
        """Unhandled Textual errors: write crash.log first (Textual alone only prints to the terminal on exit)."""
        try:
            self._crash_line = _crash_log(error)
        except Exception:
            pass
        super()._handle_exception(error)

    def viewer_actions(self, st):
        """r / t inside the mpv viewer (see video.PostActions). r runs on a worker thread while Textual is
        suspended (log records are buffered, see play_media); t records a popup request in st and mpv quits."""
        bot = self.bot
        def remove(it):
            p = bot.found_post(it["n"]); h = (p.get("username") or "").lower()
            if not h:
                raise KeyError("author unknown")
            ok = bot.mute(h, author_id=p.get("author_id"))
            bot.hide_post(it["n"], forever=True); st["changed"] = True
            return (f"@{h} muted" + (" (send=dry: logged, blocked locally)" if bot.cfg.dry_run
                                     else "" if ok is not False else " (X failed: blocked locally)") + ", post hidden")
        def popup(it, pos):
            st["popup"] = {"n": it["n"], "sub": it.get("sub") or 1}
        def log(msg):
            bot.log.event("info", msg)
        return {"remove": remove, "popup": popup, "log": log}

    def _viewer_popup(self, req, which=None, run=None):
        """t in the viewer: mpv has quit and Textual is back; show the card's filter popup for the post. Apply ->
        (filters applied + post hidden in FilterOptions) reopen at the next post with media; Esc -> same item."""
        n, sub = req["n"], req["sub"]
        order = list(self.bot.nav_order())
        origin = list(req.get("origin") or order)
        def after(r):
            if r == "cancel":
                self.bot.log.event("info", f"viewer t: cancelled, back to #{n} item {sub}")
                self._reopen_viewer(n, which, run, sub, origin); return
            self.bot.log.event("info", f"viewer t: filter applied to #{n}, post hidden")
            try:
                self.refresh_ui(); self.apply_filters_and_refill()
            except Exception as e:
                _crash_log(e)
            later = order[order.index(n) + 1:] if n in order else []
            nxt = next((k for k in later if k in self.bot.nav_order() and self.bot.found_post(k).get("media")), None)
            if nxt is None:
                self.notify("no more posts with media", timeout=3)
                self.resync_after_hide(origin); return
            self._reopen_viewer(nxt, which, run, 1, origin)
        self.push_screen(FilterOptions(self.bot, n), after)

    def resync_after_hide(self, old_order, prefer=None):
        """After posts were hidden: rebuild every open found-posts list and move the post card to the right
        post (prefer = the one the viewer last showed); the feed/queue panes come from refresh_ui."""
        scr = self.screen
        if isinstance(scr, PostCard):
            scr.resync(old_order, prefer)
        def lists():
            for s in list(self.screen_stack):
                if isinstance(s, FoundPicker):
                    try:
                        s.rebuild()
                    except Exception as e:
                        _crash_log(e)
        self.call_after_refresh(lists)  # after a closing card is gone, so an empty list can close too

    def _reopen_viewer(self, n, which, run, sub, origin=None):
        """Reopen after the popup only once the modal is gone and Textual has repainted (never suspend
        from inside the dismiss callback, while the driver is mid-resume)."""
        self.set_timer(0.15, lambda: self.play_media(n, which=which, run=run, start_sub=sub, origin=origin))

    def like_once(self, n):
        """Blocking: like found post #n via the API unless already liked. Marks first, rolls back on failure.
        Returns (ok, one-line message). Safe from worker threads (card) and the mpv IPC thread."""
        b = self.bot; st = b.state
        pid = str(b.found_post(n)["id"])
        lock = self.__dict__.setdefault("_like_lock", __import__("threading").Lock())
        with lock:
            if pid in st.liked:
                return True, "already liked"
            st.liked.append(pid); st.save()
        ok, msg = b.like_post(n)
        if not ok:
            with lock:
                if pid in st.liked:
                    st.liked.remove(pid); st.save()
            b.log.event("warn", msg)
        return ok, msg

    def _on_clear_feed(self):
        self._feed_log.clear()
        self.notify("feed cleared · drafting paused until F5", timeout=4)
        self.refresh_ui()

    def play_media(self, n, which=None, run=None, start_sub=1, origin=None):
        """Suspend Textual, show all of post #n's media in mpv in this terminal (A/D browse, q/Esc returns),
        then resume on the same post. Never falls back to a browser or external player."""
        import shutil, subprocess
        from . import video
        which = which or shutil.which
        if not which("mpv"):
            self.notify("mpv not found: install mpv to view media in the terminal", severity="warning", timeout=5)
            self.bot.log.event("info", "mpv not found: install mpv to view photos/videos in the terminal"); return "missing"
        try:
            media = self.bot.media_items(n)  # HEAD check / 403 refetch: never fatal
        except Exception as e:
            _crash_log(e); media = self.bot.found_post(n).get("media") or []
        if not any(m.get("url") for m in media):
            self.notify("no direct media URL on this post", timeout=3)
            self.bot.log.event("info", f"#{n}: no direct media URL to show"); return None
        order = [k for k in self.bot.nav_order()] or [n]
        if n not in order:
            order = [n]
        posts = [(k, self.bot.found_post(k)) for k in order]
        st = {}
        log = self.bot.log
        sink, held = log.rich_sink, []
        log.rich_sink = held.append  # no widget writes from viewer threads while Textual is suspended
        try:
            with self.suspend():
                res = video.run_mpv(None, self.bot.cfg, run=run or subprocess.run, which=which, posts=posts, start_n=n,
                                    start_sub=start_sub, state=st, on_like=lambda it: self.like_once(it["n"])[1],
                                    liked=lambda it=None: bool(it) and it.get("post_id") in self.bot.state.liked,
                                    actions=self.viewer_actions(st))
        except Exception as e:  # SuspendNotSupported (e.g. headless) or mpv failure
            self.bot.log.event("warn", f"in-terminal media viewer failed ({type(e).__name__})")
            self.notify(f"media viewer failed: {type(e).__name__}", severity="error", timeout=5); return "failed"
        finally:
            log.rich_sink = sink
            for rec in held:
                try:
                    log._emit(rec)
                except Exception:
                    pass
        if st.get("rc") not in (0, None):
            self.bot.log.event("warn", f"mpv exited with code {st['rc']} (1 init error, 2 file/stream error, 4 signal)")
        try:
            self.screen.refresh(repaint=True, layout=True)
        except Exception:
            pass
        last = (st.get("last") or {}).get("n")
        scr = self.screen
        if st.get("changed"):  # r in the viewer muted + hid posts: they leave the current results
            try:
                self.refresh_ui(); self.apply_filters_and_refill()
            except Exception as e:
                _crash_log(e)
        base = origin or order  # after a t-popup reopen: the list as it was before the first hide
        vis = set(self.bot.nav_order())
        stale = isinstance(scr, PostCard) and scr.n not in vis
        if (set(base) - vis or stale) and not st.get("popup"):
            self.resync_after_hide(base, prefer=last)
        elif last and last != n and isinstance(scr, PostCard) and scr.n == n:  # card follows the post last viewed
            scr.n, scr.post = last, self.bot.found_post(last)
            scr._redraw(); scr._lookup()
        self.refresh(repaint=True, layout=True); self.screen.refresh(repaint=True, layout=True)
        if st.get("popup"):
            st["popup"]["origin"] = base
            self._viewer_popup(st["popup"], which=which, run=run)
        return res

    def action_switch_focus(self):
        inp = self.query_one("#cmd", Input)
        if inp.has_focus:
            self.query_one("#queue", ListView).focus()
        else:
            self.show_console(True)

    def action_show_post(self, n):
        try:
            p = self.bot.found_post(int(n))
        except KeyError as e:
            self.bot.log.event("error", str(e)); return
        self.push_screen(PostCard(int(n), p))

    def action_found(self):
        if self._not_typing():
            self.push_screen(FoundPicker(self.bot.feed_found()))

    def _fatal_error(self):
        """Unhandled exception: full traceback to crash.log, one clean line on exit (no rich traceback)."""
        if getattr(self, "_cli_mode", False) and self._exception is not None:
            self._crash_line = _crash_log(self._exception)
            self._close_messages_no_wait()
            return
        super()._fatal_error()

    def _credits_refresh(self):
        """Fetch the real xAI prepaid balance in a thread (key never logged; errors are redacted)."""
        if getattr(self, "_credits_denied", False):
            return  # 401/403 earlier this session: never retried
        def work():
            import time as _t
            from .credits import fetch_balance, BalanceDenied
            usd, err = fetch_balance()
            if isinstance(err, BalanceDenied):
                self._credits_denied = True
                self.bot.credit_note = str(err)
                self.bot.log.event("info", f"xAI credits: {err} (HTTP {err.code} on the {err.step} call; not retried this session)")
            elif usd is not None:
                self.bot.credit_balance = (usd, _t.time())
            elif err and err != getattr(self, "_credits_err", None):
                self._credits_err = err
                from .config import redact
                self.bot.log.event("warn", "xAI credits: " + redact(err))
            try:
                self.call_from_thread(self.refresh_ui)
            except Exception:
                pass
        self.run_worker(work, thread=True, group="credits", exclusive=True)

    def _limit_exit(self, msg):
        """Spend limit reached (bot already reset + saved the counter): save everything and leave the TUI."""
        self._limit_msg = msg
        def go():
            self.shutdown(); self.exit()
        import threading
        if getattr(self, "_thread_id", None) == threading.get_ident() or not self.is_running:
            go()
        else:
            try:
                self.call_from_thread(go)
            except RuntimeError:
                go()

    def shutdown(self):
        """Persist queue/state and log stop. Safe to call more than once."""
        if getattr(self, "_shut", False) or self.bot is None:
            return
        self._shut = True
        self.bot.stopped = True
        try:
            self.bot.queue._save()
            self.bot.state.save()
            self._session_line = self.bot.end_session()
        finally:
            self.bot.log.event("ctl", "stopped (queue/state saved)")

    async def action_quit(self):
        self.shutdown()
        self.exit()

    def on_unmount(self):
        self.shutdown()

    def _not_typing(self):
        return not isinstance(self.focused, (Input, TextArea))

    def action_approve(self):
        if self._not_typing() and (d := self._selected()):
            dr = self.bot.queue.get(d)
            browser = dr.kind == "reply" and dr.in_reply_to and not self.bot._is_mention_target(dr)
            self._run(f"/approve @{d}")
            if browser:
                self.notify("Opened in browser: add your own flavor before posting.", timeout=4)
            elif dr.kind == "reply":
                self.notify("Mention reply sent via the API (" + ("dry run" if self.bot.cfg.dry_run else "LIVE") + ").", timeout=4)

    def action_open_queued(self):
        """o in the queue: open the highlighted draft's post (its card), what a click used to do."""
        if not self._not_typing() or not self.query_one("#queue", ListView).has_focus:
            return
        d = self._selected()
        if d is None or self._editing is not None:
            return
        n = self.post_number_for_draft(d)
        if n:
            self.action_show_post(n)
        else:
            self.notify("no post for this draft (original post)", timeout=2)

    def action_reject(self):
        if self._not_typing() and (d := self._selected()): self._run(f"/reject @{d}")

    def action_search_history(self):
        """h while not typing: pick a past search; Enter fills the input with /search <query>."""
        if not self._not_typing():
            return
        def done(q):
            if not q:
                return
            self.show_console(True)
            inp = self.query_one("#cmd", Input)
            inp.value = f"/search {q}"; inp.cursor_position = len(inp.value); inp.focus()
        self.push_screen(SearchHistoryPicker(self.bot), done)

    def action_tick(self):
        self._run("/tick")

    def action_filter_view(self):
        self._run("/filter")

    def _clear(self, src, label):
        if not self._not_typing():
            return
        n = sum(1 for d in self.bot.queue.pending() if (d.source == "mention") == (src == "mentions"))
        if not n:
            self.notify(f"no pending {label} drafts"); return
        self.push_screen(Confirm(f"Clear all {n} pending {label} drafts? y/n\n(posts stay in the feed)"),
                         lambda ok: ok and self._run(f"/clear {src}"))

    def action_clear_suggested(self):
        self._clear("suggested", "suggested")

    def action_clear_mentions(self):
        self._clear("mentions", "mention")

    def action_mentioners(self):
        if self._not_typing():
            self.push_screen(MentionersEditor(self.bot))

    def action_toggle_pause(self):
        if self._not_typing(): self._run("/resume" if self.bot.paused else "/pause")

    async def action_edit(self):
        """e: edit the highlighted draft in place, inside its queue item (Enter saves, Esc to back)."""
        if not self._not_typing() or not (d := self._selected()): return
        item = self.query_one("#queue", ListView).highlighted_child
        if item is None: return
        old = list(self.query("#qedit"))
        if self._editing == d and old and old[0].parent is item:
            old[0].focus(); return  # e again on the same draft: keep the open editor
        await self._drop_qedit()  # never two Input#qedit (DuplicateIds): an editor left open on another draft/list
        self._editing = d
        inp = QEdit(self.bot.queue.get(d).text, id="qedit")
        inp.border_subtitle = f"editing #{d} · enter/ctrl+s save · esc cancel"
        item.add_class("editing")
        await item.mount(inp)
        inp.move_cursor(inp.document.end)
        inp.focus()

    def _qedit_save(self, text):
        did, self._editing = self._editing, None
        val = " ".join(text.split()) if "\n" not in text.strip() else text.strip()
        self._drop_qedit()
        if did is not None and val:
            self._run(f"/edit @{did} {val}")
        else:
            self.refresh_ui()
        self.query_one("#queue", ListView).focus()

    def _qedit_cancel(self):
        self._editing = None
        self._drop_qedit()
        self.refresh_ui()
        self.query_one("#queue", ListView).focus()

    def _drop_qedit(self):
        """Remove every on-demand draft editor (Esc, Enter, before mounting a new one). Returns an awaitable
        that completes once they are gone (so a new Input#qedit can't collide with the old one)."""
        for it in self.query("ListItem.editing"):
            it.remove_class("editing")
        return self.query("#qedit").remove()

    def on_key(self, ev):
        if ev.key == "escape" and isinstance(self.focused, Input) and self.focused.id == "qedit":
            ev.stop()
            self._editing = None
            self._drop_qedit()
            self.refresh_ui()
            self.query_one("#queue", ListView).focus()


CLI_SUBCOMMANDS = ("login", "sample", "fix-perms", "secrets", "config", "search")
USAGE = """usage: xbot [--insecure-perms] [command] [args]

With no command, starts the terminal UI (X feed, Grok drafts, reply queue).

commands:
  help, -h, --help     show this help and exit
  login                X OAuth 2.0 login (bookmarks/likes scopes)
  config [key value]   show or set config (~/.config/xbot/config.json)
  secrets ...          edit keys in ~/.config/xbot/env
  search ...           one-off X search in the terminal (see `xbot search --help`)
  sample ...           demo with sample data (no keys, no network)
  fix-perms            tighten permissions on ~/.config/xbot and ~/.local/state/xbot

options:
  --insecure-perms     start even if the env file permissions are too open

Inside the UI, type /help for commands."""


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help", "help"):  # before anything touches config, state, network or the TUI
        print(USAGE); raise SystemExit(0)
    if argv and argv[0].startswith("-") and argv[0] != "--insecure-perms" or argv and not argv[0].startswith("-") \
            and argv[0] not in CLI_SUBCOMMANDS:
        print(f"xbot: unknown argument {argv[0]!r}\n\n{USAGE}", file=sys.stderr); raise SystemExit(2)
    from . import secure
    from .config import CONFIG_DIR, STATE_DIR
    secure.install()
    insecure = "--insecure-perms" in argv
    argv = [a for a in argv if a != "--insecure-perms"]
    if argv and argv[0] == "login":
        load_env_file()
        from .oauth2 import login
        raise SystemExit(login())
    if argv and argv[0] == "sample":  # demo: before anything touches ~/.config/xbot or ~/.local/state/xbot
        from .sample import cli
        raise SystemExit(cli(argv[1:]))
    if argv and argv[0] == "fix-perms":
        raise SystemExit(fix_perms_cli())
    try:
        secure.tighten([CONFIG_DIR, STATE_DIR])
    except OSError:
        pass
    if argv and argv[0] == "secrets":
        from .envedit import cli as secrets_cli
        raise SystemExit(secrets_cli(argv[1:]))
    if not (argv and argv[0] == "config"):
        bad = secure.env_file_problem(Path(CONFIG_DIR) / "env")
        if bad and not insecure:
            print(bad, file=sys.stderr); raise SystemExit(2)
        try:
            secure.load_secret_cmd()
        except Exception as e:
            print(f"xbot: {secure.redact(str(e))[:200]}", file=sys.stderr); raise SystemExit(2)
    if argv and argv[0] == "config":
        from .configcli import cli as config_cli
        raise SystemExit(config_cli(argv[1:]))
    if argv and argv[0] == "search":
        raise SystemExit(search_cli(argv[1:]))
    probe_graphics()  # BEFORE Textual owns stdin: the probe's replies must not arrive as keystrokes
    app = XBotApp()
    app._cli_mode = True
    try:
        app.run()
        if getattr(app, "_crash_line", None):
            raise SystemExit(1)  # printed after the terminal clear in finally
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _crash(e)
    finally:
        try:
            app.shutdown()
        except Exception as e:
            _crash(e)
        try:
            line = getattr(app, "_session_line", None) or (app.bot.end_session() if app.bot else None)
        except Exception:
            line = None
        clear_leftovers()  # every exit path (quit, spend limit, Ctrl+C, crash): wipe screen+scrollback+sixel first
        try:
            for msg in (getattr(app, "_crash_line", None), line):
                if msg:
                    print(msg, file=sys.stderr)
        except Exception:
            pass


def clear_leftovers(out=None):
    """Before the exit summary: wipe screen + scrollback so no media-viewer picture or controls line stays."""
    import sys
    from .video import CLEAR
    seq = "\x1b\\\x1b[0m" + CLEAR
    try:
        if out is not None:
            out.write(seq); out.flush(); return
        for o in (sys.stderr, sys.stdout):
            if o.isatty():
                o.write(seq); o.flush(); return
        with open("/dev/tty", "w") as t:  # both redirected: still clean the real terminal
            t.write(seq)
    except Exception:
        pass


def fix_perms_cli(out=print):
    """xbot fix-perms: ~/.config/xbot and ~/.local/state/xbot to 0700, their files (env included) to 0600."""
    from . import secure
    from .config import CONFIG_DIR, STATE_DIR
    ch = secure.tighten([CONFIG_DIR, STATE_DIR])
    out(f"xbot: tightened {len(ch)} path(s)" + (": " + ", ".join(ch) if ch else " (already private)"))
    bad = secure.env_file_problem(Path(CONFIG_DIR) / "env")
    if bad:
        out(bad); return 2
    return 0


def search_cli(argv, x=None, cfg=None, out=print, play=None, which=None):
    """xbot search "query" [--play N]: list results; --play N shows all media (photos, videos, GIFs) of the Nth
    result that has media in the terminal mpv viewer (A/D browse)."""
    import argparse, shutil
    from . import video
    ap = argparse.ArgumentParser(prog="xbot search")
    ap.add_argument("query"); ap.add_argument("--play", type=int, default=0, metavar="N")
    a = ap.parse_args(argv)
    if cfg is None:
        load_env_file(); cfg = Config.load()
    try:
        x = x or RealX()
        posts = x.search_recent(a.query, max(10, cfg.search_max_results))
        try:
            import os
            from . import search_history
            from .config import STATE_DIR
            search_history.add(os.environ.get("XBOT_STATE_DIR") or STATE_DIR, a.query)
        except Exception:
            pass
    except Exception as e:
        from .config import redact
        out(f"xbot search: {redact(str(e))[:200]}"); return 1
    withm = [p for p in posts if any(m.get("url") for m in p.get("media") or [])]
    for p in posts:
        mark = ""
        if p in withm:
            k = len(p["media"]); vid = any(m.get("type") in video.VIDEO_TYPES for m in p["media"])
            mark = f" [media {withm.index(p) + 1}: {k} item{'s' if k > 1 else ''}{', video' if vid else ''}]"
        out(f"{p['id']}{mark}: {clip(p.get('text', ''), 100)}")
    if not a.play:
        return 0
    if not 1 <= a.play <= len(withm):
        out(f"no media #{a.play} ({len(withm)} result(s) with media)"); return 2
    p = withm[a.play - 1]; media = p["media"]
    first = next((m.get("url") for m in media if m.get("type") in video.VIDEO_TYPES and m.get("url")), None)
    if first and video.url_forbidden(first) and hasattr(x, "get_post"):
        fresh = x.get_post(p["id"]) or {}
        if fresh.get("media"):
            p["media"] = fresh["media"]
    res = video.run_mpv(None, cfg, **({"run": play} if play else {}), which=which or shutil.which,
                        posts=list(enumerate(withm, 1)), start_n=a.play)  # A/D continue into the other results
    if res == "missing":
        out("mpv not found: install mpv to view media in the terminal"); return 1
    return 0


def _crash(e):
    import sys
    print(_crash_log(e), file=sys.stderr)
    raise SystemExit(1)


def _crash_log(e):
    """Write the full traceback to crash.log; return one clean line for stderr."""
    import traceback, time
    inner = getattr(e, "error", None)  # Textual WorkerFailed: the real exception (and traceback) is .error
    if isinstance(inner, BaseException):
        e = inner
    from .config import STATE_DIR, redact
    p = Path(STATE_DIR) / "crash.log"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        from .secure import append_private
        append_private(p, f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n" + redact("".join(traceback.format_exception(e))))
        where = f" (details: {p})"
    except OSError:
        where = ""
    return f"xbot: {type(e).__name__}: {redact(str(e))[:200]}{where}"


if __name__ == "__main__":
    main()
