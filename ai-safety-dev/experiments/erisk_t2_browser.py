from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = (
    Path("/mnt/c/Users/Миша")
    / "Downloads"
    / "t2-early-contextualized-depression-20251107T135209Z-1-001"
    / "t2-early-contextualized-depression"
    / "final-eriskt2-dataset-with-ground-truth"
    / "final-eriskt2-dataset-with-ground-truth"
)


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    label: int | None
    file_path: Path
    file_size_mb: float


def dataset_paths(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> tuple[Path, Path]:
    root = Path(dataset_dir)
    return root / "all_combined", root / "shuffled_ground_truth_labels.txt"


def load_labels(labels_path: str | Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    with Path(labels_path).open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            user_id, label = line.split()
            labels[user_id] = int(label)
    return labels


def list_users(dataset_dir: str | Path = DEFAULT_DATASET_DIR) -> list[UserRecord]:
    subjects_dir, labels_path = dataset_paths(dataset_dir)
    labels = load_labels(labels_path)
    users: list[UserRecord] = []
    for file_path in sorted(subjects_dir.glob("subject_*.json")):
        user_id = file_path.stem
        users.append(
            UserRecord(
                user_id=user_id,
                label=labels.get(user_id),
                file_path=file_path,
                file_size_mb=round(file_path.stat().st_size / (1024 * 1024), 2),
            )
        )
    return users


def load_user_threads(
    user_id: str,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> list[dict[str, Any]]:
    subjects_dir, _ = dataset_paths(dataset_dir)
    file_path = subjects_dir / f"{user_id}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"User file not found: {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _shorten(text: str | None, limit: int = 160) -> str:
    if not text:
        return ""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else f"{clean[: limit - 3]}..."


def summarize_user(
    user_id: str,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> dict[str, Any]:
    threads = load_user_threads(user_id, dataset_dir)
    target_submissions = 0
    target_comments = 0
    context_submissions = 0
    context_comments = 0
    participants: set[str] = set()

    for thread in threads:
        submission = thread["submission"]
        participants.add(submission["user_id"])
        if submission.get("target"):
            target_submissions += 1
        else:
            context_submissions += 1

        for comment in thread.get("comments", []):
            participants.add(comment["user_id"])
            if comment.get("target"):
                target_comments += 1
            else:
                context_comments += 1

    return {
        "user_id": user_id,
        "threads": len(threads),
        "target_submissions": target_submissions,
        "target_comments": target_comments,
        "context_submissions": context_submissions,
        "context_comments": context_comments,
        "participants": len(participants),
    }


def user_activity_table(
    user_id: str,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
    target_only: bool = True,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    threads = load_user_threads(user_id, dataset_dir)
    rows: list[dict[str, Any]] = []

    for thread_index, thread in enumerate(threads):
        submission = thread["submission"]
        if not target_only or submission.get("target"):
            rows.append(
                {
                    "thread_index": thread_index,
                    "kind": "submission",
                    "created_utc": submission.get("created_utc"),
                    "author": submission.get("user_id"),
                    "title": _shorten(submission.get("title")),
                    "body_preview": _shorten(submission.get("body")),
                    "item_id": submission.get("submission_id"),
                }
            )

        for comment_index, comment in enumerate(thread.get("comments", [])):
            if target_only and not comment.get("target"):
                continue
            rows.append(
                {
                    "thread_index": thread_index,
                    "kind": "comment",
                    "created_utc": comment.get("created_utc"),
                    "author": comment.get("user_id"),
                    "title": "",
                    "body_preview": _shorten(comment.get("body")),
                    "item_id": comment.get("comment_id"),
                    "comment_index": comment_index,
                }
            )

    rows.sort(key=lambda row: row.get("created_utc") or "")
    if max_rows is not None:
        return rows[:max_rows]
    return rows


def render_thread(
    user_id: str,
    thread_index: int,
    dataset_dir: str | Path = DEFAULT_DATASET_DIR,
) -> str:
    threads = load_user_threads(user_id, dataset_dir)
    if thread_index < 0 or thread_index >= len(threads):
        raise IndexError(f"thread_index must be between 0 and {len(threads) - 1}")

    thread = threads[thread_index]
    submission = thread["submission"]
    lines = [
        f"THREAD {thread_index}",
        "=" * 80,
        f"Submission: {submission.get('submission_id')} | author={submission.get('user_id')} | target={submission.get('target')}",
        f"Created:    {submission.get('created_utc')}",
        f"Title:      {submission.get('title') or ''}",
        "",
        submission.get("body") or "",
        "",
    ]

    comments = thread.get("comments", [])
    if not comments:
        lines.append("[No comments]")
        return "\n".join(lines)

    lines.append("COMMENTS")
    lines.append("-" * 80)
    for idx, comment in enumerate(comments):
        lines.extend(
            [
                f"[{idx}] {comment.get('comment_id')} | author={comment.get('user_id')} | target={comment.get('target')}",
                f"     Created: {comment.get('created_utc')} | parent={comment.get('parent_id')}",
                comment.get("body") or "",
                "-" * 80,
            ]
        )
    return "\n".join(lines)


def label_name(label: int | None) -> str:
    if label == 1:
        return "positive"
    if label == 0:
        return "control"
    return "unknown"
