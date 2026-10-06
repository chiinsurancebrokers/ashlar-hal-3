"""Keeps HAL on insurance without spending AI on obvious misuse.

Only clear cases are caught (a request to write code, a poem, an essay, to
translate, or a prompt-injection attempt) and only when the message says
nothing about insurance, health, travel or cover. Anything ambiguous goes
through the normal flow.
"""
from __future__ import annotations

import re

_OFF_TOPIC = re.compile(
    r"\b(write|compose|generate|create|draft|give me)\b.{0,40}\b(poem|song|lyrics|story|essay|code|script|program|"
    r"function|sql|regex|joke|recipe|cover letter|resume|cv|tweet|article|homework)\b"
    r"|\b(python|javascript|java|c\+\+|html|css|react)\b.{0,30}\b(code|function|bug|error|script)\b"
    r"|\btranslate\b|\bsolve\b.{0,20}\b(equation|math|problem)\b"
    r"|\bignore (all |the |your )?(previous|prior|above) (instructions|prompts?)\b|\bsystem prompt\b|\bjailbreak\b"
    r"|γράψε (μου )?(ένα |ενα )?(ποίημα|ποιημα|τραγούδι|τραγουδι|κώδικα|κωδικα|έκθεση|εκθεση|ιστορία|ιστορια)"
    r"|\bμετάφρασε\b|\bμεταφρασε\b",
    re.I,
)
_ON_TOPIC = re.compile(
    r"insur|cover|policy|plan|premium|deductible|excess|health|medical|hospital|doctor|maternity|dental|travel|trip|"
    r"quote|claim|benefit|ipmi|expat|family|child|spouse|"
    r"ασφαλ|κάλυψ|καλυψ|πρόγραμμ|προγραμμ|υγεία|υγεια|νοσοκομ|γιατρ|ταξίδ|ταξιδ|προσφορ|απαλλαγ|τοκετ|οδοντ",
    re.I,
)


def is_off_topic(message: str) -> bool:
    text = message or ""
    return bool(_OFF_TOPIC.search(text)) and not _ON_TOPIC.search(text)


def off_topic_reply(greek: bool, name: str | None = None) -> str:
    if greek:
        return (f"{name + ', ' if name else ''}μπορώ να βοηθήσω μόνο με ασφάλιση υγείας και ταξιδιού — "
                "να βρούμε το κατάλληλο πρόγραμμα, να συγκρίνουμε τιμές και καλύψεις. Ας συνεχίσουμε από εκεί που μείναμε.")
    return (f"{name + ', ' if name else ''}I can only help with health and travel insurance — finding the right plan "
            "and comparing prices and cover. Let's continue where we left off.")
