import re


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 32)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # Rejoin only a line ending in a letter followed by a lowercase continuation.
    text = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "-", text)
    text = re.sub(r"(?<=[A-Za-z])\n(?=[a-z])", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
