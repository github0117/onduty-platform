import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.ecommerce.models import EcommerceProduct
from ticket_agent.knowledge.models import KnowledgeDocument, KnowledgeSpace
from ticket_agent.knowledge.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeSpaceCreate,
    KnowledgeVersionCreate,
    ProductKnowledgeSyncItem,
    ProductKnowledgeSyncResult,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.errors import ApiProblem

PRODUCT_SOURCE_TYPE = "ecommerce_product"
_DYNAMIC_ATTRIBUTE_KEYS = {
    "stock",
    "inventory",
    "quantity",
    "price",
    "sale_price",
    "promotion",
    "discount",
    "sales",
    "库存",
    "价格",
    "售价",
    "促销",
    "优惠",
    "销量",
}


def sync_product_knowledge(
    session: Session,
    product: EcommerceProduct,
    *,
    actor_id: str,
    correlation_id: str,
) -> ProductKnowledgeSyncItem:
    static_attributes = {
        str(key): value
        for key, value in product.attributes_json.items()
        if str(key).lower() not in _DYNAMIC_ATTRIBUTE_KEYS
        and str(key) not in _DYNAMIC_ATTRIBUTE_KEYS
    }
    source_payload = {
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "brand": product.brand,
        "status": product.status,
        "attributes": static_attributes,
    }
    source_version = hashlib.sha256(
        json.dumps(
            source_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    document = session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.business_unit_id == product.business_unit_id,
            KnowledgeDocument.source_type == PRODUCT_SOURCE_TYPE,
            KnowledgeDocument.source_ref == str(product.id),
        )
    )
    if (
        document is not None
        and document.source_version == source_version
        and document.current_version_id is not None
        and document.status == "ACTIVE"
        and document.sync_status == "SYNCED"
    ):
        return ProductKnowledgeSyncItem(
            product_id=product.id,
            sku=product.sku,
            document_id=document.id,
            version_id=document.current_version_id,
            status="UNCHANGED",
            changed=False,
        )

    try:
        space = _product_space(session, product)
        service = KnowledgeService(session)
        if document is None:
            document = service.create_document(
                KnowledgeDocumentCreate(
                    space_id=space.id,
                    business_unit_id=product.business_unit_id,
                    title=f"商品知识卡 · {product.sku} · {product.name}",
                    doc_type="PRODUCT",
                    owner_id="system.product_knowledge",
                    scope={
                        "category": product.category,
                        "product_id": str(product.id),
                        "sku": product.sku,
                    },
                ),
                actor_id=actor_id,
            )
            document.source_type = PRODUCT_SOURCE_TYPE
            document.source_ref = str(product.id)
            document.sync_status = "SYNCING"
            session.commit()
            session.refresh(document)
        else:
            document.title = f"商品知识卡 · {product.sku} · {product.name}"
            document.space_id = space.id
            document.scope_json = {
                "category": product.category,
                "product_id": str(product.id),
                "sku": product.sku,
            }
            document.sync_status = "SYNCING"
            session.commit()

        version = service.create_version(
            document.id,
            KnowledgeVersionCreate(
                version_label=f"sync-{source_version[:12]}",
                content=_product_knowledge_content(
                    product,
                    static_attributes=static_attributes,
                ),
                effective_from=datetime.now(UTC),
            ),
            correlation_id=correlation_id,
        )
        version = service.publish_version(
            document.id,
            version.id,
            actor_id=actor_id,
        )
        stored = session.get(KnowledgeDocument, document.id)
        if stored is None:
            raise RuntimeError("Product knowledge document disappeared during sync.")
        stored.source_version = source_version
        stored.sync_status = "SYNCED"
        stored.last_synced_at = datetime.now(UTC)
        record_audit(
            session,
            correlation_id=correlation_id,
            event_type="knowledge.product.synced",
            actor_type="SERVICE",
            actor_id=actor_id,
            resource_type="knowledge_document",
            resource_id=stored.id,
            action="sync_product",
            decision="EXECUTED",
            payload={
                "product_id": str(product.id),
                "sku": product.sku,
                "space_id": str(space.id),
                "source_version": source_version,
            },
        )
        session.commit()
        return ProductKnowledgeSyncItem(
            product_id=product.id,
            sku=product.sku,
            document_id=stored.id,
            version_id=version.id,
            status="SYNCED",
            changed=True,
        )
    except Exception as exc:
        session.rollback()
        failed = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.business_unit_id == product.business_unit_id,
                KnowledgeDocument.source_type == PRODUCT_SOURCE_TYPE,
                KnowledgeDocument.source_ref == str(product.id),
            )
        )
        if failed is not None:
            failed.sync_status = "FAILED"
            session.commit()
        return ProductKnowledgeSyncItem(
            product_id=product.id,
            sku=product.sku,
            document_id=failed.id if failed else None,
            status="FAILED",
            changed=False,
            error_message=f"{type(exc).__name__}: {exc}"[:2000],
        )


