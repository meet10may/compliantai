"""
FDA 510(k) Predicate Database Expander

This script expands your predicate database by:
1. Parsing the FDA pmn96cur.txt database to find relevant cleared devices
2. Downloading 510(k) summary PDFs from the FDA website
3. Extracting "Indications for Use" text from PDFs using AI
4. Building an expanded predicate_database.json

Usage:
    python expand_database.py --product-codes FMI,JKA,FPA --max-devices 50
    python expand_database.py --search "blood collection" --max-devices 30
    python expand_database.py --search "cardiac monitor" --product-codes DRT --max-devices 20

Requirements:
    pip install openai requests pymupdf tqdm

Notes:
    - FDA PDFs are publicly available at:
      https://www.accessdata.fda.gov/cdrh_docs/pdf[YY]/[KNUMBER].pdf
    - Not all K-numbers have downloadable PDFs
    - The script uses GPT-4.1 to extract IFU text from PDFs (more reliable than regex)
    - Rate-limits requests to FDA servers (1 req/sec)
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fda_expander")

# ── FDA PDF URL patterns ────────────────────────────────────────────────────
# FDA stores 510(k) summaries at predictable URLs based on K-number
# Pattern: https://www.accessdata.fda.gov/cdrh_docs/pdf[YY]/[KNUMBER].pdf
# Where YY is derived from the K-number (e.g., K213146 → pdf21)

def get_fda_pdf_url(k_number: str) -> str:
    """Construct the FDA PDF URL for a given K-number."""
    k_number = k_number.strip().upper()
    if k_number.startswith("K"):
        # Extract year digits: K21xxxx → 21, K05xxxx → 5
        year_part = k_number[1:3]  # first two digits after K
        year_int = int(year_part)

        # Determine folder: pdf, pdf1, pdf2, ... pdf25
        if year_int >= 96:
            # 1996-1999: K96xxxx-K99xxxx
            folder = f"pdf{year_part}"
        else:
            # 2000+: K00xxxx = pdf, K01xxxx = pdf1, etc.
            if year_int == 0:
                folder = "pdf"
            else:
                folder = f"pdf{year_int}"

        return f"https://www.accessdata.fda.gov/cdrh_docs/{folder}/{k_number}.pdf"
    return None


def download_pdf(url: str, output_path: Path, timeout: int = 30) -> bool:
    """Download a PDF from the FDA website."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (research tool for 510(k) analysis)"
        }
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
        if resp.status_code == 200 and "pdf" in resp.headers.get("content-type", "").lower():
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        else:
            logger.debug(f"PDF not available: {url} (status={resp.status_code})")
            return False
    except Exception as e:
        logger.debug(f"Download failed: {url} ({e})")
        return False


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        logger.warning(f"Failed to extract text from {pdf_path}: {e}")
        return ""


