import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from engine.agent1_checker import Agent1Checker
from engine.agent2_humanizer import Agent2Humanizer, audit_summary, baseline_sources
from engine.document_parser import (
    MAX_TEXT_LENGTH, DocumentError, allowed_file, check_text_length, extract_document,
)
from engine.grok_client import GrokClient

load_dotenv()
app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    MAX_FORM_PARTS=8,
    ACCESS_TOKEN=os.environ.get("EDUCHECK_ACCESS_TOKEN", ""),
    REQUIRE_AUTH=os.environ.get("EDUCHECK_REQUIRE_AUTH") == "1",
    RATE_LIMIT=int(os.environ.get("EDUCHECK_RATE_LIMIT", "12")),
    GLOBAL_RATE_LIMIT=int(os.environ.get("EDUCHECK_GLOBAL_RATE_LIMIT", "36")),
    RATE_DB=Path(os.environ.get("EDUCHECK_RATE_DB", Path(app.instance_path) / "limits.sqlite")),
    SECRET_KEY=os.environ.get("EDUCHECK_SECRET_KEY") or secrets.token_hex(32),
)
if min(app.config["RATE_LIMIT"], app.config["GLOBAL_RATE_LIMIT"]) < 1:
    raise ValueError("EduCheck rate limits must be positive.")
proxy_hops = int(os.environ.get("EDUCHECK_PROXY_HOPS", "0"))
if proxy_hops > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops)

client = GrokClient()
sentinel = Agent1Checker(client)
artisan = Agent2Humanizer(client, sentinel)


def error_response(message, status, **headers):
    response = jsonify(error=message)
    response.headers.update({key.replace("_", "-"): value for key, value in headers.items()})
    return response, status


def consume_request(peer):
    now = int(time.time())
    minute = now // 60
    database = Path(app.config["RATE_DB"])
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=3)) as connection:
        with connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS requests (
                minute INTEGER, scope TEXT, count INTEGER, PRIMARY KEY (minute, scope)
            )""")
            connection.execute("DELETE FROM requests WHERE minute < ?", (minute - 1,))
            for scope, limit in (("global", app.config["GLOBAL_RATE_LIMIT"]), ("ip:" + peer, app.config["RATE_LIMIT"])):
                consumed = connection.execute("""
                    INSERT INTO requests VALUES (?, ?, 1)
                    ON CONFLICT (minute, scope) DO UPDATE SET count = count + 1 WHERE count < ?
                """, (minute, scope, limit))
                if not consumed.rowcount:
                    connection.rollback()
                    return 60 - now % 60
    return None


@app.before_request
def protect_workspace():
    if request.endpoint == "health" or request.endpoint == "static":
        return None
    token = app.config["ACCESS_TOKEN"]
    if app.config["REQUIRE_AUTH"] and not token:
        return error_response("Workspace access is unavailable until the server is configured.", 503)
    if token:
        auth = request.authorization
        password = auth.password if auth and auth.type == "basic" else None
        if not password or not secrets.compare_digest(password.encode(), token.encode()):
            return error_response("Workspace sign-in is required.", 401,
                                  WWW_Authenticate='Basic realm="EduCheck", charset="UTF-8"')
    if request.method == "POST" and request.path.startswith("/api/"):
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin and not same_origin_host(origin)
        ):
            return error_response("The request must come from the EduCheck workspace.", 403)
        try:
            retry = consume_request(request.remote_addr or "unknown")
        except (OSError, sqlite3.Error):
            app.logger.exception("EduCheck rate limit storage is unavailable")
            return error_response("Request processing is temporarily unavailable.", 503)
        if retry is not None:
            return error_response("Too many requests. Wait before trying again.", 429, Retry_After=str(retry))
    return None


def same_origin_host(origin):
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request.host.lower()
    except ValueError:
        return False


@app.after_request
def security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(HTTPException)
def http_error(error):
    messages = {
        400: "Invalid request.", 404: "Route not found.", 405: "Method not allowed.",
        413: "The request exceeds the upload or document size limit.", 415: "Unsupported request format.",
    }
    return error_response(messages.get(error.code, "The request could not be processed."), error.code)


@app.errorhandler(Exception)
def unexpected_error(error):
    app.logger.exception("EduCheck request failed")
    return error_response("The request could not be completed. Try again later.", 500)


@app.get("/healthz")
def health():
    return jsonify(status="online")


@app.get("/")
def index():
    return render_template(
        "index.html", provider=client.config.provider if client.is_configured() else None,
        max_length=MAX_TEXT_LENGTH,
    )


@app.get("/api/status")
def get_status():
    return jsonify(
        status="online",
        engine="EduCheck Sentinel & Artisan",
        ai_configured=client.is_configured(),
        grok_configured=client.is_configured(),
        provider=client.config.provider,
        default_model=client.config.model,
    )


@app.post("/api/upload")
def upload_file():
    file = request.files.get("file")
    if not file or not file.filename:
        return error_response("Select a document to upload.", 400)
    if not allowed_file(file.filename):
        return error_response("Unsupported file format. Choose a document from the listed formats.", 415)
    extension = Path(file.filename).suffix.lower()
    filename = secure_filename(file.filename)
    if Path(filename).suffix.lower() != extension:
        filename = "document" + extension
    try:
        with TemporaryDirectory(prefix="educheck-") as directory:
            path = Path(directory) / ("upload" + extension)
            file.save(path)
            text, metadata = extract_document(path, extension)
    except DocumentError as error:
        return error_response(str(error), error.status)
    return jsonify(filename=filename, text=text, word_count=len(text.split()), char_count=len(text), **metadata)


def document_request():
    request.max_content_length = 1024 * 1024
    data = request.get_json(silent=True)
    if not request.is_json:
        raise DocumentError("Send the document as JSON.", 415)
    if not isinstance(data, dict) or not isinstance(data.get("text"), str) or not data["text"].strip():
        raise DocumentError("Provide a nonempty document in the text field.", 400)
    text = data["text"].strip()
    try:
        text.encode("utf-8")
    except UnicodeError as error:
        raise DocumentError("The document contains invalid Unicode.", 400) from error
    return check_text_length(text), data


def report_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="educheck-audit-v1")


def text_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@app.errorhandler(DocumentError)
def document_error(error):
    return error_response(str(error), error.status)


@app.post("/api/agent1/check")
def sentinel_check():
    text, _ = document_request()
    report = sentinel.run_audit(text)
    report["audit_token"] = report_serializer().dumps({
        "hash": text_digest(text),
        "scores": audit_summary(report),
        "sources": baseline_sources(report),
    })
    return jsonify(report)


@app.post("/api/agent2/humanize")
def artisan_remediate():
    text, data = document_request()
    baseline = None
    sources = []
    token = data.get("audit_token")
    if isinstance(token, str) and len(token) <= 24_000:
        try:
            previous = report_serializer().loads(token, max_age=1800)
            if previous["hash"] == text_digest(text):
                baseline = previous["scores"]
                sources = previous.get("sources", [])
        except BadData:
            pass
    return jsonify(artisan.remediate(text, baseline, sources))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
