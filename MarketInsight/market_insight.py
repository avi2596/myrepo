"""
Today's read from two research desks, on one page.

J.P. Morgan Global Research and the Bank of America Institute both publish in
the open, and both bury the good part. J.P. Morgan hangs its charts inside long
article pages; the Institute puts a short summary on the web and keeps every
exhibit in a PDF nobody opens. This script goes and gets both, keeps only the
work that touches the six things worth watching from a US desk — the stock
market, the macro data, the dollar, oil, metals and the wider world — and lays
it out as a dated brief with the charts lifted from the source.

    python market_insight.py                  # build today's brief
    python market_insight.py --days 60        # widen the recency window
    python market_insight.py --no-cache       # ignore the page cache
    python market_insight.py --render-only    # re-render from what's on disk

Each run writes reports/<year>/<date>/ and leaves earlier editions alone, so the
folder becomes a log and the top-level index gains a link per date. Rerun it on
the same day and that day's edition is rebuilt in place. Filing by year keeps
both the folder and the page's own Log navigable once the editions pile up.

Discovery goes through each site's sitemap rather than the homepage, because
the homepages render their cards in the browser and arrive empty. The sitemaps
carry a lastmod date for every page, which is also the only publication date
the Institute exposes; J.P. Morgan articles additionally carry their own
timestamp in a meta tag, and that one is preferred when present.

The charts are the reason this exists. J.P. Morgan's exhibits are real SVGs
sitting in the page, so they come across as vectors and stay sharp. The
Institute's live in the "full analysis" PDF, so that PDF is opened and each
exhibit is cropped out of it — anchored on the "Exhibit N:" caption above the
chart and the source line beneath it, which is the pair that reliably brackets
one figure. Everything is inlined into the HTML as data URIs, so the report is
a single file that can be mailed, archived or published as-is.

What this cannot do is read anything behind a login, and it does not attempt
to: both desks put their deep research behind one. What is here is the public
tier, which is generous enough to be worth reading.

Requires: requests, beautifulsoup4, pymupdf
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from itertools import groupby
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    import pymupdf
except ImportError:                                     # pragma: no cover
    pymupdf = None

HERE = Path(__file__).resolve().parent
REPORTS = HERE / "reports"
CACHE = HERE / ".cache"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

JPM_SITEMAP = "https://www.jpmorgan.com/US/en/sitemap.xml"
JPM_BASE = "https://www.jpmorgan.com"
BOFA_SITEMAP = ("https://institute.bankofamerica.com/content/institute/"
                "bank-of-america-institute.sitemap.xml")
BOFA_BASE = "https://institute.bankofamerica.com"

# The two J.P. Morgan shelves that carry research rather than marketing: the
# global desk's notes, and the markets-and-economy commentary.
JPM_SHELVES = ("/insights/global-research/", "/insights/markets-and-economy/")

# Bank of America Institute sections, in the site's own naming. "Daily
# Insights" is a newsletter with no article pages of its own — its items are
# read off the hub page instead, further down.
BOFA_SECTIONS = {
    "economic-insights": "Economic Insights",
    "institute-insights": "Institute Insights",
    "transformation": "Institute Insights",
    "sustainability": "Institute Insights",
}
BOFA_HUBS = ("", "economic-insights", "institute-insights", "transformation")

CACHE_TTL = 6 * 3600                                    # seconds a page stays fresh
POLITE_DELAY = 0.4                                      # between network requests
INLINE_BUDGET = 4_600_000                               # base64 bytes of chart data in one page
MAX_CHARTS_PER_ARTICLE = 3


# ------------------------------------------------------------------- themes

# Weighted vocabulary per theme. Two-point terms name the theme outright; the
# one-point terms are the words that cluster around it. An article joins a
# theme at THEME_FLOOR and is dropped entirely if it joins none, which is what
# keeps small-business and payments content out of a markets brief.
THEMES: dict[str, dict] = {
    "us-stocks": {
        "label": "US Stock Market",
        "dot": "#2f6f9f",
        "terms": {
            "equity": 2, "equities": 2, "stock market": 2, "stocks": 2,
            "s&p 500": 2, "nasdaq": 2, "share price": 2, "earnings": 1,
            "valuation": 1, "ipo": 1, "buyback": 1,
            "market concentration": 2, "russell": 1,
        },
    },
    "us-macro": {
        "label": "US Macroeconomics",
        "dot": "#0f6e63",
        "terms": {
            "federal reserve": 2, "the fed": 2, "rate cut": 2, "inflation": 2,
            "cpi": 2, "payrolls": 2, "labor market": 2, "unemployment": 2,
            "gdp": 2, "recession": 2, "consumer spending": 2, "tariff": 2,
            "treasury yield": 2, "wage growth": 2, "interest rates": 2,
            "jobs report": 2, "monetary policy": 2, "fiscal": 1, "deficit": 1,
            "consumer confidence": 2, "retail sales": 2, "disposable income": 2,
            # The Institute measures the US consumer through its own card and
            # deposit data, so this is the vocabulary its macro work is written
            # in — without these terms the Consumer Checkpoint, its flagship
            # monthly read on US demand, would never clear the bar.
            "card spending": 2, "spending growth": 2, "cost of living": 2,
            "after-tax": 2, "income growth": 2, "hiring": 1, "employment": 1,
        },
    },
    "usd": {
        "label": "US Dollar",
        "dot": "#5c5aa8",
        "terms": {
            # "dollar" on its own is usually just money — the Institute writes
            # about dollars of spending — so the currency reading has to be
            # earned by a term that can only mean the exchange rate.
            "dollar": 1, "u.s. dollar": 2, "dollar strength": 2,
            "dollar weakness": 2, "dollar index": 2, "currency": 2,
            "currencies": 2, "foreign exchange": 2, "exchange rate": 2,
            "de-dollarization": 2, "greenback": 2, "fx": 1, "euro": 1,
            "yen": 1, "stablecoin": 1,
        },
    },
    "oil": {
        "label": "Oil & Energy",
        "dot": "#b3541e",
        "terms": {
            "oil": 2, "crude": 2, "brent": 2, "wti": 2, "opec": 2,
            "gasoline": 2, "petroleum": 2, "barrel": 2, "refinery": 1,
            "natural gas": 2, "lng": 2, "energy prices": 2,
        },
    },
    "metals": {
        "label": "Metals",
        "dot": "#8a6a1f",
        "terms": {
            "gold": 2, "silver": 2, "copper": 2, "metals": 2, "mining": 2,
            "precious metals": 2, "critical minerals": 2, "aluminum": 2,
            "platinum": 2, "lithium": 1, "bullion": 2, "commodities": 1,
        },
    },
    "global": {
        "label": "Global Markets",
        "dot": "#7a3b5e",
        "terms": {
            "global markets": 2, "emerging markets": 2, "china": 2,
            "eurozone": 2, "geopolit": 2, "global economy": 2, "trade war": 2,
            "global growth": 2, "world economy": 2, "cross-border": 1,
            "export": 1, "import": 1,
        },
    },
}

# A note joins a theme at THEME_FLOOR, but only enters the brief at
# ARTICLE_FLOOR. The gap is deliberate: the Institute publishes a lot of
# consumer-lifestyle research that brushes against macro vocabulary — a piece
# on wedding budgets does mention spending — and the higher bar is what keeps
# the brief to notes that are actually about the six subjects.
THEME_FLOOR = 5
ARTICLE_FLOOR = 10
THEME_ORDER = list(THEMES)


# --------------------------------------------------------------- data model

@dataclass
class Chart:
    """One figure lifted out of a source document."""
    caption: str
    mime: str
    data: bytes = field(repr=False, default=b"")

    def data_uri(self) -> str:
        return f"data:{self.mime};base64," + base64.b64encode(self.data).decode()


@dataclass
class Article:
    url: str
    source: str                                         # "J.P. Morgan" | "BofA Institute"
    section: str                                        # the desk's own shelf name
    title: str
    dek: str
    published: date
    points: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    score: int = 0
    charts: list[Chart] = field(default_factory=list)
    pdf_url: str = ""
    is_new: bool = False                                # absent from the previous edition

    @property
    def primary(self) -> str:
        return self.themes[0] if self.themes else "us-macro"


@dataclass
class Edition:
    """One day's brief, and what it is being compared against."""
    day: date
    articles: list[Article] = field(default_factory=list)
    daily: list[dict] = field(default_factory=list)
    built: str = ""
    previous: str | None = None                         # the edition before this one

    @property
    def fresh(self) -> int:
        return sum(1 for a in self.articles if a.is_new)


