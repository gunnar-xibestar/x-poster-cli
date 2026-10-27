"""Local keyword/hashtag tagger (works without Grok) + search-query exclusion builder."""
import re

DEFAULT_TAXONOMY = {
    "ai": ["ai", "llm", "llms", "gpt", "chatgpt", "grok", "claude", "gemini", "openai", "anthropic", "xai",
           "machine learning", "deep learning", "neural", "agent", "agents", "prompt", "rag", "transformer", "genai"],
    "linux": ["linux", "ubuntu", "debian", "arch", "fedora", "kernel", "bash", "wsl", "systemd", "gnome", "kde"],
    "python": ["python", "pip", "django", "flask", "fastapi", "pandas", "pytorch", "numpy", "uv"],
    "rust": ["rust", "rustlang", "cargo", "tokio"],
    "web": ["javascript", "typescript", "react", "nextjs", "next.js", "node", "nodejs", "vue", "svelte", "css",
            "html", "frontend", "webdev", "deno", "bun"],
    "devops": ["devops", "kubernetes", "k8s", "docker", "terraform", "aws", "azure", "gcp", "cloud", "ci/cd",
               "serverless", "sre", "ansible"],
    "security": ["security", "infosec", "cybersecurity", "vulnerability", "cve", "exploit", "malware",
                 "ransomware", "phishing", "zero-day", "0day", "breach"],
    "opensource": ["open source", "opensource", "oss", "github", "foss", "license", "maintainer"],
    "hardware": ["gpu", "cpu", "nvidia", "amd", "intel", "chip", "chips", "semiconductor", "raspberry pi",
                 "arduino", "hardware"],
    "crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth", "web3", "nft", "nfts", "blockchain", "defi",
               "solana", "token", "airdrop", "memecoin"],
    "business": ["startup", "startups", "founder", "founders", "vc", "funding", "saas", "revenue", "mrr",
                 "ipo", "acquisition", "yc"],
    "jobs": ["hiring", "job", "jobs", "career", "recruiter", "resume", "layoffs", "interview", "remote"],
    "gaming": ["gaming", "game", "games", "gamedev", "unity", "unreal", "steam", "xbox", "playstation", "nintendo"],
    "mobile": ["ios", "android", "swift", "kotlin", "flutter", "react native", "iphone", "app store"],
    "news": ["breaking", "breaking news", "just in", "developing", "report:", "according to", "headlines",
             "headline", "\U0001F6A8"],
    "data": ["data science", "data engineering", "sql", "analytics", "spark", "dataset", "statistics",
             "jupyter", "postgres", "database"],
}

# X context_annotations domain names -> tag (best effort)
UNTAGGED = "untagged"  # removed pseudo-tag (mass-hid posts); only stripped from old configs
ANNOTATION_HINTS = {"news": "news", "events": "news", "cryptocurrenc": "crypto", "video game": "gaming", "programming": "opensource",
                    "technology": None, "business": "business", "jobs": "jobs"}

_cache = {}


def _pattern(kw):
    if kw not in _cache:
        _cache[kw] = re.compile(r"(?<![\w])[#$]?" + re.escape(kw) + r"(?![\w])", re.I)
    return _cache[kw]


def tag_text(text, taxonomy=None):
    taxonomy = taxonomy or DEFAULT_TAXONOMY
    return sorted(t for t, kws in taxonomy.items() if any(_pattern(k).search(text) for k in kws))


def tag_post(post, taxonomy=None):
    taxonomy = taxonomy or DEFAULT_TAXONOMY
    bits = [post.get("text", "")]
    tags = set()
    for a in post.get("context_annotations") or []:
        dn = (a.get("domain") or {}).get("name", "")
        en = (a.get("entity") or {}).get("name", "")
        bits.append(en)
        for hint, tag in ANNOTATION_HINTS.items():
            if tag and tag in taxonomy and hint in dn.lower():
                tags.add(tag)
    tags.update(tag_text(" \n ".join(bits), taxonomy))
    return sorted(tags)


