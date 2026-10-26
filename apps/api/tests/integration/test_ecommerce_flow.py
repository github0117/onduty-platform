import json
import wave
import zipfile
from io import BytesIO
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.models import ConversationTurn
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.ecommerce.models import (
    EcommerceListingTask,
    EcommerceProductAsset,
    EcommerceVideoRenderJob,
)
from ticket_agent.outbox.service import dispatch_pending_events
from ticket_agent.shared.db import SessionLocal

ADMIN = {"X-Actor-Id": "ecommerce-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "ecommerce-agent", "X-Actor-Role": "agent"}
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
    b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_operation_owner_employees() -> dict[str, str]:
    with SessionLocal() as session:
        listing = DigitalEmployee(
            employee_key="test_ecommerce_listing_operator",
            name="测试商品上架数字员工",
            scenario_type="ecommerce_operations",
            domain="ecommerce_operations",
            template_code="ecommerce_listing_operator",
            workflow_key="customer_service_ticket_v1",
            business_unit_id="bu_demo",
            service_identity="digital_employee.test_listing",
            status="ACTIVE",
            handoff_queue="ECOMMERCE_LISTING_REVIEW",
            created_by="test",
        )
        visual = DigitalEmployee(
            employee_key="test_ecommerce_visual_creator",
            name="测试视觉内容数字员工",
            scenario_type="ecommerce_operations",
            domain="content_media",
            template_code="ecommerce_visual_creator",
            workflow_key="customer_service_ticket_v1",
            business_unit_id="bu_demo",
            service_identity="digital_employee.test_visual",
            status="ACTIVE",
            handoff_queue="ECOMMERCE_VISUAL_REVIEW",
            created_by="test",
        )
        session.add_all([listing, visual])
        session.commit()
        return {
            "listing": str(listing.id),
            "visual": str(visual.id),
        }


def _create_rules(client: TestClient) -> None:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "title": "电商平台商品发布规则",
            "doc_type": "POLICY",
            "owner_id": "ecommerce-admin",
            "scope": {
                "channels": ["local_shop"],
                "audiences": ["ecommerce_operator"],
            },
        },
    )
    assert document.status_code == 201, document.text
    version = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "商品标题和详情必须真实准确，不得使用国家级、世界第一、"
                "绝对安全等无法证明的宣传用语。价格和优惠必须明确。"
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=ADMIN,
        json={"release_note": "ecommerce test"},
    )
    assert published.status_code == 200, published.text


def _create_us_rules(client: TestClient) -> None:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "title": "Amazon US Listing Compliance",
            "doc_type": "POLICY",
            "owner_id": "ecommerce-admin",
            "scope": {
                "channels": ["local_shop"],
                "audiences": ["ecommerce_operator"],
                "market_codes": ["US"],
            },
        },
    )
    assert document.status_code == 201, document.text
    version = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "Amazon US listings require accurate English content, HS code, "
                "country of origin, shipping weight and package dimensions. "
                "Do not use FDA approved, cures, best in the world, 100% safe "
                "or guaranteed results without substantiation."
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=ADMIN,
        json={"release_note": "US market compliance test"},
    )
    assert published.status_code == 200, published.text


def _create_pinduoduo_rules(client: TestClient) -> None:
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "title": "拼多多雪地靴发布规则",
            "doc_type": "POLICY",
            "owner_id": "ecommerce-admin",
            "scope": {
                "channels": ["pinduoduo_sandbox"],
                "audiences": ["ecommerce_operator"],
            },
        },
    )
    assert document.status_code == 201, document.text
    version = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "拼多多雪地靴必须真实描述鞋面、内里、鞋底材质、跟高、筒高、"
                "闭合方式和尺码范围，并展示鞋底纹路和内里材质。"
                "不得使用顶级、绝对保暖、100% 防滑等无法证明的宣传用语。"
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=ADMIN,
        json={"release_note": "Pinduoduo snow boots pilot"},
    )
    assert published.status_code == 200, published.text


