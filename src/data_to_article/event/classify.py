"""事件归类引擎：把清洗后文章归入已有事件或新建事件。

平移自旧项目 event.event_builder.EventBuilder，存储/LLM 全部走接口。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from data_to_article.event.llm_classifier import LLMClassifier


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClassifyEngine:
    def __init__(self, config: dict, storage, llm):
        self.config = config
        self.storage = storage
        self.llm = llm
        self.dry_run = False

        cls_cfg = config.get("classification", {}) or {}
        dd = config.get("dedup", {}) or {}
        self.dedup_enabled = bool(dd.get("enabled", True))
        rt = cls_cfg.get("router", {}) or {}
        self.batch_size = int(rt.get("batch_size", 12))
        self.candidate_days = int(rt.get("candidate_days", 30))
        self.candidate_limit = int(rt.get("candidate_limit", 100))
        self.escalation = bool(rt.get("low_confidence_escalation", True))

    # ---------- 主流程 ----------

    def process_batch(self, hours: int = 168, limit: int = 0, dry_run: bool = False) -> dict:
        self.dry_run = dry_run
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat(timespec="seconds")

        pending = self.storage.fetch_cleaned(since=cutoff_str, limit=limit)
        for art in pending:
            art.setdefault("_etl_collection", art.get("source", ""))
        print(f"[classify] 待归类 {len(pending)} 篇（窗口 {hours}h）")

        created = assigned = skipped = 0

        claimed = []
        for art in pending:
            fp = art.get("content_fp", "")
            if fp and self.dedup_enabled:
                ok, mapped_eid = self._dedup_claim(fp)
                if not ok:
                    if mapped_eid and self.storage.get_event(mapped_eid):
                        print(f"    - skipped, already in event {mapped_eid}")
                        skipped += 1
                        continue
                    self._dedup_release(fp)
                    ok, _ = self._dedup_claim(fp)
                    if not ok:
                        print(f"    ! could not claim content_fp: {fp}")
                        skipped += 1
                        continue
            claimed.append(art)

        if not claimed:
            print(f"[classify] 无待处理文章")
            return {"created": 0, "assigned": 0, "skipped": skipped}

        candidates = self._load_candidates()
        cand_ids = {e.get("event_id", "") for e in candidates}
        norm_index = {}
        for evt in candidates:
            nt = self._normalize_title(evt.get("event_title", ""))
            if nt:
                norm_index.setdefault(nt, evt.get("event_id", ""))

        # L0 直并：归一化标题完全相等，不调 LLM
        remaining = []
        for art in claimed:
            eid = norm_index.get(self._normalize_title(art.get("title", "")), "")
            if eid:
                r = self._merge_article(eid, art, True, "direct merge: normalized title match")
                assigned += 1 if r == "assigned" else 0
                skipped += 0 if r == "assigned" else 1
            else:
                remaining.append(art)

        # LLM 批量标题路由
        if remaining and self.llm is not None:
            batches = [remaining[i:i + self.batch_size] for i in range(0, len(remaining), self.batch_size)]
            for bi, batch in enumerate(batches, 1):
                print(f"  routing batch {bi}/{len(batches)}: {len(batch)} articles, {len(candidates)} candidates")
                results = self._route_batch(batch, candidates) or [None] * len(batch)
                order = sorted(range(len(batch)), key=lambda i: batch[i].get("pub_time", "") or "")
                new_groups = {}
                for i in order:
                    art, res = batch[i], results[i]
                    try:
                        outcome = self._apply_route(art, res, candidates, cand_ids, norm_index, new_groups, i)
                    except Exception as e:
                        print(f"    ! assign failed: {e}")
                        self._skip_article(art, "failed", str(e))
                        outcome = "skipped"
                    if outcome == "new":
                        created += 1
                    elif outcome == "assigned":
                        assigned += 1
                    else:
                        skipped += 1
        elif remaining:
            for art in remaining:
                self._skip_article(art, "skipped_llm_unavailable", "llm disabled or unavailable")
                skipped += 1

        print(f"[classify] 完成: 新建 {created} 事件, 归入已有 {assigned} 篇, 跳过 {skipped} 篇")
        return {"created": created, "assigned": assigned, "skipped": skipped}

    # ---------- 候选与路由 ----------

    def _load_candidates(self) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.candidate_days)).isoformat()
        out = []
        for evt in self.storage.query_events(limit=self.candidate_limit):
            if evt.get("status", "active") != "active":
                continue
            if str(evt.get("updated_at", "")) < cutoff:
                continue
            out.append(evt)
        return out

    def _route_batch(self, batch, candidates):
        if self.llm is None:
            return None
        for _ in range(2):
            results = self._map_route_results(self.llm.route_articles(batch, candidates), batch)
            if results is not None:
                return results
        if len(batch) <= 1:
            return [None]
        print(f"    ! batch routing failed, fallback to per-article ({len(batch)})")
        out = []
        for art in batch:
            r = self._map_route_results(self.llm.route_articles([art], candidates), [art])
            out.append(r[0] if r else None)
        return out

    @staticmethod
    def _map_route_results(raw, batch):
        if not isinstance(raw, list):
            return None
        by_no = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                no = int(item.get("no", 0))
            except (TypeError, ValueError):
                continue
            by_no[no] = item
        results = [by_no.get(i) for i in range(1, len(batch) + 1)]
        if all(r is None for r in results):
            return None
        return results

    def _apply_route(self, art, res, candidates, cand_ids, norm_index, new_groups, idx):
        if res is None:
            self._skip_article(art, "skipped_llm_failed", "routing failed")
            return "skipped"
        eid = str(res.get("event_id", "") or "").strip()
        reason = str(res.get("reason", "") or "").strip()
        conf = str(res.get("confidence", "high") or "high").strip().lower()
        grp = str(res.get("new_group", "") or "").strip()
        route = {"confidence": conf, "new_group": grp}
        if eid and eid not in cand_ids:
            self._skip_article(art, "skipped_llm_failed", f"invalid event_id: {eid}")
            return "skipped"
        if eid and conf == "low" and self.escalation and self.llm is not None:
            evt = next((e for e in candidates if e.get("event_id") == eid), None)
            m, mreason = self._llm_match_article(self._make_ref(art), evt or {}, art.get("content", ""))
            route["escalated"] = True
            if m is True:
                reason = (reason + " | escalated: " + mreason).strip(" |")
            elif m is False:
                eid, grp = "", f"__solo_{idx}"
                reason = "escalated: rejected -> new | " + mreason
            else:
                self._skip_article(art, "skipped_llm_failed", "escalation failed: " + mreason)
                return "skipped"
        if eid:
            return self._merge_article(eid, art, True, reason or "llm route", route=route)
        grp = grp or f"__solo_{idx}"
        if grp in new_groups:
            return self._merge_article(new_groups[grp], art, True, f"same new_group: {grp}", route=route)
        eid = self._create_for_article(art, reason or "new event", route=route)
        if not eid:
            return "skipped"
        new_groups[grp] = eid
        cand_ids.add(eid)
        evt_doc = self.storage.get_event(eid)
        if evt_doc:
            candidates.append(evt_doc)
            nt = self._normalize_title(evt_doc.get("event_title", ""))
            if nt:
                norm_index.setdefault(nt, eid)
        return "new"

    def _llm_match_article(self, ref, evt, article_content=""):
        try:
            return self.llm.match_article(
                article_title=ref.get("title", ""),
                article_overview=ref.get("overview", ""),
                article_content=article_content,
                event_title=evt.get("event_title", ""),
                event_overview=evt.get("overview", ""),
            )
        except Exception as e:
            print(f"    ! llm match failed: {e}")
            return None, f"llm call failed: {e}"

    # ---------- 事件写入 ----------

    def _merge_article(self, event_id, art, llm_match, llm_reason, route=None):
        fp = art.get("content_fp", "")
        ref = self._make_ref(art)
        status = self._append_article(event_id, ref, fp, ref["etl_collection"], ref["assigned_at"])
        if status == "already":
            if fp:
                self._dedup_mark(fp, event_id)
            print(f"    - already member of {event_id}")
            return "skipped"
        if status == "missing":
            self._skip_article(art, "failed", f"append failed: event {event_id} missing")
            return "skipped"
        if fp:
            self._dedup_mark(fp, event_id)
        self._refresh_event_overview(event_id)
        print(f"    -> merged into {event_id}: {ref['title'][:40]}")
        return "assigned"

    def _create_for_article(self, art, llm_reason, route=None):
        ref = self._make_ref(art)
        eid = self._create_event(ref, ref["content_fp"], ref["etl_collection"], ref["assigned_at"],
                                 article_content=art.get("content", ""))
        if not eid:
            self._skip_article(art, "failed", "create event failed")
            return ""
        if ref["content_fp"]:
            self._dedup_mark(ref["content_fp"], eid)
        print(f"    -> new event {eid}: {ref['title'][:40]}")
        return eid

    def _create_event(self, ref, content_fp, etl_collection, now, article_content=""):
        eid = "evt_" + uuid.uuid4().hex
        evt = {
            "event_id": eid,
            "event_title": ref["title"][:50],
            "category": "",
            "overview": "",
            "keywords": [],
            "articles": [ref],
            "article_count": 1,
            "content_fps": [content_fp] if content_fp else [],
            "etl_collections": [etl_collection] if etl_collection else [],
            "first_pub_time": ref.get("pub_time", ""),
            "last_pub_time": ref.get("pub_time", ""),
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        if self.llm is not None and not self.dry_run:
            try:
                llm_item = dict(ref)
                if article_content:
                    llm_item["content"] = article_content
                data = self.llm.summarize_event([llm_item])
                if data.get("event_title"):
                    evt["event_title"] = data["event_title"]
                if data.get("overview"):
                    evt["overview"] = data["overview"]
                if data.get("category"):
                    evt["category"] = data["category"]
                kws = [str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()]
                if kws:
                    evt["keywords"] = kws[:10]
            except Exception as e:
                print(f"    ! event overview generate failed: {e}")
        if self.dry_run:
            print(f"    [dry] new event {eid}: {evt['event_title'][:40]}")
            return eid
        try:
            self.storage.save_event(evt)
            return eid
        except Exception as e:
            print(f"    ! create event failed: {e}")
            return ""

    def _append_article(self, event_id, ref, content_fp, etl_collection, now):
        if self.dry_run:
            print(f"    [dry] append -> {event_id}: {ref.get('title', '')[:40]}")
            return "ok"
        evt = self.storage.get_event(event_id)
        if evt is None:
            return "missing"
        fps = evt.get("content_fps") or []
        if content_fp and content_fp in fps:
            return "already"
        evt.setdefault("articles", []).append(ref)
        evt["article_count"] = int(evt.get("article_count", 0)) + 1
        if content_fp:
            fps.append(content_fp)
            evt["content_fps"] = fps
        if etl_collection:
            ec = evt.get("etl_collections") or []
            if etl_collection not in ec:
                ec.append(etl_collection)
            evt["etl_collections"] = ec
        if ref.get("pub_time"):
            first = evt.get("first_pub_time") or ref["pub_time"]
            last = evt.get("last_pub_time") or ref["pub_time"]
            evt["first_pub_time"] = min(first, ref["pub_time"])
            evt["last_pub_time"] = max(last, ref["pub_time"])
        evt["updated_at"] = now
        self.storage.update_event(event_id, evt)
        return "ok"

    def _refresh_event_overview(self, event_id, force_title=False):
        if self.llm is None or self.dry_run:
            return
        evt = self.storage.get_event(event_id)
        if not evt:
            return
        if int(evt.get("article_count", 0) or 0) in (5, 10):
            force_title = True
        items = self._load_articles(evt)
        if not items:
            items = evt.get("articles", []) or []
        items.sort(key=lambda a: (a.get("pub_time", "") or ""))
        data = self.llm.summarize_event(items)
        update = {}
        if data.get("overview"):
            update["overview"] = data["overview"]
        if data.get("category"):
            update["category"] = data["category"]
        if data.get("event_title") and (force_title or not evt.get("event_title")):
            update["event_title"] = data["event_title"]
        if update:
            update["updated_at"] = _now()
            self.storage.update_event(event_id, update)

    def _load_articles(self, event):
        out = []
        for ref in (event.get("articles") or []):
            fp = ref.get("content_fp", "")
            if not fp:
                continue
            a = self.storage.get_cleaned_by_fp(fp)
            if a:
                out.append(a)
        return out

    # ---------- 辅助 ----------

    def _make_ref(self, art):
        return {
            "content_fp": art.get("content_fp", ""),
            "title": art.get("title", ""),
            "source": art.get("source", ""),
            "pub_time": art.get("pub_time", ""),
            "url": art.get("url", ""),
            "etl_collection": art.get("_etl_collection", ""),
            "assigned_at": _now(),
        }

    @staticmethod
    def _normalize_title(title):
        return re.sub(r"[\W_]+", "", title or "").strip().lower()

    def _skip_article(self, art, result, reason):
        fp = art.get("content_fp", "")
        if fp:
            self._dedup_release(fp)
        print(f"    - skipped ({result}): {art.get('title', '')[:40]} ({reason})")

    def _dedup_claim(self, content_fp):
        if self.dry_run:
            return True, ""
        try:
            return self.storage.claim_content_fp(content_fp)
        except Exception as e:
            print(f"    ! dedup claim failed: {e}")
            return False, ""

    def _dedup_mark(self, content_fp, event_id):
        if self.dry_run:
            return
        try:
            self.storage.mark_content_fp(content_fp, event_id)
        except Exception as e:
            print(f"    ! dedup mark failed: {e}")

    def _dedup_release(self, content_fp):
        if self.dry_run:
            return
        try:
            self.storage.release_content_fp(content_fp)
        except Exception as e:
            print(f"    ! dedup release failed: {e}")
