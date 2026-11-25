"""Universal ingestion adapter for MediaCrawler, Agent-Reach, and custom JSON/CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from bkworkflow.cleaner import (
    assess_viral,
    detect_platform,
    extract_clean_url,
    extract_hashtags,
    extract_video_id,
    format_hashtags,
    parse_cn_number,
)


def _to_int(val: Any) -> int:
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if s.isdigit():
        return int(s)
    # Handle "2.3万", "1.5w", "1,234"
    s = s.replace(",", "")
    for unit in ("万", "w", "W", "k", "K"):
        if s.endswith(unit):
            try:
                return parse_cn_number(s[:-1], unit)
            except ValueError:
                return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def normalize_item(
    raw: dict[str, Any],
    *,
    default_platform: str = "",
    default_keyword: str = "",
    round_name: str = "",
) -> dict[str, Any] | None:
    """Normalize a MediaCrawler / Agent-Reach / custom video dict into Table 2 record schema."""
    # Detect URL across common schemas (MediaCrawler xhs/dy, Agent-Reach, custom)
    url = (
        raw.get("note_url")
        or raw.get("aweme_url")
        or raw.get("video_url")
        or raw.get("url")
        or raw.get("link")
        or raw.get("视频链接")
        or ""
    )
    url = extract_clean_url(str(url)) or str(url).strip()

    # MediaCrawler note_id / aweme_id fallback URL construction
    note_id = str(raw.get("note_id") or "").strip()
    aweme_id = str(raw.get("aweme_id") or "").strip()
    if not url and note_id:
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
    if not url and aweme_id:
        url = f"https://www.douyin.com/video/{aweme_id}"

    platform = detect_platform(url or raw.get("platform") or default_platform, default=default_platform or "小红书")

    if note_id:
        vid = f"xhs:{note_id}"
    elif aweme_id:
        vid = f"dy:{aweme_id}"
    else:
        vid = str(raw.get("video_id") or raw.get("视频ID") or "").strip() or extract_video_id(url)

    title = str(
        raw.get("title")
        or raw.get("desc")
        or raw.get("视频标题")
        or raw.get("content", "")[:60]
        or ""
    ).strip()
    if not vid and not title:
        return None
    if not vid:
        vid = f"{platform}:{title[:24]}"

    author = str(
        raw.get("nickname")
        or raw.get("author")
        or raw.get("user_nickname")
        or raw.get("账号")
        or ""
    ).strip()

    likes = _to_int(raw.get("liked_count") or raw.get("digg_count") or raw.get("likes") or raw.get("点赞数"))
    comments = _to_int(raw.get("comment_count") or raw.get("comments") or raw.get("评论数"))
    saves = _to_int(raw.get("collected_count") or raw.get("collect_count") or raw.get("saves") or raw.get("收藏数"))
    shares = _to_int(raw.get("share_count") or raw.get("shares") or raw.get("分享数"))

    raw_tags = raw.get("tag_list") or raw.get("tags") or raw.get("话题标签") or ""
    if isinstance(raw_tags, list):
        raw_tags_str = " ".join(f"#{str(t).lstrip('#')}" for t in raw_tags if t)
    else:
        raw_tags_str = str(raw_tags)
    tags = extract_hashtags(raw_tags_str, title, str(raw.get("desc") or ""))

    keyword = str(raw.get("source_keyword") or raw.get("keyword") or raw.get("命中关键词") or default_keyword).strip()
    assess = assess_viral(likes, comments, saves, shares)

    return {
        "视频标题": title[:120] or f"{keyword} 相关视频",
        "平台": [platform],
        "视频ID": vid,
        "命中关键词": keyword,
        "账号": author,
        "视频链接": url,
        "点赞数": likes,
        "评论数": comments,
        "收藏数": saves,
        "分享数": shares,
        "话题标签": format_hashtags(tags),
        "采集轮次": round_name or "自动采集",
        "审核状态": [assess.suggested_status],
        "备注": assess.reason,
    }


def load_raw_items(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".ndjson" or suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "results", "notes", "videos", "records"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ValueError(f"Unsupported JSON shape in {path}")
