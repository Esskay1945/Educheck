import io
import json
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image, ImageDraw, ImageFont
from werkzeug.datastructures import Authorization

import app as workspace
from engine import web_sources
from engine.agent1_checker import check_similarity
from engine.agent2_humanizer import edit_section
from engine.document_parser import DocumentError, extract_document
from engine.grok_client import EditResponse, GrokClient, ProviderConfig


@pytest.fixture
def api(monkeypatch, tmp_path):
    settings = workspace.app.config
    monkeypatch.setitem(settings, "RATE_DB", tmp_path / "limits.sqlite")
    monkeypatch.setitem(settings, "ACCESS_TOKEN", "")
    monkeypatch.setitem(settings, "REQUIRE_AUTH", False)
    monkeypatch.setitem(settings, "RATE_LIMIT", 12)
    monkeypatch.setitem(settings, "GLOBAL_RATE_LIMIT", 36)
    monkeypatch.setattr(web_sources, "search", lambda queries: ([], 2 * len(queries), 0))
    monkeypatch.setattr(workspace.client, "client", None)
    with workspace.app.test_client() as client:
        yield client


@pytest.fixture
def provider_env(monkeypatch):
    for name in ("AI_PROVIDER", "AI_MODEL", "GROK_API_KEY", "GROK_MODEL", "GROQ_API_KEY",
                 "GROQ_MODEL", "XAI_API_KEY", "XAI_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize(("selection", "key_var", "expected_host", "model"), [
    ("groq", "GROQ_API_KEY", "api.groq.com", "openai/gpt-oss-120b"),
    ("xai", "XAI_API_KEY", "api.x.ai", "grok-4.3"),
    ("openai", "OPENAI_API_KEY", "api.openai.com", "gpt-4.1-mini"),
])
def test_provider_uses_its_own_key_and_endpoint(provider_env, selection, key_var, expected_host, model):
    provider_env.setenv("GROQ_API_KEY", "gsk_an_unrelated_key")
    provider_env.setenv(key_var, "the_selected_key")
    provider_env.setenv("AI_PROVIDER", selection)
    client = GrokClient()
    assert client.is_configured()
    assert client.config.key == "the_selected_key"
    assert client.config.model == model
    assert client.client.base_url.host == expected_host
    client.client.close()


def test_legacy_groq_ignores_an_xai_model(provider_env):
    provider_env.setenv("GROK_API_KEY", "gsk_legacy")
    provider_env.setenv("GROK_MODEL", "grok-2-mini")
    assert ProviderConfig.from_env() == ProviderConfig("groq", "gsk_legacy", "openai/gpt-oss-120b")


def test_long_style_assessment_covers_tail_and_labels_invalid_response():
    client = GrokClient(ProviderConfig(None, "", None))
    passages = []

    def create(**kwargs):
        passage = json.loads(kwargs["messages"][1]["content"])["passage"]
        passages.append(passage)
        score = "out of bounds" if "second section" in passage else 24
        payload = {"style_score": score, "signals": []}
        return SimpleNamespace(choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=json.dumps(payload))),
        ])

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    text = "Start " + ("alpha " * 2_000) + "second section and document tail"
    outcome = client.analyze_ai_content(text)
    assert sum(map(len, passages)) == len(text)
    assert any(passage.endswith("document tail") for passage in passages)
    assert outcome["method"] == "partial"
    assert outcome["warning"]


def test_similarity_counts_unique_word_positions_and_preserves_offsets(monkeypatch):
    text = "🚀 Solar energy converts sunlight into electricity [1] reliably today. Solar energy converts sunlight into electricity. A lone unmatched phrase."
    page = "Solar energy converts sunlight into electricity reliably today. A different ending."
    sources = [
        {"url": f"https://{domain}/", "domain": domain, "title": domain}
        for domain in ("example.com", "example.org")
    ]
    monkeypatch.setattr(web_sources, "search", lambda _: (sources, 4, 0))
    monkeypatch.setattr(web_sources, "page_text", lambda _: page)
    score, matches, spans, coverage = check_similarity(text)
    assert score == 77.8
    assert [item["match_percentage"] for item in matches] == [77.8, 77.8]
    assert spans[0]["start"] == text.index("Solar")
    assert all(text[item["start"]:item["end"]] == item["text"] for item in spans)
    assert coverage["checked"] == 2


