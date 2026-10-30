import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeRouteDecision,
    DigitalEmployeeRouteRule,
)
from ticket_agent.digital_employees.service import (
    EMPLOYEE_TEMPLATES,
    DigitalEmployeeService,
)
from ticket_agent.knowledge.local_embedding import tokenize_text
from ticket_agent.shared.settings import get_settings

ROUTE_AMBIGUITY_MARGIN = 0.06
ROUTE_MIN_SCORE = 0.32
ROUTE_SEMANTIC_THRESHOLD = 0.28

_CONCEPT_GROUPS = (
    {"物流", "快递", "配送", "派送", "包裹", "运单", "发货", "到哪", "签收"},
    {
        "退款",
        "退货",
        "换货",
        "售后",
        "破损",
        "损坏",
        "补发",
        "赔偿",
        "漏水",
        "渗水",
        "破裂",
        "瑕疵",
        "少件",
        "缺件",
    },
    {"材质", "容量", "颜色", "尺寸", "参数", "保温", "清洗"},
    {"入职", "劳动合同", "资料", "身份证明", "HR"},
    {"复杂问题", "协同", "协调", "汇总", "主管", "统一处理"},
    {"财务", "金额", "审批", "支付", "对账"},
    {"仓储", "库存", "出库", "补货"},
)


@dataclass(frozen=True)
class RerouteAssessment:
    """Evidence for keeping a conversation with its current employee.

    The router reports scores; it does not switch the conversation. Whether a
    conversation actually moves is decided by the runtime, which also knows
    the sustained-topic and cooldown history.
    """

    current_employee_id: UUID
    current_score: float
    candidate_employee_id: UUID | None
    candidate_score: float
    margin: float
    margin_met: bool
    capability_gap: bool
    strong_gap: bool


@dataclass(frozen=True)
class EmployeeRouteResult:
    employee: DigitalEmployee
    decision: DigitalEmployeeRouteDecision | None
    # Present only when the caller said who currently owns the conversation.
    assessment: RerouteAssessment | None = None


# A buyer asking for another department explicitly. Kept deliberately narrow:
# broad words such as "换" or "人工" appear in ordinary complaints and would
# make the router jump on every annoyed message.
EXPLICIT_EMPLOYEE_REQUEST_TERMS: tuple[str, ...] = (
    "转接",
    "换个客服",
    "换一个客服",
    "换个人",
    "找你们",
    "叫你们",
    "转售后",
    "转财务",
    "转研发",
    "转hr",
)


def explicit_employee_request(text: str) -> bool:
    """True when the buyer explicitly asked for another department."""
    lowered = text.casefold()
    return any(term in lowered for term in EXPLICIT_EMPLOYEE_REQUEST_TERMS)


