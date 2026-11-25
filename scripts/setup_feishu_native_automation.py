"""Configure 100% serverless Feishu-native Buttons, AI Field Extensions, and Automation Workflows
directly inside the existing Feishu Base (zero external server required).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bkworkflow.feishu_cli import load_config, run_lark_cli, save_config


def get_field_map(base_token: str, table_id: str) -> dict[str, dict[str, Any]]:
    res = run_lark_cli(["base", "+field-list", "--base-token", base_token, "--table-id", table_id])
    fields = res.get("data", res).get("fields") or res.get("data", res).get("items") or []
    return {f["name"]: f for f in fields}


def ensure_fields(base_token: str, table_id: str, specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    fmap = get_field_map(base_token, table_id)
    to_create = [s for s in specs if s["name"] not in fmap]
    if to_create:
        print(f"Creating {len(to_create)} fields on {table_id}: {[s['name'] for s in to_create]}")
        run_lark_cli(
            [
                "base",
                "+field-create",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--json",
                json.dumps(to_create, ensure_ascii=False),
            ]
        )
        time.sleep(1.5)
        fmap = get_field_map(base_token, table_id)
    return fmap


def install_ai_extension(
    base_token: str,
    table_id: str,
    field_id: str,
    field_name: str,
    prompt_segments: list[dict[str, str]],
) -> None:
    payload = {
        "extension_id": "builtin_llm_completion",
        "inputs": {"prompt": prompt_segments},
    }
    print(f"Installing Feishu native AI extension on [{field_name}] ({field_id}) ...")
    run_lark_cli(
        [
            "base",
            "+field-extension-update",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--field-id",
            field_id,
            "--json",
            json.dumps(payload, ensure_ascii=False),
            "--yes",
        ]
    )
    print(f"  [AI Extension OK] {field_name}")


def create_bind_enable_workflow(
    base_token: str,
    table_id: str,
    button_field_id: str,
    title: str,
    steps: list[dict[str, Any]],
) -> str:
    # Check if workflow with same title already exists
    wl = run_lark_cli(["base", "+workflow-list", "--base-token", base_token])
    items = wl.get("data", wl).get("items") or wl.get("data", wl).get("workflows") or []
    wkf_id = None
    for it in items:
        if it.get("title") == title:
            wkf_id = it.get("workflow_id") or it.get("id")
            print(f"Reusing existing workflow [{title}]: {wkf_id}")
            break

    if not wkf_id:
        body = {
            "client_token": str(int(time.time() * 1000)),
            "title": title,
            "steps": steps,
        }
        print(f"Creating workflow [{title}] ...")
        res = run_lark_cli(
            [
                "base",
                "+workflow-create",
                "--base-token",
                base_token,
                "--json",
                json.dumps(body, ensure_ascii=False),
            ]
        )
        d = res.get("data", res)
        wkf_id = d.get("workflow_id") or d.get("workflow", {}).get("workflow_id") or d.get("id")
        print(f"  [Workflow Created] {title} -> {wkf_id}")

    print(f"Binding button {button_field_id} -> workflow {wkf_id} ...")
    run_lark_cli(
        [
            "base",
            "+button-rule-bind",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--field-id",
            button_field_id,
            "--workflow-id",
            wkf_id,
        ]
    )
    print(f"Enabling workflow {wkf_id} ...")
    run_lark_cli(
        [
            "base",
            "+workflow-enable",
            "--base-token",
            base_token,
            "--workflow-id",
            wkf_id,
        ]
    )
    print(f"  [Workflow Bound & Enabled OK] {title}")
    return wkf_id


def main() -> None:
    cfg = load_config()
    bt = cfg["base_token"]
    t_cand = cfg["tables"]["candidates"]
    t_dec = cfg["tables"]["deconstruct"]

    # 1. Create Button fields + raw share paste helper columns
    f_cand = ensure_fields(
        bt,
        t_cand,
        [
            {
                "type": "button",
                "name": "✅ 一键入库拆解",
                "description": "点击后自动标记为【入库】，并自动推送新建到《03_爆款拆解库》",
                "button_config": {"title": "一键入库拆解"},
            },
            {
                "type": "text",
                "name": "原始分享口令",
                "description": "运营可直接粘贴小红书/抖音复制的整段口令，右侧AI列自动提取干净信息",
            },
            {
                "type": "text",
                "name": "✨ AI口令提取",
                "description": "飞书原生AI自动从【原始分享口令】中提取干净URL、标题、账号和话题标签",
            },
        ],
    )

    f_dec = ensure_fields(
        bt,
        t_dec,
        [
            {
                "type": "button",
                "name": "🔄 回流到词库",
                "description": "点击后自动把本条【内容关键词】写入《01_词库池》并勾选【已回流词库】",
                "button_config": {"title": "回流到词库"},
            }
        ],
    )

    def fid(fmap: dict[str, dict[str, Any]], name: str) -> str:
        f = fmap[name]
        return f.get("field_id") or f.get("id")

    # 2. Configure Feishu native AI Field Extensions (zero server, zero API key!)
    if "--workflows-only" not in sys.argv:
        install_ai_extension(
            bt,
            t_dec,
            fid(f_dec, "核心观点"),
            "核心观点",
            [
                {
                    "type": "text",
                    "text": (
                        "你是教育赛道小红书/抖音爆款拆解专家。请阅读下方视频标题与口播文案"
                        "（自动忽略语音转写错别字），提炼 3-5 条核心观点。要求：每条写成简洁有力的判断短句，"
                        "换行分点输出，严禁照抄原文；若文案为空则输出空字符串。\n视频标题："
                    ),
                },
                {"type": "field_ref", "field": "视频标题"},
                {"type": "text", "text": "\n视频文案原文："},
                {"type": "field_ref", "field": "视频文案原文"},
            ],
        )

        install_ai_extension(
            bt,
            t_dec,
            fid(f_dec, "内容关键词"),
            "内容关键词",
            [
                {
                    "type": "text",
                    "text": (
                        "请从下方教育赛道爆款视频的标题与文案中，提取 5-8 个最适合去小红书/抖音搜索框搜索的"
                        "具体中长尾名词、地名或痛点场景词（如：压缩教育成本、剧场效应、芬兰慢教育、美高选课）。"
                        "要求：过滤掉“教育、学习、孩子、家长”等过于宽泛的大词，只输出关键词本身，用顿号“、”分隔，"
                        "不要解释、不要编号；若文案为空则输出空字符串。\n视频标题："
                    ),
                },
                {"type": "field_ref", "field": "视频标题"},
                {"type": "text", "text": "\n视频文案原文："},
                {"type": "field_ref", "field": "视频文案原文"},
            ],
        )

        install_ai_extension(
            bt,
            t_dec,
            fid(f_dec, "二创切入点"),
            "二创切入点",
            [
                {
                    "type": "text",
                    "text": (
                        "你是教育赛道短视频编导。请基于下方爆款视频，给出 1-2 条可直接开拍的二创切入角度"
                        "（包含前3秒情绪/反常识钩子 + 家长痛点），控制在 80 字以内；若文案为空则输出空字符串。\n视频标题："
                    ),
                },
                {"type": "field_ref", "field": "视频标题"},
                {"type": "text", "text": "\n视频文案原文："},
                {"type": "field_ref", "field": "视频文案原文"},
            ],
        )

        install_ai_extension(
            bt,
            t_cand,
            fid(f_cand, "✨ AI口令提取"),
            "✨ AI口令提取",
            [
                {
                    "type": "text",
                    "text": (
                        "请从下面粘贴的小红书/抖音分享口令中，按固定4行提取干净信息：\n"
                        "标题：...\n链接：仅保留干净https链接\n话题标签：#标签1 #标签2\n四项数据：若有赞/评/藏/享则列出，无则写待补\n"
                        "若口令为空则输出空字符串。\n原始分享口令："
                    ),
                },
                {"type": "field_ref", "field": "原始分享口令"},
            ],
        )

    # 3. Workflow 1: Button on Table 2 -> set 审核状态=入库 -> Add record to Table 3
    wf1_steps = [
        {
            "id": "step_trigger",
            "type": "ButtonTrigger",
            "title": "点击【一键入库拆解】按钮",
            "next": "step_mark_approved",
            "data": {
                "button_type": "buttonField",
                "table_name": "02_候选爆款池",
            },
        },
        {
            "id": "step_mark_approved",
            "type": "SetRecordAction",
            "title": "将当前候选视频标记为【入库】",
            "next": "step_push_deconstruct",
            "data": {
                "table_name": "02_候选爆款池",
                "ref_info": {"step_id": "step_trigger"},
                "field_values": [
                    {
                        "field_name": "审核状态",
                        "value": [{"value_type": "option", "value": {"name": "入库"}}],
                    }
                ],
            },
        },
        {
            "id": "step_push_deconstruct",
            "type": "AddRecordAction",
            "title": "自动推送新建到《03_爆款拆解库》",
            "next": None,
            "data": {
                "table_name": "03_爆款拆解库",
                "field_values": [
                    {
                        "field_name": "视频标题",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '视频标题')}"}],
                    },
                    {
                        "field_name": "平台",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '平台')}"}],
                    },
                    {
                        "field_name": "账号",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '账号')}"}],
                    },
                    {
                        "field_name": "视频链接",
                        "value": [
                            {
                                "value_type": "link",
                                "value": {
                                    "text": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '视频链接')}.text"}],
                                    "link": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '视频链接')}.link"}],
                                },
                            }
                        ],
                    },
                    {
                        "field_name": "视频ID",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '视频ID')}"}],
                    },
                    {
                        "field_name": "爆款数据摘要",
                        "value": [
                            {"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '点赞数')}"},
                            {"value_type": "text", "value": "赞 / "},
                            {"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '评论数')}"},
                            {"value_type": "text", "value": "评 / "},
                            {"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '收藏数')}"},
                            {"value_type": "text", "value": "藏 / "},
                            {"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '分享数')}"},
                            {"value_type": "text", "value": "享"},
                        ],
                    },
                    {
                        "field_name": "衍生话题标签",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '话题标签')}"}],
                    },
                    {
                        "field_name": "来源轮次",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_cand, '采集轮次')}"}],
                    },
                ],
            },
        },
    ]

    wf1_id = create_bind_enable_workflow(
        bt,
        t_cand,
        fid(f_cand, "✅ 一键入库拆解"),
        "✅ 一键入库并推送拆解库",
        wf1_steps,
    )

    # 4. Workflow 2: Button on Table 3 -> AI pick primary keyword -> Add to Table 1 -> mark 已回流词库=true
    wf2_steps = [
        {
            "id": "step_trigger",
            "type": "ButtonTrigger",
            "title": "点击【回流到词库】按钮",
            "next": "step_add_keyword",
            "data": {
                "button_type": "buttonField",
                "table_name": "03_爆款拆解库",
            },
        },
        {
            "id": "step_add_keyword",
            "type": "AddRecordAction",
            "title": "将新拆解关键词写入《01_词库池》",
            "next": "step_mark_reflowed",
            "data": {
                "table_name": "01_词库池",
                "field_values": [
                    {
                        "field_name": "关键词",
                        "value": [{"value_type": "ref", "value": f"$.step_trigger.{fid(f_dec, '内容关键词')}"}],
                    },
                    {
                        "field_name": "词类",
                        "value": [{"value_type": "option", "value": {"name": "概念名词"}}],
                    },
                    {
                        "field_name": "词源",
                        "value": [{"value_type": "option", "value": {"name": "AI扒词回流"}}],
                    },
                    {
                        "field_name": "目标平台",
                        "value": [
                            {"value_type": "option", "value": {"name": "小红书"}},
                            {"value_type": "option", "value": {"name": "抖音"}},
                        ],
                    },
                    {
                        "field_name": "采集状态",
                        "value": [{"value_type": "option", "value": {"name": "待采"}}],
                    },
                    {
                        "field_name": "轮次",
                        "value": [{"value_type": "text", "value": "飞书按钮回流"}],
                    },
                    {
                        "field_name": "来源说明",
                        "value": [
                            {"value_type": "text", "value": "表3按钮回流：《"},
                            {"value_type": "ref", "value": f"$.step_trigger.{fid(f_dec, '视频标题')}"},
                            {"value_type": "text", "value": "》"},
                        ],
                    },
                ],
            },
        },
        {
            "id": "step_mark_reflowed",
            "type": "SetRecordAction",
            "title": "标记本条记录【已回流词库】",
            "next": None,
            "data": {
                "table_name": "03_爆款拆解库",
                "ref_info": {"step_id": "step_trigger"},
                "field_values": [
                    {
                        "field_name": "已回流词库",
                        "value": [{"value_type": "boolean", "value": True}],
                    }
                ],
            },
        },
    ]

    wf2_id = create_bind_enable_workflow(
        bt,
        t_dec,
        fid(f_dec, "🔄 回流到词库"),
        "🔄 一键回流新词到词库池",
        wf2_steps,
    )

    cfg["workflows"] = {
        "approve_and_push": wf1_id,
        "reflow_to_keywords": wf2_id,
    }
    save_config(cfg)
    print("\nALL FEISHU NATIVE BUTTONS, AI EXTENSIONS, AND WORKFLOWS CONFIGURED!")


if __name__ == "__main__":
    main()
