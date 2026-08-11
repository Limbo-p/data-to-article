"""发布后端（可插拔）：backend=none（仅标记已发布）| http（自定义 HTTP 发布，格式参照本地 publish.yaml）。

config 的 publish 段：
  publish:
    backend: none | http
    api:
      url: ""
      method: POST
      headers: {CLIENT, APPID, NONCE, CURTIME, OPENKEY, PLATFORM, ...}
      defaults: {author, categoryId, channel, ...}   # 与本地 publish.yaml defaults 同结构
真实 url/headers/默认字段由使用者在自己的 config/config.yaml 填写（不进仓库）。
"""

from __future__ import annotations


def publish_article(config: dict, article: dict, event: dict = None,
                    dry_run: bool = False) -> dict:
    """发布单篇文章；dry_run=True 只返回预览，不真正发送。"""
    pcfg = config.get("publish") or {}
    backend = str(pcfg.get("backend") or "none")
    if backend == "http":
        return _publish_http(config, article, event, dry_run=dry_run)
    return {"ok": True, "backend": "none", "dry_run": dry_run,
            "message": "backend=none：仅标记已发布（未调用外部接口）"}


def _publish_http(config: dict, article: dict, event: dict = None,
                  dry_run: bool = False) -> dict:
    pcfg = config.get("publish") or {}
    api = pcfg.get("api") or {}
    url = str(api.get("url") or "").strip()
    if not url:
        return {"ok": False, "backend": "http",
                "error": "publish.api.url 未配置（请到「审核发布-发布设置」填写）"}
    headers = {str(k): str(v) for k, v in (api.get("headers") or {}).items()
               if v is not None}
    body = dict(api.get("defaults") or {})
    for k, v in (article or {}).items():
        if v is None:
            continue
        body[k] = v
    if event:
        body.setdefault("event_id", event.get("event_id", ""))
        body.setdefault("event_title", event.get("event_title", ""))
    if dry_run:
        return {"ok": True, "backend": "http", "dry_run": True,
                "url": url, "headers": headers, "body": body,
                "message": "dry-run：未真正发送"}
    try:
        import requests
        resp = requests.post(url, json=body, headers=headers, timeout=30)
        return {"ok": resp.ok, "backend": "http", "status_code": resp.status_code,
                "text": resp.text[:500], "url": url, "body": body}
    except Exception as e:
        return {"ok": False, "backend": "http",
                "error": f"{type(e).__name__}: {e}", "url": url, "body": body}