class DigitalEmployeeRouter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def route_text(
        self,
        *,
        business_unit_id: str,
        subject: str,
        body: str,
        channel: str,
        allowed_employee_ids: set[UUID] | None = None,
        current_employee_id: UUID | None = None,
        persist_decision: bool = True,
    ) -> EmployeeRouteResult:
        """Pick the employee for one message.

        Without ``current_employee_id`` this is the open-time decision: the
        best candidate wins. With it, the router additionally reports how the
        current employee compares, because a conversation should not change
        hands on a single ambiguous message.
        """
        subject_text = subject.casefold()
        body_text = body.casefold()
        statement = (
            select(DigitalEmployee, DigitalEmployeeRouteRule)
            .outerjoin(
                DigitalEmployeeRouteRule,
                DigitalEmployeeRouteRule.employee_id == DigitalEmployee.id,
            )
            .where(
                DigitalEmployee.business_unit_id == business_unit_id,
            )
        )
        if allowed_employee_ids is not None:
            if not allowed_employee_ids:
                raise ValueError(
                    "The business service entry has no enabled employees"
                )
            statement = statement.where(
                DigitalEmployee.id.in_(allowed_employee_ids)
            )
        rows = self.session.execute(statement).all()
        if not rows:
            employee = DigitalEmployeeService(self.session).ensure_default(
                business_unit_id
            )
            return EmployeeRouteResult(employee=employee, decision=None)

        explicit_owners = explicit_intent_owners(rows, channel)
        candidates: list[dict[str, Any]] = []
        for employee, rule in rows:
            excluded_reasons: list[str] = []
            if employee.status != "ACTIVE":
                excluded_reasons.append(f"员工状态为 {employee.status}")
            if rule is None:
                excluded_reasons.append("未配置派单规则")
            elif not rule.enabled:
                excluded_reasons.append("派单规则已停用")
            elif rule.channels_json and channel not in rule.channels_json:
                excluded_reasons.append(
                    f"渠道 {channel} 不在规则范围 {rule.channels_json}"
                )
            intent_breakdown = digital_employee_intent_breakdown(
                employee,
                rule,
                explicit_owners=explicit_owners,
            )
            explicit_terms = intent_breakdown["explicit"]
            inherited_terms = intent_breakdown["inherited"]
            suppressed_terms = intent_breakdown["suppressed"]
            intent_terms = intent_breakdown["effective"]
            matched_subject_terms = [
                term
                for term in intent_terms
                if _has_unnegated_term(subject_text, term)
            ]
            matched_body_terms = [
                term
                for term in intent_terms
                if term not in matched_subject_terms
                and _has_unnegated_term(body_text, term)
            ]
            matched_direct = _unique_strings(
                [*matched_subject_terms, *matched_body_terms]
            )
            matched_synonyms = _synonym_matches(
                subject_text,
                body_text,
                intent_terms,
            )
            matched = _unique_strings(
                [*matched_direct, *matched_synonyms]
            )
            semantic_score = _semantic_similarity(
                _semantic_routing_text(
                    subject_text,
                    body_text,
                    intent_terms,
                ),
                intent_terms,
            )
            keyword_score = min(
                1.0,
                len(matched_subject_terms) * 0.5
                + len(matched_body_terms) * 0.25
                + min(0.5, len(matched_synonyms) * 0.1),
            )
            priority_bonus = (
                max(0.0, 1 - rule.priority / 1000) * 0.10
                if rule is not None
                else 0.0
            )
            fallback_bonus = (
                0.02 if rule is not None and rule.fallback else 0.0
            )
            score = round(
                keyword_score * 0.55
                + semantic_score * 0.35
                + priority_bonus
                + fallback_bonus,
                4,
            )
            candidates.append(
                {
                    "employee_id": str(employee.id),
                    "employee_key": employee.employee_key,
                    "employee_name": employee.name,
                    "template_code": employee.template_code,
                    "status": employee.status,
                    "eligible": not excluded_reasons,
                    "excluded_reasons": excluded_reasons,
                    "keyword_score": round(keyword_score, 4),
                    "semantic_score": round(semantic_score, 4),
                    "score": score,
                    "matched_intents": matched,
                    "matched_direct_terms": matched_direct,
                    "matched_subject_terms": matched_subject_terms,
                    "matched_body_terms": matched_body_terms,
                    "matched_synonyms": matched_synonyms,
                    "explicit_intents": explicit_terms,
                    "inherited_intents": inherited_terms,
                    "suppressed_intents": suppressed_terms,
                    "fallback": bool(rule and rule.fallback),
                    "priority": rule.priority if rule is not None else None,
                    "selected": False,
                }
            )
        eligible = [item for item in candidates if item["eligible"]]
        if not eligible:
            employee = DigitalEmployeeService(self.session).ensure_default(
                business_unit_id
            )
            selected_candidate = _ensure_default_candidate(
                candidates,
                employee,
            )
            selected_candidate["selected"] = True
            decision = DigitalEmployeeRouteDecision(
                business_unit_id=business_unit_id,
                selected_employee_id=employee.id,
                selected_employee_key=employee.employee_key,
                candidates_json=_ordered_candidates(candidates)[:12],
                reason_code="NO_ELIGIBLE_DEFAULT",
                reason="没有可参与派单的员工，已使用平台兜底员工。",
                score=0.0,
                confidence=0.1,
            )
            if persist_decision:
                self.session.add(decision)
                self.session.flush()
            return EmployeeRouteResult(employee=employee, decision=decision)

        eligible.sort(
            key=lambda item: (
                float(item["score"]),
                str(item["employee_key"]),
            ),
            reverse=True,
        )
        winner = eligible[0]
        specific_matches = [
            item
            for item in eligible
            if (
                bool(item["matched_intents"])
                or float(item["semantic_score"])
                >= ROUTE_SEMANTIC_THRESHOLD
            )
            and not bool(item["fallback"])
        ]
        if specific_matches:
            winner = specific_matches[0]
        elif not specific_matches:
            fallback = next(
                (item for item in eligible if bool(item["fallback"])),
                None,
            )
            if fallback is None:
                employee = DigitalEmployeeService(
                    self.session
                ).ensure_default(business_unit_id)
                selected_candidate = _ensure_default_candidate(
                    candidates,
                    employee,
                )
                selected_candidate["selected"] = True
                decision = DigitalEmployeeRouteDecision(
                    business_unit_id=business_unit_id,
                    selected_employee_id=employee.id,
                    selected_employee_key=employee.employee_key,
                    candidates_json=_ordered_candidates(candidates)[:12],
                    reason_code="NO_MATCH_DEFAULT",
                    reason="没有员工规则命中问题，已使用平台兜底员工。",
                    score=0.0,
                    confidence=0.2,
                )
                if persist_decision:
                    self.session.add(decision)
                    self.session.flush()
                return EmployeeRouteResult(
                    employee=employee,
                    decision=decision,
                )
            winner = fallback
        confidence, second = _route_confidence(specific_matches or eligible)
        low_confidence = float(winner["score"]) < ROUTE_MIN_SCORE
        if low_confidence:
            fallback = next(
                (item for item in eligible if bool(item["fallback"])),
                None,
            )
            if fallback is not None:
                winner = fallback
                confidence, second = _route_confidence([fallback])
            else:
                employee = DigitalEmployeeService(
                    self.session
                ).ensure_default(business_unit_id)
                winner = _ensure_default_candidate(
                    candidates,
                    employee,
                )
                confidence = 0.2
                second = None
        assessment: RerouteAssessment | None = None
        if current_employee_id is not None:
            assessment = _assess_reroute(
                candidates=candidates,
                eligible=eligible,
                current_employee_id=current_employee_id,
            )
            # Only a clear capability gap moves the proposal away from the
            # current employee; everything else is decided by the runtime.
            proposed_id = (
                assessment.candidate_employee_id
                if assessment.margin_met and assessment.capability_gap
                else current_employee_id
            )
            proposed = next(
                (
                    item
                    for item in candidates
                    if item["employee_id"] == str(proposed_id)
                ),
                None,
            )
            if proposed is not None and bool(proposed["eligible"]):
                winner = proposed
                confidence, second = _route_confidence(eligible)

        winner_score = float(winner["score"])
        second_score = (
            float(second["score"]) if second is not None else None
        )
        ambiguous = assessment is None and (
            not low_confidence
            and not bool(winner["fallback"])
            and second is not None
            and second_score is not None
            and second_score >= ROUTE_MIN_SCORE
            and winner_score - second_score < ROUTE_AMBIGUITY_MARGIN
            and (
                bool(winner["matched_intents"])
                or winner_score >= ROUTE_MIN_SCORE
            )
        )
        selected = next(
            (
                employee
                for employee, _rule in rows
                if str(employee.id) == winner["employee_id"]
            ),
            None,
        )
        if selected is None:
            selected = self.session.get(
                DigitalEmployee,
                UUID(str(winner["employee_id"])),
            )
        if selected is None:
            selected = DigitalEmployeeService(
                self.session
            ).ensure_default(business_unit_id)
        for candidate in candidates:
            candidate["selected"] = (
                candidate["employee_id"] == winner["employee_id"]
            )
        matched_intents = winner["matched_intents"]
        if ambiguous:
            reason_code = "AMBIGUOUS_REQUIRES_HUMAN"
            reason = (
                "多个数字员工得分接近，已临时选择最高分员工，但该问题需要"
                "人工确认分派。"
            )
        elif low_confidence and winner["fallback"]:
            reason_code = (
                "LOW_CONFIDENCE_FALLBACK"
                if any(
                    item["employee_id"] == winner["employee_id"]
                    for item in eligible
                )
                else "LOW_CONFIDENCE_DEFAULT"
            )
            reason = "没有可靠命中专业员工，已使用兜底员工并建议人工复核。"
        elif isinstance(matched_intents, list) and matched_intents:
            reason_code = "INTENT_MATCH"
            reason = "命中派单依据：" + "、".join(matched_intents)
        elif (
            float(winner["semantic_score"])
            >= ROUTE_SEMANTIC_THRESHOLD
        ):
            reason_code = "SEMANTIC_MATCH"
            reason = (
                "未命中完整关键词，但问题与员工能力语义相近，"
                f"相似度 {winner['semantic_score']:.2f}。"
            )
        else:
            reason_code = "FALLBACK"
            reason = "没有专业员工可靠命中，已使用兜底员工。"
        decision = DigitalEmployeeRouteDecision(
            business_unit_id=business_unit_id,
            selected_employee_id=selected.id,
            selected_employee_key=selected.employee_key,
            candidates_json=_ordered_candidates(candidates)[:12],
            reason_code=reason_code,
            reason=reason,
            score=float(winner["score"]),
            confidence=confidence,
        )
        if persist_decision:
            self.session.add(decision)
            self.session.flush()
        return EmployeeRouteResult(
            employee=selected,
            decision=decision,
            assessment=assessment,
        )