def _create_product(
    client: TestClient,
    *,
    sku: str,
    name: str,
    price: float = 39.9,
    attributes: dict[str, object] | None = None,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/ecommerce/products",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "sku": sku,
            "name": name,
            "category": "家居日用",
            "brand": "演示品牌",
            "price": price,
            "attributes": attributes
            or {"材质": "食品级硅胶", "颜色": "奶油白"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_cover(client: TestClient, product_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/ecommerce/products/{product_id}/assets?filename=cover.png",
        headers={**AGENT, "Content-Type": "image/png"},
        content=TINY_PNG,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _silence_wav(seconds: float = 1.0) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\x00\x00" * round(24_000 * seconds))
    return buffer.getvalue()


def test_create_and_update_ecommerce_category_profile(client: TestClient) -> None:
    created = client.post(
        "/api/v1/ecommerce/categories",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "channel": "pinduoduo_sandbox",
            "code": "vacuum_cup",
            "name": "保温杯",
            "required_attributes": ["容量", "杯身材质", "保温时长"],
            "presales_keywords": ["容量", "保温", "材质"],
            "aftersales_keywords": ["漏水", "杯盖"],
            "restricted_claims": ["永久保温", "医疗级"],
        },
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]
    listed = client.get(
        "/api/v1/ecommerce/categories?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["code"] == "vacuum_cup"
    updated = client.patch(
        f"/api/v1/ecommerce/categories/{profile_id}",
        headers=ADMIN,
        json={"required_attributes": ["容量", "杯身材质", "内胆材质", "保温时长"]},
    )
    assert updated.status_code == 200
    assert "内胆材质" in updated.json()["required_attributes"]
    template = client.get(
        f"/api/v1/ecommerce/categories/{profile_id}/import-template",
        headers=AGENT,
    )
    assert template.status_code == 200
    template_text = template.content.decode("utf-8-sig")
    assert "保温杯示例商品" in template_text
    assert "内胆材质" in template_text
    assert "upper_material" not in template_text
    csv_text = (
        "sku,name,category,brand,price,stock,容量,杯身材质,内胆材质,保温时长\n"
        "CUP-CSV-001,CSV保温杯,保温杯,CSV品牌,79,30,480ml,304不锈钢,316不锈钢,12小时\n"
    )
    preview_category = client.post(
        "/api/v1/ecommerce/products/import/preview",
        params={"business_unit_id": "bu_demo", "category_profile_id": profile_id},
        headers={**ADMIN, "Content-Type": "text/csv; charset=utf-8"},
        content=csv_text,
    )
    assert preview_category.status_code == 200, preview_category.text
    assert preview_category.json()["valid_rows"] == 1
    imported_category = client.post(
        "/api/v1/ecommerce/products/import",
        params={"business_unit_id": "bu_demo", "category_profile_id": profile_id},
        headers={**ADMIN, "Content-Type": "text/csv; charset=utf-8"},
        content=csv_text,
    )
    assert imported_category.status_code == 200
    assert imported_category.json()["created_count"] == 1

    product = client.post(
        "/api/v1/ecommerce/products",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "sku": "CUP-DYNAMIC-001",
            "name": "动态品类保温杯",
            "category": "保温杯",
            "brand": "测试品牌",
            "price": 99,
            "attributes": {"容量": "480ml"},
        },
    )
    assert product.status_code == 201
    _upload_cover(client, str(product.json()["id"]))
    listing = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product.json()["id"], "channel": "pinduoduo_sandbox"},
    )
    assert listing.status_code == 201, listing.text
    missing = listing.json()["compliance"]["channel_required_attributes_missing"]
    assert {"杯身材质", "内胆材质", "保温时长"} <= set(missing)

    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "vacuum_cup_aftersales_employee",
            "name": "保温杯售后客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.vacuum_cup_aftersales",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
        },
    )
    assert employee.status_code == 201, employee.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "vacuum-cup-aftersales",
            "category_name": "保温杯",
            "category_profile_id": profile_id,
        },
    )
    assert conversation.status_code == 201, conversation.text
    accepted = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={"content": "我的保温杯漏水了，订单怎么申请退货退款？"},
    )
    assert accepted.status_code == 202, accepted.text
    ticket = client.get(
        f"/api/v1/tickets/{accepted.json()['current_ticket_id']}",
        headers=AGENT,
    )
    assert ticket.status_code == 200, ticket.text
    detail = ticket.json()
    assert detail["classification"]["primary"] == "ecommerce_aftersales"
    assert detail["classification"]["secondary"] == "category_after_sales"
    assert detail["risk"]["level"] == "R2"
    assert detail["priority"]["level"] == "P1"
    assert detail["routing"]["queue_id"] == "ECOMMERCE_AFTERSALES"
    assert detail["needs_human"] is True
    assert detail["draft"] is None


