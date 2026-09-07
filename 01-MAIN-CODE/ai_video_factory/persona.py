"""Improved persona extraction from transcripts or script text.

This module uses lightweight heuristics to find candidate characters,
their roles, frequent actions, and emotional adjectives. It's conservative
and doesn't require heavy NLP dependencies. The extractor is intentionally
simple and designed to work with noisy script text without external models.
"""
from collections import Counter
import re
from typing import List, Dict


def _tokenize_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"[\n\.\!?]+", text) if s.strip()]


def _find_proper_nouns(text: str) -> List[str]:
    names = set()
    # capture multi-word names like "Captain Alex" or contiguous capitalized tokens
    for m in re.findall(r"\b([A-Z][a-z0-9_]{2,}(?:\s+[A-Z][a-z0-9_]{2,})*)\b", text):
        names.add(m)
    # capture uppercase handles
    for m in re.findall(r"\b[A-Z0-9_]{3,}\b", text):
        names.add(m)
    return list(names)


def extract_personas(text: str, top_k: int = 4, use_spacy: bool = False) -> List[Dict]:
    """Return a list of persona dicts with keys: name, mentions, actions, adjectives, roles, confidence.

    Heuristics:
      - find candidate names by capitalized tokens and handles
      - count mentions and gather short verb/adjective patterns near mentions
      - filter trivial tokens and low-signal candidates
    """
    if not text or not text.strip():
        return []
    # Optional spaCy-backed NER path for higher-quality name extraction
    if use_spacy:
        try:
            import spacy
        except Exception:
            try:
                import subprocess, sys
                subprocess.run([sys.executable, "-m", "pip", "install", "spacy"], check=True, timeout=600)
                import spacy
            except Exception:
                use_spacy = False
        if use_spacy:
            try:
                # ensure model is available
                try:
                    nlp = spacy.load("en_core_web_sm")
                except Exception:
                    try:
                        from spacy.cli import download as spacy_download

                        spacy_download("en_core_web_sm")
                        nlp = spacy.load("en_core_web_sm")
                    except Exception:
                        nlp = None
                if nlp is not None:
                    doc = nlp(text)
                    ents = [ent.text for ent in doc.ents if ent.label_ in ("PERSON", "ORG", "GPE")]
                    counts = Counter(ents)
                    common = [n for n, _ in counts.most_common(top_k)]
                    personas = []
                    for name in common:
                        persona = {"name": name, "mentions": counts.get(name, 0), "actions": [], "adjectives": [], "roles": [], "confidence": 0.9}
                        # gather simple context heuristics around entity occurrences
                        for sent in _tokenize_sentences(text):
                            if name in sent:
                                # crude verb nearby
                                m = re.findall(rf"{re.escape(name)}\s+([a-zA-Z'\-]+)", sent, re.I)
                                for a in m:
                                    if len(a) > 2:
                                        persona["actions"].append(a.lower().strip("'-"))
                        persona["actions"] = list(dict.fromkeys(persona["actions"]))[:8]
                        personas.append(persona)
                    if personas:
                        return personas[:top_k]
            except Exception:
                pass
    sents = _tokenize_sentences(text)
    proper = _find_proper_nouns(text)
    if not proper:
        proper = re.findall(r"\b[A-Z0-9_]{3,}\b", text)
    counts = Counter(proper)
    common = [n for n, _ in counts.most_common(top_k * 3)]

    personas = []
    for name in common:
        persona = {"name": name, "mentions": counts.get(name, 0), "actions": [], "adjectives": [], "roles": []}
        actions = []
        adjectives = []
        roles = []
        for sent in sents:
            if name in sent:
                # verbs/adjectives near the name
                m = re.findall(rf"{re.escape(name)}(?:\s+is|\s+was|\s+did|\s+does|\s+will|\s+has|\s+had)?\s+([a-zA-Z'\-]+)", sent, re.I)
                actions.extend(m[:4])
                # adjectives: 'name is sneaky' or 'name, the sneaky'
                m2 = re.findall(rf"{re.escape(name)}(?:,\s*the\s+([a-zA-Z]+))|{re.escape(name)}\s+is\s+([a-zA-Z]+)", sent, re.I)
                for a in m2:
                    for t in a:
                        if t:
                            adjectives.append(t)
                # role hints
                role_hits = re.findall(r"\b(villager|traitor|hero|ally|enemy|griefer|friend|partner|rival|owner)\b", sent, re.I)
                roles.extend(role_hits)

        # filter trivial tokens
        ACTION_STOP = {"on", "in", "a", "the", "is", "was", "did", "does", "has", "had", "will", "to", "for", "of"}
        filtered_actions = []
        for a in Counter(actions).keys():
            al = a.lower().strip("'-")
            if len(al) > 2 and al not in ACTION_STOP:
                filtered_actions.append(al)

        filtered_adjs = []
        for a in Counter(adjectives).keys():
            al = a.lower()
            if len(al) > 2 and al not in ACTION_STOP:
                filtered_adjs.append(al)

        persona["actions"] = filtered_actions[:8]
        persona["adjectives"] = filtered_adjs[:8]
        persona["roles"] = [r.lower() for r in Counter(roles).keys()][:4]
        personas.append(persona)

    # if no detected personas, try pronoun-derived actor
    if not personas:
        verbs = Counter()
        for sent in sents:
            if re.search(r"\bhe\b|\bshe\b", sent, re.I):
                v = re.findall(r"\b(\w+)ed\b", sent)
                verbs.update(v)
        if verbs:
            personas.append({"name": "protagonist", "mentions": sum(verbs.values()), "actions": list(verbs.keys())[:6], "adjectives": [], "roles": []})

    # assign confidence
    for p in personas:
        p['confidence'] = float(min(1.0, 0.1 * p.get('mentions', 0) + 0.05 * len(p.get('actions', []))))

    # filter noisy single-word capitals
    STOP_WORDS = {"This", "Focus", "Identify", "Watch", "The", "A", "An", "Why", "Here", "When", "Where", "Who", "How"}
    filtered = []
    for p in personas:
        name = p.get('name', '')
        if isinstance(name, str) and name in STOP_WORDS:
            continue
        # keep if multiple mentions or useful signals
        if p.get('mentions', 0) >= 2 or p.get('actions') or p.get('adjectives') or p.get('roles'):
            filtered.append(p)

    if not filtered:
        filtered = personas[:top_k]

    return filtered[:top_k]
