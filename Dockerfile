FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY data ./data
RUN mkdir -p /app/output

ENTRYPOINT ["search-orders"]
CMD ["hh", "--hours", "30", "--max-results", "150", "--area", "113", "--output", "/app/output/latest.json"]

