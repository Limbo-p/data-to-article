# -*- coding: utf-8 -*-
"""data-to-article 总控面板（P0）：dta serve。

零依赖 http.server 实现。功能：
  - 设置：存储后端（file/mongo/mysql）+ LLM + 调度 + API Key（写 config/config.yaml + config/.env）
  - 流水线：手动/试运行 dta run，实时日志（SSE），运行历史
  - 概览：当前配置 + 存储后端 + 数据量 + 最近运行
执行全部走 data_to_article CLI；数据读取走 StorageBackend / 存储适配器。
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from data_to_article.settings import load_config  # noqa: E402
from data_to_article.storage import get_storage  # noqa: E402
from data_to_article.publish import publish_article  # noqa: E402

CONFIG_FILE = ROOT / "config" / "config.yaml"
ENV_FILE = ROOT / "config" / ".env"
TEMPLATE_FILE = Path(__file__).resolve().parent / "template.html"
PY = sys.executable

_tasks: dict = {}
_tasks_lock = threading.Lock()


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ===================== 配置读写 =====================

def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_yaml(path: Path, data: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _current_config() -> dict:
    cfg = load_config()
    cfg.setdefault("storage", {})
    cfg.setdefault("llm", {})
    return cfg


def _read_env() -> dict:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env(data: dict) -> None:
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in data.items() if v]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _key_status() -> dict:
    env = _read_env()
    out = {}
    for k in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        v = env.get(k) or os.environ.get(k, "")
        if v:
            out[k] = v[:6] + "****" + v[-2:]
    return out


# ===================== 存储/LLM 测试 =====================

def _test_storage(body: dict) -> dict:
    kind = str(body.get("backend") or "file").lower()
    try:
        if kind == "file":
            root = Path(body.get("root") or "data")
            root.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "message": f"本地目录 {root} 可用（清洗/归类/二创三库自动分目录）"}
        if kind == "mongo":
            from pymongo import MongoClient
            uri = str(body.get("uri") or os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
            c = MongoClient(uri, serverSelectionTimeoutMS=3000)
            c.admin.command("ping")
            c.close()
            return {"ok": True, "message": f"MongoDB 连接成功：{uri}"}
        if kind == "mysql":
            import pymysql
            conn = pymysql.connect(
                host=str(body.get("host") or "localhost"),
                port=int(body.get("port") or 3306),
                user=str(body.get("user") or "root"),
                password=str(body.get("password") or ""),
                charset="utf8mb4", connect_timeout=3,
            )
            conn.close()
            return {"ok": True, "message": "MySQL 连接成功（表由 MySqlBackend 首次使用自动创建）"}
        return {"ok": False, "error": f"未知存储后端：{kind}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _test_llm(body: dict) -> dict:
    provider = str(body.get("provider") or "mock")
    key = str(body.get("api_key") or "").strip()
    if provider != "mock" and not key:
        return {"ok": False, "error": f"{provider} 需要 API Key"}
    if provider == "mock":
        return {"ok": True, "message": "provider=mock（零依赖，不调用外部 LLM）"}
    return {"ok": True, "message": f"provider={provider} 配置有效（为避免费用，未实际调用；运行阶段会真实调用）"}


# ===================== 保存设置 =====================

def _save_setup(body: dict) -> dict:
    cfg = _current_config()
    st = body.get("storage") or {}
    if st:
        backend = str(st.get("backend") or "file")
        cfg.setdefault("storage", {})["backend"] = backend
        if backend == "file":
            cfg["storage"]["root"] = st.get("root") or "data"
        elif backend == "mongo":
            cfg["storage"]["uri"] = st.get("uri", "")
            cfg["storage"]["database"] = st.get("database", "data_to_article")
            if st.get("collections"):
                cfg["storage"]["collections"] = {
                    str(k): str(v) for k, v in st["collections"].items() if v
                }
        elif backend == "mysql":
            m = cfg["storage"].setdefault("mysql", {})
            for k in ("host", "port", "user", "password", "database", "table_prefix"):
                if st.get(k) is not None:
                    m[k] = st[k]
    llm = body.get("llm") or {}
    if llm:
        provider = str(llm.get("provider") or "mock")
        cfg.setdefault("llm", {})["provider"] = provider
        entry = cfg["llm"].setdefault(provider, {})
        if llm.get("base_url"):
            entry["base_url"] = str(llm["base_url"]).rstrip("/")
        if llm.get("model"):
            entry["model"] = llm["model"]
    sched = body.get("schedule") or {}
    if sched:
        cfg.setdefault("schedule", {})["mode"] = sched.get("mode", "daily")
        daily = cfg["schedule"].setdefault("daily", {})
        if sched.get("wash_classify_time"):
            daily["wash_classify_time"] = sched["wash_classify_time"]
        if sched.get("generate_time"):
            daily["generate_time"] = sched["generate_time"]
        if sched.get("catch_up") is not None:
            daily["catch_up"] = bool(sched.get("catch_up"))
    _save_yaml(CONFIG_FILE, cfg)

    keys = body.get("keys") or {}
    if any(keys.get(k) for k in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")):
        env = _read_env()
        for k in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            if keys.get(k):
                env[k] = str(keys[k]).strip()
        _write_env(env)
    return {"ok": True, "config": str(CONFIG_FILE), "env": str(ENV_FILE)}


# ===================== 数据统计/运行历史 =====================

def _effective_backend(cfg: dict) -> str:
    """与 get_storage 一致的后端解析：DTA_STORAGE > 标记文件 > config > 默认 mongo。"""
    from data_to_article.storage.registry import _read_marker_backend
    st = cfg.get("storage", {}) or {}
    return (os.environ.get("DTA_STORAGE")
            or _read_marker_backend()
            or st.get("backend") or "mongo")


def _storage_conn(cfg: dict) -> dict:
    st = cfg.get("storage", {}) or {}
    backend = st.get("backend") or "file"
    if backend == "mongo":
        return {
            "uri": st.get("uri") or os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
            "database": st.get("database") or os.environ.get("MONGO_DB", "data_to_article"),
            "collections": st.get("collections") or {},
        }
    if backend == "mysql":
        return st.get("mysql") or {}
    return {"root": st.get("root") or os.environ.get("DTA_STORAGE_ROOT", "data")}


def _stats() -> dict:
    cfg = _current_config()
    backend = _effective_backend(cfg)
    conn = _storage_conn(cfg)
    counts = {}
    try:
        if backend == "file":
            root = Path(conn.get("root", "data"))
            for name in ("raw", "cleaned", "events", "articles", "runs"):
                d = root / name
                counts[name] = len(list(d.glob("*.json"))) if d.exists() else 0
        elif backend == "mongo":
            from pymongo import MongoClient
            colls = conn.get("collections") or {}
            c = MongoClient(conn["uri"], serverSelectionTimeoutMS=3000)
            dbh = c[conn["database"]]
            def _cnt(cname):
                names = [x.strip() for x in str(cname).split(",") if x.strip()]
                return sum(dbh[n].count_documents({}) for n in names)
            counts["raw"] = _cnt(colls.get("raw", "raw_articles"))
            counts["cleaned"] = _cnt(colls.get("cleaned", "articles"))
            counts["events"] = _cnt(colls.get("events", "events"))
            counts["articles"] = _cnt(colls.get("event_articles", "event_articles"))
            c.close()
        elif backend == "mysql":
            import pymysql
            prefix = conn.get("table_prefix", "dta_")
            c = pymysql.connect(host=conn.get("host", "localhost"), port=int(conn.get("port", 3306)),
                                user=conn.get("user", "root"), password=conn.get("password", ""),
                                database=conn.get("database", "data_to_article"),
                                charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
            with c.cursor() as cur:
                for name, table in (("raw", "raw"), ("cleaned", "cleaned"),
                                    ("events", "events"), ("articles", "articles")):
                    cur.execute(f"SELECT COUNT(*) AS n FROM `{prefix}{table}`")
                    counts[name] = cur.fetchone()["n"]
            c.close()
    except Exception:
        pass
    return {"backend": backend, "conn": conn, "counts": counts, "keys": _key_status()}


def _recent_runs(limit: int = 20) -> list:
    cfg = _current_config()
    backend = _effective_backend(cfg)
    conn = _storage_conn(cfg)
    out = []
    try:
        if backend == "file":
            runs_dir = Path(conn.get("root", "data")) / "runs"
            if runs_dir.exists():
                for p in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                        d["_id"] = p.stem
                        out.append(d)
                    except Exception:
                        pass
        elif backend == "mongo":
            from pymongo import MongoClient
            colls = conn.get("collections") or {}
            c = MongoClient(conn["uri"], serverSelectionTimeoutMS=3000)
            for r in c[conn["database"]][colls.get("runs", "pipeline_runs")].find(
                    {}, {"_id": 0}).sort("started_at", -1).limit(limit):
                out.append(r)
            c.close()
        elif backend == "mysql":
            import pymysql
            prefix = conn.get("table_prefix", "dta_")
            c = pymysql.connect(host=conn.get("host", "localhost"), port=int(conn.get("port", 3306)),
                                user=conn.get("user", "root"), password=conn.get("password", ""),
                                database=conn.get("database", "data_to_article"),
                                charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
            with c.cursor() as cur:
                cur.execute(f"SELECT * FROM `{prefix}runs` ORDER BY id DESC LIMIT %s", (limit,))
                for r in cur.fetchall():
                    r["_id"] = str(r.get("id"))
                    out.append(r)
            c.close()
    except Exception:
        pass
    return out


# ===================== 任务（执行 dta） =====================

def _get_storage():
    return get_storage(_current_config())


def _event_detail(event_id: str) -> dict:
    st = _get_storage()
    event = st.get_event(event_id)
    arts = st.get_event_articles(event_id)
    return {"ok": True, "event": event, "articles": arts}


def _list_events(q: str = "", page: int = 1, limit: int = 20) -> dict:
    st = _get_storage()
    items = st.query_events(keyword=q, limit=0)
    total = len(items)
    start = max(0, (page - 1) * limit)
    page_items = items[start:start + limit]
    # 二创状态：以「二创库是否有该事件的文章」为准（旧库 ai_events 没有 generated 字段）
    for e in page_items:
        eid = e.get("event_id", "")
        e["generated"] = bool(eid) and st.articles_exist(eid)
        doc = st.get_event_articles(eid) if e["generated"] else None
        e["article_count"] = len((doc or {}).get("articles") or []) if doc else (e.get("article_count") or 0)
    return {"ok": True, "items": page_items, "total": total}


def _search(q: str) -> dict:
    st = _get_storage()
    return {"ok": True,
            "events": st.query_events(keyword=q, limit=20),
            "articles": st.search_articles(keyword=q, limit=20)}


def _review_queue(status: str = "pending", limit: int = 100) -> list:
    st = _get_storage()
    out = []
    for a in st.search_articles("", 0):
        if status and (a.get("review_status") or "pending") != status:
            continue
        out.append(a)
        if len(out) >= limit:
            break
    return out


def _publish_one(event_id: str, idx: int, dry_run: bool) -> dict:
    st = _get_storage()
    doc = st.get_event_articles(event_id)
    if not doc or not doc.get("articles") or idx >= len(doc["articles"]):
        return {"ok": False, "error": "文章不存在"}
    article = doc["articles"][idx]
    event = st.get_event(event_id)
    result = publish_article(_current_config(), article, event, dry_run=dry_run)
    if result.get("ok") and not dry_run:
        st.set_article_review(event_id, idx, "published", "已发布")
        st.record_publish({
            "event_id": event_id, "article_idx": idx,
            "title": article.get("title", ""),
            "status": "published", "published_at": _now(),
            "backend": result.get("backend"),
            "response": result.get("text") or result.get("message", ""),
        })
    return result


def _publish_batch(items: list, dry_run: bool) -> dict:
    results = []
    for it in items or []:
        res = _publish_one(str(it.get("event_id", "")),
                           _to_int(it.get("idx"), 0), dry_run)
        results.append({"event_id": it.get("event_id", ""), "idx": it.get("idx", 0), **res})
    return {"ok": True, "items": results}


def _publish_config_view() -> dict:
    return {"ok": True, "publish": _current_config().get("publish") or {}}


def _publish_config_save(body: dict) -> dict:
    p = body.get("publish")
    if isinstance(p, dict):
        cfg = _current_config()
        cfg["publish"] = p
        _save_yaml(CONFIG_FILE, cfg)
    return {"ok": True}


def _resolve_content(fp: str) -> dict:
    """按 content_fp 跨（多个）清洗集合解析参考原文。"""
    cfg = _current_config()
    backend = _effective_backend(cfg)
    conn = _storage_conn(cfg)
    try:
        if backend == "file":
            from data_to_article.storage.file import JsonFileBackend
            st = JsonFileBackend(root=conn.get("root", "data"))
            a = st.get_cleaned_by_fp(fp)
            return {"ok": True, "article": a} if a else {"ok": False, "error": "not found"}
        if backend == "mongo":
            from pymongo import MongoClient
            colls = conn.get("collections") or {}
            names = [x.strip() for x in str(colls.get("cleaned", "articles")).split(",") if x.strip()]
            c = MongoClient(conn["uri"], serverSelectionTimeoutMS=3000)
            dbh = c[conn["database"]]
            try:
                for name in names:
                    a = dbh[name].find_one({"content_fp": fp}, {"_id": 0})
                    if a:
                        return {"ok": True, "article": a}
            finally:
                c.close()
            return {"ok": False, "error": "not found"}
        if backend == "mysql":
            import pymysql
            prefix = conn.get("table_prefix", "dta_")
            c = pymysql.connect(host=conn.get("host", "localhost"), port=int(conn.get("port", 3306)),
                                user=conn.get("user", "root"), password=conn.get("password", ""),
                                database=conn.get("database", "data_to_article"),
                                charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
            try:
                with c.cursor() as cur:
                    cur.execute(f"SELECT doc FROM `{prefix}cleaned` WHERE content_fp=%s", (fp,))
                    row = cur.fetchone()
            finally:
                c.close()
            if row and row.get("doc"):
                return {"ok": True, "article": json.loads(row["doc"])}
            return {"ok": False, "error": "not found"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": False, "error": "not found"}


def _task_summary(t: dict) -> dict:
    return {"id": t["id"], "kind": t.get("kind"), "args": t.get("args"),
            "status": t["status"], "created_at": t.get("created_at"),
            "finished_at": t.get("finished_at"), "exit_code": t.get("exit_code")}


def _start_task(args: list) -> str:
    task_id = uuid.uuid4().hex[:12]
    log_q: "queue.Queue" = queue.Queue()
    task = {"id": task_id, "kind": "pipeline", "args": args, "status": "running",
            "created_at": _now(), "finished_at": None, "exit_code": None,
            "proc": None, "log": log_q, "stopped": False}
    with _tasks_lock:
        _tasks[task_id] = task

    def _run():
        env = os.environ.copy()
        env.update(_read_env())
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [PY, "-m", "data_to_article.cli", *args],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        with _tasks_lock:
            task["proc"] = proc
        lines = []
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                lines.append(line)
                log_q.put(line)
            code = proc.wait()
        except Exception as e:
            log_q.put(f"[task error] {e}")
            code = 1
        finally:
            with _tasks_lock:
                stopped = bool(task.get("stopped"))
                task["status"] = ("done" if code == 0 else
                                  ("stopped" if stopped else "failed"))
                task["exit_code"] = code
                task["finished_at"] = _now()
                task["proc"] = None
            log_q.put(None)

    threading.Thread(target=_run, daemon=True).start()
    return task_id


def _kill_tree(proc) -> None:
    if not proc or proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _stop_task(task_id: str) -> bool:
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task or task["status"] != "running":
            return False
        task["stopped"] = True
        proc = task.get("proc")
    if proc:
        _kill_tree(proc)
    return True


def _pipeline_args(body: dict) -> list:
    only_raw = str(body.get("only") or "")
    only = ",".join(s.strip() for s in only_raw.replace("，", ",").split(",") if s.strip())
    if not only:
        only = "wash,classify,generate"
    args = ["run", "--only", only]
    try:
        hours = int(body.get("hours") or 0)
    except (TypeError, ValueError):
        hours = 0
    try:
        limit = int(body.get("limit") or 0)
    except (TypeError, ValueError):
        limit = 0
    if hours > 0:
        args += ["--hours", str(hours)]
    if limit > 0:
        args += ["--limit", str(limit)]
    if bool(body.get("dry_run")):
        args.append("--dry-run")
    return args


# ===================== HTTP =====================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        def _default(o):
            # Mongo ObjectId / datetime 等转字符串，避免序列化报错
            try:
                from bson import ObjectId
                if isinstance(o, ObjectId):
                    return str(o)
            except Exception:
                pass
            if isinstance(o, datetime):
                return o.isoformat()
            return str(o)
        body = json.dumps(data, ensure_ascii=False, default=_default).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if path in ("/", "/index.html"):
                self._html(TEMPLATE_FILE.read_bytes())
                return
            if path == "/api/status":
                cfg = _current_config()
                try:
                    recent_events = _get_storage().query_events("", 10)
                except Exception:
                    recent_events = []
                self._json({"ok": True, "config_exists": CONFIG_FILE.exists(),
                            "storage": cfg.get("storage", {}),
                            "llm": cfg.get("llm", {}),
                            "schedule": cfg.get("schedule", {}),
                            "keys": _key_status(),
                            "stats": _stats(),
                            "recent_events": recent_events})
                return
            if path == "/api/pipeline/status":
                running = None
                with _tasks_lock:
                    for t in _tasks.values():
                        if t["status"] == "running":
                            running = _task_summary(t)
                            break
                self._json({"ok": True, "running": running is not None, "task": running})
                return
            if path == "/api/pipeline/runs":
                self._json({"ok": True, "items": _recent_runs(int(qs.get("limit", "20")))})
                return
            if path == "/api/events":
                self._json(_list_events(q=qs.get("q", ""),
                                        page=_to_int(qs.get("page"), 1),
                                        limit=_to_int(qs.get("limit"), 20)))
                return
            m = re.match(r"^/api/events/(evt_[A-Za-z0-9_]+)$", path)
            if m:
                self._json(_event_detail(m.group(1)))
                return
            if path == "/api/search":
                self._json(_search(qs.get("q", "")))
                return
            m = re.match(r"^/api/content/([0-9a-f]{32})$", path)
            if m:
                self._json(_resolve_content(m.group(1)))
                return
            if path == "/api/review/queue":
                self._json({"ok": True, "items": _review_queue(status=qs.get("status", "pending"))})
                return
            if path == "/api/publish/logs":
                self._json({"ok": True, "items": _get_storage().list_publish_logs(50)})
                return
            if path == "/api/publish/config":
                self._json(_publish_config_view())
                return
            m = re.match(r"^/api/tasks/([a-f0-9]{12})/log$", path)
            if m:
                self._sse_log(m.group(1))
                return
            self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body()
        try:
            if path == "/api/setup/test-storage":
                self._json(_test_storage(body))
                return
            if path == "/api/setup/test-llm":
                self._json(_test_llm(body))
                return
            if path == "/api/setup":
                self._json(_save_setup(body))
                return
            if path == "/api/pipeline/run":
                task_id = _start_task(_pipeline_args(body))
                self._json({"ok": True, "task_id": task_id})
                return
            if path == "/api/pipeline/stop":
                with _tasks_lock:
                    task = None
                    for t in _tasks.values():
                        if t["status"] == "running":
                            task = t
                            break
                if not task:
                    self._json({"ok": False, "error": "没有运行中的任务"})
                    return
                self._json({"ok": _stop_task(task["id"]), "task_id": task["id"]})
                return
            m = re.match(r"^/api/events/(evt_[A-Za-z0-9_]+)/rollback$", path)
            if m:
                ok = _get_storage().rollback_articles(m.group(1), _to_int(body.get("version"), 0))
                self._json({"ok": ok})
                return
            m = re.match(r"^/api/events/(evt_[A-Za-z0-9_]+)/generate$", path)
            if m:
                task_id = _start_task(["generate", "--event", m.group(1)])
                self._json({"ok": True, "task_id": task_id})
                return
            if path == "/api/review":
                self._json({"ok": _get_storage().set_article_review(
                    str(body.get("event_id", "")), _to_int(body.get("idx"), 0),
                    str(body.get("status", "pending")), str(body.get("note", "")))})
                return
            if path == "/api/publish":
                self._json(_publish_one(str(body.get("event_id", "")),
                                        _to_int(body.get("idx"), 0),
                                        bool(body.get("dry_run"))))
                return
            if path == "/api/publish/batch":
                self._json(_publish_batch(body.get("items") or [], bool(body.get("dry_run"))))
                return
            if path == "/api/publish/config":
                self._json(_publish_config_save(body))
                return
            self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _sse_log(self, task_id: str):
        with _tasks_lock:
            task = _tasks.get(task_id)
        if not task:
            self._json({"ok": False, "error": "task not found"}, 404)
            return
        q = task["log"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def _send(payload: str):
            try:
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                return True
            except Exception:
                return False

        _send(json.dumps({"type": "meta", "task": _task_summary(task)}, ensure_ascii=False))
        while True:
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                with _tasks_lock:
                    running = task["status"] == "running"
                if running:
                    continue
                break
            if line is None:
                break
            if not _send(json.dumps({"type": "line", "line": line}, ensure_ascii=False)):
                break
        _send(json.dumps({"type": "close", "task": _task_summary(task)}, ensure_ascii=False))


def main(host: str = "127.0.0.1", port: int = 8765, no_browser: bool = False) -> int:
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print("data-to-article 总控面板")
    print(f"  地址: {url}")
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())