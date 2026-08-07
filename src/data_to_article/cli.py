"""dta CLI：ingest / wash / classify / generate / run。"""

from __future__ import annotations

import argparse
import sys

from data_to_article.event.classify import ClassifyEngine
from data_to_article.event.llm_classifier import LLMClassifier
from data_to_article.generate.generator import GenerateEngine
from data_to_article.ingest import get_ingest
from data_to_article.llm import create_llm_client
from data_to_article.settings import load_config
from data_to_article.storage import get_storage
from data_to_article.washing.run import run_wash


def _cmd_ingest(args) -> int:
    config = load_config(args.config)
    source = get_ingest(config, args.format, path=args.file, collection=args.source, limit=args.limit)
    docs = source.read_normalized(limit=args.limit)
    storage = get_storage(config)
    n = storage.save_raw_articles(docs)
    backend = config.get("storage", {}).get("backend", "?")
    print(f"ingest: 导入 {n} 条原始文章 -> storage={backend}")
    return 0


def _cmd_wash(args) -> int:
    config = load_config(args.config)
    storage = get_storage(config)
    stats = run_wash(config, storage, hours=args.hours, limit=args.limit, dry_run=args.dry_run)
    storage.record_run("wash", "dry_run" if args.dry_run else "ok", stats)
    return 0


def _cmd_classify(args) -> int:
    config = load_config(args.config)
    storage = get_storage(config)
    llm = LLMClassifier(config)
    engine = ClassifyEngine(config, storage, llm)
    stats = engine.process_batch(hours=args.hours, limit=args.limit, dry_run=args.dry_run)
    storage.record_run("classify", "dry_run" if args.dry_run else "ok", stats)
    return 0


def _cmd_generate(args) -> int:
    config = load_config(args.config)
    storage = get_storage(config)
    llm = create_llm_client(config)
    engine = GenerateEngine(config, storage, llm)
    stats = engine.process_batch(hours=args.hours, limit=args.limit, dry_run=args.dry_run)
    storage.record_run("generate", "dry_run" if args.dry_run else "ok", stats)
    return 0


def _cmd_run(args) -> int:
    config = load_config(args.config)
    storage = get_storage(config)
    stages_cfg = config.get("pipeline", {}).get("stages", {})
    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else []
    order = ["wash", "classify", "generate"]
    for name in order:
        if only and name not in only:
            continue
        if not bool((stages_cfg.get(name) or {}).get("enabled", True)):
            print(f"[run] stage {name}: disabled, skip")
            continue
        print(f"\n===== {name} =====")
        try:
            if name == "wash":
                stats = run_wash(config, storage, hours=args.hours, limit=args.limit, dry_run=args.dry_run)
            elif name == "classify":
                llm = LLMClassifier(config)
                engine = ClassifyEngine(config, storage, llm)
                stats = engine.process_batch(hours=args.hours, limit=args.limit, dry_run=args.dry_run)
            else:
                llm = create_llm_client(config)
                engine = GenerateEngine(config, storage, llm)
                stats = engine.process_batch(hours=args.hours, limit=args.limit, dry_run=args.dry_run)
            status = "dry_run" if args.dry_run else "ok"
            storage.record_run(name, status, {"hours": args.hours, "limit": args.limit, **stats})
        except Exception as e:
            print(f"[run] stage {name} failed: {e}")
            storage.record_run(name, "failed", {"hours": args.hours}, str(e))
            if config.get("pipeline", {}).get("stop_on_error", True):
                print("[run] stop_on_error=True，停止后续阶段")
                return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dta", description="data-to-article：清洗 -> 归类 -> 二创 流水线")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="导入原始数据（jsonl/csv/mongo）")
    p_ingest.add_argument("--config", default="")
    p_ingest.add_argument("--file", default="")
    p_ingest.add_argument("--format", choices=["jsonl", "csv", "mongo"], default="jsonl")
    p_ingest.add_argument("--source", default="", help="mongo 集合名")
    p_ingest.add_argument("--limit", type=int, default=0)

    p_wash = sub.add_parser("wash", help="清洗阶段")
    p_wash.add_argument("--config", default="")
    p_wash.add_argument("--hours", type=int, default=24)
    p_wash.add_argument("--limit", type=int, default=0)
    p_wash.add_argument("--dry-run", action="store_true")

    p_cls = sub.add_parser("classify", help="归类阶段")
    p_cls.add_argument("--config", default="")
    p_cls.add_argument("--hours", type=int, default=168)
    p_cls.add_argument("--limit", type=int, default=0)
    p_cls.add_argument("--dry-run", action="store_true")

    p_gen = sub.add_parser("generate", help="二创生成阶段")
    p_gen.add_argument("--config", default="")
    p_gen.add_argument("--hours", type=int, default=168)
    p_gen.add_argument("--limit", type=int, default=0)
    p_gen.add_argument("--dry-run", action="store_true")

    p_run = sub.add_parser("run", help="运行流水线（wash -> classify -> generate）")
    p_run.add_argument("--config", default="")
    p_run.add_argument("--only", default="")
    p_run.add_argument("--hours", type=int, default=24)
    p_run.add_argument("--limit", type=int, default=0)
    p_run.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    handlers = {
        "ingest": _cmd_ingest,
        "wash": _cmd_wash,
        "classify": _cmd_classify,
        "generate": _cmd_generate,
        "run": _cmd_run,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())