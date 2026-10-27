export const demoPerspectiveIds = [
  "service-agent",
  "service-supervisor",
  "knowledge-operator",
  "business-manager",
  "auditor",
  "platform-admin",
] as const;

export const demoPerspectiveLabels: Record<string, string> = {
  "service-agent": "客服坐席",
  "service-supervisor": "客服主管",
  "knowledge-operator": "知识运营",
  "business-manager": "业务经理",
  auditor: "审计员",
  "platform-admin": "平台管理员",
};
