"""Signal ①, the sources: where a new name is said first.

x_new    names in the last day's posts of the accounts in config.json ("x_accounts")
         that none of those accounts has used in the last VOCAB_DAYS. Posts come from
         AIsa, or from "posts_file" when you already have them. The vocabulary is kept
         in the state directory; the first run only builds it.
hf_new   models that entered Hugging Face's trending top HF_TOP since the last run (the
         public API, no key). Quantised and fine-tuned copies of one model are grouped
         under its base name.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import UA, aisa, snap
from .i18n import t
from .terms import STOP, _drop_nested, names

LOOKBACK_HOURS = 30          # meant to run every 8 hours; a name enters the vocabulary the run it is
                             # reported, so the overlap repeats nothing and covers missed runs
VOCAB_DAYS = 60
X_MIN_LIKES = 100            # a name only one account used needs this much attention,
PER_POST = 3                 # and must look like a name; one post yields at most this many
HF_TOP, HF_FETCH = 50, 100   # entering the top 50 against the last run's top 100
TOP = 25


def accounts(cfg: dict) -> list[str]:
    x = cfg["x_accounts"]
    return list(dict.fromkeys(x.get("labs", []) + x.get("bloggers", [])))


def _posted(post: dict) -> datetime | None:
    """When a post was written. AIsa and X use `createdAt` (`Tue Oct 13 08:00:00 +0000 2026`;
    a single-digit day is space-padded, `Mon Oct  5 ...`); a file may use ISO 8601 in
    `created` or `created_at` instead.
    No timezone means UTC. Unreadable times are None: the post still joins the vocabulary,
    and novel_names does not report it."""
    raw = post.get("createdAt") or post.get("created_at") or post.get("created")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = " ".join(raw.split())
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _account(post: dict, fallback: str = "") -> str:
    who = fallback or post.get("account") or post.get("userName") or post.get("username") or ""
    return str(who).lstrip("@")


def _likes(post: dict) -> int:
    if "likes" in post:
        raw = post["likes"]
    elif "likeCount" in post:
        raw = post["likeCount"]
    else:
        raw = (post.get("public_metrics") or {}).get("like_count", 0)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _as_post(post: dict, account: str = "") -> dict | None:
    """One post in the shape novel_names reads. `account` wins when the caller already
    knows it (the AIsa query, or the key of a per-account dump)."""
    if not isinstance(post, dict):
        return None
    who = _account(post, account)
    if not who:
        return None
    url = post.get("url") or ""
    if not url and post.get("id"):
        url = f"https://x.com/{who}/status/{post['id']}"
    return {"account": who, "text": post.get("text") or "", "likes": _likes(post), "url": url, "created": _posted(post)}


def _bundles(raw) -> list[tuple[str, dict]]:
    """(account hint, tweet) from the shapes a posts file may take."""
    if isinstance(raw, list):
        return [("", item) for item in raw]
    if not isinstance(raw, dict):
        raise ValueError("posts file must be a JSON array, or an object keyed by account")
    if isinstance(raw.get("text"), str):
        return [("", raw)]
    if isinstance(raw.get("posts"), list):
        return [("", item) for item in raw["posts"]]
    if isinstance(raw.get("data"), list):
        users = {u.get("id"): u.get("username", "")
                 for u in ((raw.get("includes") or {}).get("users") or []) if isinstance(u, dict)}
        return [(users.get(item.get("author_id"), "") if isinstance(item, dict) else "", item) for item in raw["data"]]
    out = []
    for account, body in raw.items():
        if isinstance(body, list):
            tweets = body
        elif isinstance(body, dict):
            data = body.get("data")
            tweets = (data.get("tweets") if isinstance(data, dict) else None) or body.get("tweets") or []
        else:
            tweets = []
        out.extend((str(account), tw) for tw in tweets)
    return out


def load_posts(path: Path) -> list[dict]:
    """Posts already fetched, so the X signal can run without AIsa.

    A JSON array of posts, or an object keyed by account. Each post needs an account
    (`account`, `userName` or `username`) and text. See `_posted` for the time.
    `likes` may be `likeCount`. The object AIsa returns per account
    (`{"data": {"tweets": [...]}}`) is accepted, as is an X API payload
    (`data` plus `includes.users`).
    """
    posts = []
    for account, tw in _bundles(json.loads(Path(path).read_text())):
        row = _as_post(tw, account)
        if row and row["text"].strip():
            posts.append(row)
    return posts


def _for_accounts(posts: list[dict], handles: list[str]) -> list[dict]:
    """Posts by the configured accounts, spelled as in the config. No list means every
    account in the file: a posts file is enough on its own."""
    if not handles:
        return posts
    wanted = {h.lower(): h for h in handles}
    return [{**p, "account": wanted[p["account"].lower()]} for p in posts if p["account"].lower() in wanted]


def novel_names(posts: list[dict], vocab: dict[str, str], now: datetime) -> list[dict]:
    """Names in recent posts that are not in the vocabulary, with who said them.
    `posts` items: {"account", "text", "likes", "url", "created"}."""
    since = now - timedelta(hours=LOOKBACK_HOURS)
    found: dict[str, dict] = {}
    for p in posts:
        if p["created"] is None or p["created"] < since or p["text"].startswith("RT @"):
            continue
        strong = names(p["text"], strong=True)
        for term in names(p["text"]):
            if term in vocab:
                continue
            row = found.setdefault(term, {"term": term, "sources": set(), "likes": 0, "examples": [], "posts": [], "strong": False})
            if p["account"] not in row["sources"]:
                row["likes"] += p["likes"]
                row["examples"].append(f"@{p['account']}: {' '.join(p['text'].split())[:80]}")
                # The whole post and its link, for the mail: the reader checks the source in one click.
                row["posts"].append({"account": p["account"], "text": " ".join(p["text"].split()),
                                     "url": p.get("url", ""), "likes": p["likes"]})
            row["sources"].add(p["account"])
            row["strong"] |= term in strong
    rows = [r for r in found.values()
            if len(r["sources"]) >= 2 or (r["strong"] and r["likes"] >= X_MIN_LIKES)]
    # One viral post must not fill the report: keep its PER_POST longest single-account names.
    per_post: dict[str, int] = {}
    kept = []
    for r in sorted(rows, key=lambda r: (-len(r["sources"]), -len(r["term"]))):
        if len(r["sources"]) == 1:
            post = r["examples"][0]
            if per_post.get(post, 0) >= PER_POST:
                continue
            per_post[post] = per_post.get(post, 0) + 1
        kept.append(r)
    for r in kept:
        r.pop("strong")
        r["recent"] = len(r["sources"])
        r["note"] = t("note_x", n=r["recent"], likes=r["likes"])
        r["sources"] = sorted(r["sources"])
    kept.sort(key=lambda r: (-r["recent"], -r["likes"]))
    return _drop_nested(kept)[:TOP]


def _settle(posts: list[dict], state: Path) -> dict:
    """Novel names against the vocabulary, then every name in these posts joins it.
    No posts (a failed or empty read) leaves yesterday's vocabulary where it is."""
    path = state / "x_vocab.json.gz"
    vocab: dict[str, str] | None = snap.load(path)
    first_run = vocab is None
    rows = [] if first_run else novel_names(posts, vocab, datetime.now(timezone.utc))
    vocab = vocab or {}
    today, cutoff = date.today().isoformat(), (date.today() - timedelta(days=VOCAB_DAYS)).isoformat()
    for p in posts:
        for term in names(p["text"]):
            vocab[term] = today
    if posts:
        snap.save(path, {term: d for term, d in vocab.items() if d >= cutoff})
    return {"first_run": first_run, "terms": rows}


