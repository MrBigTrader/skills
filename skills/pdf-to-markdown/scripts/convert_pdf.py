"""
Hybrid PDF-to-Markdown Converter

Automatically detects whether a PDF has embedded text (digital) or is scanned,
then routes to the appropriate conversion tool:

  - MarkItDown (Microsoft) for digital PDFs  → fast, CPU-based
  - marker-pdf for scanned PDFs              → GPU-accelerated OCR

The output Markdown is optimized for LLM consumption with clear structure,
page boundaries, and metadata headers.

Usage:
    python convert_pdf.py --source "path/to/file.pdf" --output-dir "path/to/output"
    python convert_pdf.py --source "path/to/file.pdf" --output-dir "path/to/output" --force-ocr
    python convert_pdf.py --source "path/to/file.pdf" --output-dir "path/to/output" --force-markitdown
"""

import argparse
import os
import sys
import time
import subprocess
import re


# ---------------------------------------------------------------------------
# PDF type detection
# ---------------------------------------------------------------------------

def detect_pdf_type(pdf_path, sample_size=5):
    """Detect whether a PDF has embedded text or is scanned (image-based).

    Samples up to `sample_size` pages spread across the document.
    Returns ("digital", details) or ("scanned", details).
    """
    try:
        import pdfplumber
    except ImportError:
        print("ERROR: pdfplumber is not installed. Install with: pip install pdfplumber")
        sys.exit(1)

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        if total_pages == 0:
            return "scanned", {"total_pages": 0, "pages_with_text": 0, "reason": "Empty PDF"}

        # Pick sample pages spread evenly across the document
        if total_pages <= sample_size:
            sample_indices = list(range(total_pages))
        else:
            step = total_pages / sample_size
            sample_indices = [int(i * step) for i in range(sample_size)]

        pages_with_text = 0
        total_chars = 0

        for idx in sample_indices:
            page = pdf.pages[idx]
            text = page.extract_text() or ""
            char_count = len(text.strip())
            total_chars += char_count
            if char_count > 50:
                pages_with_text += 1
            page.close()

    ratio = pages_with_text / len(sample_indices)
    avg_chars = total_chars / len(sample_indices) if sample_indices else 0

    details = {
        "total_pages": total_pages,
        "sampled_pages": len(sample_indices),
        "pages_with_text": pages_with_text,
        "text_ratio": ratio,
        "avg_chars_per_page": avg_chars,
    }

    # If ≥50% of sampled pages have significant text → digital PDF
    if ratio >= 0.5:
        details["reason"] = f"{pages_with_text}/{len(sample_indices)} sampled pages have embedded text"
        return "digital", details
    else:
        details["reason"] = f"Only {pages_with_text}/{len(sample_indices)} sampled pages have embedded text"
        return "scanned", details


# ---------------------------------------------------------------------------
# LLM-optimized post-processing
# ---------------------------------------------------------------------------

