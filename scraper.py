import os
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import time
import argparse
import importlib

NON_HTML_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".txt",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
    ".mp3", ".wav", ".ogg", ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".xml", ".json", ".rss", ".atom"
}
MAX_SCRAPED_PAGES_TEST = 10
REQUEST_DELAY_SECONDS = 1.0
MAIN_CONTENT_ONLY_DEFAULT = True
OUTPUT_FORMAT_DEFAULT = "rtf"
COMBINE_PER_DOMAIN_DEFAULT = False

def get_sitemap_urls(sitemap_url, visited_sitemaps=None):
    """Fetches sitemap URLs, including sitemap index files (Yoast/WordPress)."""
    if visited_sitemaps is None:
        visited_sitemaps = set()
    if sitemap_url in visited_sitemaps:
        return []
    visited_sitemaps.add(sitemap_url)

    try:
        # We use headers to mimic a normal browser so we don't get blocked
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(sitemap_url, headers=headers)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        root_tag = root.tag.lower()

        # Yoast/WordPress often use a sitemap index file listing many child sitemaps.
        if root_tag.endswith("sitemapindex"):
            all_urls = []
            for child in root.iter():
                if child.tag.endswith('loc') and child.text:
                    child_sitemap = child.text.strip()
                    if child_sitemap:
                        all_urls.extend(get_sitemap_urls(child_sitemap, visited_sitemaps))
            return all_urls

        # Standard sitemap URL set: return page URLs.
        urls = []
        for child in root.iter():
            if child.tag.endswith('loc') and child.text:
                url = child.text.strip()
                if url:
                    urls.append(url)
        return urls
    except Exception as e:
        print(f"Error fetching sitemap {sitemap_url}: {e}")
        return []


def get_direct_sub_sitemaps(sitemap_url):
    """Returns direct child sitemap URLs when sitemap_url is a sitemap index."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(sitemap_url, headers=headers)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        if not root.tag.lower().endswith("sitemapindex"):
            return []

        sub_sitemaps = []
        for child in root.iter():
            if child.tag.endswith('loc') and child.text:
                value = child.text.strip()
                if value:
                    sub_sitemaps.append(value)
        return list(dict.fromkeys(sub_sitemaps))
    except Exception as e:
        print(f"Unable to list sub-sitemaps from {sitemap_url}: {e}")
        return []


def normalize_input_to_sitemap(user_input):
    """Converts a domain/base URL or sitemap URL into a final sitemap URL."""
    value = (user_input or "").strip()
    if not value:
        raise ValueError("Input cannot be empty.")

    # Allow domain-only input like "example.com".
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if not parsed.netloc:
        raise ValueError("Please provide a valid domain or URL.")

    path = parsed.path or ""
    if path.endswith(".xml"):
        sitemap_path = path
    elif path.endswith("/"):
        sitemap_path = f"{path}sitemap.xml"
    elif path:
        sitemap_path = f"{path}/sitemap.xml"
    else:
        sitemap_path = "/sitemap.xml"

    return f"{parsed.scheme}://{parsed.netloc}{sitemap_path}"


def safe_domain_name(url):
    """Returns a filesystem-safe domain key from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.split("@")[-1].split(":")[0].strip().lower()
    if not domain:
        domain = "unknown-domain"
    return re.sub(r"[^a-z0-9.-]", "_", domain)


def safe_filename_from_url(url):
    """Builds a filename from relative URL path, preserving path structure cues."""
    parsed_url = urlparse(url)
    path = parsed_url.path.strip("/")
    path_part = path.replace("/", "_") if path else "index"

    # Keep query data identifiable to reduce collisions between pages.
    query_part = ""
    if parsed_url.query:
        query_part = "__q_" + re.sub(r"[^a-zA-Z0-9._-]", "_", parsed_url.query)

    full_name = f"{path_part}{query_part}"
    return re.sub(r"[^a-zA-Z0-9._-]", "_", full_name)


def should_scrape_url(url):
    """Skips obvious non-HTML asset/file URLs before requesting page content."""
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    _, ext = os.path.splitext(path)
    return ext not in NON_HTML_EXTENSIONS


