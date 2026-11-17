"""Scrape curated public health pages; never fetch an arbitrary internal URL."""
import hashlib
from urllib.parse import urldefrag, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup
from django.conf import settings

from .ingestion import _ingest_document
from .pdf_extractor import ExtractedPDF
from .text_cleaner import clean_text


MAX_PAGE_BYTES = 2 * 1024 * 1024


def validate_source_url(url):
    url = urldefrag(url.strip())[0]
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in settings.INGEST_ALLOWED_HOSTS
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise ValueError("Use an HTTPS URL on one of the listed trusted health websites.")
    if len(url) > 200:
        raise ValueError("Source URLs must be 200 characters or fewer.")
    return url


class TrustedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_webpage(url):
    url = validate_source_url(url)
    request = Request(url, headers={"User-Agent": "HealthKnowledgeBase/1.0", "Accept": "text/html"})
    with build_opener(TrustedRedirects()).open(request, timeout=15) as response:
        validate_source_url(response.geturl())
        if response.headers.get_content_type() != "text/html":
            raise ValueError("This method accepts HTML webpages. Use PDF ingestion for PDF documents.")
        body = response.read(MAX_PAGE_BYTES + 1)
        if len(body) > MAX_PAGE_BYTES:
            raise ValueError("Webpage exceeds the 2 MiB limit.")
    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else urlsplit(url).hostname
    for element in soup.select("script, style, nav, header, footer, aside, form, noscript, [hidden]"):
        element.decompose()
    content = soup.find("main") or soup.find("article") or soup.body
    text = clean_text(content.get_text("\n", strip=True)) if content else ""
    if len(text) < 80:
        raise ValueError("Webpage has too little readable text; JavaScript-only pages are unsupported.")
    # HTML has no printed pages; section 1 represents the entire article.
    return ExtractedPDF([(1, text)], 1, title[:500], urlsplit(url).hostname, [])


def ingest_url(url, *, force=False):
    url = validate_source_url(url)
    extracted = fetch_webpage(url)
    identity = hashlib.sha256(url.encode()).hexdigest()
    checksum = hashlib.sha256(extracted.pages[0][1].encode()).hexdigest()
    return _ingest_document(f"web/{identity}", f"{identity}.html", checksum,
                            lambda: extracted, force=force, source_url=url)
