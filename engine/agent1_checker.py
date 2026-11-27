"""Sentinel web similarity and style assessment."""

import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from engine import web_sources
from engine.grok_client import GrokClient

COMMON_STOPWORDS = {
    'the', 'is', 'at', 'which', 'on', 'and', 'a', 'an', 'in', 'to', 'for', 'of',
    'with', 'as', 'by', 'that', 'this', 'it', 'from', 'be', 'are', 'was', 'were',
    'or', 'but', 'not', 'what', 'all', 'were', 'we', 'when', 'your', 'can', 'said',
    'there', 'use', 'each', 'which', 'she', 'do', 'how', 'their', 'if', 'will', 'up',
    'other', 'about', 'out', 'many', 'then', 'them', 'these', 'so', 'some', 'her',
    'would', 'make', 'like', 'him', 'into', 'time', 'has', 'look', 'two', 'more',
    'write', 'go', 'see', 'number', 'no', 'way', 'could', 'people', 'my', 'than',
    'first', 'water', 'been', 'call', 'who', 'oil', 'its', 'now', 'find', 'long',
    'down', 'day', 'did', 'get', 'come', 'made', 'may', 'part'
}

ZERO_WIDTH_CHARS = {
    '\u200b': 'Zero-Width Space',
    '\u200c': 'Zero-Width Non-Joiner',
    '\u200d': 'Zero-Width Joiner',
    '\ufeff': 'Zero-Width No-Break Space (BOM)',
    '\u00ad': 'Soft Hyphen',
    '\u2060': 'Word Joiner',
    '\u2061': 'Function Application',
    '\u2062': 'Invisible Times',
    '\u2063': 'Invisible Separator',
    '\u2064': 'Invisible Plus',
}

