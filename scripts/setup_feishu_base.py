"""Create the 3-table Feishu Base workspace for automated viral topic discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bkworkflow.feishu_cli import (
    PROJECT_ROOT,
    load_config,
    run_lark_cli,
    save_config,
)

BASE_NAME = "爆款话题挖掘·自动化工作台"

TABLE_KEYWORDS_FIELDS = [
    {"name": "关键词", "type": "text", "description": "去重后的搜索词/主题词"},
    {
        "name": "词类",
        "type": "select",
        "multiple": False,
        "options": [
            {"name": "概念名词", "hue": "Blue", "lightness": "Lighter"},
            {"name": "地名/国家", "hue": "Turquoise", "lightness": "Lighter"},
            {"name": "痛点场景", "hue": "Orange", "lightness": "Lighter"},
            {"name": "平台联想词", "hue": "Purple", "lightness": "Lighter"},
            {"name": "话题标签", "hue": "Green", "lightness": "Lighter"},
        ],
    },
    {
        "name": "词源",
        "type": "select",
        "multiple": False,
        "options": [
            {"name": "初始种子", "hue": "Blue", "lightness": "Lighter"},
            {"name": "AI扒词回流", "hue": "Purple", "lightness": "Lighter"},
            {"name": "平台联想", "hue": "Orange", "lightness": "Lighter"},
            {"name": "爆款#标签", "hue": "Green", "lightness": "Lighter"},
            {"name": "近30天热词", "hue": "Red", "lightness": "Lighter"},
        ],
    },
    {
        "name": "目标平台",
        "type": "select",
        "multiple": True,
        "options": [
            {"name": "小红书", "hue": "Red", "lightness": "Lighter"},
            {"name": "抖音", "hue": "Blue", "lightness": "Lighter"},
        ],
    },
    {
        "name": "近30天热度",
        "type": "number",
        "style": {"type": "plain", "precision": 0},
    },
    {
        "name": "采集状态",
        "type": "select",
        "multiple": False,
        "default_value": ["待采"],
        "options": [
            {"name": "待采", "hue": "Orange", "lightness": "Lighter"},
            {"name": "已采", "hue": "Green", "lightness": "Lighter"},
            {"name": "暂停/废弃", "hue": "Gray", "lightness": "Lighter"},
        ],
    },
    {"name": "轮次", "type": "text"},
    {"name": "来源说明", "type": "text"},
    {"name": "创建时间", "type": "created_at"},
]

TABLE_CANDIDATES_FIELDS = [
    {"name": "视频标题", "type": "text"},
    {
        "name": "平台",
        "type": "select",
        "multiple": False,
        "options": [
            {"name": "小红书", "hue": "Red", "lightness": "Lighter"},
            {"name": "抖音", "hue": "Blue", "lightness": "Lighter"},
        ],
    },
    {"name": "视频ID", "type": "text", "description": "唯一去重键（平台短链ID/笔记ID）"},
    {"name": "命中关键词", "type": "text"},
    {"name": "账号", "type": "text"},
    {"name": "视频链接", "type": "text", "style": {"type": "url"}},
    {"name": "点赞数", "type": "number", "style": {"type": "plain", "precision": 0}},
    {"name": "评论数", "type": "number", "style": {"type": "plain", "precision": 0}},
    {"name": "收藏数", "type": "number", "style": {"type": "plain", "precision": 0}},
    {"name": "分享数", "type": "number", "style": {"type": "plain", "precision": 0}},
    {"name": "话题标签", "type": "text"},
    {"name": "采集轮次", "type": "text"},
    {
        "name": "审核状态",
        "type": "select",
        "multiple": False,
        "default_value": ["待审"],
        "options": [
            {"name": "待审", "hue": "Orange", "lightness": "Lighter"},
            {"name": "入库", "hue": "Green", "lightness": "Lighter"},
            {"name": "待复核", "hue": "Yellow", "lightness": "Lighter"},
            {"name": "淘汰", "hue": "Gray", "lightness": "Lighter"},
        ],
    },
    {"name": "备注", "type": "text"},
]

TABLE_CANDIDATES_FORMULAS = [
    {
        "name": "爆款得分",
        "type": "formula",
        "description": "加权分 = 赞×1 + 评×3 + 藏×2 + 享×4",
        "expression": "IF([点赞数]+[评论数]+[收藏数]+[分享数]=0, 0, [点赞数]*1 + [评论数]*3 + [收藏数]*2 + [分享数]*4)",
    },
    {
        "name": "评赞比",
        "type": "formula",
        "description": "评论数/点赞数，过低可能为刷量",
        "expression": "IF([点赞数]>0, ROUND([评论数]/[点赞数], 4), 0)",
    },
    {
        "name": "藏赞比",
        "type": "formula",
        "description": "收藏数/点赞数，高藏赞比代表高干货价值",
        "expression": "IF([点赞数]>0, ROUND([收藏数]/[点赞数], 4), 0)",
    },
    {
        "name": "防刷量预警",
        "type": "formula",
        "description": "自动标记高优爆款或疑似刷量",
        "expression": 'IF([点赞数]=0, "待补数据", IF(AND([点赞数]>=5000, [评论数]/[点赞数]<0.005), "⚠️疑似刷量待复核", IF([点赞数]*1+[评论数]*3+[收藏数]*2+[分享数]*4>=50000, "🔥高优爆款", "✅正常")))',
    },
]

TABLE_DECONSTRUCT_FIELDS = [
    {"name": "视频标题", "type": "text"},
    {
        "name": "平台",
        "type": "select",
        "multiple": False,
        "options": [
            {"name": "小红书", "hue": "Red", "lightness": "Lighter"},
            {"name": "抖音", "hue": "Blue", "lightness": "Lighter"},
        ],
    },
    {"name": "账号", "type": "text"},
    {"name": "视频链接", "type": "text", "style": {"type": "url"}},
    {"name": "视频ID", "type": "text"},
    {"name": "爆款数据摘要", "type": "text"},
    {"name": "视频文案原文", "type": "text"},
    {"name": "核心观点", "type": "text", "description": "3-5条短句判断"},
    {"name": "内容关键词", "type": "text", "description": "逗号分隔，用于自动回流表1"},
    {"name": "衍生话题标签", "type": "text"},
    {"name": "二创切入点", "type": "text"},
    {"name": "已回流词库", "type": "checkbox"},
    {"name": "来源轮次", "type": "text"},
]


def main() -> None:
    cfg = load_config()
    existing_token = None
    if "--base-token" in sys.argv:
        idx = sys.argv.index("--base-token")
        existing_token = sys.argv[idx + 1]

    if cfg.get("base_token") and not existing_token and "--force" not in sys.argv:
        print(f"Base already configured: {cfg['base_token']} ({cfg.get('base_url', '')})")
        print("Pass --force to create a brand new Base.")
        return

    if existing_token:
        base_token = existing_token
        base_url = f"https://my.feishu.cn/base/{base_token}"
        tl = run_lark_cli(["base", "+table-list", "--base-token", base_token])
        items = tl.get("data", tl).get("items", [])
        table_map = {(it.get("table_name") or it.get("name")): (it.get("table_id") or it.get("id")) for it in items}
        t1_id = table_map.get("01_词库池")
        print(f"Using existing Base {base_token}, tables={table_map}")
    else:
        print(f"Creating Feishu Base: {BASE_NAME} ...")
        res = run_lark_cli(
            [
                "base",
                "+base-create",
                "--name",
                BASE_NAME,
                "--time-zone",
                "Asia/Shanghai",
                "--table-name",
                "01_词库池",
                "--fields",
                json.dumps(TABLE_KEYWORDS_FIELDS, ensure_ascii=False),
            ]
        )
        data = res.get("data", res)
        base_obj = data.get("base", data)
        table_obj = data.get("table", data)
        base_token = base_obj.get("base_token") or data.get("base_token")
        base_url = base_obj.get("url") or f"https://my.feishu.cn/base/{base_token}"
        t1_id = table_obj.get("id") or data.get("table_id")
        table_map = {"01_词库池": t1_id}
        print("Base created:", base_token, base_url, "t1:", t1_id)

    t2_id = table_map.get("02_候选爆款池")
    if not t2_id:
        print("Creating table: 02_候选爆款池 ...")
        res_t2 = run_lark_cli(
            [
                "base",
                "+table-create",
                "--base-token",
                base_token,
                "--name",
                "02_候选爆款池",
                "--fields",
                json.dumps(TABLE_CANDIDATES_FIELDS, ensure_ascii=False),
            ]
        )
        t2_data = res_t2.get("data", res_t2)
        t2_obj = t2_data.get("table", t2_data)
        t2_id = t2_obj.get("table_id") or t2_obj.get("id")
        print("Table 2 created:", t2_id)

        print("Adding formula fields to 02_候选爆款池 ...")
        run_lark_cli(
            [
                "base",
                "+field-create",
                "--base-token",
                base_token,
                "--table-id",
                t2_id,
                "--i-have-read-guide",
                "--json",
                json.dumps(TABLE_CANDIDATES_FORMULAS, ensure_ascii=False),
            ]
        )
        print("Formulas created successfully.")

    t3_id = table_map.get("03_爆款拆解库")
    if not t3_id:
        print("Creating table: 03_爆款拆解库 ...")
        res_t3 = run_lark_cli(
            [
                "base",
                "+table-create",
                "--base-token",
                base_token,
                "--name",
                "03_爆款拆解库",
                "--fields",
                json.dumps(TABLE_DECONSTRUCT_FIELDS, ensure_ascii=False),
            ]
        )
        t3_data = res_t3.get("data", res_t3)
        t3_obj = t3_data.get("table", t3_data)
        t3_id = t3_obj.get("table_id") or t3_obj.get("id")
        print("Table 3 created:", t3_id)

    cfg.update(
        {
            "source_spreadsheet_token": cfg.get("source_spreadsheet_token", ""),
            "source_sop_doc_token": cfg.get("source_sop_doc_token", ""),
            "base_name": BASE_NAME,
            "base_token": base_token,
            "base_url": base_url,
            "tables": {
                "keywords": t1_id,
                "candidates": t2_id,
                "deconstruct": t3_id,
            },
        }
    )
    save_config(cfg)
    print(f"Saved config to {PROJECT_ROOT / 'config.json'}")
    print(f"Base URL: {base_url}")


if __name__ == "__main__":
    main()
