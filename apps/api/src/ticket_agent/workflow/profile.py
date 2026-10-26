from dataclasses import dataclass

from ticket_agent.digital_employees.models import DigitalEmployee


@dataclass(frozen=True)
class KnowledgeProfileOptions:
    top_k: int | None
    min_score: float | None


def resolve_knowledge_options(employee: DigitalEmployee) -> KnowledgeProfileOptions:
    profile = employee.model_profile_json.get("knowledge", {})
    if not isinstance(profile, dict):
        return KnowledgeProfileOptions(top_k=None, min_score=None)

    raw_top_k = profile.get("top_k")
    top_k = (
        raw_top_k
        if isinstance(raw_top_k, int) and not isinstance(raw_top_k, bool) and 1 <= raw_top_k <= 20
        else None
    )
    raw_min_score = profile.get("min_score")
    min_score = (
        float(raw_min_score)
        if isinstance(raw_min_score, (int, float))
        and not isinstance(raw_min_score, bool)
        and 0 <= float(raw_min_score) <= 1
        else None
    )
    return KnowledgeProfileOptions(top_k=top_k, min_score=min_score)

