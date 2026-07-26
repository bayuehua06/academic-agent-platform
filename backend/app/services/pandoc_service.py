"""Pandoc / python-docx 文档转换服务。"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ExportFormat = Literal["docx", "pdf"]


class PandocService:
    """Markdown ↔ Word/PDF 转换引擎。"""

    def __init__(
        self,
        export_dir: Optional[str] = None,
        apa_csl_path: Optional[str] = None,
    ) -> None:
        self.export_dir = Path(export_dir or settings.export_dir)
        self.apa_csl_path = Path(apa_csl_path or settings.apa_csl_path)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def markdown_to_document(
        self,
        content_markdown: str,
        apa_references_block: Optional[str] = None,
        fmt: ExportFormat = "docx",
        filename_stem: Optional[str] = None,
    ) -> Path:
        """
        将 Markdown 正文 + APA References 导出为 docx 或 pdf。

        若系统已安装 pandoc 且存在 apa.csl，则注入 CSL 样式。
        """
        full_md = content_markdown.strip()
        if apa_references_block:
            full_md = f"{full_md}\n\n## References\n\n{apa_references_block.strip()}\n"

        stem = filename_stem or f"draft_{uuid4().hex[:8]}"
        output_path = self.export_dir / f"{stem}.{fmt}"

        # 优先使用 pypandoc
        if shutil.which("pandoc"):
            try:
                import pypandoc

                extra_args = ["--standalone"]
                if self.apa_csl_path.exists() and fmt == "docx":
                    extra_args.extend(["--csl", str(self.apa_csl_path)])

                pypandoc.convert_text(
                    full_md,
                    to=fmt,
                    format="markdown",
                    outputfile=str(output_path),
                    extra_args=extra_args,
                )
                return output_path
            except Exception as exc:  # noqa: BLE001
                logger.warning("pypandoc 转换失败，回退 python-docx: %s", exc)

        if fmt == "pdf":
            raise RuntimeError("PDF 导出需要系统安装 pandoc（及可选 pdflatex/weasyprint）")

        return self._fallback_docx(full_md, output_path)

    def _fallback_docx(self, markdown_text: str, output_path: Path) -> Path:
        """无 pandoc 时使用 python-docx 做简易导出。"""
        from docx import Document

        doc = Document()
        for line in markdown_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                doc.add_heading(stripped[2:], level=1)
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:], level=2)
            elif stripped.startswith("### "):
                doc.add_heading(stripped[4:], level=3)
            else:
                doc.add_paragraph(stripped)
        doc.save(str(output_path))
        return output_path

    def docx_to_markdown(self, docx_path: Path) -> str:
        """将 Word 文档转为 Markdown。"""
        if shutil.which("pandoc"):
            try:
                import pypandoc

                return pypandoc.convert_file(str(docx_path), to="md", format="docx")
            except Exception as exc:  # noqa: BLE001
                logger.warning("pypandoc 导入失败，回退 python-docx: %s", exc)

        return self._fallback_docx_to_md(docx_path)

    def _fallback_docx_to_md(self, docx_path: Path) -> str:
        """无 pandoc 时用 python-docx 提取段落与表格为 Markdown。"""
        from docx import Document

        doc = Document(str(docx_path))
        lines: list[str] = []

        # 段落（含 Heading 样式）
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                lines.append("")
                continue
            style = (para.style.name or "").lower() if para.style else ""
            if "heading 1" in style:
                lines.append(f"# {text}")
            elif "heading 2" in style:
                lines.append(f"## {text}")
            elif "heading 3" in style:
                lines.append(f"### {text}")
            else:
                lines.append(text)

        # 表格：评分 rubric 等常把正文全部放在表内
        for table_idx, table in enumerate(doc.tables):
            if table_idx > 0 or lines:
                lines.append("")
            lines.append(f"### Table {table_idx + 1}")
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cell_text = " ".join(
                        p.text.strip() for p in cell.paragraphs if p.text and p.text.strip()
                    )
                    cells.append(cell_text.replace("|", "\\|") if cell_text else "")
                # 跳过整行空白
                if not any(cells):
                    continue
                lines.append("| " + " | ".join(cells) + " |")

        return "\n\n".join(line for line in lines if line is not None).strip() + "\n"

    def save_upload(self, content: bytes, suffix: str = ".docx") -> Path:
        """保存上传文件到临时目录。"""
        upload_root = Path(settings.upload_dir)
        upload_root.mkdir(parents=True, exist_ok=True)
        path = upload_root / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        return path


pandoc_service = PandocService()
