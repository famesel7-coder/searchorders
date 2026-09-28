# International collaboration fit scoring

Date: 2026-09-28

## Goal

Do not treat a lead as strong merely because the service match is good. Score whether I’MON can realistically engage as an international remote studio.

## Fit adjustments

- Explicit international / worldwide / global remote: +25
- Remote work supported: +5
- Agencies / white-label partners explicitly accepted: +12
- Country-only / local-only restriction: -45
- Local candidates preferred: -25
- Onsite / studio presence requested: -20
- Role oriented to one individual contractor: -15

Weights live in `config/search_config.json` under `collaboration_fit`.

## Curated leads

The analyst `confidence` remains the base score. The system calculates:

`fit_score = clamp(confidence + collaboration_adjustment, 0, 100)`

The previous conclusion can be downgraded by accessibility constraints, but the automatic fit layer does not upgrade a manually cautious conclusion. This prevents a lead marked `verify_more` from becoming `strong` only because it is global/remote.

The dashboard shows base confidence, fit score, adjustment, and the reasons behind the adjustment.

## Why

This prevents cases like a Canada-preferred individual freelancer role from appearing stronger than a worldwide remote role that is realistically accessible to I’MON.
