FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/New_York

WORKDIR /app

# Alpine ships no zoneinfo; TZ is ignored without it.
RUN apk add --no-cache tzdata

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

RUN adduser -D appuser \
 && mkdir /backups \
 && chown appuser /backups
USER appuser

VOLUME /backups

CMD ["python", "-m", "netgear_backup"]
