"""Docling GPU Service — FastAPI endpoint for PDF→Markdown conversion."""

from __future__ import annotations

import os
import tempfile
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import AcceleratorOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DocItemLabel, DoclingDocument, ListItem, NodeItem, TableItem

log = logging.getLogger("docling_service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")

app = FastAPI(title="Docling GPU Service")

_device = os.environ.get("DOCLING_DEVICE", "cuda")
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        pipeline_options = PdfPipelineOptions(
            artifacts_path=os.environ.get("DOCLING_ARTIFACTS_PATH"),
            accelerator_options=AcceleratorOptions(device=_device),
        )
        pipeline_options.do_table_structure = os.environ.get("PDF_TABLE_STRUCTURE", "true").lower() == "true"
        pipeline_options.do_ocr = False
        _converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        log.info("Docling converter initialized (device=%s)", _device)
    return _converter


class ConvertResponse(BaseModel):
    markdown: str
    pages: int
    status: str


def _items_to_markdown(doc: DoclingDocument) -> str:
    parts: list[str] = []
    for item, _level in doc.iterate_items():
        prov = getattr(item, "prov", None)
        if prov:
            parts.append(f"<!--page:{prov[0].page_no}-->\n")
        if isinstance(item, TableItem):
            grid = item.data.grid
            if grid and grid.cols and grid.rows:
                header_idx = item.data.table_config.header_row_separators[0] if item.data.table_config and item.data.table_config.header_row_separators else 0
                lines = []
                for i, row in enumerate(grid):
                    if not row:
                        continue
                    cells = [cell.text if cell and hasattr(cell, "text") else str(cell) for cell in row]
                    lines.append("| " + " | ".join(cells) + " |")
                    if i == header_idx:
                        lines.append("| " + " | ".join("---" for _ in cells) + " |")
                parts.append("\n".join(lines) + "\n")
                continue
            md = item.export_to_markdown(doc)
            if md:
                parts.append(md + "\n")
            continue
        if isinstance(item, (ListItem, NodeItem)):
            text = item.text if hasattr(item, "text") else ""
            if text:
                parts.append(text + "\n")
            continue
        text = item.text if hasattr(item, "text") else ""
        if text:
            parts.append(text + "\n")
    return "".join(parts)


@app.get("/health")
async def health():
    return {"status": "ok", "device": _device}


@app.post("/convert", response_model=ConvertResponse)
async def convert(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        converter = _get_converter()
        result = converter.convert(tmp_path)

        if result.status == ConversionStatus.SUCCESS:
            markdown = _items_to_markdown(result.document)
        else:
            log.warning("Conversion issues (%s), falling back to export", result.status)
            markdown = result.document.export_to_markdown()

        pages = len(result.document.pages) if hasattr(result.document, "pages") else 0

        return ConvertResponse(
            markdown=markdown,
            pages=pages,
            status=str(result.status),
        )
    except Exception as e:
        log.error("Conversion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.on_event("startup")
async def startup():
    _get_converter()
    log.info("Docling GPU Service ready (device=%s)", _device)
