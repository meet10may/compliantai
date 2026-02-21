"""
FDA 510(k) Data Pipeline — IndiClear Database Builder

Builds the predicate database for IndiClear by:
1. Parsing ALL 98K records from pmn96cur.txt into a master index
2. Downloading 510(k) summary PDFs from FDA (page 1 only — IFU is always there)
3. Extracting "Indications for Use" text using a multi-strategy approach
4. Outputting a clean predicate_database.json

Architecture Decision: This is an OFFLINE pipeline, separate from the web app.
Run it once to build your dataset, then the web app reads from the output.

STRATEGY FOR IFU EXTRACTION (in order of preference):
  1. PyMuPDF page-1 text → regex extraction (free, fast, ~60% success rate)
  2. PyMuPDF page-1 + page-2 text → regex extraction (catches overflow cases)
  3. GPT-4.1-mini extraction from page-1 text (cheap, ~95% success rate, ~$0.001/doc)
  
  We do NOT read the full PDF — IFU is always on page 1 (or occasionally page 2).

SCALE:
  - 98K total records, ~84K have Summary PDFs
  - At 1 req/sec: ~23 hours to download all
  - Recommended: run in batches (--batch-size 500 --batch-offset 0)
  - Pipeline is fully resumable — skips already-processed K-numbers

Usage:
    # Process everything (will take ~24 hours for downloads)
    python build_database.py --fda-file pmn96cur.txt --api-key sk-...

    # Process in batches of 1000
    python build_database.py --fda-file pmn96cur.txt --batch-size 1000 --batch-offset 0
    python build_database.py --fda-file pmn96cur.txt --batch-size 1000 --batch-offset 1000

    # Only recent devices (2020+)
    python build_database.py --fda-file pmn96cur.txt --min-year 2020

    # Only specific product codes (for faster targeted runs)
    python build_database.py --fda-file pmn96cur.txt --product-codes FMI,JKA,FPA,GIM

    # Dry run — just parse the FDA file, no downloads
    python build_database.py --fda-file pmn96cur.txt --dry-run

Requirements:
    pip install -r requirements.txt
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import hashlib
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("build_database.log"),
    ],
)
logger = logging.getLogger("fda_pipeline")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Parse FDA Master File
# ═══════════════════════════════════════════════════════════════════════════════

def parse_fda_master_file(
    fda_file: str,
    min_year: int = None,
    product_codes: list[str] = None,
    cleared_only: bool = True,
) -> list[dict]:
    """
    Parse the entire pmn96cur.txt file into structured records.
    
    Args:
        fda_file: Path to pmn96cur.txt
        min_year: Only include devices cleared after this year (e.g., 2020)
        product_codes: If set, only include these product codes
        cleared_only: If True, only include SESE (substantially equivalent) decisions
    
    Returns:
        List of device records sorted by decision date (newest first)
    """
    records = []
    skipped = {"no_k": 0, "not_cleared": 0, "no_summary": 0, "year_filter": 0, "code_filter": 0}

    with open(fda_file, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            k_number = row.get("KNUMBER", "").strip()

            # Must be a K-number (skip DEN numbers etc.)
            if not k_number.startswith("K"):
                skipped["no_k"] += 1
                continue

            # Filter by decision
            decision = row.get("DECISION", "").strip()
            if cleared_only and decision != "SESE":
                skipped["not_cleared"] += 1
                continue

            # Must have Summary (means PDF is available on FDA site)
            summary_status = row.get("STATEORSUMM", "").strip()
            if summary_status != "Summary":
                skipped["no_summary"] += 1
                continue

            # Parse decision date
            decision_date = row.get("DECISIONDATE", "").strip()
            decision_year = None
            if decision_date:
                try:
                    parts = decision_date.split("/")
                    decision_year = int(parts[-1]) if len(parts) == 3 else None
                except (ValueError, IndexError):
                    pass

            # Filter by year
            if min_year and decision_year and decision_year < min_year:
                skipped["year_filter"] += 1
                continue

            # Filter by product code
            product_code = row.get("PRODUCTCODE", "").strip()
            if product_codes and product_code not in product_codes:
                skipped["code_filter"] += 1
                continue

            device_name = row.get("DEVICENAME", "").strip()
            # Clean up device name (remove trailing \r etc.)
            device_name = device_name.replace("\r", "").replace("\n", " ").strip()

            records.append({
                "k_number": k_number,
                "device_name": device_name,
                "product_code": product_code,
                "applicant": row.get("APPLICANT", "").strip(),
                "decision_date": decision_date,
                "decision_year": decision_year,
                "advisory_committee": row.get("REVIEWADVISECOMM", "").strip(),
                "class_advisory_committee": row.get("CLASSADVISECOMM", "").strip(),
                "submission_type": row.get("TYPE", "").strip(),
            })

    # Sort newest first
    records.sort(key=lambda x: x.get("decision_date", ""), reverse=True)

    logger.info(f"Parsed {len(records)} eligible records from FDA file")
    logger.info(f"Skipped: {json.dumps(skipped)}")
    return records


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: Download PDFs
# ═══════════════════════════════════════════════════════════════════════════════

def get_fda_pdf_url(k_number: str) -> str:
    """
    Construct FDA PDF URL for a K-number.
    
    FDA stores PDFs at: https://www.accessdata.fda.gov/cdrh_docs/pdf{YY}/{K-number}.pdf
    where YY comes from the K-number digits.
    """
    year = k_number[1:3]  # e.g., 'K25xxxx' → '25'
    return f"https://www.accessdata.fda.gov/cdrh_docs/pdf{year}/{k_number}.pdf"


def download_pdf(k_number: str, pdf_dir: Path, timeout: int = 30) -> Path | None:
    """Download a single PDF. Returns path if successful, None if failed."""
    pdf_path = pdf_dir / f"{k_number}.pdf"

    # Skip if already downloaded
    if pdf_path.exists() and pdf_path.stat().st_size > 1000:
        return pdf_path

    url = get_fda_pdf_url(k_number)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (IndiClear research tool)"}
        resp = requests.get(url, headers=headers, timeout=timeout)

        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "").lower()
            if "pdf" in content_type or len(resp.content) > 5000:
                with open(pdf_path, "wb") as f:
                    f.write(resp.content)
                return pdf_path
        return None
    except Exception:
        return None


def download_batch(
    records: list[dict],
    pdf_dir: Path,
    rate_limit: float = 1.0,
    max_workers: int = 1,
) -> dict[str, Path]:
    """
    Download PDFs for a batch of records.
    Returns dict mapping k_number → pdf_path for successful downloads.
    """
    pdf_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    already_existed = 0

    for i, record in enumerate(records):
        k_number = record["k_number"]
        pdf_path = pdf_dir / f"{k_number}.pdf"

        # Skip already downloaded
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            results[k_number] = pdf_path
            already_existed += 1
            continue

        path = download_pdf(k_number, pdf_dir)
        if path:
            results[k_number] = path
            if (i + 1) % 100 == 0:
                logger.info(f"  Downloaded {i + 1}/{len(records)} ({len(results)} successful)")
        
        # Rate limit
        time.sleep(rate_limit)

    logger.info(
        f"Download complete: {len(results)}/{len(records)} successful "
        f"({already_existed} already cached)"
    )
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Extract Indications for Use
# ═══════════════════════════════════════════════════════════════════════════════

def extract_page_text(pdf_path: Path, max_pages: int = 2) -> str:
    """Extract text from first N pages of a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(pdf_path))
        text = ""
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text += page.get_text() + "\n"
        doc.close()
        return text.strip()
    except Exception as e:
        logger.debug(f"PyMuPDF failed for {pdf_path}: {e}")
        return ""


