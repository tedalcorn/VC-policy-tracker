#!/usr/bin/env python3
"""Build a durable Vital City author research dataset.

Outputs:
- data/raw/vital_city_posts_with_authors.json
- data/processed/vital_city_author_master.csv
- data/processed/vital_city_author_source_log.csv
- data/processed/vital_city_author_review_queue.csv

The script starts from Vital City's public Ghost API and then applies any
manual overrides stored in config/manual_author_overrides.csv.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CONFIG_DIR = ROOT / "config"

API_KEY = "dd8e178e9ddfc883537e71dd07"
POSTS_URL = "https://vital-city.ghost.io/ghost/api/content/posts/"


@dataclass
class Rule:
    label: str
    patterns: list[str]


CURRENT_PROFESSION_RULES = [
    Rule("house/byline", [r"\binstitutional\b"]),
    Rule(
        "academic",
        [
            r"\bprofessor\b",
            r"\bassistant professor\b",
            r"\bassociate professor\b",
            r"\blecturer\b",
            r"\bfaculty\b",
            r"\bprofessor emeritus\b",
            r"\bdean\b",
            r"\bstudent\b",
            r"\bresearch assistant\b",
            r"\bresearch associate\b",
            r"\bphd candidate\b",
            r"\bdoctoral candidate\b",
            r"\bdoctoral student\b",
            r"\bresearcher\b",
            r"\bresearch methodologist\b",
            r"\bai researcher\b",
            r"\bscholar\b",
            r"\bpostdoctoral\b",
            r"\bdirector of the research and evaluation center\b",
        ],
    ),
    Rule(
        "journalist/media",
        [
            r"\bjournalist\b",
            r"\breporter\b",
            r"\beditor\b",
            r"\bcolumnist\b",
            r"\bwriter\b",
            r"\bhost\b",
            r"\bproducer\b",
            r"\bcritic\b",
            r"\beditorial assistant\b",
            r"\bauthor\b",
        ],
    ),
    Rule(
        "government/public sector",
        [
            r"\bcommissioner\b",
            r"\bdeputy mayor\b",
            r"\bmayor\b",
            r"\bcity council\b",
            r"\bcomptroller\b",
            r"\bagency\b",
            r"\bdepartment\b",
            r"\badministrator\b",
            r"\bchief of staff\b",
            r"\bpublic servant\b",
            r"\bpolice professional\b",
            r"\bdistrict attorney\b",
            r"\bsenior advisor\b",
            r"\bwarden\b",
            r"\bchancellor\b",
            r"\bprincipal\b",
        ],
    ),
    Rule(
        "attorney/lawyer",
        [
            r"\battorney\b",
            r"\blawyer\b",
            r"\bcounsel\b",
            r"\bprosecutor\b",
            r"\bpublic defender\b",
            r"\bsolicitor\b",
        ],
    ),
    Rule(
        "planner/policy",
        [
            r"\bplanner\b",
            r"\bplanning\b",
            r"\burbanist\b",
            r"\bpolicy analyst\b",
            r"\bpolicy director\b",
            r"\bpolicy expert\b",
            r"\bchief policy counsel\b",
            r"\bpolicy advisor\b",
            r"\bresearch project director\b",
            r"\bresearch coordinator\b",
            r"\bproject director\b",
            r"\bprogram officer\b",
            r"\bstrategy director\b",
            r"\bstrategy officer\b",
            r"\bdirector of strategy\b",
            r"\bdirector of new york legal policy\b",
            r"\bdirector of housing\b",
            r"\bdirector of justice reform\b",
            r"\beditorial and policy director\b",
            r"\bprogram director\b",
            r"\bdirector of technology law and policy\b",
            r"\bland use\b",
            r"\btransportation analyst\b",
            r"\bhousing policy\b",
            r"\bplanning commission\b",
            r"\bcommunity-based research coordinator\b",
            r"\bcommunications consultant\b",
        ],
    ),
    Rule(
        "nonprofit/advocacy",
        [
            r"\bexecutive director\b",
            r"\bnonprofit\b",
            r"\borganizer\b",
            r"\badvocacy\b",
            r"\badvocate\b",
            r"\bcampaign director\b",
            r"\bcoalition\b",
            r"\balliance\b",
            r"\bpresident of\b",
            r"\bvice president of\b",
            r"\bchief philanthropy officer\b",
            r"\bphilanthropy\b",
            r"\bboard chair\b",
            r"\bchair of the board\b",
            r"\bstreet outreach worker\b",
            r"\bgun violence prevention advocate\b",
            r"\bcommunity organizer\b",
        ],
    ),
    Rule(
        "architect/designer",
        [
            r"\barchitect\b",
            r"\barchitecture critic\b",
            r"\burban designer\b",
            r"\bdesigner\b",
            r"\bteam director at gehl\b",
            r"\bdesign principal\b",
            r"\blandscape designer\b",
        ],
    ),
    Rule(
        "business/finance",
        [
            r"\bchief investment officer\b",
            r"\bchief executive officer\b",
            r"\binvestor\b",
            r"\bentrepreneur\b",
            r"\bceo\b",
            r"\bfounder\b",
            r"\bexecutive\b",
            r"\bbanker\b",
            r"\bventure\b",
            r"\bcapital\b",
            r"\bstrategies\b",
            r"\bconsulting\b",
            r"\bfirm\b",
        ],
    ),
    Rule(
        "artist/culture",
        [
            r"\bartist\b",
            r"\bcurator\b",
            r"\bphotographer\b",
            r"\bcartoonist\b",
            r"\bnovelist\b",
            r"\bpoet\b",
            r"\bfilmmaker\b",
            r"\bmusician\b",
            r"\billustrator\b",
        ],
    ),
]

TRAINING_RULES = [
    Rule("law", [r"\bj\.d\.\b", r"\bjuris doctor\b", r"\blaw school\b", r"\battorney\b", r"\blawyer\b"]),
    Rule("architecture/design", [r"\barchitect\b", r"\barchitecture\b", r"\burban designer\b", r"\bdesigner\b"]),
    Rule(
        "economics",
        [r"\beconomist\b", r"\beconomics\b"],
    ),
    Rule(
        "sociology/criminology",
        [r"\bsociolog", r"\bcriminolog", r"\bcrime lab\b"],
    ),
    Rule(
        "public policy/planning",
        [r"\bpublic policy\b", r"\bplanning\b", r"\bland use\b", r"\burban studies\b"],
    ),
    Rule(
        "journalism/media",
        [r"\bjournalist\b", r"\breporter\b", r"\beditor\b", r"\bwriter\b"],
    ),
    Rule(
        "business/finance",
        [r"\bfinance\b", r"\binvestment\b", r"\bventure\b", r"\bentrepreneur\b"],
    ),
]

NYC_MARKERS = [
    "new york city",
    "nyc",
    "brooklyn",
    "bronx",
    "queens",
    "manhattan",
    "staten island",
    "new york-based",
    "brooklyn-based",
    "ny-based",
    "based in new york",
    "based in nyc",
    "in new york city",
]

NON_NYC_MARKERS = [
    "chicago",
    "cambridge",
    "los angeles",
    "san francisco",
    "washington, d.c.",
    "washington dc",
    "washington, dc",
    "durham",
    "princeton",
    "new haven",
    "berkeley",
    "austin",
    "seattle",
    "philadelphia",
]

INSTITUTION_KEYWORDS = {
    "government": [
        "city of ",
        "mayor's office",
        "department",
        "office of",
        "district attorney",
        "police",
        "probation",
        "correction",
        "commission",
        "council",
        "government",
        "agency",
        "governor",
        "public schools",
        "school district",
    ],
    "nonprofit/advocacy": [
        "nonprofit",
        "advocacy",
        "alliance",
        "coalition",
        "council on criminal justice",
        "citizens budget commission",
        "center for justice innovation",
        "center for court innovation",
        "prison law office",
        "think tank",
        "not-for-profit",
    ],
    "university/research": [
        "university",
        "college",
        "school of",
        "institute",
        "lab",
        "laboratory",
        "center",
        "research",
        "academy",
        "nyu",
        "cuny",
        "columbia",
        "yale",
        "princeton",
        "rutgers",
        "duke",
        "harvard",
        "john jay",
        "cornell",
        "ucsf",
    ],
    "media": [
        "news",
        "times",
        "magazine",
        "journal",
        "daily",
        "slate",
        "spectrum",
        "ny1",
        "wnyc",
        "gothamist",
        "citylab",
    ],
    "philanthropy/foundation": [
        "foundation",
        "philanthropy",
        "philanthropic",
        "trust",
        "fund",
        "revson",
    ],
    "private company/consulting": [
        "llc",
        "inc",
        "company",
        "group",
        "partners",
        "ventures",
        "strategies",
        "capital",
        "consulting",
        "studio",
        "firm",
        "real estate",
        "analytics",
    ],
}

PRIORITY = [
    "academic",
    "journalist/media",
    "government/public sector",
    "attorney/lawyer",
    "planner/policy",
    "architect/designer",
    "nonprofit/advocacy",
    "business/finance",
    "artist/culture",
    "house/byline",
]


def fetch_posts() -> list[dict]:
    posts: list[dict] = []
    params = {"key": API_KEY, "limit": 100, "page": 1, "include": "authors"}
    while True:
        url = POSTS_URL + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        posts.extend(data["posts"])
        nxt = data["meta"]["pagination"]["next"]
        if not nxt:
            break
        params["page"] = nxt
    return posts


def match_rules(text: str, rules: list[Rule]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for rule in rules:
        count = 0
        for pattern in rule.patterns:
            if re.search(pattern, text):
                count += 1
        if count:
            hits.append((rule.label, count))
    return hits


def clean_org(org: str) -> str:
    org = re.sub(r"\b(?:a|an|the)\b\s+", "", org.strip(), flags=re.I)
    org = re.sub(r"\s+", " ", org).strip(" ,.;")
    return org


def infer_current_employer(bio: str) -> str:
    if not bio:
        return ""
    text = bio.strip()
    patterns = [
        r"\bis (?:the|a|an)? .*? at (?P<org>[^.]+?)(?:,|\.|$)",
        r"\bis (?:the|a|an)? .*? of (?P<org>[^.]+?)(?:,|\.|$)",
        r"\bworks? at (?P<org>[^.]+?)(?:,|\.|$)",
        r"\bwith (?P<org>[^.]+?)(?:,|\.|$)",
        r"\bfor (?P<org>[^.]+?)(?:,|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            org = clean_org(match.group("org"))
            if len(org) > 2:
                return org
    return ""


def infer_institution_type(current_profession: str, current_employer: str, bio: str) -> str:
    text = f"{current_employer} {bio}".lower()
    if current_profession == "house/byline":
        return "house/byline"
    if not text.strip():
        return "unknown"
    for label, keywords in INSTITUTION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return label
    return "independent"


def infer_nyc_based(current_employer: str, bio: str) -> str:
    text = f"{current_employer} {bio}".lower()
    if any(marker in text for marker in NYC_MARKERS):
        return "yes"
    if any(marker in text for marker in NON_NYC_MARKERS):
        return "no"
    return "unknown"


def infer_professions(bio: str) -> tuple[str, str, str, str, str]:
    if not bio:
        return ("unknown", "", "", "low", "no Vital City bio")
    text = bio.lower()
    current_hits = match_rules(text, CURRENT_PROFESSION_RULES)
    training_hits = match_rules(text, TRAINING_RULES)
    if current_hits:
        current_hits.sort(key=lambda item: (-item[1], PRIORITY.index(item[0]) if item[0] in PRIORITY else 999))
        current_profession = current_hits[0][0]
        secondary = "; ".join(label for label, _ in current_hits[1:3])
        confidence = "high" if current_hits[0][1] >= 2 or len(current_hits) >= 2 else "medium"
    else:
        current_profession = "unknown"
        secondary = ""
        confidence = "low"
    training = "; ".join(label for label, _ in training_hits[:3])
    note = "matched Vital City bio keywords" if current_hits or training_hits else "bio present but no rule hit"
    return (current_profession, training, secondary, confidence, note)


def load_manual_overrides() -> dict[str, dict]:
    path = CONFIG_DIR / "manual_author_overrides.csv"
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["author"]: row for row in rows}


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    posts = fetch_posts()
    (RAW_DIR / "vital_city_posts_with_authors.json").write_text(json.dumps(posts, indent=2))

    author_map: dict[str, dict] = {}
    counts: Counter = Counter()
    for post in posts:
        for author in post.get("authors") or []:
            counts[author["name"]] += 1
            author_map.setdefault(author["name"], author)

    overrides = load_manual_overrides()
    master_rows: list[dict] = []
    source_rows: list[dict] = []

    for name, author in sorted(author_map.items(), key=lambda item: (-counts[item[0]], item[0])):
        bio = (author.get("bio") or "").replace("\n", " ").strip()
        current_profession, training, secondary, confidence, note = infer_professions(bio)
        current_employer = infer_current_employer(bio)
        institution_type = infer_institution_type(current_profession, current_employer, bio)
        nyc_based = infer_nyc_based(current_employer, bio)
        source_type = "vital_city_bio"
        source_url = author.get("url", "")
        source_excerpt = bio
        needs_review = "yes" if confidence != "high" or current_profession == "unknown" else "no"

        if name in overrides:
            override = overrides[name]
            current_profession = override["current_profession"] or current_profession
            training = override["training"] or training
            secondary = override["secondary_backgrounds"] or secondary
            confidence = override["confidence"] or confidence
            source_type = override["source_type"] or source_type
            source_url = override["source_url"] or source_url
            source_excerpt = override["source_excerpt"] or source_excerpt
            note = override["notes"] or note
            current_employer = override.get("current_employer", "") or current_employer
            institution_type = override.get("institution_type", "") or institution_type
            nyc_based = override.get("nyc_based", "") or nyc_based
            needs_review = "no" if confidence == "high" else needs_review

        master_rows.append(
            {
                "author": name,
                "post_count": counts[name],
                "current_profession": current_profession,
                "current_employer": current_employer,
                "institution_type": institution_type,
                "nyc_based": nyc_based,
                "training": training,
                "secondary_backgrounds": secondary,
                "confidence": confidence,
                "needs_review": needs_review,
                "vital_city_author_url": author.get("url", ""),
                "vital_city_bio": bio,
                "notes": note,
            }
        )
        source_rows.append(
            {
                "author": name,
                "source_type": source_type,
                "source_url": source_url,
                "source_excerpt": source_excerpt,
                "notes": note,
            }
        )

    master_path = PROCESSED_DIR / "vital_city_author_master.csv"
    with master_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(master_rows[0].keys()))
        writer.writeheader()
        writer.writerows(master_rows)

    source_path = PROCESSED_DIR / "vital_city_author_source_log.csv"
    with source_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(source_rows[0].keys()))
        writer.writeheader()
        writer.writerows(source_rows)

    review_rows = [row for row in master_rows if row["needs_review"] == "yes"]
    review_path = PROCESSED_DIR / "vital_city_author_review_queue.csv"
    with review_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(master_rows[0].keys()))
        writer.writeheader()
        writer.writerows(review_rows)

    summary = Counter(row["current_profession"] for row in master_rows)
    print("authors", len(master_rows))
    print("review_queue", len(review_rows))
    print("summary")
    for key, value in summary.most_common():
        print(key, value)


if __name__ == "__main__":
    main()
