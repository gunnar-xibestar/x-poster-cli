"""Slash-command parsing: turns a console line into a Command (name, text, args).

Draft refs: "2" = Suggested replies #2, "m2" = Mentions #2, "@15" = internal draft id.
"""
import re
from dataclasses import dataclass, field

# queue position: "2" = Suggested replies #2, "m2" = Mentions #2; "@15" = internal real draft id (keys)
DRAFT_REF = re.compile(r"^(?:[mM]?\d+|@\d+)$")

COMMANDS = {"pause", "resume", "stop", "align", "post", "reply", "status", "dryrun",
            "approve", "reject", "edit", "topics", "posttopics", "exclude", "include", "excluded", "model", "tick", "help",
            "search", "searchon", "searchoff", "maxresults", "cap", "maxpending", "maxmentions", "clear", "found", "reads", "send", "export", "show", "open", "block", "unblock", "blocked", "mute", "unmute", "muted", "filter", "hidden", "backfill", "mentioners", "share", "style", "limit", "feed"}


@dataclass
class Command:
    name: str
    args: list = field(default_factory=list)
    text: str = ""


class CommandError(ValueError):
    pass


def parse(line: str) -> Command:
    line = line.strip()
    if not line.startswith("/"):
        raise CommandError("commands start with / (try /help)")
    head, _, rest = line[1:].partition(" ")
    name, rest = head.lower(), rest.strip()
    if name not in COMMANDS:
        from .help import suggest
        sg = suggest(name)
        raise CommandError(f"unknown command /{name}" + (f" -- did you mean /{sg}?" if sg else " (try /help)"))
    if name in ("help", "filter", "hidden"):
        return Command(name, text=rest)
    if name == "search" and rest.strip().lower() in ("", "help", "?", "tips"):
        return Command(name, text="help")
    if name in ("align", "post", "posttopics", "model", "search", "exclude", "include"):
        if not rest:
            raise CommandError(f"/{name} needs text")
        return Command(name, text=rest)
    if name == "reply":
        tid, _, text = rest.partition(" ")
        if not (tid.isdigit() or (tid.startswith("#") and tid[1:].isdigit())) or not text.strip():
            raise CommandError("usage: /reply <tweet_id|#n> <text>")
        return Command(name, [tid], text.strip())
    if name == "edit":
        did, _, text = rest.partition(" ")
        if not DRAFT_REF.match(did) or not text.strip():
            raise CommandError("usage: /edit <n|m<n>> <text>  (n = position in Suggested replies, m<n> in Mentions)")
        return Command(name, [did.lower()], text.strip())
    if name in ("approve", "reject"):
        if not DRAFT_REF.match(rest):
            raise CommandError(f"usage: /{name} <n|m<n>>  (n = position in Suggested replies, m<n> in Mentions)")
        return Command(name, [rest.lower()])
    if name == "feed":
        if rest.lower() not in ("", "reset"):
            raise CommandError("usage: /feed  (saved posts left)  ·  /feed reset  (next F5 starts again from the oldest)")
        return Command(name, [rest.lower()] if rest else [])
    if name == "limit":
        if not rest:
            return Command(name, [])
        from .credits import parse_limit
        try:
            return Command(name, [parse_limit(rest)])
        except ValueError as e:
            raise CommandError(f"/limit: {e}")
    if name in ("maxresults", "cap", "maxpending", "maxmentions"):
        try:
            v = float(rest) if name == "cap" else int(rest)
        except ValueError:
            raise CommandError(f"usage: /{name} <number>")
        if name == "maxresults" and not 10 <= v <= 100:
            raise CommandError("X recent search max_results must be 10..100")
        if v < 0:
            raise CommandError("must be >= 0")
        return Command(name, [v])
    if name == "clear":
        if not rest:
            return Command(name, ["feed"])  # bare /clear: wipe the top-left feed display only
        r = {"mentions": "mention", "mention": "mention", "suggested": "search", "suggestions": "search", "search": "search"}.get(rest)
        if not r:
            raise CommandError("usage: /clear [mentions|suggested]")
        return Command(name, [r])
    if name == "style":
        if rest not in ("clear", ""):
            raise CommandError("usage: /style [clear]")
        return Command(name, [rest] if rest else [])
    if name == "found":
        if rest in ("mentions", "mention"):
            return Command(name, ["mention"])
        if rest in ("search", "suggestions"):
            return Command(name, ["search"])
        if rest and not rest.isdigit():
            raise CommandError("usage: /found [n|mentions|search]")
        return Command(name, [int(rest)] if rest else [])
    if name in ("block", "unblock", "mute", "unmute"):
        h = rest.strip().lstrip("@").lower()
        import re as _re
        if not _re.fullmatch(r"\w{1,15}", h):
            raise CommandError(f"usage: /{name} @handle")
        return Command(name, [h])
    if name in ("show", "open"):
        r = rest.lstrip("#")
        if not r.isdigit():
            raise CommandError(f"usage: /{name} <n>  (n from /found)")
        return Command(name, [int(r)])
    if name == "backfill":
        if rest not in ("on", "off"):
            raise CommandError("usage: /backfill on|off")
        return Command(name, [rest == "on"])
    if name == "reads":
        if rest not in ("live", "off", "auto"):
            raise CommandError("usage: /reads live|off|auto")
        return Command(name, [rest])
    if name == "send":
        if rest not in ("live", "dry"):
            raise CommandError("usage: /send live|dry")
        return Command(name, [rest == "dry"])
    if name == "dryrun":
        if rest not in ("on", "off"):
            raise CommandError("usage: /dryrun on|off")
        return Command(name, [rest == "on"])
    return Command(name)