def extract_ifu_regex(text: str) -> str:
    """
    Extract Indications for Use using regex patterns.
    
    The FDA IFU form has a very predictable layout:
    - "Indications for Use (Describe)" header
    - The actual IFU text
    - Then either "Type of Use" or "Prescription Use" / "Over-The-Counter Use" checkboxes
    
    We try multiple patterns from most specific to most general.
    """
    if not text or len(text) < 50:
        return ""

    # Clean up text
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    patterns = [
        # Pattern 1: Standard FDA IFU form — "Indications for Use (Describe)" to "Type of Use"
        r"Indications\s+for\s+Use\s*\(?Describe\)?\s*[:\-]?\s*\n([\s\S]*?)(?=\n\s*(?:Type\s+of\s+Use|Prescription\s+Use|Over[- ]The[- ]Counter))",

        # Pattern 2: "Indications for Use" followed by content, ending at common next-sections
        r"(?:Indications?\s+for\s+Use)[:\s]*\n([\s\S]*?)(?=\n\s*(?:Type\s+of\s+Use|Prescription\s+Use|Over[- ]The[- ]Counter|Device\s+Description|Technological\s+Characteristics|Predicate\s+Device|510\s*\(\s*k\s*\)\s*Summary|Substantial\s+Equivalence|II\.\s|III\.\s|IV\.\s|V\.\s))",

        # Pattern 3: After "510(k) Number" form fields, capture between "Indications" and next form element
        r"Indications?\s+for\s+Use[\s\S]{0,30}?\n([\s\S]{50,3000}?)(?=\n\s*(?:Type\s+of\s+Use|Prescription|Over[- ]the[- ]Counter|Page\s+\d|Form\s+FDA|Attachment))",

        # Pattern 4: Most permissive — just grab text after "Indications for Use"
        r"Indications?\s+for\s+Use[^a-zA-Z]{0,20}\n([\s\S]{50,2000}?)(?:\n\s*\n\s*\n|\n\s*(?:Prescription|Type\s+of|Over[- ]the))",
    ]

    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # Clean up extracted text
            extracted = re.sub(r"\n+", " ", extracted)  # Join lines
            extracted = re.sub(r"\s{2,}", " ", extracted)  # Collapse whitespace
            extracted = extracted.strip()

            # Remove common artifacts
            artifacts = [
                r"^[\s\-–—]+",  # Leading dashes
                r"Form FDA 3881.*$",  # Form number
                r"Page \d+.*$",  # Page numbers
                r"Attachment.*$",  # Attachment references
                r"See [Aa]ttach.*$",
                r"^\d+\s*$",  # Standalone numbers
            ]
            for artifact in artifacts:
                extracted = re.sub(artifact, "", extracted, flags=re.MULTILINE).strip()

            # Minimum quality check
            if len(extracted) > 40 and any(
                kw in extracted.lower()
                for kw in ["intended", "indicated", "used for", "designed for", "use with", "use in"]
            ):
                return extracted

    return ""


