---
name: bk-viral-workflow
description: "教育赛道小红书/抖音找爆款自动化工作流：直连飞书多维表格《爆款话题挖掘·自动化工作台》，串联定词验热（last30days-skill-cn）、批量采集（MediaCrawler / Agent-Reach）、自动防刷量打分入库、AI 拆解核心观点与关键词自动回流。在用户说“跑一轮找爆款”、“拉待采词”、“导入采集结果”、“拆解入库视频”、“关键词回流”或查看爆款库进度时激活。"
---

# 爆款话题挖掘自动化工作流（`bk-viral-workflow`）

本 Skill 封装了 `e:\AI_Workspace\08_space\bkworkflow` 的全套飞书直连飞轮，替代旧版 7 张碎片表 + 4 次手工贴外部 AI + 进草稿箱测标签的流程。

## 飞书多维表格结构（配置文件：`config.json`）

- **表 1 `01_词库池`**：所有搜索词、地名、概念词、平台联想词、话题标签统一去重管理（状态：`待采 / 已采 / 暂停/废弃`）。
- **表 2 `02_候选爆款池`**：一行一条视频，赞/评/藏/享独立数字列，原生公式自动计算：
  - `爆款得分` = `赞×1 + 评×3 + 藏×2 + 享×4`
  - `评赞比`、`藏赞比`
  - `防刷量预警`（`赞≥5000 且 评赞比<0.5%` 自动标 `⚠️疑似刷量待复核`；得分≥5万标 `🔥高优爆款`）
- **表 3 `03_爆款拆解库`**：沉淀核心观点、干净文案、内容关键词、二创切入点，并标记 `已回流词库`。

## 标准执行指令（在项目根目录执行）

1. **查看当前进度面板**
   ```powershell
   python run.py status
   ```
2. **第 ① 步：取本轮待采词 & 验证近 30 天热度**
   ```powershell
   python run.py next-keywords --limit 10
   python run.py trend "教育成本" --quick
   ```
3. **第 ② 步：采集小红书 / 抖音（二选一或互补）**
   - 轻量实时搜索：使用已安装的 `agent-reach`（`tools/Agent-Reach`）检索关键词与热门评论。
   - 批量抓表：使用 `tools/MediaCrawler`（`--platform xhs` 或 `--platform dy`，`--type search`，`--save_data_option json`）。
4. **第 ③ 步：清洗、防刷量打分并去重写入飞书《02_候选爆款池》**
   ```powershell
   python run.py ingest --file <采集输出JSON/CSV> --platform 小红书 --round 11.26第一轮 --mark-done
   ```
   > 人工唯一介入点：打开飞书表 2，按「爆款得分」倒序扫一眼，将想深挖的视频 `审核状态` 改为 `入库`。
5. **第 ④ 步：同步【入库】视频 → AI 批量拆解 → 新词自动回流表 1**
   ```powershell
   python run.py sync-approved
   ```
   - 读取生成的 `data/pending_deconstruct.json`，对每条视频按下方规范拆解并纠偏 ASR 错别字，输出 `data/deconstructed.json`：
     - `核心观点`：3~5 条短句判断，不照抄原文。
     - `内容关键词`：5~8 个具体可搜索的中长尾名词/地名/场景词（过滤“教育/学习”等过泛大词），用 `、` 分隔。
     - `衍生话题标签`：高相关 `#话题标签`。
     - `二创切入点`：1~2 句针对家长/学生痛点的改写钩子。
   - 回写飞书并自动回流词库：
     ```powershell
     python run.py write-deconstruct --file data/deconstructed.json
     python run.py reflow
     ```
