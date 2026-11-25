# lark-yunyingworkflow (`bkworkflow-mcp`)

教育赛道小红书 / 抖音 **找爆款自动化飞轮工作流**，直连飞书多维表格（`lark-cli`），同时提供：

- **飞书云端闭环工作台**：3 张双向关联表（`01_词库池` ↔ `02_候选爆款池` ↔ `03_爆款拆解库`）+ 自动算分与防刷量公式 + 金矿词 ROI 评级 + 飞书原生 AI 自动拆解字段 + 一键入库/回流按钮自动化 + 看板/精简视图 + 总控应用页面；
- **WorkBuddy / MCP Server（`bkworkflow-mcp`）**：支持 `uvx` 免克隆零路径直接接入，全团队用自然语言查进度、拉待采词、查近 30 天热度、清洗导入口令、拆解与关键词回流；
- **本地零代码 Web 运营工作台**：一键启动浏览器可视化操作台。

---

## 快速接入 WorkBuddy（推荐，运营免克隆代码）

前提：本机已安装 [uv](https://docs.astral.sh/uv/) 及飞书官方 CLI（`npm install -g @larksuite/cli` 且已完成 `lark-cli auth login`）。

在 **WorkBuddy → 设置 → MCP 服务器** 中贴入以下配置（将 `BKWORKFLOW_BASE_TOKEN` 替换为你的飞书多维表格 Token）：

```json
{
  "mcpServers": {
    "bkworkflow": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/El-even1/lark-yunyingworkflow.git",
        "bkworkflow-mcp"
      ],
      "env": {
        "BKWORKFLOW_BASE_TOKEN": "YOUR_FEISHU_BASE_TOKEN",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

### MCP 暴露的工具清单（10 个）

| 工具名 | 作用 |
| :--- | :--- |
| `get_viral_dashboard` | 查看飞书三张表实时统计面板 |
| `list_pending_keywords` | 拉取《01_词库池》待采关键词 |
| `add_new_keywords` | 批量去重添加新搜索词到词库池 |
| `check_keyword_30d_trend` | 调用 `last30days-skill-cn` 查询关键词近 30 天跨平台热度 |
| `list_candidates` | 按爆款得分倒序查看候选池（支持筛选高优爆款 / 疑似刷量 / 待审 / 入库） |
| `update_candidate_status` | 更新候选视频审核状态（入库 / 待复核 / 淘汰） |
| `ingest_share_texts` | 自动解析小红书/抖音分享口令或 JSON，防刷量打分并去重写入表 2 |
| `get_pending_deconstruct_videos` | 同步表 2【入库】视频到表 3，返回待拆解文案 |
| `save_deconstruct_and_reflow` | 将 AI 拆解的观点、关键词、二创切入点写回表 3 并自动回流表 1 |
| `reflow_keywords_only` | 将表 3 未回流的关键词按顿号拆分、去重并回流到表 1 |

---

## 本地开发与初始化脚本

```powershell
# 1. 复制配置模板（或直接用环境变量 BKWORKFLOW_BASE_TOKEN）
copy config.example.json config.json

# 2. 从零创建飞书 3 表多维表格 + 应用页面 + 原生按钮与 AI 自动拆解 + 闭环看板视图
python scripts/setup_feishu_base.py
python scripts/setup_feishu_pages.py
python scripts/setup_feishu_native_automation.py
python scripts/upgrade_flywheel_ui.py

# 3. 命令行日常操作
python run.py status
python run.py next-keywords --limit 10 --csv
python run.py ingest --file <采集文件.json> --platform 小红书 --mark-done
python run.py reflow

# 4. 启动本地 Web 工作台 (http://127.0.0.1:8501)
python -m bkworkflow.web_app
```
