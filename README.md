# EduCheck

EduCheck checks a document for public-web text overlap and stylistic patterns. Sentinel reports matching passages and source coverage. Artisan edits for clarity, preserves recognized citations and bibliography text, and runs a fresh Sentinel check that includes previously matched sources.

## Run locally

Use Python 3.10 or newer. Install Tesseract OCR and its language data for scanned PDFs. Install Antiword for binary Word DOC files. On Debian or Ubuntu, the system packages are:

~~~sh
sudo apt-get install antiword tesseract-ocr tesseract-ocr-eng
~~~

~~~sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
~~~

Open [EduCheck locally](http://127.0.0.1:5000).

Set `AI_PROVIDER` and the matching key in `.env` to enable provider-based style assessment and editing.

| Provider | Key | Optional model override | Default model |
| --- | --- | --- | --- |
| Groq | GROQ_API_KEY | GROQ_MODEL | openai/gpt-oss-120b |
| xAI | XAI_API_KEY | XAI_MODEL | grok-4.3 |
| OpenAI | OPENAI_API_KEY | OPENAI_MODEL | gpt-4.1-mini |

`AI_MODEL` is a shared override. If `AI_PROVIDER` is unset, EduCheck checks the provider-specific keys in the order listed. Existing `GROK_API_KEY` values are also supported. Keys starting with `gsk_` use Groq. Other legacy keys use xAI. Without a configured provider, Sentinel uses local style checks and Artisan retains the original text. The workspace and `/api/status` show which provider is configured. Actual connectivity and model entitlement are exercised when a document is processed.

## Documents and search results

The workspace accepts PDF, DOCX, DOC, ODT, RTF, TXT, Markdown, HTML, TEX, CSV, JSON, XML, and LOG. Uploads are limited to 32 MiB and 60,000 extracted characters. PDFs can contain up to 120 pages, including at most 20 pages that need OCR. Set `EDUCHECK_OCR_LANG` to an installed Tesseract language code for documents in other languages. Review extracted text before checking a scan.

Similarity measures the share of document words covered by five-word matches in the public pages reached. Search samples up to 16 excerpts across the document and checks up to 32 distinct candidate pages, including up to eight prior matches during rewrite verification. Partial coverage and service failures appear in the report. A low overlap score covers the pages reached and cannot establish originality outside that search. Use source links to review overlap and attribution. Use independent evidence for any authorship or misconduct decision.

Uploads are extracted in temporary files and removed after processing. Running a check sends short excerpts to DuckDuckGo and Wikipedia. A configured AI provider receives the text for style assessment and editing. Verification sends excerpts and, if configured, text from the edited version.

## Deploy

The Procfile serves the app with Gunicorn and requires `EDUCHECK_ACCESS_TOKEN`. Set a long, random token in the host environment and use it as the password at the browser prompt. The username can be any nonempty value. Serve the workspace over HTTPS. Set a stable `EDUCHECK_SECRET_KEY` if audit tokens should survive restarts or work across instances.

Use the Dockerfile to include Antiword and English Tesseract OCR in the runtime.

~~~sh
docker build -t educheck .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env educheck
~~~

For a hosted deployment, point health checks at `/healthz`. The SQLite rate limiter is shared by workers on one instance. Set `EDUCHECK_RATE_DB` to a writable local path if needed. For multiple replicas, enforce the deployment-wide limit at the ingress. Set `EDUCHECK_PROXY_HOPS` only when the server is reachable exclusively through the configured number of trusted proxies. Run live search and provider checks with an approved sample document after deploying.

## Test

~~~sh
pip install -r requirements-dev.txt
python -m pytest -q
~~~
