from __future__ import annotations

import html

from ..models import AnalysisReport, FeedNote
from .formatting import bullet_list


def report_to_html(report: AnalysisReport, notes: list[FeedNote] | None = None) -> str:
    structure = report.content_structure or {}
    tags = report.tag_strategy or {}
    cover = report.cover_style_analysis or {}
    evidence = {
        str(item.get("noteId", "")): str(item.get("analysis") or item.get("claim") or "")
        for item in report.evidence
        if isinstance(item, dict)
    }
    sample_rows = "".join(
        "<tr>"
        f"<td>{html.escape(note.note_id)}</td>"
        f"<td>{html.escape(note.title)}</td>"
        f"<td>{html.escape(report.summary or '暂无综合结论')}</td>"
        f"<td>{html.escape(evidence.get(note.note_id) or report.summary or '暂无单篇分析')}</td>"
        "</tr>"
        for note in (notes or [])
    )
    sample_table = (
        "<h3>样本分析明细</h3>"
        "<table class='sample-table'><thead><tr><th>样本ID</th><th>样本标题</th><th>分析结论</th>"
        f"<th>单篇分析结果</th></tr></thead><tbody>{sample_rows or '<tr><td colspan=4>暂无样本明细</td></tr>'}</tbody></table>"
    )
    return f"""
    <style>
      body {{ font-family: 'Microsoft YaHei', sans-serif; color:#17212b; line-height:1.65; font-size:13px; }}
      h2 {{ font-size:17px; margin: 4px 0 9px; }}
      h3 {{ font-size:13px; margin:18px 0 6px; color:#d84c43; }}
      p {{ margin: 5px 0; }}
      ul {{ margin: 4px 0 0; padding-left: 20px; }}
      li {{ margin: 4px 0; }}
      .muted {{ color:#88939c; }}
      .quote {{ padding:10px 12px; border-left:3px solid #f45d52; background:#fff5f3; }}
      .tag {{ display:inline-block; padding:3px 7px; margin:3px 4px 0 0; border-radius:5px; background:#ecf8f5; color:#217d6c; }}
      .sample-table {{ width:100%; border-collapse:collapse; margin-top:7px; }}
      .sample-table th, .sample-table td {{ border:1px solid #e2e8ea; padding:7px; text-align:left; vertical-align:top; }}
      .sample-table th {{ color:#54616d; background:#f7f9f9; font-weight:700; }}
    </style>
    <h2>分析结论</h2>
    <p class='quote'>{html.escape(report.summary or "暂无摘要")}</p>
    <h3>关键发现</h3>{bullet_list(report.key_findings)}
    <h3>标题公式</h3>{bullet_list(report.title_formulas)}
    <h3>内容结构</h3>
    <p><b>开头：</b>{html.escape("、".join(map(str, structure.get("openingHooks", []))) or "暂无")}</p>
    <p><b>正文：</b>{html.escape(str(structure.get("bodyPattern", "暂无")))}</p>
    <p><b>结尾：</b>{html.escape("、".join(map(str, structure.get("endingHooks", []))) or "暂无")}</p>
    <h3>标签策略</h3>
    <div>{"".join(f"<span class='tag'>#{html.escape(str(tag))}</span>" for tag in tags.get("commonTags", [])) or "<span class=muted>暂无</span>"}</div>
    <h3>封面风格</h3>{bullet_list([str(x) for x in cover.get("commonStyles", [])])}
    <h3>下一步建议</h3>{bullet_list(report.recommendations)}
    {sample_table}
    """


def report_to_markdown(topic: str, report: AnalysisReport) -> str:
    structure = report.content_structure or {}
    tags = report.tag_strategy or {}
    lines = [f"# {topic} · 小红书内容分析报告", "", "## 分析结论", report.summary or "暂无", ""]
    for heading, items in (
        ("关键发现", report.key_findings),
        ("标题公式", report.title_formulas),
        ("下一步建议", report.recommendations),
    ):
        lines.extend([f"## {heading}", *[f"- {item}" for item in items], ""])
    lines.extend(
        [
            "## 内容结构",
            f"- 开头：{'、'.join(map(str, structure.get('openingHooks', [])))}",
            f"- 正文：{structure.get('bodyPattern', '')}",
            f"- 结尾：{'、'.join(map(str, structure.get('endingHooks', [])))}",
            "",
            "## 标签策略",
            f"- 常用标签：{'、'.join(map(str, tags.get('commonTags', [])))}",
            "",
        ]
    )
    return "\n".join(lines)
