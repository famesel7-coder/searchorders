# SAMSEL portfolio site — launch status

Updated: 2026-10-22

## Primary site

- Primary public URL: https://samsel.site/
- Hosting/project: Vercel project `samsel-portfolio`
- Registrar: REG.RU
- Canonical domain: `samsel.site`
- `www.samsel.site` is attached in Vercel and configured with a permanent 308 redirect to `https://samsel.site/`.

## DNS and HTTPS

- Authoritative nameservers:
  - `ns1.vercel-dns.com`
  - `ns2.vercel-dns.com`
- Public delegation and major resolvers were verified to return the Vercel nameservers on 2026-10-22.
- Apex `samsel.site` resolves through Vercel.
- HTTPS on `https://samsel.site/` returns HTTP 200 with Vercel and HSTS.
- `https://www.samsel.site/` returns 308 to the apex domain and then HTTP 200.

## Site metadata

Production uses the custom domain for:
- canonical URL,
- Open Graph URL/image,
- Twitter image,
- `robots.txt` sitemap reference,
- all URLs in `sitemap.xml`.

## Contact form

- Contact form is routed through the already-activated FormSubmit recipient endpoint.
- Do not commit FormSubmit endpoint tokens/secrets to this repository.
- Recipient email remains `cco@imon.agency`.

## REG.RU

- Registration email for `cco@imon.agency` was confirmed on 2026-10-22.
- REG.RU confirmation page displayed: “Ваш email подтверждён”.

## Final QA

Verified on the custom domain:
- Accessibility: 100
- Best Practices: 100
- SEO: 100
- FCP ~1.2 s
- Speed Index ~2.3 s
- CLS 0

The site is ready to be used as the portfolio link in outbound sales.
