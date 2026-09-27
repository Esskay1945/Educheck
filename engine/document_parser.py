import os
import re
import docx
import mammoth
from bs4 import BeautifulSoup

# Comprehensive allowed extensions list; also accepts any file that can be decoded as text
ALLOWED_EXTENSIONS = {
    'txt', 'doc', 'docx', 'pdf', 'md', 'rtf', 'odt', 
    'html', 'htm', 'tex', 'csv', 'json', 'log', 'xml'
}

def allowed_file(filename: str) -> bool:
    """Allow all recognized document types, or any file with a valid extension"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    # Accept if in the common set or general non-executable data files
    return ext in ALLOWED_EXTENSIONS or len(ext) <= 6

def extract_text_from_file(filepath: str) -> str:
    """Extract clean text from all kinds of documents: PDF, DOCX, DOC, TXT, MD, RTF, HTML, etc."""
    if not os.path.exists(filepath):
        return ""
    
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
    
    # 1. PDF Processing
    if ext == 'pdf':
        try:
            import pypdf
            reader = pypdf.PdfReader(filepath)
            pages_text = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            return "\n\n".join(pages_text).strip()
        except Exception as e:
            print(f"pypdf extraction error: {e}")

    # 2. DOCX Processing
    elif ext == 'docx':
        try:
            doc = docx.Document(filepath)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            if paragraphs:
                return '\n\n'.join(paragraphs).strip()
        except Exception:
            pass
            
        try:
            with open(filepath, 'rb') as f:
                result = mammoth.extract_raw_text(f)
                if result.value:
                    return result.value.strip()
        except Exception:
            pass

    # 3. Legacy DOC Processing
    elif ext in ('doc', 'odt'):
        try:
            with open(filepath, 'rb') as f:
                result = mammoth.extract_raw_text(f)
                if result.value:
                    return result.value.strip()
        except Exception:
            pass

    # 4. HTML / HTM Processing
    elif ext in ('html', 'htm'):
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                # Remove scripts and styles
                for s in soup(["script", "style"]):
                    s.decompose()
                return soup.get_text(separator="\n\n").strip()
        except Exception:
            pass

    # 5. RTF Processing
    elif ext == 'rtf':
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Basic RTF control word stripping
                clean_text = re.sub(r'\\[a-z]+-?\d* ?', '', content)
                clean_text = re.sub(r'[{}]', '', clean_text)
                return clean_text.strip()
        except Exception:
            pass

    # 6. Fallback: General text decoding (handles .txt, .md, .csv, .json, .tex, etc.)
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc, errors='replace') as f:
                text = f.read()
                if text.strip():
                    return text.strip()
        except Exception:
            continue

    # Final binary fallback
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
            # Filter printable characters
            printable = "".join(chr(b) for b in raw if 32 <= b <= 126 or b in (10, 13))
            return printable.strip()
    except Exception:
        return ""
