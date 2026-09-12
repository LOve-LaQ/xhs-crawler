# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .models import AnalysisReport, FeedNote


def _safe_name(value: str) -> str:
    name = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value.strip())
    return name[:60] or "未命名任务"


def _cell(value: Any, style: int = 0) -> str:
    text = escape("" if value is None else str(value))
    style_attr = f' s="{style}"' if style else ""
    return f'<c t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def write_xlsx(
    path: Path,
    sheet_name: str,
    headers: list[str],
    rows: list[list[Any]],
    *,
    column_widths: list[int] | None = None,
    data_row_height: int = 28,
) -> None:
    """Write a small dependency-free XLSX workbook readable by Excel and WPS."""
    cols = max(1, len(headers))
    widths = column_widths or [18] * cols
    widths = (widths + [18] * cols)[:cols]
    width_xml = "".join(
        f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(widths, start=1)
    )
    row_xml = [
        f'<row r="1">{"".join(_cell(value, 1) for value in headers)}</row>'
    ]
    for row_index, row in enumerate(rows, start=2):
        row_xml.append(
            f'<row r="{row_index}" ht="{data_row_height}" customHeight="1">'
            f'{"".join(_cell(value, 2) for value in row)}</row>'
        )
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<cols>{width_xml}</cols><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font>'
        '<font><b/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFDE9E7"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" applyAlignment="1">'
        '<alignment wrapText="1" vertical="top"/></xf></cellXfs></styleSheet>'
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in {
            "[Content_Types].xml": content_types,
            "_rels/.rels": root_rels,
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": workbook_rels,
            "xl/styles.xml": styles,
            "xl/worksheets/sheet1.xml": worksheet,
        }.items():
            archive.writestr(name, content)


def _full_report_text(report: AnalysisReport) -> str:
    structure = report.content_structure or {}
    tags = report.tag_strategy or {}
    cover = report.cover_style_analysis or {}
    sections = [f"综合结论：{report.summary or '暂无'}"]
    if report.key_findings:
        sections.append("关键发现：" + "；".join(report.key_findings))
    if report.title_formulas:
        sections.append("标题公式：" + "；".join(report.title_formulas))
    if structure:
        sections.append(
            "内容结构："
            f"开头 { '、'.join(map(str, structure.get('openingHooks', []))) or '暂无'}；"
            f"正文 {structure.get('bodyPattern', '暂无')}；"
            f"结尾 { '、'.join(map(str, structure.get('endingHooks', []))) or '暂无'}"
        )
    if tags:
        sections.append(
            "标签策略："
            f"常用标签 { '、'.join(map(str, tags.get('commonTags', []))) or '暂无'}；"
            f"建议 { '、'.join(map(str, tags.get('suggestions', []))) or '暂无'}"
        )
    if cover:
        sections.append("封面风格：" + "、".join(map(str, cover.get("commonStyles", []))) or "封面风格：暂无")
    if report.recommendations:
        sections.append("下一步建议：" + "；".join(report.recommendations))
    return "\n".join(sections)


