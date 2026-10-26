export const demoPerspectiveIds = [
  "service-agent",
  "service-supervisor",
  "platform-admin",
] as const;

export const demoPerspectiveLabels: Record<string, string> = {
  "service-agent": "业务执行者",
  "service-supervisor": "管理者",
  "platform-admin": "平台管理员",
  "business-manager": "管理者",
  "knowledge-operator": "平台管理员",
};
