"""
CompliantAI - Backend API
RAG-powered Indications for Use Generator

Architecture:
1. Startup: Load predicate JSON → generate embeddings → build FAISS index
2. /api/retrieve: Embed user query → FAISS cosine search → return top-k predicates
3. /api/generate: Retrieve predicates → build prompt → GPT-4.1 → validate → return
4. /api/health: Health check + index stats
"""

import os
import json
import logging
import time
from typing import Optional
from pathlib import Path

import numpy as np
import faiss
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CompliantAI")

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CompliantAI API",
    description="RAG-powered FDA Indications for Use generator",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global State ─────────────────────────────────────────────────────────────
faiss_index: Optional[faiss.IndexFlatIP] = None
predicate_records: list[dict] = []
embedding_dim: int = 0

# ── Config ───────────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIM = 3072
GENERATION_MODEL = "gpt-4.1"
FALLBACK_MODEL = "gpt-4o"
GENERATION_TEMPERATURE = 0.2
GENERATION_MAX_TOKENS = 600
TOP_K_PREDICATES = 3

# Data paths — resolve relative to this file's location
_BACKEND_DIR = Path(__file__).parent.resolve()
_PROJECT_DIR = _BACKEND_DIR.parent
DATA_DIR = _PROJECT_DIR / "data"

if not DATA_DIR.exists():
    DATA_DIR = _BACKEND_DIR / "data"
if not DATA_DIR.exists():
    DATA_DIR = Path.cwd() / "data"
if not DATA_DIR.exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

PREDICATE_FILE = DATA_DIR / "predicate_database.json"
EMBEDDINGS_CACHE = DATA_DIR / "embeddings_cache.npz"
FAISS_INDEX_FILE = DATA_DIR / "faiss_index.bin"

logger.info(f"Data directory: {DATA_DIR}")
logger.info(f"Predicate file exists: {PREDICATE_FILE.exists()}")

BANNED_WORDS = [
    "best", "superior", "state-of-the-art", "breakthrough", "innovative",
    "advanced", "revolutionary", "cutting-edge", "world-class",
    "next-generation", "unparalleled", "groundbreaking", "leading",
    "premier", "ultimate",
]


# ── Pydantic Models ──────────────────────────────────────────────────────────

class DeviceInput(BaseModel):
    device_name: str
    device_category: str
    technology_type: str
    intended_use: str
    target_population: str
    clinical_setting: str
    user_type: str
    regulation_number: Optional[str] = ""
    product_code: Optional[str] = ""
    limitations: Optional[str] = ""
    predicate_k_number: Optional[str] = ""
    openai_api_key: str


class RetrieveRequest(BaseModel):
    device_input: DeviceInput
    top_k: int = TOP_K_PREDICATES


class GenerateRequest(BaseModel):
    device_input: DeviceInput
    top_k: int = TOP_K_PREDICATES


class PredicateResult(BaseModel):
    k_number: Optional[str]
    device_name: Optional[str]
    indications_text: Optional[str]
    filename: str
    similarity_score: float


class RetrieveResponse(BaseModel):
    predicates: list[PredicateResult]
    query_used: str


class GenerateResponse(BaseModel):
    indications_text: str
    predicates_used: list[PredicateResult]
    validation: dict
    model_used: str
    generation_time_ms: int


# ── Embedding Helpers ────────────────────────────────────────────────────────

def get_openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key)


