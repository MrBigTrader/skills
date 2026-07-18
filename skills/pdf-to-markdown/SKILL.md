---
name: pdf-to-markdown
description: >
  Convert PDF files to high-quality Markdown optimized for LLM consumption, using a smart hybrid approach.
  For digital PDFs (with embedded text), it uses Microsoft MarkItDown for fast CPU-based extraction.
  For scanned PDFs (image-only), it uses marker-pdf with NVIDIA GPU acceleration (CUDA) for OCR.
  Use this skill whenever the user wants to convert a PDF to markdown, extract structured text from a PDF
  for use with LLMs, process scanned or digital PDFs into readable markdown, or mentions markitdown /
  marker-pdf / marker for document conversion. Also use when the user asks to OCR a PDF, extract text
  preserving tables and formatting, or prepare PDF content for AI/LLM consumption. This skill handles
  the full pipeline: detecting PDF type, choosing the best tool, and saving structured LLM-ready output.
---

# PDF to Markdown Converter (Hybrid: MarkItDown + marker-pdf)

Convert PDF documents to structured Markdown **optimized for LLM consumption**, using a smart hybrid
approach that automatically picks the best tool for each PDF:

| PDF Type | Tool | Speed | How |
|---|---|---|---|
| **Digital** (embedded text) | MarkItDown (Microsoft) | ⚡ Fast (~1s) | CPU text extraction |
| **Scanned** (image-only) | marker-pdf | 🐢 Slower (~6-10s/page) | GPU OCR via CUDA |

The output is post-processed to be easily understood by LLMs, with clear structure, metadata headers,
and clean formatting.

## Prerequisites

The following must be installed on the system:

- **Python 3.10+**
- **pdfplumber** (`pip install pdfplumber`) — used for PDF type detection
- **markitdown** (`pip install markitdown[pdf]`) — fast conversion of digital PDFs
- **marker-pdf** (`pip install marker-pdf`) — GPU-accelerated OCR for scanned PDFs
- **PyTorch with CUDA support** — required only for scanned PDFs

Run the verification script to check all dependencies:

```powershell
python "<skill-directory>/scripts/verify_cuda.py"
```

## Workflow

### Step 1: Gather information from the user

Before starting, confirm these details with the user:

1. **Source PDF path** — the full path to the PDF file to convert.
2. **Output directory** — where the markdown file should be saved. Always ask the user where they want
   the output saved. Do not assume a default directory.
3. **Page range** (optional) — if the user only wants specific pages (only applies to marker-pdf).
4. **Force a specific tool** (optional) — the user may want to force MarkItDown or marker-pdf.

### Step 2: Verify dependencies

Run the verification script:

```powershell
python "<skill-directory>/scripts/verify_cuda.py"
```

If there are missing dependencies, follow the fix instructions provided by the script.
Note: GPU/marker-pdf issues only affect scanned PDFs. Digital PDFs will still convert fine.

### Step 3: Run the conversion

Use the hybrid conversion script. It will auto-detect the PDF type and choose the best tool:

```powershell
python "<skill-directory>/scripts/convert_pdf.py" --source "<source_pdf_path>" --output-dir "<output_directory>"
```

**Optional flags:**

| Flag | Purpose |
|---|---|
| `--force-ocr` | Force marker-pdf (GPU OCR) even for digital PDFs |
| `--force-markitdown` | Force MarkItDown even for scanned PDFs |
| `--page-range "0,5-10,20"` | Process specific pages only (marker-pdf only) |

**Examples:**

```powershell
# Auto-detect (recommended)
python "<skill-directory>/scripts/convert_pdf.py" --source "C:\docs\bible.pdf" --output-dir "C:\output"

# Force GPU OCR for a difficult PDF
python "<skill-directory>/scripts/convert_pdf.py" --source "C:\docs\scan.pdf" --output-dir "C:\output" --force-ocr

# Force MarkItDown for a known digital PDF
python "<skill-directory>/scripts/convert_pdf.py" --source "C:\docs\report.pdf" --output-dir "C:\output" --force-markitdown
```

### Step 4: Monitor progress

- **MarkItDown conversions** complete almost instantly (1-5 seconds for most PDFs).
- **marker-pdf conversions** run as a background task and go through several stages:
  1. Recognizing Layout
  2. Running OCR Error Detection
  3. Detecting bboxes
  4. Recognizing Text
  5. Recognizing tables

For marker-pdf, on a GTX 1650 Ti (4GB VRAM), expect roughly 6-10 seconds per page.

### Step 5: Verify the output

Once the conversion completes, the output is saved as:

```
<output_directory>/
└── <filename>/
    └── <filename>.md          ← The converted Markdown file (LLM-optimized)
```

When using marker-pdf, additional files may be present:

```
<output_directory>/
└── <filename>/
    ├── <filename>.md
    ├── <filename>_meta.json   ← Conversion metadata
    └── _page_X_Picture_Y.jpeg ← Extracted images
```

Open the `.md` file and verify:
- The metadata header is present (source file, page count)
- Headings are properly structured
- Tables are rendered correctly in Markdown format
- No major OCR errors in the text
- Content flows logically for an LLM reader

Report the file path and size to the user so they can review the result.

## LLM-Optimized Output

The Markdown output from MarkItDown is post-processed to be **easily understood by LLMs**:

- **Metadata header**: includes source filename and page count
- **Clean structure**: headings, paragraphs, and lists are properly formatted
- **Normalized whitespace**: no excessive blank lines or trailing spaces
- **Table preservation**: tables are converted to proper Markdown table syntax
- **UTF-8 encoding**: full support for accented characters and special symbols

## Performance Reference

| Scenario | Tool | Time (approx) |
|---|---|---|
| 10-page digital PDF | MarkItDown | ~1 second |
| 50-page digital PDF | MarkItDown | ~2-3 seconds |
| 200-page digital PDF | MarkItDown | ~5-10 seconds |
| 10-page scanned PDF | marker-pdf (GPU) | ~1-2 minutes |
| 50-page scanned PDF | marker-pdf (GPU) | ~5-10 minutes |
| 200-page scanned PDF | marker-pdf (GPU) | ~30-40 minutes |

## Troubleshooting

| Problem | Solution |
|---|---|
| MarkItDown produces empty output | PDF may be scanned. Try `--force-ocr` to use marker-pdf |
| marker-pdf is very slow | Check GPU usage with `nvidia-smi`. If GPU-Util is 0%, CUDA may not be configured |
| `torch.cuda.is_available()` returns `False` | Reinstall PyTorch: `pip install torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 --force-reinstall` |
| marker-pdf dependency conflict with torch | Edit `pyproject.toml` in marker-repo: change `torch = "^2.7.0"` to `torch = ">=2.0.0"` |
| Out of GPU memory | Process fewer pages with `--page-range`, or close GPU-intensive apps |
| `marker_single` not found | Check: `pip show marker-pdf`. CLI may be at `C:\Users\stgan\AppData\Roaming\Python\Python312\Scripts\marker_single.exe` |
| markitdown not found | Install: `pip install markitdown[pdf]` |
| Encoding issues (garbled text) | Ensure output is saved as UTF-8. The script handles this automatically |
