import hashlib
import re

from prompt_search_agent.ingest.records import (
    PreparedPromptRecord,
    RawPromptRecord,
)
from prompt_search_agent.search.tokenizer import (
    build_search_token,
    normalize_text,
)

# 分类名里这些词没有区分度，进索引只会制造噪声命中
CATEGORY_STOPWORDS = frozenset(
    {
        "系列",
        "关键词",
        "爆款",
        "图片",
        "素材",
        "合集",
        "大全",
        "版本",
    }
)


def sha256_str(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def normalize_category(category: str | None) -> str:
    """去掉编号与分隔符，只留下有区分度的分类词。

    "2.爆款关键词" -> "爆款关键词"
    "汉服_婚纱"    -> "汉服 婚纱"
    """
    if not category:
        return ""

    text = re.sub(r"\d+", " ", category)
    text = re.sub(r"[_\W]+", " ", text)
    return " ".join(text.split())


def build_search_tokens(
    prompt_text: str,
    category: str | None,
) -> list[str]:
    """正文分词 + 分类分词。

    分类必须进索引：库里有 35 条「汉服」、57 条「婚纱」、34 条「玫瑰」，
    这些词只出现在 category 里，不进索引就永远搜不到。
    """
    prompt_tokens = build_search_token(prompt_text)
    category_text = normalize_category(category)

    if not category_text:
        return prompt_tokens

    category_tokens = [
        token
        for token in build_search_token(category_text)
        if not any(stop in token for stop in CATEGORY_STOPWORDS)
    ]

    return list(dict.fromkeys(prompt_tokens + category_tokens))


def prepare_prompt_records(
    raw_records: list[RawPromptRecord],
) -> list[PreparedPromptRecord]:
    PPRS: list[PreparedPromptRecord] = []
    prepared_by_hash: set[str] = set()

    for raw_record in raw_records:
        if raw_record is None:
            continue

        prompt_text = raw_record.prompt_text
        SH = normalize_text(prompt_text)

        if not SH:
            continue

        content_hash = sha256_str(SH)

        if content_hash in prepared_by_hash:
            continue

        tokens = build_search_tokens(SH, raw_record.category)

        if not tokens:
            continue

        prompt_id = content_hash[:16]

        PPR = PreparedPromptRecord(
            prompt_id=prompt_id,
            prompt_text=SH,
            search_tokens=" ".join(tokens),
            content_hash=content_hash,
            category=raw_record.category,
            source_file=raw_record.source_file,
            source_sheet=raw_record.source_sheet,
            source_row=raw_record.source_row,
        )
        prepared_by_hash.add(content_hash)
        PPRS.append(PPR)

    return PPRS
