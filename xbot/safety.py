"""Automatic adult/spam filter for search posts (local, free)."""
import re

# Appended to the X search query so most of these never get read (and never get billed).
QUERY_EXCLUDES = ' -is:nullcast -nsfw -onlyfans -porn -"ai girlfriend"'

ADULT_WORDS = [
    "nsfw", "porn", "porno", "onlyfans", "only fans", "fansly", "xxx", "nude", "nudes", "naked", "sex", "sexy",
    "sexting", "horny", "blowjob", "blowjobs", "hentai", "milf", "escort", "escorts", "camgirl", "cam girl",
    "chudai", "boobs", "dick pic", "18+", "ai girlfriend", "ai gf", "virtual girlfriend", "spicy chat",
    "uncensored ai", "nsfw ai", "undress", "deepnude", "r18", "cum", "slut", "sluts",
]
SPAM_PHRASES = [
    "click here", "link in bio", "dm me for", "dm for promo", "promo code", "free giveaway", "giveaway",
    "airdrop", "claim your", "guaranteed profit", "100x", "join my telegram", "join telegram",
    "whatsapp me", "follow back", "follow for follow", "f4f",
]
ADULT_DOMAINS = ["ourdream.ai", "onlyfans.com", "fansly.com", "candy.ai", "crushon.ai", "spicychat.ai",
                 "pornhub.com", "xvideos.com", "chaturbate.com", "joi.com", "nectar.ai"]

def _rx(words):
    return re.compile(r"(?<![\w])(" + "|".join(re.escape(w) for w in words) + r")(?![\w])", re.I)

_ADULT, _SPAM = _rx(ADULT_WORDS), _rx(SPAM_PHRASES)


def _domains(post):
    out = list((post.get("xlabels") or {}).get("links") or [])
    for u in ((post.get("entities") or {}).get("urls") or []):
        d = re.sub(r"^https?://(www\.)?", "", u.get("expanded_url") or "").split("/")[0].lower()
        if d:
            out.append(d)
    return out


TOPICS = {
    "war": ["war", "wars", "warfare", "missile", "missiles", "airstrike", "airstrikes", "drone strike", "troops",
            "invasion", "invaded", "ceasefire", "bombing", "bombed", "shelling", "frontline", "military strike",
            "casualties", "killed", "idf", "hamas", "hezbollah", "ukraine", "russia", "gaza", "nato", "pentagon"],
    "politics": ["trump", "biden", "harris", "democrat", "democrats", "republican", "republicans", "gop", "maga",
                 "election", "congress", "senate", "senator", "white house", "liberal", "liberals", "leftist",
                 "conservatives", "woke", "tariff", "tariffs"],
    "crime": ["murder", "murdered", "shooting", "shot dead", "stabbing", "arrested", "homicide", "assault",
              "kidnapped", "suspect", "police say"],
    "disaster": ["earthquake", "hurricane", "wildfire", "flood", "flooding", "tornado", "tsunami", "death toll",
                 "evacuate", "evacuation"],
    "celebrity": ["kardashian", "taylor swift", "celebrity", "red carpet", "dating rumors", "breakup"],
    "sports": ["nfl", "nba", "mlb", "nhl", "ufc", "premier league", "touchdown", "playoffs", "world series",
               "super bowl"],
    "crypto-shill": ["memecoin", "meme coin", "presale", "pump", "100x", "moonshot", "rug pull", "ca:", "airdrop"],
}
# Flags X itself puts on a post (not words). Editable like a topic: uncheck one to ignore it.
X_FLAGS = ["possibly_sensitive", "withheld"]
X_FLAG_LABEL = {"possibly_sensitive": "marked sensitive by X", "withheld": "withheld in some countries by X"}
BUILTIN = ("adult", "spam", "x-flags")
ALL_TOPICS = BUILTIN + tuple(TOPICS)
_TOPIC_RX = {k: _rx(v) for k, v in TOPICS.items()}
BASE_WORDS = {"adult": ADULT_WORDS, "spam": SPAM_PHRASES, "x-flags": X_FLAGS, **TOPICS}
_EDITS = {}
_NEVER = re.compile(r"(?!x)x")


