from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import List, Optional, Tuple

ARROW_RE = re.compile(r"\s*(?:⇒|=>|→|->)\s*")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
TOKEN_RE = re.compile(
    r"<h2[^>]*>(.*?)</h2>|<h4[^>]*>(.*?)</h4>|<li[^>]*>(.*?)</li>|<blockquote[^>]*>(.*?)</blockquote>",
    re.IGNORECASE | re.DOTALL,
)
LOWER_BETTER = ("마나", "쿨다운", "재사용", "대기시간", "비용")
BUFF_HINTS = ("상향", "증가", "추가", "버프", "강화", "해금")
NERF_HINTS = ("하향", "감소", "삭제", "너프", "약화", "비활성화", "제거")
ROLE_HINTS = ("역할군", "역할", "교체")
SKIP_SECTIONS = ("패치 하이라이트",)


@dataclass
class ChangeItem:
    section: str
    text: str
    kind: str


@dataclass
class PatchSummary:
    title: str
    intro: str
    url: str
    published_at: str
    image_url: Optional[str]
    buffs: List[ChangeItem] = field(default_factory=list)
    nerfs: List[ChangeItem] = field(default_factory=list)
    mixed: List[ChangeItem] = field(default_factory=list)
    others: List[ChangeItem] = field(default_factory=list)


