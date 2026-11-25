"""WorkBuddy-compatible MCP Server for bkworkflow (supports stdio and streamable-http).

Usage:
  - Local stdio (WorkBuddy local MCP):
      python bkworkflow/mcp_server.py
  - LAN HTTP server (shared by whole ops team in WorkBuddy):
      python bkworkflow/mcp_server.py --http --port 8502
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure project root is importable when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from bkworkflow import service

mcp = FastMCP(
    "bkworkflow",
    instructions=(
        "你是教育赛道小红书/抖音找爆款自动化助手，直连飞书多维表格《爆款话题挖掘·自动化工作台》。"
        "遇到运营要求查看爆款进度、拉取待采词、验热、导入清洗链接、审核爆款、AI拆解核心观点或回流新词时，优先调用对应工具。"
    ),
)


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


@mcp.tool()
def get_viral_dashboard(refresh: bool = True) -> str:
    """查看飞书三张表（01_词库池、02_候选爆款池、03_爆款拆解库）的实时统计面板与多维表格链接。"""
    return _dump(service.get_dashboard_summary(force_refresh=refresh))


@mcp.tool()
def list_pending_keywords(platform: str = "全部", limit: int = 15) -> str:
    """从飞书《01_词库池》拉取待采集关键词。platform 可填 '全部'、'小红书' 或 '抖音'。"""
    items = service.list_keywords(status="待采", platform=platform, limit=limit, force_refresh=True)
    return _dump({"count": len(items), "keywords": items})


@mcp.tool()
def add_new_keywords(
    keywords_text: str,
    word_type: str = "概念名词",
    platforms: list[str] | None = None,
    round_name: str = "",
) -> str:
    """向飞书《01_词库池》批量添加新搜索词（自动去重并过滤过泛停用词）。keywords_text 可用顿号、逗号或换行分隔。"""
    return _dump(
        service.add_keywords(
            keywords_text,
            word_type=word_type,
            source="AI扒词回流",
            platforms=platforms or ["小红书", "抖音"],
            round_name=round_name,
            note="WorkBuddy MCP 添加",
        )
    )


@mcp.tool()
def check_keyword_30d_trend(keyword: str, quick: bool = True) -> str:
    """调用 last30days-skill-cn 查询某个教育赛道关键词最近 30 天在中文全网的讨论与热度，替代去小红书草稿箱测标签。"""
    return _dump(service.check_keyword_trend(keyword, quick=quick))


@mcp.tool()
def list_candidates(
    filter_mode: str = "all",
    platform: str = "全部",
    search: str = "",
    limit: int = 20,
) -> str:
    """按爆款得分倒序查看飞书《02_候选爆款池》。filter_mode 可选: all / hot(🔥高优爆款) / fake(⚠️疑似刷量) / pending(待审) / approved(入库) / rejected(淘汰)。"""
    items = service.list_candidates(
        filter_mode=filter_mode,
        platform=platform,
        search=search,
        limit=limit,
        force_refresh=True,
    )
    return _dump({"count": len(items), "items": items})


@mcp.tool()
def update_candidate_status(record_id: str, status: str) -> str:
    """更新飞书《02_候选爆款池》某条视频的审核状态。status 必须是 '入库'、'待复核'、'淘汰' 或 '待审'。"""
    return _dump(service.update_candidate_status(record_id, status))


@mcp.tool()
def ingest_share_texts(
    raw_text: str,
    platform: str = "",
    keyword: str = "",
    round_name: str = "",
    mark_keywords_done: bool = True,
) -> str:
    """把运营粘贴的小红书/抖音分享口令、链接（可附带赞评藏享数字）或 JSON 列表，自动清洗URL、防刷量打分并去重写入飞书《02_候选爆款池》。"""
    parsed = service.parse_pasted_share_texts(
        raw_text,
        default_platform=platform,
        default_keyword=keyword,
        round_name=round_name,
    )
    result = service.ingest_candidate_records(parsed, mark_keywords_done=mark_keywords_done)
    result["parsed_count"] = len(parsed)
    return _dump(result)


@mcp.tool()
def get_pending_deconstruct_videos(sync_from_candidates: bool = True, limit: int = 8) -> str:
    """同步表2【入库】视频到表3，并返回当前《03_爆款拆解库》中尚未拆解核心观点的视频列表（含文案原文），供 AI 直接拆解。"""
    sync_res = service.sync_approved_to_deconstruct() if sync_from_candidates else {"synced_new": 0}
    rows = service.list_deconstructs(only_pending=True, limit=limit, force_refresh=True)
    # Trim very long transcripts gently for context safety
    compact = [
        {
            "record_id": r["record_id"],
            "title": r["title"],
            "platform": r["platform"],
            "author": r["author"],
            "url": r["url"],
            "metrics": r["metrics"],
            "transcript": r["transcript"][:3500],
            "existing_keywords": r["keywords"],
        }
        for r in rows
    ]
    return _dump({"sync": sync_res, "pending_count": len(compact), "items": compact})


@mcp.tool()
def save_deconstruct_and_reflow(
    items: list[dict[str, Any]],
    auto_reflow_keywords: bool = True,
    round_name: str = "",
) -> str:
    """将 AI 拆解好的结果写回飞书《03_爆款拆解库》，并可自动把新提取的内容关键词与话题标签去重回流到《01_词库池》。
    items 每项包含: record_id, 核心观点, 内容关键词, 衍生话题标签, 二创切入点(可选)。"""
    saved = service.save_deconstruct_items(items)
    reflow = service.reflow_keywords_to_pool(round_name=round_name) if auto_reflow_keywords else None
    return _dump({"saved": saved, "reflow": reflow})


@mcp.tool()
def reflow_keywords_only(round_name: str = "") -> str:
    """仅执行关键词回流：把《03_爆款拆解库》中所有未回流的内容关键词与衍生标签自动去重写回《01_词库池》。"""
    return _dump(service.reflow_keywords_to_pool(round_name=round_name))


def main() -> None:
    parser = argparse.ArgumentParser(description="bkworkflow MCP Server for WorkBuddy")
    parser.add_argument("--http", action="store_true", help="以局域网 streamable-http 模式启动（供全团队 WorkBuddy 共用）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8502)
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