def test_grounded_low_risk_presales_is_auto_approved(
    client: TestClient,
) -> None:
    category = client.post(
        "/api/v1/ecommerce/categories",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "channel": "pinduoduo_sandbox",
            "code": "vacuum_cup_auto_reply",
            "name": "保温杯",
            "required_attributes": ["容量", "内胆材质", "保温时长"],
            "presales_keywords": ["材质", "内胆", "保温"],
            "aftersales_keywords": ["漏水", "退货", "退款"],
            "restricted_claims": ["永久保温"],
        },
    )
    assert category.status_code == 201, category.text
    product = client.post(
        "/api/v1/ecommerce/products",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "sku": "CUP-AUTO-REPLY-001",
            "name": "316不锈钢保温杯",
            "category": "保温杯",
            "brand": "测试品牌",
            "price": 89,
            "attributes": {
                "容量": "480ml",
                "内胆材质": "316不锈钢",
                "保温时长": "12小时",
                "stock": 50,
            },
        },
    )
    assert product.status_code == 201, product.text
    employee = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": "cup_auto_reply_employee",
            "name": "保温杯自动回复客服",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": "digital_employee.cup_auto_reply",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
        },
    )
    assert employee.status_code == 201, employee.text
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": "bu_demo",
            "code": "cup_auto_reply_presales",
            "name": "保温杯自动回复售前知识",
            "description": "低风险售前自动回复验收",
            "domain": "ecommerce",
            "channel": "pinduoduo",
            "category": "保温杯",
            "category_profile_id": category.json()["id"],
            "workflow_key": "ecommerce_customer_service_v1",
            "owner_id": "ecommerce-admin",
            "evaluation_required": False,
        },
    )
    assert space.status_code == 201, space.text
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "保温杯售前参数",
            "doc_type": "FAQ",
            "owner_id": "ecommerce-admin",
            "scope": {},
        },
    )
    assert document.status_code == 201, document.text
    version = client.post(
        f"/api/v1/knowledge-documents/{document.json()['id']}/versions",
        headers=ADMIN,
        json={
            "version_label": "1.0",
            "content": (
                "这款保温杯容量为 480ml，内胆材质为 316 不锈钢，"
                "保温时长可达 12 小时。库存、价格和发货时效以商品页实时信息为准。"
            ),
        },
    )
    assert version.status_code == 201, version.text
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document.json()['id']}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=ADMIN,
        json={"release_note": "auto reply test"},
    )
    assert published.status_code == 200, published.text
    bound = client.put(
        (
            "/api/v1/digital-employees/"
            f"{employee.json()['id']}/knowledge-bindings"
        ),
        headers=ADMIN,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "workflow_key": "ecommerce_customer_service_v1",
                    "scope": {},
                    "enabled": True,
                }
            ]
        },
    )
    assert bound.status_code == 200, bound.text
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "auto-reply-buyer",
            "category_name": "保温杯",
            "category_profile_id": category.json()["id"],
        },
    )
    assert conversation.status_code == 201, conversation.text
    accepted = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={
            "content": "这款保温杯内胆是什么材质，能保温多久？",
            "product_id": product.json()["id"],
            "sku": product.json()["sku"],
        },
    )
    assert accepted.status_code == 202, accepted.text
    ticket_id = accepted.json()["current_ticket_id"]
    preview = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT).json()

    stored = client.get(
        f"/api/v1/customer-service/conversations/{conversation.json()['id']}",
        headers=AGENT,
    )
    assert stored.status_code == 200, stored.text
    assert [
        message["role"] for message in stored.json()["messages"]
    ] == ["BUYER", "ASSISTANT"], json.dumps(preview, ensure_ascii=False)
    assert stored.json()["messages"][1]["content"].strip()

    dispatch_pending_events()
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["classification"]["primary"] == "ecommerce_presales"
    assert result["risk"]["level"] == "R0"
    assert result["routing"]["needs_human"] is False
    assert result["workflow_state"] == "COMPLETED"
    conversation_payload = stored.json()
    assert conversation_payload["current_turn"]["status"] == "COMPLETED"
    assert conversation_payload["current_turn"]["grounding_status"] == "GROUNDED"
    assert (
        conversation_payload["current_turn"]["citations"][0]["title"]
        == "保温杯售前参数"
    )
    queue = client.get(
        "/api/v1/customer-service/assignment-queue",
        headers=AGENT,
    )
    assert queue.status_code == 200, queue.text
    assert all(
        item["conversation_id"] != conversation.json()["id"]
        for item in queue.json()["items"]
    )

    human_conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee.json()["id"],
            "requester_ref": "manual-suggestion-buyer",
            "category_name": "保温杯",
            "category_profile_id": category.json()["id"],
        },
    )
    assert human_conversation.status_code == 201, human_conversation.text
    human_message = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{human_conversation.json()['id']}/messages"
        ),
        headers=AGENT,
        json={
            "content": "我的保温杯漏水了，内胆是什么材质？",
            "product_id": product.json()["id"],
            "sku": product.json()["sku"],
        },
    )
    assert human_message.status_code == 202, human_message.text
    human_ticket = client.get(
        f"/api/v1/tickets/{human_message.json()['current_ticket_id']}",
        headers=AGENT,
    )
    assert (
        human_ticket.json()["classification"]["primary"]
        == "ecommerce_aftersales"
    )
    human_conversation_detail = client.get(
        (
            "/api/v1/customer-service/conversations/"
            f"{human_conversation.json()['id']}"
        ),
        headers=AGENT,
    )
    assert human_conversation_detail.status_code == 200
    human_takeover = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{human_conversation.json()['id']}/takeover"
        ),
        headers=AGENT,
        json={
            "expected_version": human_conversation_detail.json()["version"]
        },
    )
    assert human_takeover.status_code == 200, human_takeover.text
    suggestion = client.post(
        (
            "/api/v1/customer-service/conversations/"
            f"{human_conversation.json()['id']}/reply-suggestions"
        ),
        headers=AGENT,
    )
    assert suggestion.status_code == 200, suggestion.text
    assert suggestion.json()["text"]
    assert suggestion.json()["citations"][0]["title"] == "保温杯售前参数"
    assert (
        suggestion.json()["skill"] == "ecommerce-aftersales"
    ), suggestion.json()["trace"]
    assert suggestion.json()["trace"] == [
        "route_skill → ecommerce-aftersales",
        "retrieve_knowledge → 1 条知识",
        "generate_reply → local/local-keyword-v1",
    ]

    with SessionLocal() as session:
        turn = session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.ticket_id == UUID(ticket_id))
            .order_by(ConversationTurn.sequence.desc())
            .limit(1)
        )
        assert turn is not None
        assert turn.status == "COMPLETED"
        assert turn.response_provider in {"local", "openai_compatible"}


