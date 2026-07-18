"""Verify that all dependencies are available for the hybrid PDF-to-Markdown converter.

Checks:
  1. pdfplumber (required for PDF type detection)
  2. markitdown (required for digital PDF conversion)
  3. PyTorch + CUDA (required for scanned PDF conversion via marker-pdf)
  4. marker_single CLI (required for scanned PDF conversion)

Exits with code 0 if everything is ready, or code 1 if there's a problem.
"""
import sys
import os
import shutil


def check_pdfplumber():
    try:
        import pdfplumber
        print(f"  pdfplumber: {pdfplumber.__version__}")
        return True
    except ImportError:
        print("  pdfplumber: NOT INSTALLED")
        print("    FIX: pip install pdfplumber")
        return False


def check_markitdown():
    try:
        from markitdown import MarkItDown
        try:
            from markitdown.__about__ import __version__
            print(f"  markitdown: {__version__}")
        except ImportError:
            print("  markitdown: installed (version unknown)")
        return True
    except ImportError:
        print("  markitdown: NOT INSTALLED")
        print("    FIX: pip install markitdown[pdf]")
        return False


def check_pytorch_cuda():
    try:
        import torch
    except ImportError:
        print("  PyTorch: NOT INSTALLED")
        print("    FIX: pip install torch --index-url https://download.pytorch.org/whl/cu121")
        return False

    version = torch.__version__
    print(f"  PyTorch: {version}")

    if "+cpu" in version:
        print("  CUDA: NO (CPU-only PyTorch build)")
        print("    FIX: pip install torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 --force-reinstall")
        return False

    if not torch.cuda.is_available():
        print("  CUDA: NOT AVAILABLE")
        print("    Possible causes: no NVIDIA GPU, outdated drivers, CUDA mismatch")
        return False

    device_count = torch.cuda.device_count()
    print(f"  CUDA: available ({device_count} device(s))")
    for i in range(device_count):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_memory / (1024**3)
        print(f"    GPU {i}: {name} ({mem:.1f} GB)")

    return True


def check_marker_single():
    # Check known path
    known_path = os.path.join(
        os.environ.get("APPDATA", ""),
        "Python", "Python312", "Scripts", "marker_single.exe"
    )
    if os.path.isfile(known_path):
        print(f"  marker_single: {known_path}")
        return True

    # Check system PATH
    found = shutil.which("marker_single")
    if found:
        print(f"  marker_single: {found}")
        return True

    print("  marker_single: NOT FOUND")
    print("    FIX: pip install marker-pdf")
    return False


def main():
    print("=" * 50)
    print("  PDF-to-Markdown Dependency Check")
    print("=" * 50)
    print()

    all_ok = True

    # Required for all conversions
    print("[Required] PDF Detection & Text Extraction:")
    if not check_pdfplumber():
        all_ok = False
    print()

    # Required for digital PDFs
    print("[Required] Digital PDF Conversion (MarkItDown):")
    if not check_markitdown():
        all_ok = False
    print()

    # Required for scanned PDFs
    print("[Required for OCR] Scanned PDF Conversion (marker-pdf):")
    cuda_ok = check_pytorch_cuda()
    marker_ok = check_marker_single()
    if not cuda_ok or not marker_ok:
        print()
        print("  NOTE: GPU/marker-pdf issues only affect scanned PDFs.")
        print("  Digital PDFs with embedded text will still convert fine via MarkItDown.")
    print()

    # Summary
    print("=" * 50)
    if all_ok and cuda_ok and marker_ok:
        print("  All checks passed. Full hybrid conversion ready.")
        print("  - Digital PDFs: MarkItDown (CPU, fast)")
        print("  - Scanned PDFs: marker-pdf (GPU OCR)")
    elif all_ok:
        print("  Partial: MarkItDown ready for digital PDFs.")
        print("  GPU/marker-pdf not fully configured for scanned PDFs.")
    else:
        print("  Some required dependencies are missing. See above for fixes.")
    print("=" * 50)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