def _from_aisa(handles: list[str]) -> tuple[list[dict], dict]:
    data, cost = aisa.call_all([{"call_id": h, "tool": "get_twitter_user_last_tweets", "arguments": {"userName": h}}
                                for h in handles])
    posts = []
    for h in handles:
        for tw in ((data.get(h) or {}).get("data") or {}).get("tweets") or []:
            row = _as_post(tw, h)
            if row:
                posts.append(row)
    return posts, {"accounts": len(handles), "answered": len(data), "posts": len(posts), "cost_micros": cost}


def x_new(cfg: dict, state: Path) -> dict:
    handles = accounts(cfg)
    posts_file = (cfg["x_accounts"].get("posts_file") or "").strip()
    if posts_file:
        posts = _for_accounts(load_posts(cfg["_dir"] / posts_file), handles)
        meta = {"accounts": len(handles) or len({p["account"] for p in posts}),
                "answered": len({p["account"] for p in posts}), "posts": len(posts),
                "cost_micros": 0, "posts_file": Path(posts_file).name}
    elif not handles:
        return {"skipped": True}
    else:
        posts, meta = _from_aisa(handles)
    return {**meta, **_settle(posts, state)}


_HF_NOISE = re.compile(r"[-_.](gguf|ggml|awq|gptq|fp8|fp16|bf16|int[48]|mlx|exl2|onnx|uncensored|abliterated|"
                       r"instruct|chat|it|base|preview|turbo|lora|q\d\w*|\d+(\.\d+)?b|a\d+(\.\d+)?b)(?=[-_.]|$)", re.I)


def base_name(model_id: str) -> str:
    """'abenzerps/Qwen-Image-2.1-Uncensored-GGUF' -> 'qwen image 2.1'."""
    name = model_id.split("/")[-1]
    for _ in range(4):   # suffixes stack: -27B-Instruct-GGUF
        name = _HF_NOISE.sub("", name)
    return re.sub(r"[-_]+", " ", name).strip().lower()


def hf_new(cfg: dict, state: Path) -> dict:
    req = urllib.request.Request(f"https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit={HF_FETCH}",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as res:
        models = json.load(res)
    path = state / "hf_top.json.gz"
    before = snap.load(path)
    if models:
        snap.save(path, [m["id"] for m in models])
    if before is None:
        return {"models": len(models), "first_run": True, "terms": []}
    seen = set(before)
    grouped: dict[str, dict] = {}
    for rank, m in enumerate(models[:HF_TOP], 1):
        if m["id"] in seen:
            continue
        term = base_name(m["id"])
        if not term or term in STOP:
            continue
        g = grouped.setdefault(term, {"term": term, "rank": rank, "copies": 0, "examples": []})
        g["copies"] += 1
        g["examples"].append(f"{m['id']} ({m.get('pipeline_tag') or '?'}, ♥{m.get('likes', 0)})")
    rows = sorted(grouped.values(), key=lambda g: g["rank"])
    for g in rows:
        g["recent"] = g["copies"]
        g["note"] = t("note_hf", rank=g["rank"]) + (t("note_hf_copies", n=g["copies"]) if g["copies"] > 1 else "")
    return {"models": len(models), "first_run": False, "terms": rows[:TOP]}
