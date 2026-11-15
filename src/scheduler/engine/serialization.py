"""Plain-dict serialization and a stable content hash for :class:`ProblemInstance`.

The hash is computed over canonical JSON (sorted keys, no whitespace), so it is identical across
platforms and Python versions. It will identify the exact inputs a stored run was solved on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scheduler.engine.models import Job, ProblemInstance, Resource, Window


def instance_to_dict(problem: ProblemInstance) -> dict[str, Any]:
    return {
        "horizon": problem.horizon,
        "resources": [
            {
                "id": r.id,
                "name": r.name,
                "windows": [[w.start, w.end] for w in r.windows],
                **({"capacity": r.capacity} if r.capacity != 1 else {}),
            }
            for r in problem.resources
        ],
        "jobs": [
            {
                "id": j.id,
                "name": j.name,
                "duration": j.duration,
                "due": j.due,
                "eligible": list(j.eligible),
                "priority": j.priority,
                "release": j.release,
                **({"work": j.work} if j.work is not None else {}),
            }
            for j in problem.jobs
        ],
    }


def instance_from_dict(data: dict[str, Any]) -> ProblemInstance:
    resources = tuple(
        Resource(
            id=r["id"],
            name=r["name"],
            windows=tuple(Window(start, end) for start, end in r["windows"]),
            capacity=r.get("capacity", 1),
        )
        for r in data["resources"]
    )
    jobs = tuple(
        Job(
            id=j["id"],
            name=j["name"],
            duration=j["duration"],
            due=j["due"],
            eligible=tuple(j["eligible"]),
            priority=j["priority"],
            release=j["release"],
            work=j.get("work"),
        )
        for j in data["jobs"]
    )
    return ProblemInstance(horizon=data["horizon"], resources=resources, jobs=jobs)


def instance_hash(problem: ProblemInstance) -> str:
    """SHA-256 hex digest of the canonical JSON form of ``problem``."""
    canonical = json.dumps(instance_to_dict(problem), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
