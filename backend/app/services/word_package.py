"""Word OOXML 包预处理：模板 (.dotx) 等可被 python-docx 打开。"""

from __future__ import annotations

import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

# python-docx 只认 document.main，不认 template.main
_TEMPLATE_TO_DOCUMENT = (
    (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    (
        "application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
        "application/vnd.ms-word.document.macroEnabled.main+xml",
    ),
)


def normalize_word_package_inplace(path: Path) -> bool:
    """
    若为 Word 模板包（ContentType=template.main），就地改成 document.main。

    Returns:
        True 表示已改写；False 表示无需处理或非 zip Word 包。
    """
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path, "r") as zin:
            try:
                ct_text = zin.read("[Content_Types].xml").decode("utf-8")
            except KeyError:
                return False
            new_ct = ct_text
            for src, dst in _TEMPLATE_TO_DOCUMENT:
                new_ct = new_ct.replace(src, dst)
            if new_ct == ct_text:
                return False

            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    data = zin.read(info.filename)
                    if info.filename == "[Content_Types].xml":
                        data = new_ct.encode("utf-8")
                    zout.writestr(info.filename, data)
        path.write_bytes(buf.getvalue())
        logger.info("已将 Word 模板包转为文档包: %s", path)
        return True
    except zipfile.BadZipFile:
        return False


def friendly_docx_open_error(exc: BaseException, filename: str | None = None) -> str:
    """把 python-docx / 包类型错误转成可读提示。"""
    msg = str(exc)
    name = filename or "该文件"
    if "template.main" in msg or "not a Word file" in msg:
        return (
            f"「{name}」是 Word 模板（.dotx）或模板内容类型，未能直接打开。"
            "请在 Word 中「另存为」普通 .docx 后再上传；系统也会尝试自动转换。"
        )
    if re.search(r"not a (Word|zip)", msg, re.I):
        return f"「{name}」不是有效的 Word 文档（.docx）。请另存为 .docx 后重试。"
    return f"无法打开 Word 文件「{name}」: {msg}"