def test_ecommerce_listing_closed_loop(client: TestClient) -> None:
    _create_rules(client)
    owners = _create_operation_owner_employees()
    product = _create_product(client, sku="DEMO-CUP-001", name="便携保温杯")
    asset = _upload_cover(client, str(product["id"]))
    assert asset["owner_employee_id"] == owners["visual"]

    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )

    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "PENDING_REVIEW"
    assert task["risk_level"] == "R1"
    assert task["owner_employee_id"] == owners["listing"]
    assert task["content"]["title"]
    assert task["content"]["short_video_script"]
    assert task["citations"]

    exported = client.get(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/export",
        headers=AGENT,
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        names = set(archive.namelist())
        assert "listing.json" in names
        assert "README.txt" in names
        assert any(name.startswith("assets/images/") for name in names)
        manifest = json.loads(archive.read("listing.json"))
        assert manifest["product"]["sku"] == "DEMO-CUP-001"
        assert manifest["task"]["market_code"] == "CN"
        assert manifest["task"]["currency"] == "CNY"

    storyboard = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/generate",
        headers=AGENT,
    )
    assert storyboard.status_code == 201, storyboard.text
    storyboard_assets = storyboard.json()["items"]
    assert len(storyboard_assets) == 3
    assert [asset["metadata"]["scene_index"] for asset in storyboard_assets] == [
        1,
        2,
        3,
    ]
    assert {
        asset["metadata"]["listing_task_id"] for asset in storyboard_assets
    } == {task["id"]}

    regenerated = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/generate",
        headers=AGENT,
    )
    assert regenerated.status_code == 201, regenerated.text
    regenerated_assets = regenerated.json()["items"]
    assert {asset["id"] for asset in regenerated_assets}.isdisjoint(
        {asset["id"] for asset in storyboard_assets}
    )
    active_assets = client.get(
        f"/api/v1/ecommerce/products/{product['id']}/assets",
        headers=AGENT,
    ).json()
    active_storyboards = [
        asset
        for asset in active_assets
        if asset["metadata"].get("source") == "STORYBOARD_GENERATED"
    ]
    assert len(active_storyboards) == 3
    assert {
        asset["metadata"]["generation_id"] for asset in active_storyboards
    } == {regenerated_assets[0]["metadata"]["generation_id"]}

    video = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/video",
        headers=AGENT,
    )
    assert video.status_code == 201, video.text
    assert video.json()["asset_type"] == "VIDEO"
    assert video.json()["metadata"]["resolution"] == "1080x1920"
    assert video.json()["metadata"]["scene_count"] == 3
    assert video.json()["metadata"]["duration_seconds"] == 15.0

    reviewed = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/reviews",
        headers=AGENT,
        json={
            "expected_version": task["version"],
            "decision": "ACCEPTED",
            "reason_code": "ECOMMERCE_APPROVED",
        },
    )

    assert reviewed.status_code == 200, reviewed.text
    detail = client.get(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}",
        headers=AGENT,
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "PUBLISHED"
    assert detail.json()["external_listing_id"].startswith("LOCAL-")

    metrics = client.get(
        "/api/v1/ecommerce/metrics?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert metrics.status_code == 200, metrics.text
    values = metrics.json()
    assert values["total_listings"] == 1
    assert values["published"] == 1
    assert values["publication_success_rate"] == 1.0
    assert values["average_publish_seconds"] is not None
    assert values["market_breakdown"] == {"CN": 1}


def test_ecommerce_video_render_job_closed_loop(client: TestClient) -> None:
    _create_rules(client)
    product = _create_product(client, sku="DEMO-VIDEO-001", name="便携视频杯")
    _upload_cover(client, str(product["id"]))
    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    storyboard = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/generate",
        headers=AGENT,
    )
    assert storyboard.status_code == 201, storyboard.text

    music = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets?filename=bgm.wav",
        headers={**AGENT, "Content-Type": "audio/wav"},
        content=_silence_wav(),
    )
    assert music.status_code == 201, music.text
    assert music.json()["asset_type"] == "AUDIO"
    assert music.json()["metadata"]["asset_role"] == "BACKGROUND_MUSIC"

    submitted = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/video-jobs",
        headers=AGENT,
        json={
            "background_music_asset_id": music.json()["id"],
            "background_music_volume": 0.2,
        },
    )
    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["background_music_asset_id"] == music.json()["id"]
    assert submitted.json()["background_music_volume"] == 0.2
    job_id = submitted.json()["id"]
    assert submitted.json()["status"] == "QUEUED"

    completed = client.get(
        f"/api/v1/ecommerce/video-render-jobs/{job_id}",
        headers=AGENT,
    )
    assert completed.status_code == 200, completed.text
    job = completed.json()
    assert job["status"] == "SUCCEEDED"
    assert job["progress"] == 100
    assert job["scene_count"] == 3
    assert job["duration_seconds"] == 15.0
    assert job["asset_id"]

    listed = client.get(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/video-render-jobs",
        headers=AGENT,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["id"] == job_id

    asset = client.get(
        f"/api/v1/ecommerce/assets/{job['asset_id']}/content",
        headers=AGENT,
    )
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "video/mp4"
    assert len(asset.content) > 1024
    rendered_assets = client.get(
        f"/api/v1/ecommerce/products/{product['id']}/assets",
        headers=AGENT,
    ).json()
    video_asset = next(
        item for item in rendered_assets if item["id"] == job["asset_id"]
    )
    subtitle_id = video_asset["metadata"]["subtitle_asset_id"]
    subtitle_asset = next(
        item for item in rendered_assets if item["id"] == subtitle_id
    )
    assert subtitle_asset["asset_type"] == "SUBTITLE"
    assert subtitle_asset["metadata"]["cue_count"] == 3
    subtitle_content = client.get(
        f"/api/v1/ecommerce/assets/{subtitle_id}/content",
        headers=AGENT,
    )
    assert subtitle_content.status_code == 200
    assert subtitle_content.headers["content-type"].startswith("text/vtt")
    assert subtitle_content.text.startswith("WEBVTT")
    assert "00:00:08.000 --> 00:00:15.000" in subtitle_content.text

    not_retryable = client.post(
        f"/api/v1/ecommerce/video-render-jobs/{job_id}/retry",
        headers=AGENT,
    )
    assert not_retryable.status_code == 409

    with SessionLocal() as session:
        stored_job = session.get(EcommerceVideoRenderJob, UUID(job_id))
        assert stored_job is not None
        stored_job.status = "FAILED"
        stored_job.progress = 70
        stored_job.error_message = "synthetic worker failure"
        session.commit()

    retried = client.post(
        f"/api/v1/ecommerce/video-render-jobs/{job_id}/retry",
        headers=AGENT,
    )
    assert retried.status_code == 202, retried.text
    retried_job = client.get(
        f"/api/v1/ecommerce/video-render-jobs/{job_id}",
        headers=AGENT,
    ).json()
    assert retried_job["status"] == "SUCCEEDED"
    assert retried_job["retry_count"] == 1
    assert retried_job["error_message"] is None

    metrics = client.get(
        "/api/v1/ecommerce/metrics?business_unit_id=bu_demo",
        headers=AGENT,
    ).json()
    assert metrics["video_jobs"] == 1
    assert metrics["video_succeeded"] == 1
    assert metrics["video_failed"] == 0
    assert metrics["video_active"] == 0
    assert metrics["video_success_rate"] == 1.0
    assert metrics["average_render_seconds"] is not None


def test_video_render_blocks_storyboards_with_visual_issues(
    client: TestClient,
) -> None:
    _create_rules(client)
    product = _create_product(client, sku="DEMO-VISUAL-001", name="视觉审核商品")
    _upload_cover(client, str(product["id"]))
    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    storyboard = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/generate",
        headers=AGENT,
    )
    assert storyboard.status_code == 201, storyboard.text

    with SessionLocal() as session:
        asset = session.get(
            EcommerceProductAsset,
            UUID(storyboard.json()["items"][0]["id"]),
        )
        assert asset is not None
        metadata = dict(asset.metadata_json)
        metadata["visual_audit_status"] = "NEEDS_REVIEW"
        metadata["visual_audit_text"] = "unexpected text"
        asset.metadata_json = metadata
        session.commit()

    blocked = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/video-jobs",
        headers=AGENT,
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "STORYBOARD_VISUAL_REVIEW_REQUIRED"

    accepted = client.post(
        (
            f"/api/v1/ecommerce/assets/"
            f"{storyboard.json()['items'][0]['id']}/visual-review/accept"
        ),
        headers=AGENT,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["metadata"]["visual_audit_status"] == "ACCEPTED"
    assert accepted.json()["metadata"]["visual_reviewed_by"] == "ecommerce-agent"

    resumed = client.post(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/storyboard/video-jobs",
        headers=AGENT,
    )
    assert resumed.status_code == 202, resumed.text
    completed = client.get(
        f"/api/v1/ecommerce/video-render-jobs/{resumed.json()['id']}",
        headers=AGENT,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "SUCCEEDED"


def test_ecommerce_listing_batch_job_closed_loop(
    client: TestClient,
) -> None:
    _create_rules(client)
    first = _create_product(client, sku="BATCH-001", name="批量商品一")
    second = _create_product(client, sku="BATCH-002", name="批量商品二")
    _upload_cover(client, str(first["id"]))
    _upload_cover(client, str(second["id"]))

    submitted = client.post(
        "/api/v1/ecommerce/listing-batch-jobs",
        headers=AGENT,
        json={
            "product_ids": [first["id"], second["id"]],
            "channel": "local_shop",
            "market_code": "CN",
        },
    )
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["id"]
    completed = client.get(
        f"/api/v1/ecommerce/listing-batch-jobs/{job_id}",
        headers=AGENT,
    )
    assert completed.status_code == 200, completed.text
    job = completed.json()
    assert job["status"] == "SUCCEEDED"
    assert job["total_count"] == 2
    assert job["succeeded_count"] == 2
    assert job["failed_count"] == 0
    assert len(job["items"]) == 2
    assert all(item["listing_task_id"] for item in job["items"])

    listed = client.get(
        "/api/v1/ecommerce/listing-batch-jobs?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == job_id


def test_ecommerce_restricted_claim_goes_to_human(client: TestClient) -> None:
    _create_rules(client)
    product = _create_product(
        client,
        sku="DEMO-RISK-001",
        name="国家级认证保温杯",
    )
    _upload_cover(client, str(product["id"]))

    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "NEEDS_HUMAN"
    assert created.json()["risk_level"] == "R2"
    assert created.json()["human_reason"] == "RESTRICTED_CLAIM"
    assert "国家级" in created.json()["compliance"]["restricted_claims"]


def test_cross_border_us_listing_localization_and_readiness(
    client: TestClient,
) -> None:
    _create_us_rules(client)
    product = _create_product(
        client,
        sku="DEMO-US-CUP-001",
        name="便携保温杯",
        attributes={
            "material": "316 stainless steel",
            "capacity": "480 ml",
            "hs_code": "961700",
            "origin_country": "CN",
            "weight_kg": 0.42,
            "package_dimensions_cm": {
                "length": 8,
                "width": 8,
                "height": 24,
            },
            "localizations": {
                "en-US": {
                    "name": "Portable Insulated Tumbler",
                    "category": "Home & Kitchen",
                    "selling_points": [
                        "Keeps drinks hot or cold on the go.",
                        "Compact 480 ml design for daily commuting.",
                    ],
                }
            },
        },
    )
    _upload_cover(client, str(product["id"]))

    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={
            "product_id": product["id"],
            "channel": "local_shop",
            "market_code": "US",
            "sale_price": 19.99,
        },
    )

    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "PENDING_REVIEW"
    assert task["market_code"] == "US"
    assert task["locale"] == "en-US"
    assert task["currency"] == "USD"
    assert task["sale_price"] == 19.99
    assert "Portable Insulated Tumbler" in task["content"]["title"]
    assert task["content"]["locale"] == "en-US"
    assert task["content"]["short_video_script"][0]["line"] == "Meet the product"
    assert task["compliance"]["market_code"] == "US"
    assert task["compliance"]["required_attributes_missing"] == []


def test_cross_border_us_listing_requires_price_and_local_data(
    client: TestClient,
) -> None:
    _create_us_rules(client)
    product = _create_product(
        client,
        sku="DEMO-US-INCOMPLETE-001",
        name="未本地化商品",
    )
    _upload_cover(client, str(product["id"]))

    missing_price = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={
            "product_id": product["id"],
            "channel": "local_shop",
            "market_code": "US",
        },
    )
    assert missing_price.status_code == 422
    assert missing_price.json()["code"] == "MARKET_PRICE_REQUIRED"

    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={
            "product_id": product["id"],
            "channel": "local_shop",
            "market_code": "US",
            "sale_price": 9.99,
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "NEEDS_HUMAN"
    assert task["risk_level"] == "R2"
    assert task["human_reason"] == "LOCALIZED_CONTENT_MISSING"
    missing = set(task["compliance"]["required_attributes_missing"])
    assert {
        "localized_content",
        "hs_code",
        "origin_country",
        "weight_kg",
        "package_dimensions_cm",
    } <= missing


def test_pinduoduo_snow_boots_attribute_check(
    client: TestClient,
) -> None:
    _create_pinduoduo_rules(client)
    complete_product = _create_product(
        client,
        sku="PDD-SNOW-001",
        name="加绒保暖雪地靴",
        attributes={
            "color": "米白色",
            "size_range": "35-40",
            "upper_material": "牛剖层革",
            "lining_material": "短毛绒",
            "sole_material": "橡胶",
            "heel_height_cm": 3,
            "shaft_height_cm": 18,
            "closure": "套筒",
            "gender": "女",
            "season": "秋冬",
            "stock": 100,
        },
    )
    _upload_cover(client, str(complete_product["id"]))
    complete = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={
            "product_id": complete_product["id"],
            "channel": "pinduoduo_sandbox",
        },
    )
    assert complete.status_code == 201, complete.text
    assert complete.json()["status"] == "PENDING_REVIEW"
    assert (
        complete.json()["compliance"][
            "channel_required_attributes_missing"
        ]
        == []
    )

    incomplete_product = _create_product(
        client,
        sku="PDD-SNOW-002",
        name="雪地靴",
        attributes={"color": "黑色", "size_range": "36-39"},
    )
    _upload_cover(client, str(incomplete_product["id"]))
    incomplete = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={
            "product_id": incomplete_product["id"],
            "channel": "pinduoduo_sandbox",
        },
    )
    assert incomplete.status_code == 201, incomplete.text
    task = incomplete.json()
    assert task["status"] == "NEEDS_HUMAN"
    assert task["risk_level"] == "R2"
    assert task["human_reason"] == "PINDUODUO_ATTRIBUTES_MISSING"
    assert {
        "upper_material",
        "lining_material",
        "sole_material",
        "heel_height_cm",
        "shaft_height_cm",
        "closure",
        "gender",
        "season",
        "stock",
    } <= set(task["compliance"]["channel_required_attributes_missing"])


