# Health document retrieval prototype

This Django project ingests the 12 curated PDFs in `data/`, retrieves the passages that best match a question, and writes a short plain-language answer from those passages with numbered sources. It does not diagnose conditions or store private patient records. Use it for public health information only.

## Architecture

PyMuPDF extracts selectable text page by page. Conservative cleaning and page-bounded chunking keep passages traceable. Google's `gemini-embedding-001` creates 768-dimensional document and query vectors. Django stores documents and chunks in Supabase PostgreSQL with pgvector, then searches them by cosine distance. The API returns passages, scores, and citation metadata to authenticated staff users. The ask page sends the top five passages to a Gemini chat model (`GEMINI_CHAT_MODEL`, default `gemini-3.5-flash-lite`) with instructions to use only those passages and cite them, and shows only the passages the answer actually cites.

The initial similarity threshold is 0.70. It is a retrieval filter, not a guarantee that a passage answers a question. Review the evaluation results and tune `RAG_MIN_SIMILARITY` on the actual corpus. Model or dimension changes require re-embedding every document; the current skip check is checksum-based, so use a fresh database or remove and re-ingest all documents after such a change.

## Setup

1. Install Python 3.13 (or supported Python 3.12) and create an environment. On Windows PowerShell:

   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Create a Supabase project with a PostgreSQL database. Copy its **direct connection** URI into `DATABASE_URL`; if your network requires the Supabase pooler, use its session-mode URI. Add `?sslmode=require` (or `&sslmode=require` if the URI already has query parameters). Make sure the database role can create the `vector` extension; on Supabase, enable **vector** in Database Extensions first if migration permissions do not permit it.
3. Copy `.env.example` to `.env`, fill in a random `DJANGO_SECRET_KEY`, the PostgreSQL URI, and a Gemini API key. The project loads `.env` automatically; process environment variables take precedence. You can also set values directly in PowerShell, for example:

   ```powershell
   $env:DJANGO_SECRET_KEY = "your-random-secret"
   $env:DJANGO_DEBUG = "True"
   $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/postgres?sslmode=require"
   $env:GEMINI_API_KEY = "your-api-key"
   ```

   Set `DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS` appropriately for any deployed instance. Keep `.env` and credentials out of Git.
4. Migrate and create a staff login:

   ```powershell
   python manage.py migrate
   python manage.py createsuperuser
   ```

   The first migration enables pgvector and creates the document tables. A PostgreSQL server is required; SQLite cannot store these vectors.

## Documents and retrieval

```powershell
python manage.py ingest_documents
python manage.py list_documents
python manage.py ingest_documents --file "data/Dehydration_ MedlinePlus.pdf"
python manage.py remove_document 1
python manage.py remove_document 1 --yes
python manage.py ingest_documents --force
python manage.py reload_knowledge_base
python manage.py clear_knowledge_base
python manage.py search_documents "How can I prevent falls?" --top-k 5
python manage.py evaluate_retrieval --top-k 5
```

Ingestion discovers PDFs recursively inside `data/`, runs sequentially, skips unchanged completed documents, and replaces changed chunks only after all new embeddings succeed. Existing database records are retained when a local file is absent. Removal cascades to chunks. A failed update leaves the previous completed version searchable and records the error. New failed documents have `failed` status. Sparse pages are reported for manual review; image-only documents fail because OCR is not included.

`ingest_documents --force` re-extracts and re-embeds every PDF even if it has not changed; use it after changing the embedding model, dimensions, or chunk settings. `reload_knowledge_base` makes the database match `data/`: it lists and removes documents whose PDF is gone (asking for confirmation unless `--yes` is given), then force-ingests every PDF. Each document stays searchable on its previous version until its new version is fully embedded, so a provider failure partway through does not empty the knowledge base. `clear_knowledge_base` removes every document and chunk after confirmation (`--yes` skips the prompt); the PDFs in `data/` are never touched. Clearing leaves nothing searchable until you ingest again.

Use Django Admin at `/admin/` to correct titles and edit publisher or verified source URL metadata. Unknown source URLs stay blank. Original PDFs remain in `data/`.

### Ask page

Run `python manage.py runserver` and open `http://127.0.0.1:8000/`. Any signed-in user can ask a question in everyday language; there is no public sign-up, so create accounts with `createsuperuser` or in Django Admin under Users. The page shows the answer with numbered markers like [1], then a Sources list giving each cited document's title (linked when a verified source URL is set in Admin), publisher, page numbers, and the exact passage. If no passage clears the similarity threshold, or the model says the passages do not answer the question, or it cites nothing valid, the page says no answer was found instead of showing an unsupported answer. Questions are limited to 1,000 characters. Each question costs one embedding call and one chat call.

### HTTP API

Run `python manage.py runserver`, sign in to `/admin/` as a staff user, then issue `POST /api/retrieve/` from the same browser session with `Content-Type: application/json` and the Django `X-CSRFToken` header. An example request body is:

```json
{"question": "What are the symptoms of dehydration?", "top_k": 5}
```

The endpoint accepts questions up to 1,000 characters and `top_k` from 1 to 5. It returns the original question and ranked passage objects containing document ID, title, publisher, source URL, page range, chunk ID, text, and similarity score. Empty results include an explanatory message. Staff session authentication and CSRF protection are required; anonymous or non-staff calls return 403. Do not use a blanket CSRF exemption or expose this endpoint publicly.

## Tests and evaluation

```powershell
python manage.py check
python manage.py test knowledge_base.tests
python manage.py test knowledge_base.integration_tests
```

The first test command uses in-memory PDFs and mocked embedding responses, so it does not need API or database credentials. The integration suite needs a PostgreSQL `DATABASE_URL` that allows Django to create and drop a test database with pgvector; it mocks Gemini and does not consume embedding quota. It is separate so local tests can pass without PostgreSQL. Run `evaluate_retrieval` only after ingestion, since it performs real query embeddings. Its 14 source expectations were derived from the checked-in PDFs; inspect any `REVIEW` output rather than treating it as a fabricated answer. The two unrelated questions are expected to return no passage, but this depends on threshold calibration.

## Troubleshooting and limits

- **Migration cannot connect:** Check `DATABASE_URL`, SSL mode, Supabase network access, and database credentials. A local PostgreSQL server at `localhost:5432` is only a fallback for commands that do not need a connection.
- **`vector` extension error:** Enable Supabase's vector extension and rerun migrations with a role that can create the extension.
- **Embedding error:** Check `GEMINI_API_KEY`, API access, quota, and rate limits. Requests retry up to three times with bounded backoff. The API key is never sent to retrieval clients.
- **Unusable PDF:** The extractor requires selectable text. Review reported sparse pages and source layouts. Multi-column ordering is heuristic and may require manual inspection; no OCR is provided.
- **Weak or misleading matches:** Review retrieved passages and tune the threshold against `evaluation_questions.json`. Similarity alone does not establish medical support.

There is no public sign-up, conversation history, upload UI, OCR, or private patient data handling. This is a small developer prototype, not a clinical decision system.
