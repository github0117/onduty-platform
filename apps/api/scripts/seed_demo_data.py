#!/usr/bin/env python3
import json
import struct
import sys
import time
import zlib
from collections.abc import Callable
from typing import Any

import httpx

BUSINESS_UNIT = "bu_demo"
ADMIN = {"X-Actor-Id": "demo-admin", "X-Actor-Role": "admin"}
AGENT = {"X-Actor-Id": "demo-agent", "X-Actor-Role": "agent"}
# 商品上架审核需要 ecommerce.operate，只有主管和管理员具备。
SUPERVISOR = {"X-Actor-Id": "demo-supervisor", "X-Actor-Role": "supervisor"}
DEMO_CUSTOMER_EMPLOYEE_KEY = "demo_vacuum_cup_customer_service"
DEMO_HR_EMPLOYEE_KEY = "demo_hr_onboarding"
DEMO_DEVELOPER_EMPLOYEE_KEY = "demo_developer_support"
ENTERPRISE_TEMPLATE_CODE = "enterprise_service_desk"
ENTERPRISE_ROUTE_INTENTS = [
    "企业服务",
    "制度",
    "流程",
    "通知",
    "账号",
    "登录",
    "密码",
    "权限",
    "IT",
    "邮箱",
    "报销",
    "发票",
    "费用",
    "财务",
    "会议室",
    "门禁",
    "工位",
    "办公用品",
    "VPN",
    "故障",
    "报错",
    "连不上",
]
HR_ROUTE_INTENTS = [
    "入职",
    "转正",
    "离职",
    "假期",
    "年假",
    "请假",
    "考勤",
    "人事",
    "HR",
]
ENTERPRISE_ROUTE_TUNING_CASES = {
    "enterprise": [
        ("报销需要准备哪些发票？", "财务与费用"),
        ("发票抬头在哪里修改？", "财务与费用"),
        ("办公室 VPN 连不上怎么办？", "IT 与账号"),
        ("企业邮箱密码怎么重置？", "IT 与账号"),
        ("财务系统权限怎么申请？", "IT 与账号"),
        ("会议室怎么预订？", "行政与设施"),
        ("门禁卡丢了怎么补办？", "行政与设施"),
        ("工位调整需要找谁？", "行政与设施"),
        ("办公用品在哪里申领？", "行政与设施"),
        ("报销费用提交后多久到账？", "财务与费用"),
        ("系统登录报错提示无权限怎么办？", "IT 与账号"),
        ("公司通知在哪里查看？", "制度与通知"),
    ],
    "developer": [
        ("GitHub 公开仓库怎么查？", "仓库与文档"),
        ("项目文档在哪里看？", "仓库与文档"),
        ("这个模块的依赖关系怎么查？", "代码与依赖"),
        ("代码结构说明在哪里？", "代码与依赖"),
        ("SDK 的接入文档怎么找？", "仓库与文档"),
        ("MCP 连接器如何配置？", "代码与依赖"),
        ("研发支持能查私有仓库吗？", "安全边界"),
        ("请帮我找 GitHub 上的项目文档", "仓库与文档"),
        ("仓库的模块划分是怎样的？", "代码与依赖"),
        ("SDK 版本和依赖关系在哪查？", "代码与依赖"),
        ("代码结构文档能直接引用吗？", "安全边界"),
        ("研发问题应该找谁支持？", "研发支持"),
    ],
    "hr": [
        ("入职材料需要准备什么？", "入职"),
        ("入职当天需要带哪些证件？", "入职"),
        ("转正申请什么时候提交？", "转正"),
        ("年假余额在哪里查询？", "假期"),
        ("请假需要提前几天申请？", "假期"),
        ("考勤记录有误怎么更正？", "考勤"),
        ("人事证明怎么开具？", "人事"),
        ("HR 的联系方式在哪里查？", "人事"),
        ("入职资料可以线上提交吗？", "入职"),
        ("年假可以跨年使用吗？", "假期"),
        ("转正需要哪些材料？", "转正"),
        ("离职手续需要提前多久办理？", "离职"),
    ],
}
# Holdout questions were written after the tuning set and are never used to
# adjust route rules. They deliberately include paraphrases that the current
# keyword/synonym matcher may miss, so the reported accuracy stays honest.
ENTERPRISE_ROUTE_HOLDOUT_CASES = {
    "enterprise": [
        ("公司制度文件在哪里可以查到？", "制度与通知"),
        ("出差费用的报销标准是多少？", "财务与费用"),
        ("企业邮箱收不到外部邮件怎么办？", "IT 与账号"),
        ("申请系统权限需要找哪个部门审批？", "IT 与账号"),
        ("办公室门禁失灵了怎么处理？", "行政与设施"),
        ("VPN 客户端提示认证失败怎么办？", "IT 与账号"),
    ],
    "developer": [
        ("如何申请访问公司的代码仓库？", "仓库与文档"),
        ("多个模块之间的依赖怎么梳理？", "代码与依赖"),
        ("SDK 升级后接口不兼容怎么办？", "代码与依赖"),
        ("MCP 工具调用失败了怎么排查？", "代码与依赖"),
        ("GitHub 上的 issue 怎么关联到内部项目？", "仓库与文档"),
        ("新人研发环境怎么配置？", "研发支持"),
    ],
    "hr": [
        ("新员工第一周需要完成哪些手续？", "入职"),
        ("试用期结束前多久提交转正材料？", "转正"),
        ("想请三天事假应该走什么流程？", "假期"),
        ("考勤打卡漏了一次怎么补？", "考勤"),
        ("离职证明什么时候能拿到？", "离职"),
        ("人事政策文件在哪里下载？", "人事"),
    ],
}
BUSINESS_SANDBOX_CONNECTOR_CODE = "demo-business-sandbox"
DEEPWIKI_CONNECTOR_CODE = "deepwiki-public"
CUSTOMER_SERVICE_ENTRY_CODE = "ecommerce_customer_service"
ENTERPRISE_SERVICE_ENTRY_CODE = "enterprise_service_desk"
DEMO_EMPLOYEE_INSTRUCTIONS = {
    "customer": (
        "你是电商客服数字员工。先用简洁中文确认商品或订单信息，再依据已发布知识回答；"
        "涉及退款、改址等资金或地址变更时只说明流程，并转人工审核，不承诺未确认的处理结果。"
    ),
    "enterprise": (
        "你是企业服务台数字员工。先确认员工所在组织和问题类型，再依据已发布制度回答；"
        "账号、权限和费用操作只说明流程，需要人工复核时明确告知，不替员工绕过审批。"
    ),
    "developer": (
        "你是研发支持数字员工。优先查询公开仓库文档并给出可追溯依据；"
        "涉及私有仓库、密钥或访问令牌时拒绝继续，并转人工处理。"
    ),
    "hr": (
        "你是 HR 入职资料数字员工。按清单逐步收集资料并保护个人信息；"
        "遇到敏感信息、缺失材料或政策例外时转人工确认。"
    ),
    "logistics": (
        "你是物流查询数字员工。先用订单号或手机号确认包裹，再依据实时物流工具回答；"
        "只播报已查询到的节点，不推断未返回的时效或赔付结果。"
    ),
    "aftersales": (
        "你是售后处理数字员工。先确认商品、订单号和售后类型，再说明可执行的处理路径；"
        "退款、补发等资金或库存动作必须走审批，不自行承诺处理结果。"
    ),
    "listing": (
        "你是商品上架数字员工。先核对商品资料、类目和必填属性，再生成上架内容；"
        "类目或属性缺失时列出待补项，不编造参数，不直接提交审核。"
    ),
    "visual": (
        "你是视觉内容数字员工。依据商品事实和品牌规范生成视觉方案；"
        "不虚构商品外观或功效，涉及图片版权和对外发布时提示人工确认。"
    ),
    "operations_supervisor": (
        "你是电商运营主管数字员工。汇总商品、上架和视觉任务的进度与异常；"
        "只基于已查询数据给出建议，涉及人群、投放和预算变更时转人工决策。"
    ),
}
BUSINESS_SANDBOX_TOOLS = [
    "get_customer_business_context",
    "get_logistics",
    "change_shipping_address",
    "get_address_change_status",
]
TEST_REQUESTER_PREFIXES = (
    "e2e-",
    "sandbox-buyer-",
    "chat-demo-",
    "enterprise-demo-smoke",
    "approval-live-",
    "policy-live-",
    "route-",
    "mcp-live-",
    "recon-live-",
    "cup-",
    "aftersales-validation",
    "auto-reply-validation",
    "feedback-validation",
    "manual-intervention-validation",
    "qwen-suggestion-validation",
    "auto-suggest-",
    "entry-route-check",
    "ui-ai-check",
    "ui-smoke",
    "business-entry-buyer",
)


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    with httpx.Client(base_url=base_url, timeout=30) as client:
        client.get("/health/ready").raise_for_status()
        _cleanup_test_tickets(client)
        _cleanup_test_conversations(client)
        _disable_test_employees(client)
        _disable_test_knowledge_spaces(client)
        _disable_test_evaluation_cases(client)

        customer_employee = _ensure_customer_employee(client)
        enterprise_employee = _ensure_enterprise_employee(client)
        hr_employee = _ensure_hr_employee(client)
        enterprise_space = _ensure_knowledge_space(
            client,
            code="enterprise_service_policies",
            name="企业服务制度与流程",
            description="企业制度、内部流程、通知配置和跨部门服务规则",
            domain="enterprise_service",
            channel="web_form",
            category="企业服务",
            workflow_key="enterprise_service_ticket_v1",
        )
        customer_space = _ensure_knowledge_space(
            client,
            code="customer_service_sop",
            name="客户服务 SOP 与 FAQ",
            description="客户沟通、问题升级、回复审核和服务记录规范",
            domain="customer_service",
            channel="web_form",
            category="客户服务",
            workflow_key="customer_service_ticket_v1",
        )
        it_space = _ensure_knowledge_space(
            client,
            code="it_access_policies",
            name="IT、账号与权限制度",
            description="企业账号、登录、权限申请和 IT 报障规范",
            domain="it_support",
            channel="web_form",
            category="IT 与权限",
            workflow_key=None,
        )
        finance_space = _ensure_knowledge_space(
            client,
            code="finance_service_policies",
            name="财务退款与发票制度",
            description="退款、发票、费用与财务审核规范",
            domain="finance",
            channel="web_form",
            category="财务与退款",
            workflow_key=None,
        )
        hr_space = _ensure_knowledge_space(
            client,
            code="hr_onboarding_policies",
            name="HR 入职与员工服务",
            description="入职资料、员工服务与人事流程规范",
            domain="hr_service",
            channel="web_form",
            category="人事",
            workflow_key="hr_onboarding_document_collection_v1",
        )
        ecommerce_space = _ensure_knowledge_space(
            client,
            code="ecommerce_demo_channel_rules",
            name="电商平台渠道规则",
            description="电商内容发布、合规宣传和渠道操作规则",
            domain="ecommerce",
            channel="ecommerce_demo",
            category="电商运营",
            workflow_key=None,
        )
        developer_space = _ensure_knowledge_space(
            client,
            code="developer_repository_guidelines",
            name="研发仓库查询规范",
            description="公开仓库文档查询范围、只读工具和安全边界",
            domain="developer_support",
            channel="enterprise_service",
            category="研发支持",
            workflow_key="customer_service_ticket_v1",
        )
        knowledge = [
            _ensure_knowledge(
                client,
                space_id=it_space["id"],
                title="测试数据｜企业账号与 IT 支持指南",
                doc_type="SOP",
                scope={"audiences": ["support_agent"]},
                content=(
                    "员工无法登录企业账号时，先确认账号状态，再通过企业自助入口"
                    "重置密码。仍无法登录时创建 IT 支持工单，并附上错误提示和"
                    "发生时间。账号权限申请需要填写系统名称、所需角色和审批人。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=it_space["id"],
                title="测试数据｜VPN 与 IT 报障处理指南",
                doc_type="SOP",
                scope={"audiences": ["support_agent"]},
                content=(
                    "办公室 VPN 连不上时，先确认当前网络可以访问互联网，并重启"
                    "VPN 客户端后重试。仍然失败时创建 IT 支持工单，附上错误提示、"
                    "发生时间和所在办公区；VPN 账号锁定请联系 IT 服务台解锁。"
                    "会议室投屏故障、邮件收发异常和系统报错同样通过 IT 支持工单处理。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=enterprise_space["id"],
                title="测试数据｜企业通知配置指南",
                doc_type="SOP",
                scope={"audiences": ["support_agent"]},
                content=(
                    "管理员进入后台设置，打开消息通知，选择团队范围和通知渠道，"
                    "确认后保存配置。测试消息应在保存后一分钟内送达。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=finance_space["id"],
                title="测试数据｜退款与发票处理政策",
                doc_type="POLICY",
                scope={"audiences": ["support_agent"]},
                content=(
                    "客户提交退款申请后，客服需核对订单号、支付渠道和退款原因。"
                    "财务审核通过后原路退回，到账时间以支付机构为准。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=enterprise_space["id"],
                title="测试数据｜费用报销与假期申请流程",
                doc_type="SOP",
                scope={"audiences": ["support_agent"]},
                content=(
                    "员工报销费用时，应在费用发生后 30 天内于财务系统提交报销单，"
                    "附上发票和事由，直属主管审批后由财务复核。"
                    "年假和请假需要在 HR 系统提交申请，年假应提前三个工作日申请"
                    "并由直属主管审批。会议室通过企业日历预订，单次连续使用不超过"
                    "四小时；门禁和办公用品在服务台提交申请后由行政处理。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=hr_space["id"],
                title="测试数据｜新员工入职资料清单",
                doc_type="SOP",
                scope={"audiences": ["new_employee", "support_agent"]},
                content=(
                    "新员工需提交身份证明、学历证明、银行卡信息和紧急联系人。"
                    "HR 收到资料后完成完整性与有效期核对。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=customer_space["id"],
                title="测试数据｜客户服务沟通与升级规范",
                doc_type="SOP",
                scope={"audiences": ["service_agent", "supervisor"]},
                content=(
                    "客服接待客户时应先确认身份和问题类型，回答必须引用已发布知识。"
                    "涉及退款、权限、隐私或资金动作时，必须说明原因并转人工审批。"
                    "人工接管后应记录处理结论和外部系统核对结果。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=customer_space["id"],
                title="测试数据｜316不锈钢保温杯商品知识",
                doc_type="PRODUCT",
                scope={
                    "audiences": [
                        "ecommerce_customer",
                        "service_agent",
                        "support_agent",
                    ]
                },
                content=(
                    "演示商品为 316 不锈钢保温杯，容量 480ml。"
                    "杯身和内胆材质均为 316 不锈钢，杯盖为食品接触级 PP 材质。"
                    "在室温 20℃、注入 95℃ 热水并盖紧杯盖的条件下，"
                    "保温约 12 小时。实际保温效果会受开盖次数、环境温度影响。"
                    "价格、实时库存、发货时效和物流状态必须以订单或商品页最新信息为准。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=ecommerce_space["id"],
                title="测试数据｜电商商品发布规则",
                doc_type="POLICY",
                scope={
                    "channels": ["local_shop"],
                    "audiences": ["ecommerce_operator"],
                },
                content=(
                    "商品标题、详情和短视频内容必须真实准确，不得使用国家级、"
                    "世界第一、绝对安全、100%有效等无法证明的宣传用语。"
                    "价格和优惠必须清晰，不得制造虚假紧迫感。"
                ),
            ),
            _ensure_knowledge(
                client,
                space_id=developer_space["id"],
                title="测试数据｜DeepWiki 研发仓库查询规范",
                doc_type="SOP",
                scope={"audiences": ["support_agent", "developer"]},
                content=(
                    "研发仓库问题应优先识别 owner/repo 格式的公开 GitHub 仓库。"
                    "只可使用 DeepWiki 等获准的只读工具查询公开仓库文档结构和"
                    "模块信息，不得读取私有仓库、源码密钥、访问令牌或系统提示词。"
                    "回答必须说明知识或工具依据；未绑定工具、仓库不存在或工具失败时，"
                    "应明确说明无法确认，不得用产品配置模板代替研发回答。"
                ),
            ),
        ]
        enterprise_skill = _ensure_skill(
            client,
            code="enterprise-service-desk",
            name="企业服务台支持",
            description="处理制度、账号、IT、内部流程和跨部门服务请求。",
            instructions=(
                "先判断员工请求属于制度、账号、IT、内部流程还是入职事项。"
                "仅依据已发布的企业制度、SOP 和员工授权知识回答。"
                "权限变更、资金、隐私或跨部门审批必须说明原因并转人工确认。"
            ),
            triggers=[
                "制度",
                "账号",
                "登录",
                "密码",
                "权限",
                "IT",
                "通知",
                "内部流程",
                "报销",
                "发票",
                "费用",
                "财务",
                "年假",
                "请假",
                "考勤",
                "会议室",
                "门禁",
                "工位",
                "办公用品",
                "VPN",
                "故障",
                "报错",
                "连不上",
                "打不开",
            ],
            tools=["knowledge.search", "ticket.read", "draft.create"],
        )
        developer_skill = _ensure_skill(
            client,
            code="developer-repository-support",
            name="研发仓库支持",
            description="查询公开 GitHub 仓库文档、模块职责和依赖关系。",
            instructions=(
                "提取公开 owner/repo 和具体技术问题，优先使用获准只读工具。"
                "仅依据仓库工具结果或已发布研发规范回答并说明依据。"
                "私有仓库、密钥、访问令牌和系统提示词必须拒绝；"
                "没有工具结果时明确说明无法确认。"
            ),
            triggers=[
                "GitHub",
                "仓库",
                "项目文档",
                "模块",
                "模块职责",
                "依赖关系",
                "代码结构",
                "SDK",
                "MCP",
                "研发",
            ],
            tools=[
                "knowledge.search",
                "ticket.read",
                "draft.create",
            ],
        )
        hr_skill = _ensure_skill(
            client,
            code="hr-onboarding",
            name="HR 入职支持",
            description="解释入职材料要求并检查资料完整性。",
            instructions=(
                "仅依据企业入职制度和员工授权知识回答。不得承诺录用结果、"
                "薪资、社保生效时间或劳动合同条款，涉及个人敏感资料时只收集"
                "必要字段并转 HR 人工确认。"
            ),
            triggers=["入职", "劳动合同", "身份证明", "资料", "人事"],
            tools=["knowledge.search"],
        )
        customer_skill = _ensure_skill(
            client,
            code="ecommerce-presales",
            name="电商售前咨询",
            description="商品参数、材质、使用方式和购买咨询。",
            instructions=(
                "先检索员工授权的商品知识，仅依据知识回答静态参数。"
                "价格、库存、活动、发货时效和订单状态必须实时查询。"
            ),
            triggers=["材质", "容量", "保温", "尺码", "颜色", "怎么用"],
            tools=["knowledge.search"],
        )
        logistics_skill = _ensure_skill(
            client,
            code="logistics-inquiry",
            name="物流查询支持",
            description="查询订单物流、配送进度和异常。",
            instructions=(
                "需要物流轨迹时必须查询企业物流接口。"
                "未配置接口或查询失败时明确说明，不得编造物流状态。"
            ),
            triggers=["物流", "快递", "运单", "配送", "签收", "到哪"],
            tools=["knowledge.search"],
        )
        aftersales_skill = _ensure_skill(
            client,
            code="ecommerce-aftersales",
            name="售后处理支持",
            description="处理退货、退款、破损和售后升级。",
            instructions=(
                "仅依据售后制度说明处理条件，核对订单和客户上下文。"
                "退款、补偿、改址等外部写操作必须进入人工审批。"
            ),
            triggers=["退货", "退款", "换货", "破损", "售后", "改地址"],
            tools=["knowledge.search"],
        )
        listing_skill = _ensure_skill(
            client,
            code="ecommerce-listing-operations",
            name="商品上架运营规程",
            description="校验商品资料、平台规则并生成上架内容。",
            instructions=(
                "先检查商品必填属性和图片，再检索平台与品类规则。"
                "生成标题、卖点、详情和标签时必须引用已发布知识；"
                "发布前必须提交人工审核。"
            ),
            triggers=["商品", "上架", "标题", "卖点", "详情", "标签"],
            tools=["knowledge.search", "draft.create"],
        )
        visual_skill = _ensure_skill(
            client,
            code="ecommerce-visual-operations",
            name="视觉内容生产规程",
            description="制作商品主图、分镜、视频和字幕并检查素材质量。",
            instructions=(
                "素材必须基于真实商品资料，不得虚构商品外观或功效。"
                "生成后检查文字、清晰度和品牌一致性，异常素材提交人工确认。"
            ),
            triggers=["主图", "图片", "分镜", "视频", "字幕", "素材"],
            tools=["knowledge.search", "draft.create"],
        )
        operations_supervisor_skill = _ensure_skill(
            client,
            code="ecommerce-operations-supervision",
            name="电商运营质量复核",
            description="汇总运营质量、返工、异常和人工介入情况。",
            instructions=(
                "按商品和上架任务汇总素材、内容和发布结果，"
                "识别返工、失败和成本异常；只提供复核建议，不替代人工最终审批。"
            ),
            triggers=["运营汇总", "质量", "返工", "异常", "成本"],
            tools=["knowledge.search", "draft.create"],
        )
        developer_employee = _ensure_developer_employee(client)
        _ensure_route_rule(
            client,
            developer_employee,
            intents=[
                "GitHub",
                "仓库",
                "项目文档",
                "模块",
                "依赖关系",
                "代码结构",
                "SDK",
                "MCP",
                "研发",
            ],
            priority=10,
        )
        _ensure_employee_knowledge_spaces(
            client,
            developer_employee,
            [developer_space],
        )
        _ensure_employee_skills(
            client,
            developer_employee,
            [developer_skill],
        )
        _ensure_deepwiki_binding(client, developer_employee)
        developer_employee = _ensure_employee_active(
            client,
            developer_employee,
        )
        developer_employee = _ensure_employee_instruction(
            client,
            developer_employee,
            DEMO_EMPLOYEE_INSTRUCTIONS["developer"],
        )
        _ensure_employee_knowledge_spaces(
            client,
            enterprise_employee,
            [
                enterprise_space,
                customer_space,
                it_space,
                finance_space,
            ],
        )
        _ensure_employee_skills(
            client,
            enterprise_employee,
            [enterprise_skill],
        )
        enterprise_employee = _ensure_employee_active(
            client,
            enterprise_employee,
        )
        enterprise_employee = _ensure_employee_instruction(
            client,
            enterprise_employee,
            DEMO_EMPLOYEE_INSTRUCTIONS["enterprise"],
        )
        _ensure_route_rule(
            client,
            enterprise_employee,
            intents=ENTERPRISE_ROUTE_INTENTS,
            priority=100,
        )
        _ensure_employee_knowledge_spaces(
            client,
            customer_employee,
            [customer_space],
        )
        _ensure_employee_skills(
            client,
            customer_employee,
            [customer_skill],
        )
        try:
            _ensure_business_sandbox_binding(client, customer_employee)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(
                "WARNING: optional business sandbox MCP is unavailable; "
                f"continuing demo setup: {type(exc).__name__}",
                file=sys.stderr,
            )
        customer_employee = _ensure_employee_active(
            client,
            customer_employee,
        )
        customer_employee = _ensure_employee_instruction(
            client,
            customer_employee,
            DEMO_EMPLOYEE_INSTRUCTIONS["customer"],
        )
        _ensure_employee_knowledge_spaces(
            client,
            hr_employee,
            [hr_space],
        )
        _ensure_employee_skills(
            client,
            hr_employee,
            [hr_skill],
        )
        hr_employee = _ensure_employee_active(client, hr_employee)
        hr_employee = _ensure_employee_instruction(
            client,
            hr_employee,
            DEMO_EMPLOYEE_INSTRUCTIONS["hr"],
        )
        _ensure_route_rule(
            client,
            hr_employee,
            intents=HR_ROUTE_INTENTS,
            priority=20,
        )
        logistics_employee = _ensure_template_business_employee(
            client,
            template_code="ecommerce_logistics",
            name="物流查询数字员工",
            knowledge_space_ids=[customer_space["id"]],
            skill_ids=[logistics_skill["id"]],
            instruction=DEMO_EMPLOYEE_INSTRUCTIONS["logistics"],
        )
        aftersales_employee = _ensure_template_business_employee(
            client,
            template_code="ecommerce_aftersales",
            name="售后处理数字员工",
            knowledge_space_ids=[customer_space["id"]],
            skill_ids=[aftersales_skill["id"]],
            instruction=DEMO_EMPLOYEE_INSTRUCTIONS["aftersales"],
        )
        listing_employee = _ensure_template_business_employee(
            client,
            template_code="ecommerce_listing_operator",
            name="商品上架数字员工",
            knowledge_space_ids=[customer_space["id"], ecommerce_space["id"]],
            skill_ids=[listing_skill["id"]],
            instruction=DEMO_EMPLOYEE_INSTRUCTIONS["listing"],
        )
        visual_employee = _ensure_template_business_employee(
            client,
            template_code="ecommerce_visual_creator",
            name="视觉内容数字员工",
            knowledge_space_ids=[customer_space["id"], ecommerce_space["id"]],
            skill_ids=[visual_skill["id"]],
            instruction=DEMO_EMPLOYEE_INSTRUCTIONS["visual"],
        )
        operations_supervisor = _ensure_template_business_employee(
            client,
            template_code="ecommerce_operations_supervisor",
            name="电商运营主管数字员工",
            knowledge_space_ids=[customer_space["id"], ecommerce_space["id"]],
            skill_ids=[operations_supervisor_skill["id"]],
            instruction=DEMO_EMPLOYEE_INSTRUCTIONS["operations_supervisor"],
        )
        business_entries = [
            _ensure_business_service_entry(
                client,
                code=CUSTOMER_SERVICE_ENTRY_CODE,
                name="国内电商客服入口",
                description="承接商品咨询、物流查询、售后处理和人工接管。",
                domain="ecommerce",
                channel="web_form",
                default_employee_id=customer_employee["id"],
                fallback_employee_id=customer_employee["id"],
                human_queue_id="ECOMMERCE_SERVICE_HUMAN",
                employee_ids=_ecommerce_entry_employee_ids(
                    client,
                    primary_employee_id=customer_employee["id"],
                    additional_employee_ids=[
                        logistics_employee["id"],
                        aftersales_employee["id"],
                    ],
                ),
            ),
            _ensure_business_service_entry(
                client,
                code=ENTERPRISE_SERVICE_ENTRY_CODE,
                name="企业服务台入口",
                description="承接制度、账号、IT、财务和内部流程请求。",
                domain="enterprise_service",
                channel="enterprise_service",
                default_employee_id=enterprise_employee["id"],
                fallback_employee_id=enterprise_employee["id"],
                human_queue_id="ENTERPRISE_SERVICE_DESK",
                employee_ids=[
                    enterprise_employee["id"],
                    developer_employee["id"],
                    hr_employee["id"],
                ],
            ),
            _ensure_business_service_entry(
                client,
                code="internal_hr_service",
                name="内部 HR 服务入口",
                description="承接入职、转正、离职、假期和人事资料请求。",
                domain="enterprise_service",
                channel="enterprise_service",
                default_employee_id=hr_employee["id"],
                fallback_employee_id=hr_employee["id"],
                human_queue_id="HR_SERVICE_DESK",
                employee_ids=[hr_employee["id"]],
            ),
            _ensure_business_service_entry(
                client,
                code="ecommerce_operations",
                name="国内电商运营入口",
                description="承接商品上架、视觉素材和运营质量复核。",
                domain="ecommerce_operations",
                channel="internal_ops",
                default_employee_id=listing_employee["id"],
                fallback_employee_id=operations_supervisor["id"],
                human_queue_id="ECOMMERCE_OPERATIONS_REVIEW",
                employee_ids=[
                    listing_employee["id"],
                    visual_employee["id"],
                    operations_supervisor["id"],
                ],
            ),
        ]

        enterprise_entry = next(
            item for item in business_entries if item["code"] == ENTERPRISE_SERVICE_ENTRY_CODE
        )
        for dataset, cases in (
            ("TUNING", ENTERPRISE_ROUTE_TUNING_CASES),
            ("HOLDOUT", ENTERPRISE_ROUTE_HOLDOUT_CASES),
        ):
            _ensure_route_evaluation_cases(
                client,
                service_entry_id=enterprise_entry["id"],
                dataset=dataset,
                cases_by_employee={
                    enterprise_employee["id"]: cases["enterprise"],
                    developer_employee["id"]: cases["developer"],
                    hr_employee["id"]: cases["hr"],
                },
            )
            _ensure_route_evaluation_run(
                client,
                service_entry_id=enterprise_entry["id"],
                dataset=dataset,
            )

        pending = _ensure_ticket(
            client,
            idempotency_key="seed:cs:pending:001",
            employee_id=customer_employee["id"],
            external_ticket_id="SEED-CS-PENDING-001",
            requester_ref="seed-customer-001",
            subject="如何为企业团队配置消息通知",
            body="管理员希望开启团队消息通知，并确认测试消息是否正常送达。",
            metadata={"product": "admin_portal", "seed": True},
        )
        pending = _wait_for_ticket(
            client,
            pending["id"],
            lambda item: item["workflow_state"] in {"PENDING_REVIEW", "NEEDS_HUMAN", "COMPLETED"},
        )

        observable = _ensure_ticket(
            client,
            idempotency_key="seed:cs:observable:001",
            employee_id=customer_employee["id"],
            external_ticket_id="SEED-CS-OBSERVABLE-001",
            requester_ref="seed-customer-004",
            subject="如何查询退款处理进度",
            body="客户提交退款后想了解当前处理进度，以及预计多久可以到账。",
            metadata={"product": "admin_portal", "seed": True},
        )
        observable = _wait_for_ticket(
            client,
            observable["id"],
            lambda item: item["workflow_state"] in {"PENDING_REVIEW", "NEEDS_HUMAN", "COMPLETED"},
        )

        high_risk = _ensure_ticket(
            client,
            idempotency_key="seed:cs:risk:001",
            employee_id=customer_employee["id"],
            external_ticket_id="SEED-CS-RISK-001",
            requester_ref="seed-customer-002",
            subject="客户身份信息疑似泄露，请立即冻结账户",
            body=("客户反馈身份证号和银行卡信息被他人看到，要求立即冻结账户并排查数据访问记录。"),
            metadata={"product": "admin_portal", "seed": True},
        )
        high_risk = _wait_for_ticket(
            client,
            high_risk["id"],
            lambda item: item["workflow_state"] in {"NEEDS_HUMAN", "PENDING_REVIEW", "COMPLETED"},
        )

        completed = _ensure_ticket(
            client,
            idempotency_key="seed:cs:completed:001",
            employee_id=customer_employee["id"],
            external_ticket_id="SEED-CS-COMPLETED-001",
            requester_ref="seed-customer-003",
            subject="通知已开启但测试消息未送达",
            body="管理员已经保存通知配置，测试消息超过一分钟仍未送达，请协助排查。",
            metadata={"product": "admin_portal", "seed": True},
        )
        completed = _wait_for_ticket(
            client,
            completed["id"],
            lambda item: item["workflow_state"] in {"PENDING_REVIEW", "NEEDS_HUMAN", "COMPLETED"},
        )
        if completed["workflow_state"] == "PENDING_REVIEW":
            client.post(
                f"/api/v1/tickets/{completed['id']}/reviews",
                headers=AGENT,
                json={
                    "expected_version": completed["version"],
                    "decision": "ACCEPTED",
                    "reason_code": "SEED_COMPLETED",
                },
            ).raise_for_status()
        completed = _wait_for_ticket(
            client,
            completed["id"],
            lambda item: item["workflow_state"] in {"COMPLETED", "NEEDS_HUMAN"},
        )

        hr_ticket = _ensure_ticket(
            client,
            idempotency_key="seed:hr:onboarding:001",
            employee_id=hr_employee["id"],
            external_ticket_id="SEED-HR-ONBOARDING-001",
            requester_ref="seed-new-employee-001",
            subject="新员工入职资料提交",
            body="请问入职需要准备哪些资料？希望本周五前完成资料收集。",
            metadata={"region": "cn-east", "seed": True},
            source_system="hr_portal",
        )
        hr_ticket = _wait_for_ticket(
            client,
            hr_ticket["id"],
            lambda item: item["workflow_state"] in {"PENDING_REVIEW", "NEEDS_HUMAN", "COMPLETED"},
        )

        ecommerce_products = [
            _ensure_ecommerce_product(
                client,
                sku="ECO-CUP-001",
                name="轻量便携保温杯",
                category="家居日用",
                brand="演示生活",
                price=59.9,
                attributes={"容量": "480ml", "材质": "316不锈钢"},
            ),
            _ensure_ecommerce_product(
                client,
                sku="ECO-LAMP-001",
                name="桌面护眼阅读灯",
                category="数码配件",
                brand="演示生活",
                price=129,
                attributes={"色温": "3000-6000K", "调光": "无级调光"},
            ),
            _ensure_ecommerce_product(
                client,
                sku="ECO-RISK-001",
                name="国家级认证不粘锅",
                category="厨房用品",
                brand="演示厨房",
                price=199,
                attributes={"口径": "28cm", "适用": "电磁炉"},
            ),
        ]
        ecommerce_assets = [
            _ensure_product_asset(
                client,
                product=product,
                filename=f"{product['sku'].lower()}-cover.png",
                color=color,
            )
            for product, color in zip(
                ecommerce_products,
                ((24, 122, 132), (241, 154, 56), (178, 72, 63)),
                strict=True,
            )
        ]
        generated_asset = _ensure_generated_image(
            client,
            product=ecommerce_products[1],
            prompt="桌面护眼阅读灯，奶油白背景，柔和棚拍光，简洁电商主图",
        )
        published_listing = _ensure_listing_task(
            client,
            product=ecommerce_products[0],
            channel="local_shop",
        )
        if published_listing["status"] in {"PENDING_REVIEW", "NEEDS_HUMAN"}:
            response = client.post(
                (f"/api/v1/ecommerce/listing-tasks/{published_listing['id']}/reviews"),
                headers=SUPERVISOR,
                json={
                    "expected_version": published_listing["version"],
                    "decision": "ACCEPTED",
                    "reason_code": "SEED_ECOMMERCE_PUBLISHED",
                },
            )
            response.raise_for_status()
        published_listing = _wait_for_listing(
            client,
            published_listing["id"],
            lambda task: task["status"] in {"PUBLISHED", "FAILED"},
        )
        pending_listing = _ensure_listing_task(
            client,
            product=ecommerce_products[1],
            channel="local_shop",
        )
        risk_listing = _ensure_listing_task(
            client,
            product=ecommerce_products[2],
            channel="local_shop",
        )
        owner_backfill = client.post(
            "/api/v1/ecommerce/operations/backfill-employee-owners",
            headers=ADMIN,
            params={"business_unit_id": BUSINESS_UNIT},
        )
        owner_backfill.raise_for_status()

        print(
            json.dumps(
                {
                    "business_unit": BUSINESS_UNIT,
                    "employees": [
                        {
                            "name": enterprise_employee["name"],
                            "workflow": enterprise_employee["workflow_key"],
                        },
                        {
                            "name": customer_employee["name"],
                            "workflow": customer_employee["workflow_key"],
                        },
                        {
                            "name": hr_employee["name"],
                            "workflow": hr_employee["workflow_key"],
                        },
                        {
                            "name": developer_employee["name"],
                            "workflow": developer_employee["workflow_key"],
                        },
                    ],
                    "business_entries": [
                        {
                            "code": item["code"],
                            "name": item["name"],
                            "employees": len(item["employees"]),
                        }
                        for item in business_entries
                    ],
                    "knowledge": knowledge,
                    "tickets": [
                        {
                            "subject": pending["subject"],
                            "workflow": pending["workflow_state"],
                            "id": pending["id"],
                        },
                        {
                            "subject": observable["subject"],
                            "workflow": observable["workflow_state"],
                            "id": observable["id"],
                        },
                        {
                            "subject": high_risk["subject"],
                            "workflow": high_risk["workflow_state"],
                            "risk": high_risk["risk"]["level"],
                            "id": high_risk["id"],
                        },
                        {
                            "subject": completed["subject"],
                            "workflow": completed["workflow_state"],
                            "id": completed["id"],
                        },
                        {
                            "subject": hr_ticket["subject"],
                            "workflow": hr_ticket["workflow_state"],
                            "id": hr_ticket["id"],
                        },
                    ],
                    "ecommerce": {
                        "employee_owner_backfill": owner_backfill.json(),
                        "products": len(ecommerce_products),
                        "assets": len(ecommerce_assets) + 1,
                        "generated_asset": {
                            "id": generated_asset["id"],
                            "provider": generated_asset["metadata"].get("generator_provider"),
                            "width": generated_asset["metadata"].get("width"),
                            "height": generated_asset["metadata"].get("height"),
                        },
                        "published_listing": {
                            "id": published_listing["id"],
                            "status": published_listing["status"],
                            "external_listing_id": published_listing["external_listing_id"],
                        },
                        "pending_listing": {
                            "id": pending_listing["id"],
                            "status": pending_listing["status"],
                        },
                        "risk_listing": {
                            "id": risk_listing["id"],
                            "status": risk_listing["status"],
                            "risk": risk_listing["risk_level"],
                            "reason": risk_listing["human_reason"],
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def _ensure_customer_employee(client: httpx.Client) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    for employee in employees.json():
        if employee["employee_key"] == DEMO_CUSTOMER_EMPLOYEE_KEY:
            return employee
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": DEMO_CUSTOMER_EMPLOYEE_KEY,
            "name": "电商客服数字员工",
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": BUSINESS_UNIT,
            "service_identity": (f"digital_employee.{DEMO_CUSTOMER_EMPLOYEE_KEY}"),
            "handoff_queue": "ECOMMERCE_SERVICE_HUMAN",
            "knowledge_policy": {
                "default_scope": {
                    "channel": "ecommerce_demo",
                    "audience": "ecommerce_customer",
                },
            },
            "model_profile": {},
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "ticket.sync",
            ],
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_enterprise_employee(client: httpx.Client) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    employee = next(
        (
            item
            for item in employees.json()
            if item.get("template_code") == ENTERPRISE_TEMPLATE_CODE
        ),
        None,
    )
    if employee is not None:
        return _ensure_employee_tools(
            client,
            employee,
            ["ticket.read", "knowledge.search", "draft.create", "ticket.sync"],
        )
    response = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "企业服务台数字员工",
            "template_code": ENTERPRISE_TEMPLATE_CODE,
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_ids": [],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "演示环境企业服务台初始化",
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_developer_employee(client: httpx.Client) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    for employee in employees.json():
        if employee["employee_key"] == DEMO_DEVELOPER_EMPLOYEE_KEY:
            return _ensure_employee_tools(
                client,
                employee,
                [
                    "ticket.read",
                    "knowledge.search",
                    "draft.create",
                ],
            )
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": DEMO_DEVELOPER_EMPLOYEE_KEY,
            "name": "研发支持数字员工",
            "version": "1.0.0",
            "scenario_type": "enterprise_service",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": BUSINESS_UNIT,
            "service_identity": (f"digital_employee.{DEMO_DEVELOPER_EMPLOYEE_KEY}"),
            "handoff_queue": "ENTERPRISE_SERVICE_DESK",
            "knowledge_policy": {
                "default_scope": {"audience": "support_agent"},
            },
            "model_profile": {},
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_hr_employee(client: httpx.Client) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    for employee in employees.json():
        if employee["employee_key"] == DEMO_HR_EMPLOYEE_KEY:
            return employee
    response = client.post(
        "/api/v1/digital-employees",
        headers=ADMIN,
        json={
            "employee_key": DEMO_HR_EMPLOYEE_KEY,
            "name": "HR 入职资料数字员工",
            "version": "1.0.0",
            "scenario_type": "hr_onboarding",
            "workflow_key": "hr_onboarding_document_collection_v1",
            "business_unit_id": BUSINESS_UNIT,
            "service_identity": "digital_employee.demo_hr_onboarding",
            "handoff_queue": "HR_SERVICE_DESK",
            "knowledge_policy": {
                "default_scope": {"audience": "new_employee"},
            },
            "model_profile": {},
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
                "employee_profile.read",
                "ticket.sync",
            ],
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_template_business_employee(
    client: httpx.Client,
    *,
    template_code: str,
    name: str,
    knowledge_space_ids: list[str],
    skill_ids: list[str],
    instruction: str,
) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    employee = next(
        (item for item in employees.json() if item.get("template_code") == template_code),
        None,
    )
    if employee is None:
        created = client.post(
            "/api/v1/digital-employees/from-template",
            headers=ADMIN,
            json={
                "name": name,
                "template_code": template_code,
                "business_unit_id": BUSINESS_UNIT,
                "knowledge_space_ids": knowledge_space_ids,
                "skill_ids": skill_ids,
                "mcp_connector_ids": [],
                "model_profile": {},
                "instruction": instruction,
                "change_note": "演示环境业务入口员工池初始化",
            },
        )
        created.raise_for_status()
        employee = created.json()
    else:
        _ensure_employee_knowledge_spaces(
            client,
            employee,
            [{"id": space_id} for space_id in knowledge_space_ids],
        )
        _ensure_employee_skills(
            client,
            employee,
            [{"id": skill_id} for skill_id in skill_ids],
        )
    employee = _ensure_employee_active(client, employee)
    return _ensure_employee_instruction(client, employee, instruction)


def _ensure_employee_active(
    client: httpx.Client,
    employee: dict[str, Any],
) -> dict[str, Any]:
    employees = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    employees.raise_for_status()
    employee = next(item for item in employees.json() if item["id"] == employee["id"])
    if employee["status"] == "ACTIVE":
        return employee
    if employee["status"] in {"TRIAL", "EVALUATION_FAILED"}:
        response = client.post(
            f"/api/v1/digital-employees/{employee['id']}/activate",
            headers=ADMIN,
        )
        response.raise_for_status()
        return response.json()
    response = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"status": "ACTIVE"},
    )
    response.raise_for_status()
    return response.json()


def _ensure_route_rule(
    client: httpx.Client,
    employee: dict[str, Any],
    *,
    intents: list[str],
    priority: int,
) -> None:
    response = client.put(
        f"/api/v1/digital-employees/{employee['id']}/route-rule",
        headers=ADMIN,
        json={
            "intents": intents,
            "categories": [],
            "channels": [],
            "priority": priority,
            "fallback": False,
            "enabled": True,
        },
    )
    response.raise_for_status()


def _ensure_route_evaluation_cases(
    client: httpx.Client,
    *,
    service_entry_id: str,
    dataset: str,
    cases_by_employee: dict[str, list[tuple[str, str]]],
) -> None:
    response = client.get(
        "/api/v1/digital-employee-route-evaluation-cases",
        headers=ADMIN,
        params={
            "business_unit_id": BUSINESS_UNIT,
            "service_entry_id": service_entry_id,
            "dataset": dataset,
        },
    )
    response.raise_for_status()
    existing = {item["question"] for item in response.json()}
    for employee_id, cases in cases_by_employee.items():
        for question, notes in cases:
            if question in existing:
                continue
            created = client.post(
                "/api/v1/digital-employee-route-evaluation-cases",
                headers=ADMIN,
                params={"business_unit_id": BUSINESS_UNIT},
                json={
                    "service_entry_id": service_entry_id,
                    "expected_employee_id": employee_id,
                    "dataset": dataset,
                    "question": question,
                    "notes": notes,
                },
            )
            created.raise_for_status()
            existing.add(question)


def _ensure_route_evaluation_run(
    client: httpx.Client,
    *,
    service_entry_id: str,
    dataset: str,
) -> dict[str, Any]:
    runs = client.get(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=ADMIN,
        params={
            "business_unit_id": BUSINESS_UNIT,
            "service_entry_id": service_entry_id,
            "dataset": dataset,
        },
    )
    runs.raise_for_status()
    existing: list[dict[str, Any]] = runs.json()["items"]
    if existing:
        return existing[0]
    created = client.post(
        "/api/v1/digital-employee-route-evaluation-runs",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
        json={"service_entry_id": service_entry_id, "dataset": dataset},
    )
    created.raise_for_status()
    result: dict[str, Any] = created.json()
    print(
        f"Route evaluation baseline {dataset}: "
        f"{result['passed']}/{result['total']} "
        f"({result['accuracy']:.0%})",
    )
    return result


def _ensure_deepwiki_binding(
    client: httpx.Client,
    employee: dict[str, Any],
) -> None:
    connectors = client.get(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    connectors.raise_for_status()
    connector = next(
        (item for item in connectors.json() if item["code"] == DEEPWIKI_CONNECTOR_CODE),
        None,
    )
    connector_url = "https://mcp.deepwiki.com/mcp"
    if connector is None:
        created = client.post(
            "/api/v1/mcp/connectors",
            headers=ADMIN,
            json={
                "business_unit_id": BUSINESS_UNIT,
                "code": DEEPWIKI_CONNECTOR_CODE,
                "name": "DeepWiki",
                "description": "公开 GitHub 仓库文档只读查询。",
                "url": connector_url,
                "timeout_seconds": 30,
            },
        )
        created.raise_for_status()
        connector = created.json()
    elif (
        connector["url"] != connector_url
        or connector["status"] != "ACTIVE"
        or connector["timeout_seconds"] != 30
    ):
        updated = client.patch(
            f"/api/v1/mcp/connectors/{connector['id']}",
            headers=ADMIN,
            json={
                "url": connector_url,
                "status": "ACTIVE",
                "timeout_seconds": 30,
            },
        )
        updated.raise_for_status()
        connector = updated.json()
    try:
        discovered = client.post(
            f"/api/v1/mcp/connectors/{connector['id']}/discover",
            headers=ADMIN,
        )
        discovered.raise_for_status()
        discovered_payload = discovered.json()
        if not discovered_payload.get("healthy"):
            print(
                "WARNING: optional DeepWiki MCP discovery failed; "
                "continuing with knowledge-only fallback.",
                file=sys.stderr,
            )
            return
        tools = discovered_payload.get("tools", [])
    except httpx.HTTPError as exc:
        print(
            "WARNING: optional DeepWiki MCP discovery raised "
            f"{type(exc).__name__}; continuing with knowledge-only fallback.",
            file=sys.stderr,
        )
        return
    allowed_tools = [str(tool["name"]) for tool in tools if not bool(tool.get("is_write"))]
    if not allowed_tools:
        return
    bindings = client.get(
        f"/api/v1/digital-employees/{employee['id']}/mcp-connectors",
        headers=ADMIN,
    )
    bindings.raise_for_status()
    preserved = [
        {
            "connector_id": item["connector_id"],
            "enabled": item["enabled"],
            "allowed_tools": item["allowed_tools"],
            "write_approved": item["write_approved"],
        }
        for item in bindings.json()
        if item["connector_id"] != connector["id"]
    ]
    replaced = client.put(
        f"/api/v1/digital-employees/{employee['id']}/mcp-connectors",
        headers=ADMIN,
        json={
            "bindings": [
                *preserved,
                {
                    "connector_id": connector["id"],
                    "enabled": True,
                    "allowed_tools": allowed_tools,
                    "write_approved": False,
                },
            ]
        },
    )
    replaced.raise_for_status()


def _ensure_business_sandbox_binding(
    client: httpx.Client,
    employee: dict[str, Any],
) -> None:
    connectors = client.get(
        "/api/v1/mcp/connectors",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    connectors.raise_for_status()
    connector = next(
        (item for item in connectors.json() if item["code"] == BUSINESS_SANDBOX_CONNECTOR_CODE),
        None,
    )
    connector_url = "http://mock-business-mcp:8091/mcp"
    if connector is None:
        created = client.post(
            "/api/v1/mcp/connectors",
            headers=ADMIN,
            json={
                "business_unit_id": BUSINESS_UNIT,
                "code": BUSINESS_SANDBOX_CONNECTOR_CODE,
                "name": "演示业务沙箱",
                "description": ("提供客户、订单、物流和改址能力；所有写操作必须经过审批。"),
                "url": connector_url,
                "timeout_seconds": 2,
            },
        )
        created.raise_for_status()
        connector = created.json()
    elif (
        connector["url"] != connector_url
        or connector["status"] != "ACTIVE"
        or connector["timeout_seconds"] != 2
    ):
        updated = client.patch(
            f"/api/v1/mcp/connectors/{connector['id']}",
            headers=ADMIN,
            json={
                "url": connector_url,
                "status": "ACTIVE",
                "timeout_seconds": 2,
            },
        )
        updated.raise_for_status()
        connector = updated.json()
    discovered = client.post(
        f"/api/v1/mcp/connectors/{connector['id']}/discover",
        headers=ADMIN,
    )
    discovered.raise_for_status()
    if not discovered.json().get("healthy"):
        raise RuntimeError(
            f"Business sandbox MCP discovery failed: {discovered.json().get('error')}"
        )
    bindings = client.get(
        (f"/api/v1/digital-employees/{employee['id']}/mcp-connectors"),
        headers=ADMIN,
    )
    bindings.raise_for_status()
    preserved = [
        {
            "connector_id": item["connector_id"],
            "enabled": item["enabled"],
            "allowed_tools": item["allowed_tools"],
            "write_approved": item["write_approved"],
        }
        for item in bindings.json()
        if item["connector_id"] != connector["id"]
    ]
    replaced = client.put(
        (f"/api/v1/digital-employees/{employee['id']}/mcp-connectors"),
        headers=ADMIN,
        json={
            "bindings": [
                *preserved,
                {
                    "connector_id": connector["id"],
                    "enabled": True,
                    "allowed_tools": BUSINESS_SANDBOX_TOOLS,
                    "write_approved": True,
                },
            ]
        },
    )
    replaced.raise_for_status()


def _ecommerce_entry_employee_ids(
    client: httpx.Client,
    *,
    primary_employee_id: str,
    additional_employee_ids: list[str] | None = None,
) -> list[str]:
    response = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    allowed_templates = {
        "ecommerce_presales",
        "ecommerce_aftersales",
        "ecommerce_logistics",
    }
    employee_ids = [
        item["id"]
        for item in response.json()
        if item["status"] == "ACTIVE" and item.get("template_code") in allowed_templates
    ]
    return list(
        dict.fromkeys(
            [
                primary_employee_id,
                *(additional_employee_ids or []),
                *employee_ids,
            ]
        )
    )


def _ensure_business_service_entry(
    client: httpx.Client,
    *,
    code: str,
    name: str,
    description: str,
    domain: str,
    channel: str,
    default_employee_id: str,
    fallback_employee_id: str,
    human_queue_id: str,
    employee_ids: list[str],
) -> dict[str, Any]:
    bindings = [
        {
            "employee_id": employee_id,
            "role_type": ("PRIMARY" if employee_id == default_employee_id else "SPECIALIST"),
            "priority": index * 10,
            "enabled": True,
        }
        for index, employee_id in enumerate(employee_ids, start=1)
    ]
    entries = client.get(
        "/api/v1/business-service-entries",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    entries.raise_for_status()
    entry = next(
        (item for item in entries.json() if item["code"] == code),
        None,
    )
    if entry is None:
        created = client.post(
            "/api/v1/business-service-entries",
            headers=ADMIN,
            json={
                "business_unit_id": BUSINESS_UNIT,
                "code": code,
                "name": name,
                "description": description,
                "domain": domain,
                "channel": channel,
                "default_employee_id": default_employee_id,
                "fallback_employee_id": fallback_employee_id,
                "human_queue_id": human_queue_id,
                "knowledge_scope": {"domain": domain},
                "sla_policy": {"first_response_seconds": 60},
                "employees": bindings,
            },
        )
        created.raise_for_status()
        return created.json()
    if (
        entry["default_employee_id"] != default_employee_id
        or entry["fallback_employee_id"] != fallback_employee_id
    ):
        updated = client.patch(
            f"/api/v1/business-service-entries/{entry['id']}",
            headers=ADMIN,
            json={
                "default_employee_id": default_employee_id,
                "fallback_employee_id": fallback_employee_id,
                "expected_version": entry["version"],
            },
        )
        updated.raise_for_status()
        entry = updated.json()
    replaced = client.put(
        f"/api/v1/business-service-entries/{entry['id']}/employees",
        headers=ADMIN,
        json=bindings,
    )
    replaced.raise_for_status()
    return replaced.json()


def _cleanup_test_tickets(client: httpx.Client) -> None:
    for prefix in TEST_REQUESTER_PREFIXES:
        response = client.post(
            "/api/v1/tickets/test-cleanup",
            headers=ADMIN,
            params={
                "business_unit_id": BUSINESS_UNIT,
                "requester_prefix": prefix,
            },
        )
        response.raise_for_status()


def _cleanup_test_conversations(client: httpx.Client) -> None:
    for prefix in TEST_REQUESTER_PREFIXES:
        response = client.post(
            "/api/v1/customer-service/test-cleanup",
            headers=ADMIN,
            params={
                "business_unit_id": BUSINESS_UNIT,
                "requester_prefix": prefix,
            },
        )
        response.raise_for_status()


def _disable_test_employees(client: httpx.Client) -> None:
    response = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    for employee in response.json():
        name = str(employee.get("name", ""))
        key = str(employee.get("employee_key", ""))
        is_test_employee = (
            name.startswith("验收")
            or "模板复验" in name
            or "资源继承复验" in name
            or key.startswith("e2e_")
        )
        if employee.get("status") != "DISABLED" and is_test_employee:
            disabled = client.patch(
                f"/api/v1/digital-employees/{employee['id']}",
                headers=ADMIN,
                json={"status": "DISABLED"},
            )
            disabled.raise_for_status()


def _ensure_employee_tools(
    client: httpx.Client,
    employee: dict[str, Any],
    tools: list[str],
) -> dict[str, Any]:
    if set(tools).issubset(set(employee.get("tool_allowlist", []))):
        return employee
    response = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"tool_allowlist": tools},
    )
    response.raise_for_status()
    return response.json()


def _ensure_employee_instruction(
    client: httpx.Client,
    employee: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    if employee.get("instruction") == instruction:
        return employee
    response = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"instruction": instruction},
    )
    response.raise_for_status()
    return response.json()


def _ensure_knowledge_space(
    client: httpx.Client,
    *,
    code: str,
    name: str,
    description: str,
    domain: str,
    channel: str,
    category: str,
    workflow_key: str | None,
) -> dict[str, Any]:
    response = client.get(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    existing = next(
        (space for space in response.json() if space["code"] == code),
        None,
    )
    if existing is not None:
        if existing["status"] == "DISABLED":
            response = client.patch(
                f"/api/v1/knowledge-spaces/{existing['id']}",
                headers=ADMIN,
                json={"status": "ACTIVE"},
            )
            response.raise_for_status()
            return response.json()
        return existing
    response = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "code": code,
            "name": name,
            "description": description,
            "domain": domain,
            "channel": channel,
            "category": category,
            "workflow_key": workflow_key,
            "owner_id": "demo-admin",
            "evaluation_required": False,
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_employee_knowledge_spaces(
    client: httpx.Client,
    employee: dict[str, Any],
    spaces: list[dict[str, Any]],
) -> None:
    response = client.get(
        f"/api/v1/digital-employees/{employee['id']}/knowledge-bindings",
        headers=ADMIN,
    )
    response.raise_for_status()
    existing = response.json()
    existing_ids = {
        binding["knowledge_space_id"] for binding in existing if binding.get("enabled", True)
    }
    requested_ids = {space["id"] for space in spaces}
    if requested_ids.issubset(existing_ids):
        return
    bindings = [
        {
            "knowledge_space_id": binding["knowledge_space_id"],
            "workflow_key": binding.get("workflow_key"),
            "scope": binding.get("scope", {}),
            "enabled": binding.get("enabled", True),
        }
        for binding in existing
    ]
    bindings.extend(
        {
            "knowledge_space_id": space["id"],
            "workflow_key": None,
            "scope": {},
            "enabled": True,
        }
        for space in spaces
        if space["id"] not in existing_ids
    )
    response = client.put(
        f"/api/v1/digital-employees/{employee['id']}/knowledge-bindings",
        headers=ADMIN,
        json={"bindings": bindings},
    )
    response.raise_for_status()


def _ensure_skill(
    client: httpx.Client,
    *,
    code: str,
    name: str,
    description: str,
    instructions: str,
    triggers: list[str],
    tools: list[str],
) -> dict[str, Any]:
    response = client.get(
        "/api/v1/skills",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    existing = next(
        (skill for skill in response.json() if skill["code"] == code),
        None,
    )
    if existing is not None:
        updates: dict[str, Any] = {}
        if existing["status"] != "ACTIVE":
            updates["status"] = "ACTIVE"
        if existing.get("triggers") != triggers:
            updates["triggers"] = triggers
        if updates:
            response = client.patch(
                f"/api/v1/skills/{existing['id']}",
                headers=ADMIN,
                json=updates,
            )
            response.raise_for_status()
            return response.json()
        return existing
    response = client.post(
        "/api/v1/skills",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "code": code,
            "name": name,
            "description": description,
            "instructions": instructions,
            "triggers": triggers,
            "tools": tools,
            "status": "ACTIVE",
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_employee_skills(
    client: httpx.Client,
    employee: dict[str, Any],
    skills: list[dict[str, Any]],
) -> None:
    response = client.get(
        f"/api/v1/digital-employees/{employee['id']}/skills",
        headers=ADMIN,
    )
    response.raise_for_status()
    existing = response.json()
    existing_ids = {binding["skill_id"] for binding in existing if binding.get("enabled", True)}
    requested_ids = {skill["id"] for skill in skills}
    if requested_ids.issubset(existing_ids):
        return
    bindings = [
        {
            "skill_id": binding["skill_id"],
            "enabled": binding.get("enabled", True),
            "priority": binding.get("priority", 100),
        }
        for binding in existing
    ]
    bindings.extend(
        {
            "skill_id": skill["id"],
            "enabled": True,
            "priority": 100,
        }
        for skill in skills
        if skill["id"] not in existing_ids
    )
    response = client.put(
        f"/api/v1/digital-employees/{employee['id']}/skills",
        headers=ADMIN,
        json={"bindings": bindings},
    )
    response.raise_for_status()


def _disable_test_knowledge_spaces(client: httpx.Client) -> None:
    response = client.get(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    for space in response.json():
        code = str(space.get("code", ""))
        is_test_space = (
            space.get("domain") == "e2e"
            or code.startswith("e2e_")
            or (code.startswith("acceptance_refund_") and space.get("document_count", 0) == 0)
        )
        if space.get("status") == "ACTIVE" and is_test_space:
            disabled = client.patch(
                f"/api/v1/knowledge-spaces/{space['id']}",
                headers=ADMIN,
                json={"status": "DISABLED"},
            )
            disabled.raise_for_status()


def _disable_test_evaluation_cases(client: httpx.Client) -> None:
    spaces_response = client.get(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    spaces_response.raise_for_status()
    spaces = {space["id"]: space for space in spaces_response.json()}
    cases_response = client.get(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    cases_response.raise_for_status()
    reason_labels = {
        "WRONG_ANSWER": "回答内容错误",
        "MISSING_KNOWLEDGE": "缺少相关知识",
        "UNSAFE_ANSWER": "回答存在风险",
        "OUTDATED_KNOWLEDGE": "知识已经过期",
    }
    for case in cases_response.json():
        localized_name = str(case.get("name", ""))
        for code, label in reason_labels.items():
            localized_name = localized_name.replace(code, label)
        if localized_name != case.get("name"):
            updated = client.patch(
                f"/api/v1/knowledge/evaluation-cases/{case['id']}",
                headers=ADMIN,
                json={"name": localized_name},
            )
            updated.raise_for_status()
        space = spaces.get(case.get("knowledge_space_id"))
        is_test_case = (
            str(case.get("name", "")).startswith("真实修复回归")
            or (space is not None and space.get("domain") == "e2e")
            or (space is not None and space.get("status") == "DISABLED")
        )
        if case.get("enabled") and is_test_case:
            disabled = client.patch(
                f"/api/v1/knowledge/evaluation-cases/{case['id']}",
                headers=ADMIN,
                json={"enabled": False},
            )
            disabled.raise_for_status()


def _ensure_knowledge(
    client: httpx.Client,
    *,
    space_id: str,
    title: str,
    doc_type: str,
    scope: dict[str, Any],
    content: str,
) -> dict[str, Any]:
    documents = client.get(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    documents.raise_for_status()
    document = next(
        (
            item
            for item in documents.json()
            if item["title"] == title and item["status"] != "ARCHIVED"
        ),
        None,
    )
    if document is None:
        response = client.post(
            "/api/v1/knowledge-documents",
            headers=ADMIN,
            json={
                "business_unit_id": BUSINESS_UNIT,
                "space_id": space_id,
                "title": title,
                "doc_type": doc_type,
                "owner_id": "demo-admin",
                "scope": scope,
            },
        )
        response.raise_for_status()
        document = response.json()
    elif document.get("space_id") != space_id or document.get("scope") != scope:
        response = client.patch(
            f"/api/v1/knowledge-documents/{document['id']}",
            headers=ADMIN,
            json={"space_id": space_id, "scope": scope},
        )
        response.raise_for_status()
        document = response.json()

    versions = client.get(
        f"/api/v1/knowledge-documents/{document['id']}/versions",
        headers=ADMIN,
    )
    versions.raise_for_status()
    version_items = versions.json()
    active = next((item for item in version_items if item["status"] == "ACTIVE"), None)
    if active is not None:
        return {"title": title, "version": active["version_label"], "status": "ACTIVE"}

    draft = next(
        (item for item in version_items if item["status"] == "DRAFT" and item["chunk_count"] > 0),
        None,
    )
    if draft is None:
        response = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/versions",
            headers=ADMIN,
            json={
                "version_label": f"seed-{len(version_items) + 1}.0",
                "content": content,
            },
        )
        response.raise_for_status()
        draft = response.json()

    published = client.post(
        (f"/api/v1/knowledge-documents/{document['id']}/versions/{draft['id']}/publish"),
        headers=ADMIN,
        json={"release_note": "测试数据初始化"},
    )
    published.raise_for_status()
    return {
        "title": title,
        "version": published.json()["version_label"],
        "status": published.json()["status"],
    }


def _ensure_ticket(
    client: httpx.Client,
    *,
    idempotency_key: str,
    employee_id: str,
    external_ticket_id: str,
    requester_ref: str,
    subject: str,
    body: str,
    metadata: dict[str, Any],
    source_system: str = "demo_helpdesk",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tickets",
        headers={**AGENT, "Idempotency-Key": idempotency_key},
        json={
            "business_unit_id": BUSINESS_UNIT,
            "employee_id": employee_id,
            "source": {
                "system": source_system,
                "channel": "web_form",
                "external_ticket_id": external_ticket_id,
            },
            "requester": {
                "external_ref": requester_ref,
                "customer_tier": "standard",
            },
            "subject": subject,
            "body": body,
            "locale": "zh-CN",
            "attachments": [],
            "metadata": metadata,
        },
    )
    if response.status_code == 409:
        problem = response.json()
        ticket_id = problem.get("context", {}).get("ticket_id")
        if problem.get("code") == "IDEMPOTENCY_CONFLICT" and ticket_id:
            detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
            detail.raise_for_status()
            return detail.json()
    response.raise_for_status()
    ticket_id = response.json()["id"]
    detail = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
    detail.raise_for_status()
    return detail.json()


def _ensure_ecommerce_product(
    client: httpx.Client,
    *,
    sku: str,
    name: str,
    category: str,
    brand: str,
    price: float,
    attributes: dict[str, object],
) -> dict[str, Any]:
    products = client.get(
        "/api/v1/ecommerce/products",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    products.raise_for_status()
    for product in products.json():
        if product["sku"] == sku:
            return product
    response = client.post(
        "/api/v1/ecommerce/products",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "sku": sku,
            "name": name,
            "category": category,
            "brand": brand,
            "price": price,
            "attributes": attributes,
        },
    )
    response.raise_for_status()
    return response.json()


def _ensure_product_asset(
    client: httpx.Client,
    *,
    product: dict[str, Any],
    filename: str,
    color: tuple[int, int, int],
) -> dict[str, Any]:
    assets = client.get(
        f"/api/v1/ecommerce/products/{product['id']}/assets",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    assets.raise_for_status()
    for asset in assets.json():
        metadata = asset.get("metadata", {})
        if isinstance(metadata, dict) and isinstance(metadata.get("width"), int):
            return asset
    response = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets",
        headers={**ADMIN, "Content-Type": "image/png"},
        params={"filename": filename},
        content=_demo_product_png(color),
    )
    response.raise_for_status()
    return response.json()


def _ensure_generated_image(
    client: httpx.Client,
    *,
    product: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    assets = client.get(
        f"/api/v1/ecommerce/products/{product['id']}/assets",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    assets.raise_for_status()
    for asset in assets.json():
        if asset.get("metadata", {}).get("source") == "AI_GENERATED":
            return asset
    response = client.post(
        f"/api/v1/ecommerce/products/{product['id']}/assets/generate",
        headers=ADMIN,
        json={"prompt": prompt},
    )
    response.raise_for_status()
    return response.json()


def _demo_product_png(color: tuple[int, int, int]) -> bytes:
    width = height = 320
    rows = bytearray()
    red, green, blue = color
    for y in range(height):
        rows.append(0)
        for x in range(width):
            distance = ((x - 160) ** 2 + (y - 160) ** 2) ** 0.5
            border = x < 8 or y < 8 or x >= width - 8 or y >= height - 8
            if border:
                rows.extend((240, 246, 246))
            elif distance < 92:
                rows.extend((255, 255, 255))
            else:
                light = 0.72 + 0.28 * (y / height)
                rows.extend(
                    (
                        int(red * light),
                        int(green * light),
                        int(blue * light),
                    )
                )

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def _ensure_listing_task(
    client: httpx.Client,
    *,
    product: dict[str, Any],
    channel: str,
) -> dict[str, Any]:
    tasks = client.get(
        "/api/v1/ecommerce/listing-tasks",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    tasks.raise_for_status()
    for task in tasks.json()["items"]:
        if task["product_id"] == product["id"] and task["channel"] == channel:
            detail = client.get(
                f"/api/v1/ecommerce/listing-tasks/{task['id']}",
                headers=ADMIN,
            )
            detail.raise_for_status()
            return detail.json()
    response = client.post(
        "/api/v1/ecommerce/listing-tasks",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
        json={"product_id": product["id"], "channel": channel},
    )
    response.raise_for_status()
    return response.json()


def _wait_for_ticket(
    client: httpx.Client,
    ticket_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/tickets/{ticket_id}", headers=AGENT)
        response.raise_for_status()
        last_payload = response.json()
        if predicate(last_payload):
            return last_payload
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for ticket {ticket_id}: {last_payload}")


def _wait_for_listing(
    client: httpx.Client,
    task_id: str,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/ecommerce/listing-tasks/{task_id}",
            headers=ADMIN,
        )
        response.raise_for_status()
        last_payload = response.json()
        if predicate(last_payload):
            return last_payload
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for listing {task_id}: {last_payload}")


if __name__ == "__main__":
    main()
