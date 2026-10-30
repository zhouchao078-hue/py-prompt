"""静态资源内容哈希指纹。

刻意不引入构建步骤：启动时按文件内容算 8 位哈希，把 index.html 里的
``/static/app.js`` 改写为 ``/static/app.<hash>.js``。目录结构保持不变，
所以 CSS 里的相对引用（``url('./xxx.woff2')``）继续有效。

命中指纹的请求返回 ``immutable`` 长缓存；未带指纹的原始路径仍可访问，
但只给一周缓存，用于字体等被 CSS 相对引用、不在 HTML 里出现的资源。
"""

import hashlib
import re
from pathlib import Path

STATIC_PREFIX = "/static/"

REFERENCE_PATTERN = re.compile(r"/static/([A-Za-z0-9_][A-Za-z0-9_./-]*)")

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
FALLBACK_CACHE = "public, max-age=604800"


def _split_extension(name: str) -> tuple[str, str, str]:
    stem, dot, suffix = name.rpartition(".")

    if not dot:
        return name, "", ""

    return stem, dot, suffix


class AssetManifest:
    """web 目录的内容哈希映射。"""

    def __init__(self, web_dir: Path) -> None:
        self.web_dir = web_dir.resolve()
        self.hashed_url: dict[str, str] = {}
        self.hashed_file: dict[str, Path] = {}
        self._index_html: str | None = None

    @classmethod
    def build(cls, web_dir: Path) -> "AssetManifest":
        manifest = cls(web_dir)

        for path in sorted(manifest.web_dir.rglob("*")):
            if not path.is_file():
                continue

            relative = path.relative_to(manifest.web_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]

            parent, _, name = relative.rpartition("/")
            stem, _, suffix = _split_extension(name)
            hashed_name = (
                f"{stem}.{digest}.{suffix}" if suffix else f"{name}.{digest}"
            )
            hashed_relative = (
                f"{parent}/{hashed_name}" if parent else hashed_name
            )

            manifest.hashed_url[relative] = STATIC_PREFIX + hashed_relative
            manifest.hashed_file[hashed_relative] = path

        return manifest

    def index_html(self, source: Path) -> str:
        """只改写 HTML 里的引用；结果缓存，避免每次请求重算。"""
        if self._index_html is None:
            html = source.read_text(encoding="utf-8")
            self._index_html = REFERENCE_PATTERN.sub(self._rewrite, html)

        return self._index_html

    def _rewrite(self, match: "re.Match[str]") -> str:
        relative = match.group(1)
        return self.hashed_url.get(relative, match.group(0))

    def resolve(self, relative: str) -> tuple[Path, str] | None:
        """返回 (文件, Cache-Control)，找不到返回 None。"""
        cleaned = relative.strip("/")

        if not cleaned:
            return None

        hashed = self.hashed_file.get(cleaned)

        if hashed is not None:
            return hashed, IMMUTABLE_CACHE

        candidate = (self.web_dir / cleaned).resolve()

        if not candidate.is_relative_to(self.web_dir) or not candidate.is_file():
            return None

        return candidate, FALLBACK_CACHE
