import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

TEST_DATABASE_DIR = Path(
    tempfile.mkdtemp(prefix=f"ticket-agent-tests-{os.getpid()}-")
)
TEST_DATABASE = TEST_DATABASE_DIR / "test_ticket_agent.db"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE}"
os.environ["APP_AUTH_MODE"] = "dev"
os.environ["TASK_MODE"] = "inline"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["ECOMMERCE_CONTENT_PROVIDER"] = "local"
os.environ["ECOMMERCE_IMAGE_PROVIDER"] = "local"
os.environ["ECOMMERCE_VISUAL_AUDIT_PROVIDER"] = "none"
os.environ["ECOMMERCE_TTS_PROVIDER"] = "none"
os.environ["ECOMMERCE_SUBTITLE_BURN_IN"] = "false"
# 本机 .env 可能为联调配置了真实 MODEL_* / QUERY_REWRITE_*，测试必须隔离为
# 本地确定性模型；环境变量优先级高于 env_file，可统一中和。
os.environ["MODEL_PROVIDER"] = "local"
os.environ["MODEL_BASE_URL"] = ""
os.environ["MODEL_NAME"] = ""
os.environ["MODEL_API_KEY"] = ""
os.environ["QUERY_REWRITE_BASE_URL"] = ""
os.environ["QUERY_REWRITE_API_KEY"] = ""
os.environ["QUERY_REWRITE_MODEL_NAME"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from ticket_agent.main import app  # noqa: E402
from ticket_agent.shared.db import Base, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database() -> Generator[None, None, None]:
    yield
    shutil.rmtree(TEST_DATABASE_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def ticket_payload() -> dict[str, object]:
    return {
        "business_unit_id": "bu_demo",
        "source": {
            "system": "demo_helpdesk",
            "channel": "web_form",
            "external_ticket_id": "HD-001",
        },
        "requester": {
            "external_ref": "customer_001",
            "customer_tier": "standard",
        },
        "subject": "如何配置企业通知",
        "body": "请问管理员如何为团队配置消息通知？",
        "locale": "zh-CN",
        "attachments": [],
        "metadata": {"product": "admin_portal"},
    }

