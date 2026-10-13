"""Vigilance (v11; the v10 "Copilot" — the package keeps its name): the fraud-operations agent of the console.

  * incidents.py — deterministic incident engine (9 kinds, hand-set severity rubric), the alerts Vigilance raises;
  * playbooks.py — classification, respond-within targets and the bank procedure for every alert kind;
  * brief.py     — the assessment (classification, red flags, key facts, recommendation) and the STR draft;
  * chat.py / tools.py / gemini.py — the read-only chat: Gemini with tools when a key is set, live-data answers if not.

Vigilance is READ-ONLY: no tool or route can hold, release, freeze or approve anything, and nothing here feeds a
payment tier, detector score or live status. It never reads ground truth (`seed_*`). With no Gemini key (or
COPILOT_ENABLED=false) it runs fully offline on deterministic templates.
"""
