# Sitemap Content Scraper (Python 3)

Need to rip page content from a sitemap without manually copy-pasting like it's 2009?  
This script handles that nonsense and saves each page as `.rtf` or `.docx`.

## What This Beast Does

- Handles standard sitemaps and Yoast/WordPress split sitemap indexes
- Lets you choose one or more sub-sitemaps from a sitemap index
- Sorts output into domain-specific folders
- Preserves relative URL path hints in filenames
- Can try to grab mostly main content (and ditch header/footer junk)
- Supports test caps and request delays so you do not accidentally DDoS someone

## Requirements

- Python 3
- `requests`
- `beautifulsoup4`
- `python-docx` (only needed for DOCX output)

Install dependencies:

```bash
python3 -m pip install requests beautifulsoup4 python-docx
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

5. **Optional main-content CSS selector**
   - Leave blank to auto-detect
   - Example selectors: `main`, `article`, `#content`, `.entry-content`
   - Useful when a site has a weird layout and auto-detection picks garbage

6. **Output format**
   - `rtf` or `docx`

7. **Combine pages into one domain document (yes/no)**
   - `yes`: saves one file like `all_pages.rtf` or `all_pages.docx`
   - `no`: saves one file per scraped page

If your sitemap is a sitemap index, the script will show the child sub-sitemaps and let you choose one, many, or all.

## CLI Arguments (Optional)

If you don't want prompts, you can pass args:

```bash
python3 scraper.py \
  --sitemap "https://example.com/sitemap.xml" \
  --max-pages 10 \
  --delay 1.0 \
  --main-content-only yes \
  --main-selector ".entry-content" \
  --format docx \
  --sub-sitemaps "1,3,5" \
  --combine-per-domain
```

Flags:
- `--sitemap` domain/base URL or full sitemap URL
- `--max-pages` max pages to save (`0` = unlimited)
- `--delay` seconds between requests
- `--main-content-only` `yes` or `no`
- `--main-selector` optional CSS selector for main-content extraction
- `--format` `rtf` or `docx`
- `--sub-sitemaps` comma-separated 1-based indexes from sitemap index (`all` if omitted)
- `--combine-per-domain` combine all scraped pages into one file

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
scraped_pages/example.com/all_pages.docx
```

Filenames are sanitized to stay filesystem-safe and include path/query cues to reduce collisions.

## Notes Before You Do Dumb Stuff

- Non-HTML URLs (images, PDFs, archives, feeds, etc.) are skipped.
- Responses that are not HTML by `Content-Type` are skipped too.
- End-of-run summary shows saved/skipped/error counts.
- Be respectful: check site terms and robots policies before scraping.
- Use test caps and delay first. Do not be that person.
