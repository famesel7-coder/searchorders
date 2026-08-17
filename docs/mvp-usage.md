# MVP usage

Copy `.env.example` to `.env`. Set `WEB_AUTH_TOKEN` when exposing the UI. Public Telegram needs no Telegram secrets; MTProto/VK secrets are needed only when those source types are enabled.

Edit `data/sources.yaml`. Only social/community source types are accepted. Do not turn include keywords into a narrow allow-list: collectors ingest broadly and classification decides whether a post is demand.

```bash
search-orders scan --max-results 30
search-orders catalog --limit 200
search-orders sources-status
search-orders feedback-status 42 interesting
```

`--max-results` limits returned new evaluations, not the number of sources that get scanned. Each source has its own `max_details`.

```bash
search-orders web --host 0.0.0.0 --port 8080
```

Public binding requires `WEB_AUTH_TOKEN`. Use `/status.json` for scan state, `/catalog.json` for the persistent catalog, `/sources.json` for source health and `/feedback.json` for feedback distribution. Lead status can also be changed from each web card.

Optional semantic refinement is enabled only when `OPENAI_CLASSIFIER_ENABLED=1` and both `OPENAI_CLASSIFIER_MODEL` and `OPENAI_API_KEY` are configured. Without them the deterministic pipeline is used.
