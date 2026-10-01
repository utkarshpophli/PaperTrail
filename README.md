<div align="center">

<img src="assets/logo.png" alt="Paper Trail: every claim, a page, an exact quote" width="820" />

# Paper Trail

**Drop in a paper. Get a workspace where every claim points back to a page and an exact quote.**

Paper Trail turns an AI/ML research paper into something you can verify, learn from and build on.
You choose the model, cloud or local, and every quote the model hands back is checked against the
paper by Paper Trail itself, not by the model.

[![Live demo](https://img.shields.io/badge/live_demo-Hugging_Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=000&labelColor=1D1D1F)](https://huggingface.co/spaces/utkarshpophli/PaperTrail)
[![License: MIT](https://img.shields.io/badge/license-MIT-1D1D1F?style=for-the-badge&labelColor=1D1D1F)](LICENSE)
[![Local first](https://img.shields.io/badge/local--first-no_login-1B7A36?style=for-the-badge&labelColor=1D1D1F)](#your-keys-your-machine)
[![Quotes verified](https://img.shields.io/badge/every_quote-verified_against_the_page-0066CC?style=for-the-badge&labelColor=1D1D1F)](#check-every-quote-against-its-page)

**Runs on the model you choose**

[![NVIDIA NIM](https://img.shields.io/badge/NVIDIA_NIM-76B900?style=for-the-badge&logo=nvidia&logoColor=fff)](#providers)
[![Anthropic](https://img.shields.io/badge/Anthropic-D97757?style=for-the-badge&logo=anthropic&logoColor=fff)](#providers)
[![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=fff)](#providers)
[![Google Gemini](https://img.shields.io/badge/Gemini-4285F4?style=for-the-badge&logo=googlegemini&logoColor=fff)](#providers)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-6566F1?style=for-the-badge&logoColor=fff)](#providers)
[![Groq](https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=fff)](#providers)
[![Ollama](https://img.shields.io/badge/Ollama_(local)-1D1D1F?style=for-the-badge&logo=ollama&logoColor=fff)](#providers)
[![LM Studio](https://img.shields.io/badge/LM_Studio_(local)-1D1D1F?style=for-the-badge&logoColor=fff)](#providers)
[![llama.cpp](https://img.shields.io/badge/llama.cpp_(local)-1D1D1F?style=for-the-badge&logoColor=fff)](#providers)

**Built with**

![Next.js](https://img.shields.io/badge/Next.js_16-000?style=flat-square&logo=nextdotjs&logoColor=fff)
![React](https://img.shields.io/badge/React_19-149ECA?style=flat-square&logo=react&logoColor=fff)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=fff)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS_4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=fff)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=fff)
![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=fff)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_+_pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=fff)
![PyMuPDF](https://img.shields.io/badge/PyMuPDF-B31B1B?style=flat-square&logoColor=fff)

</div>

---

## What it is

https://github.com/user-attachments/assets/6f131cea-22f0-427a-91d9-3afe3b2e3cd4

A model can summarise a paper in seconds. Checking that summary takes hours: you get fluent prose
and no way to tell which sentence came from which page, or whether something was measured by the
authors or merely suggested.

**Paper Trail works the other way round.** Every claim carries the page and the exact quote it
rests on. Measured results, the authors' interpretation, background, method and limitations are
labelled separately. A quote counts as `verified` only when Paper Trail finds it on the page it
cites. A claim that fails the check is shown with that result, never hidden or quietly upgraded.

From those checked claims it builds a readable story, a deep report, a technical appendix, a primer
on what the paper assumes, a quiz, worked derivations and interactive playgrounds. Every part of
these links back to the claims it rests on.

---

## How to use it

1. **Start Paper Trail** (see [Running locally](#running-locally)) and open http://localhost:3000.
2. **Add a paper.** Drop a PDF, or type an arXiv id, an arXiv URL or a paper title.
3. **Pick a model.** Choose a provider, paste your API key (cloud) or your local endpoint, and pick
   a model from the live list. **Test model** sends one tiny request first, so a wrong key or a dead
   model fails in seconds rather than mid-run.
4. **Press Generate.** The progress panel shows each step and whether it runs on your machine or is
   a cloud API call. **Cancel** stops the run and the model requests behind it.
5. **Read, check and learn** in the paper studio:
   - **Lab**: overview, primer, learn & try (quiz, derivations, interactives), deep report,
     technical appendix, claims, evidence health, method, metrics, limitations, glossary,
     citations, ask, and the original pages.
   - **Story**: the paper as a narrative, with sources one click away.
   - **Preview**: the story as a clean page to read.

![Home: paper, model, generate](assets/home.jpg)

---

## What you get

### Read it as a story, with the source one click away

The paper becomes a narrative with numbered sections, a paper map and the key numbers at a glance.
Every section ends in **Source · p. N** tags. Click one and the evidence drawer opens with the
claim, its kind, its verification status and the exact passage from that page.

![Story mode](assets/story.jpg)

![Evidence drawer](assets/evidence.jpg)

### Check every quote against its page

The verifier is ordinary code, not a model. It searches each quote in the parsed text of the page
the claim cites, and marks the claim `verified`, `partially-matched`, `mismatch` or `not-found`.
What the model said about its own accuracy is a hint, never the decision.

![Claims with verification status](assets/claims.jpg)

### See where the evidence is thin

**Evidence health** is computed in your browser from the extracted evidence, with no model involved:

- how many claims are verified;
- which pages between the first and last citation nothing cites;
- whether any collected claim goes unused;
- which story or report sections rest on one claim or none.

![Evidence health](assets/health.jpg)

### The paper's own figures, beside the text that discusses them

Each `Figure N` and `Table N` caption gets exactly one crop of what the page actually draws, built
from vector graphics and embedded images together. Multi-panel plots stay one figure, icons inside a
diagram stay part of it, and booktabs tables are found by their rules. A figure then appears under
the Primer, Deep report or Technical section that names it ("Figure 2") or cites its claims.

![Primer with the architecture figure inline](assets/primer.jpg)

![Deep report with Figure 1 and Table 1 inline](assets/report.jpg)

### Learn what the paper assumes

The **Primer** covers the background the paper takes for granted. Each concept says why this paper
needs it, and lists the claims it rests on.

### Test yourself

The **quiz** is generated from the evidence. Every question is tied to the claims it tests, and the
answer stays hidden until you ask for it.

![Quiz](assets/quiz.jpg)

### Run the paper's own numbers

**Interactives** turn a reported relationship into sliders. The defaults are the paper's values,
cited claim by claim. Any range the paper doesn't state is labelled illustrative. Formulas run on a
restricted grammar, never `eval`.

![Interactive playground](assets/interactive.jpg)

### Ask the evidence

The **Ask** tab answers questions from the paper's collected claims, metrics, glossary and learning
content, and points back to the claims it used.

---

## Running locally

Prerequisites: Python 3.12+, Node.js LTS, PostgreSQL 16+ with `pgvector`, and the Tesseract binary
for scanned-page OCR.

**Backend** (Windows paths shown; run from `backend/`, since uploaded PDFs and figures go to `./storage`):

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
cp .env.example .env            # set DATABASE_URL and JWT_SECRET_KEY
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Windows, start uvicorn without `--reload`: it can log "Reloading…" and keep serving the old
code. Restart the process by hand after backend changes.

**Frontend** (open http://localhost:3000):

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

**Tests:**

```bash
# backend: runs against a disposable Postgres DB (the suite drops and recreates every table)
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://papertrail:papertrail@localhost:5432/papertrail_test .venv/Scripts/python.exe -m pytest

# frontend
cd frontend
npm test            # Vitest
npm run test:e2e    # Playwright
```

The backend tests always use `TEST_DATABASE_URL`, never a `DATABASE_URL` from your shell or `.env`,
and refuse to run unless the database name contains `test`.

---

## Your keys, your machine

- **No login.** Local mode is the default: one local user, no accounts. Since nothing else protects
  your papers and keys, the API only answers requests from this machine. Any other client gets
  `403 local_mode_loopback_only`, even if the server was started on `0.0.0.0`.
- **Keys are never stored.** You enter an API key per run. It goes to the backend with that request
  only, is never written to disk or logs, and is redacted from provider error messages.
- **Local models stay local.** Ollama, LM Studio and llama.cpp endpoints must be on loopback. If every
  stage uses a local model, inference never leaves your machine. Looking a paper up on arXiv still
  contacts arxiv.org.
- **Cancel means cancel.** Pressing **Cancel** or closing the tab ends the run on the server and closes
  the in-flight model requests, so nothing keeps generating in the background.
- **Nothing from a paper runs.** Uploads must be real PDFs, and extracted code is shown, never executed.

---

## How it works

```mermaid
flowchart LR
    A["PDF, arXiv id<br/>or title"] --> B["Parse on your machine<br/>text · figures · tables"]
    B --> C["4 extraction passes<br/>claims · metrics<br/>glossary · narrative"]
    C --> D["Check every quote<br/>against its page<br/>(on your machine)"]
    D --> E["Technical appendix<br/>Deep report"]
    E --> F["Story · primer · quiz<br/>derivations · interactives<br/>figure links"]
    F --> G["Paper studio"]

    style B fill:#f5f5f7,stroke:#d2d2d7,color:#1d1d1f
    style D fill:#1d1d1f,stroke:#1d1d1f,color:#ffffff
    style G fill:#0066cc,stroke:#0066cc,color:#ffffff
```

Paper Trail owns the parsing. The PDF becomes page text, figure crops and table crops before any
model sees it, so every stage works with any provider, including a local model that can't read a
PDF itself. Only extracted text goes to the model you picked.

### Architecture

```mermaid
flowchart TB
    subgraph browser["Browser · Next.js on localhost:3000"]
        UI["Home · Library · Paper studio<br/>(Lab · Story · Preview)"]
    end

    subgraph api["FastAPI on 127.0.0.1:8000 · loopback only"]
        R["Routers<br/>papers · evidence · providers"]
        P["Document parser<br/>PyMuPDF · Tesseract OCR<br/>figure + table crops"]
        X["Evidence pipeline<br/>extraction · report · learning layer"]
        V["Quote verifier<br/>plain code, no model"]
        A["Provider adapters<br/>one interface · retries · deadlines"]
    end

    DB[("PostgreSQL + pgvector<br/>papers · pages · claims<br/>sections · figures")]
    FS[("storage/<br/>PDFs · figure crops")]
    CLOUD["Cloud APIs<br/>NVIDIA NIM · Anthropic · OpenAI<br/>Gemini · OpenRouter · Groq"]
    LOCAL["Local runtimes<br/>Ollama · LM Studio · llama.cpp"]

    UI -- "REST + SSE progress stream" --> R
    R --> P --> FS
    P --> DB
    R --> X --> A
    X --> V
    V --> DB
    X --> DB
    A -- "your API key, per request" --> CLOUD
    A -- "loopback endpoint" --> LOCAL
```

### What happens when you press Generate

```mermaid
sequenceDiagram
    participant U as Browser
    participant B as Backend
    participant M as Model (cloud or local)

    U->>B: Add paper (PDF upload or arXiv)
    B->>B: Parse pages, crop figures and tables
    U->>B: Analyze (provider, model, key)
    B->>M: Test request (is the model alive?)
    loop 4 extraction passes
        B-->>U: Progress: "Pass n of 4 ..."
        B->>M: Paper text + extraction prompt (streamed)
        M-->>B: Claims, metrics, glossary, narrative
    end
    B->>B: Check every quote against its page
    B->>M: Technical appendix, deep report, learning layer
    M-->>B: Sections that cite claim ids
    B->>B: Reject any section citing an unknown claim (one retry)
    B-->>U: Done, open the paper studio
    Note over U,B: Cancel or closing the tab ends the run<br/>and the in-flight model requests
```

---

## Providers

| Provider | Runs | You need | Notes |
|---|---|---|---|
| NVIDIA NIM | Cloud | NVIDIA API key | Chat and embedding models from the NIM catalog |
| Anthropic | Cloud | Anthropic API key | Claude models, picked from your account's live list |
| OpenAI | Cloud | OpenAI API key | |
| Google Gemini | Cloud | Google AI API key | |
| OpenRouter | Cloud | OpenRouter API key | Many vendors' models behind one key |
| Groq | Cloud | Groq API key | |
| Ollama | On your machine | Ollama running locally | Loopback endpoint only, e.g. `http://127.0.0.1:11434` |
| LM Studio | On your machine | LM Studio server running | Loopback endpoint only |
| llama.cpp | On your machine | `llama-server` running | Loopback endpoint only |

You can use one model for every stage, or a different model per stage. Paper Trail never silently
swaps in a different model: a model that can't do a task fails with a specific error.

---

## License

MIT. See [LICENSE](LICENSE).
