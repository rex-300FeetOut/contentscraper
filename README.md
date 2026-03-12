# Sitemap Content Scraper (Python 3)

Need to rip page content from a sitemap without manually copy-pasting like it's 2009?  
This script handles that nonsense and saves each page as an `.rtf` file.

## What This Beast Does

- Handles standard sitemaps and Yoast/WordPress split sitemap indexes
- Sorts output into domain-specific folders
- Preserves relative URL path hints in filenames
- Can try to grab mostly main content (and ditch header/footer junk)
- Supports test caps and request delays so you do not accidentally DDoS someone

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`

Install dependencies:

```bash
python3 -m pip install requests beautifulsoup4
```

## Run It

From this directory:

```bash
python3 scraper.py
```

You will be prompted for:

1. **Domain/base URL or full sitemap URL**
   - Examples:
     - `example.com`
     - `https://example.com`
     - `https://example.com/sitemap.xml`

2. **Max pages to save for this run**
   - Enter a positive number to cap pages while testing
   - Enter `0` for unlimited (send it)

3. **Delay between page requests (seconds)**
   - Example: `1.0`
   - Helps avoid tripping rate limits and making ops teams hate your guts

4. **Main-content-only mode (yes/no)**
   - `yes`: tries to focus on actual page content and skip template noise
   - `no`: grabs broader page text, including more surrounding fluff

## Output Structure

Saved under:

```text
scraped_pages/<domain>/
```

Examples:

```text
scraped_pages/example.com/index.rtf
scraped_pages/example.com/blog_docs_getting-started.rtf
scraped_pages/example.com/products_item__q_color_blue.rtf
```

Filenames are sanitized to stay filesystem-safe and include path/query cues to reduce collisions.

## Notes Before You Do Dumb Stuff

- Non-HTML URLs (images, PDFs, archives, feeds, etc.) are skipped.
- Responses that are not HTML by `Content-Type` are skipped too.
- End-of-run summary shows saved/skipped/error counts.
- Be respectful: check site terms and robots policies before scraping.
- Use test caps and delay first. Do not be that person.