def html_to_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment or "", flags=re.IGNORECASE)
    fragment = re.sub(r"</p>", "\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    text = unescape(fragment)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _numbers(text: str) -> List[float]:
    cleaned = text.replace(",", "")
    return [float(match) for match in NUMBER_RE.findall(cleaned)]


def _value_side(text: str) -> str:
    if ":" in text:
        return text.split(":", 1)[1]
    if "：" in text:
        return text.split("：", 1)[1]
    return text


def classify_change(text: str) -> str:
    if any(hint in text for hint in ROLE_HINTS) and "⇒" in text.replace("=>", "⇒"):
        return "other"

    sides = ARROW_RE.split(_value_side(text), maxsplit=1)
    if len(sides) == 2:
        before = _numbers(sides[0])
        after = _numbers(sides[1])
        if before and after:
            count = min(len(before), len(after))
            diffs = [after[index] - before[index] for index in range(count)]
            diffs = [delta for delta in diffs if delta != 0]
            if diffs:
                lower_is_better = any(token in text for token in LOWER_BETTER) and "회복" not in text
                up = sum(1 for delta in diffs if delta > 0)
                down = sum(1 for delta in diffs if delta < 0)
                if lower_is_better:
                    up, down = down, up
                if up and not down:
                    return "buff"
                if down and not up:
                    return "nerf"
                return "mixed"

    has_buff = any(hint in text for hint in BUFF_HINTS)
    has_nerf = any(hint in text for hint in NERF_HINTS)
    if has_buff and not has_nerf:
        return "buff"
    if has_nerf and not has_buff:
        return "nerf"
    if has_buff and has_nerf:
        return "mixed"
    return "other"


def summarize_patch_html(
    body_html: str,
    title: str,
    url: str,
    published_at: str = "",
    image_url: Optional[str] = None,
    intro_fallback: str = "",
) -> PatchSummary:
    summary = PatchSummary(
        title=title,
        intro="",
        url=url,
        published_at=published_at,
        image_url=image_url,
    )
    if not body_html:
        summary.intro = intro_fallback.strip()
        return summary

    section = "기타"
    for match in TOKEN_RE.finditer(body_html):
        heading, subheading, list_item, quote = match.groups()
        if heading:
            section = html_to_text(heading) or section
            continue
        if subheading:
            section = html_to_text(subheading) or section
            continue
        if quote:
            quote_text = html_to_text(quote)
            if quote_text and not summary.intro:
                summary.intro = quote_text
            continue
        if not list_item:
            continue

        text = html_to_text(list_item)
        if not text:
            continue
        if section in SKIP_SECTIONS:
            continue
        if not ARROW_RE.search(text) and not any(
            hint in text for hint in BUFF_HINTS + NERF_HINTS + ROLE_HINTS
        ):
            continue

        item = ChangeItem(section=section, text=text, kind=classify_change(text))
        if item.kind == "buff":
            summary.buffs.append(item)
        elif item.kind == "nerf":
            summary.nerfs.append(item)
        elif item.kind == "mixed":
            summary.mixed.append(item)
        else:
            summary.others.append(item)

    if not summary.intro:
        summary.intro = intro_fallback.strip()
    return summary


def compact_change_text(text: str) -> str:
    text = text.replace("⇒", "→").replace("=>", "→")
    return re.sub(r"\s+", " ", text).strip()


def group_changes_by_section(items: List[ChangeItem]) -> List[tuple[str, List[ChangeItem]]]:
    grouped: dict[str, List[ChangeItem]] = {}
    order: List[str] = []
    for item in items:
        if item.section not in grouped:
            grouped[item.section] = []
            order.append(item.section)
        grouped[item.section].append(item)
    return [(section, grouped[section]) for section in order]


def format_change_block(heading: str, items: List[ChangeItem]) -> str:
    if not items:
        return ""

    lines = [heading, ""]
    for section, section_items in group_changes_by_section(items):
        lines.append(f"**▸ {section}**")
        for item in section_items:
            lines.append(f"• {compact_change_text(item.text)}")
        lines.append("")
    return "\n".join(lines).strip()


def build_section_fields(items: List[ChangeItem], value_limit: int = 1024) -> List[tuple[str, str]]:
    fields: List[tuple[str, str]] = []
    for section, section_items in group_changes_by_section(items):
        lines: List[str] = []
        omitted = 0
        used = 0
        for item in section_items:
            line = f"• {compact_change_text(item.text)}"
            if len(line) > 240:
                line = line[:237] + "..."
            extra = len(line) + (1 if lines else 0)
            if used + extra > value_limit - 15:
                omitted = len(section_items) - len(lines)
                break
            lines.append(line)
            used += extra

        value = "\n".join(lines) if lines else "—"
        if omitted:
            value += f"\n… 외 **{omitted}**건"
        name = section if len(section) <= 256 else section[:253] + "..."
        fields.append((name, value))
    return fields


def build_patch_stats_line(summary: PatchSummary) -> str:
    parts = [
        f"🔺 상향 **{len(summary.buffs)}**",
        f"🔻 하향 **{len(summary.nerfs)}**",
    ]
    if summary.mixed:
        parts.append(f"⚖️ 조정 **{len(summary.mixed)}**")
    if summary.others:
        parts.append(f"📝 기타 **{len(summary.others)}**")
    return "　·　".join(parts)


def split_message_chunks(text: str, limit: int = 1900) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= limit:
            current = block
            continue

        for line in block.split("\n"):
            line_candidate = f"{current}\n{line}".strip() if current else line
            if len(line_candidate) <= limit:
                current = line_candidate
            else:
                if current:
                    chunks.append(current)
                current = line[: limit - 3] + "..." if len(line) > limit else line

    if current:
        chunks.append(current)
    return chunks


def build_patch_text_chunks(summary: PatchSummary) -> List[str]:
    intro = summary.intro or "공식 패치 노트에서 변경 사항을 정리했습니다."
    if len(intro) > 280:
        intro = intro[:277] + "..."

    header = (
        f"**📌 {summary.title}**\n"
        f"{intro}\n\n"
        f"{build_patch_stats_line(summary)}\n"
        f"🔗 [패치 노트 원문]({summary.url})"
    )

    body_blocks = []
    for heading, items in (
        ("**🔺 상향**", summary.buffs),
        ("**🔻 하향**", summary.nerfs),
        ("**⚖️ 조정**", summary.mixed),
        ("**📝 기타 변경**", summary.others),
    ):
        block = format_change_block(heading, items)
        if block:
            body_blocks.append(block)

    if not body_blocks:
        body_blocks.append("규칙으로 나눌 변경 줄을 찾지 못했습니다. 원문을 확인해 주세요.")

    full_text = header + "\n\n" + ("─" * 28) + "\n\n" + "\n\n".join(body_blocks)
    return split_message_chunks(full_text)


def format_change_lines(items: List[ChangeItem], limit: int = 1024) -> Tuple[str, int]:
    if not items:
        return ("없음", 0)

    lines: List[str] = []
    omitted = 0
    used = 0
    for item in items:
        label = f"• [{item.section}] {item.text}"
        if len(label) > 220:
            label = label[:217] + "..."
        extra = len(label) + (1 if lines else 0)
        if used + extra > limit - 20:
            omitted = len(items) - len(lines)
            break
        lines.append(label)
        used += extra

    text = "\n".join(lines) if lines else "없음"
    if omitted:
        suffix = f"\n… 외 {omitted}건"
        if len(text) + len(suffix) <= limit:
            text += suffix
    return text, omitted