def _assess_reroute(
    *,
    candidates: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    current_employee_id: UUID,
) -> RerouteAssessment:
    """Compare the current employee with the best eligible alternative."""
    current_id = str(current_employee_id)
    current = next(
        (item for item in candidates if item["employee_id"] == current_id),
        None,
    )
    current_score = float(current["score"]) if current is not None else 0.0
    alternatives = [
        item
        for item in eligible
        if item["employee_id"] != current_id
        and not bool(item["fallback"])
        and float(item["score"]) > 0
    ]
    alternative = (
        max(alternatives, key=lambda item: float(item["score"]))
        if alternatives
        else None
    )
    candidate_score = float(alternative["score"]) if alternative else 0.0
    margin = round(candidate_score - current_score, 4)
    capability_gap = (
        alternative is not None
        and _is_specific_match(alternative)
        and not _is_specific_match(current)
    )
    settings = get_settings()
    return RerouteAssessment(
        current_employee_id=current_employee_id,
        current_score=current_score,
        candidate_employee_id=(
            UUID(str(alternative["employee_id"])) if alternative else None
        ),
        candidate_score=candidate_score,
        margin=margin,
        margin_met=(
            alternative is not None
            and candidate_score >= ROUTE_MIN_SCORE
            and margin >= settings.conversation_reroute_margin
        ),
        capability_gap=capability_gap,
        strong_gap=(
            capability_gap
            and margin >= settings.conversation_reroute_strong_margin
        ),
    )