class WorkspaceArchive:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else None

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def set_root(self, root: str | Path) -> None:
        self.root = Path(root)
        for name in ("samples", "reports", "drafts", "logs", "qa"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def task_folder(self, category: str, task_id: str, topic: str) -> Path | None:
        if not self.root:
            return None
        folder = self.root / category / f"{_safe_name(topic)}_{task_id[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def find_task_folder(self, task_id: str, topic: str, task_type: str) -> Path | None:
        if not self.root:
            return None
        categories = (
            ("samples", "reports", "drafts")
            if task_type in {"内容采集", "内容导入"}
            else ("drafts", "reports", "samples")
            if task_type == "内容创作"
            else ("reports", "samples", "drafts")
        )
        name = f"{_safe_name(topic)}_{task_id[:8]}"
        for category in categories:
            folder = self.root / category / name
            if folder.is_dir():
                return folder
        return None

    def save_samples(self, task_id: str, topic: str, notes: list[FeedNote]) -> None:
        folder = self.task_folder("samples", task_id, topic)
        if not folder:
            return
        (folder / "notes.json").write_text(
            json.dumps([note.to_dict(include_secret=False) for note in notes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_xlsx(
            folder / "notes.xlsx",
            "样本",
            ["笔记ID", "标题", "作者", "正文", "点赞", "收藏", "评论", "标签"],
            [[note.note_id, note.title, note.author, note.body, note.liked_count, note.collected_count, note.comment_count, "、".join(note.tags)] for note in notes],
        )

    def save_report(
        self, task_id: str, topic: str, report: AnalysisReport, notes: list[FeedNote]
    ) -> None:
        folder = self.task_folder("reports", task_id, topic)
        if not folder:
            return
        (folder / "report.json").write_text(
            json.dumps(report.raw or report.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        analyses = {
            str(item.get("noteId", "")): str(item.get("analysis") or item.get("claim") or "")
            for item in report.evidence
            if isinstance(item, dict)
        }
        conclusion = _full_report_text(report)
        rows = [
            [
                note.note_id,
                note.title,
                conclusion,
                analyses.get(note.note_id) or report.summary or "模型未返回该样本的单篇分析",
                note.liked_count,
                note.collected_count,
                note.comment_count,
            ]
            for note in notes
        ]
        write_xlsx(
            folder / "report.xlsx",
            "分析报告",
            ["样本ID", "样本标题", "分析结论", "单篇分析结果", "点赞", "收藏", "评论"],
            rows,
            column_widths=[24, 34, 70, 50, 12, 12, 12],
            data_row_height=110,
        )

    def save_comment_table(
        self,
        task_id: str,
        topic: str,
        opportunities: list[dict[str, Any]],
        task_type: str = "竞品分析",
    ) -> None:
        """Archive comment operations beside the analysis report without session data."""
        category = (
            "samples"
            if task_type in {"内容采集", "内容导入"}
            else "drafts"
            if task_type == "内容创作"
            else "reports"
        )
        folder = self.task_folder(category, task_id, topic)
        if not folder:
            return
        factor_names = {
            "intent": "需求明确度",
            "relevance": "回复匹配度",
            "evidence": "事实依据",
            "naturalness": "自然度",
            "conversion": "获客潜力",
        }

        def score_details(item: dict[str, Any]) -> str:
            factors = item.get("score_breakdown") or {}
            if not isinstance(factors, dict):
                return ""
            return "；".join(
                f"{factor_names.get(str(key), key)}：{value}"
                for key, value in factors.items()
            )

        rows = [
            [
                item.get("note_title", ""),
                item.get("commenter_name", ""),
                item.get("comment_content", ""),
                item.get("ai_reply", ""),
                item.get("score", 0),
                score_details(item),
                item.get("qa_matches", ""),
                item.get("status", ""),
                item.get("created_at", ""),
                item.get("commented_at", ""),
            ]
            for item in opportunities
        ]
        write_xlsx(
            folder / "评论表.xlsx",
            "评论表",
            [
                "帖子标题",
                "评论用户",
                "原评论",
                "AI 回复建议",
                "评分",
                "评分明细",
                "问答依据",
                "状态",
                "采集时间",
                "已评论时间",
            ],
            rows,
            column_widths=[34, 18, 44, 48, 10, 42, 24, 14, 22, 22],
            data_row_height=76,
        )

    def save_drafts(self, task_id: str, topic: str, drafts: list[dict[str, Any]]) -> None:
        folder = self.task_folder("drafts", task_id, topic)
        if not folder:
            return
        (folder / "drafts.json").write_text(
            json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_xlsx(
            folder / "drafts.xlsx",
            "草稿方案",
            ["方案", "标题", "正文", "标签", "配图建议"],
            [[index + 1, item.get("title", ""), item.get("content", ""), "、".join(map(str, item.get("tags", []))), item.get("cover_suggestion", "")] for index, item in enumerate(drafts)],
        )

    def copy_assets(self, task_id: str, topic: str, assets: list[Path]) -> None:
        folder = self.task_folder("drafts", task_id, topic)
        if not folder:
            return
        asset_folder = folder / "assets"
        asset_folder.mkdir(exist_ok=True)
        for asset in assets:
            if asset.is_file():
                shutil.copy2(asset, asset_folder / asset.name)

    def save_qa_entries(self, entries: list[dict[str, Any]]) -> None:
        if not self.root:
            return
        folder = self.root / "qa"
        folder.mkdir(parents=True, exist_ok=True)
        public_entries = [
            {
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
                "keywords": str(item.get("keywords", "")),
                "updated_at": str(item.get("updated_at", "")),
            }
            for item in entries
        ]
        (folder / "qa_library.json").write_text(
            json.dumps(public_entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_xlsx(
            folder / "qa_library.xlsx",
            "问答对库",
            ["问题", "标准答案", "关键词", "更新时间"],
            [[item["question"], item["answer"], item["keywords"], item["updated_at"]] for item in public_entries],
            column_widths=[32, 56, 24, 24],
            data_row_height=58,
        )
