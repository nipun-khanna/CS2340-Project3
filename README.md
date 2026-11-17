# Health document retrieval prototype

This Django project ingests the 12 curated PDFs in `data/` and curated public health webpages, retrieves the passages that best match a question, and writes a short plain-language answer from those passages with numbered sources. It does not diagnose conditions or store private patient records. Use it for public health information only.

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

### Two ingestion methods (US-06)

Staff users can open **Developer tools** from the ask page, or visit `/developer/`. The PDF form reads one of the curated files in `data/`. The webpage form scrapes a public HTML article from an exact host in `INGEST_ALLOWED_HOSTS` (configured in `config/settings.py`). For example:

```powershell
python manage.py ingest_webpage "https://medlineplus.gov/dehydration.html"
python manage.py ingest_webpage "https://medlineplus.gov/dehydration.html" --force
```

These are distinct input methods: local PDF text extraction and remote HTML scraping. Both use the existing cleaning, chunking, embedding, and transactional storage pipeline. Web content is fetched again on each ingestion; unchanged extracted text is skipped unless forced. Web records keep their source URL and use a `web/` identity based on that URL. Citations label them as web articles rather than inventing PDF page numbers. Internally, their chunks use section/page 1 to fit the existing storage model.

The scraper requires HTTPS, checks redirect destinations against the same host list, uses a 15-second network timeout, and reads at most 2 MiB. It removes scripts, navigation, and other boilerplate, preferring a main/article element. JavaScript rendering, OCR, PDF downloads through the scraper, and unrestricted web crawling are unsupported. Source websites can still change their layouts or block requests. Add hosts only after reviewing their provenance and relevance to the curated dataset.

`reload_knowledge_base` still refreshes local PDFs and removes missing PDF records; it now preserves scraped webpage records. Refresh a webpage separately with `ingest_webpage URL --force`. `clear_knowledge_base` clears both source types. Staff forms retain session authentication and CSRF protection; ordinary end users cannot run ingestion or evaluations.

### Clear or reload on the website (US-11)

The **Knowledge base** section of `/developer/` has **Reload knowledge base** and **Clear knowledge base** buttons. Both require ticking a confirmation box and run the same `reload_knowledge_base --yes` and `clear_knowledge_base --yes` commands described above. Reloading all 12 PDFs takes about 40 seconds.

### Performance monitoring and usage logs (US-10, US-12)

Every question asked on the ask page records its timestamp, question length, success, and response time (question text is not stored, since it may contain private health details). Staff can open **View system performance** from `/developer/`, or visit `/developer/monitoring/`, to see for the last hour, 24 hours, or 7 days: request count, failures and failure rate, average, median, 95th-percentile, and slowest response time, requests slower than the target, an `OK`/`ATTENTION` status, recent failures, and the recent usage log. Targets are `RESPONSE_TIME_TARGET_SECONDS` (default 10; the 95th percentile must not exceed it) and `MAX_FAILURE_RATE` (default 0.05). The full log is also in Django Admin under Usage logs.

### Prompts by question intent (US-08)

`knowledge_base/services/prompts.py` classifies each question at runtime as `factual`, `explanation`, `procedural`, or `creative` and builds the system prompt from shared grounding and safety rules plus that intent's style rules, word limit, and temperature. For example, "What is postural hypotension?" gets a short direct answer, "Why do older adults get dehydrated?" a cause-and-effect explanation, "How do I stay hydrated?" a numbered list of steps, and "Write a short poem about staying hydrated" a cited poem. Creative requests search on their topic ("staying hydrated") so the format wording does not hurt retrieval. Every intent keeps the same citation and no-outside-knowledge rules.

### Known-answer evaluation (US-09)

`evaluate_retrieval` checks source ranking only. The new evaluator calls the complete answer service and compares its output with six known questions in `evaluation_answers.json`: four source-grounded health questions and two unrelated questions that should be declined. Each answerable case includes a reference answer, source PDF and page numbers, expected source title, and groups of acceptable phrases for required concepts.

```powershell
python manage.py evaluate_answers --output evaluation-results.json
python manage.py evaluate_answers --cases evaluation_answers.json --output evaluation-results.json
```

