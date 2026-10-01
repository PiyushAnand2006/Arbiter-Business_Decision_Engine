"""Cross-source agreement (architecture §5.2).

agreement = size of the largest agreeing group / number of sources holding the field.
A fact is conflicted when more than one distinct normalized value exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalize import values_equal


@dataclass
class Reading:
    source: str
    raw: Any
    normalized: Any
    updated_at: str  # ISO timestamp of the source record


@dataclass
class Group:
    normalized: Any
    readings: list[Reading] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return [r.source for r in self.readings]

    @property
    def freshest(self) -> str:
        return max(r.updated_at for r in self.readings)


def group_readings(fieldname: str, readings: list[Reading], tolerance: float) -> list[Group]:
    """Bucket readings into agreeing groups; largest (then freshest) first."""
    groups: list[Group] = []
    for r in readings:
        if r.normalized is None:
            continue
        for g in groups:
            if values_equal(fieldname, g.normalized, r.normalized, tolerance):
                g.readings.append(r)
                break
        else:
            groups.append(Group(normalized=r.normalized, readings=[r]))
    groups.sort(key=lambda g: (len(g.readings), g.freshest), reverse=True)
    return groups


def agreement(groups: list[Group]) -> float:
    total = sum(len(g.readings) for g in groups)
    if total == 0:
        return 0.0
    return len(groups[0].readings) / total


def is_conflicted(groups: list[Group]) -> bool:
    return len(groups) > 1
