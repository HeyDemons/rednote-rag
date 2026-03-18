#!/usr/bin/env python3
"""
Quick retrieval diagnostics for rednote-rag.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.rag import RAGService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect RAG retrieval hits for a query.")
    parser.add_argument("query", help="Search query text")
    parser.add_argument("--k", type=int, default=8, help="Top-k chunk hits to retrieve")
    parser.add_argument("--note-id", action="append", default=None, dest="note_ids", help="Limit to one or more note_id")
    parser.add_argument("--source-type", choices=["likes", "favorites"], default=None, help="Limit to one source_type")
    parser.add_argument("--grouped", action="store_true", help="Print note-level grouped summary after raw hits")
    return parser


def print_hits(hits: list[dict]) -> None:
    print(f"HIT_COUNT: {len(hits)}")
    for idx, hit in enumerate(hits, start=1):
        print(f"[{idx}] score={hit['score']:.4f} note_id={hit['note_id']} chunk={hit['chunk_index']}")
        print(f"    title={hit['title']}")
        print(f"    source_type={hit['source_type']} content_source={hit['content_source']}")
        print(f"    author={hit['author_name']}")
        print(f"    note_url={hit['note_url']}")
        print(f"    snippet={hit['snippet'][:220].replace(chr(10), ' | ')}")


def print_grouped_summary(hits: list[dict]) -> None:
    grouped: dict[str, dict] = defaultdict(lambda: {"max_score": 0.0, "title": "", "source_type": "", "content_source": set(), "chunks": 0})
    for hit in hits:
        entry = grouped[hit["note_id"]]
        entry["max_score"] = max(entry["max_score"], float(hit["score"]))
        entry["title"] = hit["title"]
        entry["source_type"] = hit["source_type"]
        entry["content_source"].add(hit["content_source"])
        entry["chunks"] += 1

    print("\nGROUPED_BY_NOTE:")
    ordered = sorted(grouped.items(), key=lambda item: item[1]["max_score"], reverse=True)
    for idx, (note_id, entry) in enumerate(ordered, start=1):
        sources = ",".join(sorted(source for source in entry["content_source"] if source))
        print(
            f"[{idx}] note_id={note_id} score={entry['max_score']:.4f} "
            f"chunks={entry['chunks']} source_type={entry['source_type']} content_source={sources}"
        )
        print(f"    title={entry['title']}")


def main() -> None:
    args = build_parser().parse_args()
    rag = RAGService()
    hits = rag.search(
        args.query,
        k=args.k,
        note_ids=args.note_ids,
        source_type=args.source_type,
    )

    print(f"QUERY: {args.query}")
    if args.note_ids:
        print(f"NOTE_IDS: {','.join(args.note_ids)}")
    if args.source_type:
        print(f"SOURCE_TYPE: {args.source_type}")
    print_hits(hits)
    if args.grouped:
        print_grouped_summary(hits)


if __name__ == "__main__":
    main()
