import os
import sys
import argparse
import requests
from pathlib import Path
from urllib.parse import urlparse


def get_filename_from_url(url):
    """Extract filename from URL, falling back to a sanitized URL hash if needed."""
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename:
        # Fall back to a hash of the URL if no usable filename found
        import hashlib
        filename = hashlib.md5(url.encode()).hexdigest()
    return filename


def download_file(url, dest_dir, session, timeout=30):
    """Download a single file, returning a result dict."""
    filename = get_filename_from_url(url)
    dest_path = dest_dir / filename

    # Handle duplicate filenames by appending a counter
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    try:
        response = session.get(url, timeout=timeout, stream=True)
        response.raise_for_status()

        total = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)

        size_kb = dest_path.stat().st_size / 1024
        return {
            "url": url,
            "filename": dest_path.name,
            "size_kb": round(size_kb, 1),
            "status": "ok",
            "error": None,
        }

    except requests.exceptions.RequestException as e:
        # Clean up partial file if it exists
        if dest_path.exists():
            dest_path.unlink()
        return {
            "url": url,
            "filename": None,
            "size_kb": None,
            "status": "error",
            "error": str(e),
        }


def load_urls(url_file):
    """Load URLs from a text file, skipping blank lines and comments."""
    urls = []
    with open(url_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="Download files from a list of URLs."
    )
    parser.add_argument("url_file", help="Text file containing one URL per line")
    parser.add_argument("dest_dir", help="Directory to save downloaded files")
    parser.add_argument(
        "--timeout", "-t", type=int, default=30,
        help="Request timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--skip-existing", "-s", action="store_true",
        help="Skip download if a file with the same name already exists"
    )
    args = parser.parse_args()

    # Validate inputs
    if not os.path.isfile(args.url_file):
        print(f"Error: URL file '{args.url_file}' not found.", file=sys.stderr)
        sys.exit(1)

    dest_dir = Path(args.dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    urls = load_urls(args.url_file)
    if not urls:
        print("No URLs found in input file.")
        sys.exit(0)

    print(f"Downloading {len(urls)} file(s) to '{dest_dir}'...\n")

    success, skipped, failed = 0, 0, 0

    with requests.Session() as session:
        session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; image-downloader/1.0)"})

        for i, url in enumerate(urls, 1):
            filename = get_filename_from_url(url)
            prefix = f"[{i}/{len(urls)}]"

            if args.skip_existing and (dest_dir / filename).exists():
                print(f"{prefix} Skipping (exists): {filename}")
                skipped += 1
                continue

            print(f"{prefix} Downloading: {url}")
            result = download_file(url, dest_dir, session, timeout=args.timeout)

            if result["status"] == "ok":
                print(f"  -> {result['filename']} ({result['size_kb']} KB)")
                success += 1
            else:
                print(f"  -> ERROR: {result['error']}")
                failed += 1

    print(f"\nDone. {success} downloaded, {skipped} skipped, {failed} failed.")


if __name__ == "__main__":
    main()