def create_embedding(client: OpenAI, text: str) -> np.ndarray:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    vec = np.array(response.data[0].embedding, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def create_batch_embeddings(client: OpenAI, texts: list[str]) -> np.ndarray:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    vectors = np.array(
        [item.embedding for item in sorted(response.data, key=lambda x: x.index)],
        dtype=np.float32,
    )
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors = vectors / norms
    return vectors


def build_predicate_text(record: dict) -> str:
    parts = []
    if record.get("Device Name"):
        parts.append(f"Device: {record['Device Name']}")
    if record.get("Indications for Use"):
        parts.append(f"Indications: {record['Indications for Use']}")
    return " ".join(parts)


def build_query_text(device_input: DeviceInput) -> str:
    parts = [
        f"Device: {device_input.device_name}",
        f"Category: {device_input.device_category}",
        f"Technology: {device_input.technology_type}",
        f"Intended use: {device_input.intended_use}",
        f"Population: {device_input.target_population}",
        f"Setting: {device_input.clinical_setting}",
        f"User: {device_input.user_type}",
    ]
    if device_input.limitations:
        parts.append(f"Limitations: {device_input.limitations}")
    return " ".join(parts)


# ── FAISS Index Management ───────────────────────────────────────────────────

def build_faiss_index(vectors: np.ndarray) -> faiss.IndexFlatIP:
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)
    logger.info(f"FAISS index built: {index.ntotal} vectors, dim={dim}")
    return index


def search_index(index: faiss.IndexFlatIP, query_vec: np.ndarray, top_k: int = TOP_K_PREDICATES) -> list[tuple[int, float]]:
    query_vec = query_vec.reshape(1, -1)
    scores, indices = index.search(query_vec, top_k)
    results = []
    for idx, score in zip(indices[0], scores[0]):
        if idx >= 0:
            results.append((int(idx), float(score)))
    return results


# ── Index Building ───────────────────────────────────────────────────────────

async def ensure_index_built(api_key: str):
    global faiss_index, predicate_records, embedding_dim

    if faiss_index is not None:
        return

    logger.info("Loading predicate database...")
    with open(PREDICATE_FILE) as f:
        all_records = json.load(f)

    valid_records = [
        r for r in all_records
        if r.get("Indications for Use") and r.get("Device Name")
    ]
    predicate_records = valid_records
    logger.info(f"Loaded {len(valid_records)} valid predicates (filtered from {len(all_records)} total)")

    if EMBEDDINGS_CACHE.exists():
        logger.info("Loading cached embeddings...")
        cached = np.load(EMBEDDINGS_CACHE)
        vectors = cached["vectors"]
        if len(vectors) == len(valid_records):
            faiss_index = build_faiss_index(vectors)
            embedding_dim = vectors.shape[1]
            logger.info("Index built from cache ✓")
            return
        else:
            logger.warning("Cache size mismatch, regenerating embeddings...")

    logger.info("Generating embeddings with text-embedding-3-large...")
    client = get_openai_client(api_key)
    texts = [build_predicate_text(r) for r in valid_records]
    vectors = create_batch_embeddings(client, texts)

    np.savez(EMBEDDINGS_CACHE, vectors=vectors)
    logger.info(f"Embeddings cached to {EMBEDDINGS_CACHE}")

    faiss_index = build_faiss_index(vectors)
    faiss.write_index(faiss_index, str(FAISS_INDEX_FILE))
    embedding_dim = vectors.shape[1]
    logger.info("Index built and saved ✓")


# ── Prompt Construction ──────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior FDA regulatory writer with 20+ years of experience drafting 510(k) submissions.

Your task is to draft a legally compliant "Indications for Use" section for a 510(k) submission.

