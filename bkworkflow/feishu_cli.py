"""Thin, portable Python wrapper around local lark-cli for Feishu Sheets & Base.

Works both from a cloned workspace AND when installed ephemerally via `uvx` / `pip`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

# Writable working directory for lark-cli relative @file / --output artifacts
WORK_DIR = (
    PROJECT_ROOT
    if (PROJECT_ROOT / "run.py").exists() and os.access(PROJECT_ROOT, os.W_OK)
    else (Path.home() / ".bkworkflow")
)

_RESOLVED_CFG_CACHE: dict[str, Any] | None = None


def _candidate_lark_cli_paths() -> list[Path]:
    paths: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        npm_dir = Path(appdata) / "npm"
        paths.append(npm_dir / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe")
        paths.append(npm_dir / "lark-cli.cmd")
    # Common custom global npm prefixes on Windows & macOS/Linux
    for raw in (
        r"E:\nodejs\node_global\node_modules\@larksuite\cli\bin\lark-cli.exe",
        r"E:\nodejs\node_global\lark-cli.cmd",
        r"C:\Program Files\nodejs\node_modules\@larksuite\cli\bin\lark-cli.exe",
        str(Path.home() / ".npm-global" / "bin" / "lark-cli"),
        "/usr/local/bin/lark-cli",
        "/opt/homebrew/bin/lark-cli",
    ):
        paths.append(Path(raw))
    return paths


def find_lark_cli() -> str:
    env_bin = os.environ.get("LARK_CLI_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin

    # Prefer direct lark-cli.exe over .cmd wrapper on Windows to avoid cmd.exe '&' escaping issues
    for candidate in _candidate_lark_cli_paths():
        if candidate.exists():
            return str(candidate)

    in_path = shutil.which("lark-cli")
    if in_path:
        p = Path(in_path)
        if p.suffix.lower() == ".cmd":
            direct_exe = p.parent / "node_modules" / "@larksuite" / "cli" / "bin" / "lark-cli.exe"
            if direct_exe.exists():
                return str(direct_exe)
        return in_path

    raise FileNotFoundError(
        "未找到 lark-cli。请先安装飞书 CLI (`npm install -g @larksuite/cli`) 并完成 `lark-cli auth login`，"
        "或通过环境变量 LARK_CLI_BIN 指定可执行文件路径。"
    )


def run_lark_cli(
    args: list[str],
    *,
    cwd: Path | None = None,
    as_identity: str | None = "user",
    parse_json: bool = True,
) -> Any:
    exe = find_lark_cli()
    cmd = [exe, *args]
    if as_identity and "--as" not in args:
        cmd.extend(["--as", as_identity])

    run_dir = cwd or WORK_DIR
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"

    proc = None
    for attempt in range(3):
        proc = subprocess.run(
            cmd,
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0:
            break
        if proc.returncode == 4 and "transport" in (proc.stderr or "") and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        raise RuntimeError(
            f"lark-cli failed (exit {proc.returncode}): {' '.join(args[:4])}\n"
            f"STDOUT:\n{proc.stdout[:1500]}\nSTDERR:\n{proc.stderr[:1500]}"
        )
    assert proc is not None
    if not parse_json:
        return proc.stdout
    stdout = proc.stdout.strip()
    if not stdout:
        return {}
    data = json.loads(stdout)
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(f"lark-cli business error: {json.dumps(data, ensure_ascii=False)}")
    return data


def _discover_tables_by_name(base_token: str) -> dict[str, str]:
    res = run_lark_cli(["base", "+table-list", "--base-token", base_token])
    items = res.get("data", res).get("items") or res.get("data", res).get("tables") or []
    by_name = {(it.get("table_name") or it.get("name")): (it.get("table_id") or it.get("id")) for it in items}
    return {
        "keywords": by_name.get("01_词库池", "01_词库池"),
        "candidates": by_name.get("02_候选爆款池", "02_候选爆款池"),
        "deconstruct": by_name.get("03_爆款拆解库", "03_爆款拆解库"),
    }


def load_config() -> dict[str, Any]:
    """Load config from local config.json, ~/.bkworkflow/config.json, or BKWORKFLOW_BASE_TOKEN env."""
    global _RESOLVED_CFG_CACHE
    env_token = os.environ.get("BKWORKFLOW_BASE_TOKEN", "").strip()

    for path in (CONFIG_PATH, Path.home() / ".bkworkflow" / "config.json"):
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            if env_token and env_token != cfg.get("base_token"):
                cfg["base_token"] = env_token
                cfg["base_url"] = f"https://my.feishu.cn/base/{env_token}"
                cfg["tables"] = _discover_tables_by_name(env_token)
            return cfg

    if env_token:
        if _RESOLVED_CFG_CACHE and _RESOLVED_CFG_CACHE.get("base_token") == env_token:
            return _RESOLVED_CFG_CACHE
        tables = {
            "keywords": os.environ.get("BKWORKFLOW_TABLE_KEYWORDS") or "",
            "candidates": os.environ.get("BKWORKFLOW_TABLE_CANDIDATES") or "",
            "deconstruct": os.environ.get("BKWORKFLOW_TABLE_DECONSTRUCT") or "",
        }
        if not all(tables.values()):
            discovered = _discover_tables_by_name(env_token)
            for k in tables:
                tables[k] = tables[k] or discovered[k]
        cfg = {
            "base_name": os.environ.get("BKWORKFLOW_BASE_NAME", "爆款话题挖掘·自动化工作台"),
            "base_token": env_token,
            "base_url": os.environ.get("BKWORKFLOW_BASE_URL", f"https://my.feishu.cn/base/{env_token}"),
            "app_url": os.environ.get("BKWORKFLOW_APP_URL", ""),
            "tables": tables,
        }
        _RESOLVED_CFG_CACHE = cfg
        return cfg

    return {}


def save_config(cfg: dict[str, Any]) -> None:
    target = CONFIG_PATH if (PROJECT_ROOT / "run.py").exists() else (Path.home() / ".bkworkflow" / "config.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_temp_rel_json(payload: Any, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".lark_tmp_", suffix=".json", dir=str(work_dir))
    os.close(fd)
    p = Path(tmp_name)
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def base_list_records(
    base_token: str,
    table_id: str,
    *,
    filter_obj: dict[str, Any] | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 0
    tmp_dir = WORK_DIR / ".cache"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    while True:
        out_file = tmp_dir / f"records_{table_id}_{offset}.ndjson"
        rel_out = f".cache/{out_file.name}"
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--limit",
            str(limit),
            "--offset",
            str(offset),
            "--format",
            "ndjson",
            "--output",
            rel_out,
            "--overwrite",
        ]
        if filter_obj:
            args.extend(["--filter-json", json.dumps(filter_obj, ensure_ascii=False)])

        res = run_lark_cli(args, cwd=WORK_DIR)
        if out_file.exists():
            for line in out_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            out_file.unlink(missing_ok=True)
        manifest_file = out_file.with_suffix(".manifest.json")
        manifest_file.unlink(missing_ok=True)

        data = res.get("data", res) if isinstance(res, dict) else {}
        has_more = bool(data.get("has_more"))
        if not has_more:
            break
        offset += limit
    return records


def base_batch_create(
    base_token: str,
    table_id: str,
    records: list[dict[str, Any]],
    *,
    batch_size: int = 100,
) -> list[str]:
    """Serial batch insert into a Feishu Base table (max 200 per call, default 100)."""
    created_ids: list[str] = []
    tmp_dir = WORK_DIR / ".cache"
    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        tmp_file = _write_temp_rel_json({"create_records": chunk}, tmp_dir)
        rel_path = f"@.cache/{tmp_file.name}"
        try:
            res = run_lark_cli(
                [
                    "base",
                    "+record-batch-create",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--json",
                    rel_path,
                ],
                cwd=WORK_DIR,
            )
            data = res.get("data", res) if isinstance(res, dict) else {}
            ids = data.get("record_id_list") or []
            created_ids.extend(ids)
        finally:
            tmp_file.unlink(missing_ok=True)
    return created_ids


def base_batch_update(
    base_token: str,
    table_id: str,
    updates: dict[str, dict[str, Any]],
    *,
    batch_size: int = 100,
) -> None:
    """Serial batch update `{record_id: {field: value}}`."""
    items = list(updates.items())
    tmp_dir = WORK_DIR / ".cache"
    for i in range(0, len(items), batch_size):
        chunk = dict(items[i : i + batch_size])
        tmp_file = _write_temp_rel_json({"update_records": chunk}, tmp_dir)
        rel_path = f"@.cache/{tmp_file.name}"
        try:
            run_lark_cli(
                [
                    "base",
                    "+record-batch-update",
                    "--base-token",
                    base_token,
                    "--table-id",
                    table_id,
                    "--json",
                    rel_path,
                ],
                cwd=WORK_DIR,
            )
        finally:
            tmp_file.unlink(missing_ok=True)