def test_unavailable_search_has_no_numeric_score(monkeypatch):
    monkeypatch.setattr(web_sources, "search", lambda _: ([], 4, 4))
    score, _, _, coverage = check_similarity("A search failure needs a visible result.")
    assert score is None
    assert coverage["status"] == "unavailable"


def test_partial_coverage_retains_observed_overlap(monkeypatch):
    source = {"url": "https://example.com/", "domain": "example.com", "title": "Sample"}
    monkeypatch.setattr(web_sources, "search", lambda _: ([source], 4, 3))
    text = "Enough words were checked for public web overlap."
    monkeypatch.setattr(web_sources, "page_text", lambda _: text)
    score, _, _, coverage = check_similarity(text)
    assert score == 100
    assert coverage["status"] == "partial"


def test_known_sources_are_rescanned_even_when_fresh_search_has_failed(monkeypatch):
    source = {"url": "https://example.com/", "domain": "example.com", "title": "Sample"}
    text = "The original source still contains these words."
    monkeypatch.setattr(web_sources, "search", lambda _: ([], 4, 4))
    monkeypatch.setattr(web_sources, "page_text", lambda _: text)
    score, _, _, coverage = check_similarity(text, [source])
    assert score == 100
    assert coverage["status"] == "partial"


def test_rejects_nonpublic_dns_results_before_opening_connection(monkeypatch):
    monkeypatch.setattr(web_sources.socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.10.10.10", 443)),
    ])
    with pytest.raises(web_sources.FetchError):
        web_sources.resolve_public_host("example.org", 443)


def test_rewrite_preserves_citations_and_rejects_lost_markers():
    original = "It is important to note that energy losses were 12% (Shah, 2020) [3–5]."
    valid = SimpleNamespace(edit_chunk=lambda text: EditResponse(
        humanized_text=text.replace("It is important to note that", "Note that"),
        changes_summary=["Simplified the introduction"],
    ))
    result, changes, failed = edit_section(valid, 0, original)
    assert result == "Note that energy losses were 12% (Shah, 2020) [3–5]."
    assert changes and not failed

    invalid = SimpleNamespace(edit_chunk=lambda text: EditResponse(
        humanized_text="Note that energy losses were significant.", changes_summary=[],
    ))
    assert edit_section(invalid, 0, original) == (original, [], True)


def test_rewrite_verifies_fresh_output_and_ignores_a_stale_report(api, monkeypatch):
    original = "It is important to note that solar power works (Shah, 2020)."
    replacement = "Measurements show that solar power works (Shah, 2020)."
    audits = []
    real_audit = workspace.sentinel.run_audit

    def audit(text, known_sources=()):
        audits.append(text)
        report = real_audit(text, known_sources)
        report["similarity_score"] = report["plagiarism_score"] = 81 if text == replacement else 73
        return report

    monkeypatch.setattr(workspace.sentinel, "run_audit", audit)
    monkeypatch.setattr(workspace.client, "is_configured", lambda: True)
    monkeypatch.setattr(workspace.client, "edit_chunk", lambda text: EditResponse(
        humanized_text=text.replace("It is important to note that", "Measurements show that"),
        changes_summary=["Simplified the introduction"],
    ))
    old = api.post("/api/agent1/check", json={"text": original + " First draft."}).json
    result = api.post("/api/agent2/humanize", json={
        "text": original, "audit_token": old["audit_token"], "agent1_report": {"similarity_score": 0},
    })
    assert result.status_code == 200
    assert audits == [original + " First draft.", original, replacement]
    assert result.json["before_scores"]["similarity_score"] == 73
    assert result.json["after_scores"]["similarity_score"] == 81

    current = api.post("/api/agent1/check", json={"text": original}).json
    result = api.post("/api/agent2/humanize", json={"text": original, "audit_token": current["audit_token"]})
    assert result.status_code == 200
    assert audits[-2:] == [original, replacement]


def test_status_and_validation(api):
    assert api.get("/healthz").json == {"status": "online"}
    assert api.get("/").headers["Content-Security-Policy"].startswith("default-src 'self';")
    assert api.post("/api/agent1/check", json={"text": None}).status_code == 400
    assert api.post("/api/agent1/check", json={"text": "a" * 60_001}).status_code == 413
    assert api.post("/api/agent1/check", data={"text": "document"}).status_code == 415


