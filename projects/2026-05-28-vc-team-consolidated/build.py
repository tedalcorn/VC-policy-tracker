#!/usr/bin/env python3
"""Consolidate VC team policy recommendations into themes.

Reads docs/data/{policy_tracking.json, policy_scores.json, articles.json}
plus config/institutional_authors.csv, filters to VC team authors with AI
confidence >= 3, clusters near-duplicate asks via TF-IDF cosine, and emits
recommendations.html with citations as hyperlinked parentheticals.

Rerun anytime to refresh after the policy data updates.
"""
import csv, json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent            # policy-tracker/
DATA = ROOT / "docs" / "data"
THRESHOLD = 0.35                     # cosine sim for "matching" recs

inst = {r["author"].strip()
        for r in csv.DictReader(open(ROOT / "config" / "institutional_authors.csv"))
        if r["author"].strip()}

policy   = json.load(open(DATA / "policy_tracking.json"))
scores   = json.load(open(DATA / "policy_scores.json"))
articles = {a["slug"]: a for a in json.load(open(DATA / "articles.json"))}

recs = []
for slug, p in policy.items():
    sc = scores.get(slug, {})
    try: sv = int(sc.get("score") or 0)
    except: sv = 0
    if sv < 3: continue
    author = p.get("primary_author","") or sc.get("primary_author","")
    if author not in inst: continue
    display = (p.get("rec_summary") or sc.get("policy_ask") or "").strip()
    # Cluster on the AI's policy_ask — more uniform phrasing reveals overlaps
    # that paraphrased rec_summary text would obscure.
    cluster_text = (sc.get("policy_ask") or p.get("rec_summary") or "").strip()
    if not display or not cluster_text: continue
    a = articles.get(slug, {})
    recs.append({
        "slug": slug, "author": author,
        "text": display, "cluster_text": cluster_text,
        "title": p.get("title") or sc.get("title") or a.get("title",""),
        "date":  p.get("published_at") or sc.get("published_at") or a.get("published_at",""),
        "url":   a.get("url") or p.get("url") or f"https://www.vitalcitynyc.org/{slug}/",
        "score": sv,
    })

# EDITORIAL CLUSTERS — curated by reading all VC-team recs.
# TF-IDF cosine missed semantic overlap on this dataset (paraphrasing varies too
# much across same-theme asks). Re-curate when the underlying recs change
# materially. (header, [slugs]) — singletons drop out automatically.
MANUAL_CLUSTERS = [
    ("Federal court should appoint a receiver / remediation manager with broad independent powers over Rikers Island.",
     ["why-the-citys-jails-are-broken",
      "information-suppression-in-nyc-jails",
      "rikers-hearing-june-2023",
      "fixing-new-york-citys-jails-a-federal-receiver-closing-remarks",
      "a-rare-remedy-to-the-persistent-brutality-of-rikers"]),
    ("Close Rikers Island by reducing the jail population to a target floor (~2,200–3,300), with jail used only as a last resort.",
     ["special-report-on-rikers",
      "a-brief-history-of-the-3300-target"]),
    ("Fundamentally restructure NYC jail management — overriding union obstacles, prioritizing violence-reduction and rehabilitation modeled on humane systems abroad.",
     ["liz-glazer-nyc-jails-fatal-cost-of-waiting",
      "could-our-jails-be-a-civic-asset"]),
    ("The next NYPD commissioner — paired with a competent Deputy Mayor for Public Safety — must restore governance standards, organizational integrity, and a sustained crime-fighting strategy.",
     ["what-kind-of-nypd-commissioner-do-we-need",
      "police-commissioner-jessica-tisch-vs-new-york-city-crime-and-corruption"]),
    ("Police should focus on solving serious crime — not running community/social-services programs or chasing quality-of-life enforcement.",
     ["police-become-government",
      "the-false-promise-of-police-crackdowns-in-new-york-city-roosevelt-island-queens-corridor"]),
    ("On subways and public transit, respond with specialized behavioral-health crisis teams and proven policing/social-service strategies — not National Guard or reactive enforcement.",
     ["daniel-penny-jordan-neely-and-all-of-us-in-between",
      "surging-the-guard-wont-safeguard-the-subways"]),
]

