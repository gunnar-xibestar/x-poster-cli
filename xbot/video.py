"""In-terminal media viewer with mpv: a post's photos, videos and GIFs as one playlist.

Opened by `v` on a card or a click on [media]. Streams the URLs from the X API (nothing
saved). Photos fill the area; videos use video_scale (default 0.6) with a vf scale+pad
filter so they stay centered. Keys: a/d seek, ←/→ media across posts, ↑/↓ volume,
r mute+hide, t tags, z large-fit photo, q/Esc/Ctrl+C force-close.
"""
import os, shutil, subprocess, sys

TARGET_BPS = 832_000
VOS = ("auto", "sixel", "tct")
AUDIO = ("off", "on")


def pick_variant(variants, target=TARGET_BPS):
    """mp4 variant closest to `target` bit/s (a GIF has a single mp4 without bit_rate). None if no mp4."""
    vs = [v for v in variants or [] if v.get("content_type") == "video/mp4" and v.get("url")]
    if not vs:
        return None
    return min(vs, key=lambda v: abs(int(v.get("bit_rate") or 0) - target))["url"]


CELL_PX = (8, 16)  # fallback cell size when neither the pty nor the startup probe knows (WSL reports 0). Kept
# small on purpose: guessing too small only shrinks the picture, guessing too big pushes it over the controls line.


def probed_cell():
    """Cell size (w, h) in pixels from textual-image's startup probe (CSI 16 t), or None."""
    try:
        from .app import graphics_probed
        cs = getattr(graphics_probed(), "cell_size", None)
        w, h = int(getattr(cs, "width", 0) or 0), int(getattr(cs, "height", 0) or 0)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def cell_px(cols, rows, xpx=0, ypx=0, probed=None):
    """Pixel size of one cell: from the pty's pixel size, else the startup probe, else CELL_PX."""
    if xpx and ypx and cols and rows:
        return xpx // cols, ypx // rows
    return probed or probed_cell() or CELL_PX


def parse_px_reports(data):
    """Terminal answers to CSI 14 t / CSI 16 t: ESC [ 4 ; h ; w t (text area px) and ESC [ 6 ; h ; w t
    (cell px). Returns (text_w, text_h, cell_w, cell_h), 0 where not answered."""
    import re
    s = data.decode("latin-1") if isinstance(data, (bytes, bytearray)) else str(data)
    tw = th = cw = ch = 0
    for kind, h, w in re.findall(r"\x1b\[([46]);(\d+);(\d+)t", s):
        if kind == "4":
            th, tw = int(h), int(w)
        else:
            ch, cw = int(h), int(w)
    return tw, th, cw, ch


def query_term_px(tty="/dev/tty", timeout=0.35):
    """Ask the terminal for its text-area (CSI 14 t) and cell (CSI 16 t) pixel size. (0,0,0,0) when there
    is no tty or no answer. Needs the tty for itself (Textual suspended)."""
    import select, termios, time
    try:
        fd = os.open(tty, os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return 0, 0, 0, 0
    old = None
    try:
        old = termios.tcgetattr(fd)
        new = list(old); new[3] &= ~(termios.ICANON | termios.ECHO)
        new[6] = list(new[6]); new[6][termios.VMIN] = 0; new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new)
        os.write(fd, b"\x1b[14t\x1b[16t")
        buf, end = b"", time.monotonic() + timeout
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                break
            chunk = os.read(fd, 256)
            if not chunk:
                break
            buf += chunk
            if buf.count(b"t") >= 2 and b"\x1b[4;" in buf and b"\x1b[6;" in buf:
                break
        return parse_px_reports(buf)
    except Exception:
        return 0, 0, 0, 0
    finally:
        try:
            if old is not None:
                termios.tcsetattr(fd, termios.TCSANOW, old)
        finally:
            os.close(fd)


def resolve_px(cols, rows, xpx=0, ypx=0, report=(0, 0, 0, 0), probed=None, sixel_scale="auto"):
    """Pixel size (xpx, ypx) of the whole terminal used for every sixel box (photos and videos alike).
    Candidates: TIOCGWINSZ, CSI 14 t (text area), CSI 16 t cell * cols/rows, the startup probe's cell;
    the largest consistent one wins (Windows Terminal / WSL with display scaling can under-report, or report
    0 so the small CELL_PX fallback was used: the picture box then filled only ~78% of the screen).
    sixel_scale: 'auto', or a number multiplying the result (manual fix when every report is wrong)."""
    tw, th, cw, ch = (tuple(report) + (0, 0, 0, 0))[:4]
    cands = []
    if xpx and ypx:
        cands.append((xpx, ypx))
    if tw and th:
        cands.append((tw, th))
    if cw and ch:
        cands.append((cw * cols, ch * rows))
    pc = probed or probed_cell()
    if pc:
        cands.append((pc[0] * cols, pc[1] * rows))
    # consistent = roughly the cell aspect of a text terminal (w/h per cell between 0.3 and 1.0)
    ok = [c for c in cands if cols and rows and 0.3 <= (c[0] / cols) / max(1, c[1] / rows) <= 1.0]
    best = max(ok or cands, key=lambda c: c[0] * c[1]) if cands else (0, 0)
    try:
        f = float(sixel_scale) if str(sixel_scale).strip().lower() not in ("", "auto", "none") else 0.0
    except (TypeError, ValueError):
        f = 0.0
    if f > 0:
        if not best[0]:
            best = (CELL_PX[0] * cols, CELL_PX[1] * rows)
        best = (int(best[0] * f), int(best[1] * f))
    return best


def sixel_geometry(cols, rows, xpx=0, ypx=0, probed=None):
    """Box for the sixel picture: (left, top, cols, rows, width_px, height_px). It starts at row/col 1 and
    ends at least one row above the STATUS_ROWS reserved for the controls line, so even a tall photo
    (fit inside it by --keepaspect) can't reach them or make the terminal scroll."""
    cw, ch = cell_px(cols, rows, xpx, ypx, probed)
    c = max(1, cols - 1)
    r = max(1, rows - STATUS_ROWS - 2)  # -1 for the 1-based top offset, -1 spare row: the cursor lands below the image
    return 1, 1, c, r, c * cw, r * ch


def term_size(fd=None):
    """(cols, rows, xpixels, ypixels) of the controlling terminal; pixels 0 when unknown."""
    import fcntl, struct, termios
    for f in ([fd] if fd is not None else []) + [1, 0, 2]:
        try:
            rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(f, termios.TIOCGWINSZ, b"\0" * 8))
            if cols and rows:
                return cols, rows, xp, yp
        except Exception:
            continue
    c, r = shutil.get_terminal_size((80, 24))
    return c, r, 0, 0


