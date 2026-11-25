"""Main CLI entrypoint for the bkworkflow Feishu-connected viral discovery flywheel."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from bkworkflow.cleaner import format_hashtags, format_metrics_summary, split_keywords
from bkworkflow.feishu_cli import (
    PROJECT_ROOT,
    base_batch_create,
    base_batch_update,
    base_list_records,
    load_config,
)
from bkworkflow.ingestor import load_raw_items, normalize_item


def _require_cfg() -> dict[str, Any]:
    cfg = load_config()
    if not cfg.get("base_token"):
        raise SystemExit("config.json missing base_token. Run: python scripts/setup_feishu_base.py")
    return cfg


def _first_select(val: Any) -> str:
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val or "")


def cmd_status(_args: argparse.Namespace) -> None:
    cfg = _require_cfg()
    bt = cfg["base_token"]
    t = cfg["tables"]

    kws = base_list_records(bt, t["keywords"])
    cands = base_list_records(bt, t["candidates"])
    decs = base_list_records(bt, t["deconstruct"])

    kw_pending = sum(1 for r in kws if _first_select(r.get("采集状态")) == "待采")
    kw_done = sum(1 for r in kws if _first_select(r.get("采集状态")) == "已采")

    cand_approved = sum(1 for r in cands if _first_select(r.get("审核状态")) == "入库")
    cand_review = sum(1 for r in cands if _first_select(r.get("审核状态")) == "待复核")
    cand_pending = sum(1 for r in cands if _first_select(r.get("审核状态")) == "待审")

    dec_unreflowed = sum(1 for r in decs if not r.get("已回流词库") and (r.get("内容关键词") or r.get("衍生话题标签")))
    dec_need_ai = sum(1 for r in decs if not str(r.get("核心观点") or "").strip())

    print(f"Base: {cfg['base_name']}")
    print(f"URL : {cfg['base_url']}")
    print("-" * 56)
    print(f"01_词库池      : 共 {len(kws):3d} 条 | 待采 {kw_pending:3d} | 已采 {kw_done:3d}")
    print(f"02_候选爆款池  : 共 {len(cands):3d} 条 | 入库 {cand_approved:3d} | 待复核 {cand_review:3d} | 待审 {cand_pending:3d}")
    print(f"03_爆款拆解库  : 共 {len(decs):3d} 条 | 待AI拆解 {dec_need_ai:3d} | 待回流词库 {dec_unreflowed:3d}")


def cmd_next_keywords(args: argparse.Namespace) -> None:
    cfg = _require_cfg()
    kws = base_list_records(cfg["base_token"], cfg["tables"]["keywords"])
    picked: list[dict[str, Any]] = []
    for r in kws:
        if _first_select(r.get("采集状态")) != "待采":
            continue
        platforms = r.get("目标平台") or []
        if args.platform and platforms and args.platform not in platforms:
            continue
        picked.append(
            {
                "record_id": r.get("record_id"),
                "keyword": str(r.get("关键词") or "").strip(),
                "platforms": platforms,
                "heat": r.get("近30天热度") or 0,
                "source": _first_select(r.get("词源")),
            }
        )
    picked.sort(key=lambda x: x["heat"], reverse=True)
    picked = picked[: args.limit]
    if args.csv:
        print(",".join(x["keyword"] for x in picked))
    else:
        print(json.dumps(picked, ensure_ascii=False, indent=2))


def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = _require_cfg()
    bt = cfg["base_token"]
    t_cand = cfg["tables"]["candidates"]
    t_kw = cfg["tables"]["keywords"]

    src = Path(args.file)
    raw_items = load_raw_items(src)
    round_name = args.round or dt.date.today().strftime("%m.%d自动采集")

    existing_cands = base_list_records(bt, t_cand)
    existing_ids = {str(r.get("视频ID") or "").strip() for r in existing_cands}

    to_create: list[dict[str, Any]] = []
    seen_batch: set[str] = set()
    touched_keywords: set[str] = set()

    for raw in raw_items:
        rec = normalize_item(
            raw,
            default_platform=args.platform or "",
            default_keyword=args.keyword or "",
            round_name=round_name,
        )
        if not rec:
            continue
        vid = rec["视频ID"]
        if rec["命中关键词"]:
            touched_keywords.add(rec["命中关键词"])
        if vid in existing_ids or vid in seen_batch:
            continue
        seen_batch.add(vid)
        to_create.append(rec)

    print(f"Loaded {len(raw_items)} raw items -> {len(to_create)} new deduplicated candidates.")
    if to_create:
        base_batch_create(bt, t_cand, to_create)
        print(f"Inserted {len(to_create)} records into 02_候选爆款池.")

    if args.mark_done and touched_keywords:
        kws = base_list_records(bt, t_kw)
        updates = {}
        for r in kws:
            kw = str(r.get("关键词") or "").strip()
            if kw in touched_keywords and _first_select(r.get("采集状态")) == "待采":
                updates[r["record_id"]] = {"采集状态": ["已采"]}
        if updates:
            base_batch_update(bt, t_kw, updates)
            print(f"Marked {len(updates)} keywords as 已采 in 01_词库池.")


def cmd_sync_approved(args: argparse.Namespace) -> None:
    """Copy approved candidates (审核状态=入库) from Table 2 -> Table 3 if not yet present."""
    cfg = _require_cfg()
    bt = cfg["base_token"]
    t_cand = cfg["tables"]["candidates"]
    t_dec = cfg["tables"]["deconstruct"]

    cands = base_list_records(bt, t_cand)
    decs = base_list_records(bt, t_dec)
    existing_dec_ids = {str(r.get("视频ID") or "").strip() for r in decs}

    new_decs: list[dict[str, Any]] = []
    for r in cands:
        if _first_select(r.get("审核状态")) != "入库":
            continue
        vid = str(r.get("视频ID") or "").strip()
        if not vid or vid in existing_dec_ids:
            continue
        existing_dec_ids.add(vid)
        likes = int(r.get("点赞数") or 0)
        comments = int(r.get("评论数") or 0)
        saves = int(r.get("收藏数") or 0)
        shares = int(r.get("分享数") or 0)
        new_decs.append(
            {
                "视频标题": str(r.get("视频标题") or ""),
                "平台": r.get("平台") or ["抖音"],
                "账号": str(r.get("账号") or ""),
                "视频链接": str(r.get("视频链接") or ""),
                "视频ID": vid,
                "爆款数据摘要": format_metrics_summary(likes, comments, saves, shares),
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
        base_batch_create(bt, t_dec, new_decs)
        print(f"Synced {len(new_decs)} newly approved videos to 03_爆款拆解库.")
    else:
        print("No new approved videos to sync.")

    # Export all rows in Table 3 missing 核心观点 so an Agent/LLM can batch-deconstruct them
    decs_after = base_list_records(bt, t_dec)
    pending_ai = [
        {
            "record_id": r["record_id"],
            "视频标题": r.get("视频标题") or "",
            "平台": _first_select(r.get("平台")),
            "账号": r.get("账号") or "",
            "视频链接": r.get("视频链接") or "",
            "视频文案原文": r.get("视频文案原文") or "",
            "现有关键词": r.get("内容关键词") or "",
        }
        for r in decs_after
        if not str(r.get("核心观点") or "").strip()
    ]
    out = PROJECT_ROOT / "data" / "pending_deconstruct.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pending_ai, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(pending_ai)} rows awaiting AI deconstruction -> {out}")


def cmd_write_deconstruct(args: argparse.Namespace) -> None:
    """Batch-update Table 3 with AI-generated 核心观点 / 内容关键词 / 衍生话题标签 / 二创切入点."""
    cfg = _require_cfg()
    bt = cfg["base_token"]
    t_dec = cfg["tables"]["deconstruct"]

    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    updates: dict[str, dict[str, Any]] = {}
    for it in items:
        rid = it.get("record_id")
        if not rid:
            continue
        patch: dict[str, Any] = {}
        for field in ("视频文案原文", "核心观点", "内容关键词", "衍生话题标签", "二创切入点"):
            if field in it and it[field] is not None and str(it[field]).strip():
                patch[field] = str(it[field]).strip()
        if patch:
            updates[rid] = patch

    if updates:
        base_batch_update(bt, t_dec, updates)
        print(f"Updated {len(updates)} records in 03_爆款拆解库.")
    else:
        print("Nothing to update.")


def cmd_reflow(args: argparse.Namespace) -> None:
    """Close the flywheel: reflow un-processed keywords & tags from Table 3 -> Table 1."""
    cfg = _require_cfg()
    bt = cfg["base_token"]
    t_kw = cfg["tables"]["keywords"]
    t_dec = cfg["tables"]["deconstruct"]

    existing_kws = {
        str(r.get("关键词") or "").strip() for r in base_list_records(bt, t_kw)
    }
    decs = base_list_records(bt, t_dec)
    round_name = args.round or dt.date.today().strftime("%m.%d回流")

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
                        "轮次": round_name,
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
                        "轮次": round_name,
                        "来源说明": f"表3标签回流：《{title}》",
                    }
                )
        mark_reflowed[r["record_id"]] = {"已回流词库": True}

    if new_kw_records:
        base_batch_create(bt, t_kw, new_kw_records)
    if mark_reflowed:
        base_batch_update(bt, t_dec, mark_reflowed)

    print(
        f"Reflow complete: added {len(new_kw_records)} new 待采 keywords to 01_词库池, "
        f"marked {len(mark_reflowed)} deconstructs as 已回流."
    )


def cmd_trend(args: argparse.Namespace) -> None:
    """Invoke local last30days-skill-cn script for a keyword to verify 30-day momentum."""
    skill_dir = PROJECT_ROOT / ".agents" / "skills" / "last30days-skill-cn"
    candidates = list(skill_dir.rglob("last30days.py"))
    if not candidates:
        raise SystemExit(f"last30days.py not found under {skill_dir}. Check skill install.")
    script = candidates[0]
    cmd = [sys.executable, str(script), args.keyword]
    if args.quick:
        cmd.append("--quick")
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bkworkflow", description="爆款话题挖掘自动化工作流 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="查看飞书三张表的实时统计状态").set_defaults(func=cmd_status)

    p_next = sub.add_parser("next-keywords", help="导出表1中待采关键词")
    p_next.add_argument("--limit", type=int, default=10)
    p_next.add_argument("--platform", choices=["小红书", "抖音"], default=None)
    p_next.add_argument("--csv", action="store_true", help="仅输出逗号分隔关键词串")
    p_next.set_defaults(func=cmd_next_keywords)

    p_ing = sub.add_parser("ingest", help="将 MediaCrawler / Agent-Reach 采集结果清洗打分并去重写入表2")
    p_ing.add_argument("--file", required=True, help="JSON/NDJSON/CSV 文件路径")
    p_ing.add_argument("--platform", choices=["小红书", "抖音"], default="")
    p_ing.add_argument("--keyword", default="")
    p_ing.add_argument("--round", default="")
    p_ing.add_argument("--mark-done", action="store_true", help="同时将命中词在表1标记为已采")
    p_ing.set_defaults(func=cmd_ingest)

    p_sync = sub.add_parser("sync-approved", help="将表2中【入库】视频同步至表3并导出待AI拆解清单")
    p_sync.set_defaults(func=cmd_sync_approved)

    p_wd = sub.add_parser("write-deconstruct", help="将AI拆解结果回写到表3")
    p_wd.add_argument("--file", required=True, help="包含 record_id 与拆解字段的 JSON 文件")
    p_wd.set_defaults(func=cmd_write_deconstruct)

    p_ref = sub.add_parser("reflow", help="将表3未回流的内容关键词与标签自动去重写回表1词库池")
    p_ref.add_argument("--round", default="")
    p_ref.set_defaults(func=cmd_reflow)

    p_tr = sub.add_parser("trend", help="调用 last30days-skill-cn 验证关键词近30天跨平台热度")
    p_tr.add_argument("keyword", help="要验证的关键词")
    p_tr.add_argument("--quick", action="store_true")
    p_tr.set_defaults(func=cmd_trend)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