def get_content_container(soup, main_content_only):
    """Finds the best content container; falls back safely when needed."""
    if not main_content_only:
        return soup

    selectors = [
        "main",
        "article",
        "[role='main']",
        "#main",
        "#content",
        "#primary",
        ".main",
        ".content",
        ".post",
        ".entry-content",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node

    # Fallback for pages without semantic/main wrappers.
    return soup.body if soup.body else soup


def scrape_page_text(url, main_content_only=True, main_content_selector=None):
    """Scrapes the main text content from a URL, stripping out noise."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type:
            print(f"Skipping non-HTML response ({content_type or 'unknown'}): {url}")
            return "", "skipped_content_type"
        soup = BeautifulSoup(response.content, 'html.parser')

        content_root = None
        if main_content_only and main_content_selector:
            content_root = soup.select_one(main_content_selector)
            if content_root is None:
                print(
                    f"Main selector '{main_content_selector}' not found on page; "
                    "falling back to auto-detection."
                )
        if content_root is None:
            content_root = get_content_container(soup, main_content_only)

        # Remove noisy layout elements from whichever container is selected.
        for element in content_root(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
            
        text = content_root.get_text(separator='\n', strip=True)
        return text, "ok"
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return "", "error"

def save_as_rtf(text, filename):
    """Saves plain text into a basic RTF format."""
    # Basic escaping required for the RTF format
    text = text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')
    text = text.replace('\n', '\\par\n')
    
    # RTF Header and body
    rtf_content = r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fnil\fcharset0 Calibri;}}\f0\fs24 "
    rtf_content += text + r"}"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(rtf_content)


def save_as_docx(text, filename):
    """Saves plain text into a DOCX file."""
    try:
        docx_module = importlib.import_module("docx")
    except ImportError as e:
        raise RuntimeError(
            "DOCX output requires python-docx. Install with: "
            "python3 -m pip install python-docx"
        ) from e

    document = docx_module.Document()
    for paragraph in text.split("\n"):
        document.add_paragraph(paragraph)
    document.save(filename)


def save_text_file(text, filename_base, output_format):
    """Saves text as either RTF or DOCX based on requested format."""
    output_format = (output_format or OUTPUT_FORMAT_DEFAULT).lower()
    if output_format == "rtf":
        filename = f"{filename_base}.rtf"
        save_as_rtf(text, filename)
        return filename
    if output_format == "docx":
        filename = f"{filename_base}.docx"
        save_as_docx(text, filename)
        return filename
    raise ValueError(f"Unsupported output format: {output_format}")


def build_combined_text(scraped_pages):
    """Combines multiple page texts into one text body with URL separators."""
    chunks = []
    for url, text in scraped_pages:
        chunks.append(f"URL: {url}\n\n{text}")
    return "\n\n" + ("\n\n" + ("=" * 80) + "\n\n").join(chunks)

def main(
    sitemap_url,
    output_dir="scraped_pages",
    max_saved_pages=MAX_SCRAPED_PAGES_TEST,
    request_delay_seconds=REQUEST_DELAY_SECONDS,
    main_content_only=MAIN_CONTENT_ONLY_DEFAULT,
    output_format=OUTPUT_FORMAT_DEFAULT,
    combine_per_domain=COMBINE_PER_DOMAIN_DEFAULT,
    urls_override=None,
    main_content_selector=None,
):
    """Main execution function."""
    domain_dir = os.path.join(output_dir, safe_domain_name(sitemap_url))
    os.makedirs(domain_dir, exist_ok=True)

    print(f"Fetching sitemap: {sitemap_url}")
    print(f"Saving pages into: {domain_dir}")
    if urls_override is None:
        urls = list(dict.fromkeys(get_sitemap_urls(sitemap_url)))
    else:
        urls = list(dict.fromkeys(urls_override))
    
    if not urls:
        print("No URLs found. Check the sitemap URL.")
        return

    print(f"Found {len(urls)} URLs. Starting scrape...")
    if max_saved_pages == 0:
        print("Page limit: unlimited (0 selected).")
    else:
        print(f"Test mode limit: stop after {max_saved_pages} saved pages.")
    print(f"Request delay: {request_delay_seconds:.1f}s between page requests.")
    print(f"Main-content-only mode: {'on' if main_content_only else 'off'}")
    if main_content_only and main_content_selector:
        print(f"Main-content CSS selector: {main_content_selector}")
    print(f"Output format: {output_format}")
    print(f"Combine into single domain document: {'yes' if combine_per_domain else 'no'}")

    stats = {
        "saved": 0,
        "skipped_extension": 0,
        "skipped_content_type": 0,
        "errors": 0,
    }
    scraped_pages = []

    for i, url in enumerate(urls):
        if max_saved_pages > 0 and stats["saved"] >= max_saved_pages:
            print(f"Reached test limit of {max_saved_pages} saved pages. Stopping.")
            break

        if not should_scrape_url(url):
            print(f"Skipping non-HTML URL by extension: {url}")
            stats["skipped_extension"] += 1
            continue

        print(f"Scraping ({i+1}/{len(urls)}): {url}")
        text, status = scrape_page_text(
            url,
            main_content_only=main_content_only,
            main_content_selector=main_content_selector,
        )
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        
        if text:
            if combine_per_domain:
                scraped_pages.append((url, text))
                print("  -> Added to combined domain document")
            else:
                # Filename preserves relative URL path cues while staying filesystem-safe.
                safe_name = safe_filename_from_url(url)
                filename_base = os.path.join(domain_dir, safe_name)
                try:
                    filename = save_text_file(text, filename_base, output_format)
                    print(f"  -> Saved to {filename}")
                except Exception as e:
                    print(f"  -> Failed to save {url}: {e}")
                    stats["errors"] += 1
                    continue
            stats["saved"] += 1
        elif status == "skipped_content_type":
            stats["skipped_content_type"] += 1
        elif status == "error":
            stats["errors"] += 1

    if combine_per_domain and scraped_pages:
        combined_text = build_combined_text(scraped_pages)
        combined_base = os.path.join(domain_dir, "all_pages")
        try:
            combined_filename = save_text_file(combined_text, combined_base, output_format)
            print(f"\nCombined document saved to: {combined_filename}")
        except Exception as e:
            print(f"\nFailed to save combined domain document: {e}")
            stats["errors"] += 1

    print("\nRun summary:")
    print(f"- Saved pages: {stats['saved']}")
    print(f"- Skipped by extension: {stats['skipped_extension']}")
    print(f"- Skipped by content type: {stats['skipped_content_type']}")
    print(f"- Request errors: {stats['errors']}")


def prompt_int_with_default(prompt_text, default, min_value=1):
    """Prompts for integer value with a default fallback."""
    value = input(f"{prompt_text} [{default}]: ").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        print(f"Invalid integer '{value}'. Using default {default}.")
        return default
    if parsed < min_value:
        print(f"Value must be >= {min_value}. Using default {default}.")
        return default
    return parsed


def prompt_float_with_default(prompt_text, default):
    """Prompts for float value with a default fallback."""
    value = input(f"{prompt_text} [{default}]: ").strip()
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        print(f"Invalid number '{value}'. Using default {default}.")
        return default
    if parsed < 0:
        print(f"Value must be >= 0. Using default {default}.")
        return default
    return parsed


def prompt_yes_no_with_default(prompt_text, default):
    """Prompts for yes/no with a default fallback."""
    default_hint = "Y/n" if default else "y/N"
    value = input(f"{prompt_text} [{default_hint}]: ").strip().lower()
    if not value:
        return default
    if value in ("y", "yes"):
        return True
    if value in ("n", "no"):
        return False
    print(f"Invalid choice '{value}'. Using default {'yes' if default else 'no'}.")
    return default


def prompt_choice_with_default(prompt_text, choices, default):
    """Prompts for a string choice with default fallback."""
    choices_display = "/".join(choices)
    value = input(f"{prompt_text} ({choices_display}) [{default}]: ").strip().lower()
    if not value:
        return default
    if value in choices:
        return value
    print(f"Invalid choice '{value}'. Using default '{default}'.")
    return default


def parse_cli_args():
    """Parses optional command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Scrape text from sitemap URLs and save as RTF or DOCX."
    )
    parser.add_argument(
        "--sitemap",
        help="Domain/base URL or full sitemap URL (example.com or https://example.com/sitemap.xml).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Max pages to save (0 = unlimited).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay between page requests in seconds.",
    )
    parser.add_argument(
        "--main-content-only",
        choices=["yes", "no"],
        help="Try to extract just the main page content.",
    )
    parser.add_argument(
        "--main-selector",
        help=(
            "Optional CSS selector for main content extraction "
            "(example: main, article, #content, .entry-content)."
        ),
    )
    parser.add_argument(
        "--format",
        choices=["rtf", "docx"],
        help="Output format for saved files.",
    )
    parser.add_argument(
        "--combine-per-domain",
        action="store_true",
        help="Combine all scraped pages into one document per domain.",
    )
    parser.add_argument(
        "--sub-sitemaps",
        help=(
            "Comma-separated 1-based sub-sitemap indexes to scrape from a sitemap index "
            "(example: 1,3,5). If omitted, prompts interactively."
        ),
    )
    return parser.parse_args()


