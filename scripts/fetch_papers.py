#!/usr/bin/env python3
"""
Fetch latest sleep medicine research papers from PubMed E-utilities API.
Targets top sleep journals and covers major sleep medicine topics.
"""
import json
import sys
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
from urllib.parse import quote_plus
import os

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

JOURNALS = [
    "SLEEP",
    "Sleep Medicine Reviews",
    "Sleep Medicine",
    "Journal of Clinical Sleep Medicine",
    "Journal of Sleep Research",
    "Sleep Health",
    "Nature and Science of Sleep",
    "Sleep Medicine Clinics",
    "Behavioral Sleep Medicine",
    "Chronobiology International",
    "Current Sleep Medicine Reports",
]

TOPICS = [
    "insomnia",
    "obstructive sleep apnea",
    "circadian rhythm",
    "narcolepsy",
    "parasomnia",
    "restless legs syndrome",
    "CBT-I",
    "polysomnography",
    "sleep deprivation",
    "sleep architecture",
    "REM sleep behavior disorder",
    "melatonin",
    "shift work sleep disorder",
    "pediatric sleep",
    "chronotype",
    "hypersomnia",
    "actigraphy",
    "slow wave sleep",
    "glymphatic",
    "orexin",
]

HEADERS = {"User-Agent": "SleepBrainBot/1.0 (research aggregator)"}


def build_query(days: int = 7, max_journals: int = 11) -> str:
    journal_part = " OR ".join(
        [f'"{j}"[Journal]' for j in JOURNALS[:max_journals]]
    )
    lookback = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y/%m/%d"
    )
    date_part = (
        f'"{lookback}"[Date - Publication] : "3000"[Date - Publication]'
    )
    return f"({journal_part}) AND {date_part}"


def search_papers(query: str, retmax: int = 50) -> list[str]:
    params = (
        f"?db=pubmed&term={quote_plus(query)}&retmax={retmax}&sort=date&retmode=json"
    )
    url = PUBMED_SEARCH + params
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"[ERROR] PubMed search failed: {e}", file=sys.stderr)
        return []


def fetch_details(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    ids = ",".join(pmids)
    params = f"?db=pubmed&id={ids}&retmode=xml"
    url = PUBMED_FETCH + params
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=60) as resp:
            xml_data = resp.read().decode()
    except Exception as e:
        print(f"[ERROR] PubMed fetch failed: {e}", file=sys.stderr)
        return []
    papers = []
    try:
        root = ET.fromstring(xml_data)
        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            art = medline.find(".//Article") if medline else None
            if art is None:
                continue
            title_el = art.find(".//ArticleTitle")
            title = (
                (title_el.text or "").strip()
                if title_el is not None and title_el.text
                else ""
            )
            abstract_parts = []
            for abs_el in art.findall(".//Abstract/AbstractText"):
                label = abs_el.get("Label", "")
                text = "".join(abs_el.itertext()).strip()
                if label and text:
                    abstract_parts.append(f"{label}: {text}")
                elif text:
                    abstract_parts.append(text)
            abstract = " ".join(abstract_parts)[:2000]
            journal_el = art.find(".//Journal/Title")
            journal = (
                (journal_el.text or "").strip()
                if journal_el is not None and journal_el.text
                else ""
            )
            pub_date = art.find(".//PubDate")
            date_str = ""
            if pub_date is not None:
                year = pub_date.findtext("Year", "")
                month = pub_date.findtext("Month", "")
                day = pub_date.findtext("Day", "")
                parts = [p for p in [year, month, day] if p]
                date_str = " ".join(parts)
            pmid_el = medline.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else ""
            link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
            keywords = []
            for kw in medline.findall(".//KeywordList/Keyword"):
                if kw.text:
                    keywords.append(kw.text.strip())
            papers.append(
                {
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "date": date_str,
                    "abstract": abstract,
                    "url": link,
                    "keywords": keywords,
                }
            )
    except ET.ParseError as e:
        print(f"[ERROR] XML parse failed: {e}", file=sys.stderr)
    return papers


def load_excluded_pmids(history_path: str, window_days: int = 7) -> set[str]:
    excluded = set()
    if not history_path or not os.path.exists(history_path):
        return excluded
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        tz_taipei = timezone(timedelta(hours=8))
        cutoff = (datetime.now(tz_taipei) - timedelta(days=window_days)).strftime(
            "%Y-%m-%d"
        )
        for date_key, pmid_list in history.items():
            if date_key >= cutoff:
                excluded.update(pmid_list)
        print(
            f"[INFO] Loaded {len(excluded)} excluded PMIDs from last {window_days} days",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[WARN] Could not load history: {e}", file=sys.stderr)
    return excluded


def save_history(history_path: str, date_str: str, pmids: list[str], window_days: int = 7):
    history = {}
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}
    tz_taipei = timezone(timedelta(hours=8))
    cutoff = (datetime.now(tz_taipei) - timedelta(days=window_days)).strftime(
        "%Y-%m-%d"
    )
    history = {k: v for k, v in history.items() if k >= cutoff}
    history[date_str] = pmids
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(
        f"[INFO] Saved {len(pmids)} PMIDs to history (keeping {window_days}-day window)",
        file=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Fetch sleep medicine papers from PubMed"
    )
    parser.add_argument("--days", type=int, default=7, help="Lookback days")
    parser.add_argument(
        "--max-papers", type=int, default=40, help="Max papers to fetch"
    )
    parser.add_argument("--output", default="-", help="Output file (- for stdout)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--exclude-history",
        default="",
        help="Path to reported_pmids.json for dedup",
    )
    parser.add_argument(
        "--history-window",
        type=int,
        default=7,
        help="How many days of history to check for dedup",
    )
    args = parser.parse_args()

    excluded = load_excluded_pmids(args.exclude_history, args.history_window)

    query = build_query(days=args.days)
    print(
        f"[INFO] Searching PubMed for papers from last {args.days} days...",
        file=sys.stderr,
    )
    pmids = search_papers(query, retmax=args.max_papers)
    print(f"[INFO] Found {len(pmids)} papers from PubMed", file=sys.stderr)

    new_pmids = [p for p in pmids if p not in excluded]
    skipped = len(pmids) - len(new_pmids)
    if skipped:
        print(
            f"[INFO] Excluded {skipped} previously reported papers, {len(new_pmids)} new",
            file=sys.stderr,
        )

    if not new_pmids:
        print("NO_CONTENT", file=sys.stderr)
        if args.json:
            print(
                json.dumps(
                    {
                        "date": datetime.now(
                            timezone(timedelta(hours=8))
                        ).strftime("%Y-%m-%d"),
                        "count": 0,
                        "papers": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return
    papers = fetch_details(new_pmids)
    print(
        f"[INFO] Fetched details for {len(papers)} new papers", file=sys.stderr
    )

    tz_taipei = timezone(timedelta(hours=8))
    date_str = datetime.now(tz_taipei).strftime("%Y-%m-%d")

    reported_pmids = [p["pmid"] for p in papers if p.get("pmid")]
    if args.exclude_history:
        save_history(args.exclude_history, date_str, reported_pmids, args.history_window)

    output_data = {
        "date": date_str,
        "count": len(papers),
        "papers": papers,
    }
    out_str = json.dumps(output_data, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(out_str)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_str)
        print(f"[INFO] Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