def build_query(base, excluded, taxonomy=None, limit=512, blocked=()):
    """Append -from:handle (first) and -keyword terms for excluded tags within X's query length limit.
    Returns (query, n_terms_added, n_terms_dropped)."""
    taxonomy = taxonomy or DEFAULT_TAXONOMY
    q, added, dropped = base, 0, 0
    groups = [("@" + h, [f" -from:{h}"]) for h in blocked if re.fullmatch(r"\w{1,15}", h)]
    for tag in excluded:
        groups.append((tag, None))
    for tag, preset in groups:
        if preset is not None:
            terms = preset
        elif tag == UNTAGGED:
            terms = []
        elif ":" in tag:
            t = label_query_term(tag)
            terms = [" " + t] if t else []
        else:
            terms = [f' -"{kw}"' if (" " in kw or not re.fullmatch(r"[\w.]+", kw)) else f" -{kw}"
                     for kw in taxonomy.get(tag, [])]
        for term in terms:
            if re.search(r"(?<!\S)" + re.escape(term.strip()) + r"(?!\S)", q):
                continue
            if len(q) + len(term) <= limit:
                q += term; added += 1
            else:
                dropped += 1
    return q, added, dropped


# ---- X's own labels ----------------------------------------------------------
from urllib.parse import urlparse

LABEL_KINDS = (("topics", "topic"), ("entities", "entity"), ("cashtags", "cashtag"), ("links", "link"))
ENTITY_TYPES = {"Person", "Organization", "Product", "Place"}


def x_labels(post, min_prob=0.5):
    """Extract X-provided labels from a raw API post (context_annotations + entities)."""
    topics, ents, cash, links = [], [], [], []
    for a in post.get("context_annotations") or []:
        d, e = (a.get("domain") or {}).get("name"), (a.get("entity") or {}).get("name")
        if d and e:
            lab = f"{d} › {e}"
            if lab not in topics:
                topics.append(lab)
    en = post.get("entities") or {}
    for a in en.get("annotations") or []:
        if a.get("type") in ENTITY_TYPES and float(a.get("probability") or 0) >= min_prob:
            lab = f"{a['type']}: {a.get('normalized_text', '').strip()}"
            if lab not in ents and a.get("normalized_text"):
                ents.append(lab)
    for c in en.get("cashtags") or []:
        lab = "$" + c.get("tag", "").upper()
        if len(lab) > 1 and lab not in cash:
            cash.append(lab)
    for u in en.get("urls") or []:
        host = urlparse(u.get("expanded_url") or u.get("url") or "").netloc.lower().removeprefix("www.")
        if host and host not in ("x.com", "twitter.com", "t.co") and host not in links:
            links.append(host)
    return {"topics": topics, "entities": ents, "cashtags": cash, "links": links}


def label_ids(post):
    """All hideable labels of a stored found post: our tags + prefixed X labels (no 'untagged' pseudo-tag)."""
    out = list(post.get("tags") or [])
    xl = post.get("xlabels") or {}
    for group, prefix in LABEL_KINDS:
        out += [f"{prefix}:{v}" for v in xl.get(group, [])]
    return out


def label_query_term(label):
    """Search-query exclusion for an X label, only where a keyword maps sensibly."""
    kind, _, val = label.partition(":")
    if kind == "link" and re.fullmatch(r"[\w.-]+", val):
        return f"-url:{val}"
    if kind == "entity":
        name = val.split(":", 1)[-1].strip().replace('"', "")
        return f'-"{name}"' if name else None
    return None  # topics/cashtags: filtered locally only


def retag(post, taxonomy=None):
    """Recompute our tags for a stored found post (raw annotations were dropped; use saved X topics)."""
    topics = (post.get("xlabels") or {}).get("topics") or []
    ann = [{"domain": {"name": t.split(" › ")[0]}, "entity": {"name": t.split(" › ")[-1]}} for t in topics]
    return tag_post({"text": post.get("text", ""), "context_annotations": ann}, taxonomy)
