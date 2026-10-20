import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import jieba

DEFAULT_USERDICT_PATH = (
    Path(__file__).parents[3] / "data" / "userdict.txt"
)
@lru_cache(maxsize=1)
def _initialize_jieba(userdict_path: Path = DEFAULT_USERDICT_PATH) -> None:
    if not userdict_path.exists():
        raise FileNotFoundError(
            f"jieba user dictionary not found:{userdict_path}"
        )
    jieba.setLogLevel(logging.ERROR)
    jieba.load_userdict(str(userdict_path))
    jieba.initialize()
def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)

    text =text.translate(
        {
            ord("\u200b"): None,
            ord("\u200c"): None,
            ord("\u200d"): None,
            ord("\ufeff"): None,
            }
    )
    text = text.replace("\xa0", " ")
    text = text.replace("\u202f", " ")
    text = text.replace("\t", " ")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
def _tokenize(text:str) -> list[str]:
    _initialize_jieba()

    normalized = normalize_text(text)
    raw_tokens = jieba.cut_for_search(normalized)
    tokens: list[str] = []
    for token in raw_tokens:
        token = token.strip().casefold()

        if not token:
            continue
        if not any(character.isalnum() for character in token):
            continue
        tokens.append(token)
    return tokens
def build_search_token(text:str) -> list[str]:
    return _tokenize(text)
def extract_search_token(text:str) -> list[str]:
    tokens = build_search_token(text)
    return  list(dict.fromkeys(tokens))
