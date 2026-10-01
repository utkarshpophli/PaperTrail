# Fixtures — Document Pipeline golden paper set

Per docs/TESTING.md's "golden fixture set" — real, freely-licensed papers
checked into the repo, reused across unit/integration/eval tests.

## `s2orc_1911.02782v3.pdf`

- **Title:** S2ORC: The Semantic Scholar Open Research Corpus
- **arXiv ID:** 1911.02782 (v3)
- **Authors:** Kyle Lo, Lucy Lu Wang, Mark Neumann, Rodney Kinney, Daniel S. Weld
- **Venue:** ACL 2020
- **License:** CC BY 4.0
- **License evidence:** `https://arxiv.org/abs/1911.02782` — the abstract
  page's license link resolves to
  `https://creativecommons.org/licenses/by/4.0/` (confirmed by fetching the
  page HTML and finding the `licenses/by/4.0/` link; arXiv only shows an
  explicit license link for papers where the author selected one, as
  opposed to arXiv's non-exclusive default distribution license which does
  not grant redistribution rights).
- **Retrieved:** 2026-09-17 from `https://arxiv.org/pdf/1911.02782v3`
- **Why this paper:** ACL two-column camera-ready layout — real, dense
  multi-column text used to stress-test `parser.py`'s reading-order
  handling (see `backend/app/documents/parser.py`'s comment on `sort=True`
  vs. default extraction, decided against this exact fixture). It also has
  4 real embedded figures with captions, used for `figures.py` tests.

## `synthetic_scanned.pdf`

- **Not a real paper — synthetic, built for this fixture set.**
- A real, freely-redistributable arXiv paper with a genuinely scanned
  (image-only, no text layer) page was not found in the time available —
  essentially all arXiv submissions are born-digital LaTeX/Word PDFs with a
  text layer, and licensing for the rare exceptions (old digitized papers
  uploaded by third parties) is not clean redistribution permission. Per
  the task's explicit allowance, a synthetic fixture is used instead.
- **Construction:** 2 pages, built with PyMuPDF + Pillow
  (see the generation script inline in this task's report — not checked
  in, the PDF itself is the fixture).
  - Page 1: a normal text layer (`page.insert_text`) plus one embedded
    figure image with a "Figure 1: ..." caption below it — exercises the
    normal (non-OCR) text path and figure/caption extraction.
  - Page 2: a single full-page rendered image with no text layer at all
    (text drawn onto a Pillow image, then inserted as the page's only
    content) — has no extractable text, forcing `parser.py`'s OCR
    fallback. The image's rendered sentence is known ("This page exists
    only as a rendered image so the document parser must fall back to
    OCR...") so the OCR test can assert real recovered words appear in the
    output, not just that OCR ran.
- **License:** N/A (original, created for this repo, not sourced from any
  paper).
