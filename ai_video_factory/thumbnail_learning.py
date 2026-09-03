"""Thumbnail variant selection backed by the existing feedback history."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Tuple

from .knowledge_v2 import RealKnowledgeBase


def rank_thumbnail_variants(kb: RealKnowledgeBase, topic: str) -> Dict[int, Tuple[float, int]]:
    """Return smoothed mean engagement and sample count for variants 1-3."""
    buckets = defaultdict(list)
    for record in kb.feedback_history:
        style = str(record.features.thumbnail_style or "")
        if not style.startswith("variant_"):
            continue
        try:
            variant = int(style.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        if variant in (1, 2, 3):
            topic_bonus = 0.05 if record.features.topic.strip().lower() == topic.strip().lower() else 0.0
            buckets[variant].append((record.engagement_score + topic_bonus, 1))

    ranked: Dict[int, Tuple[float, int]] = {}
    for variant in (1, 2, 3):
        values = buckets.get(variant, [])
        # Beta(1,1)-style smoothing keeps unseen variants near 0.5.
        total = sum(value for value, _ in values)
        count = len(values)
        ranked[variant] = ((total + 0.5) / (count + 1), count)
    return ranked


def choose_thumbnail_variant(root_dir: str, topic: str) -> int:
    """Pick the best observed variant, with stable exploration for ties."""
    kb = RealKnowledgeBase(root_dir=root_dir)
    ranked = rank_thumbnail_variants(kb, topic)
    return max(ranked, key=lambda variant: (ranked[variant][0], ranked[variant][1], -variant))