class Agent1Checker:
    """Sentinel: Multi-Source Forensic Academic Integrity Engine"""

    def __init__(self, grok_client: GrokClient):
        self.grok_client = grok_client

    def detect_flags_and_anomalies(self, text: str) -> List[Dict[str, Any]]:
        """Detect non-numerical warnings: structural oddities, hidden characters, homoglyphs, and copy-paste irregularities"""
        anomalies = []

        # 1. Hidden / Zero-Width Characters Check
        found_invisible = []
        for char, name in ZERO_WIDTH_CHARS.items():
            count = text.count(char)
            if count > 0:
                found_invisible.append(f"{count}× {name}")

        if found_invisible:
            anomalies.append({
                "category": "Hidden Characters",
                "severity": "low",
                "badge": "Formatting Review",
                "title": "Invisible / Zero-Width Characters Detected",
                "description": f"Found invisible unicode markers: {', '.join(found_invisible)}. Some markers have legitimate uses in typography and writing systems."
            })

        # 2. Homoglyph / Mixed Script Check (e.g. Cyrillic letters mixed into Latin text)
        latin_count = len(re.findall(r'[a-zA-Z]', text))
        cyrillic_matches = re.findall(r'[\u0400-\u04FF]', text)
        greek_matches = re.findall(r'[\u0370-\u03FF]', text)

        if latin_count > 50 and cyrillic_matches:
            anomalies.append({
                "category": "Character Substitution",
                "severity": "low",
                "badge": "Mixed Scripts",
                "title": "Cyrillic and Latin Scripts Detected",
                "description": f"Found {len(cyrillic_matches)} Cyrillic characters alongside Latin text. Review any unexpected substitutions."
            })

        if latin_count > 50 and greek_matches:
            anomalies.append({
                "category": "Character Substitution",
                "severity": "low",
                "badge": "Mixed Scripts",
                "title": "Greek and Latin Scripts Detected",
                "description": f"Found {len(greek_matches)} Greek characters alongside Latin text. This is common in technical documents."
            })

        # 3. Structural & Punctuation Anomalies
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]

        # Check for abnormal run-ons (>70 words in a single sentence)
        run_ons = [s for s in sentences if len(s.split()) > 70]
        if run_ons:
            anomalies.append({
                "category": "Structural Oddity",
                "severity": "medium",
                "badge": "Formatting Alert",
                "title": f"Unusual Sentence Run-On ({len(run_ons)} detected)",
                "description": f"Found exceptionally long continuous sentences without punctuation (>70 words), which may affect readability."
            })

        # Check for abnormal em-dash or hyphen stuffing
        dash_count = text.count('—') + text.count('--')
        if dash_count >= 5:
            anomalies.append({
                "category": "Stylistic Tell",
                "severity": "medium",
                "badge": "Cadence Anomaly",
                "title": f"Excessive Dash Formatting ({dash_count} instances)",
                "description": "Unusually high density of parenthetical em-dashes, which may affect readability."
            })

        # Check for non-breaking space clusters
        nbsp_count = text.count('\u00a0')
        if nbsp_count >= 4:
            anomalies.append({
                "category": "Copy-Paste Artifact",
                "severity": "low",
                "badge": "Clipboard Artifact",
                "title": f"Non-Breaking Space Sequences ({nbsp_count} found)",
                "description": "Presence of non-breaking whitespace clusters, typically retained from copy-pasting directly from web DOM or rich text documents."
            })

        # 4. Low Burstiness Cadence Warning
        lengths = [len(s.split()) for s in sentences if len(s.split()) > 3]
        if len(lengths) >= 5:
            avg_len = sum(lengths) / len(lengths)
            std_dev = (sum((x - avg_len) ** 2 for x in lengths) / len(lengths)) ** 0.5
            if std_dev < 3.5:
                anomalies.append({
                    "category": "Rhythm by Rule",
                    "severity": "medium",
                    "badge": "Cadence Uniformity",
                    "title": "Abnormally Uniform Sentence Lengths",
                    "description": f"Standard deviation of sentence length is only {std_dev:.1f} words (mean: {avg_len:.1f}w). Review whether the uniform rhythm suits the passage."
                })

        return anomalies

    def run_audit(self, text, known_sources=()):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            similarity_task = pool.submit(check_similarity, text, known_sources)
            ai_result = self.grok_client.analyze_ai_content(text)
            flags = self.detect_flags_and_anomalies(text)
            similarity_score, sources, matches, coverage = similarity_task.result()

        by_snippet = {signal["snippet"]: signal["explanation"] for signal in ai_result["tells_detected"]}
        for snippet, explanation in by_snippet.items():
            for match in re.finditer(re.escape(snippet), text):
                matches.append({
                    "start": match.start(), "end": match.end(), "text": match.group(),
                    "type": "ai", "reason": explanation,
                })
                if len(matches) >= MAX_HIGHLIGHTS + 100:
                    break
            if len(matches) >= MAX_HIGHLIGHTS + 100:
                break
        matches.sort(key=lambda item: (item["start"], item["type"] != "plagiarism"))

        return {
            "similarity_score": similarity_score,
            "plagiarism_score": similarity_score,
            "ai_score": ai_result["ai_score"],
            "integrity_score": None,
            "sources": sources,
            "flags_and_anomalies": flags,
            "flagged_segments": matches,
            "similarity_coverage": coverage,
            "ai_analysis": ai_result,
            "duration": round(time.monotonic() - started, 2),
            "agent_logs": [
                f"Searched {coverage['queries']} document excerpts and checked {coverage['checked']} web pages.",
                f"Style assessment method: {ai_result['method']}.",
            ],
        }


PHRASE_LENGTH = 5
MAX_QUERIES = 16
MAX_SOURCES = 32
MAX_HIGHLIGHTS = 400
FOOTNOTE = re.compile(r"\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]")
REMOVE_INVISIBLE = str.maketrans(dict.fromkeys(ZERO_WIDTH_CHARS))
TOKEN = re.compile(r"[^\W_](?:[^\W_]|[" + "".join(ZERO_WIDTH_CHARS) + r"])*")


