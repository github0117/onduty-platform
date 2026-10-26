from collections.abc import Callable

from ticket_agent.classification.conversation_signals import (
    is_technical_documentation_question,
)
from ticket_agent.model_gateway.types import (
    DraftClaim,
    DraftGenerationResponse,
    DraftSnippet,
    GatewayResponse,
    GeneratedDraft,
    ModelClassification,
    TicketCategory,
    WorkforceStepModelOutput,
    WorkforceStepResponse,
)


class LocalModelGateway:
    """Deterministic provider for offline development and model fallback."""

    _security_keywords = {
        "数据泄露",
        "泄露",
        "越权",
        "私有仓库",
        "密钥",
        "访问令牌",
        "系统提示词",
        "盗用",
        "账号被盗",
        "被黑",
        "隐私",
        "删除数据",
        "导出数据",
        "律师函",
        "法务",
        "监管",
    }
    _complaint_keywords = {"投诉", "曝光", "举报"}
    _transaction_keywords = {"退款", "赔付", "重复扣费", "交易争议"}
    _billing_keywords = {"发票", "账单", "扣费", "报销", "费用"}
    _incident_keywords = {
        "不可用",
        "报错",
        "崩溃",
        "故障",
        "超时",
        "异常",
        "蓝屏",
        "死机",
        "断网",
        "vpn",
        "连不上",
        "打不开",
        "无法连接",
        "收不到邮件",
    }
    _howto_keywords = {
        "怎么",
        "如何",
        "配置",
        "设置",
        "使用",
        "开通",
        "年假",
        "请假",
        "考勤",
        "会议室",
        "门禁",
        "工位",
        "办公用品",
        "入职",
        "离职",
        "转正",
    }
    _access_keywords = {"登录", "密码", "权限", "账号", "帐号"}
    _ecommerce_presales_keywords = {
        "尺码",
        "鞋面",
        "内里",
        "材质",
        "筒高",
        "跟高",
        "库存",
        "发货",
        "颜色",
        "怎么选",
    }
    _ecommerce_aftersales_keywords = {
        "退货",
        "退换",
        "退款",
        "物流",
        "快递",
        "订单",
        "售后",
        "漏发",
        "少发",
        "质量问题",
    }
    @property
    def name(self) -> str:
        return "local-keyword-v1"

    def classify(self, *, subject: str, body: str) -> GatewayResponse:
        text = f"{subject}\n{body}".lower()
        category, secondary, confidence = self._category(text)
        return GatewayResponse(
            classification=ModelClassification(
                primary=category,
                secondary=secondary,
                confidence=confidence,
                risk_tags=[],
                summary=self._summarize(subject, body),
            ),
            provider="local",
            model=self.name,
        )

    def generate_draft(
        self,
        *,
        subject: str,
        body: str,
        category: str,
        queue_id: str,
        snippets: list[DraftSnippet],
        skill_instructions: str | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> DraftGenerationResponse:
        del subject, body, queue_id, skill_instructions, on_text_delta
        templates = {
            "ecommerce_presales": (
                "您好，已根据商品知识为您整理商品信息。"
                "具体库存、价格和发货时效请以商品页实时信息为准。"
            ),
            "product_howto": (
                "您好，已收到您关于产品配置的咨询。我们已将问题转交产品支持组。"
                "请补充当前页面、期望配置项及实际结果，便于我们提供准确的操作步骤。"
            ),
            "access_identity": (
                "您好，已收到您的账号访问问题。我们已将问题转交身份支持组。"
                "请补充账号类型、发生时间和错误提示，便于进一步核查。"
            ),
            "service_incident": (
                "您好，已收到您反馈的服务异常。我们已将问题转交技术支持组。"
                "请补充影响范围、发生时间和可复现步骤；如问题持续影响业务，请及时回复。"
            ),
        }
        text = templates.get(
            category,
            "您好，已收到您的工单。我们正在根据您提供的信息确认处理团队和处理方式。",
        )
        if snippets:
            grounded_fact = (
                snippets[0].content.strip().rstrip("。").replace("。", "，")
            )
            if category == "ecommerce_presales":
                text = f"您好。根据已发布商品知识：{grounded_fact}。"
            else:
                text = (
                    f"您好。根据已发布知识：{grounded_fact}。"
                    "如需进一步协助，请补充当前页面、期望结果和错误提示。"
                )
        sentences = [
            sentence.strip()
            for sentence in text.split("。")
            if sentence.strip()
        ]
        claims: list[DraftClaim] = []
        citation_assigned = False
        for index, sentence in enumerate(sentences):
            claim_text = f"{sentence}。"
            claim_type = "greeting" if index == 0 else "instruction"
            cited_ids: list[str] = []
            if (
                not citation_assigned
                and snippets
                and (index > 0 or len(sentences) == 1)
            ):
                cited_ids = [snippet.chunk_id for snippet in snippets[:3]]
                citation_assigned = True
            claims.append(
                DraftClaim(
                    text=claim_text,
                    claim_type=claim_type,
                    cited_chunk_ids=cited_ids,
                )
            )
        cited_ids = list(
            dict.fromkeys(
                chunk_id
                for claim in claims
                for chunk_id in claim.cited_chunk_ids
            )
        )
        return DraftGenerationResponse(
            draft=GeneratedDraft(
                text=text,
                claims=claims,
                cited_chunk_ids=cited_ids,
            ),
            provider="local",
            model=self.name,
        )

    def generate_workforce_step(
        self,
        *,
        task_title: str,
        objective: str,
        context: dict[str, object],
        step_title: str,
        instructions: str,
        snippets: list[DraftSnippet],
        skill_instructions: str | None = None,
    ) -> WorkforceStepResponse:
        del objective, context, skill_instructions
        findings = (
            [
                f"{snippet.title}：{snippet.content[:300]}"
                for snippet in snippets[:3]
            ]
            if snippets
            else ["当前没有检索到可直接支持该步骤的知识依据。"]
        )
        return WorkforceStepResponse(
            output=WorkforceStepModelOutput(
                summary=f"{task_title}：已完成“{step_title}”本地规则分析。",
                findings=findings,
                recommended_actions=[
                    instructions,
                    "请专业员工或人工负责人核对后继续下一环节。",
                ],
                requires_human=not bool(snippets),
                cited_chunk_ids=[
                    snippet.chunk_id for snippet in snippets[:3]
                ],
            ),
            provider="local",
            model=self.name,
        )

    def _category(self, text: str) -> tuple[TicketCategory, str, float]:
        if self._contains(text, self._security_keywords):
            return "data_privacy_security", "security_request", 0.92
        if self._contains(text, self._complaint_keywords):
            return "complaint_escalation", "service_complaint", 0.91
        if any(
            term in text
            for term in (
                "改地址",
                "修改地址",
                "修改收货地址",
                "换地址",
                "更换收货地址",
                "变更地址",
                "变更收货地址",
                "更改收货地址",
                "收货地址改",
            )
        ):
            return "ecommerce_aftersales", "address_change", 0.98
        if (
            any(term in text for term in ("雪地靴", "商品"))
            and self._contains(text, self._ecommerce_aftersales_keywords)
        ):
            return "ecommerce_aftersales", "order_after_sales", 0.93
        if is_technical_documentation_question(text):
            return "product_howto", "technical_documentation", 0.94
        if self._contains(text, self._ecommerce_presales_keywords):
            return "ecommerce_presales", "product_consultation", 0.94
        if self._contains(text, self._transaction_keywords):
            return "transaction_dispute", "refund_request", 0.90
        if self._contains(text, self._billing_keywords):
            return "billing_invoice", "billing_question", 0.88
        if self._contains(text, self._incident_keywords):
            return "service_incident", "service_error", 0.86
        if self._contains(text, self._access_keywords):
            return "access_identity", "login_failure", 0.89
        if self._contains(text, self._howto_keywords):
            return "product_howto", "configuration", 0.93
        return "other_unclassified", "unknown", 0.42

    @staticmethod
    def _contains(text: str, keywords: set[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _summarize(subject: str, body: str) -> str:
        compact_body = " ".join(body.split())
        if len(compact_body) > 120:
            compact_body = f"{compact_body[:117]}..."
        return f"客户反馈：{subject.strip()}。{compact_body}"