# ------------------------------------------------------------- network layer

class Fetcher:
    """A polite, cached HTTP client.

    Every page these sites serve is static for hours, so repeat runs during a
    day of tuning should not repeat the traffic. Responses land in .cache under
    a hash of the URL and are reused until CACHE_TTL passes.
    """

    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Accept-Language": "en-US,en;q=0.9",
        })
        CACHE.mkdir(exist_ok=True)
        self._last = 0.0

    def get(self, url: str) -> bytes | None:
        path = CACHE / (hashlib.sha1(url.encode()).hexdigest() + Path(urlparse(url).path).suffix[:5])
        if self.use_cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
            return path.read_bytes()

        gap = time.time() - self._last
        if gap < POLITE_DELAY:
            time.sleep(POLITE_DELAY - gap)

        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=30)
                self._last = time.time()
                if r.status_code == 200:
                    path.write_bytes(r.content)
                    return r.content
                if r.status_code in (403, 404, 410):
                    return None
            except requests.RequestException:
                pass
            time.sleep(1.5 * (attempt + 1))
        return None

    def soup(self, url: str) -> BeautifulSoup | None:
        raw = self.get(url)
        return BeautifulSoup(raw.decode("utf-8", "replace"), "html.parser") if raw else None


def sitemap_entries(fetch: Fetcher, url: str) -> list[tuple[str, date]]:
    """(loc, lastmod) pairs out of a sitemap, newest first."""
    raw = fetch.get(url)
    if not raw:
        return []
    text = raw.decode("utf-8", "replace")
    out = []
    for loc, mod in re.findall(r"<loc>(.*?)</loc>\s*<lastmod>(.*?)</lastmod>", text, re.S):
        try:
            out.append((loc.strip(), date.fromisoformat(mod.strip()[:10])))
        except ValueError:
            continue
    return sorted(out, key=lambda p: p[1], reverse=True)


# ------------------------------------------------------------ text handling

def meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = (soup.find("meta", property=name) or soup.find("meta", attrs={"name": name}))
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_suffix(title: str) -> str:
    """Drop the "| J.P. Morgan Global Research" tail the CMS appends.

    The separator is not always a pipe — a few pages ship with a stray capital
    I where one was meant — so both spellings are cut.
    """
    return re.sub(r"\s*[|I]\s*(J\.?P\.?\s*Morgan|Bank of America)\b.*$", "", title, flags=re.I).strip()


BOILERPLATE = re.compile(
    r"(cookie|privacy|subscribe|newsletter|all rights reserved|these materials|"
    r"for general information purposes|read our full analysis|opens in a new tab|"
    r"get the latest|deposit products|member fdic|equal housing|"
    r"bookmark this|read the latest|check back|updated regularly|"
    # Several of these pages are webcast transcripts, and their opening
    # paragraphs are the host saying hello. Real analysis starts later down.
    r"good (morning|afternoon|evening)|thank you (very much )?for joining|"
    r"welcome (back )?to|my name is|joining me today|let's get started|"
    r"thanks for having me|before we (begin|start)|this podcast|"
    r"speaking on|as a reminder)", re.I)

# Transcript prose gives itself away in the first word or two. A note written
# to be read does not open a paragraph with "So maybe with that, Steve".
CONVERSATIONAL = re.compile(
    r"^(so|yeah|yes|well|right|okay|ok|sure|great|absolutely|exactly|"
    r"and so|but|now|look|i mean|you know|that's right|thanks)\b[,\s]", re.I)


# Deliberately narrow. Broad words like "card" or "rail" also name the
# containers the Institute wraps its actual copy in, and stripping those
# leaves a card with nothing to say.
FURNITURE = re.compile(
    r"(primary-navigation|mega-?nav|site-?nav|global-?nav|nav-content|menu|"
    r"promo|teaser|related|subscribe|disclaimer|advert|cookie|breadcrumb|"
    r"social-share|skip-link)", re.I)


def body_text(soup: BeautifulSoup) -> str:
    main = soup.find("main") or soup.body or soup
    return tidy(" ".join(p.get_text(" ", strip=True) for p in main.find_all(["p", "li", "h2", "h3"])))


def key_points(soup: BeautifulSoup, limit: int = 4) -> list[str]:
    """The article's own summary, preferring a "key takeaways" list.

    Both desks lead with a short standfirst — J.P. Morgan as a bulleted "Key
    takeaways" block, the Institute as the opening paragraphs under the
    headline. Whichever is present, the point is to carry the desk's own words
    rather than a summary this script invented.
    """
    main = soup.find("main") or soup.body or soup

    # Article pages carry promo rails, related-story cards and disclaimers in
    # the same container as the copy. Take them out first or a card ends up
    # quoting the bank's advertising back at the reader.
    main = BeautifulSoup(str(main), "html.parser")
    for junk in main.find_all(["aside", "nav", "footer", "form"]):
        junk.decompose()
    for junk in main.find_all(attrs={"class": FURNITURE}):
        junk.decompose()

    for head in main.find_all(["h2", "h3", "h4"]):
        if "key takeaway" in head.get_text(" ", strip=True).lower():
            for sib in head.find_all_next(["ul", "ol", "p"], limit=6):
                items = [tidy(li.get_text(" ", strip=True)) for li in sib.find_all("li")]
                items = [i for i in items if 30 < len(i) < 400]
                if items:
                    return items[:limit]
            break

    paras = [tidy(p.get_text(" ", strip=True)) for p in main.find_all("p")]
    paras = [p for p in paras if 60 < len(p) < 400]

    # Some of these pages are webcast transcripts end to end. Picking the least
    # chatty paragraphs out of a conversation still reads as a conversation, so
    # when a page is mostly dialogue nothing is quoted from it and the card
    # falls back to the desk's own summary line.
    if paras and sum(bool(CONVERSATIONAL.match(p)) for p in paras) / len(paras) > 0.2:
        return []

    out, seen = [], set()
    for t in paras:
        key = t[:60].lower()
        if not BOILERPLATE.search(t) and not CONVERSATIONAL.match(t) and key not in seen:
            seen.add(key)
            out.append(t)
        if len(out) >= limit:
            break
    return out


