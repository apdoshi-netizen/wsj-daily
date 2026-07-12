#!/usr/bin/env python3
"""
WSJ Daily generator — runs in GitHub Actions.

Fetch live WSJ headlines (Google News RSS) for 4 slots, ask the Claude API to
pick the best per slot + write a one-line summary, resolve each pick to its
direct wsj.com URL, and write picks.json. The workflow then commits picks.json,
and the Apps Script mailer reads it and emails at 9 AM ET.

Uses curl (present on GitHub runners) for every HTTP call — the method verified
to work against Google News' article/batchexecute endpoints. Requires env var
ANTHROPIC_API_KEY. If the Claude call fails, falls back to a keyword heuristic
so a picks.json is always produced.
"""
import os, sys, re, json, subprocess, urllib.parse, email.utils, datetime
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

MODEL = "claude-haiku-4-5"
SLOTS = [
    ("Macro", '(economy OR inflation OR "Federal Reserve" OR "interest rates" OR jobs OR GDP OR tariffs OR Treasury OR "central bank") site:wsj.com when:2d', 48,
     ["econom", "inflation", "fed", "rate", "jobs", "gdp", "tariff", "treasury", "yield", "central bank", "dollar", "recession"]),
    ("Industry / Company / Transaction", '(merger OR acquisition OR deal OR earnings OR takeover OR IPO OR bankruptcy OR buyout) site:wsj.com when:2d', 48,
     ["merger", "acqui", "deal", "earnings", "takeover", "ipo", "bankrupt", "buyout", "bid", "billion", "stake", "shares"]),
    ("Op-Ed", 'site:wsj.com/opinion when:4d', 96, ["opinion"]),
    ("Tech", 'site:wsj.com/tech when:2d', 48,
     ["ai", "artificial intelligence", "chip", "semiconductor", "software", "tech", "nvidia", "apple", "google", "microsoft", "openai", "meta", "data center"]),
]
NOISE = re.compile(r'(Print Edition|News Archive|Exchange Rate|Roundup: Market Talk|What to Read|WSJ Dollar Index|Latest News and Forecasts)', re.I)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def curl(args):
    return subprocess.run(["curl", "-sL", "--max-time", "30", "-A", UA] + args,
                          capture_output=True, text=True).stdout


def fetch_candidates():
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for key, query, maxage, _kw in SLOTS:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            root = ET.fromstring(curl([url]))
        except Exception:
            out[key] = []; continue
        rows, seen = [], set()
        for it in root.find("channel").findall("item"):
            if (it.findtext("source") or "").strip() != "WSJ":
                continue
            title = re.sub(r"\s*-\s*WSJ\s*$", "", (it.findtext("title") or "").strip())
            if not title or title in seen or NOISE.search(title):
                continue
            try:
                dt = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
            except Exception:
                continue
            if (now - dt).total_seconds() > maxage * 3600:
                continue
            seen.add(title)
            rows.append((dt, title, it.findtext("link")))
        rows.sort(reverse=True)
        out[key] = [{"i": i, "title": t, "ageHrs": round((now - dt).total_seconds() / 3600, 1), "url": u}
                    for i, (dt, t, u) in enumerate(rows[:12])]
    return out