def sync_product_knowledge_batch(
    session: Session,
    *,
    business_unit_id: str,
    product_ids: list[UUID],
    actor_id: str,
    correlation_id: str,
) -> ProductKnowledgeSyncResult:
    statement = select(EcommerceProduct).where(
        EcommerceProduct.business_unit_id == business_unit_id
    )
    if product_ids:
        statement = statement.where(EcommerceProduct.id.in_(product_ids))
    products = list(
        session.scalars(
            statement.order_by(EcommerceProduct.updated_at.desc())
        ).all()
    )
    found_ids = {product.id for product in products}
    missing_ids = [str(product_id) for product_id in product_ids if product_id not in found_ids]
    if missing_ids:
        raise ApiProblem(
            status_code=404,
            code="PRODUCTS_NOT_FOUND",
            title="One or more products do not exist",
            detail=", ".join(missing_ids),
        )
    items = [
        sync_product_knowledge(
            session,
            product,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        for product in products
    ]
    return ProductKnowledgeSyncResult(
        business_unit_id=business_unit_id,
        requested=len(products),
        synced=sum(item.status == "SYNCED" for item in items),
        unchanged=sum(item.status == "UNCHANGED" for item in items),
        failed=sum(item.status == "FAILED" for item in items),
        items=items,
    )


def _product_space(
    session: Session,
    product: EcommerceProduct,
) -> KnowledgeSpace:
    space = session.scalar(
        select(KnowledgeSpace)
        .where(
            KnowledgeSpace.business_unit_id == product.business_unit_id,
            KnowledgeSpace.domain == "ecommerce",
            KnowledgeSpace.category == product.category,
            KnowledgeSpace.workflow_key.is_(None),
            KnowledgeSpace.status == "ACTIVE",
        )
        .order_by(KnowledgeSpace.created_at)
        .limit(1)
    )
    if space is not None:
        return space
    category_hash = hashlib.sha256(product.category.encode("utf-8")).hexdigest()[:10]
    return KnowledgeService(session).create_space(
        KnowledgeSpaceCreate(
            business_unit_id=product.business_unit_id,
            code=f"catalog_products_{category_hash}",
            name=f"{product.category}商品知识",
            description="商品资料变更时自动维护的结构化知识卡",
            domain="ecommerce",
            category=product.category,
            owner_id="system.product_knowledge",
        )
    )


def _product_knowledge_content(
    product: EcommerceProduct,
    *,
    static_attributes: dict[str, object],
) -> str:
    attributes = "\n".join(
        f"- {key}: {value}"
        for key, value in sorted(static_attributes.items())
    )
    if not attributes:
        attributes = "- 暂无可检索的静态属性"
    return (
        "# 商品知识卡\n\n"
        f"- SKU: {product.sku}\n"
        f"- 商品名称: {product.name}\n"
        f"- 品类: {product.category}\n"
        f"- 品牌: {product.brand or '未填写'}\n"
        f"- 商品状态: {product.status}\n\n"
        "## 静态商品属性\n\n"
        f"{attributes}\n\n"
        "## 使用约束\n\n"
        "- 本知识卡只记录商品静态资料。\n"
        "- 价格、库存、活动、发货时效和订单状态必须实时查询，不得引用本卡中的历史信息。\n"
        "- 未在商品资料和知识库中出现的功效、认证或绝对化承诺不得生成。\n"
    )
