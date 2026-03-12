import os
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
import time

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


def scrape_page_text(url, main_content_only=True):
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

def main(
    sitemap_url,
    output_dir="scraped_pages",
    max_saved_pages=MAX_SCRAPED_PAGES_TEST,
    request_delay_seconds=REQUEST_DELAY_SECONDS,
    main_content_only=MAIN_CONTENT_ONLY_DEFAULT,
):
    """Main execution function."""
    domain_dir = os.path.join(output_dir, safe_domain_name(sitemap_url))
    os.makedirs(domain_dir, exist_ok=True)

    print(f"Fetching sitemap: {sitemap_url}")
    print(f"Saving pages into: {domain_dir}")
    urls = list(dict.fromkeys(get_sitemap_urls(sitemap_url)))
    
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

    stats = {
        "saved": 0,
        "skipped_extension": 0,
        "skipped_content_type": 0,
        "errors": 0,
    }

    for i, url in enumerate(urls):
        if max_saved_pages > 0 and stats["saved"] >= max_saved_pages:
            print(f"Reached test limit of {max_saved_pages} saved pages. Stopping.")
            break

        if not should_scrape_url(url):
            print(f"Skipping non-HTML URL by extension: {url}")
            stats["skipped_extension"] += 1
            continue

        print(f"Scraping ({i+1}/{len(urls)}): {url}")
        text, status = scrape_page_text(url, main_content_only=main_content_only)
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)
        
        if text:
            # Filename preserves relative URL path cues while staying filesystem-safe.
            safe_name = safe_filename_from_url(url)
            filename = os.path.join(domain_dir, f"{safe_name}.rtf")
            
            save_as_rtf(text, filename)
            print(f"  -> Saved to {filename}")
            stats["saved"] += 1
        elif status == "skipped_content_type":
            stats["skipped_content_type"] += 1
        elif status == "error":
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

if __name__ == "__main__":
    user_value = input(
        "Enter a domain/base URL or full sitemap URL "
        "(example.com OR https://example.com/sitemap.xml): "
    )
    try:
        target_sitemap = normalize_input_to_sitemap(user_value)
        max_pages = prompt_int_with_default(
            "Max pages to save for this run (0 for unlimited)",
            MAX_SCRAPED_PAGES_TEST,
            min_value=0,
        )
        delay_seconds = prompt_float_with_default(
            "Delay between page requests (seconds)",
            REQUEST_DELAY_SECONDS,
        )
        main_only = prompt_yes_no_with_default(
            "Try to extract only main page content (exclude header/footer/nav)",
            MAIN_CONTENT_ONLY_DEFAULT,
        )
        print(f"Using sitemap URL: {target_sitemap}")
        main(
            target_sitemap,
            max_saved_pages=max_pages,
            request_delay_seconds=delay_seconds,
            main_content_only=main_only,
        )
    except ValueError as e:
        print(f"Input error: {e}")