"""dta CLI：ingest / run 子命令（P0 骨架；P1 接入 wash/classify/generate）。"""

from __future__ import annotations

import argparse
import sys

from data_to_article.ingest import get_ingest
from data_to_article.llm import create_llm_client
from data_to_article.settings import load_config
from data_to_article.storage import get_storage


def _cmd_ingest(args) -> int:
    config = load_config(args.config)
    source = get_ingest(config, args.format, path=args.file, collection=args.source, limit=args.limit)
    docs = source.read_normalized(limit=args.limit)
    storage = get_storage(config)
    n = storage.save_raw_articles(docs)
    backend = config.get("storage", {}).get("backend", "?")
    print(f"ingest: 导入 {n} 条原始文章 -> storage={backend}")
    return 0


def _cmd_run(args) -> int:
    config = load_config(args.config)
    storage = get_storage(config)
    llm = create_llm_client(config)
    print("dta run (P0 骨架)")
    print(f"  storage : {type(storage).__name__}")
    print(f"  llm     : {type(llm).__name__} (provider={config.get('llm', {}).get('provider', '?')})")
    stages = config.get("pipeline", {}).get("stages", {})
    for name in ("wash", "classify", "generate"):
        enabled = bool((stages.get(name) or {}).get("enabled", True))
        print(f"  stage {name:9s}: {'enabled' if enabled else 'disabled'}  (P1 接入)")
        if enabled:
            storage.record_run(name, "pending", {"dry_run": args.dry_run}, "")
    print("P0 骨架完成：wash/classify/generate 将在 P1 平移接入。")
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

    p_run = sub.add_parser("run", help="运行流水线")
    p_run.add_argument("--config", default="")
    p_run.add_argument("--only", default="")
    p_run.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "run":
        return _cmd_run(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
