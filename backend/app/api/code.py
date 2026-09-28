"""Read-only code viewer for ``file:line`` citations.

A cited file is readable only when at least one indexed code chunk for it is
visible to the caller, so the endpoint cannot be used to browse the container
file system. The path resolves inside the corpus root and never follows a path
outside it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.ingest.pipeline import CORPUS_ROOT
from app.rag.retrieval import acl_fragment, acl_role_tags

router = APIRouter(prefix="/api/code", tags=["code"])

MAX_FILE_CHARS = 200_000

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".sh": "shell",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".sql": "sql",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

PrincipalDep = Annotated[Principal, Depends(get_principal)]


class CodeFile(BaseModel):
    source_uri: str
    path: str
    language: str
    content: str
    line_count: int
    start_line: int | None = None
    end_line: int | None = None
    truncated: bool = False


def corpus_relative_path(source_uri: str) -> str | None:
    """The corpus-relative path of a ``file:`` source, or None when unsafe."""
    if not source_uri.startswith("file:"):
        return None
    relative = source_uri[len("file:") :]
    segments = relative.split("/")
    if (
        not relative
        or relative.startswith("/")
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        return None
    return PurePosixPath(*segments).as_posix()


def resolve_corpus_file(source_uri: str) -> Path | None:
    """Resolve a source to a file inside the corpus root, or None."""
    relative = corpus_relative_path(source_uri)
    if relative is None:
        return None
    root = CORPUS_ROOT.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


async def visible_to_caller(request: Request, principal: Principal, source_uri: str) -> bool:
    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )
    statement = text(
        "SELECT 1 FROM doc_chunks "
        "WHERE source_uri = :source_uri AND source_type = 'code' "
        f"AND {acl_fragment()} LIMIT 1"
    )
    async with engine.connect() as conn:
        found = (
            await conn.execute(
                statement,
                {
                    "source_uri": source_uri,
                    "dept": f"dept:{principal.dept}",
                    "roles": acl_role_tags(principal.role),
                },
            )
        ).scalar_one_or_none()
    return found is not None


@router.get("/file", response_model=CodeFile)
async def read_code_file(
    source_uri: str,
    request: Request,
    principal: PrincipalDep,
    start: int | None = None,
    end: int | None = None,
) -> CodeFile:
    relative = corpus_relative_path(source_uri)
    path = resolve_corpus_file(source_uri) if relative is not None else None
    if (
        relative is None
        or path is None
        or not await visible_to_caller(request, principal, source_uri)
    ):
        # The same answer for "not indexed", "not yours", and "does not exist".
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    try:
        text_content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found") from exc

    truncated = len(text_content) > MAX_FILE_CHARS
    content = text_content[:MAX_FILE_CHARS]
    start_line = max(1, start) if start is not None else None
    end_line = max(1, end) if end is not None else None
    if start_line is not None and end_line is not None and end_line < start_line:
        end_line = start_line
    return CodeFile(
        source_uri=source_uri,
        path=relative,
        language=LANGUAGE_BY_SUFFIX.get(path.suffix, "text"),
        content=content,
        line_count=content.count("\n") + 1,
        start_line=start_line,
        end_line=end_line,
        truncated=truncated,
    )
