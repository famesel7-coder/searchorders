# ADR 0003 — Social/community sources only

Date: 2026-08-17
Status: accepted

Search Orders monitors published demand in social networks, messengers and public communities. Freelance exchanges, tender marketplaces and job boards are excluded from ingestion.

Enabled source types are limited to `telegram_public`, `telegram_client`, `vk_wall` and `rss_feed` for community-owned feeds. Configuration loading rejects marketplace source types.

Consequences: marketplace collectors are removed from the active registry; vacancies inside communities are content filtered by intent classification; canonical leads retain links to every source repost. This ADR supersedes earlier source choices wherever they allowed marketplaces in published-demand ingestion.
