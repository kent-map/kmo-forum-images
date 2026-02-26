import os
import sys
import argparse
import shutil
from pathlib import Path
from PIL import Image
import imghdr


# Optimization settings
SIZE_THRESHOLD_MB = 5
MAX_DIMENSION = 4000
JPEG_QUALITY = 85


def is_uuid_like(s):
    """Return True if s looks like a UUID with or without hyphens."""
    clean = s.replace("-", "")
    return len(clean) == 32 and all(c in "0123456789abcdefABCDEF" for c in clean)


def format_uuid(stem):
    """
    Convert a 32-char hex string to hyphenated UUID format.
    e.g. 19f6b479ac822c03290b5fcec74f1663
      -> 19f6b479-ac82-2c03-290b-5fcec74f1663
    Returns the original string unchanged if it doesn't look like a UUID.
    """
    clean = stem.replace("-", "")
    if len(clean) == 32 and all(c in "0123456789abcdefABCDEF" for c in clean):
        return f"{clean[0:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:32]}"
    return stem


def detect_extension(file_path):
    """
    Detect image type from file contents and return (ext, kind).
    Returns (None, None) if the file is not a recognised image format.
    """
    try:
        kind = imghdr.what(file_path)
    except Exception:
        return None, None
    if kind is None:
        return None, None
    mapping = {
        "jpeg": ".jpg",
        "png":  ".png",
        "gif":  ".gif",
        "webp": ".webp",
        "tiff": ".tiff",
        "bmp":  ".bmp",
    }
    return mapping.get(kind), kind


def ext_from_suffix(suffix):
    """Normalise a file suffix to a canonical extension."""
    mapping = {
        ".jpg":  ".jpg",
        ".jpeg": ".jpg",
        ".png":  ".png",
        ".gif":  ".gif",
        ".webp": ".webp",
        ".tiff": ".tiff",
        ".tif":  ".tiff",
        ".bmp":  ".bmp",
    }
    return mapping.get(suffix.lower())


def needs_optimization(file_path, threshold_mb=SIZE_THRESHOLD_MB):
    """Return True if file exceeds the size threshold."""
    return file_path.stat().st_size > threshold_mb * 1024 * 1024


def optimize_image(src_path, dest_path, ext):
    """Resize and lightly compress an image, preserving metadata."""
    with Image.open(src_path) as img:
        original_size = img.size

        if max(img.size) > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

        save_kwargs = {}
        if "exif" in img.info:
            save_kwargs["exif"] = img.info["exif"]

        if ext == ".jpg":
            save_kwargs["quality"] = JPEG_QUALITY
            save_kwargs["optimize"] = True
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
        elif ext == ".png":
            save_kwargs["optimize"] = True

        img.save(dest_path, **save_kwargs)

    return original_size, img.size


def convert_to_jpg(src_path, dest_path):
    """Convert a TIFF or PNG to a JPEG, preserving metadata where possible."""
    with Image.open(src_path) as img:
        original_size = img.size

        if max(img.size) > MAX_DIMENSION:
            img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

        save_kwargs = {"quality": JPEG_QUALITY, "optimize": True}
        if "exif" in img.info:
            save_kwargs["exif"] = img.info["exif"]

        if img.mode != "RGB":
            img = img.convert("RGB")

        img.save(dest_path, "JPEG", **save_kwargs)

    return original_size, img.size


def main():
    parser = argparse.ArgumentParser(
        description="Rename images to hyphenated UUID format, add extensions, "
                    "optimize large files, and create JPG versions of TIFF/PNG."
    )
    parser.add_argument("src_dir", help="Directory containing downloaded images")
    parser.add_argument(
        "dest_dir", nargs="?",
        help="Output directory (defaults to src_dir, renaming in place)"
    )
    parser.add_argument(
        "--threshold", "-t", type=float, default=SIZE_THRESHOLD_MB,
        help=f"File size threshold in MB for optimization (default: {SIZE_THRESHOLD_MB})"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be done without making any changes"
    )
    args = parser.parse_args()

    src_dir = Path(args.src_dir)
    dest_dir = Path(args.dest_dir) if args.dest_dir else src_dir
    in_place = dest_dir == src_dir

    if not src_dir.is_dir():
        print(f"Error: '{src_dir}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    if not in_place and not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    # Collect files whose stem looks like a UUID (with or without hyphens).
    # This covers both extension-less files and files like 1f10f510...354.jpg
    # that already have an extension but still need the stem reformatted.
    candidates = [
        f for f in src_dir.iterdir()
        if f.is_file() and is_uuid_like(f.stem)
    ]
    if not candidates:
        print("No files requiring processing found.")
        sys.exit(0)

    print(f"Processing {len(candidates)} file(s)...\n")

    results = {"renamed": 0, "optimized": 0, "converted": 0, "skipped": 0, "failed": 0}

    for file_path in sorted(candidates):

        # Determine extension: trust existing suffix if present, otherwise detect from content
        if file_path.suffix:
            ext = ext_from_suffix(file_path.suffix)
            if ext is None:
                # Has a suffix but not a recognised image type — skip silently
                results["skipped"] += 1
                continue
        else:
            ext, _ = detect_extension(file_path)
            if not ext:
                # Not a recognised image — skip silently
                results["skipped"] += 1
                continue

        uuid_stem = format_uuid(file_path.stem)
        dest_path = dest_dir / (uuid_stem + ext)
        original_mb = file_path.stat().st_size / (1024 * 1024)
        should_optimize = needs_optimization(file_path, args.threshold)
        needs_jpg = ext in (".tiff", ".png")

        # Skip if already correctly named and in the right place
        if dest_path == file_path and not should_optimize and not needs_jpg:
            results["skipped"] += 1
            continue

        # Build description of actions for this file
        actions = []
        if uuid_stem != file_path.stem:
            actions.append("reformat UUID")
        if not file_path.suffix:
            actions.append(f"add {ext}")
        if should_optimize:
            actions.append("optimize")
        if needs_jpg:
            actions.append("create .jpg copy")

        print(f"  {file_path.name}  ({original_mb:.1f} MB)")
        print(f"    -> {', '.join(actions) if actions else 'no changes needed'}")

        if args.dry_run:
            continue

        try:
            if should_optimize:
                orig_size, new_size = optimize_image(file_path, dest_path, ext)
                new_mb = dest_path.stat().st_size / (1024 * 1024)
                print(f"    {orig_size[0]}x{orig_size[1]} -> {new_size[0]}x{new_size[1]},  "
                      f"{original_mb:.1f} MB -> {new_mb:.1f} MB")
                if in_place:
                    file_path.unlink()
                results["optimized"] += 1
            else:
                if dest_path != file_path:
                    if in_place:
                        file_path.rename(dest_path)
                    else:
                        shutil.copy2(file_path, dest_path)
                results["renamed"] += 1

            # Create JPG version for TIFF and PNG
            if needs_jpg:
                jpg_path = dest_dir / (uuid_stem + ".jpg")
                orig_size, new_size = convert_to_jpg(dest_path, jpg_path)
                jpg_mb = jpg_path.stat().st_size / (1024 * 1024)
                print(f"    JPG copy: {orig_size[0]}x{orig_size[1]} -> {new_size[0]}x{new_size[1]},  "
                      f"{jpg_mb:.1f} MB")
                results["converted"] += 1

        except Exception as e:
            print(f"    ERROR: {e}")
            results["failed"] += 1

    print(f"\nDone. {results['renamed']} renamed, {results['optimized']} optimized, "
          f"{results['converted']} JPG copies created, "
          f"{results['skipped']} skipped, {results['failed']} failed.")


if __name__ == "__main__":
    main()