def best_variant(variants, max_h=None):
    """Highest-bitrate mp4 whose height (from the .../WxH/... URL) fits max_h pixels; else the highest overall."""
    import re
    vs = [v for v in variants or [] if v.get("content_type") == "video/mp4" and v.get("url")]
    if not vs:
        return None
    def h(v):
        m = re.search(r"/(\d+)x(\d+)/", v["url"]); return int(m.group(2)) if m else 0
    fit = [v for v in vs if max_h and h(v) and h(v) <= max_h] or vs
    return max(fit, key=lambda v: int(v.get("bit_rate") or 0))["url"]


def resolve_vo(setting="auto", env=None, pixels_known=True):
    """auto: sixel on Windows Terminal (cell size estimated when unknown) or any sixel terminal that reports
    its pixel size; otherwise tct."""
    s = (setting or "auto").lower()
    if s in ("sixel", "tct"):
        return s
    from .app import pick_renderer
    e = os.environ if env is None else env
    if pick_renderer("auto", env) == "sixel" and (pixels_known or e.get("WT_SESSION")):
        return "sixel"
    return "tct"


INPUT_CONF = ("a seek -5\nA seek -5\nd seek 5\nD seek 5\nUP add volume 5\nDOWN add volume -5\nSPACE cycle pause\n"
              "m cycle mute\nM cycle mute\n"
              "LEFT playlist-prev; script-message xbot-prev\nRIGHT playlist-next; script-message xbot-next\n"
              "q quit\nQ quit\nESC quit\n")
LIKE_CONF = "l script-message xbot-like\nL script-message xbot-like\n"
VIDEO_KEYS = "a/d seek 5s  ·  ↑/↓ volume  ·  space pause  ·  m mute"
BROWSE_KEYS = "←/→ prev/next"
LIKE_KEYS = "l like"
POST_KEYS = "r remove  t tags"
BACK_KEYS = "q/Esc back"
HINT = VIDEO_KEYS + "  " + BACK_KEYS  # legacy name
HEART_OSD = ("♥", "♥ ♥ ♥", "♥ ♥ ♥ ♥ ♥", "♥ ♥ ♥", "♥")
VIDEO_SCALE = 0.6  # default share of the picture area a video/GIF gets (smaller sixel frames = more fps)
SCALE_BOUNDS = (0.2, 1.0)
VIDEO_FAST = ["--vo-sixel-fixedpalette=yes", "--vo-sixel-dither=none", "--sws-scaler=fast-bilinear"]


