from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from mistralai.client.models import OCRResponse

from app.ingest.ocr import ocr_pdf_markdown, ocr_to_markdown
from app.llm import MistralProvider


def test_ocr_to_markdown_joins_pages() -> None:
    response = cast(
        OCRResponse,
        SimpleNamespace(
            pages=[
                SimpleNamespace(markdown="# Title\nIntro"),
                SimpleNamespace(markdown="## Section\nBody"),
            ]
        ),
    )
    assert ocr_to_markdown(response) == "# Title\nIntro\n\n## Section\nBody"


def test_ocr_to_markdown_no_pages() -> None:
    response = cast(OCRResponse, SimpleNamespace(pages=[]))
    assert ocr_to_markdown(response) == ""


async def test_ocr_pdf_markdown_roundtrip() -> None:
    provider = MagicMock(spec=MistralProvider)
    provider.ocr_pdf = AsyncMock(
        return_value=cast(
            OCRResponse,
            SimpleNamespace(pages=[SimpleNamespace(markdown="# A\nbody")]),
        )
    )

    markdown = await ocr_pdf_markdown(provider, "mistral-ocr-4-0", "a.pdf", b"%PDF")

    assert markdown == "# A\nbody"
    provider.ocr_pdf.assert_awaited_once()