def tokens_and_spans(text):
    without_citations = FOOTNOTE.sub(lambda match: " " * len(match.group()), text)
    words = []
    spans = []
    for match in TOKEN.finditer(without_citations):
        word = match.group().translate(REMOVE_INVISIBLE)
        words.append(unicodedata.normalize("NFKC", word).casefold())
        spans.append(match.span())
    return words, spans


def extract_search_queries(words):
    if len(words) < PHRASE_LENGTH:
        return []
    width = min(8, len(words))
    starts = list(range(0, len(words) - width + 1, width))
    last = len(words) - width
    if starts[-1] != last:
        starts.append(last)
    queries = {}
    groups = min(MAX_QUERIES, len(starts))
    for group in range(groups):
        left = group * len(starts) // groups
        right = (group + 1) * len(starts) // groups
        options = (words[start:start + width] for start in starts[left:right])
        phrase = max(options, key=lambda items: sum(
            1 for word in set(items) if len(word) > 2 and word not in COMMON_STOPWORDS
        ))
        queries.setdefault(" ".join(phrase)[:240], None)
    return list(queries)


def matching_words(index, source_text):
    words, _ = tokens_and_spans(source_text)
    matched = set()
    seen_phrases = set()
    for start in range(len(words) - PHRASE_LENGTH + 1):
        phrase = tuple(words[start:start + PHRASE_LENGTH])
        if phrase in index and phrase not in seen_phrases:
            seen_phrases.add(phrase)
            for position in index[phrase]:
                matched.update(range(position, position + PHRASE_LENGTH))
    return matched


def matching_spans(matched, spans):
    ordered = sorted(matched)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end] == ordered[end - 1] + 1:
            end += 1
        yield spans[ordered[start]][0], spans[ordered[end - 1]][1]
        start = end


def check_similarity(text, known_sources=()):
    words, spans = tokens_and_spans(text)
    queries = extract_search_queries(words)
    coverage = {"queries": len(queries), "searches": 0, "failed_searches": 0,
                "discovered": 0, "checked": 0, "status": "unavailable"}
    if not queries:
        coverage["message"] = "At least five words are needed for a web similarity check."
        return None, [], [], coverage

    discovered, searches, failed_searches = web_sources.search(queries)
    pooled = {}
    for source in (*known_sources, *discovered):
        pooled.setdefault(source["url"], source)
    candidates = list(pooled.values())
    coverage.update(searches=searches, failed_searches=failed_searches, discovered=len(candidates))
    index = {}
    for start in range(len(words) - PHRASE_LENGTH + 1):
        index.setdefault(tuple(words[start:start + PHRASE_LENGTH]), []).append(start)

    matched_words = set()
    matched_sources = []
    flags = []
    selected = candidates[:MAX_SOURCES]
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = pool.map(web_sources.page_text, (source["url"] for source in selected))
        for source, page in zip(selected, pages):
            if not page:
                continue
            coverage["checked"] += 1
            matched = matching_words(index, page)
            if not matched:
                continue
            matched_words.update(matched)
            percentage = round(100 * len(matched) / len(words), 1)
            matched_sources.append({**source, "match_percentage": percentage})
            for start, end in matching_spans(matched, spans):
                if len(flags) == MAX_HIGHLIGHTS:
                    break
                flags.append({
                    "start": start, "end": end, "text": text[start:end], "type": "plagiarism",
                    "reason": f"Text overlap with {source['domain']}",
                    "source_url": source["url"], "source_title": source["title"],
                })

    if coverage["checked"] == 0 and (failed_searches or candidates):
        coverage["message"] = "Web similarity is unavailable. Search or source retrieval failed."
        return None, [], [], coverage
    if failed_searches or coverage["checked"] < len(candidates):
        coverage.update(status="partial", message="Some searches or sources could not be checked. Similarity reflects the pages reached.")
    else:
        coverage.update(status="complete", message="Similarity reflects the public web pages checked by this search.")
    matched_sources.sort(key=lambda source: source["match_percentage"], reverse=True)
    return round(100 * len(matched_words) / len(words), 1), matched_sources, flags, coverage