def parse_sub_sitemap_selection(selection_text, total):
    """Parses comma-separated 1-based indexes into zero-based list."""
    selection_text = (selection_text or "").strip().lower()
    if selection_text in ("", "all", "*"):
        return list(range(total))

    indexes = []
    for token in selection_text.split(","):
        value = token.strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError(f"Invalid selection token: '{value}'")
        idx = int(value)
        if idx < 1 or idx > total:
            raise ValueError(f"Selection out of range: '{idx}' (valid: 1-{total})")
        indexes.append(idx - 1)
    if not indexes:
        raise ValueError("No valid sub-sitemap indexes selected.")
    return list(dict.fromkeys(indexes))


def choose_sub_sitemaps(sitemap_url, cli_selection_text=None):
    """Lets user choose one or more direct sub-sitemaps when sitemap index is detected."""
    sub_sitemaps = get_direct_sub_sitemaps(sitemap_url)
    if not sub_sitemaps:
        return []

    print("\nDetected sitemap index with these sub-sitemaps:")
    for i, sub in enumerate(sub_sitemaps, start=1):
        print(f"  {i}. {sub}")

    if cli_selection_text is None:
        selection_text = input(
            "Select sub-sitemaps by number (comma-separated), or 'all' "
            "[all]: "
        )
    else:
        selection_text = cli_selection_text

    try:
        selected_indexes = parse_sub_sitemap_selection(selection_text, len(sub_sitemaps))
    except ValueError as e:
        print(f"Invalid sub-sitemap selection ({e}). Falling back to all.")
        selected_indexes = list(range(len(sub_sitemaps)))

    selected = [sub_sitemaps[i] for i in selected_indexes]
    print(f"Selected {len(selected)} sub-sitemap(s).")
    return selected

