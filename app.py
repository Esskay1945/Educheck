import os
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from engine.document_parser import allowed_file, extract_text_from_file
from engine.grok_client import GrokClient, DEFAULT_GROK_MODEL
from engine.agent1_checker import Agent1Checker
from engine.agent2_humanizer import Agent2Humanizer

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Shared client instance (configured via env)
default_grok_client = GrokClient()
default_sentinel = Agent1Checker(default_grok_client)
default_artisan = Agent2Humanizer(default_grok_client, default_sentinel)

def get_engines(req_api_key: str = None, req_model: str = None):
    """Retrieve engine instances with optional environment or request Grok configuration"""
    api_key = req_api_key or os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY")
    model = req_model or DEFAULT_GROK_MODEL
    
    if api_key:
        client = GrokClient(api_key=api_key, model=model)
        sentinel = Agent1Checker(client)
        artisan = Agent2Humanizer(client, sentinel)
        return sentinel, artisan, client
    return default_sentinel, default_artisan, default_grok_client

@app.route('/')
def index():
    has_env_key = bool(os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY"))
    return render_template('index.html', has_grok_key=has_env_key)

@app.route('/api/status', methods=['GET'])
def get_status():
    has_key = bool(os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY"))
    return jsonify({
        "status": "online",
        "engine": "EduCheck Sentinel & Artisan Forensic Studio",
        "grok_configured": has_key,
        "default_model": DEFAULT_GROK_MODEL
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        extracted_text = extract_text_from_file(filepath)
        word_count = len(extracted_text.split())
        char_count = len(extracted_text)
        
        try:
            os.remove(filepath)
        except Exception:
            pass

        if not extracted_text:
            return jsonify({"error": "Could not extract text from document"}), 400

        return jsonify({
            "filename": filename,
            "text": extracted_text,
            "word_count": word_count,
            "char_count": char_count
        })
    
    return jsonify({"error": "Unsupported file format. Please upload a valid document or text file."}), 400

@app.route('/api/agent1/check', methods=['POST'])
def sentinel_check():
    data = request.get_json() or {}
    text = data.get('text', '').strip()

    if not text:
        return jsonify({"error": "Input text cannot be empty"}), 400

    sentinel, _, _ = get_engines()
    try:
        report = sentinel.run_audit(text)
        return jsonify(report)
    except Exception as e:
        return jsonify({"error": f"Forensic audit failed: {str(e)}"}), 500

@app.route('/api/agent2/humanize', methods=['POST'])
def artisan_remediate():
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    sentinel_report = data.get('agent1_report')

    if not text:
        return jsonify({"error": "Text to remediate cannot be empty"}), 400

    _, artisan, _ = get_engines()
    try:
        remediation = artisan.remediate(text, sentinel_report)
        return jsonify(remediation)
    except Exception as e:
        return jsonify({"error": f"Prose reconstruction failed: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
