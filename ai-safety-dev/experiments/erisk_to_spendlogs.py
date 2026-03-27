"""Convert eRisk T2 dataset to SpendLogs format for behavioral pipeline testing.

Each eRisk user has Reddit submissions and comments over time.
We convert each target user's writings into simulated LLM chat sessions:
  - User's Reddit post -> {"role": "user", "content": "..."}
  - Synthetic AI response -> {"role": "assistant", "content": "..."}

This creates SpendLogs rows that the behavioral aggregator can process
to test risk zone detection on real depression-labeled data.

Usage:
    # Preview what would be generated (dry run)
    py experiments/erisk_to_spendlogs.py --dry-run --limit 5

    # Insert into database
    py experiments/erisk_to_spendlogs.py

    # Process specific users
    py experiments/erisk_to_spendlogs.py --users subject_01ZzrIT subject_05DR7kW
"""

import argparse
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DATASET_DIR = Path(r"D:\PSU\диплом\datasets\erisk")
ERISK_USER_PREFIX = "erisk_"


def load_labels(dataset_dir: Path) -> dict[str, int]:
    """Load ground truth labels: 0=control, 1=positive (depression)."""
    labels_path = dataset_dir / "shuffled_ground_truth_labels.txt"
    labels = {}
    with labels_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            user_id, label = line.split()
            labels[user_id] = int(label)
    return labels


def load_user_data(user_id: str, dataset_dir: Path) -> list[dict]:
    """Load a single user's eRisk JSON file."""
    file_path = dataset_dir / "all_combined" / f"{user_id}.json"
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_erisk_datetime(date_str: str) -> datetime:
    """Parse eRisk date format '2024-09-06 16:36:22 UTC' to datetime."""
    clean = date_str.replace(" UTC", "").strip()
    return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def extract_target_writings(threads: list[dict], user_id: str) -> list[dict]:
    """Extract all writings by the target user, sorted chronologically.

    Returns list of {"text": str, "timestamp": datetime, "type": "submission"|"comment"}.
    """
    writings = []

    for thread in threads:
        submission = thread.get("submission", {})
        if submission.get("target") and submission.get("user_id") == user_id:
            text_parts = []
            if submission.get("title"):
                text_parts.append(submission["title"])
            if submission.get("body"):
                text_parts.append(submission["body"])
            if text_parts:
                writings.append({
                    "text": "\n\n".join(text_parts),
                    "timestamp": parse_erisk_datetime(submission["created_utc"]),
                    "type": "submission",
                })

        for comment in thread.get("comments", []):
            if comment.get("target") and comment.get("user_id") == user_id:
                if comment.get("body"):
                    writings.append({
                        "text": comment["body"],
                        "timestamp": parse_erisk_datetime(comment["created_utc"]),
                        "type": "comment",
                    })

    writings.sort(key=lambda w: w["timestamp"])
    return writings


def group_by_day(writings: list[dict]) -> dict[str, list[dict]]:
    """Group writings by calendar date (UTC)."""
    days: dict[str, list[dict]] = {}
    for w in writings:
        day_key = w["timestamp"].strftime("%Y-%m-%d")
        days.setdefault(day_key, []).append(w)
    return days


def writings_to_spendlogs_rows(
    user_id: str,
    writings: list[dict],
) -> list[dict]:
    """Convert a user's writings into SpendLogs-compatible row dicts.

    Each writing becomes one SpendLogs row with:
    - messages: [{"role": "user", "content": text}]
    - end_user: "erisk_{user_id}"
    - startTime/endTime: from the writing timestamp
    """
    rows = []
    for w in writings:
        request_id = str(uuid.uuid4())
        messages = [
            {"role": "user", "content": w["text"]},
            {"role": "assistant", "content": "(synthetic response placeholder)"},
        ]
        rows.append({
            "request_id": request_id,
            "call_type": "acompletion",
            "api_key": "erisk-synthetic",
            "spend": 0.0,
            "total_tokens": len(w["text"].split()),
            "prompt_tokens": len(w["text"].split()),
            "completion_tokens": 0,
            "startTime": w["timestamp"],
            "endTime": w["timestamp"],
            "model": "erisk-synthetic",
            "user": "",
            "end_user": f"{ERISK_USER_PREFIX}{user_id}",
            "messages": messages,
            "response": {},
            "metadata_json": {
                "source": "erisk_t2",
                "original_type": w["type"],
            },
            "session_id": f"erisk_{user_id}_{w['timestamp'].strftime('%Y%m%d')}",
        })
    return rows


