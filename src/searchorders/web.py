from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIServer, make_server

from .results_store import read_results, write_results


ScanCallback = Callable[[], Any]


def _money(lead: dict[str, Any]) -> str | None:
    currency = str(lead.get("currency") or "").strip()
    low = lead.get("salary_from")
    high = lead.get("salary_to")
    if isinstance(low, int) and isinstance(high, int):
        return f"{low:,}-{high:,} {currency}".replace(",", " ").strip()
    if isinstance(low, int):
        return f"от {low:,} {currency}".replace(",", " ").strip()
    if isinstance(high, int):
        return f"до {high:,} {currency}".replace(",", " ").strip()
    return None


def _format_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%d.%m.%Y %H:%M")


def _render_badge(bucket: str) -> str:
    label = {
        "hot": "Hot",
        "review": "Review",
        "archive": "Archive",
        "rejected": "Rejected",
    }.get(bucket, bucket.title())
    return f'<span class="badge badge-{html.escape(bucket)}">{html.escape(label)}</span>'


def _render_card(item: dict[str, Any]) -> str:
    lead = item.get("lead", {}) if isinstance(item.get("lead"), dict) else {}
    score = item.get("score", {}) if isinstance(item.get("score"), dict) else {}
    matched_case = item.get("matched_case")
    proposal = item.get("proposal_draft")
    reasons = score.get("reasons", []) if isinstance(score.get("reasons"), list) else []
    budget = _money(lead)
    parts = [
        '<article class="lead-card">',
        '<div class="lead-card-head">',
        _render_badge(str(score.get("bucket", "archive"))),
        f'<div class="score">{html.escape(str(score.get("total", 0)))}/100</div>',
        "</div>",
        f"<h3>{html.escape(str(lead.get('title', 'Без названия')))}</h3>",
        '<div class="meta-row">',
        f"<span>{html.escape(str(lead.get('company_name') or 'Без компании'))}</span>",
        f"<span>{html.escape(str(lead.get('source') or 'unknown'))}</span>",
        f"<span>{html.escape(_format_dt(lead.get('published_at')))}</span>",
        "</div>",
    ]
    if budget:
        parts.append(f'<p class="budget">{html.escape(budget)}</p>')
    description = str(lead.get("description") or "").strip()
    if description:
        parts.append(f'<p class="description">{html.escape(description[:420])}</p>')
    if reasons:
        reasons_markup = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in reasons[:4])
        parts.extend(['<ul class="reasons">', reasons_markup, "</ul>"])
    if isinstance(matched_case, dict):
        parts.append(
            '<p class="case-line">Кейс: '
            f'<a href="{html.escape(str(matched_case.get("url") or "#"))}" target="_blank" rel="noreferrer">'
            f'{html.escape(str(matched_case.get("name") or "Без названия"))}</a></p>'
        )
    if proposal:
        parts.extend(
            [
                "<details>",
                "<summary>Черновик предложения</summary>",
                f"<pre>{html.escape(str(proposal))}</pre>",
                "</details>",
            ]
        )
    source_url = str(lead.get("url") or "").strip()
    if source_url:
        parts.append(
            f'<p class="source-link"><a href="{html.escape(source_url)}" target="_blank" rel="noreferrer">Открыть источник</a></p>'
        )
    parts.append("</article>")
    return "".join(parts)


