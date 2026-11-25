"""Read all 7 sheets of the legacy Feishu spreadsheet, clean/unpivot them,
and migrate deduplicated records into the new 3-table Feishu Base.

Never modifies the original spreadsheet.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    base_list_records,
    load_config,
    run_lark_cli,
)

ROW_PREFIX_RE = re.compile(r"^\[row=\d+\]\s*")


def fetch_sheet_rows(spreadsheet_token: str, sheet_id: str, max_col: str, max_row: int) -> list[list[str]]:
    """Fetch full CSV of a sheet in safe row windows and return list of rows."""
    all_rows: list[list[str]] = []
    step = 60
    for start in range(1, max_row + 1, step):
        end = min(start + step - 1, max_row)
        rng = f"A{start}:{max_col}{end}"
        res = run_lark_cli(
            [
                "sheets",
                "+csv-get",
                "--spreadsheet-token",
                spreadsheet_token,
                "--sheet-id",
                sheet_id,
                "--range",
                rng,
                "--max-chars",
                "120000",
            ]
        )
        data = res.get("data", res)
        annotated = data.get("annotated_csv") or ""
        if not annotated.strip():
            continue
        # Strip leading [row=N] prefix per logical row
        clean_lines = [ROW_PREFIX_RE.sub("", line) for line in annotated.splitlines()]
        reader = csv.reader(io.StringIO("\n".join(clean_lines)))
        for row in reader:
            if any(cell.strip() for cell in row):
                all_rows.append(row)
    return all_rows


def col_letter(n: int) -> str:
    res = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res


def parse_round1_sheet(rows: list[list[str]], sheet_name: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Parse 11.20第一轮爆款话题挖掘."""
    keywords: list[dict] = []
    candidates: list[dict] = []
    deconstructs: list[dict] = []
    if len(rows) <= 1:
        return keywords, candidates, deconstructs

    for row in rows[1:]:
        def g(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        topic_kw = g(1)
        account = g(2)
        title = g(3)
        raw_link = g(4)
        raw_metrics = g(5)
        raw_tags = g(6)
        transcript = g(7)
        core_view = g(8)
        content_kws = g(9)
        extra_tags = g(10)

        url = extract_clean_url(raw_link)
        if not url and not title and not transcript:
            continue

        platform = detect_platform(raw_link, default="抖音")
        vid = extract_video_id(url) or f"legacy:{title[:24]}"
        m = parse_metrics_text(raw_metrics)
        tags = extract_hashtags(raw_tags, extra_tags, raw_link)
        assess = assess_viral(m["likes"], m["comments"], m["saves"], m["shares"])

        # Table 1 keywords
        for kw in split_keywords(topic_kw):
            keywords.append(
                {
                    "关键词": kw,
                    "词类": ["概念名词"],
                    "词源": ["初始种子"],
                    "目标平台": [platform],
                    "采集状态": ["已采"],
                    "轮次": "11.20第一轮",
                    "来源说明": f"旧表《{sheet_name}》B列",
                }
            )
        for kw in split_keywords(content_kws):
            keywords.append(
                {
                    "关键词": kw,
                    "词类": ["概念名词"],
                    "词源": ["AI扒词回流"],
                    "目标平台": ["小红书", "抖音"],
                    "采集状态": ["待采"],
                    "轮次": "11.20第一轮",
                    "来源说明": f"旧表《{sheet_name}》J列内容关键词",
                }
            )

        # Table 2 candidate
        candidates.append(
            {
                "视频标题": title or extract_title_and_author(raw_link)[0] or "未命名视频",
                "平台": [platform],
                "视频ID": vid,
                "命中关键词": topic_kw.lstrip("#"),
                "账号": account,
                "视频链接": url,
                "点赞数": m["likes"],
                "评论数": m["comments"],
                "收藏数": m["saves"],
                "分享数": m["shares"],
                "话题标签": format_hashtags(tags),
                "采集轮次": sheet_name,
                "审核状态": [assess.suggested_status],
                "备注": assess.reason,
            }
        )

        # Table 3 deconstruct (if has transcript or core_view)
        if transcript or core_view:
            deconstructs.append(
                {
                    "视频标题": title or "未命名视频",
                    "平台": [platform],
                    "账号": account,
                    "视频链接": url,
                    "视频ID": vid,
                    "爆款数据摘要": format_metrics_summary(
                        m["likes"], m["comments"], m["saves"], m["shares"]
                    ),
                    "视频文案原文": transcript[:15000],
                    "核心观点": core_view,
                    "内容关键词": "、".join(split_keywords(content_kws, drop_stopwords=False)),
                    "衍生话题标签": format_hashtags(tags),
                    "二创切入点": "",
                    "已回流词库": bool(content_kws),
                    "来源轮次": sheet_name,
                }
            )

    return keywords, candidates, deconstructs


def parse_search_links_sheet(rows: list[list[str]], sheet_name: str, default_platform: str) -> tuple[list[dict], list[dict]]:
    """Unpivot horizontally-sprawling search sheets (11.22 XHS, 11.23/11.25 DY)."""
    keywords: list[dict] = []
    candidates: list[dict] = []
    if len(rows) <= 1:
        return keywords, candidates

    last_search_kw = ""
    for row in rows[1:]:
        col_a = row[0].strip() if len(row) > 0 else ""
        col_b = row[1].strip() if len(row) > 1 else ""
        col_c = row[2].strip() if len(row) > 2 else ""

        # In 11.25抖音搜索链接, col A is content kw, col B is search kw, links start from col C
        if col_c and not extract_clean_url(col_c):
            search_kw = col_c
            link_start_col = 3
        elif col_b and not extract_clean_url(col_b) and "没有主动显示" not in col_b:
            search_kw = col_b
            link_start_col = 2
        else:
            search_kw = last_search_kw
            link_start_col = 2

        if search_kw:
            last_search_kw = search_kw

        # Collect keywords from col A (content keywords), col B (tags), and search_kw
        for kw in split_keywords(col_a):
            keywords.append(
                {
                    "关键词": kw,
                    "词类": ["概念名词"],
                    "词源": ["AI扒词回流"],
                    "目标平台": [default_platform],
                    "采集状态": ["已采"],
                    "轮次": sheet_name[:5],
                    "来源说明": f"旧表《{sheet_name}》A列",
                }
            )
        for kw in split_keywords(search_kw):
            keywords.append(
                {
                    "关键词": kw,
                    "词类": ["平台联想词"],
                    "词源": ["平台联想"],
                    "目标平台": [default_platform],
                    "采集状态": ["已采"],
                    "轮次": sheet_name[:5],
                    "来源说明": f"旧表《{sheet_name}》搜索词",
                }
            )
        for tag in extract_hashtags(col_b):
            if tag not in split_keywords(search_kw, drop_stopwords=False):
                keywords.append(
                    {
                        "关键词": tag,
                        "词类": ["话题标签"],
                        "词源": ["爆款#标签"],
                        "目标平台": [default_platform],
                        "采集状态": ["待采"],
                        "轮次": sheet_name[:5],
                        "来源说明": f"旧表《{sheet_name}》推荐标签",
                    }
                )

        # Scan ALL cells from link_start_col onward to unpivot every horizontally pasted URL!
        cur_kw = search_kw
        for idx in range(link_start_col, len(row)):
            cell = row[idx].strip()
            if not cell:
                continue
            url = extract_clean_url(cell)
            if url:
                platform = detect_platform(cell, default=default_platform)
                vid = extract_video_id(url)
                title, author = extract_title_and_author(cell)
                # Look ahead 1-2 columns for companion hashtags cell (not containing a URL)
                neighbor_tags: list[str] = []
                for offset in (1, 2):
                    if idx + offset < len(row):
                        nxt = row[idx + offset].strip()
                        if nxt and not extract_clean_url(nxt) and ("#" in nxt or offset == 2):
                            neighbor_tags.extend(extract_hashtags(nxt))
                all_tags = extract_hashtags(cell, " ".join(f"#{t}" for t in neighbor_tags))
                candidates.append(
                    {
                        "视频标题": title or f"{cur_kw} 相关视频",
                        "平台": [platform],
                        "视频ID": vid,
                        "命中关键词": cur_kw,
                        "账号": author,
                        "视频链接": url,
                        "点赞数": 0,
                        "评论数": 0,
                        "收藏数": 0,
                        "分享数": 0,
                        "话题标签": format_hashtags(all_tags),
                        "采集轮次": sheet_name,
                        "审核状态": ["待审"],
                        "备注": "从旧表横向平铺行自动规整，待采集补全四项互动数据",
                    }
                )
            elif "#" not in cell and len(cell) <= 25 and not cell.isdigit():
                # Some rows put a second search term mid-row (like row 8 col L "美国精英高中")
                cur_kw = cell

    return keywords, candidates


def parse_transcript_sheet(rows: list[list[str]], sheet_name: str, default_platform: str) -> tuple[list[dict], list[dict]]:
    """Parse 11.22/11.23/11.25 链接原文 sheets."""
    keywords: list[dict] = []
    deconstructs: list[dict] = []
    if len(rows) <= 1:
        return keywords, deconstructs

    header = [c.strip() for c in rows[0]]
    # Locate columns flexibly
    def find_col(names: tuple[str, ...], fallback: int) -> int:
        for i, h in enumerate(header):
            for n in names:
                if n in h:
                    return i
        return fallback

    c_author = 1
    c_link = find_col(("链接",), 2)
    c_text = find_col(("文案", "原文"), 3)
    c_rewrite = find_col(("二创", "改写"), 4)
    c_kw = find_col(("内容关键词", "关键词"), 5)
    c_tag = find_col(("话题标签", "标签"), 6)

    for row in rows[1:]:
        def g(idx: int) -> str:
            return row[idx].strip() if idx < len(row) else ""

        raw_link = g(c_link)
        transcript = g(c_text)
        if not raw_link and not transcript:
            continue

        url = extract_clean_url(raw_link)
        platform = detect_platform(raw_link, default=default_platform)
        title, parsed_author = extract_title_and_author(raw_link)
        author = g(c_author) or parsed_author
        vid = extract_video_id(url) or f"text:{sheet_name}:{title[:20]}"
        kws = split_keywords(g(c_kw), drop_stopwords=False)
        tags = extract_hashtags(g(c_tag), raw_link)

        for kw in split_keywords(g(c_kw)):
            keywords.append(
                {
                    "关键词": kw,
                    "词类": ["概念名词"],
                    "词源": ["AI扒词回流"],
                    "目标平台": ["小红书", "抖音"],
                    "采集状态": ["待采"],
                    "轮次": sheet_name[:5],
                    "来源说明": f"旧表《{sheet_name}》内容关键词",
                }
            )

        deconstructs.append(
            {
                "视频标题": title or f"{author or '未知博主'} 视频",
                "平台": [platform],
                "账号": author,
                "视频链接": url,
                "视频ID": vid,
                "爆款数据摘要": "待补数据",
                "视频文案原文": transcript[:15000],
                "核心观点": "",
                "内容关键词": "、".join(kws),
                "衍生话题标签": format_hashtags(tags),
                "二创切入点": g(c_rewrite),
                "已回流词库": bool(kws),
                "来源轮次": sheet_name,
            }
        )

    return keywords, deconstructs


def main() -> None:
    cfg = load_config()
    if not cfg.get("base_token"):
        raise RuntimeError("Run scripts/setup_feishu_base.py first.")

    src_token = cfg["source_spreadsheet_token"]
    base_token = cfg["base_token"]
    t_kw = cfg["tables"]["keywords"]
    t_cand = cfg["tables"]["candidates"]
    t_dec = cfg["tables"]["deconstruct"]

    wb = run_lark_cli(["sheets", "+workbook-info", "--spreadsheet-token", src_token])
    sheets = wb.get("data", wb).get("sheets", [])

    all_keywords: dict[str, dict[str, Any]] = {}
    all_candidates: dict[str, dict[str, Any]] = {}
    all_deconstructs: dict[str, dict[str, Any]] = {}

    def add_kw(rec: dict[str, Any]) -> None:
        k = rec["关键词"].strip()
        if not k:
            return
        if k not in all_keywords:
            all_keywords[k] = rec
        else:
            # Merge target platforms
            existing = all_keywords[k]
            merged_p = list(dict.fromkeys(existing["目标平台"] + rec["目标平台"]))
            existing["目标平台"] = merged_p
            if existing["采集状态"] == ["待采"] and rec["采集状态"] == ["已采"]:
                existing["采集状态"] = ["已采"]

    def add_cand(rec: dict[str, Any]) -> None:
        vid = rec["视频ID"].strip()
        if not vid:
            return
        if vid not in all_candidates:
            all_candidates[vid] = rec
        else:
            # Prefer record that has non-zero metrics
            cur = all_candidates[vid]
            if cur["点赞数"] == 0 and rec["点赞数"] > 0:
                all_candidates[vid] = rec

    def add_dec(rec: dict[str, Any]) -> None:
        vid = rec["视频ID"].strip()
        if not vid:
            return
        if vid not in all_deconstructs:
            all_deconstructs[vid] = rec

    for s in sheets:
        sid = s["sheet_id"]
        sname = s["sheet_name"]
        rc = min(int(s["row_count"]), 220)
        cc = col_letter(min(int(s["column_count"]), 26))
        print(f"Reading legacy sheet: {sname} ({sid}, {rc}x{cc}) ...")
        rows = fetch_sheet_rows(src_token, sid, cc, rc)
        print(f"  -> non-empty rows: {len(rows)}")

        if "第一轮" in sname:
            kws, cands, decs = parse_round1_sheet(rows, sname)
            for x in kws:
                add_kw(x)
            for x in cands:
                add_cand(x)
            for x in decs:
                add_dec(x)
        elif "搜索链接" in sname:
            plat = "小红书" if "小红书" in sname else "抖音"
            kws, cands = parse_search_links_sheet(rows, sname, plat)
            for x in kws:
                add_kw(x)
            for x in cands:
                add_cand(x)
        elif "链接原文" in sname:
            plat = "小红书" if "小红书" in sname else "抖音"
            kws, decs = parse_transcript_sheet(rows, sname, plat)
            for x in kws:
                add_kw(x)
            for x in decs:
                add_dec(x)

    # Deduplicate against already existing records in the Base (idempotent!)
    existing_kws = {
        str(r.get("关键词", "")).strip() for r in base_list_records(base_token, t_kw)
    }
    existing_cands = {
        str(r.get("视频ID", "")).strip() for r in base_list_records(base_token, t_cand)
    }
    existing_decs = {
        str(r.get("视频ID", "")).strip() for r in base_list_records(base_token, t_dec)
    }

    new_kws = [v for k, v in all_keywords.items() if k not in existing_kws]
    new_cands = [v for k, v in all_candidates.items() if k not in existing_cands]
    new_decs = [v for k, v in all_deconstructs.items() if k not in existing_decs]

    # Save cleaned local snapshot for transparency
    out_dir = PROJECT_ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "migrated_snapshot.json").write_text(
        json.dumps(
            {
                "keywords": list(all_keywords.values()),
                "candidates": list(all_candidates.values()),
                "deconstructs": list(all_deconstructs.values()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Parsed unique totals: keywords={len(all_keywords)}, "
        f"candidates={len(all_candidates)}, deconstructs={len(all_deconstructs)}"
    )
    print(
        f"Writing new records to Base: keywords={len(new_kws)}, "
        f"candidates={len(new_cands)}, deconstructs={len(new_decs)}"
    )

    if new_kws:
        base_batch_create(base_token, t_kw, new_kws)
    if new_cands:
        base_batch_create(base_token, t_cand, new_cands)
    if new_decs:
        base_batch_create(base_token, t_dec, new_decs)

    print("Migration complete!")


if __name__ == "__main__":
    main()