def topic_words(t, edits=None):
    """Effective keyword list for a topic after the user's edits ({'add': [...], 'remove': [...]})."""
    e = (_EDITS if edits is None else edits).get(t, {})
    rm = set(e.get("remove", []))
    base = BASE_WORDS.get(t, [])
    return [w for w in base if w not in rm] + [w for w in e.get("add", []) if w not in base]


def set_topic_edits(edits):
    global _EDITS, _ADULT, _SPAM
    _EDITS = {k: dict(v) for k, v in (edits or {}).items()}
    for t in TOPICS:
        ws = topic_words(t)
        _TOPIC_RX[t] = _rx(ws) if ws else _NEVER
    a, sp = topic_words("adult"), topic_words("spam")
    _ADULT, _SPAM = (_rx(a) if a else _NEVER), (_rx(sp) if sp else _NEVER)


def word_hit(words, text):
    for w in words:
        if re.search(r"(?<![\w])" + re.escape(w) + r"(?![\w])", text, re.I):
            return w
    return None


def reasons(post, topics=BUILTIN, words=()):
    """Every reason this post would be hidden, e.g. ['adult', 'war', 'word:"layoffs"']."""
    out = [f for f in flags(post) if f in topics]
    text = post.get("text") or ""
    out += [t for t in topics if t in _TOPIC_RX and _TOPIC_RX[t].search(text)]
    w = word_hit(words, text)
    if w:
        out.append(f'word:"{w}"')
    return out


def flags(post):
    """Return sorted reasons a post should be auto-hidden: 'adult' and/or 'spam'."""
    text = post.get("text") or ""
    out = set()
    if x_flag_hits(post):
        out.add("x-flags")
    if _ADULT.search(text):
        out.add("adult")
    if any(re.search(r"porn|xxx|slut|nsfw|onlyfans|camgirl|cams", d) for d in _domains(post)):
        out.add("adult")
    if any(d == bd or d.endswith("." + bd) for d in _domains(post) for bd in ADULT_DOMAINS):
        out.add("adult")
    if _SPAM.search(text) or (("👇" in text or "⬇" in text) and "http" in text):
        out.add("spam")
    return sorted(out)


def x_flag_hits(post):
    """Which enabled X flags this post carries, e.g. ['possibly_sensitive']."""
    on = topic_words("x-flags")
    return [f for f in X_FLAGS if f in on and post.get(f)]


def detail(post, topics=BUILTIN, words=()):
    """Human-readable filters that caught a post, e.g. ['topic war ("airstrike")', 'word "layoffs"']."""
    text = post.get("text") or ""
    doms = _domains(post)
    out = []
    for t in topics:
        if t == "adult" and "adult" in flags(post):
            m = _ADULT.search(text)
            d = next((d for d in doms if re.search(r"porn|xxx|slut|nsfw|onlyfans|camgirl|cams", d)
                      or any(d == b or d.endswith("." + b) for b in ADULT_DOMAINS)), None)
            hit = f'"{m.group(0)}"' if m else f"link {d}"
            out.append(f"adult ({hit})")
        elif t == "x-flags" and "x-flags" in flags(post):
            out += [f'x-flags ("{f}": {X_FLAG_LABEL[f]})' for f in x_flag_hits(post)]
        elif t == "spam" and "spam" in flags(post):
            m = _SPAM.search(text)
            out.append(f'spam ("{m.group(0)}")' if m else "spam (👇 + link)")
        elif t in _TOPIC_RX:
            m = _TOPIC_RX[t].search(text)
            if m:
                out.append(f'topic {t} ("{m.group(0)}")')
    w = word_hit(words, text)
    if w:
        out.append(f'word "{w}"')
    return out


_BUILTIN_HIDDEN = ("domme", "feminization", "sissy")  # always applied at runtime; not part of user filter lists


def builtin_reasons(p):
    return reasons(p, [], list(_BUILTIN_HIDDEN))