def classify(article: Article, haystacks: dict[str, str]) -> None:
    """Score an article against every theme and keep the ones it clears.

    Where a term appears matters more than how often: a word in the headline or
    the URL slug is the desk telling you what the piece is about, whereas the
    same word in paragraph nine may be an aside. Body hits are therefore capped
    so a single passing mention of "China" cannot drag a US wage note into
    Global Markets.
    """
    weights = {"title": 3, "url": 3, "dek": 2, "keywords": 2, "body": 1}
    scores: dict[str, int] = {}

    for theme, spec in THEMES.items():
        total = 0
        for term, weight in spec["terms"].items():
            for field_name, text in haystacks.items():
                if term in text:
                    hit = weight * weights[field_name]
                    total += min(hit, 3) if field_name == "body" else hit
        if total >= THEME_FLOOR:
            scores[theme] = total

    top = max(scores.values(), default=0)
    # A second theme has to be a real part of the piece, not a paragraph of it.
    # Judged against the strongest theme rather than an absolute number, so a
    # genuinely wide-ranging outlook still files under everything it covers
    # while a Fed note that mentions copper once does not.
    kept = {t: s for t, s in scores.items() if s >= max(THEME_FLOOR, 0.4 * top)}

    article.themes = sorted(kept, key=lambda t: (-kept[t], THEME_ORDER.index(t)))
    article.score = top
    if top < ARTICLE_FLOOR:
        article.themes = []


# ----------------------------------------------------- J.P. Morgan articles

# Filenames that are furniture rather than findings.
JPM_SKIP = re.compile(
    r"(logo|headshot|banner|header|hero|masthead|icon|thumb|tile|avatar|"
    r"portrait|_bio|profile|footer|badge)", re.I)
# "graph" but not "graphic": the outlook pages decorate their section heads
# with icon strips named Core_Themes_Graphic.svg, which are not figures.
JPM_CHART = re.compile(r"(graph(?!ic)|chart|exhibit|figure|fig[_-]|table|plot)", re.I)


def jpm_charts(soup: BeautifulSoup, fetch: Fetcher) -> list[Chart]:
    """Exhibits out of a J.P. Morgan article.

    The page mixes three kinds of image: the article's own charts, staff
    portraits, and the cards for unrelated articles at the foot. A file is
    taken as a chart when its name says so (Graph, Table, Exhibit) or when it
    carries the long alt text the accessibility team writes for figures —
    which is itself the best caption available, so it is kept.
    """
    charts: list[Chart] = []
    seen: set[str] = set()

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or "/content/dam/" not in src or JPM_SKIP.search(src):
            continue
        alt = tidy(img.get("alt") or "")
        if not (JPM_CHART.search(src) or len(alt) >= 25):
            continue

        url = urljoin(JPM_BASE, src)
        name = Path(urlparse(url).path).name
        if name in seen:
            continue
        seen.add(name)

        raw = fetch.get(url)
        if not raw or len(raw) < 1200:
            continue
        ext = Path(name).suffix.lower()
        mime = {".svg": "image/svg+xml", ".png": "image/png",
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext)
        if not mime:
            continue

        caption = alt or re.sub(r"[_-]+", " ", Path(name).stem).strip()
        charts.append(Chart(caption=caption[:300], mime=mime, data=raw))
        if len(charts) >= MAX_CHARTS_PER_ARTICLE:
            break
    return charts


