import re
from dataclasses import dataclass

FACTUAL = "factual"
EXPLANATION = "explanation"
PROCEDURAL = "procedural"
CREATIVE = "creative"

BASE_RULES = [
    "Use only facts stated in the passages. Never add outside medical knowledge.",
    "Cite the passage after each sentence that uses it, like [1] or [2][3].",
    "Write in plain, friendly language a non-expert can follow.",
    "Do not diagnose, and do not tell anyone to start, stop, or change a medicine or dose. "
    "Where it fits, suggest talking to a doctor, nurse, or pharmacist.",
    "If the question describes a possible emergency (such as chest pain, trouble breathing, a serious fall, "
    "or signs of a stroke), first tell the person to call 911. This is the one statement you may make without a citation.",
    "If the passages do not answer the question, set answerable to false and leave answer empty and cited_passages empty.",
]


@dataclass(frozen=True)
class PromptStrategy:
    intent: str
    style_rules: tuple[str, ...]
    max_words: int
    temperature: float


STRATEGIES = {
    FACTUAL: PromptStrategy(FACTUAL, (
        "The user wants a specific fact. Answer directly in the first sentence.",
        "Give only the requested fact and the minimum context needed; do not add background.",
    ), max_words=80, temperature=0.1),
    EXPLANATION: PromptStrategy(EXPLANATION, (
        "The user wants to understand why or how something works.",
        "Explain causes and effects step by step, connecting ideas so the reasoning is clear.",
        "Use a short everyday comparison only if the passages support it.",
    ), max_words=200, temperature=0.2),
    PROCEDURAL: PromptStrategy(PROCEDURAL, (
        "The user wants practical steps or tips.",
        "Answer as a numbered list of short, concrete actions, one action per line, each with its citation.",
    ), max_words=180, temperature=0.2),
    CREATIVE: PromptStrategy(CREATIVE, (
        "The user wants a creative format, such as a poem, story, song, or memorable saying.",
        "Use the requested format with a warm, encouraging tone, but every health fact must still come from the passages and be cited.",
        "Do not invent statistics, characters' medical outcomes, or advice that is not in the passages.",
    ), max_words=200, temperature=0.7),
}

_PATTERNS = [
    (CREATIVE, re.compile(
        r"\b(poem|rhyme|haiku|limerick|song|lyrics|story|jingle|slogan|creative|fun way|motto)\b", re.I)),
    (PROCEDURAL, re.compile(
        r"\b(how (do|can|should) (i|we|you)|how to|steps?|tips?|ways to|checklist|what should i do|what can i do|plan)\b", re.I)),
    (EXPLANATION, re.compile(
        r"\b(why|explain|how does|how do(es)? .* work|what causes|what happens|difference between|understand|reason)\b", re.I)),
]


_CREATIVE_TOPIC = re.compile(
    r"\b(?:poem|rhyme|haiku|limerick|song|lyrics|story|jingle|slogan|motto)\b.*?\b(?:about|on|for)\s+(.+)", re.I)


def search_query(question: str, intent: str) -> str:
    # Format requests like "write a poem about" pull the embedding away from the health topic.
    if intent == CREATIVE and (match := _CREATIVE_TOPIC.search(question)):
        return match.group(1)
    return question


def classify_intent(question: str) -> str:
    for intent, pattern in _PATTERNS:
        if pattern.search(question):
            return intent
    return FACTUAL


def build_system_instruction(strategy: PromptStrategy) -> str:
    rules = [*BASE_RULES, *strategy.style_rules, f"Keep the answer under {strategy.max_words} words."]
    rules_text = "\n".join(f"- {rule}" for rule in rules)
    return ("You answer health questions from older adults using ONLY the numbered passages you are given.\n"
            f"Question type: {strategy.intent}.\nRules:\n{rules_text}")


def select_prompt(question: str) -> tuple[PromptStrategy, str]:
    strategy = STRATEGIES[classify_intent(question)]
    return strategy, build_system_instruction(strategy)