def test_pinduoduo_connection_reports_missing_credentials(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/ecommerce/channels/pinduoduo/test",
        headers=AGENT,
    )

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["success"] is False


def test_pinduoduo_product_csv_preview_and_import(
    client: TestClient,
) -> None:
    csv_text = (
        "sku,name,category,brand,price,stock,color,size_range,"
        "upper_material,lining_material,sole_material,heel_height_cm,"
        "shaft_height_cm,closure,gender,season,origin_country,hs_code,"
        "weight_kg,package_length_cm,package_width_cm,package_height_cm\n"
        "CSV-SNOW-001,加绒雪地靴,雪地靴,示例品牌,129,100,米白色,35-40,"
        "牛剖层革,短毛绒,橡胶,3,18,套筒,女,秋冬,CN,640399,0.85,32,24,13\n"
        "CSV-SNOW-002,缺资料雪地靴,雪地靴,示例品牌,99,20,黑色,36-40,"
        "牛剖层革,,橡胶,2,16,套筒,女,秋冬,,,0.8,30,20,12\n"
    ).encode()

    preview = client.post(
        "/api/v1/ecommerce/products/import/preview?business_unit_id=bu_demo",
        headers={**AGENT, "Content-Type": "text/csv"},
        content=csv_text,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_rows"] == 2
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["invalid_rows"] == 1
    invalid_row = next(
        row for row in preview.json()["rows"] if not row["valid"]
    )
    assert "lining_material is required" in invalid_row["errors"]

    imported = client.post(
        "/api/v1/ecommerce/products/import?business_unit_id=bu_demo",
        headers={**ADMIN, "Content-Type": "text/csv"},
        content=csv_text,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created_count"] == 1
    assert imported.json()["skipped_count"] == 1
    assert imported.json()["products"][0]["sku"] == "CSV-SNOW-001"
    assert imported.json()["products"][0]["category"] == "雪地靴"

    duplicate = client.post(
        "/api/v1/ecommerce/products/import/preview?business_unit_id=bu_demo",
        headers={**AGENT, "Content-Type": "text/csv"},
        content=csv_text,
    )
    duplicate_row = next(
        row for row in duplicate.json()["rows"] if row["sku"] == "CSV-SNOW-001"
    )
    assert "sku already exists" in " ".join(duplicate_row["errors"])


def test_ecommerce_listing_content_edit_and_recheck(
    client: TestClient,
) -> None:
    _create_rules(client)
    product = _create_product(
        client,
        sku="DEMO-EDIT-001",
        name="可编辑保温杯",
    )
    _upload_cover(client, str(product["id"]))
    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )
    assert created.status_code == 201, created.text
    task = created.json()

    edited = client.patch(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/content",
        headers=AGENT,
        json={
            "expected_version": task["version"],
            "title": "轻量便携保温杯 480ml",
            "selling_points": [
                "316 不锈钢内胆",
                "480ml 日常容量",
                "适合通勤携带",
            ],
            "detail_description": "轻量杯身搭配旋盖设计，适合日常通勤使用。",
            "hashtags": ["保温杯", "通勤好物"],
        },
    )
    assert edited.status_code == 200, edited.text
    edited_task = edited.json()
    assert edited_task["version"] == task["version"] + 1
    assert edited_task["status"] == "PENDING_REVIEW"
    assert edited_task["content"]["title"] == "轻量便携保温杯 480ml"
    assert edited_task["content"]["selling_points"][0] == "316 不锈钢内胆"

    restricted = client.patch(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/content",
        headers=AGENT,
        json={
            "expected_version": edited_task["version"],
            "title": "国家级认证保温杯",
            "selling_points": ["绝对安全"],
            "detail_description": "人工编辑后重新执行合规检查。",
            "hashtags": [],
        },
    )
    assert restricted.status_code == 200, restricted.text
    restricted_task = restricted.json()
    assert restricted_task["status"] == "NEEDS_HUMAN"
    assert restricted_task["risk_level"] == "R2"
    assert restricted_task["human_reason"] == "RESTRICTED_CLAIM"
    assert "国家级" in restricted_task["compliance"]["restricted_claims"]

    stale = client.patch(
        f"/api/v1/ecommerce/listing-tasks/{task['id']}/content",
        headers=AGENT,
        json={
            "expected_version": task["version"],
            "title": "过期版本编辑",
            "selling_points": ["测试"],
            "detail_description": "该请求应被版本冲突拒绝。",
            "hashtags": [],
        },
    )
    assert stale.status_code == 409


def test_ecommerce_listing_requires_product_image(client: TestClient) -> None:
    _create_rules(client)
    product = _create_product(client, sku="DEMO-NO-IMAGE-001", name="缺少主图商品")

    created = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["status"] == "NEEDS_HUMAN"
    assert created.json()["human_reason"] == "MISSING_PRODUCT_IMAGE"
    assert created.json()["compliance"]["missing_product_image"] is True


def test_ecommerce_product_asset_upload_and_download(
    client: TestClient,
) -> None:
    product = _create_product(client, sku="DEMO-ASSET-001", name="素材测试商品")

    uploaded = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets?filename=cover.png",
        headers={**AGENT, "Content-Type": "image/png"},
        content=TINY_PNG,
    )

    assert uploaded.status_code == 201, uploaded.text
    asset = uploaded.json()
    assert asset["asset_type"] == "IMAGE"
    assert asset["size_bytes"] == len(TINY_PNG)
    assert asset["metadata"]["width"] == 1
    assert asset["metadata"]["height"] == 1

    listed = client.get(
        (
            f"/api/v1/ecommerce/products/{product['id']}/assets"
            "?business_unit_id=bu_demo"
        ),
        headers=AGENT,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == asset["id"]

    content = client.get(
        f"/api/v1/ecommerce/assets/{asset['id']}/content",
        headers=AGENT,
    )
    assert content.status_code == 200
    assert content.content == TINY_PNG
    assert content.headers["content-type"].startswith("image/png")


def test_ecommerce_generated_image_is_saved_as_asset(
    client: TestClient,
) -> None:
    product = _create_product(client, sku="DEMO-GENERATE-001", name="AI 主图商品")

    generated = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets/generate",
        headers=AGENT,
        json={"prompt": "奶油白色产品，柔和棚拍光，简洁电商主图"},
    )

    assert generated.status_code == 201, generated.text
    asset = generated.json()
    assert asset["asset_type"] == "IMAGE"
    assert asset["metadata"]["source"] == "AI_GENERATED"
    assert asset["metadata"]["generator_provider"] == "local"
    assert asset["metadata"]["width"] == 512
    assert asset["metadata"]["height"] == 512