def clamp_scale(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return VIDEO_SCALE
    return min(SCALE_BOUNDS[1], max(SCALE_BOUNDS[0], v)) if v == v else VIDEO_SCALE


def fit_box(cols, rows, xpx=0, ypx=0, probed=None, kind="photo", w=None, h=None, scale=VIDEO_SCALE, large=False):
    """Centred sixel box for one item: (left, top, cols, rows, width_px, height_px), 1-based cells. Videos/GIFs
    get `scale` of the area above the controls line, photos all of it; with the media's pixel size the box is
    shrunk to its aspect so the centring uses the real scaled picture."""
    _, _, ac, ar, _, _ = sixel_geometry(cols, rows, xpx, ypx, probed)
    if large:  # z on a photo: every column, every row but the controls line, no padding
        ac, ar = max(1, cols), max(1, rows - 1)
    cw, ch = cell_px(cols, rows, xpx, ypx, probed)
    f = clamp_scale(scale) if kind != "photo" else 1.0
    bw, bh = max(1, ac * cw * f), max(1, ar * ch * f)
    if w and h:
        k = min(bw / w, bh / h)
        bw, bh = w * k, h * k
    c = max(1, min(ac, int(bw // cw)))
    r = max(1, min(ar, int(bh // ch)))
    left = 1 + (ac - c) // 2
    top = 1 + (ar - r) // 2
    return left, top, c, r, c * cw, r * ch


STATUS_ROWS = 2  # rows kept free below the picture: a rule + the controls line (never drawn over the frame)
VIDEO_TYPES = ("video", "animated_gif")


def large_photo_url(url):
    """pbs.twimg.com images default to a small size: ask for name=large (others unchanged)."""
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    if not url or "pbs.twimg.com" not in url:
        return url
    u = urlsplit(url)
    q = dict(parse_qsl(u.query)); q["name"] = "large"
    if "format" not in q and "." in u.path.rsplit("/", 1)[-1]:
        path, ext = u.path.rsplit(".", 1)
        if ext.lower() in ("jpg", "jpeg", "png", "webp"):
            return urlunsplit((u.scheme, u.netloc, path, urlencode({"format": ext.lower(), "name": "large"}), ""))
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), ""))


def playlist(media, max_h=None):
    """Every playable item of a post, in order: [{'kind': 'photo'|'video', 'url', 'type'}]. Videos/GIFs get the
    sharpest mp4 that fits max_h pixels; photos the large size. Items without a direct URL are skipped."""
    out = []
    for m in media or []:
        vid = m.get("type") in VIDEO_TYPES
        url = (best_variant(m.get("variants"), max_h=max_h) if vid and m.get("variants") else None) or m.get("url")
        if not url:
            continue
        out.append({"kind": "video" if vid else "photo", "type": m.get("type", "photo"),
                    "url": url if vid else large_photo_url(url), "w": m.get("width"), "h": m.get("height")})
    return out


def posts_playlist(posts, max_h=None):
    """One playlist over a whole list (feed / search results): every playable item of every post with media, in
    order. posts = [(n, post)]. Each item also carries n, handle, post_idx/post_count (among posts with media) and
    sub/sub_count (item within its post). Posts without playable media are skipped. mpv opens entries lazily, so
    nothing is downloaded up front."""
    groups = []
    for n, p in posts:
        its = playlist(p.get("media"), max_h=max_h)
        if its:
            groups.append((n, p, its))
    out = []
    for gi, (n, p, its) in enumerate(groups, 1):
        for si, it in enumerate(its, 1):
            out.append(dict(it, n=n, handle=p.get("username"), post_id=str(p.get("id")), post_idx=gi,
                            post_count=len(groups), sub=si, sub_count=len(its)))
    return out


def start_index(items, n):
    """Playlist index of the first item of post n (0 if it isn't in the list)."""
    return next((i for i, it in enumerate(items) if it.get("n") == n), 0)


def _items(src):
    if isinstance(src, str):
        return [{"kind": "video", "type": "video", "url": src}]
    return [i if isinstance(i, dict) else {"kind": "video", "type": "video", "url": i} for i in src]


def controls_line(kind, pos=0, count=1, st=None, liked=False, msg=None, width=None, item=None):
    """The status/controls line drawn BELOW the picture. Photos: counter, ←/→, l, q/Esc only.
    Videos: counter + time/state + seek/volume/pause/mute + ←/→, l, q/Esc. With a multi-post `item`
    the counter is `post 3/12 · @handle · 2/4` (item within its post); ←/→ is always shown."""
    st = st or {}
    if item and item.get("post_idx"):
        head = f"post {item['post_idx']}/{item['post_count']}"
        if item.get("handle"):
            head += f"  ·  @{item['handle']}"
        parts = [f"{head}  ·  {item['sub']}/{item['sub_count']}"]
    else:
        parts = [f"{pos + 1}/{count}"]
    parts.append("photo" if kind == "photo" else "video")
    if kind == "photo" and (st or {}).get("large"):
        parts.append("large")
    if kind != "photo":
        def t(v):
            try:
                v = int(float(v)); return f"{v // 60}:{v % 60:02d}"
            except (TypeError, ValueError):
                return "-:--"
        parts.append(f"{t(st.get('time-pos'))}/{t(st.get('duration'))}"
                     + (" PAUSED" if st.get("pause") else "") + (" muted" if st.get("mute") else ""))
        parts.append(VIDEO_KEYS)
    parts.append(BROWSE_KEYS)  # always shown; at the ends ←/→ do nothing (brief "no more media" note)
    if kind == "photo" and (st or {}).get("can_large", True):
        parts.append(ZOOM_KEYS)
    parts.append(("♥ liked" if liked else LIKE_KEYS))
    if item and item.get("post_id"):
        parts.append(POST_KEYS)
    parts.append(BACK_KEYS)
    if msg:
        parts.insert(1, msg)
    line = "  ·  ".join(parts)
    return line[:width] if width else line


def mpv_argv(url, vo="tct", audio="off", cols=80, rows=24, input_fd=None, xpx=0, ypx=0, ipc_fd=None, start=0, cell=None, scale=VIDEO_SCALE):
    """mpv command for one URL or a playlist (list of URLs or playlist() items). The picture gets
    rows - STATUS_ROWS; mpv's own OSD/status is off so nothing is drawn over the frame (xbot paints the
    controls line in the reserved rows below, via IPC)."""
    items = _items(url)
    vrows = max(2, rows - STATUS_ROWS)
    a = ["mpv", "--really-quiet", f"--vo={vo}", "--keepaspect=yes", "--keep-open=no",
         "--save-position-on-quit=no", "--resume-playback=no", "--cache-on-disk=no", "--write-filename-in-watch-later-config=no",
         "--terminal=yes", "--input-terminal=no", "--input-default-bindings=yes",  # keys come from xbot via IPC
         "--osd-level=0", "--osd-bar=no", "--osd-on-seek=no", "--term-osd=no", "--term-status-msg=",
         "--image-display-duration=inf", "--loop-playlist=no",
         # never a GUI window (WSLg / X11 / Wayland would steal keyboard focus from the terminal):
         "--force-window=no", "--idle=no", "--audio-display=no", "--stop-screensaver=no", "--hwdec=no"]
    if start:
        a.append(f"--playlist-start={start}")
    if audio != "on":
        a.append("--mute=yes")
    if vo == "tct":
        a += [f"--vo-tct-width={cols}", f"--vo-tct-height={vrows}"]
    else:
        # global = photo quality (adaptive 256-colour palette, fs dithering, lanczos); each entry then gets its
        # own centred box via an mpv per-file group --{ ... --}; videos/GIFs also get the fast settings
        # the VO's size/position must also be set globally: per-file --{ } values alone may not reach the
        # sixel VO (it then falls back to its own default size, which the pipe to xbot makes tiny). Global =
        # the start item's box; on every item change xbot also sets the item's box over IPC (item_props).
        # mpv 0.41's sixel VO only reads left/top at start (and draws the picture at the box's top-left,
        # it does not centre a letterboxed frame), so the box is CONSTANT (the whole picture area, from
        # 1;1) and each item is centred inside it by a filter: scale to fit + pad with black to the box
        # (pad_vf). Per item / on z only width/height and the filter change, both of which mpv applies live.
        if items:
            it0 = items[min(start, len(items) - 1)]
            a += box_opts(area_box(cols, rows, xpx, ypx, cell))
            a.append("--vf=" + pad_vf(it0, cols, rows, xpx, ypx, cell, scale))
        a += ["--video-unscaled=no", "--video-zoom=0",  # always scale to the box (small photos are upscaled)
              "--vo-sixel-alt-screen=no",  # xbot owns the alt screen (see run_mpv)
              "--vo-sixel-fixedpalette=no", "--vo-sixel-reqcolors=256", "--vo-sixel-dither=fs", "--vo-sixel-buffered=yes",
              "--sws-scaler=lanczos", "--framedrop=vo"]
    if ipc_fd is not None:
        a.append(f"--input-ipc-client=fd://{ipc_fd}")
    if input_fd is not None:
        a.append(f"--input-conf=/dev/fd/{input_fd}")
    return a + ["--"] + [i["url"] for i in items]


ZOOM_KEYS = "z large"


def area_box(cols, rows, xpx=0, ypx=0, cell=None, large=False):
    """The constant sixel box: the whole picture area from 1;1 (large: all columns, all rows but the
    controls line). (left, top, cols, rows, width_px, height_px)."""
    _, _, ac, ar, _, _ = sixel_geometry(cols, rows, xpx, ypx, cell)
    if large:
        ac, ar = max(1, cols), max(1, rows - 1)
    cw, ch = cell_px(cols, rows, xpx, ypx, cell)
    return 1, 1, ac, ar, ac * cw, ar * ch


def box_opts(box):
    left, top, c, r, wpx, hpx = box
    return [f"--vo-sixel-cols={c}", f"--vo-sixel-rows={r}", f"--vo-sixel-width={wpx}", f"--vo-sixel-height={hpx}",
            f"--vo-sixel-left={left}", f"--vo-sixel-top={top}"]


def pad_vf(item, cols, rows, xpx=0, ypx=0, cell=None, scale=VIDEO_SCALE, large=False):
    """Video filter that centres the item in the box: fit into its content box (photos: the whole box,
    videos/GIFs: `scale` of it), then pad with black to exactly the box size."""
    kind = "photo" if item.get("kind") == "photo" else "video"
    _, _, _, _, W, H = area_box(cols, rows, xpx, ypx, cell, large)
    f = 1.0 if kind == "photo" else clamp_scale(scale)
    bw, bh = max(2, int(W * f)) // 2 * 2, max(2, int(H * f)) // 2 * 2
    flags = "lanczos" if kind == "photo" else "fast_bilinear"
    return (f"lavfi=[format=rgb24,scale={bw}:{bh}:force_original_aspect_ratio=decrease:flags={flags},"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black]")


def item_props(item, cols, rows, xpx=0, ypx=0, cell=None, scale=VIDEO_SCALE, large=False):
    """IPC commands for one item: the constant box (only width/height change, for z), the centring filter,
    zoom 0 (never crop)."""
    box = area_box(cols, rows, xpx, ypx, cell, large)
    cmds = [["set_property", k, v] for k, v in zip(
        ("vo-sixel-cols", "vo-sixel-rows", "vo-sixel-width", "vo-sixel-height"), box[2:])]
    return cmds + [["vf", "set", pad_vf(item, cols, rows, xpx, ypx, cell, scale, large)],
                   ["set_property", "video-zoom", 0]]


def photo_boxes(item, cols, rows, xpx=0, ypx=0, cell=None):
    """(normal, large) boxes for a photo."""
    w, h = item.get("w"), item.get("h")
    return (fit_box(cols, rows, xpx, ypx, cell, "photo", w, h),
            fit_box(cols, rows, xpx, ypx, cell, "photo", w, h, large=True))


def sixel_item_opts(item, cols, rows, xpx=0, ypx=0, cell=None, scale=VIDEO_SCALE):
    kind = "photo" if item.get("kind") == "photo" else "video"
    left, top, c, r, wpx, hpx = fit_box(cols, rows, xpx, ypx, cell, kind, item.get("w"), item.get("h"), scale)
    o = [f"--vo-sixel-cols={c}", f"--vo-sixel-rows={r}", f"--vo-sixel-width={wpx}", f"--vo-sixel-height={hpx}",
         f"--vo-sixel-left={left}", f"--vo-sixel-top={top}"]
    return o + (VIDEO_FAST if kind == "video" else [])


class StatusPainter:
    """Draws the controls line on the terminal's last row (and a rule above it), outside the picture area."""
    def __init__(self, items, cols=80, rows=24, write=None, liked=None, start=0):
        self.items, self.cols, self.rows = items, cols, rows
        self.write = write or (lambda s: None)
        self.liked = liked or (lambda item=None: False)  # liked(current item) -> bool
        self.st, self.msg, self.last = {"playlist-pos": start}, None, None
        import threading
        self.lock = threading.RLock()  # IPC thread + repaint timers

    def pos(self):
        try:
            pos = int(self.st.get("playlist-pos") or 0)
        except (TypeError, ValueError):
            pos = int(self.st.get("last-pos") or 0)
        return min(max(pos, 0), len(self.items) - 1) if self.items else 0

    def current(self):
        """The item on screen now (None without items)."""
        return self.items[self.pos()] if self.items else None

    def line(self):
        pos, it = self.pos(), self.current()
        kind = it["kind"] if it else "video"
        return controls_line(kind, pos, len(self.items) or 1, self.st, self.liked(it), self.msg,
                             width=self.cols - 1, item=it)

    def paint(self, force=False):
        try:
            with self.lock:
                self._paint(force)
        except Exception as e:  # a bad value must never kill the watcher or a repaint timer
            log_exc(e)

    def _paint(self, force=False):
        ln = self.line()
        if ln == self.last and not force:
            return
        self.last = ln
        r = self.rows
        rule = "" if self.st.get("large") else f"\x1b[{r - 1};1H\x1b[2K\x1b[2m{'─' * (self.cols - 1)}\x1b[0m"
        self.write(f"\x1b7{rule}\x1b[{r};1H\x1b[2K\x1b[1m{ln}\x1b[0m\x1b8")

    def update(self, name, value):
        self.st[name] = value
        if name == "playlist-pos":
            if not isinstance(value, int) or value < 0:  # mpv reports -1 while tearing down: keep the last real position
                self.st[name] = self.st.get("last-pos", 0); return
            self.st["last-pos"] = value
            import time as _t
            self.moved_at = _t.monotonic()
            changed = value != getattr(self, "_pos_seen", None)
            self._pos_seen = value
            self.msg = getattr(self, "arrive_msg", {}).pop(value, None)
            if changed:
                self.st["large"] = False  # ←/→: a new item starts at the normal fit
                g = getattr(self, "geom", None)
                it = self.items[value] if 0 <= value < len(self.items) else None
                if g and it and it.get("kind") == "photo":
                    n_, l_ = photo_boxes(it, *g)
                    self.st["can_large"] = l_[2:4] != n_[2:4]
                hook = getattr(self, "on_move", None)
                if hook and 0 <= value < len(self.items):
                    try:
                        hook(self.items[value])
                    except Exception as e:
                        log_exc(e)  # e.g. "@x muted, post hidden" after r
        self.paint()


REPAINT_EVENTS = ("file-loaded", "playback-restart", "video-reconfig")
REPAINT_DELAY = 0.35
OBSERVE = ("playlist-pos", "time-pos", "duration", "pause", "mute")


IPC_TIMEOUT = 1.0     # every IPC send gives up after this (never blocks a key or the watcher forever)
PING_EVERY = 2.0      # watchdog: ask mpv for a property this often ...
HUNG_AFTER = 15.0     # ... and call on_hung when it hasn't answered anything for this long


def ipc_loop(sock, on_like=None, interval=0.12, painter=None, send_lock=None, on_hung=None,
             ping_every=PING_EVERY, hung_after=HUNG_AFTER):
    """Read mpv IPC events: keep the controls line (painter) current; on the `l` script-message call
    on_like() -> message and show a heart + the result in the controls line (never over the picture).
    Sends time out; a watchdog pings mpv and calls on_hung() once if mpv stops answering."""
    import json, time, socket as _s
    import threading
    lk = send_lock or threading.Lock()
    try:
        sock.settimeout(IPC_TIMEOUT)
    except OSError:
        return
    def send(cmd, **extra):
        try:
            if not lk.acquire(timeout=IPC_TIMEOUT):
                return False
            try:
                sock.sendall((json.dumps({"command": cmd, **extra}) + "\n").encode())
                return True
            finally:
                lk.release()
        except (OSError, ValueError):
            return False
    for i, prop in enumerate(OBSERVE, 1):
        send(["observe_property", i, prop])
    if painter:
        painter.paint(force=True)
    buf, heard, pinged, fired = b"", time.monotonic(), 0.0, False
    try:
        while True:
            now = time.monotonic()
            if on_hung and not fired:
                if now - pinged >= ping_every:
                    send(["get_property", "pid"], request_id=999); pinged = now
                if now - heard > hung_after:
                    fired = True
                    log_exc(RuntimeError(f"mpv did not answer IPC for {now - heard:.0f}s: stopping it"))
                    try:
                        on_hung()
                    except Exception as e:
                        log_exc(e)
            try:
                chunk = sock.recv(65536)
            except _s.timeout:
                continue
            if not chunk:
                break
            heard = time.monotonic()
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                try:
                    _ipc_event(raw, on_like, interval, painter)
                except Exception as e:  # never let one bad event end the watcher (mpv keeps running regardless)
                    log_exc(e)
    except OSError:  # mpv exited / socket closed
        pass
    except Exception as e:
        log_exc(e)


class Stopper:
    """Ends mpv no matter what: quit over IPC, then terminate, then kill (each step only if still running)."""
    def __init__(self, send, grace=1.5):
        self.send, self.grace, self.proc = send, grace, None
        import threading
        self.started = threading.Event()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, ipc=True):
        if self.started.is_set():
            return
        self.started.set()
        import threading
        threading.Thread(target=self._run, args=(ipc,), daemon=True).start()

    def _run(self, ipc):
        import time
        if ipc:
            try:
                self.send(["quit"])
            except Exception:
                pass
        for sig in ("terminate", "kill"):
            end = time.monotonic() + self.grace
            while time.monotonic() < end:
                if self.proc is None or self.proc.poll() is not None:
                    return
                time.sleep(0.05)
            if self.alive():
                try:
                    getattr(self.proc, sig)()
                    log_exc(RuntimeError(f"mpv did not quit: {sig}"))
                except Exception:
                    pass


def run_proc(argv, stopper, **kw):
    """subprocess.run replacement that exposes the process to the Stopper."""
    p = subprocess.Popen(argv, **kw)
    stopper.proc = p
    try:
        p.wait()
    except BaseException:
        p.kill(); p.wait(); raise
    return subprocess.CompletedProcess(argv, p.returncode)


def log_exc(e):
    try:
        from .app import _crash_log
        _crash_log(e)
    except Exception:
        pass


def stderr_log():
    """mpv's stderr goes to ~/.local/state/xbot/mpv-stderr.log (truncated each run), never to the terminal."""
    try:
        from .config import STATE_DIR
        from pathlib import Path
        p = Path(STATE_DIR) / "mpv-stderr.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        return os.fdopen(fd, "wb")
    except Exception:
        return subprocess.DEVNULL


def write_all(fd, data):
    """Write every byte to fd. A plain write() on a tty can be short (signal, EAGAIN on a non-blocking
    descriptor); dropping the rest of a chunk can cut a sixel frame's ESC P header or its ST, and the
    terminal then prints the frame as text. Retries until done; gives up only on a real error."""
    import errno, select
    mv = memoryview(data)
    while mv:
        try:
            k = os.write(fd, mv)
            mv = mv[k:]
        except InterruptedError:
            continue
        except BlockingIOError:
            select.select([], [fd], [], 1.0)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EINTR):
                continue
            log_exc(e); return False
    return True


def input_raw(fd):
    """Raw keyboard input (no echo, no line buffering, no signals, no XON/XOFF) but output processing
    (OPOST) left as is, like mpv's own terminal setup; tty.setraw would also change the output side."""
    import termios
    a = termios.tcgetattr(fd)
    a[0] &= ~(termios.IXON | termios.IXOFF | termios.ICRNL | termios.INLCR | termios.IGNCR | termios.BRKINT | termios.ISTRIP)
    a[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
    a[6][termios.VMIN], a[6][termios.VTIME] = 1, 0
    termios.tcsetattr(fd, termios.TCSANOW, a)


class TermProxy:
    """mpv's stdout goes through a pipe to this thread, which copies it to the terminal and inserts our
    controls-line updates only at safe points: never inside a sixel DCS string (ESC P ... ESC \\) or a
    half-written escape sequence. Writing straight to the tty from another thread could land in the
    middle of a sixel frame; the terminal then aborts the image, prints the rest as text or keeps
    swallowing output, which looks like a frozen player and a broken TUI afterwards.
    The proxy never stops reading (mpv would block on a full pipe); on any error it passes data through."""
    def __init__(self, rfd, out):
        import threading
        self.rfd, self.out = rfd, out  # out(bytes) writes to the terminal
        self.pending, self.lock = None, threading.Lock()
        self.in_dcs, self.tail = False, b""
        self.dcs_since, self.dcs_bytes, self.dcs_warned = 0.0, 0, False
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def submit(self, s):
        with self.lock:
            self.pending = s.encode() if isinstance(s, str) else s

    def safe(self):
        return not self.in_dcs and not self.tail

    DCS_MAX_SECS = 5.0          # safety net: a DCS open this long / this big is suspicious ...
    DCS_MAX_BYTES = 32 << 20    # ... but we still never inject into it (logged once)

    def scan(self, data):
        """Update DCS / partial-escape state after `data`. Recognises 7-bit DCS (ESC P) / ST (ESC \\) and the
        8-bit C1 forms (0x90 / 0x9C). Cheap: only looks at ESC / C1 positions, never decodes bytes."""
        import time
        buf = self.tail + data
        self.tail = b""
        i, n = 0, len(buf)
        while i < n:
            if self.in_dcs:
                j7, j8 = buf.find(b"\x1b\\", i), buf.find(b"\x9c", i)
                js = [j for j in (j7, j8) if j >= 0]
                if not js:
                    self.dcs_bytes += n - i
                    if buf.endswith(b"\x1b"):
                        self.tail = b"\x1b"  # maybe the first half of ST
                    self._check_dcs(time)
                    return
                j = min(js)
                self.in_dcs, i = False, j + (2 if j == j7 else 1)
                continue
            j7, j8 = buf.find(b"\x1b", i), buf.find(b"\x90", i)
            if j8 >= 0 and (j7 < 0 or j8 < j7):
                self._open_dcs(time); i = j8 + 1; continue
            if j7 < 0:
                return
            j = j7
            if j + 1 >= n:
                self.tail = buf[j:]; return
            c = buf[j + 1]
            if c == 0x50:  # 'P'
                self._open_dcs(time); i = j + 2; continue
            if c == 0x5b:  # '[' CSI: parameters until a final byte 0x40-0x7e
                k = j + 2
                while k < n and not (0x40 <= buf[k] <= 0x7e):
                    k += 1
                if k >= n:
                    self.tail = buf[j:]; return
                i = k + 1; continue
            i = j + 2

    def _open_dcs(self, time):
        self.in_dcs, self.dcs_since, self.dcs_bytes, self.dcs_warned = True, time.monotonic(), 0, False

    def _check_dcs(self, time):
        if not self.dcs_warned and (time.monotonic() - self.dcs_since > self.DCS_MAX_SECS
                                    or self.dcs_bytes > self.DCS_MAX_BYTES):
            self.dcs_warned = True
            log_exc(RuntimeError(f"sixel DCS open {time.monotonic() - self.dcs_since:.1f}s / {self.dcs_bytes} bytes: "
                                 "controls-line updates held back until it ends"))

    def flush_pending(self):
        with self.lock:
            p, self.pending = self.pending, None
        if p:
            self.out(p)

    def loop(self):
        import select
        while True:
            try:
                ready, _, _ = select.select([self.rfd], [], [], 0.05)
                if not ready:
                    if self.safe():
                        self.flush_pending()
                    continue
                data = os.read(self.rfd, 65536)
                if not data:
                    break
                self.out(data)
                try:
                    self.scan(data)
                except Exception as e:  # unknown state: assume we're inside a frame until an ST shows up
                    log_exc(e); self.in_dcs, self.tail = True, b""
                if self.safe():
                    self.flush_pending()
            except Exception as e:
                log_exc(e)
                try:
                    data = os.read(self.rfd, 65536)  # keep draining so mpv never blocks
                    if not data:
                        break
                    self.out(data)
                except Exception:
                    break
        with self.lock:
            self.pending = None  # mpv is gone: a late controls line would land outside the viewer screen


def _ipc_event(raw, on_like, interval, painter):
    import json, time
    try:
        ev = json.loads(raw)
    except ValueError:
        return
    if ev.get("event") == "property-change" and painter:
        v = ev.get("data")
        if ev.get("name") == "time-pos" and v is not None:
            v = int(v)  # repaint once a second, not every frame
        painter.update(ev.get("name"), v)
    elif ev.get("event") in REPAINT_EVENTS and painter:
        # a new item / first frame: mpv's sixel output may have cleared or drawn over the controls line
        painter.paint(force=True)
        import threading
        t = threading.Timer(REPAINT_DELAY, lambda: painter.paint(force=True)); t.daemon = True; t.start()
    elif ev.get("event") == "client-message" and (ev.get("args") or [None])[0] in ("xbot-next", "xbot-prev") and painter:
        nxt = ev["args"][0] == "xbot-next"
        just_moved = time.monotonic() - getattr(painter, "moved_at", 0) < 0.3  # this key's own move already landed
        if not just_moved and ((painter.pos() >= len(painter.items) - 1) if nxt else (painter.pos() <= 0)):
            # mpv's playlist-next/prev is a no-op at the ends: say so on the controls line
            painter.msg = "no more media" if nxt else "first item"; painter.paint()
    elif ev.get("event") == "client-message" and (ev.get("args") or [None])[0] == "xbot-like" and on_like:
        for h in HEART_OSD:  # grow then shrink, in the controls line
            if painter:
                painter.msg = h; painter.paint()
            time.sleep(interval)
        try:
            msg = (on_like(painter.current()) if painter else on_like()) or "♥"
        except Exception as e:
            msg = f"like failed ({type(e).__name__})"
        if painter:
            painter.msg = f"♥ {msg}"; painter.paint()


GUI_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XDG_SESSION_TYPE", "XAUTHORITY",
           "DBUS_SESSION_BUS_ADDRESS", "BROWSER")


def mpv_env(environ=None):
    """safe_env() minus everything that lets mpv reach a display server: in WSLg any X11/Wayland
    connection can create a window and pull keyboard focus away from Windows Terminal. On WSL with
    PULSE_SERVER set (WSLg audio), XDG_RUNTIME_DIR goes too, so libwayland can't fall back to
    $XDG_RUNTIME_DIR/wayland-0."""
    from .secure import safe_env
    import os as _os
    e = _os.environ if environ is None else environ
    env = safe_env(source=e)
    for k in GUI_ENV:
        env.pop(k, None)
    if e.get("WSL_DISTRO_NAME") and e.get("PULSE_SERVER"):
        env.pop("XDG_RUNTIME_DIR", None)
    return env


CLEAR = "\x1b[2J\x1b[3J\x1b[H"  # screen + scrollback (removes sixel graphics too) + home
ENTER_VIEWER = "\x1b[?1049h" + CLEAR
# end any unterminated sixel/DCS string, reset attributes + scroll region, show the cursor, wipe the viewer
# screen, leave it, and wipe the normal screen too so no picture or controls line is left behind
LEAVE_VIEWER = "\x1b\\\x1b[0m\x1b[r\x1b[?25h" + CLEAR + "\x1b[?1049l" + CLEAR
MOUSE_OFF = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l\x1b[?1006l\x1b[?1015l\x1b[?1004l\x1b[?2004l"
# Mouse tracking (X10/normal/button/any, UTF-8/SGR/urxvt encodings), focus reports and bracketed paste off
# while mpv runs; Textual turns its modes back on when it resumes.

KEYMAP = {b"a": "a", b"A": "A", b"d": "d", b"D": "D", b" ": "SPACE", b"m": "m", b"M": "M", b"l": "l", b"L": "L",
          b"q": "q", b"Q": "Q", b"\x03": "q",
          b"r": "r", b"R": "R", b"t": "t", b"T": "T", b"z": "z", b"Z": "Z"}  # r / t are handled by xbot (PostActions), never by mpv
ARROWS = {b"A": "UP", b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT"}


def parse_keys(buf):
    """Raw tty bytes -> (mpv key names, unparsed rest). Mouse reports (ESC [ M b x y, SGR ESC [ < ... M/m),
    focus reports, bracketed paste and any other escape sequence are dropped, never echoed or forwarded.
    A trailing lone ESC stays in `rest` (the caller decides after a short timeout that it was the Esc key)."""
    keys, i, n = [], 0, len(buf)
    while i < n:
        b = buf[i:i + 1]
        if b != b"\x1b":
            if b in KEYMAP:
                keys.append(KEYMAP[b])
            i += 1; continue
        if i + 1 >= n:
            return keys, buf[i:]
        c = buf[i + 1:i + 2]
        if c == b"\x1b":  # ESC ESC: the first one was a real Esc press
            keys.append("ESC"); i += 1; continue
        if c in (b"[", b"O"):
            if c == b"[" and buf[i + 2:i + 3] == b"M":  # X10 / normal mouse: ESC [ M Cb Cx Cy
                if i + 6 > n:
                    return keys, buf[i:]
                i += 6; continue
            if c == b"[" and buf[i + 2:i + 6] == b"200~":  # bracketed paste: drop all of it
                j = buf.find(b"\x1b[201~", i + 6)
                if j < 0:
                    return keys, buf[i:]
                i = j + 6; continue
            k = i + 2
            while k < n and not (0x40 <= buf[k] <= 0x7e):
                k += 1
            if k >= n:
                return keys, buf[i:]
            fin = buf[k:k + 1]
            if fin in ARROWS and k == i + 2:  # ESC [ A / ESC O A (no params) = arrows
                keys.append(ARROWS[fin])
            i = k + 1; continue  # anything else (SGR mouse, focus, F-keys, modified keys): dropped
        keys.append("ESC"); i += 1  # ESC + other byte (Alt+key): treat as Esc
    return keys, b""


def next_post_index(items, pos, gone=()):
    """Playlist index of the first item of the next post (after the one at pos) not in `gone`; None if none."""
    cur = items[pos].get("post_id") if items else None
    seen = {cur}
    for i in range(pos + 1, len(items)):
        pid = items[i].get("post_id")
        if pid not in seen and pid not in gone:
            return i
        seen.add(pid)
    return None


class PostActions:
    """r / t in the viewer, handled by xbot on the key thread (never sent to mpv).
    r: remove = mute the author on X + hide the post, in a background thread (the key thread never blocks on
       the network); the viewer moves to the next post with media and the removed post's entries are taken
       out of mpv's playlist in place (playlist-remove), so mpv is never restarted.
    t: hand off to the Textual filter popup: `popup(item)` records what to open, then mpv quits; the app
       shows the popup and reopens the viewer (next post on apply, the same item on Esc)."""
    def __init__(self, painter, send, remove=None, popup=None, log=None, run=None, timeout=15.0, **_):
        self.timeout = timeout
        self.painter, self.send, self.remove, self.popup = painter, send, remove, popup
        self.log = log or (lambda msg: None)
        self.busy = set()
        import threading
        self.run = run or (lambda f: threading.Thread(target=f, daemon=True).start())

    def _say(self, msg):
        self.painter.msg = msg; self.painter.paint(force=True)

    def drop_post(self, pid, msg):
        """Jump past post pid and remove its entries from mpv's playlist (and the painter's items)."""
        p = self.painter
        with p.lock:
            items, pos = p.items, p.pos()
            idx = [i for i, it in enumerate(items) if it.get("post_id") == pid]
            if not idx:
                return None
            nxt = next_post_index(items, max(idx))
            if nxt is None and len(idx) == len(items):  # the only post with media left: caller closes the viewer
                self._say(f"{msg} · no more posts with media"); return "last"
            if nxt is None:  # last post: go back to the previous post instead
                nxt = min(idx) - 1
            if pos in idx:
                self.send(["playlist-play-index", nxt])
            for i in sorted(idx, reverse=True):
                self.send(["playlist-remove", i])
            shift = sum(1 for i in idx if i < nxt)
            p.items = [it for it in items if it.get("post_id") != pid]
            new = nxt - shift if pos in idx else pos - sum(1 for i in idx if i < pos)
            if not hasattr(p, "arrive_msg"):
                p.arrive_msg = {}
            p.st["playlist-pos"] = p.st["last-pos"] = new
            p.msg = msg; p.arrive_msg[new] = msg
            p.paint(force=True)
            self.log(f"viewer: post {pid} taken out of the playlist ({len(idx)} item(s)), now at item {new + 1}/{len(p.items)}")
            return new

    def key(self, k):
        """True when the key was handled here (do not forward it to mpv)."""
        it = self.painter.current()
        if it and k in ("a", "A", "d", "D") and it.get("kind") == "photo":
            return True  # a/d seek videos only; on photos they do nothing
        if it and k in ("z", "Z"):
            if it.get("kind") != "photo":
                return True  # videos: ignored
            p = self.painter
            g = getattr(p, "geom", None) or (p.cols, p.rows, 0, 0, None)
            normal, large = photo_boxes(it, *g)
            if normal[2:4] == large[2:4]:  # no bigger picture possible
                p.st["can_large"] = False; p.msg = "already at max size"; p.paint(force=True); return True
            on = not p.st.get("large")
            p.st["large"] = on
            for c in item_props(it, *g, large=on):
                self.send(c)
            p.paint(force=True)
            return True
        if not it or not it.get("post_id"):
            return False
        pid = it["post_id"]
        if k in ("r", "R") and self.remove:
            if pid in self.busy:
                return True
            self.busy.add(pid)
            who = f"@{it['handle']}" if it.get("handle") else "author"
            self.log(f"viewer r: remove #{it.get('n')} {who} requested")
            last = self.drop_post(pid, f"removing {who} …") == "last"  # advance NOW; mute/hide never hold the viewer
            def go():
                try:
                    go_()
                finally:
                    if last:  # nothing left to show: close the viewer, back to the (rebuilt) search view
                        self.log(f"viewer r: #{it.get('n')} was the last post with media, closing the viewer")
                        self.send(["quit"])
            def go_():
                import threading
                box = {}
                def work():
                    try:
                        box["msg"] = self.remove(it) or f"{who} muted, post hidden"
                    except Exception as e:
                        box["err"] = e
                w = threading.Thread(target=work, daemon=True); w.start(); w.join(self.timeout)
                if w.is_alive():
                    self.log(f"viewer r: mute {who} still running after {self.timeout:.0f}s (continues in background)")
                    self._say(f"{who}: mute still pending"); return
                if "err" in box:
                    e = box["err"]
                    self.log(f"viewer r: remove #{it.get('n')} failed ({type(e).__name__}: {e})")
                    self._say(f"remove {who} failed ({type(e).__name__})"); return
                self.log(f"viewer r: {box['msg']}")
                self._say(f"✓ {box['msg']}")
            self.run(go); return True
        if k in ("t", "T") and self.popup:
            self.log(f"viewer t: filter popup for #{it.get('n')}")
            self.popup(it, self.painter.pos())
            self.send(["quit"]); return True
        return False


class KeyReader:
    """Reads the real terminal in raw mode (no echo) while mpv runs and forwards keys to mpv as IPC
    `keypress` commands, so the input-conf bindings (←/→, space, arrows, m, l, q/Esc) apply. mpv itself does
    not read the terminal (its stdout is a pipe)."""
    ESC_WAIT = 0.05

    QUIT_KEYS = ("q", "Q", "ESC")

    def __init__(self, fd, send, intercept=None, on_quit=None):
        self.fd, self.send, self.intercept = fd, send, intercept
        self.on_quit = on_quit  # on_quit(hard): Ctrl+C = hard (quit now, escalate); q/Esc = quit with escalation
        self.stop_r, self.stop_w = os.pipe()
        import threading
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        import select
        rest = b""
        while True:
            try:
                ready, _, _ = select.select([self.fd, self.stop_r], [], [], self.ESC_WAIT if rest else None)
                if self.stop_r in ready:
                    break
                if not ready:  # nothing followed: a lone ESC is the Esc key; other partial input is dropped
                    if rest == b"\x1b":
                        self.forward("ESC")
                    rest = b""; continue
                data = os.read(self.fd, 1024)
                if not data:
                    break
                if b"\x03" in data and self.on_quit:  # ISIG is off: Ctrl+C is ours to handle, never lost
                    self.on_quit(True); rest = b""; continue
                keys, rest = parse_keys(rest + data)
                for k in keys:
                    self.forward(k)
            except Exception as e:
                log_exc(e); rest = b""
                import time; time.sleep(0.05)

    def forward(self, k):
        if self.intercept and self.intercept(k):
            return
        try:
            self.send(["keypress", k])
        finally:
            if k in self.QUIT_KEYS and self.on_quit:
                self.on_quit(False)

    def stop(self):
        try:
            os.write(self.stop_w, b"x")
        except OSError:
            pass
        self.thread.join(timeout=2)
        for f in (self.stop_r, self.stop_w):
            try:
                os.close(f)
            except OSError:
                pass


def restore_terminal(run=subprocess.run, out=None):
    """After mpv: sane tty modes, leave mpv's alt screen, show the cursor, reset colors."""
    out = out or sys.stdout
    try:
        t = open("/dev/tty")
    except OSError:
        t = None
    try:
        from .secure import safe_env
        run(["stty", "sane"], stdin=t, check=False, env=safe_env())
    except Exception:
        pass
    finally:
        if t:
            t.close()
    try:
        # end any unterminated sixel/DCS string, reset attributes + scroll region, show cursor,
        # leave mpv's alt screen and clear, so Textual repaints onto a clean terminal
        if out is sys.stdout:  # the viewer was drawn on the tty: clean the same terminal (Textual may own sys.stdout)
            try:
                with open("/dev/tty", "w") as tt:
                    tt.write(LEAVE_VIEWER); tt.flush()
            except OSError:
                out.write(LEAVE_VIEWER); out.flush()
        else:
            out.write(LEAVE_VIEWER); out.flush()
    except Exception:
        pass
    try:
        import termios
        with open("/dev/tty") as t:
            termios.tcflush(t.fileno(), termios.TCIFLUSH)  # drop stray keys / terminal replies
    except Exception:
        pass


def url_forbidden(url, head=None):
    """True if the CDN answers 403 (expired signed URL)."""
    try:
        if head is None:
            import requests
            head = lambda u: requests.head(u, allow_redirects=True, timeout=6).status_code
        return head(url) == 403
    except Exception:
        return False


def run_mpv(url, cfg, run=subprocess.run, which=shutil.which, size=None, env=None, tty="/dev/tty", variants=None,
            on_like=None, liked=None, media=None, posts=None, start_n=None, state=None, actions=None, start_sub=1):
    """Show url (or a whole post's `media` as a playlist) in this terminal. mpv reads keys from the real tty
    (xbot reads the tty raw and forwards keys as IPC keypresses); ←/→ browse, q/Esc quit; l likes (on_like). The controls line is painted by xbot in the
    rows reserved below the picture. Returns 'mpv', 'missing' (mpv not installed) or 'empty' (nothing playable)."""
    import socket, threading
    if not which("mpv"):
        return "missing"
    cols, rows, xp, yp = (tuple(size) + (0, 0))[:4] if size else term_size()
    if not size:  # one shared pixel size for photos and videos: the real text area, not a 100%-DPI / fallback guess
        rep = query_term_px(tty) if tty else (0, 0, 0, 0)
        xp, yp = resolve_px(cols, rows, xp, yp, rep, sixel_scale=getattr(cfg, "sixel_scale", "auto"))
    vo = resolve_vo(getattr(cfg, "video_vo", "auto"), env, pixels_known=bool(xp and yp))
    max_h = yp or rows * (probed_cell() or (10, 20))[1]  # stream quality only (layout uses cell_px)
    start = 0
    if posts is not None:  # whole list: [(n, post)]; opens at post start_n's first item, ←/→ cross posts
        items = posts_playlist(posts, max_h=max_h)
        start = start_index(items, start_n)
        start = min(len(items) - 1, start + max(0, start_sub - 1)) if items else 0
    elif media is not None:
        items = playlist(media, max_h=max_h)
    else:
        items = _items(url)
        if variants and len(items) == 1:  # sharpest stream that fits the terminal's pixel height
            items[0]["url"] = best_variant(variants, max_h=max_h) or items[0]["url"]
    if not items:
        return "empty"
    r, w = os.pipe()
    tin = tout = None
    ours, theirs = socket.socketpair()
    th = proxy = keys = None
    pr = pw = None
    try:
        os.write(w, (INPUT_CONF + (LIKE_CONF if on_like else "")).encode()); os.close(w); w = None
        try:
            tin = open(tty, "rb", buffering=0) if tty else None
            tout = open(tty, "wb", buffering=0) if tty else None
        except OSError:
            tin = tout = None
        def out(b, o=tout):
            if o:
                write_all(o.fileno(), b)
        pr, pw = os.pipe()
        proxy = TermProxy(pr, out); proxy.thread.start()
        painter = StatusPainter(items, cols, rows, write=proxy.submit, liked=liked, start=start)
        if state is not None:
            state["painter"] = painter
        geom = (cols, rows, xp, yp)
        painter.geom = (cols, rows, xp, yp, None)
        if items and items[start].get("kind") == "photo":
            n_, l_ = photo_boxes(items[start], *painter.geom)
            painter.st["can_large"] = l_[2:4] != n_[2:4]
        slock = threading.Lock()  # IPC socket shared by the watcher and the key reader
        stopper = Stopper(lambda c: ipc_send(c))
        if state is not None:
            state["stopper"] = stopper
        th = threading.Thread(target=ipc_loop, args=(ours, on_like),
                              kwargs={"painter": painter, "send_lock": slock,
                                      "on_hung": lambda: stopper.stop(ipc=False)},  # watchdog: mpv stopped answering
                              daemon=True); th.start()
        argv = mpv_argv(items, vo, getattr(cfg, "video_audio", "off"), cols, rows, input_fd=r, xpx=xp, ypx=yp,
                        ipc_fd=theirs.fileno(), start=start, scale=getattr(cfg, "video_scale", VIDEO_SCALE))
        from .secure import safe_env
        import json as _json
        def ipc_send(cmd):
            try:
                if not slock.acquire(timeout=IPC_TIMEOUT):
                    return
                try:
                    ours.sendall((_json.dumps({"command": cmd}) + "\n").encode())  # socket has IPC_TIMEOUT
                finally:
                    slock.release()
            except (OSError, ValueError):
                pass
        if vo == "sixel":
            sc = getattr(cfg, "video_scale", VIDEO_SCALE)
            painter.on_move = lambda it: [ipc_send(c) for c in item_props(it, *geom, None, sc)]
        if tout:
            out((MOUSE_OFF + ENTER_VIEWER).encode())  # no mouse/focus/paste reports; viewer in the alt screen
        saved = None
        if tin:
            try:
                import termios, tty as _tty
                saved = termios.tcgetattr(tin.fileno()); input_raw(tin.fileno())  # keys raw, output untouched
            except Exception:
                saved = None
            pa = PostActions(painter, ipc_send, **(actions or {}))  # z zoom always; r / t with actions
            if state is not None:
                state["actions"] = pa
            keys = KeyReader(tin.fileno(), ipc_send, intercept=pa.key if pa else None,
                             on_quit=lambda hard: stopper.stop(ipc=True)); keys.thread.start()
        try:
            err = stderr_log()
            try:
                # stderr NOT to the terminal: a decoder warning written by another mpv thread in the middle
                # of a sixel frame ends the DCS and the rest of the frame is printed as text
                runner = (lambda a, **kw: run_proc(a, stopper, **kw)) if run is subprocess.run else run
                res = runner(argv, pass_fds=(r, theirs.fileno()), env=mpv_env(), stdout=pw, stderr=err,
                          stdin=subprocess.DEVNULL)  # no API keys, no GUI; frames via the proxy, keys via IPC
            finally:
                if err not in (None, subprocess.DEVNULL):
                    err.close()
        finally:
            if keys:
                keys.stop()
            if saved is not None:
                try:
                    import termios
                    termios.tcsetattr(tin.fileno(), termios.TCSANOW, saved)
                    termios.tcflush(tin.fileno(), termios.TCIFLUSH)
                except Exception:
                    pass
        if state is not None:
            state["rc"] = getattr(res, "returncode", None)
    finally:
        if pw is not None:
            os.close(pw)  # proxy sees EOF once mpv is gone
        if proxy:
            proxy.thread.join(timeout=3)
        if pr is not None:
            os.close(pr)
        os.close(r)
        if w is not None:
            os.close(w)
        for t in (tin, tout):
            if t:
                t.close()
        for sck in (theirs, ours):
            try:
                sck.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sck.close()
        if th:
            th.join(timeout=2)
        if state is not None and th is not None:
            state["last"] = state["painter"].current()
        restore_terminal(run)
    return "mpv"
