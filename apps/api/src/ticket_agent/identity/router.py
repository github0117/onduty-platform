from typing import Annotated

from fastapi import APIRouter, Query

from ticket_agent.api.dependencies import Actor
from ticket_agent.identity.dependencies import resolve_business_unit
from ticket_agent.identity.policy import (
    DEMO_RESET_BUSINESS_UNIT_LABELS,
    POLICY_VERSION,
    ROLE_LABELS,
    capabilities_for,
    demo_reset_feature,
)
from ticket_agent.shared.settings import get_settings

router = APIRouter(tags=["identity"])


@router.get("/me")
def get_me(
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    """Return the server-authoritative identity and capability snapshot."""

    active_business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    settings = get_settings()
    business_units = list(principal.business_units)
    labels = {
        unit: DEMO_RESET_BUSINESS_UNIT_LABELS.get(unit, unit)
        for unit in business_units
    }
    return {
        "actor_id": principal.actor_id,
        "role": principal.role,
        "role_label": ROLE_LABELS.get(principal.role, principal.role),
        "issuer": principal.issuer or "dev",
        "auth_mode": settings.app_auth_mode,
        "service_identity": principal.service_identity,
        "policy_version": POLICY_VERSION,
        "test_identity_switch_enabled": settings.app_auth_mode != "oidc",
        "business_units": business_units,
        "business_unit_labels": labels,
        "primary_business_unit_id": principal.primary_business_unit_id,
        "active_business_unit_id": active_business_unit_id,
        "capabilities": sorted(capabilities_for(principal.role)),
        "features": {
            "demo_reset": demo_reset_feature(
                principal,
                active_business_unit_id,
            ),
        },
    }
