FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY data/search_sources.json /app/data/search_sources.json
COPY data/outreach_status.json /app/data/outreach_status.json
COPY realtime_service /app/realtime_service
ENV SEARCHORDERS_HOST=0.0.0.0 SEARCHORDERS_INTERVAL=300 SEARCHORDERS_STATE=/app/.runtime
EXPOSE 8787
CMD ["python","-m","realtime_service.app"]
