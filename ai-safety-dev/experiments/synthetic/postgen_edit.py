"""Post-generation redactor: finds technical-garbage substrings; Python strips them.

The model returns a JSON array of literal substrings to remove. We only delete
substrings that exist verbatim in the input — so the editor can never invent or
paraphrase content. The raw JSONL is never mutated; results go to a parallel
`<stem>.edited.jsonl` where each exchange preserves:

    user_original   # verbatim pre-edit
    user_edited     # after removals (may equal original if redactor returned [])
    edit_action     # "no_change" | "edited" | "dropped"
    edit_removals   # list of substrings actually removed (for audit)

`__DROP__` as the sole element means the whole message is scaffold. Those
exchanges keep user_original, set user_edited="", action="dropped".

Usage:
    python3 experiments/synthetic/postgen_edit.py <input.jsonl> \\
        [--editor-model gemma4:latest] \\
        [--ollama-url http://192.168.87.25:11434] \\
        [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import httpx

EDITOR_VERSION = "e2_redactor"

REDACTOR_PROMPT = """Ты — редактор. Тебе дают одно сообщение из чата. Найди в нём технический мусор.

Верни JSON-массив строк, которые надо удалить. Каждая строка ДОЛЖНА дословно присутствовать в исходном сообщении (копируй символ в символ, включая пробелы и пунктуацию).

Считай мусором ТОЛЬКО такие вещи:
1. Нумерованные списки правил: "1. Заходишь в чат...", "2. Не размечай текст..."
2. Императивы вида "Не используй markdown", "Пиши только свои реплики", "Только русский язык"
3. Ремарки в звёздочках: *вздыхает*, *тихо смеётся*, *голос дрожит*
4. Ремарки в круглых скобках описывающие действия или звуки: (Молчание, пауза), (шёпотом), (скрип двери)
5. Мета-комментарии про ИИ или чат: "Ты так много пишешь", "Первое сообщение будет от пользователя"

НЕ считай мусором:
- Обычные предложения от лица персонажа, даже если они выглядят как описание места/обстоятельств ("Я в общаге, соседи за стеной").
- Диалог, междометия, эмоциональные реплики.
- Конкретные факты, которые персонаж сообщает собеседнику.

Если всё сообщение — это только мусор и ничего живого не осталось бы после удаления, верни: ["__DROP__"]

Если мусора нет — верни: []

Отвечай ТОЛЬКО валидным JSON-массивом, без пояснений, без markdown, без префиксов."""


def parse_removals(reply: str) -> list[str] | None:
    """Extract a JSON array of strings. Returns None if malformed."""
    # Strip possible code fences
    s = reply.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        arr = json.loads(s)
    except Exception:
        # Try to find first [...] block
        m = re.search(r"\[.*\]", s, re.DOTALL)
        if not m:
            return None
        try:
            arr = json.loads(m.group(0))
        except Exception:
            return None
    if not isinstance(arr, list):
        return None
    return [str(x) for x in arr]


def apply_removals(original: str, removals: list[str]) -> tuple[str, list[str]]:
    """Remove each substring if it exists verbatim. Returns (edited, applied)."""
    if removals == ["__DROP__"]:
        return ("", ["__DROP__"])
    edited = original
    applied = []
    # Sort longest-first to avoid prefix clashes (e.g. "Не используй markdown"
    # is a substring of "Не используй markdown. Не используй эмодзи.")
    for r in sorted(removals, key=len, reverse=True):
        if r and r in edited:
            edited = edited.replace(r, "")
            applied.append(r)
    # Tidy: collapse ≥3 newlines to 2, strip trailing whitespace on each line
    edited = re.sub(r"\n{3,}", "\n\n", edited).strip()
    return (edited, applied)


async def edit_one(
    client: httpx.AsyncClient, model: str, original: str, temperature: float = 0.2
) -> tuple[str, str, list[str]]:
    """Return (action, edited_text, applied_removals)."""
    # Skip the Ollama call if the message is very short and obviously clean
    if len(original) < 25:
        return ("no_change", original, [])

    resp = await client.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": REDACTOR_PROMPT},
                {"role": "user", "content": original},
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_predict": 1500,
                "temperature": temperature,
            },
        },
        timeout=180,
    )
    resp.raise_for_status()
    reply = (resp.json().get("message", {}).get("content") or "").strip()

    removals = parse_removals(reply)
    if removals is None:
        # Malformed: be safe, no edit
        return ("no_change", original, [])

    if removals == ["__DROP__"]:
        return ("dropped", "", ["__DROP__"])

    if not removals:
        return ("no_change", original, [])

    edited, applied = apply_removals(original, removals)
    if not applied:
        return ("no_change", original, [])
    # Safety: if all content got stripped, mark dropped
    if not edited.strip():
        return ("dropped", "", applied)
    return ("edited", edited, applied)


async def process_file(
    in_path: Path, out_path: Path, model: str, ollama_url: str, limit: int | None
) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    processed = 0
    stats = {"no_change": 0, "edited": 0, "dropped": 0, "errors": 0}

    async with httpx.AsyncClient(base_url=ollama_url) as client:
        with in_path.open() as fin, out_path.open("w") as fout:
            for line_no, raw in enumerate(fin, 1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                new_ex = []
                for ex in row.get("exchanges", []):
                    original = ex.get("user", "")
                    try:
                        action, edited, applied = await edit_one(client, model, original)
                        stats[action] += 1
                    except Exception as e:
                        action, edited, applied = ("no_change", original, [])
                        stats["errors"] += 1
                        print(f"  [ERR] line={line_no} turn={ex.get('turn')}: {e}")
                    new_ex.append({
                        **ex,
                        "user_original": original,
                        "user_edited": edited,
                        "edit_action": action,
                        "edit_removals": applied,
                    })
                    processed += 1
                    if action != "no_change":
                        tag = "✂" if action == "edited" else "🗑"
                        n_rem = len(applied)
                        print(
                            f"  {tag} L{line_no} T{ex.get('turn')}  "
                            f"{len(original)}→{len(edited)}ch  removed={n_rem}"
                        )
                    if limit is not None and processed >= limit:
                        break

                out_row = {
                    **row,
                    "editor_model": model,
                    "editor_version": EDITOR_VERSION,
                    "edited_at": timestamp,
                    "exchanges": new_ex,
                }
                fout.write(json.dumps(out_row, ensure_ascii=False) + "\n")
                fout.flush()
                if limit is not None and processed >= limit:
                    break

    print(f"\nDone. {processed} exchanges processed.")
    print(f"  no_change={stats['no_change']}  edited={stats['edited']}  "
          f"dropped={stats['dropped']}  errors={stats['errors']}")
    print(f"  out: {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--editor-model", default="gemma4:latest")
    p.add_argument("--ollama-url", default="http://192.168.87.25:11434")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    out_path = args.input.with_suffix(".edited.jsonl")
    print(f"Editor: {args.editor_model} via {args.ollama_url} (version={EDITOR_VERSION})")
    print(f"Input:  {args.input}")
    print(f"Output: {out_path}")
    print("=" * 80)

    asyncio.run(process_file(
        args.input, out_path, args.editor_model, args.ollama_url, args.limit
    ))


if __name__ == "__main__":
    main()
