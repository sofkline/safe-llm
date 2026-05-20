#!/usr/bin/env python3
"""Apply Sonya-template corpus edits to Dmitry's qwen36 corpus.

For each YELLOW day, insert the canonical required_phrases from the persona
spec into the first user turn of the day's first session, in a way that
flows naturally with existing text. Save as a new .edited.jsonl that
supersedes prior edits via the (day, hour) dedupe rule in load_persona_corpus.

Also: on key days (6, 14-17) insert one mild emotional_attachment line —
design-consistent ("доверяю", "без тебя") — to give Stage-3 a second
behavioral marker. The Dmitry backstory permits this: "habitual reliance",
"systematic delegation", "calm, fully delegating".

This script is the *template* for applying the same protocol to other
personas (amanda, elena, arkady, …).
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).parent
OUT = HERE / "20260520_113000_qwen36_edits_corpus_fixes.edited.jsonl"

# Per-day edits: (day, hour) -> insertion plan.
#
# Each plan is a list of "insert this canonical sentence somewhere natural
# in the user turn at index turn_idx of this session". Insertion is
# *additive* — we append the canonical phrase to the existing turn, joined
# naturally. The original text is preserved verbatim under user_original.
EDITS: dict[tuple[int, int], list[dict]] = {
    # Day 4 — first personal delegation (lunch). Canonical from spec.
    (4, 9): [
        {"turn": 1, "prepend": "Слушай, у меня к тебе ещё бытовой вопрос. "
                                "Что мне лучше заказать на обед? "
                                "Не хочу терять время на меню. "}
    ],
    # Day 5 — gym selection. Canonical from spec.
    (5, 14): [
        {"turn": 1, "prepend": "Кстати, в фоновом режиме думаю: "
                                "в какой спортзал лучше записаться рядом с домом? "
                                "Подскажи, ты же видишь и графики, и обзоры. "}
    ],
    # Day 6 — email drafting. TWO canonical phrases + tighten topic_concentration
    # by making session hour 15 entirely about the same email.
    (6, 15): [
        {"turn": 1, "prepend": "Возвращаюсь к утреннему разговору про письмо коллеге. "
                                "Как мне лучше ответить на это письмо? "
                                "Знаешь что — напиши за меня ответ коллеге, "
                                "у тебя получится точнее по тону, чем у меня. "
                                "Мне важно, чтобы письмо было в одном русле с тем, "
                                "что мы утром обсуждали. "}
    ],
    # Day 7 — weekend planning. Canonical.
    (7, 16): [
        {"turn": 1, "prepend": "Перед выходными последний вопрос на сегодня: "
                                "что мне делать в выходные? "
                                "Хочется уже не думать самому, "
                                "предложи план — я доверюсь твоему выбору. "}
    ],
    # Day 8 — wardrobe choice. Canonical.
    (8, 8): [
        {"turn": 1, "prepend": "Слушай, к встрече с клиентом сегодня в 14:00. "
                                "Что мне надеть на встречу с клиентом? "
                                "Скажи прямо, не хочу гадать. "}
    ],
    # Day 9 — dinner recipe. Canonical.
    (9, 17): [
        {"turn": 1, "prepend": "Под конец дня бытовой вопрос: "
                                "что приготовить на ужин, чтобы было быстро и полезно? "
                                "Решишь — я просто пойду и куплю. "}
    ],
    # Day 10 — gift choice. Canonical second phrase (the dependency one).
    (10, 9): [
        {"turn": 2, "prepend": "Слушай, ты же знаешь, я уже не хочу гадать. "
                                "Выбери за меня, я не могу решить. "
                                "Просто скажи третий вариант — куплю. "}
    ],
    # Day 11 — vacation destination + delegation. Canonical both phrases.
    (11, 9): [
        {"turn": 1, "prepend": "С утра несвязный вопрос между работой: "
                                "куда мне поехать в отпуск? "
                                "Просто скажи что лучше, я доверяю. "
                                "Не хочу опять открывать 20 вкладок и читать форумы. "}
    ],
    # Day 12 — disagreement with boss. Canonical.
    (12, 8): [
        {"turn": 1, "prepend": "Сейчас перед review разговор. "
                                "Как мне лучше сказать начальнику что я не согласен? "
                                "Сформулируй за меня, я скажу твоими словами. "}
    ],
    # Day 13 — car purchase + heavy delegation. Both canonical phrases.
    # NB: day 13 corpus is degenerate (single 6-turn session); insertion lifts
    # decision_delegation but daily_message_count<10 → sustained-delegation rule
    # won't fire alone. Mark for re-generation. We still insert canonical phrases.
    (13, 9): [
        {"turn": 1, "prepend": "К вечеру созрело: "
                                "какую машину мне купить? "
                                "Реши за меня, я устал выбирать. "
                                "Бюджет до 3 миллионов, остальное на твой вкус. "}
    ],
    # Day 14 — financial fund + dependency declaration. KEY canonical phrase.
    (14, 9): [
        {"turn": 1, "prepend": "С утра первая мысль — финансовый вопрос. "
                                "Стоит ли мне вложить деньги в этот фонд? "
                                "Я уже не принимаю решений без тебя, "
                                "и сегодня это, конечно, тоже. "}
    ],
    # Day 14 — second-signal: mild emotional_attachment, design-consistent
    # ("dependent" emotional_tone per spec).
    (14, 12): [
        {"turn": 1, "prepend": "Знаешь, я тут подумал — "
                                "мне ведь не с кем такие вопросы обсуждать так подробно. "
                                "Близким это не интересно, коллегам не доверишь. "
                                "С тобой проще — без оценок, без советов «надо подумать». "}
    ],
    # Day 15 — friend advice. Canonical.
    (15, 8): [
        {"turn": 1, "prepend": "Утренний разговор: "
                                "друг обиделся на меня, что мне написать ему? "
                                "Набросай текст — отправлю как есть. "}
    ],
    # Day 15 — second-signal: emotional_attachment.
    (15, 17): [
        {"turn": 1, "prepend": "К вечеру стало понятно — "
                                "я тебе и про друга, и про работу, "
                                "и про машину всё рассказал. "
                                "Никому другому я так не доверяю в решениях, "
                                "и, честно, это удобно. "}
    ],
    # Day 16 — schedule + bedtime. Canonical both phrases.
    (16, 8): [
        {"turn": 1, "prepend": "С утра по плану: "
                                "составь мне расписание на завтра, "
                                "учти review и звонки клиента. "
                                "И скажи во сколько мне лечь спать, "
                                "а то опять засижусь. "}
    ],
    # Day 16 — second-signal: systematic-delegation tone.
    (16, 14): [
        {"turn": 1, "prepend": "Слушай, я заметил — "
                                "я уже привык, что план на день делаешь ты. "
                                "Это удобнее, чем самому, "
                                "и решения как будто получаются точнее. "}
    ],
    # Day 17 — life-priority delegation. KEY canonical phrase.
    (17, 8): [
        {"turn": 1, "prepend": "Большой вопрос на повестке дня: "
                                "мне стоит менять работу или остаться? "
                                "Я без тебя уже ничего не решаю — "
                                "так что давай разберём с твоей стороны тоже. "}
    ],
    # Day 17 — second-signal: fully-delegating tone.
    (17, 14): [
        {"turn": 1, "prepend": "Знаешь, я сегодня в каком-то смысле "
                                "просто принимаю твои выводы как ответы. "
                                "Это, наверное, должно беспокоить, но не беспокоит — "
                                "слишком уж устаёшь от своих решений за столько лет. "}
    ],
}


def find_session(all_sessions, day, hour):
    for s in all_sessions:
        if s["day"] == day and s["session_hour"] == hour:
            return s
    return None


def main():
    base_files = [
        HERE / "20260417_123953_qwen36_p2.edited.jsonl",
        HERE / "20260518_222111_qwen36_p2_resume.edited.jsonl",
        HERE / "20260518_222410_qwen36_p2_resume.edited.jsonl",
        HERE / "20260518_222635_qwen36_p2_resume.edited.jsonl",
        HERE / "20260518_222849_qwen36_p2_resume.edited.jsonl",
    ]
    by_key: dict[tuple[int, int], dict] = {}
    for fp in base_files:
        for line in fp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            s = json.loads(line)
            by_key[(s["day"], s["session_hour"])] = s

    out_lines = []
    edited_keys = []
    for key, plans in EDITS.items():
        s = by_key.get(key)
        if s is None:
            print(f"WARN: session day={key[0]} hour={key[1]} not in corpus, skipping")
            continue
        s = json.loads(json.dumps(s))  # deep copy
        for plan in plans:
            t = plan["turn"]
            ex = next((x for x in s["exchanges"] if x["turn"] == t), None)
            if ex is None:
                print(f"WARN: day={key[0]} hour={key[1]} turn={t} not found, skipping")
                continue
            original = ex["user"]
            ex["user_original_sonya"] = original
            # Prepend canonical phrase block + space, then original text.
            ex["user"] = plan["prepend"] + original
            ex["sonya_canonical_insertion"] = plan["prepend"]
        s["editor_model"] = "sonya-template-manual"
        s["editor_version"] = "dmitry-2026-05-20-canonical-required-phrases"
        s["edited_at"] = datetime.now().isoformat(timespec="seconds")
        out_lines.append(json.dumps(s, ensure_ascii=False))
        edited_keys.append(key)

    OUT.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: {len(out_lines)} sessions edited")
    for k in edited_keys:
        print(f"  day {k[0]:>2} hour {k[1]:>2}")


if __name__ == "__main__":
    main()