Run this after ingesting the reference PDFs, with a working database and `GEMINI_API_KEY`. Each case can consume an embedding and a chat request. The staff page can run one known question at a time and show the reference, generated answer, checks, and cited passages on the website.

Answerable cases check expected concepts, the expected cited source, and an inline citation. Unrelated cases must return the not-found response with no sources. Output is `PASS`, `REVIEW`, or `ERROR`; errors do not count as successful refusals. The command continues through all cases, saves full answers/sources/checks/timings with model and threshold metadata, and exits nonzero if any case is not PASS. The report is local and ignored by Git.

Phrase checks are regression smoke tests, not a semantic or clinical accuracy score. They can miss contradictions or unsupported additions, and valid paraphrases can require review. Compare full generated answers with the cited source and reference answer before accepting results. Source titles must match the curated baseline; update reviewed cases if document titles are intentionally changed. Do not infer live model accuracy from the mocked regression suite.

See [the sprint video guide](docs/demo-video.md) for a hosted-site walkthrough, speaking script, and team recording requirements.

### Ask page

Run `python manage.py runserver` and open `http://127.0.0.1:8000/`. Anyone can ask a question in everyday language without signing in. Staff tools still require a staff login; there is no public sign-up, so create staff accounts with `createsuperuser` or in Django Admin under Users. The page shows the answer with numbered markers like [1], then a Sources list giving each cited document's title (linked when a verified source URL is set in Admin), publisher, page numbers, and the exact passage. If no passage clears the similarity threshold, or the model says the passages do not answer the question, or it cites nothing valid, the page says no answer was found instead of showing an unsupported answer. Questions are limited to 1,000 characters. Each question costs one embedding call and one chat call.

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

## Deploying to Vercel

The repository is ready for Vercel, which detects Django from `manage.py` and serves `config.wsgi` directly. WhiteNoise serves admin and app static files. New Vercel projects allow functions to run for up to 300 seconds, enough for a knowledge base reload (about 40 seconds).

1. In Vercel, choose **Add New → Project** and import this GitHub repository (the framework is detected as Django), or deploy from a local checkout with `npx vercel deploy --prod`. A private repository owned by another personal GitHub account cannot be imported on the Hobby plan; use the CLI instead.
2. Under **Settings → Environment Variables**, add:
   - `DJANGO_SECRET_KEY`: a new long random value (required; the app refuses to start on Vercel without it).
   - `DJANGO_DEBUG`: `False`.
   - `DATABASE_URL`: the Supabase **transaction pooler** URI (port `6543`), with `?sslmode=require`. Serverless functions open many short connections, which the session pooler on port 5432 can run out of.
   - `GEMINI_API_KEY`, and optionally `RAG_MIN_SIMILARITY`, `GEMINI_CHAT_MODEL`, `RESPONSE_TIME_TARGET_SECONDS`, `MAX_FAILURE_RATE`.
   - For a custom domain, also `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` (with `https://`). `*.vercel.app` addresses are allowed automatically.
3. Deploy. Migrations and ingestion are not run by Vercel: run `python manage.py migrate` and ingest documents locally against the same `DATABASE_URL` (or use the Developer tools page after creating a staff user).

## Troubleshooting and limits

- **Migration cannot connect:** Check `DATABASE_URL`, SSL mode, Supabase network access, and database credentials. A local PostgreSQL server at `localhost:5432` is only a fallback for commands that do not need a connection.
- **`vector` extension error:** Enable Supabase's vector extension and rerun migrations with a role that can create the extension.
- **Embedding error:** Check `GEMINI_API_KEY`, API access, quota, and rate limits. Requests retry up to three times with bounded backoff. The API key is never sent to retrieval clients.
- **Unusable PDF:** The extractor requires selectable text. Review reported sparse pages and source layouts. Multi-column ordering is heuristic and may require manual inspection; no OCR is provided.
- **Weak or misleading matches:** Review retrieved passages and tune the threshold against `evaluation_questions.json`. Similarity alone does not establish medical support.

There is no public sign-up, conversation history, arbitrary file upload UI, OCR, or private patient data handling. This is a small developer prototype, not a clinical decision system.