def extract_ifu_with_regex(text: str) -> str:
    """Try to extract Indications for Use section using regex patterns."""
    # Common patterns in FDA 510(k) PDFs
    patterns = [
        # Pattern 1: "Indications for Use" header followed by text
        r"(?:Indications?\s+for\s+Use[:\s]*\n)([\s\S]*?)(?:\n\s*(?:Device\s+Description|Technological\s+Characteristics|Predicate\s+Device|Substantial\s+Equivalence|Summary|IV\.|V\.|3\.|4\.))",
        # Pattern 2: After the IFU form header
        r"(?:Indications?\s+for\s+Use\s*\(Describe\))([\s\S]*?)(?:Type\s+of\s+Use|Prescription\s+Use|Over-The-Counter)",
        # Pattern 3: Simpler extraction
        r"(?:indications?\s+for\s+use[:\s]*)([\s\S]{100,2000}?)(?:\n\s*\n\s*\n)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # Clean up
            extracted = re.sub(r"\s+", " ", extracted)
            extracted = extracted.strip()
            if len(extracted) > 50:  # Minimum viable length
                return extracted

    return ""


def extract_ifu_with_ai(text: str, api_key: str, device_name: str = "") -> str:
    """Use GPT-4.1 to extract the Indications for Use from PDF text."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    # Truncate very long documents
    if len(text) > 15000:
        text = text[:15000]

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0,
            max_tokens=800,
            messages=[
                {
                    "role": "system",
                    "content": "You are a regulatory document parser. Extract the exact 'Indications for Use' section from the 510(k) document text provided. Return ONLY the indications text, nothing else. If you cannot find it, respond with 'NOT_FOUND'.",
                },
                {
                    "role": "user",
                    "content": f"Extract the Indications for Use text from this 510(k) document:\n\n{text}",
                },
            ],
        )
        result = response.choices[0].message.content.strip()
        if result == "NOT_FOUND" or len(result) < 30:
            return ""
        return result
    except Exception as e:
        logger.warning(f"AI extraction failed: {e}")
        return ""


def parse_fda_database(
    txt_path: str,
    product_codes: list[str] = None,
    search_term: str = None,
    decision: str = "SESE",  # Substantially Equivalent
    max_results: int = 100,
) -> list[dict]:
    """Parse the FDA pmn96cur.txt file and filter for relevant devices."""
    results = []

    with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            # Filter by decision (cleared only)
            if decision and row.get("DECISION", "").strip() != decision:
                continue

            # Filter by product code
            pc = row.get("PRODUCTCODE", "").strip()
            if product_codes and pc not in product_codes:
                continue

            # Filter by search term in device name
            device_name = row.get("DEVICENAME", "").strip()
            if search_term and search_term.lower() not in device_name.lower():
                continue

            # Must have Summary available
            if row.get("STATEORSUMM", "").strip() != "Summary":
                continue

            k_number = row.get("KNUMBER", "").strip()
            if not k_number.startswith("K"):
                continue

            results.append({
                "k_number": k_number,
                "device_name": device_name,
                "product_code": pc,
                "applicant": row.get("APPLICANT", "").strip(),
                "decision_date": row.get("DECISIONDATE", "").strip(),
                "advisory_committee": row.get("REVIEWADVISECOMM", "").strip(),
                "type": row.get("TYPE", "").strip(),
            })

            if len(results) >= max_results:
                break

    # Sort by decision date (most recent first)
    results.sort(key=lambda x: x.get("decision_date", ""), reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Expand IndiClear predicate database from FDA data")
    parser.add_argument("--fda-file", default="pmn96cur.txt", help="Path to FDA pmn96cur.txt file")
    parser.add_argument("--product-codes", type=str, default=None, help="Comma-separated product codes (e.g., FMI,JKA,FPA)")
    parser.add_argument("--search", type=str, default=None, help="Search term for device name")
    parser.add_argument("--max-devices", type=int, default=50, help="Maximum devices to process")
    parser.add_argument("--api-key", type=str, default=None, help="OpenAI API key (or set OPENAI_API_KEY env)")
    parser.add_argument("--output", type=str, default="predicate_database_expanded.json", help="Output JSON file")
    parser.add_argument("--pdf-dir", type=str, default="pdfs", help="Directory to store downloaded PDFs")
    parser.add_argument("--existing-db", type=str, default=None, help="Existing predicate DB to merge with")
    parser.add_argument("--skip-download", action="store_true", help="Skip PDF download, use existing PDFs")
    parser.add_argument("--use-ai", action="store_true", help="Use GPT-4.1 for extraction (more accurate, costs ~$0.01/doc)")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if args.use_ai and not api_key:
        print("ERROR: --use-ai requires an OpenAI API key (--api-key or OPENAI_API_KEY env)")
        sys.exit(1)

    product_codes = args.product_codes.split(",") if args.product_codes else None

    if not product_codes and not args.search:
        print("ERROR: Provide --product-codes and/or --search to filter devices")
        print("Example: python expand_database.py --search 'blood collection' --product-codes FMI,JKA")
        sys.exit(1)

    # Step 1: Parse FDA database
    logger.info(f"Parsing FDA database: {args.fda_file}")
    devices = parse_fda_database(
        args.fda_file,
        product_codes=product_codes,
        search_term=args.search,
        max_results=args.max_devices,
    )
    logger.info(f"Found {len(devices)} matching cleared devices")

    if not devices:
        print("No matching devices found. Try different product codes or search terms.")
        sys.exit(0)

    # Step 2: Download PDFs
    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(exist_ok=True)

    successful_extractions = []

    for i, device in enumerate(devices):
        k_number = device["k_number"]
        pdf_path = pdf_dir / f"{k_number}.pdf"

        logger.info(f"[{i+1}/{len(devices)}] Processing {k_number}: {device['device_name'][:60]}")

        # Download PDF if not exists
        if not args.skip_download and not pdf_path.exists():
            url = get_fda_pdf_url(k_number)
            if url:
                logger.info(f"  Downloading: {url}")
                success = download_pdf(url, pdf_path)
                if not success:
                    logger.warning(f"  PDF not available for {k_number}")
                    continue
                time.sleep(1)  # Rate limiting - be nice to FDA servers
            else:
                continue
        elif not pdf_path.exists():
            logger.warning(f"  PDF not found: {pdf_path}")
            continue

        # Extract text
        raw_text = extract_text_from_pdf(pdf_path)
        if not raw_text:
            logger.warning(f"  Could not extract text from PDF")
            continue

        # Extract Indications for Use
        ifu_text = ""

        # Try regex first (free)
        ifu_text = extract_ifu_with_regex(raw_text)

        # Fall back to AI extraction if regex failed and --use-ai is set
        if not ifu_text and args.use_ai:
            logger.info(f"  Regex failed, using AI extraction...")
            ifu_text = extract_ifu_with_ai(raw_text, api_key, device["device_name"])

        if ifu_text:
            logger.info(f"  ✓ Extracted IFU ({len(ifu_text)} chars)")
            successful_extractions.append({
                "510(k) Number": k_number,
                "Device Name": device["device_name"],
                "Indications for Use": ifu_text,
                "Filename": f"{k_number}.pdf",
                "Product Code": device["product_code"],
                "Applicant": device["applicant"],
                "Decision Date": device["decision_date"],
                "Advisory Committee": device["advisory_committee"],
            })
        else:
            logger.warning(f"  ✗ Could not extract IFU")

    # Step 3: Merge with existing database
    if args.existing_db and Path(args.existing_db).exists():
        logger.info(f"Merging with existing database: {args.existing_db}")
        with open(args.existing_db) as f:
            existing = json.load(f)
        # Filter valid existing entries
        existing_valid = [e for e in existing if e.get("Indications for Use")]
        existing_knums = {e.get("510(k) Number") for e in existing_valid}

        # Add new entries that don't already exist
        new_count = 0
        for entry in successful_extractions:
            if entry["510(k) Number"] not in existing_knums:
                existing_valid.append(entry)
                new_count += 1

        successful_extractions = existing_valid
        logger.info(f"Merged: {new_count} new + {len(existing_valid) - new_count} existing = {len(successful_extractions)} total")

    # Step 4: Save
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(successful_extractions, f, indent=2)

    logger.info(f"")
    logger.info(f"═══════════════════════════════════════════")
    logger.info(f"  Database expansion complete!")
    logger.info(f"  Devices processed: {len(devices)}")
    logger.info(f"  Successful extractions: {len(successful_extractions)}")
    logger.info(f"  Output: {output_path}")
    logger.info(f"═══════════════════════════════════════════")
    logger.info(f"")
    logger.info(f"Next steps:")
    logger.info(f"  1. Review the extracted text for accuracy")
    logger.info(f"  2. Copy to data/predicate_database.json")
    logger.info(f"  3. Delete data/embeddings_cache.npz and data/faiss_index.bin")
    logger.info(f"  4. Restart the backend — it will re-embed automatically")


if __name__ == "__main__":
    main()