def _is_specific_match(candidate: dict[str, Any] | None) -> bool:
    if candidate is None:
        return False
    return bool(candidate["matched_intents"]) or float(
        candidate["semantic_score"]
    ) >= ROUTE_SEMANTIC_THRESHOLD


def explicit_intent_owners(
    rows: Iterable[Any],
    channel: str,
) -> dict[str, set[str]]:
    """Map explicit rule intents to the employees that claim them.

    Only explicit route-rule intents participate in ownership. Manifest and
    template terms are inherited defaults, so a specialist rule inside the
    same entry pool can take a term away from a generic template employee.
    """

    owners: dict[str, set[str]] = {}
    for employee, rule in rows:
        if employee.status != "ACTIVE" or rule is None or not rule.enabled:
            continue
        if rule.channels_json and channel not in rule.channels_json:
            continue
        for term in _unique_strings(rule.intents_json):
            owners.setdefault(term.casefold(), set()).add(str(employee.id))
    return owners


def digital_employee_intent_breakdown(
    employee: DigitalEmployee,
    rule: DigitalEmployeeRouteRule | None,
    *,
    explicit_owners: dict[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    """Separate explicit, inherited, suppressed and effective intents."""

    explicit = (
        _unique_strings(rule.intents_json)
        if rule is not None and rule.enabled
        else []
    )
    inherited_values = [
        *_manifest_strings(employee, "intents"),
        *_manifest_strings(employee, "capabilities"),
        *_template_intents(employee.template_code),
    ]
    inherited: list[str] = []
    suppressed: list[str] = []
    own_id = str(employee.id)
    for term in _unique_strings(inherited_values):
        if term in explicit:
            continue
        owners = (explicit_owners or {}).get(term.casefold())
        if owners and own_id not in owners:
            suppressed.append(term)
        else:
            inherited.append(term)
    return {
        "explicit": explicit,
        "inherited": inherited,
        "suppressed": suppressed,
        "effective": _unique_strings([*explicit, *inherited]),
    }


def _manifest_strings(
    employee: DigitalEmployee,
    key: str,
) -> list[str]:
    values = employee.manifest_json.get(key, [])
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _template_intents(template_code: str | None) -> list[str]:
    template = next(
        (
            item
            for item in EMPLOYEE_TEMPLATES
            if item.code == template_code
        ),
        None,
    )
    return template.intents if template is not None else []


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _synonym_matches(
    subject_text: str,
    body_text: str,
    intent_terms: list[str],
) -> list[str]:
    matches: list[str] = []
    seen_alias_groups: set[tuple[str, ...]] = set()
    for term in intent_terms:
        group = _concept_group_for(term)
        if group is None:
            continue
        subject_aliases = [
            alias
            for alias in group
            if _has_unnegated_term(subject_text, alias)
        ]
        body_aliases = [
            alias
            for alias in group
            if _has_unnegated_term(body_text, alias)
        ]
        aliases = _unique_strings(
            [*subject_aliases, *body_aliases]
        )
        direct_aliases = [
            alias
            for alias in aliases
            if alias.casefold() not in term.casefold()
        ]
        if direct_aliases:
            alias_group = tuple(direct_aliases[:3])
            if alias_group in seen_alias_groups:
                continue
            seen_alias_groups.add(alias_group)
            matches.append(
                f"{term}≈{'/'.join(alias_group)}"
            )
    return matches


def _concept_group_for(term: str) -> set[str] | None:
    normalized = term.casefold()
    return next(
        (
            item
            for item in _CONCEPT_GROUPS
            if any(
                known.casefold() in normalized
                or normalized in known.casefold()
                for known in item
            )
        ),
        None,
    )


_HARD_NEGATION_PREFIX = re.compile(
    r"(?:不要|不想|不需要|无需|不用|不是|并非|别|不)"
    r"[^，,。；;！!？?\n]{0,4}$"
)
_SOFT_NEGATION_PREFIX = re.compile(
    r"(?:没有|没|未)"
    r"(?:再|继续|提出|发起|申请|要求|要|想|打算|考虑|进行)?"
    r"[^，,。；;！!？?\n]{0,2}$"
)
_LOGISTICS_FACT_TERMS = {
    "物流",
    "快递",
    "配送",
    "派送",
    "包裹",
    "运单",
    "发货",
    "到哪",
    "签收",
}


def _has_unnegated_term(text: str, term: str) -> bool:
    normalized = term.casefold().strip()
    if not normalized:
        return False
    return any(
        not _is_negated(text, match.start(), normalized)
        for match in re.finditer(re.escape(normalized), text)
    )


def _is_negated(text: str, start: int, term: str) -> bool:
    prefix = text[max(0, start - 12) : start]
    if _HARD_NEGATION_PREFIX.search(prefix):
        return True
    if term.casefold() in _LOGISTICS_FACT_TERMS:
        return False
    return bool(_SOFT_NEGATION_PREFIX.search(prefix))


def _semantic_routing_text(
    subject_text: str,
    body_text: str,
    intent_terms: list[str],
) -> str:
    aliases = {
        term.casefold()
        for term in intent_terms
        if term.strip()
    }
    for term in intent_terms:
        group = _concept_group_for(term)
        if group is not None:
            aliases.update(alias.casefold() for alias in group)
    clean_subject = _remove_negated_terms(subject_text, aliases)
    clean_body = _remove_negated_terms(body_text, aliases)
    return f"{clean_subject}\n{clean_subject}\n{clean_body}"


def _remove_negated_terms(text: str, terms: set[str]) -> str:
    cleaned = text
    for term in sorted(terms, key=len, reverse=True):
        if not term:
            continue
        matches = [
            match
            for match in re.finditer(re.escape(term), cleaned)
            if _is_negated(cleaned, match.start(), term)
        ]
        for match in reversed(matches):
            cleaned = (
                cleaned[: match.start()]
                + " " * (match.end() - match.start())
                + cleaned[match.end() :]
            )
    return cleaned


def _semantic_similarity(text: str, intent_terms: list[str]) -> float:
    question_tokens = set(tokenize_text(text))
    if not question_tokens:
        return 0.0
    best = 0.0
    for intent_term in intent_terms:
        intent_tokens = set(tokenize_text(intent_term))
        if not intent_tokens:
            continue
        overlap = question_tokens & intent_tokens
        if len(overlap) < 2:
            continue
        intent_chars = {
            token
            for token in intent_tokens
            if len(token) == 1
        }
        intent_phrases = {
            token
            for token in intent_tokens
            if len(token) > 1
        }
        char_coverage = (
            len(overlap & intent_chars) / len(intent_chars)
            if intent_chars
            else 0.0
        )
        phrase_coverage = (
            len(overlap & intent_phrases) / len(intent_phrases)
            if intent_phrases
            else 0.0
        )
        if (
            not (overlap & intent_phrases)
            and len(overlap & intent_chars) < 2
        ):
            continue
        best = max(best, char_coverage, phrase_coverage)
    return round(best, 4)


def _route_confidence(
    eligible: list[dict[str, Any]],
) -> tuple[float, dict[str, Any] | None]:
    if not eligible:
        return 0.0, None
    ordered = sorted(
        eligible,
        key=lambda item: (
            float(item["score"]),
            str(item["employee_key"]),
        ),
        reverse=True,
    )
    top = float(ordered[0]["score"])
    second = ordered[1] if len(ordered) > 1 else None
    margin = (
        max(0.0, top - float(second["score"])) if second else top
    )
    strength = min(1.0, top / 0.75)
    confidence = min(0.99, 0.45 * strength + 0.54 * margin)
    return round(confidence, 2), second


def _ordered_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (
            bool(item["selected"]),
            bool(item["eligible"]),
            float(item["score"]),
            str(item["employee_key"]),
        ),
        reverse=True,
    )


def _ensure_default_candidate(
    candidates: list[dict[str, Any]],
    employee: DigitalEmployee,
) -> dict[str, Any]:
    for candidate in candidates:
        if candidate["employee_id"] == str(employee.id):
            return candidate
    candidate = {
        "employee_id": str(employee.id),
        "employee_key": employee.employee_key,
        "employee_name": employee.name,
        "template_code": employee.template_code,
        "status": employee.status,
        "eligible": True,
        "excluded_reasons": [],
        "keyword_score": 0.0,
        "semantic_score": 0.0,
        "score": 0.0,
        "matched_intents": [],
        "matched_direct_terms": [],
        "matched_subject_terms": [],
        "matched_body_terms": [],
        "matched_synonyms": [],
        "fallback": True,
        "priority": None,
        "selected": False,
    }
    candidates.append(candidate)
    return candidate