def extract_ifu_with_ai(text: str, api_key: str) -> str:
    """
    Use GPT-4.1-mini to extract IFU from page text.
    Cost: ~$0.0005 per document (very cheap).
    Much more reliable than regex for messy PDFs.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # Only send first ~4000 chars (page 1 + some of page 2)
    truncated = text[:4000] if len(text) > 4000 else text

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0,
            max_tokens=800,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a document parser specialized in FDA 510(k) submissions. "
                        "Extract the EXACT 'Indications for Use' text from the document. "
                        "This is typically found on the first page of the 510(k) summary. "
                        "Return ONLY the indications text — no headers, no form fields, no page numbers. "
                        "If the text says 'See attachment' or you cannot find a clear IFU section, "
                        "respond with exactly: NOT_FOUND"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Extract the Indications for Use from this 510(k) document page:\n\n{truncated}",
                },
            ],
        )
        result = response.choices[0].message.content.strip()

        if result == "NOT_FOUND" or len(result) < 30:
            return ""

        # Clean up any AI artifacts
        result = result.strip('"').strip("'").strip()
        if result.lower().startswith("indications for use"):
            # Remove the header if AI included it
            result = re.sub(r"^indications?\s+for\s+use[:\s]*", "", result, flags=re.IGNORECASE).strip()

        return result
    except Exception as e:
        logger.warning(f"AI extraction failed: {e}")
        return ""


def extract_ifu(
    pdf_path: Path,
    api_key: str = None,
    use_ai_fallback: bool = True,
) -> tuple[str, str]:
    """
    Multi-strategy IFU extraction.
    
    Returns:
        (ifu_text, extraction_method) — method is 'regex', 'ai', or 'failed'
    """
    # Strategy 1: Page 1 regex
    page1_text = extract_page_text(pdf_path, max_pages=1)
    if page1_text:
        ifu = extract_ifu_regex(page1_text)
        if ifu:
            return ifu, "regex_page1"

    # Strategy 2: Page 1+2 regex (sometimes IFU overflows to page 2)
    page12_text = extract_page_text(pdf_path, max_pages=2)
    if page12_text and len(page12_text) > len(page1_text):
        ifu = extract_ifu_regex(page12_text)
        if ifu:
            return ifu, "regex_page12"

    # Strategy 3: AI extraction from page 1 (fallback)
    if use_ai_fallback and api_key and page1_text:
        ifu = extract_ifu_with_ai(page1_text, api_key)
        if ifu:
            return ifu, "ai_page1"

    # Strategy 4: AI extraction from pages 1+2
    if use_ai_fallback and api_key and page12_text:
        ifu = extract_ifu_with_ai(page12_text, api_key)
        if ifu:
            return ifu, "ai_page12"

    return "", "failed"


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Build Output Database
# ═══════════════════════════════════════════════════════════════════════════════

def build_database(
    records: list[dict],
    downloaded: dict[str, Path],
    api_key: str = None,
    use_ai: bool = True,
    progress_file: str = "extraction_progress.json",
) -> list[dict]:
    """
    Extract IFU from all downloaded PDFs and build the predicate database.
    Saves progress incrementally so you can resume if interrupted.
    """
    output = []
    stats = {"regex_page1": 0, "regex_page12": 0, "ai_page1": 0, "ai_page12": 0, "failed": 0, "skipped": 0}

    # Load progress if resuming
    progress_path = Path(progress_file)
    processed_knums = set()
    if progress_path.exists():
        with open(progress_path) as f:
            progress = json.load(f)
            output = progress.get("results", [])
            processed_knums = {r["510(k) Number"] for r in output}
            logger.info(f"Resuming from progress file: {len(processed_knums)} already processed")

    for i, record in enumerate(records):
        k_number = record["k_number"]

        # Skip already processed
        if k_number in processed_knums:
            stats["skipped"] += 1
            continue

        # Skip if no PDF
        if k_number not in downloaded:
            continue

        pdf_path = downloaded[k_number]
        ifu_text, method = extract_ifu(pdf_path, api_key=api_key, use_ai_fallback=use_ai)
        stats[method] += 1

        if ifu_text:
            entry = {
                "510(k) Number": k_number,
                "Device Name": record["device_name"],
                "Indications for Use": ifu_text,
                "Filename": f"{k_number}.pdf",
                "Product Code": record.get("product_code", ""),
                "Applicant": record.get("applicant", ""),
                "Decision Date": record.get("decision_date", ""),
                "Advisory Committee": record.get("advisory_committee", ""),
                "Extraction Method": method,
            }
            output.append(entry)

        # Progress logging
        if (i + 1) % 50 == 0:
            success = len(output)
            logger.info(
                f"  Progress: {i + 1}/{len(records)} processed | "
                f"{success} extracted | Methods: {json.dumps({k:v for k,v in stats.items() if v > 0})}"
            )

        # Save progress every 100 records
        if (i + 1) % 100 == 0:
            with open(progress_path, "w") as f:
                json.dump({"results": output, "stats": stats}, f)

    # Final save
    with open(progress_path, "w") as f:
        json.dump({"results": output, "stats": stats}, f)

    return output


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5: Merge with Existing Database
# ═══════════════════════════════════════════════════════════════════════════════

def merge_databases(new_entries: list[dict], existing_file: str = None) -> list[dict]:
    """Merge new extractions with an existing predicate database."""
    if not existing_file or not Path(existing_file).exists():
        return new_entries

    with open(existing_file) as f:
        existing = json.load(f)

    # Index existing by K-number
    existing_map = {}
    for entry in existing:
        kn = entry.get("510(k) Number")
        if kn:
            existing_map[kn] = entry

    # Merge: new entries override existing (they may have better extractions)
    for entry in new_entries:
        kn = entry.get("510(k) Number")
        if kn:
            existing_map[kn] = entry

    merged = list(existing_map.values())
    # Filter out entries with no IFU text
    merged = [e for e in merged if e.get("Indications for Use")]

    logger.info(f"Merged database: {len(merged)} total entries")
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="IndiClear FDA Data Pipeline — Build predicate database from FDA 510(k) data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all 98K records (will take ~24 hours for downloads)
  python build_database.py --fda-file pmn96cur.txt --api-key sk-...

  # Process in batches
  python build_database.py --fda-file pmn96cur.txt --batch-size 500 --batch-offset 0
  python build_database.py --fda-file pmn96cur.txt --batch-size 500 --batch-offset 500

  # Only recent devices
  python build_database.py --fda-file pmn96cur.txt --min-year 2020 --api-key sk-...

  # Only specific product codes (blood collection)
  python build_database.py --fda-file pmn96cur.txt --product-codes FMI,JKA,FPA

  # Dry run — just see what would be processed
  python build_database.py --fda-file pmn96cur.txt --dry-run

  # Regex only (no AI, free)
  python build_database.py --fda-file pmn96cur.txt --no-ai
        """,
    )

    parser.add_argument("--fda-file", required=True, help="Path to pmn96cur.txt")
    parser.add_argument("--api-key", default=None, help="OpenAI API key (or OPENAI_API_KEY env)")
    parser.add_argument("--output", default="predicate_database.json", help="Output JSON file")
    parser.add_argument("--pdf-dir", default="pdfs", help="Directory for downloaded PDFs")
    parser.add_argument("--existing-db", default=None, help="Existing database to merge with")

    # Filtering
    parser.add_argument("--min-year", type=int, default=None, help="Only devices cleared after this year")
    parser.add_argument("--product-codes", default=None, help="Comma-separated product codes to filter")

    # Batching
    parser.add_argument("--batch-size", type=int, default=None, help="Process N records per run")
    parser.add_argument("--batch-offset", type=int, default=0, help="Start at offset N (for batching)")

    # Options
    parser.add_argument("--no-ai", action="store_true", help="Skip AI extraction (regex only, free)")
    parser.add_argument("--dry-run", action="store_true", help="Parse FDA file only, don't download")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between FDA requests")
    parser.add_argument("--skip-download", action="store_true", help="Skip download, process existing PDFs")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    use_ai = not args.no_ai and api_key is not None

    if not args.no_ai and not api_key:
        logger.warning("No API key provided. Using regex-only extraction (--no-ai). Pass --api-key for better results.")
        use_ai = False

    product_codes = args.product_codes.split(",") if args.product_codes else None

    # ── Step 1: Parse FDA file ──
    logger.info("=" * 60)
    logger.info("STEP 1: Parsing FDA master file")
    logger.info("=" * 60)

    records = parse_fda_master_file(
        args.fda_file,
        min_year=args.min_year,
        product_codes=product_codes,
    )

    # Apply batching
    if args.batch_size:
        total = len(records)
        records = records[args.batch_offset : args.batch_offset + args.batch_size]
        logger.info(f"Batch: offset={args.batch_offset}, size={args.batch_size} → {len(records)} records (from {total} total)")

    if args.dry_run:
        logger.info(f"\n{'='*60}")
        logger.info(f"DRY RUN SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total eligible records: {len(records)}")
        logger.info(f"Estimated download time: {len(records) * args.rate_limit / 3600:.1f} hours")
        logger.info(f"Estimated AI cost: ${len(records) * 0.0005:.2f} (if --api-key provided)")

        # Show sample
        logger.info(f"\nSample records:")
        for r in records[:10]:
            logger.info(f"  {r['k_number']} | {r['device_name'][:60]} | {r['product_code']} | {r['decision_date']}")

        # Show product code distribution
        code_dist = {}
        for r in records:
            pc = r.get("product_code", "?")
            code_dist[pc] = code_dist.get(pc, 0) + 1
        logger.info(f"\nTop product codes:")
        for code, count in sorted(code_dist.items(), key=lambda x: -x[1])[:20]:
            logger.info(f"  {code}: {count}")

        return

    # ── Step 2: Download PDFs ──
    logger.info(f"\n{'='*60}")
    logger.info("STEP 2: Downloading PDFs from FDA")
    logger.info(f"{'='*60}")

    pdf_dir = Path(args.pdf_dir)

    if args.skip_download:
        # Use existing PDFs
        downloaded = {}
        for record in records:
            pdf_path = pdf_dir / f"{record['k_number']}.pdf"
            if pdf_path.exists() and pdf_path.stat().st_size > 1000:
                downloaded[record["k_number"]] = pdf_path
        logger.info(f"Found {len(downloaded)} existing PDFs in {pdf_dir}")
    else:
        downloaded = download_batch(records, pdf_dir, rate_limit=args.rate_limit)

    # ── Step 3: Extract IFU text ──
    logger.info(f"\n{'='*60}")
    logger.info("STEP 3: Extracting Indications for Use")
    logger.info(f"{'='*60}")

    results = build_database(
        records,
        downloaded,
        api_key=api_key,
        use_ai=use_ai,
    )

    # ── Step 4: Merge and save ──
    logger.info(f"\n{'='*60}")
    logger.info("STEP 4: Building final database")
    logger.info(f"{'='*60}")

    final = merge_databases(results, args.existing_db)

    # Save output
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(final, f, indent=2)

    # ── Summary ──
    logger.info(f"\n{'='*60}")
    logger.info(f"  PIPELINE COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Records parsed:     {len(records)}")
    logger.info(f"  PDFs downloaded:    {len(downloaded)}")
    logger.info(f"  IFU extracted:      {len(final)}")
    logger.info(f"  Output saved to:    {output_path}")
    logger.info(f"{'='*60}")
    logger.info(f"")
    logger.info(f"NEXT STEPS:")
    logger.info(f"  1. Copy {output_path} → data/predicate_database.json")
    logger.info(f"  2. Delete data/embeddings_cache.npz and data/faiss_index.bin")
    logger.info(f"  3. Restart the backend — FAISS index rebuilds automatically")
    logger.info(f"")
    if args.batch_size and args.batch_offset + args.batch_size < len(records):
        next_offset = args.batch_offset + args.batch_size
        logger.info(f"  To continue with next batch:")
        logger.info(f"  python build_database.py --fda-file {args.fda_file} --batch-size {args.batch_size} --batch-offset {next_offset} --existing-db {output_path}")


if __name__ == "__main__":
    main()
