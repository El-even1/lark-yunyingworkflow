"""Build native Feishu BaseApp (multi-page ops workbench) + in-Base Dashboard
connected to the live 3-table Feishu Base.

All page & block creations execute strictly serially per lark-base guidelines.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bkworkflow.feishu_cli import load_config, run_lark_cli, save_config


def create_app_block(
    app_token: str,
    page_id: str,
    name: str,
    btype: str,
    data_config: dict[str, Any] | None = None,
    sub_type: str | None = None,
) -> dict[str, Any]:
    args = [
        "base",
        "+app-block-create",
        "--app-token",
        app_token,
        "--page-id",
        page_id,
        "--name",
        name,
        "--type",
        btype,
    ]
    if sub_type:
        args.extend(["--sub-type", sub_type])
    if data_config is not None:
        args.extend(["--data-config", json.dumps(data_config, ensure_ascii=False)])
    res = run_lark_cli(args)
    print(f"  [AppBlock OK] {name} ({btype})")
    return res.get("data", res)


def create_dash_block(
    base_token: str,
    dashboard_id: str,
    name: str,
    btype: str,
    data_config: dict[str, Any],
) -> dict[str, Any]:
    args = [
        "base",
        "+dashboard-block-create",
        "--base-token",
        base_token,
        "--dashboard-id",
        dashboard_id,
        "--name",
        name,
        "--type",
        btype,
        "--data-config",
        json.dumps(data_config, ensure_ascii=False),
    ]
    res = run_lark_cli(args)
    print(f"  [DashBlock OK] {name} ({btype})")
    return res.get("data", res)


def build_base_app(cfg: dict[str, Any]) -> dict[str, Any]:
    base_token = cfg["base_token"]
    bg = run_lark_cli(["base", "+base-get", "--base-token", base_token])
    base_info = bg.get("data", bg).get("base", {})
    ws_token = base_info.get("workspace_token")
    if not ws_token:
        raise RuntimeError("Base has no workspace_token; cannot create BaseApp.")

    print(f"Creating BaseApp in workspace {ws_token} ...")
    res = run_lark_cli(
        [
            "base",
            "+app-create",
            "--name",
            "爆款话题挖掘·运营工作台",
            "--workspace-token",
            ws_token,
            "--theme-style",
            "cloudBlue",
        ]
    )
    app_data = res.get("data", res)
    app_obj = app_data.get("app", app_data)
    app_token = app_obj.get("app_token") or app_data.get("app_token") or app_obj.get("token")
    app_url = app_obj.get("url") or f"https://my.feishu.cn/app/{app_token}"
    print(f"BaseApp created: {app_token} ({app_url})")

    # Fetch default page and reuse it as Page 1
    ag = run_lark_cli(["base", "+app-get", "--app-token", app_token])
    ag_data = ag.get("data", ag)
    pages = ag_data.get("pages") or ag_data.get("app", {}).get("pages") or []
    if not pages:
        pl = run_lark_cli(["base", "+app-page-list", "--app-token", app_token])
        pages = pl.get("data", pl).get("items") or pl.get("data", pl).get("pages") or []
    default_page_id = pages[0].get("page_id") or pages[0].get("id")
    print(f"Renaming default page {default_page_id} -> 📊 运营总览看板 ...")
    run_lark_cli(
        [
            "base",
            "+app-page-update",
            "--app-token",
            app_token,
            "--page-id",
            default_page_id,
            "--name",
            "📊 运营总览看板",
        ]
    )

    # Page 1 blocks (serially)
    guide_md = (
        "# 爆款话题挖掘 · 4步运营飞轮\n\n"
        "本工作台直连底层三张核心数据表，运营团队 **无需懂代码**，按左侧页面顺序操作即可：\n\n"
        "1. **🔍 词库管理池**：查看待采关键词，或直接新增种子词；在 WorkBuddy 输入一句话即可查近 30 天热度。\n"
        "2. **🔥 极速筛爆款**：按 **爆款得分** 和 **防刷量预警** 快速筛选，把想深挖的视频 **审核状态** 改为 **入库**。\n"
        "3. **🧠 爆款拆解库**：沉淀入库视频的口播文案、核心观点与二创切入点，在 WorkBuddy 说一句即可自动拆解并把新词回流到词库池。"
    )
    create_app_block(app_token, default_page_id, "运营操作速查", "text", {"text": guide_md})

    create_app_block(
        app_token,
        default_page_id,
        "待采关键词数",
        "statistics",
        {
            "base_token": base_token,
            "data_sources": [
                {
                    "table_name": "01_词库池",
                    "count_all": True,
                    "filter": {
                        "conjunction": "and",
                        "conditions": [
                            {"field_name": "采集状态", "operator": "is", "value": "待采"}
                        ],
                    },
                }
            ],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "候选爆款总数",
        "statistics",
        {
            "base_token": base_token,
            "data_sources": [{"table_name": "02_候选爆款池", "count_all": True}],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "已入库爆款数",
        "statistics",
        {
            "base_token": base_token,
            "data_sources": [
                {
                    "table_name": "02_候选爆款池",
                    "count_all": True,
                    "filter": {
                        "conjunction": "and",
                        "conditions": [
                            {"field_name": "审核状态", "operator": "is", "value": "入库"}
                        ],
                    },
                }
            ],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "爆款拆解库总数",
        "statistics",
        {
            "base_token": base_token,
            "data_sources": [{"table_name": "03_爆款拆解库", "count_all": True}],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "候选视频审核状态分布",
        "column",
        {
            "base_token": base_token,
            "data_sources": [
                {
                    "table_name": "02_候选爆款池",
                    "count_all": True,
                    "group_by": [
                        {
                            "field_name": "审核状态",
                            "mode": "integrated",
                            "sort": {"type": "value", "order": "desc"},
                        }
                    ],
                }
            ],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "平台内容占比（小红书 vs 抖音）",
        "ring",
        {
            "base_token": base_token,
            "data_sources": [
                {
                    "table_name": "02_候选爆款池",
                    "count_all": True,
                    "group_by": [
                        {
                            "field_name": "平台",
                            "mode": "integrated",
                            "sort": {"type": "value", "order": "desc"},
                        }
                    ],
                }
            ],
        },
    )
    create_app_block(
        app_token,
        default_page_id,
        "各采集轮次产出量",
        "bar",
        {
            "base_token": base_token,
            "data_sources": [
                {
                    "table_name": "02_候选爆款池",
                    "count_all": True,
                    "group_by": [
                        {
                            "field_name": "采集轮次",
                            "mode": "integrated",
                            "sort": {"type": "value", "order": "desc"},
                        }
                    ],
                }
            ],
        },
    )

    # Page 2: 极速筛爆款
    print("Creating Page 2: 🔥 极速筛爆款 ...")
    p2_res = run_lark_cli(
        [
            "base",
            "+app-page-create",
            "--app-token",
            app_token,
            "--name",
            "🔥 极速筛爆款",
        ]
    )
    p2_data = p2_res.get("data", p2_res)
    p2_id = p2_data.get("page_id") or p2_data.get("page", {}).get("page_id") or p2_data.get("id")
    create_app_block(
        app_token,
        p2_id,
        "筛选说明",
        "text",
        {
            "text": (
                "## 每天 3 分钟极速筛爆款\n"
                "- 优先看 **防刷量预警** 为 **高优爆款** 的记录，避开 **疑似刷量待复核**。\n"
                "- 选中想深挖的视频，直接把 **审核状态** 改为 **入库**，后续由 AI 自动拆解并回流新词。"
            )
        },
    )
    create_app_block(
        app_token,
        p2_id,
        "候选爆款审核列表",
        "list",
        {"base_token": base_token, "table_name": "02_候选爆款池"},
    )

    # Page 3: 词库管理池
    print("Creating Page 3: 🔍 词库管理池 ...")
    p3_res = run_lark_cli(
        [
            "base",
            "+app-page-create",
            "--app-token",
            app_token,
            "--name",
            "🔍 词库管理池",
        ]
    )
    p3_data = p3_res.get("data", p3_res)
    p3_id = p3_data.get("page_id") or p3_data.get("page", {}).get("page_id") or p3_data.get("id")
    create_app_block(
        app_token,
        p3_id,
        "词库说明",
        "text",
        {
            "text": (
                "## 关键词统一去重池\n"
                "- 所有待采词、平台联想词、爆款标签和拆解回流词统一沉淀在此，**无需再按日期建新表**。\n"
                "- 运营可直接在此新增种子词，或在 WorkBuddy 里输入：拉取 10 个待采词并查近 30 天热度。"
            )
        },
    )
    create_app_block(
        app_token,
        p3_id,
        "关键词待采列表",
        "list",
        {"base_token": base_token, "table_name": "01_词库池"},
    )

    # Page 4: 爆款拆解库
    print("Creating Page 4: 🧠 爆款拆解库 ...")
    p4_res = run_lark_cli(
        [
            "base",
            "+app-page-create",
            "--app-token",
            app_token,
            "--name",
            "🧠 爆款拆解库",
        ]
    )
    p4_data = p4_res.get("data", p4_res)
    p4_id = p4_data.get("page_id") or p4_data.get("page", {}).get("page_id") or p4_data.get("id")
    create_app_block(
        app_token,
        p4_id,
        "拆解回流说明",
        "text",
        {
            "text": (
                "## 爆款拆解与自动回流\n"
                "- 沉淀所有入库爆款的 **核心观点**、**内容关键词** 与 **二创切入点**。\n"
                "- 在 WorkBuddy 对话框直接说：帮我拆解表 3 待拆解的爆款并回流新词，AI 会自动写回并勾选 **已回流词库**。"
            )
        },
    )
    create_app_block(
        app_token,
        p4_id,
        "爆款拆解清单",
        "list",
        {"base_token": base_token, "table_name": "03_爆款拆解库"},
    )

    return {
        "workspace_token": ws_token,
        "app_token": app_token,
        "app_url": app_url,
        "pages": {
            "overview": default_page_id,
            "candidates": p2_id,
            "keywords": p3_id,
            "deconstruct": p4_id,
        },
    }


def build_in_base_dashboard(cfg: dict[str, Any]) -> dict[str, Any]:
    base_token = cfg["base_token"]
    dl = run_lark_cli(["base", "+dashboard-list", "--base-token", base_token])
    existing = dl.get("data", dl).get("items") or []
    dash_id = None
    for item in existing:
        if item.get("name") == "📊 爆款数据总览":
            dash_id = item.get("dashboard_id")
            print(f"Reusing existing Dashboard: {dash_id}")
            break
    if not dash_id:
        print("Creating in-Base Dashboard: 📊 爆款数据总览 ...")
        res = run_lark_cli(
            [
                "base",
                "+dashboard-create",
                "--base-token",
                base_token,
                "--name",
                "📊 爆款数据总览",
            ]
        )
        d = res.get("data", res)
        dash_id = d.get("dashboard_id") or d.get("block_id") or d.get("id") or d.get("dashboard", {}).get("id")
        if not dash_id:
            dl2 = run_lark_cli(["base", "+dashboard-list", "--base-token", base_token])
            dash_id = (dl2.get("data", dl2).get("items") or [{}])[0].get("dashboard_id")
        print(f"Dashboard created: {dash_id}")

    create_dash_block(
        base_token,
        dash_id,
        "待采关键词数",
        "statistics",
        {
            "table_name": "01_词库池",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "采集状态", "operator": "is", "value": "待采"}],
            },
        },
    )
    create_dash_block(
        base_token,
        dash_id,
        "候选爆款总数",
        "statistics",
        {"table_name": "02_候选爆款池", "count_all": True},
    )
    create_dash_block(
        base_token,
        dash_id,
        "已入库爆款数",
        "statistics",
        {
            "table_name": "02_候选爆款池",
            "count_all": True,
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "审核状态", "operator": "is", "value": "入库"}],
            },
        },
    )
    create_dash_block(
        base_token,
        dash_id,
        "爆款拆解库总数",
        "statistics",
        {"table_name": "03_爆款拆解库", "count_all": True},
    )
    create_dash_block(
        base_token,
        dash_id,
        "账号点赞榜 Top 10",
        "ranking",
        {
            "table_name": "02_候选爆款池",
            "series": [{"field_name": "点赞数", "rollup": "MAX"}],
            "group_by": [
                {"field_name": "账号", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
            ],
            "limit_size": 10,
        },
    )
    create_dash_block(
        base_token,
        dash_id,
        "平台内容分布",
        "ring",
        {
            "table_name": "02_候选爆款池",
            "count_all": True,
            "group_by": [
                {"field_name": "平台", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
            ],
        },
    )
    create_dash_block(
        base_token,
        dash_id,
        "审核状态分布",
        "column",
        {
            "table_name": "02_候选爆款池",
            "count_all": True,
            "group_by": [
                {"field_name": "审核状态", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
            ],
        },
    )
    create_dash_block(
        base_token,
        dash_id,
        "词库来源分布",
        "bar",
        {
            "table_name": "01_词库池",
            "count_all": True,
            "group_by": [
                {"field_name": "词源", "mode": "integrated", "sort": {"type": "value", "order": "desc"}}
            ],
        },
    )

    print("Arranging dashboard layout ...")
    run_lark_cli(
        [
            "base",
            "+dashboard-arrange",
            "--base-token",
            base_token,
            "--dashboard-id",
            dash_id,
        ]
    )
    return {"dashboard_id": dash_id}


def main() -> None:
    cfg = load_config()
    if not cfg.get("base_token"):
        raise RuntimeError("Missing base_token in config.json")

    if not cfg.get("app_token") or "--force" in sys.argv:
        app_info = build_base_app(cfg)
        cfg.update(app_info)
        save_config(cfg)
    else:
        print(f"BaseApp already exists: {cfg['app_url']}")

    if not cfg.get("dashboard_id") or "--force" in sys.argv:
        dash_info = build_in_base_dashboard(cfg)
        cfg.update(dash_info)
        save_config(cfg)
    else:
        print(f"Dashboard already exists: {cfg['dashboard_id']}")

    print("All Feishu native pages & dashboard ready!")
    print("BaseApp URL:", cfg.get("app_url"))
    print("Base URL   :", cfg.get("base_url"))


if __name__ == "__main__":
    main()
