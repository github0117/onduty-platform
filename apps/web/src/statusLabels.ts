export const workflowStateLabels: Record<string, string> = {
  RECEIVED: "已接收",
  CLASSIFYING: "正在分类",
  RISK_EVALUATED: "风险已评估",
  ROUTING: "正在分流",
  DRAFTING: "正在生成回复",
  PENDING_REVIEW: "等待审核",
  NEEDS_HUMAN: "等待人工处理",
  TAKEN_OVER: "人工处理中",
  SYNCING: "正在同步",
  COMPLETED: "已处理完成",
  FAILED_RETRYABLE: "处理失败，可重试",
  FAILED_TERMINAL: "处理失败",
};

export const conversationStatusLabels: Record<string, string> = {
  ACTIVE: "进行中",
  CLOSED: "已关闭",
  ARCHIVED: "已归档",
};

export const syncStateLabels: Record<string, string> = {
  NOT_STARTED: "尚未同步",
  PENDING: "等待同步",
  SYNCING: "正在同步",
  RETRYING: "正在重试",
  SUCCEEDED: "同步成功",
  FAILED: "同步失败",
};

export const draftStateLabels: Record<string, string> = {
  NEEDS_REVIEW: "等待审核",
  AUTO_ACCEPTED: "已自动通过",
  ACCEPTED: "已采纳",
  EDITED_AND_ACCEPTED: "修改后采纳",
  REJECTED: "已驳回",
  ESCALATED: "已转人工",
};

export const groundingStatusLabels: Record<string, string> = {
  GROUNDED: "有知识依据",
  PARTIALLY_GROUNDED: "部分有知识依据",
  NO_KNOWLEDGE: "无知识依据",
  APPROVAL_REQUIRED: "需要写操作审批",
};

export const knowledgeDocumentStatusLabels: Record<string, string> = {
  DRAFT: "草稿",
  PROCESSING: "处理中",
  ACTIVE: "可用",
  ARCHIVED: "已归档",
  FAILED: "处理失败",
};

export const knowledgeVersionStatusLabels: Record<string, string> = {
  DRAFT: "草稿",
  PROCESSING: "处理中",
  ACTIVE: "已发布",
  SUPERSEDED: "已被新版本替代",
  RETIRED: "已停用",
  FAILED: "处理失败",
};

export const knowledgeDocumentTypeLabels: Record<string, string> = {
  SOP: "SOP · 操作流程",
  FAQ: "FAQ · 常见问答",
  POLICY: "制度 · 政策规则",
  PRODUCT: "产品 · 产品资料",
};

export const knowledgeSyncStatusLabels: Record<string, string> = {
  SYNCING: "同步中",
  SYNCED: "已同步",
  FAILED: "同步失败",
};

export const feedbackRatingLabels: Record<string, string> = {
  POSITIVE: "有帮助",
  NEGATIVE: "需要改进",
};

export const feedbackReasonLabels: Record<string, string> = {
  WRONG_ANSWER: "回答内容错误",
  MISSING_KNOWLEDGE: "缺少相关知识",
  UNSAFE_ANSWER: "回答存在风险",
  OUTDATED_KNOWLEDGE: "知识已经过期",
  HELPFUL: "回答有帮助",
};

export const productStatusLabels: Record<string, string> = {
  READY: "资料可用",
  ACTIVE: "可用",
  INACTIVE: "已停用",
  DRAFT: "草稿",
  ARCHIVED: "已归档",
  FAILED: "失败",
};

export const assetStatusLabels: Record<string, string> = {
  READY: "可用",
  PROCESSING: "处理中",
  ARCHIVED: "已归档",
  FAILED: "处理失败",
};

export const assetTypeLabels: Record<string, string> = {
  IMAGE: "图片",
  VIDEO: "视频",
  AUDIO: "音频",
  SUBTITLE: "字幕",
};

export const batchStatusLabels: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "处理中",
  SUCCEEDED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "失败",
};

export const eventStatusLabels: Record<string, string> = {
  RUNNING: "执行中",
  SUCCEEDED: "成功",
  FAILED: "失败",
  DENIED: "已拒绝",
  WAITING_HUMAN: "等待人工",
  PENDING: "等待中",
};

