"""Bounded web search and fetching for similarity checks."""

import ipaddress
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit

import urllib3
from bs4 import BeautifulSoup

USER_AGENT = "EduCheck/1.1 (public web similarity checks; https://github.com/Esskay1945/Educheck)"
REDIRECTS = {301, 302, 303, 307, 308}
MAX_BYTES = 1_500_000
PUBLIC_IPV6 = ipaddress.ip_network("2000::/3")
HOST_PATTERN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.I)


class FetchError(Exception):
    """The source could not be safely or completely read."""


def source_url(url):
    """Normalize a public web URL. DNS and connection checks happen before fetching."""
    if not isinstance(url, str) or len(url) > 2_048 or any(ord(c) < 33 for c in url) or "\\" in url:
        raise FetchError("Invalid web URL")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (ValueError, UnicodeError) as error:
        raise FetchError("Invalid web URL") from error
    ports = {"http": 80, "https": 443}
    if (
        parsed.scheme not in ports or port not in (None, ports[parsed.scheme])
        or parsed.username is not None or parsed.password is not None
        or not HOST_PATTERN.fullmatch(host)
    ):
        raise FetchError("Unsupported web URL")
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    return urlunsplit((parsed.scheme, host, path, query, ""))


def resolve_public_host(host, port):
    addresses = []
    for _, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(sockaddr[0])
        address = getattr(address, "ipv4_mapped", None) or address
        reserved = not address.is_global or address.is_multicast
        transition = address.version == 6 and (
            address not in PUBLIC_IPV6 or address.sixtofour is not None or address.teredo is not None
        )
        if reserved or transition:
            raise FetchError("Source destination is outside the public internet")
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses:
        raise FetchError("Source host did not resolve")
    return addresses


def fetch(url, allowed_types, method="GET", body=None, redirects=0):
    deadline = time.monotonic() + 7
    for step in range(redirects + 1):
        url = source_url(url)
        parsed = urlsplit(url)
        host = parsed.hostname
        secure = parsed.scheme == "https"
        port = 443 if secure else 80
        addresses = resolve_public_host(host, port)
        headers = {"Host": host, "User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        target = urlunsplit(("", "", parsed.path, parsed.query, ""))
        response = None
        connection = None
        try:
            for address in addresses[:2]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                timeout = urllib3.Timeout(connect=min(2, remaining), read=min(2, remaining))
                if secure:
                    connection = urllib3.HTTPSConnectionPool(
                        address, port, assert_hostname=host, server_hostname=host, cert_reqs="CERT_REQUIRED"
                    )
                else:
                    connection = urllib3.HTTPConnectionPool(address, port)
                try:
                    response = connection.urlopen(
                        method, target, headers=headers, body=body, timeout=timeout,
                        retries=False, redirect=False, preload_content=False,
                    )
                    break
                except (urllib3.exceptions.HTTPError, OSError):
                    connection.close()
            if response is None:
                raise FetchError("Source connection failed")
            if response.status in REDIRECTS:
                location = response.headers.get("Location")
                if step == redirects or not location:
                    raise FetchError("Source redirect could not be followed")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise FetchError("Source returned an unsuccessful status")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if content_type not in allowed_types or encoding != "identity":
                raise FetchError("Unsupported source response")
            data = bytearray()
            for chunk in response.stream(16_384, decode_content=False):
                data.extend(chunk)
                if len(data) > MAX_BYTES or time.monotonic() > deadline:
                    raise FetchError("Source exceeded the size or time limit")
            return bytes(data)
        finally:
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()
    raise FetchError("Source redirect limit reached")


HTML_TYPES = {"text/html", "application/xhtml+xml"}


def wikipedia(query):
    url = "https://en.wikipedia.org/w/api.php?" + urlencode({
        "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 3,
    })
    data = json.loads(fetch(url, {"application/json"}))
    return [
        {"title": item["title"], "url": "https://en.wikipedia.org/wiki/" + quote(item["title"].replace(" ", "_"))}
        for item in data["query"]["search"]
    ]


def duckduckgo(query):
    page = BeautifulSoup(fetch(
        "https://html.duckduckgo.com/html/", HTML_TYPES,
        method="POST", body=urlencode({"q": f'"{query}"'}).encode(),
    ), "html.parser")
    results = page.select(".result__a")
    if not results and not page.select_one(".no-results, .result--no-result"):
        raise FetchError("Web index returned an unavailable results page")
    sources = []
    for anchor in results[:5]:
        raw = urljoin("https://duckduckgo.com", anchor.get("href", ""))
        parsed = urlsplit(raw)
        if parsed.hostname == "duckduckgo.com" and parsed.path == "/l/":
            raw = parse_qs(parsed.query).get("uddg", [""])[0]
        try:
            url = source_url(raw)
        except FetchError:
            continue
        if urlsplit(url).hostname not in {"duckduckgo.com", "html.duckduckgo.com"}:
            sources.append({"title": anchor.get_text(" ", strip=True), "url": url})
    return sources


def search(queries):
    jobs = [(provider, query) for query in queries for provider in (duckduckgo, wikipedia)]
    by_rank = [[] for _ in range(5)]
    failed = 0

    def run(job):
        provider, query = job
        try:
            return provider(query)
        except (FetchError, OSError, urllib3.exceptions.HTTPError, ValueError, KeyError, TypeError):
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for results in pool.map(run, jobs):
            if results is None:
                failed += 1
                continue
            for rank, item in enumerate(results):
                try:
                    url = source_url(item["url"])
                except FetchError:
                    continue
                by_rank[rank].append({**item, "url": url, "domain": urlsplit(url).hostname})
    candidates = {}
    for source in (source for rank in by_rank for source in rank):
        candidates.setdefault(source["url"], source)
    return list(candidates.values()), len(jobs), failed


def page_text(url):
    try:
        data = fetch(url, HTML_TYPES | {"text/plain"}, redirects=2)
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "sup"]):
            tag.decompose()
        content = soup.find(id="mw-content-text") or soup.find("main") or soup.find("article") or soup
        return content.get_text(" ", strip=True)
    except (FetchError, OSError, urllib3.exceptions.HTTPError, ValueError):
        return ""
