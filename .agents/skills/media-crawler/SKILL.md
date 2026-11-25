---
name: media-crawler
description: "调用本项目 tools/MediaCrawler 批量采集小红书（xhs）、抖音（dy）、B站等平台的关键词搜索结果、四项互动数据（赞/评/藏/享）、话题标签和评论区，并配合 python run.py ingest 一键清洗打分导入飞书多维表格《02_候选爆款池》。"
---

# MediaCrawler 批量采集指南（本地目录：`tools/MediaCrawler`）

用于大批量按词库采集小红书与抖音搜索结果，直接替代旧 SOP 中“手动搜词 → 截图 → 抄口令 → 抄赞评藏 → 扒标签”整条人工链。

## 首次环境初始化（只需执行一次）

```powershell
cd e:\AI_Workspace\08_space\bkworkflow\tools\MediaCrawler
uv sync
uv run playwright install chromium
```

> 若不用 `uv`，也可在新建 venv 中 `pip install -r requirements.txt && playwright install chromium`。

## 采集并与飞书联动标准步骤

1. **从飞书表 1 拉取本轮待采关键词（逗号分隔）**
   ```powershell
   cd e:\AI_Workspace\08_space\bkworkflow
   python run.py next-keywords --limit 5 --platform 小红书 --csv
   ```

2. **运行 MediaCrawler 采集（首次扫码登录小号，之后复用登录态）**
   - 小红书（`xhs`）：
     ```powershell
     cd e:\AI_Workspace\08_space\bkworkflow\tools\MediaCrawler
     uv run main.py --platform xhs --lt qrcode --type search --keywords "教育成本,AI教育,美国精英高中" --save_data_option json
     ```
   - 抖音（`dy`）：
     ```powershell
     uv run main.py --platform dy --lt qrcode --type search --keywords "教育成本,AI教育,美国精英高中" --save_data_option json
     ```
   > 采集输出默认落在 `tools/MediaCrawler/data/xhs/json/` 或 `tools/MediaCrawler/data/douyin/json/`。

3. **一键清洗、防刷量打分、去重并回写飞书《02_候选爆款池》**
   ```powershell
   cd e:\AI_Workspace\08_space\bkworkflow
   python run.py ingest --file tools/MediaCrawler/data/xhs/json/search_contents_xxx.json --platform 小红书 --round 11.26第一轮 --mark-done
   ```

## 合规与防风控提示

- 建议使用测试小号扫码，单次词数控制在 3~5 个，调大 `config/base_config.py` 中的请求间隔（`CRAWLER_MAX_SLEEP_SEC`），避免触发滑块或账号限流。
- 遇到验证码/滑块时由本人在弹窗中手动处理，不要强行高频重试。