STRICT RULES:
- No promotional language whatsoever.
- No superiority claims.
- No performance metrics unless explicitly provided by the user.
- No adjectives like "innovative," "advanced," "state-of-the-art," "breakthrough," "superior," "cutting-edge," or any marketing language.
- Must clearly define:
   - Device type and what it is (physical description)
   - Intended use (exactly what it does)
   - Patient population (who it's used on)
   - Clinical setting / environment (where it's used)
   - User qualifications (who operates it)
   - Any limitations, contraindications, or exclusions
- Keep language precise and narrowly scoped.
- Use formal FDA regulatory tone throughout.
- Follow the structure and phrasing patterns of the reference predicate examples closely.
- Use standard FDA phrasing such as "The [Device Name] is intended to..." or "The device is indicated for..."
- Output should be 1-3 well-crafted paragraphs.
- Be specific about device characteristics (sterile, single-use, multi-sample, etc.) when relevant.
- Include safety features if applicable.
- Do NOT include any headers, titles, labels, or markdown formatting.
- Output ONLY the Indications for Use text itself."""


VALIDATION_PROMPT = """You are an FDA regulatory compliance reviewer. Evaluate the following Indications for Use text.

Check for:
1. Promotional or marketing language
2. Vague or ambiguous claims
3. Performance claims not supported by user input
4. Marketing adjectives (innovative, advanced, superior, etc.)
5. Regulatory risk language
6. Missing required elements:
   - Device type description
   - Intended use
   - Patient population
   - Clinical setting
   - User type/qualifications
7. Overly broad or insufficiently scoped language

Respond ONLY with a JSON object:
{
  "pass": true/false,
  "issues": ["issue1", "issue2"],
  "risk_level": "low|medium|high",
  "suggestions": ["suggestion1", "suggestion2"]
}

If no issues found, return: {"pass": true, "issues": [], "risk_level": "low", "suggestions": []}"""


def build_generation_prompt(device_input: DeviceInput, predicates: list[PredicateResult]) -> str:
    user_data = {
        "device_name": device_input.device_name,
        "device_category": device_input.device_category,
        "technology_type": device_input.technology_type,
        "intended_use": device_input.intended_use,
        "target_population": device_input.target_population,
        "clinical_setting": device_input.clinical_setting,
        "user_type": device_input.user_type,
        "regulation_number": device_input.regulation_number or "Not specified",
        "product_code": device_input.product_code or "Not specified",
        "limitations": device_input.limitations or "None specified",
    }

    predicate_text = "\n\n".join([
        f"PREDICATE {i+1} (510(k): {p.k_number or 'N/A'} — {p.device_name}):\n"
        f"Similarity Score: {p.similarity_score:.2%}\n"
        f"\"{p.indications_text}\""
        for i, p in enumerate(predicates)
    ])

    return f"""Draft the Indications for Use section for the following device.

USER INPUT:
{json.dumps(user_data, indent=2)}

REFERENCE EXAMPLES (from previously cleared 510(k) submissions — study their structure, tone, and phrasing patterns carefully, then use them as templates for the new device):

{predicate_text}

Write the final Indications for Use section only. No headers, no commentary, just the regulatory text. Match the style and structure of the reference examples as closely as possible while adapting to the new device."""


# ── Hard Constraint Validator ────────────────────────────────────────────────

def hard_validate(text: str) -> list[str]:
    issues = []
    lower = text.lower()

    for word in BANNED_WORDS:
        if word in lower:
            issues.append(f"Contains prohibited term: \"{word}\"")

    if len(text) < 80:
        issues.append("Output is unusually short (less than 80 characters)")

    sentences = [s.strip() for s in text.split(".") if s.strip()]
    if len(sentences) < 2:
        issues.append("Output may lack sufficient detail (fewer than 2 sentences)")

    if "intended" not in lower and "indicated" not in lower:
        issues.append("Missing standard phrasing ('intended' or 'indicated')")

    return issues


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "index_built": faiss_index is not None,
        "predicate_count": len(predicate_records),
        "embedding_model": EMBEDDING_MODEL,
        "generation_model": GENERATION_MODEL,
        "embedding_dim": embedding_dim,
    }


@app.post("/api/retrieve", response_model=RetrieveResponse)
async def retrieve_predicates(request: RetrieveRequest):
    try:
        if not PREDICATE_FILE.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Predicate database not found at {PREDICATE_FILE}. Make sure data/predicate_database.json exists.",
            )

        await ensure_index_built(request.device_input.openai_api_key)

        client = get_openai_client(request.device_input.openai_api_key)
        query_text = build_query_text(request.device_input)
        query_vec = create_embedding(client, query_text)

        results = search_index(faiss_index, query_vec, request.top_k)

        predicates = []
        for idx, score in results:
            record = predicate_records[idx]
            predicates.append(PredicateResult(
                k_number=record.get("510(k) Number"),
                device_name=record.get("Device Name"),
                indications_text=record.get("Indications for Use"),
                filename=record.get("Filename", ""),
                similarity_score=score,
            ))

        return RetrieveResponse(predicates=predicates, query_used=query_text)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/retrieve")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate", response_model=GenerateResponse)
async def generate_indications(request: GenerateRequest):
    try:
        if not PREDICATE_FILE.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Predicate database not found at {PREDICATE_FILE}.",
            )

        start_time = time.time()

        # Step 1: Ensure index is built
        await ensure_index_built(request.device_input.openai_api_key)

        client = get_openai_client(request.device_input.openai_api_key)

        # Step 2: Retrieve top predicates
        query_text = build_query_text(request.device_input)
        query_vec = create_embedding(client, query_text)
        results = search_index(faiss_index, query_vec, request.top_k)

        predicates = []
        for idx, score in results:
            record = predicate_records[idx]
            predicates.append(PredicateResult(
                k_number=record.get("510(k) Number"),
                device_name=record.get("Device Name"),
                indications_text=record.get("Indications for Use"),
                filename=record.get("Filename", ""),
                similarity_score=score,
            ))

        logger.info(f"Retrieved {len(predicates)} predicates (top score: {predicates[0].similarity_score:.3f})")

        # Step 3: Build prompt and generate
        user_prompt = build_generation_prompt(request.device_input, predicates)
        model_used = GENERATION_MODEL

        try:
            completion = client.chat.completions.create(
                model=GENERATION_MODEL,
                temperature=GENERATION_TEMPERATURE,
                max_tokens=GENERATION_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            generated_text = completion.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Primary model failed: {e}, falling back to {FALLBACK_MODEL}")
            model_used = FALLBACK_MODEL
            completion = client.chat.completions.create(
                model=FALLBACK_MODEL,
                temperature=GENERATION_TEMPERATURE,
                max_tokens=GENERATION_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            generated_text = completion.choices[0].message.content.strip()

        logger.info(f"Generated {len(generated_text)} chars with {model_used}")

        # Step 4: Hard constraint validation
        hard_issues = hard_validate(generated_text)

        # Step 5: AI validation pass
        ai_validation = {"pass": True, "issues": [], "risk_level": "low", "suggestions": []}
        try:
            val_completion = client.chat.completions.create(
                model=GENERATION_MODEL,
                temperature=0,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": VALIDATION_PROMPT},
                    {"role": "user", "content": generated_text},
                ],
            )
            val_text = val_completion.choices[0].message.content.strip()
            val_text = val_text.replace("```json", "").replace("```", "").strip()
            ai_validation = json.loads(val_text)
        except Exception as e:
            logger.warning(f"AI validation failed: {e}")

        # Combine validations
        all_issues = hard_issues + (ai_validation.get("issues") or [])
        validation_result = {
            "pass": len(all_issues) == 0,
            "hard_constraint_issues": hard_issues,
            "ai_issues": ai_validation.get("issues", []),
            "risk_level": ai_validation.get("risk_level", "low"),
            "suggestions": ai_validation.get("suggestions", []),
        }

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Full pipeline completed in {elapsed_ms}ms | Validation: {'PASS' if validation_result['pass'] else 'ISSUES FOUND'}")

        return GenerateResponse(
            indications_text=generated_text,
            predicates_used=predicates,
            validation=validation_result,
            model_used=model_used,
            generation_time_ms=elapsed_ms,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/generate")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/predicates")
async def list_predicates():
    with open(PREDICATE_FILE) as f:
        all_records = json.load(f)
    valid = [r for r in all_records if r.get("Indications for Use") and r.get("Device Name")]
    return {
        "total": len(all_records),
        "valid": len(valid),
        "predicates": [
            {
                "k_number": r.get("510(k) Number"),
                "device_name": r.get("Device Name"),
                "filename": r.get("Filename"),
            }
            for r in valid
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)