def test_auth_origin_and_rate_limit(api, monkeypatch):
    settings = workspace.app.config
    monkeypatch.setitem(settings, "REQUIRE_AUTH", True)
    assert api.get("/api/status").status_code == 503
    monkeypatch.setitem(settings, "ACCESS_TOKEN", "workspace-password")
    monkeypatch.setitem(settings, "RATE_LIMIT", 1)
    monkeypatch.setattr(workspace.time, "time", lambda: 60 * 120 + 5)
    assert api.get("/api/status").status_code == 401
    auth = Authorization("basic", {"username": "educheck", "password": "workspace-password"})
    payload = {"text": "A test document can be checked repeatedly."}
    path = "/api/agent1/check"
    assert api.post(path, json=payload, auth=auth, headers={"Origin": "https://example.org"}).status_code == 403
    assert api.post(path, json=payload, auth=auth).status_code == 200
    limited = api.post(path, json=payload, auth=auth)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "55"


def test_concurrent_uploads_with_same_name_are_isolated(api):
    def upload(text):
        with workspace.app.test_client() as worker:
            return worker.post("/api/upload", data={"file": (io.BytesIO(text.encode()), "report.txt")}).json["text"]

    texts = [f"Independent document {number}" for number in range(8)]
    with ThreadPoolExecutor() as pool:
        assert list(pool.map(upload, texts)) == texts
    unsupported = api.post("/api/upload", data={"file": (io.BytesIO(b"hello"), "sample.bin")})
    assert unsupported.status_code == 415


def test_odt_paragraphs_and_docx_tables_are_extracted(tmp_path):
    odt = tmp_path / "letter.odt"
    with ZipFile(odt, "w") as package:
        package.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        package.writestr("content.xml", """<o:document-content
            xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
            xmlns:t="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
            <o:body><o:text><t:h>Title</t:h><t:p>Read<t:s t:c="2"/>this <t:span>part</t:span>.</t:p>
            </o:text></o:body></o:document-content>""")
    assert extract_document(odt)[0] == "Title\n\nRead  this part."

    docx = tmp_path / "letter.docx"
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with ZipFile(docx, "w") as package:
        package.writestr("word/document.xml", f"""<w:document xmlns:w="{namespace}"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
            <w:body><w:p><w:r><w:t>Paragraph</w:t><w:footnoteReference w:id="2"/></w:r></w:p>
            <w:p><w:hyperlink r:id="rId9"><w:r><w:t>Reference site</w:t></w:r></w:hyperlink></w:p>
            <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
            </w:body></w:document>""")
        package.writestr("word/_rels/document.xml.rels", """<Relationships>
            <Relationship Id="rId9" Type="https://example.org/hyperlink"
                Target="https://example.org/reference" TargetMode="External"/>
            </Relationships>""")
        package.writestr("word/footnotes.xml", f"""<w:footnotes xmlns:w="{namespace}">
            <w:footnote w:id="2"><w:p><w:r><w:t>Footnote content.</w:t></w:r></w:p></w:footnote>
            </w:footnotes>""")
    assert extract_document(docx)[0] == (
        "Paragraph[2]\n\nReference site (https://example.org/reference)\n\nTable cell\n\nNotes\n\n[2] Footnote content."
    )


def test_mislabeled_binary_document_is_rejected(tmp_path):
    malformed = tmp_path / "invalid.doc"
    malformed.write_bytes(b"Text labeled as binary Word")
    with pytest.raises(DocumentError, match="legacy Word"):
        extract_document(malformed)


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is needed for scanned PDF coverage")
def test_scanned_pdf_uses_real_ocr(tmp_path):
    image = Image.new("RGB", (1400, 800), "white")
    sentence = "Academic integrity requires clear attribution."
    ImageDraw.Draw(image).text((90, 175), sentence, fill="black", font=ImageFont.load_default(size=47))
    filename = tmp_path / "scanned.pdf"
    image.save(filename, "PDF")
    text, metadata = extract_document(filename)
    assert sentence in text
    assert metadata["ocr_pages"] == 1