def test_ecommerce_generates_candidates_and_selects_primary(
    client: TestClient,
) -> None:
    _create_rules(client)
    product = _create_product(client, sku="DEMO-CANDIDATE-001", name="候选图商品")

    generated = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets/generate-batch",
        headers=AGENT,
        json={"prompt": "简洁电商主图，柔和棚拍光", "count": 3},
    )

    assert generated.status_code == 201, generated.text
    assets = generated.json()["items"]
    assert len(assets) == 3
    assert len({asset["metadata"]["sha256"] for asset in assets}) == 3
    assert all(asset["metadata"]["quality_score"] >= 0.85 for asset in assets)

    primary = client.post(
        f"/api/v1/ecommerce/assets/{assets[1]['id']}/primary",
        headers=AGENT,
    )
    assert primary.status_code == 200, primary.text
    assert primary.json()["metadata"]["is_primary"] is True

    listed = client.get(
        (
            f"/api/v1/ecommerce/products/{product['id']}/assets"
            "?business_unit_id=bu_demo"
        ),
        headers=AGENT,
    )
    primary_ids = [
        asset["id"] for asset in listed.json() if asset["metadata"].get("is_primary")
    ]
    assert primary_ids == [assets[1]["id"]]

    listing = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    )
    assert listing.status_code == 201, listing.text
    assert listing.json()["content"]["primary_image_asset_id"] == assets[1]["id"]

    usage = client.get(
        "/api/v1/ecommerce/image-generations?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert usage.status_code == 200, usage.text
    latest = usage.json()["items"][0]
    assert latest["requested_count"] == 3
    assert latest["succeeded_count"] == 3
    assert latest["status"] == "SUCCEEDED"
    assert latest["provider"] == "local"
    assert usage.json()["total_images"] >= 3


def test_ecommerce_asset_archive_and_publish_retry(
    client: TestClient,
) -> None:
    _create_rules(client)
    product = _create_product(client, sku="DEMO-ARCHIVE-001", name="归档测试商品")
    asset = _upload_cover(client, str(product["id"]))
    assert (
        client.post(
            f"/api/v1/ecommerce/assets/{asset['id']}/primary",
            headers=AGENT,
        ).status_code
        == 200
    )

    archived = client.post(
        f"/api/v1/ecommerce/assets/{asset['id']}/archive",
        headers=AGENT,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"
    assert archived.json()["metadata"]["is_primary"] is False

    active = client.get(
        (
            f"/api/v1/ecommerce/products/{product['id']}/assets"
            "?business_unit_id=bu_demo"
        ),
        headers=AGENT,
    )
    assert active.json() == []
    all_assets = client.get(
        (
            f"/api/v1/ecommerce/products/{product['id']}/assets"
            "?business_unit_id=bu_demo&include_archived=true"
        ),
        headers=AGENT,
    )
    assert all_assets.json()[0]["status"] == "ARCHIVED"

    _upload_cover(client, str(product["id"]))
    listing = client.post(
        "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
        headers=AGENT,
        json={"product_id": product["id"], "channel": "local_shop"},
    ).json()
    with SessionLocal() as session:
        task = session.get(EcommerceListingTask, UUID(listing["id"]))
        assert task is not None
        task.status = "FAILED"
        task.error_message = "channel unavailable"
        task.version += 1
        failed_version = task.version
        session.commit()

    retried = client.post(
        f"/api/v1/ecommerce/listing-tasks/{listing['id']}/retry",
        headers=AGENT,
        json={
            "expected_version": failed_version,
            "reason_code": "SANDBOX_RETRY",
        },
    )
    assert retried.status_code == 202, retried.text
    detail = client.get(
        f"/api/v1/ecommerce/listing-tasks/{listing['id']}",
        headers=AGENT,
    )
    assert detail.json()["status"] == "PUBLISHED"
