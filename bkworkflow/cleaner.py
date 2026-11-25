"""Data cleaning, URL normalization, metric parsing, and anti-fake-like scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff\"'<>）)】]+")
XHS_ID_RE = re.compile(r"xiaohongshu\.com/(?:discovery/item|explore)/([0-9a-zA-Z]+)")
DY_SHORT_RE = re.compile(r"v\.douyin\.com/([0-9a-zA-Z_-]+)")
DY_VIDEO_RE = re.compile(r"douyin\.com/(?:video|note)/(\d+)")

# Matches both "2.0万赞" (num before label) and "点赞 6.2 万" (label before num) — single-line only!
METRIC_NUM_FIRST_RE = re.compile(
    r"(\d+(?:\.\d+)?)[ \t]*([万wWkK]?)[ \t]*(赞|点赞|评|评论|藏|收藏|享|分享|转发)"
)
METRIC_LABEL_FIRST_RE = re.compile(
    r"(点赞|评论|收藏|转发|分享|赞|评|藏|享)[ \t]*[:：]?[ \t]*(\d+(?:\.\d+)?)[ \t]*([万wWkK]?)"
)
BARE_FIRST_NUM_RE = re.compile(r"^[ \t]*(\d+(?:\.\d+)?)[ \t]*([万wWkK]?)[ \t]*$")

HASHTAG_RE = re.compile(r"#\s*([^\s#@，。！？；：、\n\r\[\]【】]+)")
XHS_SHARE_TITLE_RE = re.compile(r"【([^】]+?)\s*-\s*([^|】]+?)\s*\|\s*小红书")
DY_SHARE_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?\s+)?(?:[0-9]{2}/[0-9]{2}\s+|:[0-9][ap]m\s+|[A-Za-z0-9@./:_-]{2,12}\s+){1,6}"
)

GENERIC_STOPWORDS = {
    "教育",
    "学习",
    "孩子",
    "家长",
    "父母",
    "视频",
    "内容",
    "问题",
    "方法",
    "思维",
    "上热门",
    "我要上热门",
    "抖音精选",
    "小红书",
    "抖音",
}


def parse_cn_number(num_str: str, unit: str = "") -> int:
    val = float(num_str)
    u = (unit or "").strip().lower()
    if u in ("万", "w"):
        val *= 10_000
    elif u == "k":
        val *= 1_000
    return int(round(val))


def parse_metrics_text(text: str) -> dict[str, int]:
    """Parse multi-line Chinese metric blobs (both '2.0万赞' and '点赞 6.2 万') into structured ints."""
    out = {"likes": 0, "comments": 0, "saves": 0, "shares": 0}
    if not text:
        return out
    s = str(text)

    def _assign(label: str, n: int) -> None:
        if label in ("赞", "点赞"):
            out["likes"] = n
        elif label in ("评", "评论"):
            out["comments"] = n
        elif label in ("藏", "收藏"):
            out["saves"] = n
        elif label in ("享", "分享", "转发"):
            out["shares"] = n

    for label, num_s, unit in METRIC_LABEL_FIRST_RE.findall(s):
        _assign(label, parse_cn_number(num_s, unit))
    for num_s, unit, label in METRIC_NUM_FIRST_RE.findall(s):
        _assign(label, parse_cn_number(num_s, unit))

    # Handle bare first-line likes like "10.9万\n1514评\n5.2万藏\n5.3万享"
    if out["likes"] == 0:
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        if lines:
            m = BARE_FIRST_NUM_RE.match(lines[0])
            if m:
                out["likes"] = parse_cn_number(m.group(1), m.group(2))
    return out


def extract_clean_url(text: str) -> str:
    if not text:
        return ""
    m = URL_RE.search(str(text))
    if not m:
        return ""
    url = m.group(0).rstrip(".,;:!?，。；：！？")
    # Strip noisy xsec_token query on XHS only for display? Keep full XHS URL so link stays clickable!
    return url


def extract_video_id(url: str) -> str:
    if not url:
        return ""
    m = XHS_ID_RE.search(url)
    if m:
        return f"xhs:{m.group(1)}"
    m = DY_VIDEO_RE.search(url)
    if m:
        return f"dy:{m.group(1)}"
    m = DY_SHORT_RE.search(url)
    if m:
        return f"dy:{m.group(1)}"
    # Fallback: strip query string
    return url.split("?", 1)[0]


def detect_platform(text: str, default: str = "") -> str:
    s = str(text or "").lower()
    if "xiaohongshu.com" in s or "xhslink.com" in s or "小红书" in s:
        return "小红书"
    if "douyin.com" in s or "dou音" in s or "抖音" in s:
        return "抖音"
    return default


def extract_title_and_author(share_text: str) -> tuple[str, str]:
    """Extract clean title and author name from XHS/Douyin share blobs."""
    s = str(share_text or "").strip()
    if not s:
        return "", ""

    m = XHS_SHARE_TITLE_RE.search(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Douyin share text: strip leading copy codes and trailing URL + copy hint
    cleaned = URL_RE.sub("", s)
    cleaned = re.sub(r"复制此链接.*$", "", cleaned, flags=re.S).strip()
    cleaned = DY_SHARE_PREFIX_RE.sub("", cleaned).strip()
    # Remove trailing hashtags from title if title is long
    title_only = re.split(r"\s*#\s*", cleaned, maxsplit=1)[0].strip()
    if not title_only:
        title_only = cleaned[:80].strip()
    return title_only[:120], ""


def extract_hashtags(*texts: str) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for t in texts:
        if not t:
            continue
        for raw in HASHTAG_RE.findall(str(t)):
            tag = raw.strip().strip("#")
            if not tag or len(tag) > 30:
                continue
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def format_hashtags(tags: list[str]) -> str:
    return " ".join(f"#{t}" for t in tags)


def split_keywords(text: str, *, drop_stopwords: bool = True) -> list[str]:
    if not text:
        return []
    # Remove parenthetical explanations like （"新时代孩子的好的学习习惯"）
    cleaned = re.sub(r"[（(][^）)]{0,80}[）)]", "", str(text))
    parts = re.split(r"[、,，;；\n\r|/]+", cleaned)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        w = p.strip().lstrip("#").strip()
        if not w or len(w) < 2 or len(w) > 35:
            continue
        if w.startswith("http") or "没有主动显示" in w:
            continue
        if drop_stopwords and w in GENERIC_STOPWORDS:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


@dataclass
class ViralAssessment:
    score: int
    comment_ratio: float
    save_ratio: float
    warning: str
    suggested_status: str
    reason: str


def assess_viral(likes: int, comments: int, saves: int, shares: int) -> ViralAssessment:
    """Compute weighted viral score & anti-fake-like flag matching SOP rules."""
    total = likes + comments + saves + shares
    score = likes * 1 + comments * 3 + saves * 2 + shares * 4
    comment_ratio = round(comments / likes, 4) if likes > 0 else 0.0
    save_ratio = round(saves / likes, 4) if likes > 0 else 0.0

    if total == 0:
        return ViralAssessment(
            score=0,
            comment_ratio=0.0,
            save_ratio=0.0,
            warning="待补数据",
            suggested_status="待审",
            reason="暂无四项互动数据，需采集补全",
        )

    if likes >= 5000 and comment_ratio < 0.005:
        return ViralAssessment(
            score=score,
            comment_ratio=comment_ratio,
            save_ratio=save_ratio,
            warning="⚠️疑似刷量待复核",
            suggested_status="待复核",
            reason=f"点赞 {likes} 但评论仅 {comments}（评赞比 {comment_ratio:.2%} < 0.5%），疑似刷量或抄漏单位",
        )

    if score >= 50_000 or (saves + shares >= 5_000 and comment_ratio >= 0.01):
        return ViralAssessment(
            score=score,
            comment_ratio=comment_ratio,
            save_ratio=save_ratio,
            warning="🔥高优爆款",
            suggested_status="入库",
            reason=f"爆款分 {score:,}，藏赞比 {save_ratio:.1%}，评赞比 {comment_ratio:.1%}",
        )

    return ViralAssessment(
        score=score,
        comment_ratio=comment_ratio,
        save_ratio=save_ratio,
        warning="✅正常",
        suggested_status="待审",
        reason=f"爆款分 {score:,}，互动结构正常",
    )


def format_metrics_summary(likes: int, comments: int, saves: int, shares: int) -> str:
    def fmt(n: int) -> str:
        if n >= 10_000:
            return f"{n / 10_000:.1f}万"
        return str(n)

    if likes + comments + saves + shares == 0:
        return "待补数据"
    return f"{fmt(likes)}赞 / {fmt(comments)}评 / {fmt(saves)}藏 / {fmt(shares)}享"
