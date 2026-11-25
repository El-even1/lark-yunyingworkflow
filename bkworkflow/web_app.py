"""Zero-code Web Workbench server (Starlette + Uvicorn) for non-technical ops teams."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from bkworkflow import service
from bkworkflow.feishu_cli import PROJECT_ROOT

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _err(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=status)


async def index(_request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def api_summary(request: Request) -> JSONResponse:
    try:
        refresh = request.query_params.get("refresh") == "1"
        return JSONResponse({"ok": True, "data": service.get_dashboard_summary(force_refresh=refresh)})
    except Exception as e:
        return _err(e, 500)


async def api_keywords_list(request: Request) -> JSONResponse:
    try:
        qp = request.query_params
        data = service.list_keywords(
            status=qp.get("status") or None,
            platform=qp.get("platform") or None,
            limit=int(qp.get("limit", "150")),
            force_refresh=qp.get("refresh") == "1",
        )
        return JSONResponse({"ok": True, "items": data})
    except Exception as e:
        return _err(e, 500)


async def api_keywords_add(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        res = service.add_keywords(
            body.get("raw_text", ""),
            word_type=body.get("word_type", "概念名词"),
            source=body.get("source", "初始种子"),
            platforms=body.get("platforms") or ["小红书", "抖音"],
            round_name=body.get("round_name", ""),
            note=body.get("note", "Web工作台添加"),
        )
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_trend(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        kw = str(body.get("keyword") or "").strip()
        if not kw:
            return _err(ValueError("请输入要验证的关键词"))
        res = service.check_keyword_trend(kw, quick=bool(body.get("quick", True)))
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e, 500)


async def api_candidates_list(request: Request) -> JSONResponse:
    try:
        qp = request.query_params
        data = service.list_candidates(
            filter_mode=qp.get("filter", "all"),
            platform=qp.get("platform", "全部"),
            search=qp.get("search", ""),
            limit=int(qp.get("limit", "150")),
            force_refresh=qp.get("refresh") == "1",
        )
        return JSONResponse({"ok": True, "items": data})
    except Exception as e:
        return _err(e, 500)


async def api_candidate_status(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        res = service.update_candidate_status(body["record_id"], body["status"])
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_ingest_preview(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        items = service.parse_pasted_share_texts(
            body.get("raw_text", ""),
            default_platform=body.get("platform", ""),
            default_keyword=body.get("keyword", ""),
            round_name=body.get("round_name", ""),
        )
        return JSONResponse({"ok": True, "items": items})
    except Exception as e:
        return _err(e)


async def api_ingest_commit(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        items = body.get("items")
        if items is None:
            items = service.parse_pasted_share_texts(
                body.get("raw_text", ""),
                default_platform=body.get("platform", ""),
                default_keyword=body.get("keyword", ""),
                round_name=body.get("round_name", ""),
            )
        res = service.ingest_candidate_records(
            items,
            mark_keywords_done=bool(body.get("mark_done", True)),
        )
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_ingest_upload(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            return _err(ValueError("请上传 JSON 或 CSV 文件"))
        suffix = Path(upload.filename or "upload.json").suffix or ".json"
        content = await upload.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            res = service.ingest_from_file(
                tmp_path,
                platform=str(form.get("platform") or ""),
                keyword=str(form.get("keyword") or ""),
                round_name=str(form.get("round_name") or ""),
                mark_keywords_done=str(form.get("mark_done") or "true").lower() == "true",
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_deconstruct_list(request: Request) -> JSONResponse:
    try:
        qp = request.query_params
        data = service.list_deconstructs(
            only_pending=qp.get("only_pending") == "1",
            limit=int(qp.get("limit", "100")),
            force_refresh=qp.get("refresh") == "1",
        )
        return JSONResponse({"ok": True, "items": data})
    except Exception as e:
        return _err(e, 500)


async def api_sync_approved(_request: Request) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, "data": service.sync_approved_to_deconstruct()})
    except Exception as e:
        return _err(e, 500)


async def api_deconstruct_ai(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        res = service.ai_deconstruct_batch(
            body.get("record_ids") or [],
            api_base=body.get("api_base") or "https://api.deepseek.com/v1",
            api_key=body.get("api_key") or "",
            model=body.get("model") or "deepseek-chat",
        )
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_deconstruct_save(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        items = body.get("items")
        if isinstance(items, str):
            items = json.loads(items)
        res = service.save_deconstruct_items(items or [])
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e)


async def api_reflow(request: Request) -> JSONResponse:
    try:
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass
        res = service.reflow_keywords_to_pool(round_name=str(body.get("round_name") or ""))
        return JSONResponse({"ok": True, "data": res})
    except Exception as e:
        return _err(e, 500)


async def api_workbuddy_config(_request: Request) -> JSONResponse:
    lan_ip = service.get_lan_ip()
    mcp_script = str(PROJECT_ROOT / "bkworkflow" / "mcp_server.py")
    http_cfg = {
        "mcpServers": {
            "bkworkflow": {
                "type": "streamable-http",
                "url": f"http://{lan_ip}:8502/mcp",
                "description": "教育赛道找爆款·飞书多维表格自动化工作流",
            }
        }
    }
    stdio_cfg = {
        "mcpServers": {
            "bkworkflow": {
                "type": "stdio",
                "command": "python",
                "args": [mcp_script],
                "env": {"PYTHONIOENCODING": "utf-8"},
            }
        }
    }
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "lan_ip": lan_ip,
                "web_url": f"http://{lan_ip}:8501",
                "mcp_http_url": f"http://{lan_ip}:8502/mcp",
                "workbuddy_http_config": http_cfg,
                "workbuddy_stdio_config": stdio_cfg,
            },
        }
    )


routes = [
    Route("/", index),
    Route("/api/summary", api_summary),
    Route("/api/keywords", api_keywords_list),
    Route("/api/keywords/add", api_keywords_add, methods=["POST"]),
    Route("/api/trend", api_trend, methods=["POST"]),
    Route("/api/candidates", api_candidates_list),
    Route("/api/candidates/status", api_candidate_status, methods=["POST"]),
    Route("/api/ingest/preview", api_ingest_preview, methods=["POST"]),
    Route("/api/ingest/commit", api_ingest_commit, methods=["POST"]),
    Route("/api/ingest/upload", api_ingest_upload, methods=["POST"]),
    Route("/api/deconstruct", api_deconstruct_list),
    Route("/api/deconstruct/sync", api_sync_approved, methods=["POST"]),
    Route("/api/deconstruct/ai", api_deconstruct_ai, methods=["POST"]),
    Route("/api/deconstruct/save", api_deconstruct_save, methods=["POST"]),
    Route("/api/reflow", api_reflow, methods=["POST"]),
    Route("/api/workbuddy-config", api_workbuddy_config),
]

app = Starlette(routes=routes)


def run_server(host: str = "0.0.0.0", port: int = 8501) -> None:
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
