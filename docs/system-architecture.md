# Search Orders v2 — system architecture

## Product boundary

Search Orders tracks published demand in social/community sources. Marketplaces and job boards are out of scope and rejected at configuration load time.

```text
Source Registry
  ├─ Telegram Public
  ├─ Telegram MTProto
  ├─ VK public walls
  └─ community RSS/Atom
        ↓
Raw Posts → contact/budget extraction → cross-source dedupe
        ↓
Intent: project_demand / employment / self_promo / demand / ambiguous
        ↓
Service + industry tags → scoring → case match → proposal
        ↓
Persistent Lead Catalog
```

## Invariants

- collectors transport facts and never mark Telegram/VK as project work merely because of platform;
- `source_name` is channel/community metadata and is not `company_name`;
- collection limits are per source; output limit is applied after ingestion;
- posts are persisted before evaluation;
- one canonical lead may link to many reposts;
- source failures are isolated and tracked.

## SQLite

`scan_runs` stores lifecycle/counts; `sources` stores health; `posts` stores immutable source identity; `leads` stores canonical evaluation/CRM status; `lead_posts` links reposts; `lead_status_history` audits status changes.

## Runtime

`POST /scan` starts a background scan thread so the HTTP request does not block on every source. Public binding requires `WEB_AUTH_TOKEN`. SQLite remains suitable for the single-node MVP; migrate the same entities to Postgres/queue when multiple workers are needed.