class SearchOrdersWebApp:
    def __init__(
        self,
        scan_callback: ScanCallback,
        *,
        output_path: Path,
        title: str,
    ) -> None:
        self.scan_callback = scan_callback
        self.output_path = output_path
        self.title = title

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        query = parse_qs(environ.get("QUERY_STRING", ""))
        head_only = method == "HEAD"
        if path == "/":
            if method in {"GET", "HEAD"}:
                return self._html_response(
                    start_response,
                    self._render_page(query=query),
                    head_only=head_only,
                )
            if method == "POST":
                return self._method_not_allowed(start_response)
        if path == "/scan":
            if method != "POST":
                return self._method_not_allowed(start_response)
            return self._html_response(start_response, self._render_after_scan())
        if path == "/results.json":
            if method not in {"GET", "HEAD"}:
                return self._method_not_allowed(start_response)
            payload = read_results(self.output_path) or {"generated_at": None, "summary": {"total": 0, "hot": 0, "review": 0, "archive": 0, "rejected": 0}, "items": []}
            return self._json_response(
                start_response,
                payload,
                head_only=head_only,
            )
        if path == "/healthz":
            if method not in {"GET", "HEAD"}:
                return self._method_not_allowed(start_response)
            return self._text_response(start_response, "ok", head_only=head_only)
        return self._text_response(start_response, "Not found", status="404 Not Found")

    def _render_after_scan(self) -> str:
        try:
            previous_payload = read_results(self.output_path)
            result = self.scan_callback()
            if result.evaluations:
                write_results(self.output_path, result.evaluations)
            summary = (
                f"Проверено {result.collected_count}, новых {result.new_count}, "
                f"сохранено {len(result.evaluations)}."
            )
            if not result.evaluations and previous_payload:
                summary = f"{summary} Новых лидов нет, показываем прошлую сохранённую выдачу."
            return self._render_page(status=("success", summary), warnings=result.warnings)
        except Exception as exc:  # pragma: no cover - defensive path
            return self._render_page(status=("error", f"Сканирование завершилось ошибкой: {exc}"))

    def _render_page(
        self,
        *,
        query: dict[str, list[str]] | None = None,
        status: tuple[str, str] | None = None,
        warnings: list[str] | None = None,
    ) -> str:
        payload = read_results(self.output_path) or {"generated_at": None, "summary": {"total": 0, "hot": 0, "review": 0, "archive": 0, "rejected": 0}, "items": []}
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        banner = ""
        if status:
            status_kind, status_text = status
            banner = f'<div class="banner banner-{html.escape(status_kind)}">{html.escape(status_text)}</div>'
        elif query and query.get("status"):
            banner = f'<div class="banner banner-success">{html.escape(query["status"][0])}</div>'
        warnings_markup = ""
        if warnings:
            warnings_markup = '<div class="warnings"><h3>Предупреждения источников</h3><ul>' + "".join(
                f"<li>{html.escape(str(item))}</li>" for item in warnings
            ) + "</ul></div>"
        cards = "".join(_render_card(item) for item in items[:20] if isinstance(item, dict))
        empty = (
            '<div class="empty-state"><p>Пока нет сохранённых результатов. Нажмите кнопку запуска, и сайт соберёт свежие лиды.</p></div>'
            if not cards
            else f'<div class="card-grid">{cards}</div>'
        )
        generated_at = _format_dt(payload.get("generated_at"))
        return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(self.title)}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: rgba(255, 250, 240, 0.88);
      --ink: #1f2430;
      --muted: #626b7a;
      --line: rgba(31, 36, 48, 0.12);
      --accent: #c65f2a;
      --accent-2: #1f6f78;
      --hot: #b63a2b;
      --review: #b98019;
      --archive: #4f637d;
      --rejected: #5c6370;
      --shadow: 0 20px 60px rgba(46, 30, 18, 0.12);
      --radius: 24px;
      --font-sans: "Avenir Next", "Trebuchet MS", "Segoe UI", sans-serif;
      --font-serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--font-sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(198, 95, 42, 0.22), transparent 28%),
        radial-gradient(circle at left 20%, rgba(31, 111, 120, 0.14), transparent 24%),
        linear-gradient(180deg, #f7f1e9 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .shell {{
      max-width: 1160px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: calc(var(--radius) + 6px);
      box-shadow: var(--shadow);
      overflow: hidden;
      position: relative;
      padding: 28px;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -10% -45% auto;
      width: 280px;
      height: 280px;
      background: radial-gradient(circle, rgba(198, 95, 42, 0.2), transparent 68%);
      pointer-events: none;
    }}
    .kicker {{
      text-transform: uppercase;
      letter-spacing: .18em;
      font-size: 12px;
      color: var(--accent-2);
      margin: 0 0 14px;
    }}
    h1 {{
      margin: 0;
      font-family: var(--font-serif);
      font-size: clamp(34px, 5vw, 56px);
      line-height: 1;
    }}
    .lead {{
      max-width: 760px;
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.6;
    }}
    .hero-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin-top: 22px;
    }}
    button, .link-chip {{
      border: 0;
      border-radius: 999px;
      padding: 13px 18px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    button {{
      background: linear-gradient(135deg, var(--accent), #da7a2e);
      color: #fff7f0;
      box-shadow: 0 14px 30px rgba(198, 95, 42, 0.24);
    }}
    .link-chip {{
      background: rgba(31, 111, 120, 0.08);
      color: var(--accent-2);
      border: 1px solid rgba(31, 111, 120, 0.16);
    }}
    .timestamp {{
      color: var(--muted);
      font-size: 14px;
    }}
    .summary-grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      margin: 24px 0 0;
    }}
    .summary-card {{
      border-radius: 20px;
      padding: 18px;
      background: rgba(255, 255, 255, 0.74);
      border: 1px solid var(--line);
    }}
    .summary-card strong {{
      display: block;
      font-size: 30px;
      line-height: 1;
      margin-bottom: 8px;
      font-family: var(--font-serif);
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 14px;
    }}
    .banner, .warnings {{
      margin-top: 18px;
      border-radius: 18px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
    }}
    .banner-success {{ border-color: rgba(31, 111, 120, 0.22); }}
    .banner-error {{ border-color: rgba(182, 58, 43, 0.22); }}
    .warnings h3 {{
      margin: 0 0 10px;
      font-size: 15px;
    }}
    .warnings ul, .reasons {{
      margin: 0;
      padding-left: 18px;
    }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      margin: 32px 0 18px;
    }}
    .section-title h2 {{
      margin: 0;
      font-size: 26px;
      font-family: var(--font-serif);
    }}
    .section-title p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .card-grid {{
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    }}
    .lead-card {{
      background: rgba(255, 255, 255, 0.84);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
      box-shadow: 0 14px 38px rgba(31, 36, 48, 0.08);
    }}
    .lead-card-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: white;
    }}
    .badge-hot {{ background: var(--hot); }}
    .badge-review {{ background: var(--review); }}
    .badge-archive {{ background: var(--archive); }}
    .badge-rejected {{ background: var(--rejected); }}
    .score {{
      font-weight: 800;
      color: var(--accent-2);
    }}
    .lead-card h3 {{
      margin: 14px 0 8px;
      font-size: 24px;
      line-height: 1.1;
      font-family: var(--font-serif);
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    .budget {{
      margin: 14px 0 0;
      font-weight: 800;
      color: var(--accent);
    }}
    .description {{
      margin: 14px 0;
      color: #343b48;
      line-height: 1.55;
    }}
    .case-line, .source-link {{
      margin: 14px 0 0;
    }}
    .lead-card a {{
      color: var(--accent-2);
      font-weight: 700;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--accent-2);
      margin-top: 14px;
    }}
    pre {{
      white-space: pre-wrap;
      font-family: "SFMono-Regular", "Menlo", monospace;
      background: rgba(31, 36, 48, 0.05);
      padding: 12px;
      border-radius: 16px;
      margin-top: 12px;
      font-size: 13px;
      line-height: 1.5;
    }}
    .empty-state {{
      background: rgba(255, 255, 255, 0.72);
      border: 1px dashed rgba(31, 36, 48, 0.18);
      border-radius: 24px;
      padding: 28px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      .shell {{ padding: 20px 14px 40px; }}
      .hero {{ padding: 20px; }}
      h1 {{ line-height: 0.95; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <p class="kicker">I’MON Lead Desk</p>
      <h1>{html.escape(self.title)}</h1>
      <p class="lead">Отдельный сайт для ручного запуска поиска и просмотра свежих лидов без Telegram. Сайт использует тот же pipeline скоринга, кейс-матчинга и дедупликации, что и CLI.</p>
      <div class="hero-actions">
        <form method="post" action="/scan">
          <button type="submit">Запустить новый поиск</button>
        </form>
        <a class="link-chip" href="/results.json" target="_blank" rel="noreferrer">Открыть JSON</a>
        <span class="timestamp">Последнее сохранение: {html.escape(generated_at)}</span>
      </div>
      <div class="summary-grid">
        <div class="summary-card"><strong>{html.escape(str(summary.get("total", 0)))}</strong><span>Всего лидов</span></div>
        <div class="summary-card"><strong>{html.escape(str(summary.get("hot", 0)))}</strong><span>Hot</span></div>
        <div class="summary-card"><strong>{html.escape(str(summary.get("review", 0)))}</strong><span>Review</span></div>
        <div class="summary-card"><strong>{html.escape(str(summary.get("archive", 0)))}</strong><span>Archive</span></div>
      </div>
      {banner}
      {warnings_markup}
    </section>
    <section>
      <div class="section-title">
        <h2>Последние результаты</h2>
        <p>Показываем до 20 карточек из последнего сохранённого прогона.</p>
      </div>
      {empty}
    </section>
  </main>
</body>
</html>"""

    @staticmethod
    def _html_response(
        start_response: Callable[..., Any],
        body: str,
        *,
        head_only: bool = False,
    ) -> list[bytes]:
        payload = body.encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "text/html; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(payload))),
            ],
        )
        return [] if head_only else [payload]

    @staticmethod
    def _json_response(
        start_response: Callable[..., Any],
        body: dict[str, Any],
        *,
        head_only: bool = False,
    ) -> list[bytes]:
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        start_response(
            "200 OK",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(payload))),
            ],
        )
        return [] if head_only else [payload]

    @staticmethod
    def _text_response(
        start_response: Callable[..., Any],
        body: str,
        *,
        status: str = "200 OK",
        head_only: bool = False,
    ) -> list[bytes]:
        payload = body.encode("utf-8")
        start_response(
            status,
            [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("Content-Length", str(len(payload))),
            ],
        )
        return [] if head_only else [payload]

    def _method_not_allowed(self, start_response: Callable[..., Any]) -> list[bytes]:
        return self._text_response(start_response, "Method not allowed", status="405 Method Not Allowed")


def serve_web(
    scan_callback: ScanCallback,
    *,
    output_path: Path,
    host: str,
    port: int,
    title: str,
) -> WSGIServer:
    app = SearchOrdersWebApp(scan_callback, output_path=output_path, title=title)
    httpd = make_server(host, port, app)
    print(f"Serving Search Orders web UI on http://{host}:{port}")
    return httpd
