import math
import os
import time

from google import genai
from google.genai import errors, types


MODEL = "gemini-embedding-001"
DIMENSIONS = 768


def embed_text(text: str, task_type: str, *, client=None) -> list[float]:
    if task_type not in {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}:
        raise ValueError("Unsupported embedding task")
    if client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        client = genai.Client(api_key=key)
    for attempt in range(3):
        try:
            response = client.models.embed_content(
                model=MODEL, contents=text,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSIONS),
            )
            values = list(response.embeddings[0].values)
            if len(values) != DIMENSIONS or not all(math.isfinite(v) for v in values):
                raise ValueError("Embedding response has invalid dimensions or values")
            magnitude = math.sqrt(sum(v * v for v in values))
            if magnitude == 0:
                raise ValueError("Embedding response is a zero vector")
            return [v / magnitude for v in values]
        except ValueError:
            raise
        except errors.APIError as exc:
            if exc.code != 429 and exc.code < 500:
                raise RuntimeError("Embedding request was rejected") from exc
            if attempt == 2:
                raise RuntimeError("Embedding request failed after 3 attempts") from exc
            time.sleep(2 ** attempt)
        except (TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise RuntimeError("Embedding request failed after 3 attempts") from exc
            time.sleep(2 ** attempt)
    raise AssertionError("Unreachable")