async def insert_rows_to_db(rows: list[dict]) -> int:
    """Insert SpendLogs rows into the database."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

    from database import Session
    from database.models import LiteLLM_SpendLogs

    inserted = 0
    async with Session() as session:
        async with session.begin():
            for row_data in rows:
                row = LiteLLM_SpendLogs(**row_data)
                session.add(row)
                inserted += 1
    return inserted


def print_summary(
    user_id: str,
    label: Optional[int],
    writings: list[dict],
    rows: list[dict],
):
    """Print a summary of what was/would be generated."""
    days = group_by_day(writings)
    label_str = {0: "control", 1: "depression", None: "unknown"}[label]
    print(f"\n{'='*60}")
    print(f"User: {user_id} | Label: {label_str} | Writings: {len(writings)} | Days: {len(days)} | SpendLogs rows: {len(rows)}")
    print(f"Date range: {writings[0]['timestamp'].date()} -> {writings[-1]['timestamp'].date()}" if writings else "No writings")
    print(f"{'='*60}")

    # Show first 3 days
    for i, (day, day_writings) in enumerate(sorted(days.items())[:3]):
        msgs_preview = [w["text"][:80].replace("\n", " ") for w in day_writings[:2]]
        print(f"  {day}: {len(day_writings)} writings")
        for preview in msgs_preview:
            print(f"    -> {preview}...")
    if len(days) > 3:
        print(f"  ... and {len(days) - 3} more days")


async def main():
    parser = argparse.ArgumentParser(description="Convert eRisk T2 dataset to SpendLogs")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of users to process")
    parser.add_argument("--users", nargs="+", help="Specific user IDs to process")
    parser.add_argument("--positive-only", action="store_true", help="Only process depression-positive users")
    parser.add_argument("--control-only", action="store_true", help="Only process control users")
    args = parser.parse_args()

    labels = load_labels(args.dataset_dir)
    all_combined = args.dataset_dir / "all_combined"

    # Determine which users to process
    if args.users:
        user_ids = args.users
    else:
        user_ids = sorted([p.stem for p in all_combined.glob("subject_*.json")])

    if args.positive_only:
        user_ids = [u for u in user_ids if labels.get(u) == 1]
    elif args.control_only:
        user_ids = [u for u in user_ids if labels.get(u) == 0]

    if args.limit:
        user_ids = user_ids[:args.limit]

    logger.info("Processing %d users (dry_run=%s)", len(user_ids), args.dry_run)

    total_rows = 0
    total_writings = 0

    for user_id in user_ids:
        try:
            threads = load_user_data(user_id, args.dataset_dir)
            writings = extract_target_writings(threads, user_id)

            if not writings:
                logger.debug("User %s has no target writings, skipping", user_id)
                continue

            rows = writings_to_spendlogs_rows(user_id, writings)

            if args.dry_run:
                print_summary(user_id, labels.get(user_id), writings, rows)
            else:
                inserted = await insert_rows_to_db(rows)
                logger.info("User %s: inserted %d rows", user_id, inserted)

            total_rows += len(rows)
            total_writings += len(writings)

        except Exception:
            logger.exception("Failed to process user %s", user_id)

    print(f"\nTotal: {len(user_ids)} users, {total_writings} writings, {total_rows} SpendLogs rows")

    if args.dry_run:
        print("\n(Dry run — nothing was inserted. Remove --dry-run to insert into database.)")
    else:
        # Also save labels mapping for later correlation
        labels_out = {
            f"{ERISK_USER_PREFIX}{uid}": labels.get(uid)
            for uid in user_ids
            if labels.get(uid) is not None
        }
        labels_path = Path(__file__).parent / "erisk_labels.json"
        with labels_path.open("w") as f:
            json.dump(labels_out, f, indent=2)
        logger.info("Labels saved to %s", labels_path)


if __name__ == "__main__":
    asyncio.run(main())
