# unicorn_.py
import scrapy
from scrapy_playwright.page import PageMethod
import logging
import os
import re
import time
from urllib.parse import urlparse


class UnicornSpider(scrapy.Spider):
    name = "unicorn_"
    allowed_domains = ["shop.unicornstore.in"]
    start_urls = ["https://shop.unicornstore.in/product/iphone-15-black-128-gb"]

    custom_settings = {
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30000,
        "LOG_LEVEL": "INFO",
    }

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_selector", "body"),
                        PageMethod("wait_for_timeout", 100),
                    ],
                },
                callback=self.parse,
                dont_filter=True,
            )

    def _make_safe_filename(self, url: str) -> str:
        """Create a safe filename from the product URL (slug + timestamp)."""
        parsed = urlparse(url)
        # take last non-empty path segment
        segments = [seg for seg in parsed.path.split("/") if seg]
        slug = segments[-1] if segments else "product"
        # sanitize: allow alnum, -, _
        safe = re.sub(r"[^0-9a-zA-Z_\-]+", "_", slug).strip("_")
        if not safe:
            safe = "product"
        ts = int(time.time())
        return f"{safe}_{ts}.html"

    async def parse(self, response):
        page = response.meta.get("playwright_page")
        overview_html = None

        # ---------- 1) Listen for responses that look like the "overview" fragment ----------
        if page:
            matching_resps = []

            def on_response(resp):
                try:
                    url_lower = (resp.url or "").lower()
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "overview" in url_lower or url_lower.endswith(".html") or "text/html" in ct:
                        matching_resps.append(resp)
                        logging.info(f"[listener] candidate response captured: {resp.url}")
                except Exception:
                    pass

            page.on("response", on_response)

            try:
                clicked = False
                try:
                    await page.click("text=Overview", timeout=3000)
                    clicked = True
                except Exception:
                    try:
                        await page.click("span.p-tabview-title:has-text('Overview')", timeout=3000)
                        clicked = True
                    except Exception:
                        logging.info("Could not click Overview using selectors; continuing.")

                await page.wait_for_timeout(1400)  # wait for network responses to arrive

                if matching_resps:
                    resp_obj = matching_resps[-1]
                    try:
                        overview_html = await resp_obj.text()
                        logging.info(f"Captured overview HTML from response: {resp_obj.url}")
                    except Exception as e:
                        logging.warning(f"Failed to read resp.text(): {e}")

                # try expect_response if available and nothing captured yet
                if not overview_html:
                    try:
                        if hasattr(page, "expect_response"):
                            def predicate(r): return (
                                ("overview" in (r.url or "").lower())
                                or (r.url or "").lower().endswith(".html")
                                or "text/html" in ((r.headers.get("content-type") or "").lower())
                            )
                            async with page.expect_response(predicate) as resp_cm:
                                if not clicked:
                                    try:
                                        await page.click("text=Overview", timeout=3000)
                                    except Exception:
                                        pass
                            resp_obj = resp_cm.value
                            overview_html = await resp_obj.text()
                            logging.info(
                                f"[expect_response] captured overview HTML from {resp_obj.url}")
                    except Exception:
                        pass

            finally:
                try:
                    page.off("response", on_response)
                except Exception:
                    pass
                try:
                    await page.close()
                except Exception:
                    pass

        # ---------- 2) Fallback: try to extract from rendered DOM ----------
        if not overview_html:
            selectors_to_try = [
                "div.p-tabview-panels div.p-tabview-panel.p-tabview-panel-active",
                "div.p-tabview-panels",
                "section#overview",
                "div.overview",
                "div#overview",
            ]
            for sel in selectors_to_try:
                overview_html = response.css(sel).get()
                if overview_html:
                    logging.info(f"Found overview in DOM using selector: {sel}")
                    break

        # ---------- 3) Final fallback: save whole page HTML ----------
        if not overview_html:
            logging.warning(
                "Overview not found by network or DOM selectors; falling back to full page HTML.")
            overview_html = response.text

        # ---------- 4) Save result into overview/ folder ----------
        out_dir = "overview"  # <- dedicated folder requested
        os.makedirs(out_dir, exist_ok=True)

        filename = self._make_safe_filename(response.url)
        filepath = os.path.join(out_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(overview_html or "")

        logging.info(f"Saved overview HTML to {filepath}")
        yield {"file": filepath}

