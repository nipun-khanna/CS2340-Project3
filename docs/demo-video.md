# Demo video: US-09

The course requires a **5–10 minute team video**, with **every member on camera and speaking**, and a working demonstration on the **deployed website**. This guide supplies Arjun's US-09 segment and a team outline. Record actual working behavior; the local regression suite is not a substitute for the hosted demonstration.

The assigned cards place **US-09 in Sprint 1** and **US-06 in Sprint 2**. Use each segment in its appropriate sprint review; do not describe future-sprint work as already delivered in an earlier sprint.

## Before recording

1. Merge/deploy the PR through the team's normal workflow, install the updated requirements, and retain the existing PostgreSQL/pgvector configuration. This change needs no new migrations.
2. Set `GEMINI_API_KEY` on the server. The key is required for embeddings and answer generation. Log in with an existing staff account and open `/developer/`.
3. Ingest the local dehydration PDF and both CDC STEADI brochures used by `evaluation_answers.json`.
4. Rehearse the known questions on the deployed site. If a check says REVIEW, inspect the actual answer, source passage, and expected concepts. Correct real issues; do not change expectations merely to get PASS.
5. For a full developer report, run `python manage.py evaluate_answers --output evaluation-results.json` against the same deployed dataset and model configuration. Review the generated answers against the reference PDFs. Keep actual results available for the recording.
6. Share the deployed browser window. Keep terminal environment settings and credentials off screen. Have each teammate prepare an accurate account of their own work and the team's actual Scrum practices.

## Arjun's US-09 segment (about 90 seconds)

**Show:** `/developer/`, select “What happens to blood pressure when someone with postural hypotension goes from sitting to standing?”, then click **Test answer**.

**Say:** “My first story is US-09: testing response accuracy against known questions. We already had retrieval tests, which check whether the right document is found. I added an evaluator that also checks the generated answer. Each question has a reference answer based on a checked-in PDF, expected concepts, and an expected cited source.”

**Show:** The generated answer, reference answer, individual checks, and source passage. Describe the actual result on screen.

**Say:** “For answerable questions, we check that the bot answered, included the expected concepts, cited the expected document, and included a citation marker. The report also shows how long the request took. These checks flag regressions; I still compare the full answer with the reference because matching phrases alone cannot prove correctness.”

**Show:** Choose the car-transmission question and click **Test answer**.

**Say:** “The suite also includes unrelated questions. These should return our not-found response without sources. Provider failures are reported as errors rather than successful abstentions. There are six known cases, and the command-line evaluator saves full results as JSON and exits unsuccessfully if any case needs review.”

## Suggested seven-minute team outline

| Time | Presenter/content |
| --- | --- |
| 0:00–0:40 | Introduce the team, intended elderly-user persona, problem, and sprint scope. |
| 0:40–2:10 | Arjun: demonstrate the story assigned to this sprint using the segment above. |
| 2:10–4:40 | Other teammates: demonstrate their own completed stories and explain their decisions. Divide time so every member speaks. |
| 4:40–5:40 | Explain how responsibilities were divided and what actually happened in planning, standups, and review. |
| 5:40–6:30 | Explain real challenges, how the team resolved them, and remaining limitations. |
| 6:30–7:00 | State the next sprint's planned work, or remaining work if this is the final sprint. |

Adjust the time split for the team's size and sprint scope. Do not invent meetings, contributions, completed deployments, or successful live evaluations. Export the recording, confirm it is 5–10 minutes long, and test the final shared link in a signed-out browser so graders can access it without special permission.

## Code explanation for the live TA demo

- `services/evaluation.py`: case validation and answer/reference comparison.
- `evaluation_answers.json`: known questions, reference answers, PDF page references, and expected concepts.
- `views.py` and `developer_tools.html`: staff-only forms protected by normal Django CSRF middleware.
- `management/commands/evaluate_answers.py`: batch report and failure exit status.

Be ready to explain why retrieval success alone does not establish answer accuracy, and why phrase checks still need human review.