if __name__ == "__main__":
    args = parse_cli_args()
    user_value = args.sitemap or input(
        "Enter a domain/base URL or full sitemap URL "
        "(example.com OR https://example.com/sitemap.xml): "
    )
    try:
        target_sitemap = normalize_input_to_sitemap(user_value)
        max_pages = (
            args.max_pages
            if args.max_pages is not None
            else prompt_int_with_default(
                "Max pages to save for this run (0 for unlimited)",
                MAX_SCRAPED_PAGES_TEST,
                min_value=0,
            )
        )
        if max_pages < 0:
            print(f"Invalid --max-pages '{max_pages}'. Falling back to default.")
            max_pages = MAX_SCRAPED_PAGES_TEST

        delay_seconds = (
            args.delay
            if args.delay is not None
            else prompt_float_with_default(
                "Delay between page requests (seconds)",
                REQUEST_DELAY_SECONDS,
            )
        )
        if delay_seconds < 0:
            print(f"Invalid --delay '{delay_seconds}'. Falling back to default.")
            delay_seconds = REQUEST_DELAY_SECONDS

        if args.main_content_only is None:
            main_only = prompt_yes_no_with_default(
                "Try to extract only main page content (exclude header/footer/nav)",
                MAIN_CONTENT_ONLY_DEFAULT,
            )
        else:
            main_only = args.main_content_only == "yes"

        if main_only:
            main_selector = args.main_selector
            if main_selector is None:
                main_selector = input(
                    "Optional CSS selector for main content "
                    "(blank = auto-detect; examples: main, article, #content, .entry-content): "
                ).strip()
                if not main_selector:
                    main_selector = None
        else:
            main_selector = None

        output_format = args.format or prompt_choice_with_default(
            "Output format",
            ["rtf", "docx"],
            OUTPUT_FORMAT_DEFAULT,
        )

        combine_per_domain = (
            args.combine_per_domain
            if args.combine_per_domain
            else prompt_yes_no_with_default(
                "Combine all scraped pages into one document per domain",
                COMBINE_PER_DOMAIN_DEFAULT,
            )
        )

        print(f"Using sitemap URL: {target_sitemap}")
        selected_sub_sitemaps = choose_sub_sitemaps(
            target_sitemap,
            cli_selection_text=args.sub_sitemaps,
        )
        if selected_sub_sitemaps:
            all_urls = []
            for sub_sitemap_url in selected_sub_sitemaps:
                all_urls.extend(get_sitemap_urls(sub_sitemap_url))
            selected_urls = list(dict.fromkeys(all_urls))
            print(f"Collected {len(selected_urls)} URL(s) from selected sub-sitemaps.")
            main(
                target_sitemap,
                max_saved_pages=max_pages,
                request_delay_seconds=delay_seconds,
                main_content_only=main_only,
                output_format=output_format,
                combine_per_domain=combine_per_domain,
                urls_override=selected_urls,
                main_content_selector=main_selector,
            )
        else:
            main(
                target_sitemap,
                max_saved_pages=max_pages,
                request_delay_seconds=delay_seconds,
                main_content_only=main_only,
                output_format=output_format,
                combine_per_domain=combine_per_domain,
                main_content_selector=main_selector,
            )
    except ValueError as e:
        print(f"Input error: {e}")