def postprocess_for_llm(markdown_text, source_filename, total_pages=None):
    """Post-process raw Markdown to make it more structured and useful for LLMs.

    Adds:
      - A metadata header with source file info
      - Cleans up excessive whitespace
      - Normalizes heading levels
      - Ensures consistent line spacing
    """
    lines = []

    # Metadata header
    lines.append(f"# {os.path.splitext(source_filename)[0]}")
    lines.append("")
    lines.append(f"> **Source**: `{source_filename}`")
    if total_pages:
        lines.append(f"> **Pages**: {total_pages}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Clean up the raw markdown
    content = markdown_text.strip()

    # Collapse 3+ consecutive blank lines into 2
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    # Remove trailing whitespace from each line
    content = '\n'.join(line.rstrip() for line in content.split('\n'))

    lines.append(content)

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Conversion: MarkItDown (digital PDFs)
# ---------------------------------------------------------------------------

def convert_with_markitdown(pdf_path, output_dir):
    """Convert a digital PDF using Microsoft MarkItDown (CPU, fast)."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        print("ERROR: markitdown is not installed.")
        print("FIX: pip install markitdown[pdf]")
        sys.exit(1)

    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    target_dir = os.path.join(output_dir, basename)
    os.makedirs(target_dir, exist_ok=True)
    out_md = os.path.join(target_dir, f"{basename}.md")

    print(f"Converting with MarkItDown (CPU)...")
    start = time.time()

    md = MarkItDown()
    result = md.convert(pdf_path)

    # Get page count for metadata
    total_pages = None
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
    except Exception:
        pass

    # Post-process for LLM consumption
    processed = postprocess_for_llm(
        result.text_content,
        os.path.basename(pdf_path),
        total_pages=total_pages,
    )

    with open(out_md, "w", encoding="utf-8") as f:
        f.write(processed)

    elapsed = time.time() - start
    size_kb = os.path.getsize(out_md) / 1024

    print(f"Done in {elapsed:.1f}s")
    print(f"Output: {out_md}")
    print(f"Size: {size_kb:.1f} KB")

    return out_md


# ---------------------------------------------------------------------------
# Conversion: marker-pdf (scanned PDFs)
# ---------------------------------------------------------------------------

def find_marker_single():
    """Locate the marker_single executable."""
    # Check known path first
    known_path = os.path.join(
        os.environ.get("APPDATA", ""),
        "Python", "Python312", "Scripts", "marker_single.exe"
    )
    if os.path.isfile(known_path):
        return known_path

    # Try system PATH
    import shutil
    found = shutil.which("marker_single")
    if found:
        return found

    return None


def convert_with_marker(pdf_path, output_dir, page_range=None):
    """Convert a scanned PDF using marker-pdf with GPU acceleration."""
    marker_path = find_marker_single()
    if not marker_path:
        print("ERROR: marker_single not found.")
        print("FIX: pip install marker-pdf")
        sys.exit(1)

    # Verify CUDA is available
    try:
        import torch
        if not torch.cuda.is_available():
            print("WARNING: CUDA not available. marker-pdf will use CPU (much slower).")
            device = "cpu"
        else:
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            print(f"GPU detected: {gpu_name}")
    except ImportError:
        print("WARNING: PyTorch not installed. marker-pdf may not work.")
        device = "cpu"

    print(f"Converting with marker-pdf (device={device})...")
    start = time.time()

    cmd = [
        marker_path,
        pdf_path,
        "--output_dir", output_dir,
        "--output_format", "markdown",
    ]
    if page_range:
        cmd.extend(["--page_range", page_range])

    env = os.environ.copy()
    env["TORCH_DEVICE"] = device

    process = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if process.returncode != 0:
        print(f"ERROR: marker-pdf failed with exit code {process.returncode}")
        if process.stderr:
            print(f"stderr: {process.stderr[:500]}")
        sys.exit(1)

    elapsed = time.time() - start

    # Find the output file
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    expected_dir = os.path.join(output_dir, basename)
    expected_md = os.path.join(expected_dir, f"{basename}.md")

    if os.path.isfile(expected_md):
        size_kb = os.path.getsize(expected_md) / 1024
        print(f"Done in {elapsed:.1f}s")
        print(f"Output: {expected_md}")
        print(f"Size: {size_kb:.1f} KB")
        return expected_md
    else:
        # Search for any .md file in the output dir
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith(".md"):
                    md_path = os.path.join(root, f)
                    size_kb = os.path.getsize(md_path) / 1024
                    print(f"Done in {elapsed:.1f}s")
                    print(f"Output: {md_path}")
                    print(f"Size: {size_kb:.1f} KB")
                    return md_path

        print(f"WARNING: Conversion completed but .md file not found in {output_dir}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Hybrid PDF-to-Markdown converter (MarkItDown + marker-pdf)"
    )
    parser.add_argument("--source", required=True, help="Path to the source PDF file")
    parser.add_argument("--output-dir", required=True, help="Directory to save the output")
    parser.add_argument("--force-ocr", action="store_true",
                        help="Force using marker-pdf (GPU OCR) regardless of PDF type")
    parser.add_argument("--force-markitdown", action="store_true",
                        help="Force using MarkItDown regardless of PDF type")
    parser.add_argument("--page-range", default=None,
                        help="Page range for marker-pdf (e.g., '0,5-10,20')")

    args = parser.parse_args()

    # Validate source
    if not os.path.isfile(args.source):
        print(f"ERROR: Source file not found: {args.source}")
        sys.exit(1)

    # Ensure output dir exists
    os.makedirs(args.output_dir, exist_ok=True)

    pdf_name = os.path.basename(args.source)
    print(f"{'='*60}")
    print(f"  PDF-to-Markdown Hybrid Converter")
    print(f"  Source: {pdf_name}")
    print(f"{'='*60}")
    print()

    # Determine conversion method
    if args.force_ocr:
        method = "marker-pdf"
        print(f"Method: marker-pdf (forced via --force-ocr)")
    elif args.force_markitdown:
        method = "markitdown"
        print(f"Method: MarkItDown (forced via --force-markitdown)")
    else:
        # Auto-detect
        print("Detecting PDF type...")
        pdf_type, details = detect_pdf_type(args.source)
        print(f"  Type: {pdf_type}")
        print(f"  Total pages: {details['total_pages']}")
        print(f"  Reason: {details['reason']}")
        print()

        if pdf_type == "digital":
            method = "markitdown"
            print(f"Method: MarkItDown (fast, text extraction)")
        else:
            method = "marker-pdf"
            print(f"Method: marker-pdf (GPU OCR for scanned pages)")

    print()

    # Execute conversion
    if method == "markitdown":
        result_path = convert_with_markitdown(args.source, args.output_dir)
    else:
        result_path = convert_with_marker(args.source, args.output_dir, args.page_range)

    print()
    print(f"{'='*60}")
    if result_path:
        print(f"  Conversion complete!")
        print(f"  Output: {result_path}")
    else:
        print(f"  Conversion finished but output file not found.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
