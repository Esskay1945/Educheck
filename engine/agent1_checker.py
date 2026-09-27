import re
import time
import requests
from difflib import SequenceMatcher
from typing import Dict, Any, List, Tuple
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup
from scrapling.fetchers import Fetcher
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

def normalize_text(text: str) -> str:
    """Normalize text by stripping footnote citations, hidden chars, and extra whitespace"""
    if not text:
        return ""
    # Strip footnote bracket citations like [1], [a], [12], [ a ]
    t = re.sub(r'\[\s*[0-9a-zA-Z]+\s*\]', '', text)
    # Strip invisible/zero-width chars
    for char in ZERO_WIDTH_CHARS.keys():
        t = t.replace(char, '')
    t = t.replace('\u00a0', ' ')
    # Normalize whitespace before punctuation marks
    t = re.sub(r'\s+([,.:;!?])', r'\1', t)
    return " ".join(t.lower().split())

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
                "severity": "high",
                "badge": "Tampering Risk",
                "title": "Invisible / Zero-Width Characters Detected",
                "description": f"Found invisible unicode markers: {', '.join(found_invisible)}. These are commonly inserted to disrupt n-gram string matching."
            })

        # 2. Homoglyph / Mixed Script Check (e.g. Cyrillic letters mixed into Latin text)
        latin_count = len(re.findall(r'[a-zA-Z]', text))
        cyrillic_matches = re.findall(r'[\u0400-\u04FF]', text)
        greek_matches = re.findall(r'[\u0370-\u03FF]', text)
        
        if latin_count > 50 and cyrillic_matches:
            anomalies.append({
                "category": "Character Substitution",
                "severity": "high",
                "badge": "Homoglyph Alert",
                "title": "Cyrillic Character Substitution Detected",
                "description": f"Found {len(cyrillic_matches)} Cyrillic characters disguised inside predominantly Latin text (e.g. 'а', 'е', 'о', 'р', 'с')."
            })
            
        if latin_count > 50 and greek_matches:
            anomalies.append({
                "category": "Character Substitution",
                "severity": "high",
                "badge": "Homoglyph Alert",
                "title": "Greek Character Substitution Detected",
                "description": f"Found {len(greek_matches)} Greek unicode characters mixed into standard Latin text."
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
                "description": f"Found exceptionally long continuous sentences without punctuation (>70 words), often indicative of automated splicing."
            })

        # Check for abnormal em-dash or hyphen stuffing
        dash_count = text.count('—') + text.count('--')
        if dash_count >= 5:
            anomalies.append({
                "category": "Stylistic Tell",
                "severity": "medium",
                "badge": "Cadence Anomaly",
                "title": f"Excessive Dash Formatting ({dash_count} instances)",
                "description": "Unusually high density of parenthetical em-dashes, a recognized syntactic hallmark of machine-generated prose."
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
                    "description": f"Standard deviation of sentence length is only {std_dev:.1f} words (mean: {avg_len:.1f}w). Natural human writing displays higher rhythm burstiness."
                })

        return anomalies

    def extract_search_queries(self, text: str, max_queries: int = 5) -> List[str]:
        """Extract substantive search queries from text (both key phrases and opening clauses)"""
        raw_sentences = [s.strip() for s in re.split(r'[.!?\n]+', text) if len(s.strip()) > 15]
        candidates = []

        for s in raw_sentences:
            s_clean = normalize_text(s)
            words = [w for w in re.findall(r'\b[a-zA-Z0-9-]+\b', s_clean) if len(w) > 1]
            content_words = [w for w in words if w not in COMMON_STOPWORDS]
            
            if len(words) >= 5:
                # 1. Continuous slice
                slice_len = min(8, len(words))
                phrase = " ".join(words[:slice_len])
                candidates.append((len(content_words), phrase))
                
                # 2. Mid slice if sentence is long
                if len(words) >= 14:
                    mid_phrase = " ".join(words[5:12])
                    candidates.append((len(content_words) - 1, mid_phrase))

        # Sort candidates by information density
        candidates.sort(key=lambda x: x[0], reverse=True)
        seen = set()
        queries = []
        for _, q in candidates:
            if q not in seen:
                seen.add(q)
                queries.append(q)
            if len(queries) >= max_queries:
                break
                
        return queries

    def search_web_sources(self, query: str) -> List[Dict[str, str]]:
        """Multi-engine search: queries live web indexes and encyclopedic repositories"""
        results = []
        seen_urls = set()

        # 1. Wikipedia API direct encyclopedic search
        try:
            r = requests.get('https://en.wikipedia.org/w/api.php', params={
                'action': 'query',
                'list': 'search',
                'srsearch': query,
                'format': 'json'
            }, timeout=4, headers={'User-Agent': 'EduCheckAcademicScanner/2.0'})
            if r.status_code == 200:
                wiki_data = r.json()
                for item in wiki_data.get('query', {}).get('search', [])[:2]:
                    title = item.get('title', '')
                    clean_slug = title.replace(' ', '_')
                    wiki_url = f"https://en.wikipedia.org/wiki/{clean_slug}"
                    if wiki_url not in seen_urls:
                        seen_urls.add(wiki_url)
                        snippet = re.sub(r'<[^>]+>', '', item.get('snippet', ''))
                        results.append({
                            'title': f"{title} - Wikipedia",
                            'url': wiki_url,
                            'domain': 'en.wikipedia.org',
                            'snippet': snippet
                        })
        except Exception as e:
            pass

        # 2. Live Web Index Search via Stealth Fetcher
        try:
            page = Fetcher.post(
                'https://html.duckduckgo.com/html/',
                data={'q': query},
                timeout=8
            )

            if page.status == 200:
                bodies = page.css('.result__body')
                for b in bodies[:4]:
                    title_nodes = b.css('.result__title a')
                    snippet_nodes = b.css('.result__snippet')
                    if title_nodes:
                        a_tag = title_nodes[0]
                        title = a_tag.text.strip() if hasattr(a_tag, 'text') and a_tag.text else "Web Source"
                        raw_href = a_tag.attrib.get('href', '')
                        
                        if '/l/?uddg=' in raw_href:
                            try:
                                raw_href = unquote(raw_href.split('/l/?uddg=')[1].split('&')[0])
                            except Exception:
                                pass
                                
                        snippet = snippet_nodes[0].text.strip() if snippet_nodes and hasattr(snippet_nodes[0], 'text') and snippet_nodes[0].text else ""
                        
                        if raw_href.startswith('http') and not any(d in raw_href for d in ['duckduckgo.com', 'google.com']):
                            if raw_href not in seen_urls:
                                seen_urls.add(raw_href)
                                domain = urlparse(raw_href).netloc
                                results.append({
                                    'title': title,
                                    'url': raw_href,
                                    'domain': domain,
                                    'snippet': snippet
                                })
        except Exception as e:
            pass

        return results

    def fetch_page_content(self, url: str) -> str:
        """Fetch target web page content and extract clean, complete text using BeautifulSoup"""
        try:
            page = Fetcher.get(url, timeout=8)
            if page.status == 200 and page.body:
                soup = BeautifulSoup(page.body, 'html.parser')
                # Decompose non-content tags & citations
                for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript', 'sup']):
                    tag.decompose()
                # Decompose Wikipedia / web citation noise
                for cl in ['reference', 'IPA', 'noprint', 'mw-jump-link', 'mw-editsection']:
                    for el in soup.find_all(class_=cl):
                        el.decompose()
                content = (
                    soup.find('div', id='mw-content-text') or 
                    soup.find('main') or 
                    soup.find('article') or 
                    soup.find('div', class_='content') or 
                    soup
                )
                text = " ".join(content.get_text(separator=' ').split())
                return text
        except Exception as e:
            pass
        return ""

    def calculate_text_similarity(self, input_text: str, source_text: str) -> Tuple[float, List[Tuple[int, int, str]]]:
        """Calculate match percentage of input_text against source_text using exact blocks & rolling n-grams"""
        if not input_text or not source_text:
            return 0.0, []

        input_clean = normalize_text(input_text)
        source_clean = normalize_text(source_text)

        if not input_clean or not source_clean:
            return 0.0, []

        # Tokenize alphanumeric words
        input_words = re.findall(r'\b[a-zA-Z0-9-]+\b', input_clean)
        source_tokens = re.findall(r'\b[a-zA-Z0-9-]+\b', source_clean)
        source_tokens_str = " " + " ".join(source_tokens) + " "

        matched_word_indices = set()

        # Multi-order rolling n-grams (5-word, 4-word, 3-word)
        if len(input_words) >= 3:
            for n in [5, 4, 3]:
                for i in range(len(input_words) - (n - 1)):
                    ngram = " " + " ".join(input_words[i:i+n]) + " "
                    if ngram in source_tokens_str:
                        for k in range(i, i+n):
                            matched_word_indices.add(k)

        # Exact contiguous SequenceMatcher ratio fallback
        seq_ratio = 0.0
        try:
            matcher = SequenceMatcher(None, input_clean, source_clean)
            match_blocks_len = sum(b.size for b in matcher.get_matching_blocks() if b.size >= 16)
            seq_ratio = match_blocks_len / max(1, len(input_clean))
        except Exception:
            pass

        ngram_ratio = len(matched_word_indices) / max(1, len(input_words))
        ratio = max(ngram_ratio, seq_ratio)

        # 3. Find matching segments in the original input_text to highlight in the UI
        matched_spans = []
        raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?\n])\s+', input_text) if len(s.strip()) > 8]
        for s in raw_sentences:
            s_words = re.findall(r'\b[a-zA-Z0-9-]+\b', s.lower())
            if not s_words:
                continue

            s_matched = 0
            for i in range(max(0, len(s_words) - 2)):
                ngram = " " + " ".join(s_words[i:i+3]) + " "
                if ngram in source_tokens_str:
                    s_matched += 3

            # Flag sentence if >=35% words matched or short clause matches completely
            if (s_matched / len(s_words) >= 0.35) or (len(s_words) <= 7 and " ".join(s_words) in source_tokens_str):
                if s in input_text:
                    pos = input_text.find(s)
                    matched_spans.append((pos, pos + len(s), s))

        return min(1.0, ratio), matched_spans

    def check_similarity(self, text: str, logs: List[str]) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Execute full similarity detection pipeline across live web sources"""
        queries = self.extract_search_queries(text)
        logs.append(f"Extracted {len(queries)} substantive search queries from input document.")
        
        discovered_sources = {}
        for q in queries:
            logs.append(f"Live web index search: \"{q[:45]}...\"")
            results = self.search_web_sources(q)
            for res in results:
                url = res['url']
                if url not in discovered_sources:
                    discovered_sources[url] = res
            time.sleep(0.2)

        logs.append(f"Discovered {len(discovered_sources)} potential candidate web sources.")

        flagged_segments = []
        verified_sources = []
        overall_matched_chars = set()

        for url, meta in list(discovered_sources.items())[:5]:
            logs.append(f"Fetching target source content: {meta.get('domain', url)}")
            source_content = self.fetch_page_content(url)
            combined_source = (source_content + " " + meta.get('snippet', '')).strip()
            
            ratio, matches = self.calculate_text_similarity(text, combined_source)
            if ratio > 0.05 or matches:
                match_pct = round(ratio * 100, 1)
                verified_sources.append({
                    "title": meta['title'],
                    "url": url,
                    "domain": meta['domain'],
                    "match_percentage": match_pct,
                    "snippet": meta.get('snippet', '')
                })
                
                for start, end, match_str in matches:
                    for char_idx in range(start, end):
                        overall_matched_chars.add(char_idx)
                    flagged_segments.append({
                        "start": start,
                        "end": end,
                        "text": match_str,
                        "type": "plagiarism",
                        "reason": f"Matches content from {meta['domain']} ({match_pct}% overlap)",
                        "source_url": url,
                        "source_title": meta['title']
                    })

        # Calculate Overall Similarity Score (0% to 100%)
        similarity_score = min(100, round((len(overall_matched_chars) / max(1, len(text))) * 100))
        if verified_sources and similarity_score < 10:
            similarity_score = max(similarity_score, int(max(s['match_percentage'] for s in verified_sources)))

        logs.append(f"Similarity check complete. Overall Similarity Score: {similarity_score}%.")
        return similarity_score, verified_sources, flagged_segments

    def run_audit(self, text: str) -> Dict[str, Any]:
        """Orchestrate forensic audit sequence across 4 Core Pillars"""
        logs = []
        start_time = time.time()
        logs.append("Sentinel initialized 4-pillar forensic audit sequence.")

        # 1. Flags and Anomalies Detection
        anomalies = self.detect_flags_and_anomalies(text)
        if anomalies:
            logs.append(f"Detected {len(anomalies)} structural flags or character anomalies.")
        else:
            logs.append("No character tampering or structural anomalies detected.")

        # 2. Overall Similarity & Source-Specific Match Percentage
        similarity_score, sources, plag_segments = self.check_similarity(text, logs)

        # 3. AI-Generated Content Score
        logs.append("Sentinel evaluating AI cadence, perplexity, and linguistic markers.")
        ai_result = self.grok_client.analyze_ai_content(text)
        ai_score = ai_result.get("ai_score", 0)
        logs.append(f"AI content assessment completed: {ai_score}% likelihood ({ai_result.get('verdict', 'Evaluated')}).")

        # 4. Mark Flagged Segments in Document
        all_flagged = list(plag_segments)
        for sentence_info in ai_result.get("sentence_breakdown", []):
            if sentence_info.get("classification") == "AI":
                s_text = sentence_info.get("sentence", "").strip()
                if s_text and s_text in text:
                    pos = text.find(s_text)
                    all_flagged.append({
                        "start": pos,
                        "end": pos + len(s_text),
                        "text": s_text,
                        "type": "ai",
                        "reason": "AI writing pattern: uniform cadence / synthetic syntax",
                        "source_url": None,
                        "source_title": "AI Pattern Detection"
                    })

        all_flagged.sort(key=lambda x: x['start'])

        # Overall composite integrity rating
        composite_risk = (similarity_score * 0.6) + (ai_score * 0.4)
        integrity_score = max(0, min(100, round(100 - composite_risk)))

        duration = round(time.time() - start_time, 2)
        logs.append(f"Sentinel finalized audit report in {duration}s. Similarity: {similarity_score}%, AI: {ai_score}%.")

        return {
            "similarity_score": similarity_score,
            "plagiarism_score": similarity_score,
            "ai_score": ai_score,
            "integrity_score": integrity_score,
            "sources": sources,
            "flags_and_anomalies": anomalies,
            "flagged_segments": all_flagged,
            "ai_analysis": ai_result,
            "duration": duration,
            "agent_logs": logs
        }
