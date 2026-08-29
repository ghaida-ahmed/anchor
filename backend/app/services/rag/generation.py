"""LLM provider abstraction, the OpenAI implementation, and prompt construction.

Vendor-specific calls live here and nowhere else. `RagService` speaks only to
`LLMProvider`, so a second vendor is a new class plus a branch in the factory.
"""

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings
from app.core.exceptions import AnchorError
from app.services.rag.embeddings import ProviderNotConfiguredError
from app.services.rag.retrieval import RetrievedChunk

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 1.5

# Low but not zero: the answer must track the sources, while still reading as prose
# rather than a copy-paste of the chunks.
TEMPERATURE = 0.2

SYSTEM_PROMPT = """You are ANCHOR's study tutor. You answer a student's question \
using ONLY the excerpts from their own uploaded course materials that are provided \
below.

Rules you must follow:
- Base every factual claim on the provided excerpts. Do not use outside knowledge, \
even if you are confident it is correct.
- If the excerpts do not contain enough information to answer, say so plainly and \
stop. Do not guess, and do not pad the answer with general knowledge.
- Never state or imply that something appears in the student's materials unless an \
excerpt supports it.
- Do not invent document names, page numbers, or citations. Citations are attached \
separately by the application; you must not write them yourself.
- Write clearly and directly, as a good tutor would. Explain the idea rather than \
merely quoting. Use short paragraphs, and lists only where they genuinely help.
- If the excerpts partly answer the question, answer that part and say explicitly \
what the materials do not cover."""

INSUFFICIENT_CONTEXT_ANSWER = (
    "I couldn't find enough information in your uploaded course materials to answer "
    "that. Try rephrasing the question, or upload the material that covers it."
)


class GenerationError(AnchorError):
    """The provider could not produce an answer."""


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, messages: list[ChatMessage]) -> str:
        """Produce an answer from an ordered list of chat messages."""

    def generate_json(self, messages: list[ChatMessage], schema: dict) -> object:
        """Produce structured output conforming to a JSON schema.

        The default implementation asks for JSON in the prompt and parses whatever
        comes back — workable for any provider. Providers with native structured
        output override this and let the API enforce the shape.

        Either way the caller MUST still validate: a schema constrains structure,
        not truth. Nothing here checks that a question is answerable from the
        supplied excerpts, or that the marked answer is the right one.
        """
        instruction = ChatMessage(
            role="user",
            content=(
                "Respond with JSON only — no prose, no code fences — matching this "
                f"schema:\n{json.dumps(schema)}"
            ),
        )
        return parse_json_response(self.generate([*messages, instruction]))


_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_json_response(text: str) -> object:
    """Parse a model's JSON reply, tolerating markdown fences.

    Models wrap JSON in ```json blocks often enough that failing on it would be
    needlessly brittle. Anything else that will not parse is a genuine error.
    """
    cleaned = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise GenerationError(
            "The language model returned output that could not be read as JSON."
        ) from error


class _TransientLLMError(Exception):
    """Internal marker: worth retrying."""


def _retry(operation, describe: str) -> str:
    last_error: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        try:
            return operation()
        except _TransientLLMError as error:
            last_error = error.__cause__ or error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_SECONDS * (2**attempt))

    raise GenerationError(
        f"The {describe} could not be reached after several attempts."
    ) from last_error


class GeminiLLMProvider(LLMProvider):
    """Gemini text generation via the google-genai SDK.

    The message shape differs from OpenAI's — Gemini takes the system prompt as a
    separate `system_instruction` rather than a message with `role: "system"` — so
    the shared `ChatMessage` list is split here. Every prompt rule is unchanged:
    the same `SYSTEM_PROMPT` governs both providers, so grounding behaviour does
    not drift when the provider changes.
    """

    def __init__(self, client=None) -> None:
        if client is None:
            if not settings.GEMINI_API_KEY:
                raise ProviderNotConfiguredError("gemini", "GEMINI_API_KEY")

            from google import genai

            client = genai.Client(api_key=settings.GEMINI_API_KEY)

        self._client = client
        self._model = settings.GEMINI_LLM_MODEL

    def generate(self, messages: list[ChatMessage]) -> str:
        from google.genai import types

        system_instruction = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        prompt = "\n\n".join(
            message.content for message in messages if message.role != "system"
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=TEMPERATURE,
        )

        def call() -> str:
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=prompt, config=config
                )
            except Exception as error:
                raise _classify_gemini_error(error) from error

            text = getattr(response, "text", None)
            if not text or not text.strip():
                # A safety block or an exhausted output budget both land here.
                raise GenerationError(
                    "The language model returned an empty answer. It may have "
                    "declined to respond to this question."
                )
            return text.strip()

        return _retry(call, "language model")

    def generate_json(self, messages: list[ChatMessage], schema: dict) -> object:
        """Uses Gemini's native `response_schema`, so the API enforces the shape."""
        from google.genai import types

        system_instruction = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        prompt = "\n\n".join(
            message.content for message in messages if message.role != "system"
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_json_schema=schema,
        )

        def call() -> str:
            try:
                response = self._client.models.generate_content(
                    model=self._model, contents=prompt, config=config
                )
            except Exception as error:
                raise _classify_gemini_error(error) from error

            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise GenerationError(
                    "The language model returned an empty response. It may have "
                    "declined to answer."
                )
            return text.strip()

        return parse_json_response(_retry(call, "language model"))


