# EduCheck — Academic Integrity & Prose Reconstruction Studio

EduCheck is an enterprise-grade academic integrity and prose reconstruction platform engineered for high-precision document forensics, multi-source web cross-referencing, and stylistic humanization.

---

## 🏛️ The Dual-Engine Architecture

EduCheck operates on two tightly coordinated engines:

### 1. 🛡️ Sentinel — Forensic Detection Engine
Sentinel provides forensic-level academic inspection across four core industry pillars:
- **Overall Similarity Score (%)**: Computes aggregate verbatim and rolling n-gram text overlap against live web indexes and encyclopedic repositories.
- **Source-Specific Match Percentage (%)**: Attributes specific matching segments and ratios to individual web sources with live URL citations.
- **AI-Generated Content Likelihood (%)**: Forensic evaluation of syntactic perplexity, rhythm burstiness, and machine-learning generation hallmarks.
- **Flags & Anomalies Scanner**: Detects adversarial evasion tactics, including:
  - Invisible / zero-width characters (`\u200b`, `\u200c`, `\u200d`, BOM `\ufeff`, soft hyphens)
  - Mixed-script homoglyphs (Cyrillic or Greek substitutions masquerading as Latin characters)
  - Cadence uniformity and robotic sentence run-ons (>70 words)
  - Web DOM copy-paste artifacts (non-breaking whitespace clusters)

### 2. ✍️ Artisan — Prose Reconstruction & Humanizer
Artisan reconstructs flagged prose to bypass synthetic cadence while preserving academic rigor:
- **Variable Burstiness & Cadence Modulation**: Injects natural human variation in clause length and syntactic rhythm.
- **Semantic Fidelity Preservation**: Retains citations, technical terminology, and core academic arguments.
- **Instant Forensic Verification**: Automatically triggers a secondary Sentinel audit on humanized output to verify reduced AI markers and zero unintended plagiarism.

---

## 🚀 Key Features

- **Multi-Format Document Parsing**: Native extraction for `.pdf`, `.docx`, `.doc`, `.txt`, `.rtf`, `.odt`, and `.html`.
- **Live Stealth Web Indexing**: High-speed, multi-threaded search across encyclopedic databases and web indexes with automated citation noise decomposition.
- **Interactive Segment Inspector**: Color-coded inline markup for both plagiarism (red) and AI-generated cadence (orange).
- **Curated Academic UI**: Premium maroon-and-white aesthetic designed for academic institutions, researchers, and editorial workflows.

---

## 🛠️ Quickstart & Installation

### Prerequisites
- Python 3.10 or higher
- An API Key (Groq or xAI Grok)

### Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Esskay1945/Educheck.git
   cd Educheck
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the example environment file and add your API key:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   ```ini
   GROK_API_KEY=gsk_your_key_here
   ```

5. **Start the EduCheck server:**
   ```bash
   python app.py
   ```
   Open your browser and navigate to `http://127.0.0.1:5000`.

---

## 📁 Repository Structure

```
Educheck/
├── app.py                      # Flask application and REST API endpoints
├── requirements.txt            # Project dependencies
├── .env.example                # Sample environment configuration template
├── .gitignore                  # Git ignore rules (secrets, venvs, caches)
├── engine/
│   ├── __init__.py
│   ├── agent1_checker.py       # Sentinel: Plagiarism, anomaly & web search engine
│   ├── agent2_humanizer.py     # Artisan: Prose reconstruction & humanizer engine
│   ├── document_parser.py      # Multi-format document parser (PDF, DOCX, TXT)
│   └── grok_client.py          # Unified LLM provider client (Groq / xAI)
├── templates/
│   └── index.html              # Sleek academic interface (HTML5 / Vanilla CSS / JS)
└── uploads/                    # Secure local staging directory for file uploads
```

---

## 🔒 Security & Privacy

- Document uploads are processed locally and staged securely.
- No confidential API keys are ever tracked or committed to version control.
