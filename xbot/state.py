"""Persistent bot state: seen post ids, replied threads, daily spend."""
import json, time
from pathlib import Path

# X pay-per-use rates (docs.x.com / changelog, Apr 20 2026). Estimates only.
COST_POST = 0.015
COST_POST_URL = 0.20
COST_SUMMONED_REPLY = 0.010
COST_READ = 0.005
COST_OWNED_READ = 0.001
COST_MUTE = 0.015    # User Interaction: Create
COST_UNMUTE = 0.010  # Interaction: Delete
COST_USER_LOOKUP = 0.010


class BotState:
    def __init__(self, path: Path = None, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.seen: list = []
        self.replied_threads: list = []
        self.spend: dict = {}  # utc date -> usd
        self.prefill: dict = {}  # post id -> stored Grok draft not yet in the queue (survives restarts)
        self.reply_send_times: list = []  # live API reply sends (max_replies_per_hour)
        self.grok_spend: dict = {}  # utc date -> xAI usd (kept, for est. credits left)
        self.grok_run_spend = 0.0  # xAI usd this session (0 at every start and exit)
        self.x_run_spend = 0.0  # X API usd this session (same rules)
        self.me_id = None  # cached own X user id
        self.spend_log: list = []  # [[unix ts, usd], ...] every live X + Grok charge, last 5 days (never reset on exit)
        self.liked: list = []  # post ids liked via the browser like intent (l): never opened twice
        if self.path and self.path.exists():
            data = None
            for _ in range(3):  # tolerate a torn/partial read: retry, then keep defaults instead of crashing
                try:
                    data = json.loads(self.path.read_text()); break
                except (OSError, ValueError):
                    time.sleep(0.05)
            if isinstance(data, dict):
                self.__dict__.update({k: v for k, v in data.items()
                                      if k in ("seen", "replied_threads", "spend", "reply_send_times", "prefill", "me_id", "liked", "grok_spend", "grok_run_spend", "x_run_spend", "spend_log")})

    def save(self):
        if not self.path:
            return
        self.seen = self.seen[-5000:]
        self.replied_threads = self.replied_threads[-5000:]
        self.liked = self.liked[-5000:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .secure import write_private  # atomic 0600: readers never see a half-written file
        write_private(self.path, json.dumps({k: getattr(self, k) for k in
                                             ("seen", "replied_threads", "spend", "reply_send_times", "prefill", "me_id", "liked", "grok_spend", "grok_run_spend", "x_run_spend", "spend_log")}))

    def today(self):
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))  # X bills per UTC day

    WINDOW_S = 5 * 24 * 3600  # rolling 5 x 24h

    def _log_spend(self, usd):
        if usd:
            self.spend_log.append([round(self.clock(), 3), round(float(usd), 6)])
        self.prune_spend_log()

    def prune_spend_log(self):
        cut = self.clock() - self.WINDOW_S
        self.spend_log = [e for e in (self.spend_log or [])
                          if isinstance(e, (list, tuple)) and len(e) == 2 and e[0] > cut]

    def spent_5d(self):
        """X + Grok API spend in the last 5 x 24 h (persisted per-charge records; not touched by session resets)."""
        cut = self.clock() - self.WINDOW_S
        return round(sum(e[1] for e in (self.spend_log or [])
                         if isinstance(e, (list, tuple)) and len(e) == 2 and e[0] > cut), 6)

    def add_spend(self, usd):
        self._log_spend(usd)
        self.x_run_spend = round(getattr(self, "x_run_spend", 0.0) + usd, 6)
        self.spend = {self.today(): round(self.spend.get(self.today(), 0) + usd, 4)}
        self.save()

    def add_grok_spend(self, usd):
        self._log_spend(usd)
        d = self.today()
        self.grok_spend[d] = round(self.grok_spend.get(d, 0) + usd, 6)
        self.grok_run_spend = round(self.grok_run_spend + usd, 6)
        self.save()

    def grok_spent(self, since=None):
        return sum(v for k, v in self.grok_spend.items() if not since or k >= since)

    def api_run_spend(self):
        return round(self.grok_run_spend + self.x_run_spend, 6)

    def reset_run_spend(self):
        self.grok_run_spend = 0.0
        self.x_run_spend = 0.0
        self.save()

    def spent_today(self):
        return self.spend.get(self.today(), 0.0)

    def reply_sends_last_hour(self):
        now = self.clock()
        self.reply_send_times = [t for t in self.reply_send_times if now - t < 3600]
        return len(self.reply_send_times)

    def note_reply_send(self):
        self.reply_send_times.append(self.clock()); self.save()