def _classify_gemini_error(error: Exception) -> Exception:
    """Retry transport and rate-limit failures; fail fast on everything else."""
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(error).lower()

    if status in (408, 429, 500, 502, 503, 504) or any(
        marker in message
        for marker in ("rate limit", "resource_exhausted", "timeout", "unavailable")
    ):
        return _TransientLLMError(str(error))

    if status in (401, 403) or "api key" in message or "permission" in message:
        return GenerationError("The AI provider rejected the credentials.")

    return GenerationError(
        f"The language model rejected the request ({status or 'error'})."
    )


class OpenAIChatProvider(LLMProvider):
    """OpenAI chat completions. Optional; selected via AI_PROVIDER=openai."""

    def __init__(self, client=None) -> None:
        if client is None:
            if not settings.OPENAI_API_KEY:
                raise ProviderNotConfiguredError("openai", "OPENAI_API_KEY")

            from openai import OpenAI

            client = OpenAI(api_key=settings.OPENAI_API_KEY)

        self._client = client
        self._model = settings.OPENAI_LLM_MODEL

    def generate(self, messages: list[ChatMessage]) -> str:
        from openai import APIConnectionError, APIStatusError, RateLimitError

        def call() -> str:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    temperature=TEMPERATURE,
                    messages=[
                        {"role": message.role, "content": message.content}
                        for message in messages
                    ],
                )
            except (RateLimitError, APIConnectionError) as error:
                raise _TransientLLMError(str(error)) from error
            except APIStatusError as error:
                raise GenerationError(
                    f"The language model rejected the request ({error.status_code})."
                ) from error

            content = response.choices[0].message.content if response.choices else None
            if not content or not content.strip():
                raise GenerationError("The language model returned an empty answer.")
            return content.strip()

        return _retry(call, "language model")

    def generate_json(self, messages: list[ChatMessage], schema: dict) -> object:
        """Uses OpenAI JSON mode. The schema is described in the prompt, since
        strict json_schema support varies by model."""
        from openai import APIConnectionError, APIStatusError, RateLimitError

        described = [
            *messages,
            ChatMessage(
                role="user",
                content=f"Respond with JSON matching this schema:\n{json.dumps(schema)}",
            ),
        ]

        def call() -> str:
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    temperature=TEMPERATURE,
                    response_format={"type": "json_object"},
                    messages=[{"role": m.role, "content": m.content} for m in described],
                )
            except (RateLimitError, APIConnectionError) as error:
                raise _TransientLLMError(str(error)) from error
            except APIStatusError as error:
                raise GenerationError(
                    f"The language model rejected the request ({error.status_code})."
                ) from error

            content = response.choices[0].message.content if response.choices else None
            if not content or not content.strip():
                raise GenerationError("The language model returned an empty answer.")
            return content.strip()

        return parse_json_response(_retry(call, "language model"))


def build_context(
    chunks: list[RetrievedChunk], max_tokens: int
) -> tuple[str, list[RetrievedChunk]]:
    """Assemble the excerpt block, and report which chunks actually fitted.

    Returning the used chunks matters: citations must describe what the model was
    actually shown, not everything retrieval happened to find.

    Each excerpt is labelled with its source so the model can say "the lecture on
    congestion control covers…", but the labels are for the model's benefit only —
    citation metadata is taken from the database rows, never parsed back out of the
    generated text.
    """
    from app.services.rag.chunking import count_tokens

    blocks: list[str] = []
    used: list[RetrievedChunk] = []
    total = 0

    for position, chunk in enumerate(chunks, start=1):
        block = (
            f'[Excerpt {position}] From "{chunk.document_name}", page '
            f"{chunk.page_number}:\n{chunk.content}"
        )
        tokens = count_tokens(block)

        if total + tokens > max_tokens:
            # Chunks arrive best-first, so stopping here drops the weakest matches.
            break

        blocks.append(block)
        used.append(chunk)
        total += tokens

    return "\n\n".join(blocks), used


def build_messages(question: str, context: str) -> list[ChatMessage]:
    user_content = (
        f"Course material excerpts:\n\n{context}\n\n---\n\nStudent's question: {question}"
    )
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_content),
    ]


_LLM_PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiLLMProvider,
    "openai": OpenAIChatProvider,
}


def get_llm_provider() -> LLMProvider:
    """The single place generation-provider selection happens."""
    provider = _LLM_PROVIDERS.get(settings.AI_PROVIDER)
    if provider is None:  # pragma: no cover - Literal keeps this unreachable
        raise GenerationError(f"Unknown AI provider '{settings.AI_PROVIDER}'.")
    return provider()
