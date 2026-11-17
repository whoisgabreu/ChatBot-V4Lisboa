from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPT_EXTENSIONS = {".md", ".txt"}
SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class PromptManager:
    """Carrega system prompts de arquivos e recarrega automaticamente quando mudam."""

    def __init__(self, prompts_dir: Path, default_file: str) -> None:
        self.prompts_dir = Path(prompts_dir)
        self.default_name = self._normalize(default_file)
        self._cache: dict[str, tuple[int, str]] = {}

    @property
    def default_path(self) -> Path:
        return self._path(self.default_name)

    def _normalize(self, name: str) -> str:
        name = name.strip()
        if name.lower().endswith((".md", ".txt")):
            name = name.rsplit(".", 1)[0]
        return name

    def normalize_name(self, name: str) -> str:
        return self._normalize(name)

    def _path(self, name: str) -> Path:
        normalized = self._normalize(name)
        if not SAFE_NAME_RE.match(normalized):
            raise ValueError(f"nome de prompt invalido: {name!r}")
        for ext in PROMPT_EXTENSIONS:
            candidate = self.prompts_dir / f"{normalized}{ext}"
            if candidate.is_file():
                return candidate
        return self.prompts_dir / f"{normalized}.md"

    def list(self) -> list[str]:
        if not self.prompts_dir.is_dir():
            return []
        return sorted(
            {
                path.stem
                for path in self.prompts_dir.iterdir()
                if path.is_file() and path.suffix.lower() in PROMPT_EXTENSIONS
            }
        )

    def exists(self, name: str) -> bool:
        try:
            return self._path(name).is_file()
        except ValueError:
            return False

    def get(self, name: str | None = None) -> str:
        target = self._normalize(name) if name else self.default_name
        path = self._path(target)
        if not path.is_file():
            if target != self.default_name:
                logger.warning("prompt %r nao encontrado, usando %r", target, self.default_name)
                return self.get(None)
            raise FileNotFoundError(f"system prompt nao encontrado: {path}")

        mtime = path.stat().st_mtime_ns
        cached = self._cache.get(path.name)
        if cached and cached[0] == mtime:
            return cached[1]

        content = path.read_text(encoding="utf-8").strip()
        self._cache[path.name] = (mtime, content)
        logger.info("system prompt carregado: %s", path)
        return content

    @staticmethod
    def render(template: str, **values: object) -> str:
        result = template
        for key, value in values.items():
            result = result.replace("{{" + key + "}}", str(value))
        if "{{date}}" in result:
            result = result.replace("{{date}}", datetime.now().strftime("%d/%m/%Y"))
        if "{{time}}" in result:
            result = result.replace("{{time}}", datetime.now().strftime("%H:%M"))
        return result
