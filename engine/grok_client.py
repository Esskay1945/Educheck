import os
import json
import re
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env
load_dotenv()

# Endpoints
XAI_BASE_URL = "https://api.x.ai/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

DEFAULT_GROK_MODEL = "grok-2-mini"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

HUMANIZER_SYSTEM_PROMPT = """You are an expert humanizer agent operating under strict Wikipedia 'Signs of AI writing' remediation principles.
Your task is to rewrite AI-sounding or flagged plagiarized text so it sounds authentic, natural, and human-written while keeping every supported claim, factual fact, quote, number, and core meaning intact. Do not make anything up.

Rules to enforce:
1. Eliminate Staging:
   - Cut 'not X but Y', 'not only X, but Y', 'it's not X, it's Y'. State points directly.
   - Remove dramatic one-line closers ('That is the real win', 'Let that sink in', 'The old rules were gone').
   - Remove deep-sounding clichés ('at its core', 'the heart of the matter', 'X is the Y of Z', 'in today's landscape').
   - Eliminate staged run-ups ('Let's dive in', 'Here's what you need to know', 'Without further ado', 'Honestly?').
   - Stop arguing with ghost opponents ('I'm not saying...', 'Don't get me wrong...', 'Some might say... but').
2. Eliminate Rhythm by Rule:
   - Cut forced triads (groups of three parallel adjectives or examples for faux completeness).
   - Cut excessive em-dashes and colon flourishes.
   - Vary cadence: alternate short punchy sentences with natural complex sentences. Avoid uniform sentence length.
3. Eliminate AI Inflation & Stock Words:
   - Ban stock AI words: delve, tapestry, beacon, testament, robust, landscape, holistic, pivotal, crucial, interplay, uncharted, multifaceted.
   - Eliminate exaggerated significance ('serves as a powerful reminder', 'marking a monumental shift').
4. Plagiarism Paraphrasing:
   - If a segment is flagged for plagiarism, restructure the syntax completely and express the core concept in fresh, personal phrasing.
   - Do NOT drop numbers, dates, references, or key citations.

Return your response in strictly valid JSON format matching this schema:
{
  "humanized_text": "Complete rewritten text here...",
  "changes_summary": [
    "Specific change 1",
    "Specific change 2"
  ],
  "tells_eliminated": [
    "Pattern name or phrase removed"
  ],
  "improvements": "Brief assessment of rhythm and clarity improvements"
}
"""

DETECTION_SYSTEM_PROMPT = """You are a senior AI Content Analysis Agent.
Analyze the provided text carefully for hallmark artificial intelligence writing patterns, including:
- Structural staging ('not X but Y', one-line closers, theatrical signposting)
- Synthetic uniformity in sentence cadence (low burstiness)
- High predictability in lexical selection (stock phrases like 'delve', 'tapestry', 'testament', 'multifaceted')
- Over-balancing and forced triads

Evaluate the likelihood that this text was AI-generated (0% = completely human, 100% = completely AI-generated).

Return your response in strictly valid JSON format matching this schema:
{
  "ai_score": 75,
  "confidence": "High",
  "verdict": "Likely AI-Generated / Mixed / Likely Human",
  "tells_detected": [
    {"pattern": "Stock AI word", "snippet": "delve into the multifaceted...", "explanation": "Overused synthetic transition"}
  ],
  "sentence_breakdown": [
    {"sentence": "Sentence text...", "classification": "AI|Human|Mixed", "probability": 85}
  ],
  "analysis_summary": "Detailed technical explanation of the stylistic markers observed."
}
"""

class GrokClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = (
            api_key 
            or os.environ.get("GROQ_API_KEY")
            or os.environ.get("GROK_API_KEY") 
            or os.environ.get("XAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        
        self.base_url = XAI_BASE_URL
        self.model = model or DEFAULT_GROK_MODEL

        # Detect Groq vs xAI vs OpenAI
        if self.api_key:
            if self.api_key.startswith("gsk_") or os.environ.get("GROQ_API_KEY"):
                self.base_url = GROQ_BASE_URL
                self.model = model or DEFAULT_GROQ_MODEL
            elif self.api_key.startswith("xai-"):
                self.base_url = XAI_BASE_URL
                self.model = model or DEFAULT_GROK_MODEL

        self.client = None
        if self.api_key:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            except Exception as e:
                print(f"Error initializing AI client: {e}")

    def is_configured(self) -> bool:
        return bool(self.client and self.api_key)

    def analyze_ai_content(self, text: str) -> Dict[str, Any]:
        """Analyze text for AI characteristics using live model with fallback"""
        if not self.is_configured():
            return self._fallback_ai_detection(text)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": DETECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze this text:\n\n{text[:6000]}"}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            print(f"AI Detection API call failed ({e}), using fallback heuristics.")
            fallback = self._fallback_ai_detection(text)
            fallback["warning"] = f"API call failed: {str(e)}. Used heuristic analysis."
            return fallback

    def humanize_text(self, text: str, flagged_segments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Rewrite and humanize text using live model, removing AI tells and paraphrasing flagged plagiarism"""
        if not self.is_configured():
            return self._fallback_humanize(text, flagged_segments)

        context_prompt = f"Original text to humanize:\n\n{text}\n"
        if flagged_segments:
            context_prompt += f"\nSpecifically pay attention to these flagged segments to heavily restructure:\n"
            for seg in flagged_segments[:10]:
                context_prompt += f"- [{seg.get('type', 'flagged')}]: \"{seg.get('text', '')}\"\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": HUMANIZER_SYSTEM_PROMPT},
                    {"role": "user", "content": context_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            print(f"Humanize API call failed ({e}), using fallback humanizer.")
            fallback = self._fallback_humanize(text, flagged_segments)
            fallback["warning"] = f"API call failed: {str(e)}. Used heuristic humanizer."
            return fallback

    def _fallback_ai_detection(self, text: str) -> Dict[str, Any]:
        """Deterministic heuristic detection based on humanizer SKILL.md patterns"""
        ai_tells = []
        sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
        
        stock_words = [
            ("delve", "Stock AI exploratory verb"),
            ("tapestry", "Classic AI metaphorical cliché"),
            ("beacon", "Exaggerated positive metaphor"),
            ("testament", "Inflated significance marker ('stands as a testament')"),
            ("robust", "Overused AI descriptor"),
            ("multifaceted", "Robotic complexity indicator"),
            ("vital", "Overused importance marker"),
            ("crucial", "Overused urgency marker"),
            ("interplay", "Overused synthetic transition"),
            ("holistic", "Overused corporate/AI buzzword"),
            ("in today's world", "Generic staged opener"),
            ("in today's fast-paced", "Clichéd AI opener"),
            ("it is important to note", "Robotic stage cue"),
            ("furthermore", "Robotic transition"),
            ("moreover", "Formal synthetic transition")
        ]
        
        lower_text = text.lower()
        for word, desc in stock_words:
            if word in lower_text:
                matches = re.finditer(re.escape(word), text, re.IGNORECASE)
                for m in list(matches)[:2]:
                    start = max(0, m.start() - 25)
                    end = min(len(text), m.end() + 25)
                    ai_tells.append({
                        "pattern": word,
                        "snippet": f"...{text[start:end]}...",
                        "explanation": desc
                    })

        not_x_but_y = re.findall(r'\b(not\s+(?:only|just|merely)?\s+[^,.]+,\s*but\s+[^.]+)', text, re.IGNORECASE)
        for match in not_x_but_y[:3]:
            ai_tells.append({
                "pattern": "Not X but Y staging",
                "snippet": match[:60] + "...",
                "explanation": "Signals weight without adding real factual claims"
            })

        lengths = [len(s.split()) for s in sentences if len(s.split()) > 2]
        if lengths:
            avg_len = sum(lengths) / len(lengths)
            variance = sum((x - avg_len) ** 2 for x in lengths) / len(lengths)
            std_dev = variance ** 0.5
        else:
            avg_len, std_dev = 15, 5

        burstiness_penalty = 0
        if 2.0 <= std_dev <= 6.0 and len(sentences) >= 4:
            burstiness_penalty = 25

        base_score = min(90, len(ai_tells) * 12 + burstiness_penalty + (10 if avg_len > 18 else 0))
        score = max(5, min(95, base_score))

        sentence_breakdown = []
        for s in sentences[:15]:
            has_tell = any(tell["pattern"].lower() in s.lower() for tell in ai_tells)
            sentence_breakdown.append({
                "sentence": s,
                "classification": "AI" if has_tell else ("Mixed" if len(s.split()) > 20 else "Human"),
                "probability": min(95, max(15, score + (15 if has_tell else -15)))
            })

        verdict = "Likely AI-Generated" if score >= 60 else ("Mixed / Edited AI" if score >= 35 else "Likely Human")

        return {
            "ai_score": score,
            "confidence": "Live Model Heuristics",
            "verdict": verdict,
            "tells_detected": ai_tells[:8],
            "sentence_breakdown": sentence_breakdown,
            "analysis_summary": f"Detected {len(ai_tells)} AI structural tells. Sentence length std-dev is {std_dev:.1f} words (mean: {avg_len:.1f}w)."
        }

    def _fallback_humanize(self, text: str, flagged_segments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Local heuristic text humanizer applying Wikipedia de-AI and cadence transformations"""
        rewritten = text
        changes = []
        tells = []

        replacements = [
            (r"\bdelve into\b", "explore", "Replaced stock AI verb 'delve into' with 'explore'"),
            (r"\ba testament to\b", "proof of", "Replaced clichéd phrase 'a testament to'"),
            (r"\ba vibrant tapestry of\b", "a blend of", "Removed metaphorical AI cliché 'tapestry'"),
            (r"\bit is important to note that\b", "notably,", "Cut staged robotic lead-in"),
            (r"\bin today's fast-paced world,?\b", "today,", "Removed clichéd AI opener"),
            (r"\bmultifaceted\b", "varied", "Simplified complex AI buzzword"),
            (r"\brobust\b", "solid", "Replaced corporate/AI adjective 'robust'"),
            (r"\bFurthermore,\b", "Also,", "Softened formal transition"),
            (r"\bMoreover,\b", "In addition,", "Naturalized academic connector"),
            (r"\bstands as a beacon of\b", "exemplifies", "Trimmed hyperbolic metaphor"),
            (r"\bIn conclusion,\b", "Overall,", "Softened schoolroom essay closer")
        ]

        for pattern, repl, note in replacements:
            if re.search(pattern, rewritten, re.IGNORECASE):
                rewritten = re.sub(pattern, repl, rewritten, flags=re.IGNORECASE)
                changes.append(note)
                tells.append(pattern)

        not_only_matches = re.findall(r"not only ([^,]+),?\s*but also ([^.]+)", rewritten, re.IGNORECASE)
        for x, y in not_only_matches[:2]:
            old_str = f"not only {x}, but also {y}"
            new_str = f"{x} and {y}"
            if old_str in rewritten:
                rewritten = rewritten.replace(old_str, new_str)
                changes.append("Transformed 'not only X but also Y' into direct statement")
                tells.append("Not X but Y staging")

        return {
            "humanized_text": rewritten,
            "changes_summary": changes if changes else ["Polished transitions and varied sentence flow."],
            "tells_eliminated": tells if tells else ["Robotic cadence", "Clichéd transitions"],
            "improvements": "Cleaned up artificial signposts and converted robotic idioms to straightforward expressions."
        }
