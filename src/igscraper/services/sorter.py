# sorter.py
from __future__ import annotations
import json, time, logging, tempfile
from pathlib import Path
from typing import List, Sequence, Dict, Any, Optional

try:
    import json5
    _HAS_JSON5 = True
except Exception:
    _HAS_JSON5 = False

logger_default = logging.getLogger(__name__)


def _safe_load(text: str, use_json5: Optional[bool]):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if use_json5 is None:
            use_json5 = _HAS_JSON5
        if use_json5 and _HAS_JSON5:
            return json5.loads(text)
        raise


def parse_multiline_jsonl(text: str, use_json5: Optional[bool] = None) -> List[dict]:
    objs, buf = [], ""
    depth = 0
    in_string = False
    escape = False

    for ch in text:
        buf += ch
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1

            if depth == 0 and buf.strip():
                try:
                    objs.append(_safe_load(buf, use_json5))
                    buf = ""
                except Exception:
                    buf = ""

    buf = buf.strip()
    if buf:
        try:
            objs.append(_safe_load(buf, use_json5))
        except Exception:
            pass

    return objs


def _atomic_write_lines(path: Path, lines: Sequence[str], encoding="utf-8"):
    tempdir = path.parent
    tempdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding=encoding, delete=False, dir=str(tempdir), suffix=".tmp"
    ) as f:
        for line in lines:
            f.write(line + "\n")
        tmp = Path(f.name)
    tmp.replace(path)


def sort_jsonl_folder(
    root: Path,
    *,
    key="timestamp",
    patterns=None,
    encoding="utf-8",
    use_json5=None,
    logger=None,
    recursive=True,
    dry_run=False,
):
    """
    Sort JSONL files found under `root`, writing `_sorted.jsonl` beside each file.
    No printing; logs only.
    """
    logger = logger or logger_default
    root = Path(root)

    if patterns is None:
        patterns = ["profile_data_*.jsonl", "post_entity_*.jsonl"]

    # discover
    jsonl_files = []
    for pattern in patterns:
        jsonl_files.extend(root.rglob(pattern) if recursive else root.glob(pattern))

    if not jsonl_files:
        logger.warning("No matching JSONL files under %s", root)
        return {
            "total_found": 0,
            "sorted": 0,
            "skipped_up_to_date": 0,
            "no_records": 0,
            "failed": 0,
            "files": [],
            "duration_seconds": 0.0,
        }

    summary = {
        "total_found": len(jsonl_files),
        "sorted": 0,
        "skipped_up_to_date": 0,
        "no_records": 0,
        "failed": 0,
        "files": [],
    }

    start = time.time()

    for path in jsonl_files:
        rec = {"path": str(path), "status": None, "records": 0, "error": None}

        try:
            if path.name.endswith("_sorted.jsonl"):
                rec["status"] = "skipped_already_sorted"
                summary["files"].append(rec)
                continue

            out_path = path.with_name(path.stem + "_sorted.jsonl")

            if out_path.exists() and out_path.stat().st_mtime >= path.stat().st_mtime:
                rec["status"] = "skipped_up_to_date"
                summary["skipped_up_to_date"] += 1
                summary["files"].append(rec)
                logger.info("Skipping (up-to-date): %s", path)
                continue

            text = path.read_text(encoding=encoding, errors="ignore")
            records = parse_multiline_jsonl(text, use_json5=use_json5)

            if not records:
                rec["status"] = "no_records"
                summary["no_records"] += 1
                summary["files"].append(rec)
                logger.warning("No records in %s", path)
                continue

            records.sort(key=lambda d: d.get(key, ""))

            if not dry_run:
                lines = [json.dumps(r, ensure_ascii=False) for r in records]
                _atomic_write_lines(out_path, lines, encoding=encoding)

            rec["status"] = "sorted"
            rec["records"] = len(records)
            summary["sorted"] += 1
            summary["files"].append(rec)
            logger.info("Sorted %s (%d records)", path, len(records))

        except Exception as e:
            rec["status"] = "failed"
            rec["error"] = str(e)
            summary["failed"] += 1
            summary["files"].append(rec)
            logger.exception("Failed to process %s", path)

    summary["duration_seconds"] = time.time() - start
    logger.info(
        "Summary: total=%d sorted=%d skipped=%d no_records=%d failed=%d duration=%.2fs",
        summary["total_found"],
        summary["sorted"],
        summary["skipped_up_to_date"],
        summary["no_records"],
        summary["failed"],
        summary["duration_seconds"],
    )

    return summary


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Sort Instagram JSONL files.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--key", default="timestamp")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pattern", action="append")
    parser.add_argument("--use-json5", action="store_true")
    parser.add_argument("--no-recursive", dest="recursive", action="store_false")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    sort_jsonl_folder(
        Path(args.root),
        key=args.key,
        patterns=args.pattern,
        recursive=args.recursive,
        use_json5=args.use_json5,
        dry_run=args.dry_run,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# from ig_jsonl_sorter.sorter import sort_jsonl_folder

# logging.basicConfig(level=logging.INFO)

# summary = sort_jsonl_folder(Path("/base/path/from/main/outputs"))
