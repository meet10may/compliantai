# IndiClear 510(k) — AI-Powered Indications for Use Generator

> RAG-powered web application that generates FDA-compliant "Indications for Use" sections for 510(k) submissions.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                    │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  Device   │→ │  Predicate   │→ │  Generated Output │  │
│  │  Form     │  │  Review      │  │  + Validation     │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP API
┌────────────────────────▼────────────────────────────────┐
│                   BACKEND (FastAPI)                      │
│                                                         │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │  Embedding   │   │    FAISS     │   │   Prompt     │  │
│  │  Module      │   │  Vector Store│   │   Builder    │  │
│  │ (text-embed- │   │ (cosine sim) │   │   Engine     │  │
│  │  ding-3-lg)  │   │              │   │              │  │
│  └──────┬──────┘   └──────┬───────┘   └──────┬───────┘  │
│         │                 │                   │          │
│         ▼                 ▼                   ▼          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              OpenAI API (GPT-4.1)                   │ │
│  │  Generation (temp=0.2) → Validation (temp=0)        │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─────────────┐   ┌──────────────┐                     │
│  │  Hard        │   │   AI         │                     │
│  │  Constraints │   │   Validator  │                     │
│  │  Filter      │   │   (2nd pass) │                     │
│  └─────────────┘   └──────────────┘                     │
└─────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                     DATA LAYER                          │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ predicate_   │  │embeddings│  │  faiss_index.bin   │  │
│  │ database.json│  │_cache.npz│  │  (auto-generated)  │  │
│  └──────────────┘  └──────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## RAG Pipeline (per request)

```
User Input (structured form)
    │
    ▼
Build query text (device name + category + use + population + setting + ...)
    │
    ▼
Embed query with text-embedding-3-large → 3072-dim vector
    │
    ▼
L2-normalize → FAISS Inner Product search (= cosine similarity)
    │
    ▼
Return top-3 predicate matches with similarity scores
    │
    ▼
Build prompt: System (FDA rules) + User (device JSON + predicate examples)
    │
    ▼
GPT-4.1 (temperature=0.2, max_tokens=600) → generated text
    │
    ▼
Hard constraint filter (banned words, structural checks)
    │
    ▼
AI validation pass (GPT-4.1, temperature=0) → compliance review
    │
    ▼
Return final output + validation report
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- OpenAI API key (with access to `gpt-4.1` and `text-embedding-3-large`)

### 1. Clone and setup backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
python main.py
```

The backend runs at `http://localhost:8000`. Check health: `http://localhost:8000/api/health`

### 2. Setup frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

The frontend runs at `http://localhost:3000` and proxies API calls to the backend.

### 3. Use the app

1. Open `http://localhost:3000`
2. Click "Start Drafting"
3. Fill in device details + your OpenAI API key
4. Click "Match Predicates" — this triggers:
   - First-time: embeds all 20 predicates (takes ~5s, cached after)
   - Embeds your query
   - FAISS cosine similarity search
5. Review matched predicates
6. Click "Generate with GPT-4.1"
7. Review output + validation results

## Project Structure

```
indiclear-mvp/
├── backend/
│   ├── main.py              # FastAPI app — RAG pipeline, all endpoints
│   ├── requirements.txt     # Python dependencies
│   └── .env.example         # Environment variable template
├── frontend/
│   ├── src/app/
│   │   ├── layout.js        # Root layout
│   │   ├── page.js          # Main app (all steps)
│   │   └── globals.css      # Tailwind + custom styles
│   ├── next.config.js       # API proxy config
│   ├── tailwind.config.js   # Tailwind theme
│   └── package.json         # Node dependencies
├── data/
│   ├── predicate_database.json    # Your 510(k) predicate dataset
│   ├── embeddings_cache.npz       # Auto-generated embedding cache
│   └── faiss_index.bin            # Auto-generated FAISS index
└── README.md
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check + index stats |
| `/api/predicates` | GET | List all predicates in database |
| `/api/retrieve` | POST | Embed query → FAISS search → return top-k |
| `/api/generate` | POST | Full pipeline: retrieve → generate → validate |

## Adding More Data

To add new predicates, edit `data/predicate_database.json`:

```json
{
  "510(k) Number": "K999999",
  "Indications for Use": "The Device X is intended to...",
  "Device Name": "Device X",
  "Filename": "K999999.pdf"
}
```

Then delete `data/embeddings_cache.npz` and `data/faiss_index.bin` — they'll be regenerated on next request.

## Deployment (Free Options)

### Option A: Railway.app (Recommended for MVP)

1. Push to GitHub
2. Create Railway project → connect repo
3. Add two services: backend (Python) + frontend (Node)
4. Set environment variables
5. Railway gives you a public URL

### Option B: Render.com

1. Create two services: Web Service (backend) + Static Site (frontend)
2. Backend: set build command `pip install -r requirements.txt`, start `uvicorn main:app`
3. Frontend: set build command `npm run build`, publish dir `out`

### Option C: Vercel (frontend) + Railway (backend)

1. Deploy frontend to Vercel (free)
2. Deploy backend to Railway
3. Update `next.config.js` rewrites to point to Railway backend URL

## Cost Estimate (OpenAI)

| Operation | Model | Input Tokens | Output Tokens | Cost/call |
|-----------|-------|-------------|---------------|-----------|
| Embed predicates (one-time) | text-embedding-3-large | ~6,000 | — | ~$0.001 |
| Embed query | text-embedding-3-large | ~100 | — | ~$0.00001 |
| Generate | gpt-4.1 | ~1,500 | ~300 | ~$0.005 |
| Validate | gpt-4.1 | ~500 | ~100 | ~$0.002 |
| **Total per generation** | | | | **~$0.007** |

100 generations/month ≈ **$0.70**

## Tech Stack

- **Backend**: FastAPI + FAISS + OpenAI Python SDK
- **Embeddings**: `text-embedding-3-large` (3072 dimensions)
- **Vector Store**: FAISS `IndexFlatIP` (cosine similarity via normalized inner product)
- **Generation**: GPT-4.1 (primary) / GPT-4o (fallback)
- **Frontend**: Next.js 14 + Tailwind CSS
- **Validation**: Dual-pass (hard constraints + AI reviewer)
