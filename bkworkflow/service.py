"""Shared service layer backing both the zero-code Web Workbench and WorkBuddy MCP Server."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from bkworkflow.cleaner import (
    assess_viral,
    detect_platform,
    extract_clean_url,
    extract_hashtags,
    extract_title_and_author,
    extract_video_id,
    format_hashtags,
    format_metrics_summary,
    parse_metrics_text,
    split_keywords,
)
from bkworkflow.feishu_cli import (
    PROJECT_ROOT,
    base_batch_create,
    base_batch_update,
    base_list_records,
    load_config,
)
from bkworkflow.ingestor import load_raw_items, normalize_item

# Simple in-memory TTL cache to keep Web UI snappy while staying fresh
_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL_SEC = 20.0


def get_lan_ip() -> str:
    """Return real local LAN IPv4 (avoiding Clash/TUN 198.18.x.x virtual adapters)."""
    try:
        hostname = socket.gethostname()
        candidates = socket.gethostbyname_ex(hostname)[2]
        for prefix in ("192.168.", "10.", "172."):
            for ip in candidates:
                if ip.startswith(prefix) and not ip.startswith("198.18."):
                    return ip
        for ip in candidates:
            if not ip.startswith(("127.", "169.254.", "198.18.")):
                return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("198.18."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def _clean_url_cell(val: Any) -> str:
    """Feishu Base text(url) cells return Markdown '[text](https://...)'; unwrap to bare URL."""
    s = str(val or "").strip()
    if not s:
        return ""
    m = re.search(r"\((https?://[^)\s]+)\)", s)
    if m:
        return m.group(1)
    return extract_clean_url(s) or s


def invalidate_cache(table_key: str | None = None) -> None:
    if table_key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(table_key, None)


def _cfg() -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("base_token"):
        raise RuntimeError("config.json 未配置 base_token，请先运行 scripts/setup_feishu_base.py")
    return cfg


def _first_select(val: Any) -> str:
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val or "")


def _get_table(table_key: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force_refresh and table_key in _CACHE:
        ts, data = _CACHE[table_key]
        if now - ts < CACHE_TTL_SEC:
            return data
    cfg = _cfg()
    rows = base_list_records(cfg["base_token"], cfg["tables"][table_key])
    _CACHE[table_key] = (now, rows)
    return rows


def get_dashboard_summary(*, force_refresh: bool = False) -> dict[str, Any]:
    cfg = _cfg()
    kws = _get_table("keywords", force_refresh=force_refresh)
    cands = _get_table("candidates", force_refresh=force_refresh)
    decs = _get_table("deconstruct", force_refresh=force_refresh)

    kw_pending = sum(1 for r in kws if _first_select(r.get("采集状态")) == "待采")
    kw_done = sum(1 for r in kws if _first_select(r.get("采集状态")) == "已采")

    cand_approved = sum(1 for r in cands if _first_select(r.get("审核状态")) == "入库")
    cand_review = sum(1 for r in cands if _first_select(r.get("审核状态")) == "待复核")
    cand_pending = sum(1 for r in cands if _first_select(r.get("审核状态")) == "待审")
    cand_hot = sum(1 for r in cands if "高优爆款" in str(r.get("防刷量预警") or ""))
    cand_fake = sum(1 for r in cands if "刷量" in str(r.get("防刷量预警") or ""))

    dec_need_ai = sum(
        1
        for r in decs
        if not str(r.get("核心观点") or "").strip() and str(r.get("视频文案原文") or "").strip()
    )
    dec_need_text = sum(1 for r in decs if not str(r.get("视频文案原文") or "").strip())
    dec_unreflowed = sum(
        1
        for r in decs
        if not r.get("已回流词库")
        and (str(r.get("内容关键词") or "").strip() or str(r.get("衍生话题标签") or "").strip())
    )

    return {
        "base_name": cfg.get("base_name", "爆款话题挖掘·自动化工作台"),
        "base_token": cfg["base_token"],
        "base_url": cfg["base_url"],
        "app_url": cfg.get("app_url", ""),
        "lan_ip": get_lan_ip(),
        "counts": {
            "keywords_total": len(kws),
            "keywords_pending": kw_pending,
            "keywords_done": kw_done,
            "candidates_total": len(cands),
            "candidates_approved": cand_approved,
            "candidates_review": cand_review,
            "candidates_pending": cand_pending,
            "candidates_hot": cand_hot,
            "candidates_fake": cand_fake,
            "deconstruct_total": len(decs),
            "deconstruct_need_ai": dec_need_ai,
            "deconstruct_need_text": dec_need_text,
            "deconstruct_unreflowed": dec_unreflowed,
        },
    }


def list_keywords(
    *,
    status: str | None = None,
    platform: str | None = None,
    limit: int = 100,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    rows = _get_table("keywords", force_refresh=force_refresh)
    out = []
    for r in rows:
        st = _first_select(r.get("采集状态"))
        if status and status != "全部" and st != status:
            continue
        plats = r.get("目标平台") or []
        if platform and platform != "全部" and plats and platform not in plats:
            continue
        out.append(
            {
                "record_id": r.get("record_id", ""),
                "keyword": str(r.get("关键词") or "").strip(),
                "word_type": _first_select(r.get("词类")),
                "source": _first_select(r.get("词源")),
                "platforms": plats,
                "heat": r.get("近30天热度") or 0,
                "status": st,
                "round": str(r.get("轮次") or ""),
                "note": str(r.get("来源说明") or ""),
            }
        )
    out.sort(key=lambda x: (x["status"] != "待采", -(x["heat"] or 0)))
    return out[:limit]


def add_keywords(
    raw_text: str,
    *,
    word_type: str = "概念名词",
    source: str = "初始种子",
    platforms: list[str] | None = None,
    round_name: str = "",
    note: str = "工作台手动添加",
) -> dict[str, Any]:
    cfg = _cfg()
    existing_rows = _get_table("keywords", force_refresh=True)
    existing = {str(r.get("关键词") or "").strip() for r in existing_rows}

    words = split_keywords(raw_text, drop_stopwords=True)
    plats = platforms or ["小红书", "抖音"]
    rname = round_name or dt.date.today().strftime("%m.%d新增")

    to_create = []
    skipped = []
    for w in words:
        if w in existing:
            skipped.append(w)
            continue
        existing.add(w)
        to_create.append(
            {
                "关键词": w,
                "词类": [word_type],
                "词源": [source],
                "目标平台": plats,
                "采集状态": ["待采"],
                "轮次": rname,
                "来源说明": note,
            }
        )

    if to_create:
        base_batch_create(cfg["base_token"], cfg["tables"]["keywords"], to_create)
        invalidate_cache("keywords")

    return {
        "added_count": len(to_create),
        "added": [x["关键词"] for x in to_create],
        "skipped_duplicates": skipped,
    }


def list_candidates(
    *,
    filter_mode: str = "all",
    platform: str = "全部",
    search: str = "",
    limit: int = 120,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    rows = _get_table("candidates", force_refresh=force_refresh)
    q = search.strip().lower()
    out = []
    for r in rows:
        plat = _first_select(r.get("平台"))
        st = _first_select(r.get("审核状态"))
        warn = str(r.get("防刷量预警") or "")
        if platform and platform != "全部" and plat != platform:
            continue
        if filter_mode == "hot" and "高优爆款" not in warn:
            continue
        elif filter_mode == "fake" and "刷量" not in warn:
            continue
        elif filter_mode == "pending" and st != "待审":
            continue
        elif filter_mode == "approved" and st != "入库":
            continue
        elif filter_mode == "review" and st != "待复核":
            continue
        elif filter_mode == "rejected" and st != "淘汰":
            continue

        title = str(r.get("视频标题") or "")
        author = str(r.get("账号") or "")
        kw = str(r.get("命中关键词") or "")
        tags = str(r.get("话题标签") or "")
        if q and q not in f"{title} {author} {kw} {tags}".lower():
            continue

        score = r.get("爆款得分")
        try:
            score_num = float(score or 0)
        except (TypeError, ValueError):
            score_num = 0.0

        out.append(
            {
                "record_id": r.get("record_id", ""),
                "title": title,
                "platform": plat,
                "video_id": str(r.get("视频ID") or ""),
                "keyword": kw,
                "author": author,
                "url": _clean_url_cell(r.get("视频链接")),
                "likes": int(r.get("点赞数") or 0),
                "comments": int(r.get("评论数") or 0),
                "saves": int(r.get("收藏数") or 0),
                "shares": int(r.get("分享数") or 0),
                "score": int(round(score_num)),
                "comment_ratio": r.get("评赞比") or 0,
                "save_ratio": r.get("藏赞比") or 0,
                "warning": warn,
                "tags": tags,
                "round": str(r.get("采集轮次") or ""),
                "status": st,
                "note": str(r.get("备注") or ""),
            }
        )

    out.sort(key=lambda x: (x["score"], x["likes"]), reverse=True)
    return out[:limit]


def update_candidate_status(record_id: str, new_status: str) -> dict[str, Any]:
    if new_status not in ("待审", "入库", "待复核", "淘汰"):
        raise ValueError(f"非法状态: {new_status}")
    cfg = _cfg()
    base_batch_update(
        cfg["base_token"],
        cfg["tables"]["candidates"],
        {record_id: {"审核状态": [new_status]}},
    )
    invalidate_cache("candidates")
    return {"ok": True, "record_id": record_id, "status": new_status}


def parse_pasted_share_texts(
    raw_text: str,
    *,
    default_platform: str = "",
    default_keyword: str = "",
    round_name: str = "",
) -> list[dict[str, Any]]:
    """Smart parser: accepts JSON array, CSV, or freeform pasted XHS/Douyin share links (one per block/line)."""
    s = raw_text.strip()
    if not s:
        return []

    rname = round_name or dt.date.today().strftime("%m.%d导入")

    # 1) Try JSON first
    if s.startswith("[") or s.startswith("{"):
        try:
            obj = json.loads(s)
            items = obj if isinstance(obj, list) else (obj.get("items") or obj.get("data") or [obj])
            out = []
            for raw in items:
                if isinstance(raw, dict):
                    rec = normalize_item(
                        raw,
                        default_platform=default_platform,
                        default_keyword=default_keyword,
                        round_name=rname,
                    )
                    if rec:
                        out.append(rec)
            if out:
                return out
        except json.JSONDecodeError:
            pass

    # 2) Freeform share links: split by blank lines, or by lines containing http(s)://
    blocks = re.split(r"\n\s*\n+", s)
    if len(blocks) == 1 and len(re.findall(r"https?://", s)) > 1:
        blocks = [ln for ln in s.splitlines() if ln.strip()]

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blk in blocks:
        url = extract_clean_url(blk)
        if not url:
            continue
        vid = extract_video_id(url)
        if vid in seen:
            continue
        seen.add(vid)
        plat = detect_platform(blk, default=default_platform or "抖音")
        title, author = extract_title_and_author(blk)
        m = parse_metrics_text(blk)
        tags = extract_hashtags(blk)
        assess = assess_viral(m["likes"], m["comments"], m["saves"], m["shares"])
        out.append(
            {
                "视频标题": title or f"{default_keyword or '导入'} 相关视频",
                "平台": [plat],
                "视频ID": vid,
                "命中关键词": default_keyword,
                "账号": author,
                "视频链接": url,
                "点赞数": m["likes"],
                "评论数": m["comments"],
                "收藏数": m["saves"],
                "分享数": m["shares"],
                "话题标签": format_hashtags(tags),
                "采集轮次": rname,
                "审核状态": [assess.suggested_status],
                "备注": assess.reason,
            }
        )
    return out


def ingest_candidate_records(
    records: list[dict[str, Any]],
    *,
    mark_keywords_done: bool = True,
) -> dict[str, Any]:
    cfg = _cfg()
    bt = cfg["base_token"]
    existing = _get_table("candidates", force_refresh=True)
    existing_ids = {str(r.get("视频ID") or "").strip() for r in existing}

    to_create = []
    duplicates = 0
    touched_kws: set[str] = set()
    seen_batch: set[str] = set()

    for rec in records:
        vid = str(rec.get("视频ID") or "").strip()
        kw = str(rec.get("命中关键词") or "").strip()
        if kw:
            touched_kws.add(kw)
        if not vid or vid in existing_ids or vid in seen_batch:
            duplicates += 1
            continue
        seen_batch.add(vid)
        to_create.append(rec)

    if to_create:
        base_batch_create(bt, cfg["tables"]["candidates"], to_create)
        invalidate_cache("candidates")

    marked_done = 0
    if mark_keywords_done and touched_kws:
        kws = _get_table("keywords", force_refresh=True)
        updates = {}
        for r in kws:
            kw = str(r.get("关键词") or "").strip()
            if kw in touched_kws and _first_select(r.get("采集状态")) == "待采":
                updates[r["record_id"]] = {"采集状态": ["已采"]}
        if updates:
            base_batch_update(bt, cfg["tables"]["keywords"], updates)
            invalidate_cache("keywords")
            marked_done = len(updates)

    return {
        "inserted": len(to_create),
        "duplicates_skipped": duplicates,
        "keywords_marked_done": marked_done,
    }


def ingest_from_file(
    file_path: str | Path,
    *,
    platform: str = "",
    keyword: str = "",
    round_name: str = "",
    mark_keywords_done: bool = True,
) -> dict[str, Any]:
    raw_items = load_raw_items(Path(file_path))
    rname = round_name or dt.date.today().strftime("%m.%d导入")
    normalized = []
    for raw in raw_items:
        rec = normalize_item(
            raw,
            default_platform=platform,
            default_keyword=keyword,
            round_name=rname,
        )
        if rec:
            normalized.append(rec)
    res = ingest_candidate_records(normalized, mark_keywords_done=mark_keywords_done)
    res["raw_loaded"] = len(raw_items)
    return res


def sync_approved_to_deconstruct() -> dict[str, Any]:
    cfg = _cfg()
    bt = cfg["base_token"]
    cands = _get_table("candidates", force_refresh=True)
    decs = _get_table("deconstruct", force_refresh=True)
    existing_ids = {str(r.get("视频ID") or "").strip() for r in decs}

    new_decs = []
    for r in cands:
        if _first_select(r.get("审核状态")) != "入库":
            continue
        vid = str(r.get("视频ID") or "").strip()
        if not vid or vid in existing_ids:
            continue
        existing_ids.add(vid)
        new_decs.append(
            {
                "视频标题": str(r.get("视频标题") or ""),
                "平台": r.get("平台") or ["抖音"],
                "账号": str(r.get("账号") or ""),
                "视频链接": str(r.get("视频链接") or ""),
                "视频ID": vid,
                "爆款数据摘要": format_metrics_summary(
                    int(r.get("点赞数") or 0),
                    int(r.get("评论数") or 0),
                    int(r.get("收藏数") or 0),
                    int(r.get("分享数") or 0),
                ),
                "视频文案原文": "",
                "核心观点": "",
                "内容关键词": "",
                "衍生话题标签": str(r.get("话题标签") or ""),
                "二创切入点": "",
                "已回流词库": False,
                "来源轮次": str(r.get("采集轮次") or ""),
            }
        )

    if new_decs:
        base_batch_create(bt, cfg["tables"]["deconstruct"], new_decs)
        invalidate_cache("deconstruct")

    return {"synced_new": len(new_decs)}


def list_deconstructs(*, only_pending: bool = False, limit: int = 80, force_refresh: bool = False) -> list[dict[str, Any]]:
    rows = _get_table("deconstruct", force_refresh=force_refresh)
    out = []
    for r in rows:
        core = str(r.get("核心观点") or "").strip()
        transcript = str(r.get("视频文案原文") or "").strip()
        if only_pending and core:
            continue
        out.append(
            {
                "record_id": r.get("record_id", ""),
                "title": str(r.get("视频标题") or ""),
                "platform": _first_select(r.get("平台")),
                "author": str(r.get("账号") or ""),
                "url": _clean_url_cell(r.get("视频链接")),
                "metrics": str(r.get("爆款数据摘要") or ""),
                "transcript": transcript,
                "core_views": core,
                "keywords": str(r.get("内容关键词") or ""),
                "tags": str(r.get("衍生话题标签") or ""),
                "rewrite": str(r.get("二创切入点") or ""),
                "reflowed": bool(r.get("已回流词库")),
                "round": str(r.get("来源轮次") or ""),
            }
        )
    # Prioritize rows that have transcript but missing core views
    out.sort(key=lambda x: (bool(x["core_views"]), not bool(x["transcript"])))
    return out[:limit]


def save_deconstruct_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = _cfg()
    updates: dict[str, dict[str, Any]] = {}
    field_map = {
        "视频文案原文": ("视频文案原文", "transcript"),
        "核心观点": ("核心观点", "core_views"),
        "内容关键词": ("内容关键词", "keywords"),
        "衍生话题标签": ("衍生话题标签", "tags"),
        "二创切入点": ("二创切入点", "rewrite"),
    }
    for it in items:
        rid = str(it.get("record_id") or "").strip()
        if not rid:
            continue
        patch: dict[str, Any] = {}
        for target_field, aliases in field_map.items():
            for alias in aliases:
                if alias in it and it[alias] is not None and str(it[alias]).strip():
                    patch[target_field] = str(it[alias]).strip()
                    break
        if patch:
            updates[rid] = patch

    if updates:
        base_batch_update(cfg["base_token"], cfg["tables"]["deconstruct"], updates)
        invalidate_cache("deconstruct")
    return {"updated": len(updates)}


def reflow_keywords_to_pool(*, round_name: str = "") -> dict[str, Any]:
    cfg = _cfg()
    bt = cfg["base_token"]
    existing_kws = {
        str(r.get("关键词") or "").strip()
        for r in _get_table("keywords", force_refresh=True)
    }
    decs = _get_table("deconstruct", force_refresh=True)
    rname = round_name or dt.date.today().strftime("%m.%d回流")

    new_kw_records: list[dict[str, Any]] = []
    seen_new: set[str] = set()
    mark_reflowed: dict[str, dict[str, Any]] = {}

    for r in decs:
        if r.get("已回流词库"):
            continue
        raw_kws = str(r.get("内容关键词") or "")
        raw_tags = str(r.get("衍生话题标签") or "")
        if not raw_kws.strip() and not raw_tags.strip():
            continue

        title = str(r.get("视频标题") or "")[:30]
        for kw in split_keywords(raw_kws):
            if kw not in existing_kws and kw not in seen_new:
                seen_new.add(kw)
                new_kw_records.append(
                    {
                        "关键词": kw,
                        "词类": ["概念名词"],
                        "词源": ["AI扒词回流"],
                        "目标平台": ["小红书", "抖音"],
                        "采集状态": ["待采"],
                        "轮次": rname,
                        "来源说明": f"表3回流：《{title}》",
                    }
                )
        for tag in split_keywords(raw_tags.replace("#", "、")):
            if tag not in existing_kws and tag not in seen_new:
                seen_new.add(tag)
                new_kw_records.append(
                    {
                        "关键词": tag,
                        "词类": ["话题标签"],
                        "词源": ["爆款#标签"],
                        "目标平台": ["小红书", "抖音"],
                        "采集状态": ["待采"],
                        "轮次": rname,
                        "来源说明": f"表3标签回流：《{title}》",
                    }
                )
        mark_reflowed[r["record_id"]] = {"已回流词库": True}

    if new_kw_records:
        base_batch_create(bt, cfg["tables"]["keywords"], new_kw_records)
        invalidate_cache("keywords")
    if mark_reflowed:
        base_batch_update(bt, cfg["tables"]["deconstruct"], mark_reflowed)
        invalidate_cache("deconstruct")

    return {
        "new_keywords_added": len(new_kw_records),
        "new_keywords": [x["关键词"] for x in new_kw_records],
        "deconstructs_marked_reflowed": len(mark_reflowed),
    }


def check_keyword_trend(keyword: str, *, quick: bool = True, timeout_sec: int = 75) -> dict[str, Any]:
    skill_dir = PROJECT_ROOT / ".agents" / "skills" / "last30days-skill-cn"
    candidates = list(skill_dir.rglob("last30days.py"))
    if not candidates:
        raise FileNotFoundError(f"未找到 last30days.py: {skill_dir}")
    cmd = [sys.executable, str(candidates[0]), keyword, "--emit", "compact"]
    if quick:
        cmd.append("--quick")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    return {
        "keyword": keyword,
        "returncode": proc.returncode,
        "report": proc.stdout.strip(),
        "log": proc.stderr.strip()[-1500:],
    }


def ai_deconstruct_batch(
    record_ids: list[str],
    *,
    api_base: str,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    """Call any OpenAI-compatible LLM API (DeepSeek / Doubao Ark / Kimi) to deconstruct selected records."""
    if not api_key:
        raise ValueError("请填写大模型 API Key（支持 DeepSeek / 豆包火山方舟 / Kimi 等 OpenAI 兼容接口）")
    decs = {r["record_id"]: r for r in list_deconstructs(only_pending=False, limit=500, force_refresh=True)}
    endpoint = api_base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    results = []
    errors = []
    with httpx.Client(timeout=60.0) as client:
        for rid in record_ids:
            row = decs.get(rid)
            if not row or not row["transcript"]:
                errors.append({"record_id": rid, "error": "缺少视频文案原文"})
                continue
            prompt = (
                "你是教育赛道小红书/抖音爆款运营专家。请对下方口播/图文文案做拆解（自动纠正语音转写错别字），"
                "严格返回纯 JSON 对象（不要 markdown 代码块），包含 4 个键：\n"
                '1. "核心观点": 字符串，3-5条短句判断（用换行分隔），不照抄原文；\n'
                '2. "内容关键词": 字符串，5-8个适合小红书/抖音搜索的具体中长尾名词/地名/场景词（过滤“教育/学习/孩子”等过泛大词），用顿号“、”分隔；\n'
                '3. "衍生话题标签": 字符串，5个高相关话题标签，如 "#教育成本 #剧场效应"；\n'
                '4. "二创切入点": 字符串，1-2句面向家长的强钩子二创选题建议。\n\n'
                f"视频标题：{row['title']}\n文案原文：\n{row['transcript'][:4000]}"
            )
            try:
                resp = client.post(
                    endpoint,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Strip accidental ```json fences
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
                parsed = json.loads(content)
                parsed["record_id"] = rid
                results.append(parsed)
            except Exception as exc:
                errors.append({"record_id": rid, "title": row["title"], "error": str(exc)})

    saved = save_deconstruct_items(results) if results else {"updated": 0}
    return {"updated": saved["updated"], "results": results, "errors": errors}
