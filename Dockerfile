FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EDUCHECK_REQUIRE_AUTH=1 \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home educheck

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=educheck:educheck app.py .
COPY --chown=educheck:educheck engine/ engine/
COPY --chown=educheck:educheck templates/ templates/
COPY --chown=educheck:educheck static/ static/
RUN install -d -o educheck -g educheck /app/instance
USER educheck

EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn app:app --preload --no-control-socket --bind 0.0.0.0:$PORT --timeout 150 --workers 2"]
