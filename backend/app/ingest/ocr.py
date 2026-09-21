"""OCR-based ingestion of PDF documents.

PDFs are processed through the OCR model, which returns classified blocks with
bounding boxes and a reconstructed markdown rendering per page. The markdown
preserves the heading hierarchy, so section-aware chunking reuses the same
markdown chunker used for plain markdown sources.
"""

from __future__ import annotations

from mistralai.client.models import OCRResponse

from app.llm.provider import MistralProvider


def ocr_to_markdown(response: OCRResponse) -> str:
    return "\n\n".join(page.markdown for page in response.pages)


async def ocr_pdf_markdown(
    provider: MistralProvider,
    model: str,
    file_name: str,
    content: bytes,
) -> str:
    response = await provider.ocr_pdf(model=model, file_name=file_name, content=content)
    return ocr_to_markdown(response)
