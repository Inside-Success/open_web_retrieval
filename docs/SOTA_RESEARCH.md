# Web Fetch SOTA Research (2026-03-24)

Researched before implementing Plan #01. Preserved here for future reference.

## Tool Comparison

| Tool | Verdict |
|------|---------|
| **Crawl4AI** | Best OSS option for anti-bot — free, 62.5k stars, 3-tier detection. But requires Playwright (~150MB), 100-200MB RAM/browser, known memory leaks. Deferred to ROADMAP v0.5. |
| **Firecrawl** | 95.3% success rate (vs Crawl4AI 89.7%). But self-hosted is crippled (anti-bot is proprietary). Cloud: $16-599/mo. |
| **Scrapfly** | Best anti-bot bypass (20+ systems, CAPTCHA solving). Cloud-only, $30-100/mo. |
| **Tavily** | Search API, not a fetcher. Complementary to Brave/SearxNG. |
| **Jina Reader** | URL→Markdown. Explicitly does NOT bypass anti-bot. Free tier: 20 RPM. |
| **ScrapeGraphAI** | LLM-powered extraction. Wrong tool — too expensive per page for bulk. |
| **retryhttp** | tenacity-based, retries 429/500/502/503/504. Supports httpx natively. 14 stars. |
| **httpx-retries** | Transport-layer retry for httpx. Successor to deprecated httpx-retry. |
| **httpx+trafilatura** | Our current stack. Community consensus: still recommended for cooperative sites. |

## Community Findings

- Crawl4AI anti-bot works via 3-tier escalation: HTTP status → proxy rotation → fallback function
- `CrawlResult.crawl_stats` exposes `resolved_by: "direct"|"proxy"|"fallback_fetch"|null`
- FlareSolverr (similar approach) saw bypass rates drop 90%→30% within weeks of Cloudflare updates
- Cloudflare now uses "AI Labyrinth" — redirects bots to AI-generated honeypot pages
- Anti-bot bypass is an arms race, not a solved problem

## Industry Trends (2026)

- Shift from "httpx + parse" to "browser automation + visual extraction"
- Best practice: use httpx as fast path, escalate to browser only when needed
- "Efficient pattern: LLMs generate scraper code once, run deterministically at scale"
- httpx+trafilatura is still the recommended "Indie/MVP" approach per Bright Data

## Sources

- [Crawl4AI vs Firecrawl: Detailed Comparison 2026 (Bright Data)](https://brightdata.com/blog/ai/crawl4ai-vs-firecrawl)
- [Crawl4AI Anti-Bot Documentation](https://docs.crawl4ai.com/advanced/anti-bot-and-fallback/)
- [Crawl4AI vs Firecrawl: Full Comparison (CapSolver)](https://www.capsolver.com/blog/AI/crawl4ai-vs-firecrawl)
- [AI Web Scraping 2026 (Morph)](https://www.morphllm.com/ai-web-scraping)
- [Cloudflare AI Labyrinth](https://blog.cloudflare.com/ai-labyrinth/)
- [Best Python HTTP Clients 2026 (Bright Data)](https://brightdata.com/blog/web-data/best-python-http-clients)
- [retryhttp GitHub](https://github.com/austind/retryhttp)
- [httpx-retries GitHub](https://github.com/will-ockmore/httpx-retries)
- [Playwright Memory Issues (Microsoft #6319)](https://github.com/microsoft/playwright/issues/6319)
- [Crawl4AI Self-Hosting Guide](https://docs.crawl4ai.com/core/self-hosting/)
- [Crawl4AI Installation](https://docs.crawl4ai.com/core/installation/)