slug_to_cluster = {}
cluster_headers = []
for cid, (header, slugs) in enumerate(MANUAL_CLUSTERS):
    cluster_headers.append(header)
    for s in slugs: slug_to_cluster[s] = cid

groups = defaultdict(list)
singletons = []
for i, r in enumerate(recs):
    cid = slug_to_cluster.get(r["slug"])
    if cid is None: singletons.append(i)
    else: groups[cid].append(i)

multi_clusters = [(cluster_headers[cid], groups[cid]) for cid in sorted(groups, key=lambda c: -len(groups[c]))]
singletons.sort(key=lambda i: -datetime.fromisoformat(recs[i]["date"][:10]).timestamp())

def fmtdate(d):
    try: return datetime.fromisoformat(d[:10]).strftime("%b %-d, %Y")
    except: return (d or "")[:10]

# Render
total_themes = len(multi_clusters) + len(singletons)
parts = ['<!doctype html><meta charset="utf-8">',
         '<title>VC team — consolidated policy recommendations</title>',
         '<style>',
         'body{font-family:Georgia,"Times New Roman",serif;max-width:780px;margin:40px auto;padding:0 24px;line-height:1.55;color:#1a1a1a}',
         'h1{font-size:26px;margin-bottom:4px}',
         '.meta{color:#888;font-size:13px;margin-bottom:28px}',
         '.rec{margin:18px 0;padding:14px 16px;border-left:3px solid #c4543a;background:#fbf9f3;border-radius:2px}',
         '.rec.multi{border-left-color:#2c4870;background:#f1f4f8}',
         '.ask{font-size:15px;margin:0 0 8px 0}',
         '.cites{font-size:13px;color:#555}',
         '.cites a{color:#2c4870;text-decoration:none}',
         '.cites a:hover{text-decoration:underline}',
         '.count{display:inline-block;background:#2c4870;color:#fff;font-size:11px;padding:1px 6px;border-radius:8px;margin-right:6px;font-family:sans-serif}',
         'h2.section{font-family:sans-serif;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.08em;margin:32px 0 8px;border-top:1px solid #ddd;padding-top:14px}',
         '</style>',
         '<h1>Consolidated VC team policy recommendations</h1>',
         f'<div class="meta">{len(recs)} recommendations across {len(inst)} institutional authors, '
         f'consolidated into <b>{total_themes}</b> themes &mdash; '
         f'<b>{len(multi_clusters)}</b> with multiple supporting articles, {len(singletons)} singletons.</div>']

PARTICLES = {"de","del","la","von","van","da","di","du","le"}
def lastname(name):
    parts = (name or "").strip().split()
    if not parts: return ""
    if len(parts) >= 2 and parts[-2].lower() in PARTICLES:
        return f"{parts[-2]} {parts[-1]}"
    return parts[-1]

def cite(r):
    title = (r["title"] or "").replace('"','&quot;')
    return (f'<a href="{r["url"]}" target="_blank" rel="noopener" '
            f'title="{r["author"]}">{fmtdate(r["date"])}, {lastname(r["author"])}: &ldquo;{title}&rdquo;</a>')

parts.append('<h2 class="section">Themes with multiple articles</h2>')
for header, idxs in multi_clusters:
    items = sorted([recs[i] for i in idxs], key=lambda r: r["date"])
    cites = ", ".join(cite(r) for r in items)
    parts.append(f'<div class="rec multi">'
                 f'<div class="ask"><span class="count">{len(items)}</span>{header}</div>'
                 f'<div class="cites">({cites})</div></div>')

parts.append('<h2 class="section">Standalone recommendations</h2>')
for i in singletons:
    r = recs[i]
    parts.append(f'<div class="rec"><div class="ask">{r["text"]}</div>'
                 f'<div class="cites">({cite(r)})</div></div>')

out = HERE / "recommendations.html"
out.write_text("\n".join(parts), encoding="utf-8")
print(f"Wrote {out}")
print(f"  {len(recs)} VC-team recs → {total_themes} themes ({len(multi_clusters)} multi-article, {len(singletons)} singletons)")