def curate_with_claude(cands):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    slim = {k: [{"i": c["i"], "title": c["title"], "ageHrs": c["ageHrs"]} for c in v] for k, v in cands.items()}
    rubric = (
        "Macro: the story with the broadest cross-asset, market-moving significance "
        "(central banks, major data prints, fiscal/tariff/policy, big rate/FX/oil moves). "
        "Industry/Company/Transaction: one concrete corporate story — a named deal, financing, "
        "material earnings, or major regulatory/legal/product event. "
        "Op-Ed: one substantive opinion column. "
        "Tech: one consequential tech-industry development (AI, chips, big-tech, major product, regulation).")
    user = (
        "Candidate WSJ headlines by slot (newest first; ageHrs = hours old):\n"
        + json.dumps(slim, ensure_ascii=False) +
        "\n\nFor EACH slot pick the ONE headline that best fits that slot's topic per the rubric. "
        "The feeds are noisy — a fresh headline that is off-topic for the slot must NOT be chosen; "
        "topical fit first, then prefer fresher among good fits. The 4 picks must be 4 distinct stories. "
        "Write a summary <=25 words grounded ONLY in the headline. Return ONLY:\n"
        '{"picks":[{"slot":"Macro","i":N,"summary":"..."},'
        '{"slot":"Industry / Company / Transaction","i":N,"summary":"..."},'
        '{"slot":"Op-Ed","i":N,"summary":"..."},{"slot":"Tech","i":N,"summary":"..."}]}')
    payload = json.dumps({"model": MODEL, "max_tokens": 1024,
                          "system": "You are a financial news editor. Follow the rubric and return only JSON.\n\n" + rubric,
                          "messages": [{"role": "user", "content": user}]})
    resp = curl(["-H", "x-api-key: " + key, "-H", "anthropic-version: 2023-06-01",
                 "-H", "content-type: application/json", "--data", payload,
                 "https://api.anthropic.com/v1/messages"])
    text = json.loads(resp)["content"][0]["text"]
    return json.loads(re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.I).strip())["picks"]


def heuristic(cands):
    picks = []
    for key, _q, _m, kw in SLOTS:
        lst = cands.get(key, [])
        chosen = next((c for c in lst if any(k in c["title"].lower() for k in kw)), lst[0] if lst else None)
        picks.append({"slot": key, "i": chosen["i"] if chosen else -1, "summary": chosen["title"] if chosen else ""})
    return picks


def resolve_one(gn):
    m = re.search(r'/articles/([^?]+)', gn)
    if not m:
        return None
    aid = m.group(1)
    page = curl(["-H", "Cookie: CONSENT=YES+", "https://news.google.com/articles/" + aid])
    sg = (re.search(r'data-n-a-sg="([^"]+)"', page) or [None, None])[1]
    ts = (re.search(r'data-n-a-ts="([^"]+)"', page) or [None, None])[1]
    nid = (re.search(r'data-n-a-id="([^"]+)"', page) or [None, None])[1] or aid
    if not (sg and ts):
        return None
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,'
             'null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"%s",%s,"%s"]' % (nid, ts, sg))
    freq = json.dumps([[["Fbv4je", inner, None, "generic"]]])
    resp = curl(["-H", "Content-Type: application/x-www-form-urlencoded;charset=UTF-8", "-H", "Cookie: CONSENT=YES+",
                 "--data", "f.req=" + urllib.parse.quote(freq),
                 "https://news.google.com/_/DotsSplashUi/data/batchexecute"])
    u = re.findall(r'https?://[^"\\]*wsj\.com[^"\\]*', resp)
    return u[0] if u else None


def main():
    cands = fetch_candidates()
    try:
        selections = curate_with_claude(cands)
        print("curation: Claude", file=sys.stderr)
    except Exception as e:
        print("curation: heuristic fallback (" + str(e)[:120] + ")", file=sys.stderr)
        selections = heuristic(cands)

    labels = {k: k for k, _q, _m, _kw in SLOTS}
    picks = []
    for key, _q, _m, _kw in SLOTS:              # keep canonical slot order
        s = next((x for x in selections if x["slot"] == key), None)
        row = None
        if s and s.get("i", -1) >= 0:
            row = next((c for c in cands.get(key, []) if c["i"] == s["i"]), None)
        if not row:
            picks.append({"slot": key, "label": labels[key], "title": "", "url": "",
                          "summary": "No WSJ pick today.", "source": "WSJ"}); continue
        direct = resolve_one(row["url"]) or ""
        print(("OK   " if direct else "FAIL ") + key + ": " + row["title"][:55], file=sys.stderr)
        picks.append({"slot": key, "label": labels[key], "title": row["title"], "url": direct,
                      "summary": (s.get("summary") or "")[:200], "source": "WSJ"})

    date = datetime.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    result = {"date": date, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "picks": picks}
    with open("picks.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
