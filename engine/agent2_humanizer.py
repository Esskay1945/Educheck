"""Citation-preserving editing and independent verification."""

import re
import time
from concurrent.futures import ThreadPoolExecutor

from engine.document_parser import MAX_TEXT_LENGTH
from engine.grok_client import split_text

REFERENCE_HEADING = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:references|bibliography|works cited|sources|notes)[ \t]*:?[ \t]*$"
)
PROTECTED = re.compile(
    r"(?im)^\s*\[?\d+[.)\]]\s+[^\n]+(?=\n|$)"  # Numbered reference and list entries
    r"|!?\[[^\]\n]+\]\([^\n)]+\)"  # Markdown links
    r"|https?://[^\s<>\"”]+|(?:doi:\s*)?10\.\d{4,9}/[^\s<>\"”]+"
    r"|\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]|\[\s*[a-z][a-z0-9_-]*\s*\]"
    r"|\([^()\n]{0,130}\b(?:18|19|20)\d{2}[a-z]?(?:[^()\n]{0,70})\)"
    r"|“[^”\n]+”|(?<!\w)\"[^\"\n]+\"|[⁰¹²³⁴⁵⁶⁷⁸⁹]+"
    r"|\b\d+(?:[.,]\d+)*(?:%|\b)"
)
PLACEHOLDER = re.compile(r"\[\[EDUCHECK_KEEP_\d+_\d+\]\]")
SCORE_KEYS = ("similarity_score", "plagiarism_score", "ai_score", "integrity_score")


def audit_summary(report):
    return {
        **{key: report[key] for key in SCORE_KEYS},
        "similarity_coverage": report["similarity_coverage"],
        "ai_method": report["ai_analysis"]["method"],
        "ai_warning": report["ai_analysis"]["warning"],
    }


def baseline_sources(report):
    return [
        {"url": source["url"], "domain": source["domain"], "title": source["title"][:200]}
        for source in report["sources"][:8]
    ]


def preserve_citations(chunk, index):
    originals = {}

    def replace(match):
        token = f"[[EDUCHECK_KEEP_{index}_{len(originals)}]]"
        originals[token] = match.group()
        return token

    return PROTECTED.sub(replace, chunk), originals


def edit_section(client, index, chunk):
    leading = chunk[:len(chunk) - len(chunk.lstrip())]
    trailing = chunk[len(chunk.rstrip()):]
    passage = chunk.strip()
    if not passage:
        return chunk, [], False

    if PLACEHOLDER.search(passage):
        return chunk, [], True
    masked, originals = preserve_citations(passage, index)
    result = client.edit_chunk(masked)
    if result is None:
        return chunk, [], True
    edited = result.humanized_text.strip()
    if PLACEHOLDER.findall(edited) != list(originals) or len(edited) < len(masked) * 0.55:
        return chunk, [], True

    edited = PLACEHOLDER.sub(lambda match: originals[match.group()], edited)
    if len(edited) > len(passage) * 1.5:
        return chunk, [], True
    changes = [change[:300] for change in result.changes_summary] if edited != passage else []
    return leading + edited + trailing, changes, False


class Agent2Humanizer:
    def __init__(self, grok_client, agent1_checker):
        self.grok_client = grok_client
        self.agent1_checker = agent1_checker

    def _edit_document(self, text):
        citation_heading = REFERENCE_HEADING.search(text)
        end = citation_heading.start() if citation_heading else len(text)
        body, references = text[:end], text[end:]
        protected = [match.span() for match in PROTECTED.finditer(body)]
        chunks = split_text(body, protected)
        warnings = []
        changes = []
        if self.grok_client.is_configured():
            with ThreadPoolExecutor(max_workers=4) as pool:
                edits = list(pool.map(lambda item: edit_section(self.grok_client, *item), enumerate(chunks)))
            rewritten = "".join(edited for edited, _, _ in edits) + references
            changes = list(dict.fromkeys(change for _, notes, _ in edits for change in notes))
            if any(failed for _, _, failed in edits):
                warnings.append("Some sections were retained because the provider response could not be validated.")
        else:
            rewritten = text
            warnings.append("Configure an AI provider to edit prose. The original text was retained.")

        # An oversized edit remains reviewable in its original form and within the audit limit.
        if len(rewritten) > MAX_TEXT_LENGTH:
            rewritten = text
            changes = []
            warnings.append("The edited text exceeded the document limit. The original text was retained.")
        return rewritten, changes, warnings

    def remediate(self, text, before_scores=None, known_sources=()):
        started = time.monotonic()
        if before_scores is None:
            with ThreadPoolExecutor(max_workers=1) as pool:
                baseline = pool.submit(self.agent1_checker.run_audit, text)
                rewritten, changes, warnings = self._edit_document(text)
                original_report = baseline.result()
            before_scores = audit_summary(original_report)
            known_sources = baseline_sources(original_report)
        else:
            rewritten, changes, warnings = self._edit_document(text)
        verification = self.agent1_checker.run_audit(rewritten, known_sources)
        return {
            "original_text": text,
            "humanized_text": rewritten,
            "before_scores": before_scores,
            "after_scores": audit_summary(verification),
            "verification_sources": verification["sources"],
            "changes_summary": changes,
            "tells_eliminated": [],
            "improvements": "Edited for clarity and flow." if rewritten != text else "Original text retained.",
            "warnings": warnings,
            "duration": round(time.monotonic() - started, 2),
            "agent_logs": ["Sentinel independently checked the returned text."],
        }
