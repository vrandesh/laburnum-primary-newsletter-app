import argparse
import json
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import urllib3


ARCHIVE_URLS = [
    "https://www.laburnumps.vic.edu.au/enews/this_year",
    "https://www.laburnumps.vic.edu.au/enews/past_years",
]
DEFAULT_OUTPUT = "laburnum_enews_archive.json"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_stack.append(tag)
            return
        if self.skip_stack:
            return
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()
            return
        if self.skip_stack:
            return
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_stack and data:
            self.parts.append(data)

    def text(self) -> str:
        raw = unescape("".join(self.parts))
        raw = re.sub(r"\r", "", raw)
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def fetch_html(url: str, verify_ssl: bool) -> str:
    response = requests.get(url, timeout=30, verify=verify_ssl)
    response.raise_for_status()
    return response.text


def strip_html(html_fragment: str) -> str:
    extractor = TextExtractor()
    extractor.feed(html_fragment)
    return extractor.text()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def infer_year(value: str) -> int | None:
    match = re.search(r"(20\d{2})", value)
    if not match:
        return None
    return int(match.group(1))


def parse_issue_datetime(value: str) -> tuple[str, int]:
    cleaned = normalize_whitespace(value)
    cleaned = re.sub(r"^Special Edition\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(",", "")
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat(), int(datetime.strptime(cleaned, fmt).timestamp())
        except ValueError:
            continue
    year = infer_year(cleaned)
    fallback_key = int(f"{year or 0}0000")
    return "", fallback_key


def parse_archive_cards(archive_html: str, archive_url: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r'<a href="(?P<href>details/\d+)" class="archivecolDv">.*?'
        r'<img src="(?P<image>[^"]+)".*?'
        r'<div class="data_title"[^>]*>(?P<title>.*?)</div>.*?'
        r"<div>(?P<date>.*?)</div>",
        re.IGNORECASE | re.DOTALL,
    )
    newsletters = []
    for match in pattern.finditer(archive_html):
        relative_href = match.group("href")
        published_date = normalize_whitespace(match.group("date"))
        published_iso, sort_key = parse_issue_datetime(published_date)
        newsletters.append(
            {
                "title": normalize_whitespace(match.group("title")),
                "published_date": published_date,
                "published_iso_date": published_iso,
                "published_year": infer_year(published_date),
                "sort_key": sort_key,
                "archive_relative_url": relative_href,
                "detail_url": urljoin(archive_url, relative_href),
                "image_url": urljoin(archive_url, match.group("image")),
                "archive_source": archive_url,
            }
        )
    return newsletters


def split_page_divs(detail_html: str) -> list[str]:
    matches = list(re.finditer(r'<div\s+class="pageDiv\b[^"]*">', detail_html, re.IGNORECASE))
    if not matches:
        return []

    segments = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(detail_html)
        segments.append(detail_html[start:end])
    return segments


def parse_article_segment(segment_html: str) -> dict[str, Any] | None:
    title_match = re.search(r"<h2[^>]*>(.*?)</h2>", segment_html, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None

    title = normalize_whitespace(strip_html(title_match.group(1)))
    text_match = re.search(
        r'<div class="textContnt"[^>]*>(?P<body>.*?)(?:<h3 align="center">(?:.*?)(?:Our Vision:|Curiosity)|<hr>)',
        segment_html,
        re.IGNORECASE | re.DOTALL,
    )
    body_html = text_match.group("body") if text_match else segment_html
    body_text = strip_html(body_html)

    image_urls = [
        image
        for image in re.findall(r'<img[^>]+src="([^"]+)"', body_html, re.IGNORECASE)
        if image.strip()
    ]

    return {
        "title": title,
        "body_text": body_text,
        "image_urls": image_urls,
    }


def parse_newsletter_detail(detail_html: str, detail_url: str) -> dict[str, Any]:
    issue_title_match = re.search(
        r'<h1 class="newsTitle"[^>]*>(.*?)</h1>', detail_html, re.IGNORECASE | re.DOTALL
    )
    issue_date_match = re.search(
        r'<h4 class="DateDv"[^>]*>(.*?)</h4>', detail_html, re.IGNORECASE | re.DOTALL
    )

    issue_title = normalize_whitespace(strip_html(issue_title_match.group(1))) if issue_title_match else ""
    issue_date = normalize_whitespace(strip_html(issue_date_match.group(1))) if issue_date_match else ""
    issue_iso, issue_sort_key = parse_issue_datetime(issue_date)

    article_segments = split_page_divs(detail_html)
    articles = []
    for segment in article_segments:
        article = parse_article_segment(segment)
        if article:
            articles.append(article)

    return {
        "detail_url": detail_url,
        "issue_title": issue_title,
        "issue_date": issue_date,
        "issue_iso_date": issue_iso,
        "issue_year": infer_year(issue_date),
        "issue_sort_key": issue_sort_key,
        "article_count": len(articles),
        "articles": articles,
    }


def scrape_newsletters(archive_urls: list[str], verify_ssl: bool) -> dict[str, Any]:
    archive_cards: list[dict[str, Any]] = []
    for archive_url in archive_urls:
        archive_html = fetch_html(archive_url, verify_ssl=verify_ssl)
        archive_cards.extend(parse_archive_cards(archive_html, archive_url))

    newsletters = []
    for card in archive_cards:
        detail_html = fetch_html(card["detail_url"], verify_ssl=verify_ssl)
        detail_data = parse_newsletter_detail(detail_html, card["detail_url"])
        merged = {**card, **detail_data}
        merged["year"] = merged.get("issue_year") or merged.get("published_year")
        merged["sort_key"] = merged.get("issue_sort_key") or merged.get("sort_key") or 0
        newsletters.append(merged)

    newsletters.sort(key=lambda item: item.get("sort_key", 0), reverse=True)
    year_counts: dict[int, int] = {}
    for newsletter in newsletters:
        year = newsletter.get("year")
        if isinstance(year, int):
            year_counts[year] = year_counts.get(year, 0) + 1

    return {
        "archive_urls": archive_urls,
        "newsletter_count": len(newsletters),
        "years": [
            {"year": year, "issue_count": count}
            for year, count in sorted(year_counts.items(), reverse=True)
        ],
        "newsletters": newsletters,
    }


def load_or_fetch_data(
    archive_urls: list[str],
    output_path: Path,
    verify_ssl: bool,
    refresh: bool,
) -> tuple[dict[str, Any], bool]:
    if output_path.exists() and not refresh:
        return json.loads(output_path.read_text(encoding="utf-8")), True
    data = scrape_newsletters(archive_urls, verify_ssl=verify_ssl)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data, False


def count_occurrences(text: str, keyword_pattern: re.Pattern[str]) -> int:
    return len(keyword_pattern.findall(text))


def make_snippet(text: str, keyword_pattern: re.Pattern[str], radius: int = 120) -> str:
    match = keyword_pattern.search(text)
    if not match:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact[: radius * 2] + ("..." if len(compact) > radius * 2 else "")

    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    snippet = text[start:end].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def search_newsletters(data: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
    keyword_pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    results: list[dict[str, Any]] = []

    for newsletter in data.get("newsletters", []):
        for article in newsletter.get("articles", []):
            searchable_text = " ".join(
                [
                    newsletter.get("issue_title", ""),
                    newsletter.get("issue_date", ""),
                    article.get("title", ""),
                    article.get("body_text", ""),
                ]
            )
            hit_count = count_occurrences(searchable_text, keyword_pattern)
            if not hit_count:
                continue

            results.append(
                {
                    "published_date": newsletter.get("published_date", ""),
                    "issue_date": newsletter.get("issue_date", ""),
                    "detail_url": newsletter.get("detail_url", ""),
                    "article_title": article.get("title", ""),
                    "hit_count": hit_count,
                    "snippet": make_snippet(article.get("body_text", ""), keyword_pattern),
                }
            )

    results.sort(key=lambda item: (-item["hit_count"], item["published_date"], item["article_title"]))
    return results


def print_fetch_summary(data: dict[str, Any], output_path: Path, loaded_from_cache: bool) -> None:
    action = "Loaded" if loaded_from_cache else "Wrote"
    print(f"{action} {data['newsletter_count']} newsletters at {output_path.resolve()}")
    for newsletter in data["newsletters"]:
        print(
            f"- {newsletter['published_date']} | {newsletter['detail_url']} | "
            f"{newsletter['article_count']} articles"
        )


def print_search_results(keyword: str, results: list[dict[str, Any]], limit: int) -> None:
    if not results:
        print(f'No matches found for "{keyword}".')
        return

    print(f'Found {len(results)} matching article(s) for "{keyword}":')
    for result in results[:limit]:
        print(f"- {result['published_date']} | {result['article_title']} | hits={result['hit_count']}")
        print(f"  URL: {result['detail_url']}")
        print(f"  Snippet: {result['snippet']}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Laburnum Primary School eNews newsletters from the available archive pages."
    )
    parser.add_argument(
        "--archive-url",
        action="append",
        dest="archive_urls",
        help="Archive page to scrape. Pass multiple times to combine multiple archive pages.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Path to the JSON file to write.",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Enable TLS certificate verification. Off by default because this site may fail local verification.",
    )
    parser.add_argument(
        "--keyword",
        help="Search the fetched newsletters for a keyword or phrase.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of search matches to print.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch the site again even if the output JSON already exists.",
    )
    args = parser.parse_args()

    if not args.verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    archive_urls = args.archive_urls or ARCHIVE_URLS
    output_path = Path(args.output)
    data, loaded_from_cache = load_or_fetch_data(
        archive_urls=archive_urls,
        output_path=output_path,
        verify_ssl=args.verify_ssl,
        refresh=args.refresh,
    )

    print_fetch_summary(data, output_path, loaded_from_cache)

    if args.keyword:
        print()
        results = search_newsletters(data, args.keyword)
        print_search_results(args.keyword, results, args.limit)


if __name__ == "__main__":
    main()
