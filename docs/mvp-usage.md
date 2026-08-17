# MVP usage

Copy `.env.example` to `.env`. Set `WEB_AUTH_TOKEN` when exposing the UI. Public Telegram needs no Telegram secrets; MTProto/VK secrets are needed only when those source types are enabled.

Edit `data/sources.yaml`. Only social/community source types are accepted. Do not turn include keywords into a narrow allow-list: collectors ingest broadly and classification decides whether a post is demand.

```bash
search-orders scan --max-results 30
search-orders catalog --limit 200
search-orders sources-status
```

`--max-results` limits returned new evaluations, not the number of sources that get scanned. Each source has its own `max_details`.

```bash
search-orders web --host 0.0.0.0 --port 8080
```

Public binding requires `WEB_AUTH_TOKEN`. Use `/status.json` for scan state and `/catalog.json` for the persistent catalog.