def parse_jpm(url: str, lastmod: date, fetch: Fetcher) -> Article | None:
    soup = fetch.soup(url)
    if not soup:
        return None

    title = strip_suffix(meta(soup, "og:title", "title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else ""))
    if not title:
        return None

    # The CMS stamps its own publication time; prefer it over the sitemap's
    # lastmod, which also moves when a template is touched.
    published = lastmod
    stamp = meta(soup, "alg-search-date")
    if stamp.isdigit():
        try:
            published = datetime.fromtimestamp(int(stamp), timezone.utc).date()
        except (ValueError, OSError):
            pass

    shelf = url.split("/insights/")[-1].split("/")
    section = "Global Research" if shelf[0] == "global-research" else "Markets & Economy"
    if len(shelf) > 2:
        section += " · " + shelf[1].replace("-", " ").title()

    art = Article(url=url, source="J.P. Morgan", section=section, title=title,
                  dek=meta(soup, "og:description", "description"), published=published,
                  points=key_points(soup))
    classify(art, {
        "title": title.lower(),
        "url": url.lower(),
        "dek": art.dek.lower(),
        "keywords": meta(soup, "keywords").lower(),
        "body": body_text(soup).lower()[:20000],
    })
    if not art.themes:
        return None
    art.charts = jpm_charts(soup, fetch)
    return art


# ------------------------------------------------- Bank of America Institute

EXHIBIT = re.compile(r"^\s*Exhibit\s+\d+\s*[:.]")
ATTRIBUTION = re.compile(r"^(BANK OF AMERICA INSTITUTE|Source\s*:)", re.I)


def pdf_exhibits(raw: bytes, limit: int = MAX_CHARTS_PER_ARTICLE) -> list[Chart]:
    """Crop the exhibits out of an Institute PDF.

    Every figure in these reports is bracketed the same way: an "Exhibit N:"
    caption on top and a source or "BANK OF AMERICA INSTITUTE" line at the
    bottom. Those two lines are what the crop is anchored on, which is far
    steadier than trying to find the drawing itself — the vector clusters that
    make up a chart sometimes merge with the rest of the page and swallow it.

    Width comes from the layout: when two captions sit on the same line the
    page is in two columns and each figure gets half, otherwise it runs the
    full text measure.
    """
    if pymupdf is None:
        return []
    charts: list[Chart] = []
    try:
        doc = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:
        return []

    with doc:
        for page in doc:
            rect = page.rect
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    spans = line["spans"]
                    text = "".join(s["text"] for s in spans).strip()
                    if text:
                        # The face is what separates a caption from the chart's
                        # subtitle beneath it: the Institute sets captions in a
                        # bold cut and the subtitle in a light one. Comparing
                        # the font name works whatever those two cuts are, which
                        # the bold flag does not — several of these templates
                        # mark neither line as bold.
                        lines.append((pymupdf.Rect(line["bbox"]), text, spans[0]["font"]))

            captions = [(r, t) for r, t, _ in lines if EXHIBIT.match(t)]
            if not captions:
                continue
            captions.sort(key=lambda c: (round(c[0].y0 / 12), c[0].x0))

            for box, text in captions:
                row = [c for c in captions if abs(c[0].y0 - box.y0) < 14]
                two_up = len(row) > 1
                if two_up and box.x0 >= rect.width / 2:
                    x0, x1 = rect.width / 2 + 4, rect.width - 38
                elif two_up:
                    x0, x1 = box.x0 - 6, rect.width / 2 - 4
                else:
                    x0, x1 = box.x0 - 6, rect.width - 38

                below = [c[0].y0 for c in captions if c[0].y0 > box.y0 + 14]
                limit_y = min(below) - 8 if below else rect.height - 30
                feet = [r for r, t, _f in lines
                        if r.y0 > box.y1 and r.y1 <= limit_y + 40
                        and r.x0 >= x0 - 12 and r.x1 <= x1 + 14 and ATTRIBUTION.match(t)]
                y1 = max(r.y1 for r in feet) + 6 if feet else limit_y
                if y1 - box.y0 < 90:                    # too thin to be a figure
                    continue

                clip = pymupdf.Rect(x0, box.y0 - 6, x1, y1)
                if clip.width < 80 or clip.height < 80:  # nothing renderable
                    continue
                try:
                    pix = page.get_pixmap(clip=clip, dpi=150)
                    png = pix.tobytes("png")
                except Exception:
                    # A caption near a page edge can still yield a clip MuPDF
                    # refuses to rasterise; one missing figure is not worth
                    # losing the rest of the report over.
                    continue
                # A caption often wraps onto a second or third line; without
                # them the figure is labelled with half a sentence. Walk down
                # the column collecting lines set in the caption's own face,
                # stopping at the first line that changes face — the subtitle.
                face = next((f for r, t, f in lines if r == box and t == text), "")
                below = sorted((l for l in lines if l[0].y0 > box.y0 + 1
                                and l[0].x0 >= x0 - 12 and l[0].x1 <= x1 + 14),
                               key=lambda l: l[0].y0)
                full, cursor = [text], box
                for rect, line_text, line_face in below:
                    if rect.y0 > cursor.y1 + 6:         # a gap means a new block
                        break
                    if line_face != face or EXHIBIT.match(line_text):
                        break
                    full.append(line_text)
                    cursor = rect

                charts.append(Chart(caption=tidy(" ".join(full))[:300], mime="image/png",
                                    data=png))
                if len(charts) >= limit:
                    return charts
    return charts


def pdf_published(raw: bytes) -> date | None:
    """The date printed on the front page of an Institute report.

    The web page never states when a note was published, so the sitemap's
    lastmod has to stand in — except that the PDF puts the real date in its
    masthead ("23 July 2026"), which is worth preferring when it is there.
    """
    if pymupdf is None:
        return None
    try:
        with pymupdf.open(stream=raw, filetype="pdf") as doc:
            head = doc[0].get_text()[:1500]
    except Exception:
        return None
    hit = re.search(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
                    r"September|October|November|December)\s+(20\d\d)\b", head, re.I)
    if not hit:
        return None
    try:
        return datetime.strptime(f"{hit.group(1)} {hit.group(2)} {hit.group(3)}",
                                 "%d %B %Y").date()
    except ValueError:
        return None


def bofa_listing(fetch: Fetcher) -> dict[str, dict]:
    """Category and month for each article, read off the Institute's own hubs.

    The article pages themselves never print a date; the cards that link to
    them do ("Economy … July 2026"), so the hubs are where that comes from.
    """
    found: dict[str, dict] = {}
    month = re.compile(
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\s+(20\d\d)", re.I)

    for hub in BOFA_HUBS:
        soup = fetch.soup(f"{BOFA_BASE}/{hub}.html" if hub else BOFA_BASE)
        if not soup:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not (href.startswith("/") and href.endswith(".html") and href.count("/") >= 2):
                continue
            label = tidy(a.get_text(" ", strip=True))
            hit = month.search(label)
            if not hit:
                continue
            found[urljoin(BOFA_BASE, href)] = {
                "month": hit.group(0).title(),
                "category": label.split()[0],
            }
    return found


def daily_insights(fetch: Fetcher, days: int) -> list[dict]:
    """The Daily Insights newsletter items, which exist only as hub cards.

    There are no article pages behind these — each headline links straight to
    a tracked PDF — so they are carried as a dated one-line list rather than
    treated as articles.
    """
    soup = fetch.soup(f"{BOFA_BASE}/daily-insights.html")
    if not soup:
        return []
    cutoff = date.today() - timedelta(days=days)
    out = []
    for anchor in soup.select("a.tile-anchor"):
        head = anchor.find(class_=re.compile("tile__headline"))
        eyebrow = anchor.find(class_=re.compile("tile__lead-in"))
        if not (head and eyebrow):
            continue
        try:
            when = datetime.strptime(tidy(eyebrow.get_text()), "%m-%d-%Y").date()
        except ValueError:
            continue
        if when < cutoff:
            continue
        out.append({"title": tidy(head.get_text()), "date": when.isoformat(),
                    "url": anchor["href"]})
    return sorted(out, key=lambda d: d["date"], reverse=True)


def parse_bofa(url: str, lastmod: date, listing: dict, fetch: Fetcher) -> Article | None:
    soup = fetch.soup(url)
    if not soup:
        return None

    title = strip_suffix(meta(soup, "og:title", "title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else ""))
    if not title:
        return None

    slug = urlparse(url).path.lstrip("/").split("/")[0]
    card = listing.get(url, {})
    section = BOFA_SECTIONS.get(slug, "Institute Insights")
    if card.get("month"):
        section += " · " + card["month"]

    art = Article(url=url, source="BofA Institute", section=section, title=title,
                  dek=meta(soup, "og:description", "description"), published=lastmod,
                  points=key_points(soup))
    classify(art, {
        "title": title.lower(),
        "url": url.lower(),
        "dek": art.dek.lower(),
        "keywords": meta(soup, "keywords").lower(),
        "body": body_text(soup).lower()[:20000],
    })
    if not art.themes:
        return None

    link = soup.find("a", href=re.compile(r"\.pdf($|\?)", re.I))
    if link:
        art.pdf_url = urljoin(BOFA_BASE, link["href"])
        raw = fetch.get(art.pdf_url)
        if raw:
            art.charts = pdf_exhibits(raw)
            art.published = pdf_published(raw) or art.published
    return art


# ---------------------------------------------------------------- selection

def gather(fetch: Fetcher, days: int, per_theme: int, verbose: bool = True) -> tuple[list[Article], list[dict]]:
    """Everything recent from both desks that lands on at least one theme."""
    cutoff = date.today() - timedelta(days=days)
    articles: list[Article] = []

    jpm = [(u, d) for u, d in sitemap_entries(fetch, JPM_SITEMAP)
           if d >= cutoff and any(s in u for s in JPM_SHELVES)]
    if verbose:
        print(f"J.P. Morgan: {len(jpm)} candidates since {cutoff}", file=sys.stderr)
    for url, mod in jpm:
        art = parse_jpm(url, mod, fetch)
        # Discovery goes by the sitemap's lastmod, which also moves when an old
        # page is merely retouched. The article's own date is the one that
        # decides whether it belongs in a brief about this week.
        if art and art.published >= cutoff:
            articles.append(art)
            if verbose:
                print(f"  + {art.published} [{art.score:2d}] {len(art.charts)} charts  {art.title[:64]}",
                      file=sys.stderr)

    listing = bofa_listing(fetch)
    bofa = [(u, d) for u, d in sitemap_entries(fetch, BOFA_SITEMAP)
            if d >= cutoff and urlparse(u).path.count("/") >= 2 and u.endswith(".html")]
    if verbose:
        print(f"BofA Institute: {len(bofa)} candidates since {cutoff}", file=sys.stderr)
    for url, mod in bofa:
        art = parse_bofa(url, mod, listing, fetch)
        if art and art.published >= cutoff:
            articles.append(art)
            if verbose:
                print(f"  + {art.published} [{art.score:2d}] {len(art.charts)} charts  {art.title[:64]}",
                      file=sys.stderr)

    # Each theme gets its freshest few. Taking the top N overall would let a
    # busy week of macro copy crowd out the only oil note in the window, so
    # selection runs per theme — and within a theme, a note actually filed
    # under it outranks a wide-ranging outlook that merely touches it, however
    # recent that outlook is. Otherwise the dollar section fills with pieces
    # about everything and the one real currency note never appears.
    chosen: dict[str, Article] = {}
    for theme in THEME_ORDER:
        ranked = sorted((a for a in articles if theme in a.themes),
                        key=lambda a: (a.themes[0] == theme, a.published, a.score, len(a.charts)),
                        reverse=True)
        picks = ranked[:per_theme]
        # The two desks answer the same question differently — J.P. Morgan
        # from the forecast side, the Institute from its own card and payroll
        # data — so a theme that has both should show both, even when one
        # desk happens to have published more recently.
        for desk in ("J.P. Morgan", "BofA Institute"):
            if not any(a.source == desk for a in picks):
                other = next((a for a in ranked if a.source == desk), None)
                if other:
                    picks.append(other)
        for art in picks:
            chosen.setdefault(art.url, art)

    picked = sorted(chosen.values(), key=lambda a: (a.published, a.score), reverse=True)
    trim_to_budget(picked)
    return picked, daily_insights(fetch, days)


def trim_to_budget(articles: list[Article]) -> None:
    """Keep the page mailable by dropping surplus charts, widest first.

    Every article keeps its first chart; beyond that, extras are shed from the
    chart-heaviest articles until the inlined total fits. The budget is counted
    in base64, which is what actually lands in the file — a third larger than
    the bytes on disk.
    """
    def total() -> int:
        return sum(-(-len(c.data) // 3) * 4 for a in articles for c in a.charts)

    while total() > INLINE_BUDGET:
        fattest = max(articles, key=lambda a: (len(a.charts), sum(len(c.data) for c in a.charts)))
        if len(fattest.charts) <= 1:
            break
        fattest.charts.pop()


# ------------------------------------------------------------------- render

CSS = """
:root{
  --paper:#f2f3f5; --card:#ffffff; --ink:#14171c; --ink-2:#4a515c; --ink-3:#767f8c;
  --rule:#dfe2e7; --rule-2:#eceef1; --accent:#0f6e63; --accent-soft:#e2efec;
  --jpm:#6b4f2a; --bofa:#012169; --shadow:0 1px 2px rgba(20,23,28,.06),0 8px 24px rgba(20,23,28,.05);
  --serif:"Iowan Old Style","Charter","Palatino Linotype",Palatino,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#101317; --card:#171b21; --ink:#e8eaed; --ink-2:#aab2bd; --ink-3:#7e8794;
    --rule:#272d35; --rule-2:#1f242b; --accent:#4bb3a4; --accent-soft:#16302d;
    --jpm:#c2a578; --bofa:#8ea9df; --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --paper:#101317; --card:#171b21; --ink:#e8eaed; --ink-2:#aab2bd; --ink-3:#7e8794;
  --rule:#272d35; --rule-2:#1f242b; --accent:#4bb3a4; --accent-soft:#16302d;
  --jpm:#c2a578; --bofa:#8ea9df; --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}
:root[data-theme="light"]{
  --paper:#f2f3f5; --card:#ffffff; --ink:#14171c; --ink-2:#4a515c; --ink-3:#767f8c;
  --rule:#dfe2e7; --rule-2:#eceef1; --accent:#0f6e63; --accent-soft:#e2efec;
  --jpm:#6b4f2a; --bofa:#012169; --shadow:0 1px 2px rgba(20,23,28,.06),0 8px 24px rgba(20,23,28,.05);
}

*{box-sizing:border-box}
/* The tiles jump to their section as plain fragment links — no smooth
   scrolling. Over a page this tall an animated scroll of several thousand
   pixels is slow and disorienting, and it is silently dropped altogether when
   the window is throttled, which leaves the click doing nothing at all. */
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
     font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px 96px}

/* masthead */
.masthead{border-bottom:1px solid var(--rule);padding:44px 0 26px;margin-bottom:34px}
.kicker{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
        color:var(--accent);margin:0 0 14px}
.masthead h1{font-family:var(--serif);font-weight:600;font-size:clamp(30px,4.4vw,50px);
             line-height:1.06;letter-spacing:-.015em;margin:0;text-wrap:balance;max-width:20ch}
.standfirst{color:var(--ink-2);max-width:64ch;margin:16px 0 0;font-size:17px}
.meta-row{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:22px;
          font-family:var(--mono);font-size:11.5px;letter-spacing:.05em;color:var(--ink-3)}
.meta-row strong{color:var(--ink-2);font-weight:600}

/* counts — and the jump links to each section */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
       background:var(--rule);border:1px solid var(--rule);border-radius:3px;overflow:hidden;margin-bottom:34px}
.tile{background:var(--card);padding:14px 16px;display:block;text-decoration:none;color:inherit;
      position:relative;transition:background .15s,color .15s}
a.tile::after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;
              background:var(--accent);transform:scaleX(0);transform-origin:left;
              transition:transform .18s}
a.tile:hover{background:var(--accent-soft)}
a.tile:hover::after,a.tile:focus-visible::after{transform:scaleX(1)}
a.tile:hover .l{color:var(--ink-2)}
.tile.is-empty{opacity:.55}
.tile .n{font-family:var(--serif);font-size:27px;line-height:1;font-variant-numeric:tabular-nums}
.tile .l{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
         color:var(--ink-3);margin-top:7px;display:flex;align-items:center;gap:7px;
         transition:color .15s}
.dot{width:8px;height:8px;border-radius:50%;flex:none}

.layout{display:grid;grid-template-columns:206px minmax(0,1fr);gap:44px;align-items:start}
@media (max-width:900px){.layout{grid-template-columns:1fr;gap:26px}}

/* the date rail */
.rail{position:sticky;top:24px}
@media (max-width:900px){.rail{position:static}}
.rail h2{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
         color:var(--ink-3);margin:0 0 12px;font-weight:600}
.rail nav{display:flex;flex-direction:column;gap:2px;margin-bottom:30px}
.rail nav .year{font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;color:var(--accent);
                margin:14px 0 4px;font-weight:600}
.rail nav .year:first-child{margin-top:0}
.rail nav a{font-family:var(--mono);font-size:12.5px;text-decoration:none;color:var(--ink-2);
            padding:7px 10px;border-left:2px solid var(--rule);border-radius:0 3px 3px 0}
.rail nav a:hover{background:var(--rule-2);color:var(--ink)}
.rail nav a[aria-current="page"]{border-left-color:var(--accent);background:var(--accent-soft);
            color:var(--ink);font-weight:600}
/* sections and cards */
.theme{margin-bottom:52px;scroll-margin-top:24px}
.theme-head{display:flex;align-items:baseline;gap:12px;padding-bottom:10px;
            border-bottom:2px solid var(--ink);margin-bottom:22px}
.theme-head h2{font-family:var(--serif);font-size:24px;font-weight:600;margin:0;letter-spacing:-.01em}
.theme-head .count{font-family:var(--mono);font-size:11px;color:var(--ink-3);margin-left:auto}

article.card{background:var(--card);border:1px solid var(--rule);border-radius:4px;
             box-shadow:var(--shadow);padding:26px 28px;margin-bottom:20px}
@media (max-width:600px){article.card{padding:20px 18px}}
.badges{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:12px;
        font-family:var(--mono);font-size:11px;letter-spacing:.05em;color:var(--ink-3)}
.src{font-weight:700;letter-spacing:.08em;text-transform:uppercase}
/* Marks a note that was not in the previous edition. Weekly runs repeat most
   of each subject's standing picture, so this is what the week's news is. */
.new{font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:10px;
     color:var(--paper);background:var(--accent);border-radius:2px;padding:2px 6px}
article.card.is-new{border-left:2px solid var(--accent)}
.src.jpm{color:var(--jpm)} .src.bofa{color:var(--bofa)}
.sep{color:var(--rule)}
.card h3{font-family:var(--serif);font-size:22px;line-height:1.22;font-weight:600;
         margin:0 0 10px;letter-spacing:-.01em;text-wrap:balance}
.card h3 a{text-decoration:none;background-image:linear-gradient(var(--accent),var(--accent));
           background-size:0 1px;background-repeat:no-repeat;background-position:0 100%;
           transition:background-size .2s}
.card h3 a:hover{background-size:100% 1px;color:var(--accent)}
.dek{color:var(--ink-2);margin:0 0 16px;max-width:68ch}
.points{margin:0 0 18px;padding:0;list-style:none;display:flex;flex-direction:column;gap:9px}
.points li{position:relative;padding-left:17px;color:var(--ink-2);font-size:14.7px;max-width:72ch}
.points li::before{content:"";position:absolute;left:0;top:.62em;width:6px;height:6px;
                   border-radius:50%;background:var(--accent);opacity:.65}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:4px}
.tag{font-family:var(--mono);font-size:10px;letter-spacing:.07em;text-transform:uppercase;
     color:var(--ink-3);border:1px solid var(--rule);border-radius:2px;padding:3px 7px;
     display:inline-flex;align-items:center;gap:6px}

/* figures pulled from the source */
.figures{margin:20px 0 0;display:flex;flex-direction:column;gap:20px}
figure{margin:0;border-top:1px solid var(--rule-2);padding-top:18px}
figure .frame{background:#fff;border:1px solid var(--rule);border-radius:3px;padding:12px;
              overflow-x:auto}
figure img{display:block;width:100%;height:auto;max-width:100%}
figcaption{font-size:12.7px;color:var(--ink-3);margin-top:9px;max-width:78ch;line-height:1.5}
figcaption b{color:var(--ink-2);font-weight:600}

/* daily strip */
.daily{border:1px solid var(--rule);border-radius:4px;background:var(--card);
       box-shadow:var(--shadow);padding:24px 28px;margin-bottom:52px}
.daily ol{list-style:none;margin:14px 0 0;padding:0;display:flex;flex-direction:column}
.daily li{display:flex;gap:16px;padding:9px 0;border-top:1px solid var(--rule-2);align-items:baseline}
.daily li:first-child{border-top:0}
.daily time{font-family:var(--mono);font-size:11.5px;color:var(--ink-3);flex:none;width:76px;
            font-variant-numeric:tabular-nums}
.daily a{text-decoration:none;font-size:15px}
.daily a:hover{color:var(--accent);text-decoration:underline}

.empty{color:var(--ink-3);font-size:14px;padding:14px 0}
footer{border-top:1px solid var(--rule);margin-top:56px;padding-top:22px;
       font-size:12.5px;color:var(--ink-3);max-width:76ch}
footer a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
[hidden]{display:none !important}
@media print{.rail{display:none}.layout{grid-template-columns:1fr}}
"""


def esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def split_caption(caption: str) -> tuple[str, str]:
    """"Exhibit 4: Services drove …" → a bolded label and the rest."""
    hit = re.match(r"(Exhibit\s+\d+)\s*[:.]\s*(.*)", caption, re.I)
    return (hit.group(1), hit.group(2)) if hit else ("", caption)


def render_report(edition: Edition, dates: list[str], standalone: bool = True) -> str:
    """The brief itself.

    With standalone off the same page comes back without its outer document
    scaffolding, for hosts that supply their own — and with the date rail
    pointing at anchors, since the neighbouring editions are not there to
    link to.
    """
    day, articles, daily = edition.day, edition.articles, edition.daily
    charts = sum(len(a.charts) for a in articles)
    long_day = day.strftime("%d %B %Y").lstrip("0")

    since = ""
    if edition.previous:
        prior = date.fromisoformat(edition.previous).strftime("%d %b").lstrip("0")
        since = (f'<span><strong>{edition.fresh} new</strong> since {esc(prior)}</span>'
                 if edition.fresh else f'<span>nothing new since {esc(prior)}</span>')

    shown = dates if standalone else [day.isoformat()]
    rail = rail_markup(day.isoformat(), shown, standalone)

    sections, landed = [], set()
    for theme in THEME_ORDER:
        spec = THEMES[theme]
        # Filed under its strongest theme only. A wide outlook that touches all
        # six would otherwise be printed six times, carrying its charts with it
        # — the other themes it covers are listed as tags on the card.
        members = [a for a in articles if a.primary == theme]
        if not members:
            # Nothing filed here, but the subject was asked for: show the notes
            # that cover it rather than dropping the section and leaving the
            # reader to wonder whether anyone wrote about metals this week.
            members = sorted((a for a in articles if theme in a.themes),
                             key=lambda a: (a.published, a.score), reverse=True)[:2]
        if not members:
            continue
        # Arrivals first. Within a subject the standing picture is mostly last
        # week's, so what came in since then goes at the top of it.
        members = sorted(members, key=lambda a: (a.is_new, a.published, a.score), reverse=True)
        cards = []
        for art in members:
            figures = []
            for chart in art.charts:
                label, rest = split_caption(chart.caption)
                cap = (f"<b>{esc(label)}</b> {esc(rest)}" if label else esc(rest))
                figures.append(
                    f'<figure><div class="frame">'
                    f'<img src="{chart.data_uri()}" alt="{esc(chart.caption)}" loading="lazy"></div>'
                    f'<figcaption>{cap}</figcaption></figure>')

            # Built up before the f-string rather than inside it: nesting a
            # quoted f-string within another needs Python 3.12, and this has to
            # run on whatever interpreter it lands on.
            bullets = "".join(f"<li>{esc(p)}</li>" for p in art.points[:4])
            points = f'<ul class="points">{bullets}</ul>' if bullets else ""
            gallery = f'<div class="figures">{"".join(figures)}</div>' if figures else ""
            tags = "".join(
                f'<span class="tag"><span class="dot" style="background:{THEMES[t]["dot"]}"></span>'
                f'{esc(THEMES[t]["label"])}</span>' for t in art.themes)
            cls = "jpm" if art.source == "J.P. Morgan" else "bofa"
            pdf = (f'<span class="sep">·</span><a href="{esc(art.pdf_url)}">full analysis (PDF)</a>'
                   if art.pdf_url else "")
            flag = '<span class="new">New</span>' if art.is_new else ""

            cards.append(
                f'<article class="card{" is-new" if art.is_new else ""}" '
                f'data-themes="{" ".join(art.themes)}">'
                f'<div class="badges">{flag}<span class="src {cls}">{esc(art.source)}</span>'
                f'<span class="sep">·</span><span>{esc(art.section)}</span>'
                f'<span class="sep">·</span><time datetime="{art.published.isoformat()}">'
                f'{esc(art.published.strftime("%d %b %Y").lstrip("0"))}</time>{pdf}</div>'
                f'<h3><a href="{esc(art.url)}">{esc(art.title)}</a></h3>'
                f'<p class="dek">{esc(art.dek)}</p>'
                f'{points}'
                f'<div class="tags">{tags}</div>'
                f'{gallery}'
                f'</article>')

        landed.add(theme)
        sections.append(
            f'<section class="theme" id="{theme}"><div class="theme-head">'
            f'<span class="dot" style="background:{spec["dot"]};width:11px;height:11px"></span>'
            f'<h2>{esc(spec["label"])}</h2>'
            f'<span class="count">{len(members)} {"note" if len(members) == 1 else "notes"}</span>'
            f'</div>{"".join(cards)}</section>')

    # The tiles double as the table of contents: each jumps to its section.
    # A subject nobody wrote about this week has no section to jump to, so it
    # stays a plain tile rather than a link that goes nowhere.
    tiles = []
    for theme in THEME_ORDER:
        n = sum(1 for a in articles if theme in a.themes)
        inner = (f'<div class="n">{n}</div><div class="l">'
                 f'<span class="dot" style="background:{THEMES[theme]["dot"]}"></span>'
                 f'{esc(THEMES[theme]["label"])}</div>')
        tiles.append(f'<a class="tile" href="#{theme}">{inner}</a>' if theme in landed
                     else f'<div class="tile is-empty">{inner}</div>')

    daily_html = ""
    if daily:
        items = "".join(
            f'<li><time datetime="{d["date"]}">'
            f'{esc(date.fromisoformat(d["date"]).strftime("%d %b").lstrip("0"))}</time>'
            f'<a href="{esc(d["url"])}">{esc(d["title"])}</a></li>' for d in daily[:12])
        daily_html = (
            f'<section class="daily"><div class="badges">'
            f'<span class="src bofa">BofA Institute</span><span class="sep">·</span>'
            f'<span>Daily Insights</span></div>'
            f'<p class="dek" style="margin:0">One-line reads from the Institute\'s daily '
            f'newsletter. Each links to the note it came from.</p>'
            f'<ol>{items}</ol></section>')

    head = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Insight · {esc(long_day)}</title>
<meta name="description" content="US markets, macro, dollar, oil, metals and global markets — the day's read from J.P. Morgan Global Research and the Bank of America Institute.">
<style>{CSS}</style>
</head>
<body>""" if standalone else f"""<title>Market Insight · {esc(long_day)}</title>
<style>{CSS}</style>"""

    return f"""{head}
<div class="wrap">
<header class="masthead">
  <p class="kicker">Market Insight · Daily Brief</p>
  <h1>What the research desks are saying today</h1>
  <p class="standfirst">The public research from J.P. Morgan Global Research and the Bank of
    America Institute, filtered to the US stock market, US macroeconomics, the dollar, oil,
    metals and global markets — with every chart lifted from the source document.</p>
  <div class="meta-row">
    <span><strong>{esc(long_day)}</strong></span>
    <span>{len(articles)} notes</span>
    {since}
    <span>{charts} charts from source</span>
    <span>{len(daily)} daily items</span>
    <span>Built {esc(edition.built or datetime.now().strftime("%H:%M"))}</span>
  </div>
</header>

<div class="tiles">{"".join(tiles)}</div>

<div class="layout">
  <aside class="rail">
    <h2>Log</h2>
    <nav>{rail}</nav>
  </aside>
  <main id="brief">
    {daily_html}
    {"".join(sections) or '<p class="empty">Nothing cleared the topic filter in this window.</p>'}
    <footer>
      <p>Assembled automatically from the public pages of
      <a href="https://www.jpmorgan.com/global">jpmorgan.com</a> and
      <a href="https://institute.bankofamerica.com/">institute.bankofamerica.com</a>.
      Headlines, summaries and charts belong to their publishers and are reproduced here for
      reference; follow any headline to read the note in full. Nothing here is investment advice.</p>
    </footer>
  </main>
</div>
</div>
{"</body>" + chr(10) + "</html>" if standalone else ""}
"""


def render_index(dates: list[str], latest: dict) -> str:
    rows = []
    for year, group in groupby(dates, key=lambda d: d[:4]):
        rows.append(f'<li class="yr"><h2>{esc(year)}</h2></li>')
        for d in group:
            info = latest.get(d, {})
            rows.append(
                f'<li><a href="reports/{d[:4]}/{d}/index.html">'
                f'<time datetime="{d}">{esc(date.fromisoformat(d).strftime("%d %B %Y").lstrip("0"))}</time>'
                f'<span>{info.get("articles", 0)} notes · {info.get("charts", 0)} charts</span></a></li>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Insight · Archive</title>
<style>{CSS}
.arch{{list-style:none;margin:0;padding:0;max-width:640px}}
.arch li{{border-top:1px solid var(--rule)}}
.arch li:last-child{{border-bottom:1px solid var(--rule)}}
.arch a{{display:flex;justify-content:space-between;gap:20px;align-items:baseline;
        padding:15px 4px;text-decoration:none}}
.arch a:hover{{background:var(--rule-2)}}
.arch time{{font-family:var(--serif);font-size:19px}}
.arch span{{font-family:var(--mono);font-size:11.5px;color:var(--ink-3)}}
.arch li.yr{{border:0;padding:26px 0 4px}}
.arch li.yr:first-child{{padding-top:0}}
.arch li.yr h2{{font-family:var(--mono);font-size:11px;letter-spacing:.16em;color:var(--accent);
                margin:0;font-weight:600}}
</style>
</head>
<body>
<div class="wrap">
<header class="masthead">
  <p class="kicker">Market Insight</p>
  <h1>Daily briefs</h1>
  <p class="standfirst">One edition per day, built from J.P. Morgan Global Research and the
    Bank of America Institute. The newest is at the top.</p>
</header>
<ul class="arch">{"".join(rows)}</ul>
</div>
</body>
</html>
"""


# --------------------------------------------------------------------- main

def edition_dir(day: str) -> Path:
    """Where one edition lives: reports/<year>/<date>/."""
    return REPORTS / day[:4] / day


def edition_dates() -> list[str]:
    """Every edition on disk, newest first."""
    out = []
    for year in REPORTS.iterdir():
        if year.is_dir() and re.fullmatch(r"\d{4}", year.name):
            out += [p.name for p in year.iterdir()
                    if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)]
    return sorted(out, reverse=True)


def migrate_flat_editions() -> int:
    """Move editions written before the year folders existed.

    The first version put every edition straight under reports/. Filing them
    by year keeps the folder navigable once there are a few hundred, and the
    move is done here rather than by hand so an old checkout upgrades itself.
    """
    moved = 0
    for path in sorted(REPORTS.iterdir()):
        if not (path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)):
            continue
        target = edition_dir(path.name)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        moved += 1
    return moved


def mark_new(articles: list[Article], day: date) -> str | None:
    """Flag the notes that were not in the edition before this one.

    Run weekly, consecutive editions overlap heavily: the recency window is far
    wider than the gap between runs, so most of each subject's standing picture
    repeats from one Monday to the next. Throwing the older notes out would lose
    the context — the picture is the point — so instead the arrivals are marked
    and sorted to the top, which is what makes the week's actual news findable.

    Only report.json is read, not the assets beside it, so this stays cheap.
    """
    earlier = [d for d in edition_dates() if d < day.isoformat()]
    if not earlier:
        return None                                     # the first edition: nothing to compare
    previous = max(earlier)
    data = edition_dir(previous) / "report.json"
    if not data.exists():
        return None
    try:
        seen = {a["url"] for a in json.loads(data.read_text(encoding="utf-8"))["articles"]}
    except (ValueError, KeyError):
        return None
    for art in articles:
        art.is_new = art.url not in seen
    return previous


def rail_href(current: str, target: str) -> str:
    """A link from one edition to another, across year folders when needed."""
    if current[:4] == target[:4]:
        return f"../{target}/index.html"
    return f"../../{target[:4]}/{target}/index.html"


def rail_markup(current: str, dates: list[str], standalone: bool = True) -> str:
    """The Log: every edition, filed under its year, newest first."""
    parts = []
    for year, group in groupby(dates, key=lambda d: d[:4]):
        parts.append(f'<h3 class="year">{esc(year)}</h3>')
        for d in group:
            href = rail_href(current, d) if standalone else "#brief"
            here = ' aria-current="page"' if d == current else ""
            label = date.fromisoformat(d).strftime("%d %b").lstrip("0")
            parts.append(f'<a href="{href}"{here}>{esc(label)}</a>')
    return "".join(parts)


def load_edition(day: str) -> Edition | None:
    """Rebuild an edition from what was stored for it.

    report.json holds the words and assets/ holds the figures, which together
    are everything the page is made of. The two rendered HTML files are
    therefore derived and need not be kept — they can be regenerated from here
    at any time, which is what lets them stay out of version control instead of
    committing several megabytes of inlined base64 a day.
    """
    folder = edition_dir(day)
    data = folder / "report.json"
    if not data.exists():
        return None
    blob = json.loads(data.read_text(encoding="utf-8"))

    articles = []
    for record in blob["articles"]:
        charts = []
        for chart in record.get("charts", []):
            path = folder / "assets" / chart["file"]
            if not path.exists():
                continue
            mime = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
            charts.append(Chart(caption=chart["caption"], mime=mime, data=path.read_bytes()))
        articles.append(Article(
            url=record["url"], source=record["source"], section=record["section"],
            title=record["title"], dek=record["dek"],
            published=date.fromisoformat(record["published"]),
            points=record.get("points", []), themes=record.get("themes", []),
            score=record.get("score", 0), charts=charts, pdf_url=record.get("pdf", ""),
            is_new=record.get("new", False)))

    # When the edition was built, not when its HTML was last written — so a
    # page regenerated months later still reports the run that gathered it,
    # and regenerating produces the same bytes.
    built = ""
    try:
        built = datetime.fromisoformat(blob["built"]).strftime("%H:%M")
    except (KeyError, ValueError):
        pass
    return Edition(day=date.fromisoformat(day), articles=articles,
                   daily=blob.get("daily_insights", []), built=built,
                   previous=blob.get("previous"))


def write_pages(edition: Edition, dates: list[str]) -> Path:
    """The two rendered forms of one edition."""
    folder = edition_dir(edition.day.isoformat())
    folder.mkdir(parents=True, exist_ok=True)
    page = folder / "index.html"
    page.write_text(render_report(edition, dates), encoding="utf-8")
    # The same edition without the outer document, for publishing somewhere
    # that wraps the content in its own.
    (folder / "artifact.html").write_text(
        render_report(edition, dates, standalone=False), encoding="utf-8")
    return page


def write_archive(dates: list[str]) -> None:
    summary = {}
    for d in dates:
        data = edition_dir(d) / "report.json"
        if data.exists():
            blob = json.loads(data.read_text(encoding="utf-8"))
            summary[d] = {"articles": len(blob["articles"]),
                          "charts": sum(len(a["charts"]) for a in blob["articles"])}
    (HERE / "index.html").write_text(render_index(dates, summary), encoding="utf-8")


def write_report(edition: Edition) -> Path:
    day, articles, daily = edition.day, edition.articles, edition.daily
    folder = edition_dir(day.isoformat())
    assets = folder / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    # Charts are inlined into the page, but they are also written out as files
    # so a figure can be reused somewhere else without unpicking base64.
    payload = []
    for i, art in enumerate(articles, 1):
        names = []
        for j, chart in enumerate(art.charts, 1):
            ext = ".svg" if "svg" in chart.mime else ".png"
            name = f"{i:02d}-{j}{ext}"
            (assets / name).write_bytes(chart.data)
            names.append(name)
        payload.append({
            "url": art.url, "source": art.source, "section": art.section,
            "title": art.title, "dek": art.dek, "published": art.published.isoformat(),
            "themes": art.themes, "score": art.score, "points": art.points,
            "pdf": art.pdf_url, "new": art.is_new,
            "charts": [{"file": n, "caption": c.caption}
                       for n, c in zip(names, art.charts)],
        })

    now = datetime.now()
    (folder / "report.json").write_text(json.dumps(
        {"date": day.isoformat(), "built": now.isoformat(timespec="seconds"),
         "previous": edition.previous,
         "articles": payload, "daily_insights": daily}, indent=2), encoding="utf-8")

    edition.built = now.strftime("%H:%M")
    dates = edition_dates()
    page = write_pages(edition, dates)
    write_archive(dates)

    # Earlier editions gain a link to this one. Where the rendered page is
    # still on disk its rail is patched in place; where it has been cleaned
    # away it is simply rebuilt from that day's stored data.
    for d in dates:
        if d == day.isoformat():
            continue
        old = edition_dir(d) / "index.html"
        if old.exists():
            refresh_rail(old, dates, d)
        else:
            stored = load_edition(d)
            if stored:
                write_pages(stored, dates)
    return page


def refresh_rail(page: Path, dates: list[str], current: str) -> None:
    """Rewrite an older edition's date rail so the archive stays navigable."""
    html = page.read_text(encoding="utf-8")
    rail = rail_markup(current, dates)
    updated = re.sub(r"(<nav>).*?(</nav>)", lambda m: m.group(1) + rail + m.group(2),
                     html, count=1, flags=re.S)
    if updated != html:
        page.write_text(updated, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=45,
                    help="how far back a note may have been published (default 45)")
    ap.add_argument("--per-theme", type=int, default=4,
                    help="most recent notes to keep per theme (default 4)")
    ap.add_argument("--no-cache", action="store_true", help="ignore cached pages")
    ap.add_argument("--render-only", action="store_true",
                    help="rebuild pages from reports/*/report.json, download nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    REPORTS.mkdir(exist_ok=True)
    moved = migrate_flat_editions()
    if moved and not args.quiet:
        print(f"filed {moved} earlier edition(s) under their year", file=sys.stderr)
    today = date.today()

    if args.render_only:
        # Every page, rebuilt from the stored words and figures. This is how an
        # edition comes back after the rendered HTML has been cleaned away, and
        # how the whole archive is re-rendered after a change to the layout.
        dates = edition_dates()
        rebuilt = 0
        for d in dates:
            stored = load_edition(d)
            if not stored:
                print(f"  {d}: no report.json, skipped", file=sys.stderr)
                continue
            write_pages(stored, dates)
            rebuilt += 1
        write_archive(dates)
        print(f"{rebuilt} of {len(dates)} editions rebuilt, plus the archive index")
        return 0

    if pymupdf is None:
        print("note: pymupdf is not installed — BofA charts will be skipped", file=sys.stderr)

    fetch = Fetcher(use_cache=not args.no_cache)
    articles, daily = gather(fetch, args.days, args.per_theme, verbose=not args.quiet)
    if not articles:
        print("nothing matched — try a longer --days window", file=sys.stderr)
        return 1

    # What arrived since the last edition, before anything is written.
    previous = mark_new(articles, today)
    edition = Edition(day=today, articles=articles, daily=daily, previous=previous)

    page = write_report(edition)
    charts = sum(len(a.charts) for a in articles)
    size = page.stat().st_size / 1_000_000
    fresh = (f" · {edition.fresh} new since {previous}" if previous else "")
    print(f"\n{len(articles)} notes{fresh} · {charts} charts · {len(daily)} daily items")
    print(f"{page}  ({size:.1f} MB)")
    print(f"{HERE / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