export const eventTypeLabels: Record<string, string> = {
  model: "模型调用",
  tool: "工具调用",
  workflow: "流程节点",
  human: "人工处理",
};

export const employeeStatusLabels: Record<string, string> = {
  ACTIVE: "已启用",
  TRIAL: "试用中",
  DISABLED: "已停用",
  EVALUATION_FAILED: "评测未通过",
  ARCHIVED: "已归档",
};

export const queueLabels: Record<string, string> = {
  ECOMMERCE_PRESALES: "电商售前",
  ECOMMERCE_AFTERSALES: "电商售后",
  TRANSACTION_OPS: "交易处理",
  PRODUCT_SUPPORT: "产品支持",
  IDENTITY_SUPPORT: "账号支持",
  FINANCE_SUPPORT: "财务支持",
  CUSTOMER_SUCCESS: "客户成功",
  SECURITY_RESPONSE: "安全响应",
  MANUAL_TRIAGE: "人工分流",
  TECH_SERVICE_PLATFORM: "技术服务台",
  ENTERPRISE_SERVICE_DESK: "企业服务台",
  HR_SERVICE_DESK: "HR 服务台",
  ECOMMERCE_SERVICE_HUMAN: "电商客服人工组",
  AFTER_SALES_REVIEW: "售后审核组",
};

export const humanReasonLabels: Record<string, string> = {
  HIGH_RISK_TOPIC: "高风险问题，必须人工处理",
  LOW_CLASSIFICATION_CONFIDENCE: "分类置信度不足",
  UNCLASSIFIED: "无法确定问题类型",
  POLICY_REQUIRES_HUMAN_REVIEW: "业务规则要求人工审核",
  AFTER_SALES_REQUIRES_HUMAN: "售后问题必须人工处理",
  KNOWLEDGE_NOT_FOUND: "知识库未命中相关内容",
};

export const ticketCategoryLabels: Record<string, string> = {
  product_howto: "产品使用",
  access_identity: "账号权限",
  service_incident: "服务故障",
  billing_invoice: "账单发票",
  transaction_dispute: "交易争议",
  complaint_escalation: "投诉升级",
  data_privacy_security: "数据安全",
  hr_onboarding: "HR 入职",
  hr_service: "HR 服务",
  finance_service: "财务服务",
  it_support: "IT 支持",
  enterprise_service_request: "企业服务请求",
  ecommerce_presales: "电商售前",
  ecommerce_aftersales: "电商售后",
  ecommerce_logistics: "物流查询",
  other_unclassified: "待人工分类",
};

export const ticketSecondaryLabels: Record<string, string> = {
  address_change: "修改收货地址",
  product_consultation: "商品咨询",
  order_after_sales: "订单售后",
  refund_request: "退款申请",
  configuration: "配置说明",
  login_failure: "登录问题",
};

export const riskReasonLabels: Record<string, string> = {
  ADDRESS_CHANGE_HARD_RULE: "改址属于外部写操作",
  RISK_FORCED_HUMAN: "高风险问题必须人工审核",
  ECOMMERCE_AFTERSALES_RULE: "售后问题需人工处理",
  FINANCIAL_ACTION_HARD_RULE: "涉及资金动作",
  COMPLAINT_HARD_RULE: "投诉需要升级处理",
  SECURITY_HARD_RULE: "涉及安全或隐私",
};

export const providerLabels: Record<string, string> = {
  local: "本地规则",
  "local-keyword-v1": "本地规则",
  openai_compatible: "大模型",
  system_policy: "系统策略",
};

export const channelLabels: Record<string, string> = {
  pinduoduo: "国内电商演示渠道",
  pinduoduo_sandbox: "国内电商演示渠道",
  taobao_sandbox: "国内电商演示渠道",
  douyin_sandbox: "国内电商演示渠道",
  local_shop: "本地演示店铺",
  ecommerce_demo: "国内电商演示渠道",
  web_form: "网页演示入口",
  workforce: "内部任务",
};

export function localizedLabel(
  labels: Record<string, string>,
  value: string | null | undefined,
  fallback = "-",
): string {
  if (!value) return fallback;
  return labels[value] ?? value;
}
