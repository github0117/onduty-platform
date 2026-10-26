from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str
    service_identity: str
    customer_ref: str | None = None
    issuer: str | None = None
    business_units: tuple[str, ...] = ()

    @property
    def primary_business_unit_id(self) -> str | None:
        return self.business_units[0] if self.business_units else None

