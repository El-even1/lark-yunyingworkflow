"""Upgrade Feishu Base & BaseApp into a visually cohesive closed-loop viral flywheel:
1. Bidirectional link fields connecting Table 1 <-> Table 2 <-> Table 3 + backfill existing relations
2. Closed-loop ROI formula fields on Table 1 (产出候选数, 产出入库爆款数, 最高爆款得分, 词条ROI评级)
3. Polished Kanban + Minimal Grid + Gallery views on all 3 tables (hiding technical clutter)
4. Flywheel Console upgrade on BaseApp Home Page + in-Base Dashboard
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bkworkflow.cleaner import split_keywords
from bkworkflow.feishu_cli import (
    base_batch_update,
    base_list_records,
    load_config,
    run_lark_cli,
)


def field_names(bt: str, tid: str) -> set[str]:
    res = run_lark_cli(["base", "+field-list", "--base-token", bt, "--table-id", tid])
    items = res.get("data", res).get("fields") or res.get("data", res).get("items") or []
    return {f["name"] for f in items}


def view_map(bt: str, tid: str) -> dict[str, str]:
    res = run_lark_cli(["base", "+view-list", "--base-token", bt, "--table-id", tid])
    items = res.get("data", res).get("views") or res.get("data", res).get("items") or []
    return {v["name"]: (v.get("view_id") or v.get("id")) for v in items}


def ensure_view(
    bt: str,
    tid: str,
    name: str,
    vtype: str,
    *,
    visible_fields: list[str] | None = None,
    group_by: list[dict[str, Any]] | None = None,
    sort_by: list[dict[str, Any]] | None = None,
) -> str:
    vm = view_map(bt, tid)
    vid = vm.get(name)
    if not vid:
        print(f"Creating view [{name}] ({vtype}) on {tid} ...")
        res = run_lark_cli(
            [
                "base",
                "+view-create",
                "--base-token",
                bt,
                "--table-id",
                tid,
                "--json",
                json.dumps({"name": name, "type": vtype}, ensure_ascii=False),
            ]
        )
        d = res.get("data", res)
        v_obj = d.get("view", d)
        vid = v_obj.get("view_id") or v_obj.get("id")
        if not vid:
            vid = view_map(bt, tid).get(name)
    else:
        print(f"Reusing existing view [{name}] ({vid})")

    if group_by is not None:
        run_lark_cli(
            [
                "base",
                "+view-set-group",
                "--base-token",
                bt,
                "--table-id",
                tid,
                "--view-id",
                vid,
                "--json",
                json.dumps({"group_config": group_by}, ensure_ascii=False),
            ]
        )
    if visible_fields is not None:
        run_lark_cli(
            [
                "base",
                "+view-set-visible-fields",
                "--base-token",
                bt,
                "--table-id",
                tid,
                "--view-id",
                vid,
                "--json",
                json.dumps({"visible_fields": visible_fields}, ensure_ascii=False),
            ]
        )
    if sort_by is not None:
        run_lark_cli(
            [
                "base",
                "+view-set-sort",
                "--base-token",
                bt,
                "--table-id",
                tid,
                "--view-id",
                vid,
                "--json",
                json.dumps({"sort_config": sort_by}, ensure_ascii=False),
            ]
        )
    print(f"  [View OK] {name}")
    return vid


def step1_links_and_formulas(cfg: dict[str, Any]) -> None:
    bt = cfg["base_token"]
    t_kw = cfg["tables"]["keywords"]
    t_cand = cfg["tables"]["candidates"]
    t_dec = cfg["tables"]["deconstruct"]

    # 1a. Bidirectional link: Table 2 (02_候选爆款池) <-> Table 1 (01_词库池)
    f_cand = field_names(bt, t_cand)
    if "关联词条" not in f_cand:
        print("Creating bidirectional link: 02_候选爆款池[关联词条] <-> 01_词库池[关联候选视频] ...")
        run_lark_cli(
            [
                "base",
                "+field-create",
                "--base-token",
                bt,
                "--table-id",
                t_cand,
                "--json",
                json.dumps(
                    {
                        "type": "link",
                        "name": "关联词条",
                        "link_table": "01_词库池",
                        "bidirectional": True,
                        "bidirectional_link_field_name": "关联候选视频",
                        "description": "关联该视频命中的词库词条，自动统计每个词的爆款产出ROI",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        time.sleep(1.5)

    # 1b. Bidirectional link: Table 3 (03_爆款拆解库) <-> Table 2 (02_候选爆款池)
    f_dec = field_names(bt, t_dec)
    if "关联原视频" not in f_dec:
        print("Creating bidirectional link: 03_爆款拆解库[关联原视频] <-> 02_候选爆款池[关联拆解记录] ...")
        run_lark_cli(
            [
                "base",
                "+field-create",
                "--base-token",
                bt,
                "--table-id",
                t_dec,
                "--json",
                json.dumps(
                    {
                        "type": "link",
                        "name": "关联原视频",
                        "link_table": "02_候选爆款池",
                        "bidirectional": True,
                        "bidirectional_link_field_name": "关联拆解记录",
                        "description": "反向关联《02_候选爆款池》原视频，打通词->视频->拆解闭环",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        time.sleep(1.5)

    # 1c. Closed-loop ROI formula fields on Table 1 (01_词库池)
    f_kw = field_names(bt, t_kw)
    roi_formulas = [
        {
            "name": "产出候选数",
            "type": "formula",
            "description": "该词在《02_候选爆款池》中挖出的候选视频总数",
            "expression": "COUNTA([关联候选视频])",
        },
        {
            "name": "产出入库爆款数",
            "type": "formula",
            "description": "该词最终通过筛选进入【入库】的真爆款数量",
            "expression": 'COUNTA([关联候选视频].[审核状态].FILTER(CurrentValue = "入库"))',
        },
        {
            "name": "最高爆款得分",
            "type": "formula",
            "description": "该词名下最高单条爆款得分",
            "expression": "IF(COUNTA([关联候选视频])=0, 0, MAX([关联候选视频].[爆款得分]))",
        },
        {
            "name": "词条ROI评级",
            "type": "formula",
            "description": "闭环自动评级：🏆金矿词 / 🔥已出爆款 / ✅已验证 / 🧊待挖掘",
            "expression": 'IF(COUNTA([关联候选视频].[审核状态].FILTER(CurrentValue = "入库"))>=2, "🏆金矿词", IF(COUNTA([关联候选视频].[审核状态].FILTER(CurrentValue = "入库"))>=1, "🔥已出爆款", IF(COUNTA([关联候选视频])>=1, "✅已验证", "🧊待挖掘")))',
        },
    ]
    missing_formulas = [f for f in roi_formulas if f["name"] not in f_kw]
    if missing_formulas:
        print(f"Creating closed-loop ROI formulas on 01_词库池: {[f['name'] for f in missing_formulas]} ...")
        run_lark_cli(
            [
                "base",
                "+field-create",
                "--base-token",
                bt,
                "--table-id",
                t_kw,
                "--i-have-read-guide",
                "--json",
                json.dumps(missing_formulas, ensure_ascii=False),
            ]
        )
        time.sleep(1.5)

    # 1d. Backfill links for all existing candidates & deconstructions
    print("Backfilling live relational links across all 3 tables ...")
    kws = base_list_records(bt, t_kw)
    cands = base_list_records(bt, t_cand)
    decs = base_list_records(bt, t_dec)

    kw_to_id: dict[str, str] = {}
    for r in kws:
        k = str(r.get("关键词") or "").strip().lower()
        if k:
            kw_to_id[k] = r["record_id"]

    cand_updates: dict[str, dict[str, Any]] = {}
    vid_to_cand_id: dict[str, str] = {}
    for r in cands:
        vid = str(r.get("视频ID") or "").strip()
        if vid:
            vid_to_cand_id[vid] = r["record_id"]
        if r.get("关联词条"):
            continue
        hit_kw = str(r.get("命中关键词") or "").strip()
        tags = str(r.get("话题标签") or "")
        matched_ids: list[str] = []
        # Exact match on 命中关键词 first, then fallback to split keywords / tags
        for cand_word in [hit_kw, *split_keywords(hit_kw, drop_stopwords=False), *split_keywords(tags.replace("#", "、"), drop_stopwords=False)]:
            w = cand_word.strip().lstrip("#").lower()
            if w and w in kw_to_id and kw_to_id[w] not in matched_ids:
                matched_ids.append(kw_to_id[w])
                if len(matched_ids) >= 3:
                    break
        if matched_ids:
            cand_updates[r["record_id"]] = {"关联词条": [{"id": x} for x in matched_ids]}

    dec_updates: dict[str, dict[str, Any]] = {}
    for r in decs:
        if r.get("关联原视频"):
            continue
        vid = str(r.get("视频ID") or "").strip()
        if vid and vid in vid_to_cand_id:
            dec_updates[r["record_id"]] = {"关联原视频": [{"id": vid_to_cand_id[vid]}]}

    print(f"Linking {len(cand_updates)} candidates -> keywords, {len(dec_updates)} deconstructs -> candidates ...")
    if cand_updates:
        base_batch_update(bt, t_cand, cand_updates)
    if dec_updates:
        base_batch_update(bt, t_dec, dec_updates)
    print("Step 1 complete!")


def step2_polished_views(cfg: dict[str, Any]) -> None:
    bt = cfg["base_token"]
    t_kw = cfg["tables"]["keywords"]
    t_cand = cfg["tables"]["candidates"]
    t_dec = cfg["tables"]["deconstruct"]

    # Table 1 Views
    ensure_view(
        bt,
        t_kw,
        "📋 词库流转看板",
        "kanban",
        group_by=[{"field": "采集状态", "desc": False}],
        visible_fields=["关键词", "词条ROI评级", "产出入库爆款数", "产出候选数", "词源", "目标平台", "轮次"],
        sort_by=[{"field": "产出入库爆款数", "desc": True}, {"field": "产出候选数", "desc": True}],
    )
    ensure_view(
        bt,
        t_kw,
        "🏆 金矿词排行榜",
        "grid",
        visible_fields=["关键词", "词条ROI评级", "产出入库爆款数", "产出候选数", "最高爆款得分", "词源", "目标平台", "采集状态", "关联候选视频"],
        sort_by=[{"field": "产出入库爆款数", "desc": True}, {"field": "最高爆款得分", "desc": True}],
    )

    # Table 2 Views
    ensure_view(
        bt,
        t_cand,
        "🔥 爆款筛选看板",
        "kanban",
        group_by=[{"field": "审核状态", "desc": False}],
        visible_fields=["视频标题", "防刷量预警", "爆款得分", "平台", "点赞数", "评论数", "收藏数", "关联词条", "✅ 一键入库拆解"],
        sort_by=[{"field": "爆款得分", "desc": True}],
    )
    ensure_view(
        bt,
        t_cand,
        "⚡ 极速筛爆款",
        "grid",
        visible_fields=[
            "视频标题",
            "✅ 一键入库拆解",
            "防刷量预警",
            "审核状态",
            "爆款得分",
            "平台",
            "关联词条",
            "点赞数",
            "评论数",
            "收藏数",
            "视频链接",
            "关联拆解记录",
        ],
        sort_by=[{"field": "爆款得分", "desc": True}],
    )

    # Table 3 Views
    ensure_view(
        bt,
        t_dec,
        "🧠 拆解与回流工作台",
        "grid",
        group_by=[{"field": "已回流词库", "desc": False}],
        visible_fields=[
            "视频标题",
            "🔄 回流到词库",
            "已回流词库",
            "核心观点",
            "内容关键词",
            "二创切入点",
            "爆款数据摘要",
            "关联原视频",
        ],
    )
    ensure_view(
        bt,
        t_dec,
        "🃏 爆款金句卡片",
        "gallery",
        visible_fields=["视频标题", "平台", "爆款数据摘要", "核心观点", "内容关键词", "二创切入点", "🔄 回流到词库"],
    )
    print("Step 2 complete!")


def step3_upgrade_console_and_dashboard(cfg: dict[str, Any]) -> None:
    bt = cfg["base_token"]
    app_token = cfg.get("app_token")
    overview_page = (cfg.get("pages") or {}).get("overview")
    dash_id = cfg.get("dashboard_id")

    # 3a. Upgrade in-Base Dashboard with 金矿词产出排行 Top 10
    if dash_id:
        bl = run_lark_cli(["base", "+dashboard-block-list", "--base-token", bt, "--dashboard-id", dash_id])
        existing_names = {b.get("name") for b in (bl.get("data", bl).get("items") or bl.get("data", bl).get("blocks") or [])}
        if "🏆 金矿词产出 Top 10" not in existing_names:
            print("Adding 🏆 金矿词产出 Top 10 ranking to Base Dashboard ...")
            run_lark_cli(
                [
                    "base",
                    "+dashboard-block-create",
                    "--base-token",
                    bt,
                    "--dashboard-id",
                    dash_id,
                    "--name",
                    "🏆 金矿词产出 Top 10",
                    "--type",
                    "ranking",
                    "--data-config",
                    json.dumps(
                        {
                            "table_name": "01_词库池",
                            "series": [{"field_name": "产出候选数", "rollup": "MAX"}],
                            "group_by": [
                                {"field_name": "关键词", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
                            ],
                            "limit_size": 10,
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            run_lark_cli(["base", "+dashboard-arrange", "--base-token", bt, "--dashboard-id", dash_id])
            print("  [Dashboard upgraded & arranged OK]")

    # 3b. Upgrade BaseApp Home Page -> 🌀 爆款飞轮总控台
    if app_token and overview_page:
        print("Renaming BaseApp Page 1 -> 🌀 爆款飞轮总控台 ...")
        run_lark_cli(
            [
                "base",
                "+app-page-update",
                "--app-token",
                app_token,
                "--page-id",
                overview_page,
                "--name",
                "🌀 爆款飞轮总控台",
            ]
        )
        abl = run_lark_cli(["base", "+app-block-list", "--app-token", app_token, "--page-id", overview_page])
        existing_blocks = {b.get("name"): b for b in (abl.get("data", abl).get("items") or [])}

        # Update top guide text to highlight the closed-loop flywheel
        if "运营操作速查" in existing_blocks:
            guide_wid = existing_blocks["运营操作速查"]["widget_id"]
            flywheel_md = (
                "# 🌀 教育赛道 · 爆款增长飞轮总控台\n\n"
                "**① 词库池（找词）** → **② 候选池（防刷量筛爆款）** → **③ 拆解库（云端AI提观点与新词）** → **④ 一键回流（新词再生下一轮爆款）**\n\n"
                "- **三表双向关联已打通**：每个词自动统计产出候选数、入库爆款数与 **金矿词 ROI 评级**。\n"
                "- **运营每日极速 3 步**：在下方高优列表点 **一键入库拆解** → 去拆解库粘文案自动出 AI 拆解 → 点 **回流到词库** 闭合飞轮。"
            )
            run_lark_cli(
                [
                    "base",
                    "+app-block-update",
                    "--app-token",
                    app_token,
                    "--page-id",
                    overview_page,
                    "--block-id",
                    guide_wid,
                    "--data-config",
                    json.dumps({"text": flywheel_md}, ensure_ascii=False),
                ]
            )
            print("  [Updated Home Guide OK]")

        if "🏆 金矿词产出分布" not in existing_blocks:
            run_lark_cli(
                [
                    "base",
                    "+app-block-create",
                    "--app-token",
                    app_token,
                    "--page-id",
                    overview_page,
                    "--name",
                    "🏆 金矿词产出分布",
                    "--type",
                    "bar",
                    "--data-config",
                    json.dumps(
                        {
                            "base_token": bt,
                            "data_sources": [
                                {
                                    "table_name": "01_词库池",
                                    "count_all": True,
                                    "group_by": [
                                        {"field_name": "词条ROI评级", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
                                    ],
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            print("  [Added 🏆 金矿词产出分布 OK]")

        if "⚡ 首页极速筛爆款（精简视图）" not in existing_blocks:
            run_lark_cli(
                [
                    "base",
                    "+app-block-create",
                    "--app-token",
                    app_token,
                    "--page-id",
                    overview_page,
                    "--name",
                    "⚡ 首页极速筛爆款（精简视图）",
                    "--type",
                    "list",
                    "--data-config",
                    json.dumps(
                        {
                            "base_token": bt,
                            "table_name": "02_候选爆款池",
                            "columns": [
                                {"field_name": "✅ 一键入库拆解", "type": "field"},
                                {"field_name": "防刷量预警", "type": "field"},
                                {"field_name": "爆款得分", "type": "field"},
                                {"field_name": "平台", "type": "field"},
                                {"field_name": "视频标题", "type": "field"},
                                {"field_name": "关联词条", "type": "field"},
                                {"field_name": "视频链接", "type": "field"},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ]
            )
            print("  [Added ⚡ 首页极速筛爆款 OK]")

    print("Step 3 complete!")


def main() -> None:
    cfg = load_config()
    step1_links_and_formulas(cfg)
    step2_polished_views(cfg)
    step3_upgrade_console_and_dashboard(cfg)
    print("\nALL CLOSED-LOOP FLYWHEEL UPGRADES DONE!")


if __name__ == "__main__":
    main()
