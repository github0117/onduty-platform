/**
 * Capability names and path → capability mapping.
 *
 * The role → capability table lives only on the server
 * (`ticket_agent.identity.policy`). This module never re-derives permissions
 * from a role; callers pass the capability set returned by `GET /api/v1/me`.
 */

export type Capability =
  | "platform.overview"
  | "tickets.view_self"
  | "tickets.view"
  | "tickets.write"
  | "tickets.sync"
  | "service.chat"
  | "service.workbench"
  | "service.admin"
  | "service.approvals.view"
  | "service.approvals.decide"
  | "service.incidents.view"
  | "service.incidents.manage"
  | "knowledge.view"
  | "knowledge.use"
  | "knowledge.write"
  | "employees.directory"
  | "employees.view"
  | "employees.write"
  | "ecommerce.view"
  | "ecommerce.operate"
  | "ecommerce.catalog.write"
  | "operations.view"
  | "operations.manage"
  | "mcp.connectors.view"
  | "mcp.connectors.write"
  | "models.view"
  | "demo.reset";

export const capabilityLabels: Record<Capability, string> = {
  "platform.overview": "平台总览",
  "tickets.view_self": "查看自己的工单",
  "tickets.view": "查看工单",
  "tickets.write": "处理工单",
  "tickets.sync": "批量重试同步",
  "service.chat": "客服对话",
  "service.workbench": "人工客服工作台",
  "service.admin": "客服主管看板",
  "service.approvals.view": "查看写操作审批",
  "service.approvals.decide": "审批写操作",
  "service.incidents.view": "查看执行异常",
  "service.incidents.manage": "处理执行异常",
  "knowledge.view": "查看知识",
  "knowledge.use": "使用知识",
  "knowledge.write": "维护知识",
  "employees.directory": "查看员工目录",
  "employees.view": "查看数字员工",
  "employees.write": "配置数字员工",
  "ecommerce.view": "查看电商运营",
  "ecommerce.operate": "执行电商运营",
  "ecommerce.catalog.write": "维护商品目录",
  "operations.view": "查看运行与审计",
  "operations.manage": "运维管理",
  "mcp.connectors.view": "查看外部连接",
  "mcp.connectors.write": "维护外部连接",
  "models.view": "查看模型配置",
  "demo.reset": "恢复演示数据",
};

const pathCapabilities: Array<{
  prefix: string;
  anyOf: readonly Capability[];
}> = [
  { prefix: "/demo", anyOf: [] },
  { prefix: "/overview", anyOf: ["platform.overview"] },
  { prefix: "/customer-service/workbench", anyOf: ["service.workbench"] },
  { prefix: "/customer-service/admin", anyOf: ["service.admin"] },
  {
    prefix: "/customer-service/approvals",
    anyOf: ["service.approvals.view"],
  },
  {
    prefix: "/customer-service/incidents",
    anyOf: ["service.incidents.view"],
  },
  { prefix: "/customer-service", anyOf: ["service.chat"] },
  { prefix: "/ecommerce", anyOf: ["ecommerce.view"] },
  { prefix: "/tickets", anyOf: ["tickets.view", "tickets.view_self"] },
  { prefix: "/knowledge", anyOf: ["knowledge.view"] },
  { prefix: "/employees", anyOf: ["employees.view"] },
  { prefix: "/models", anyOf: ["models.view"] },
  { prefix: "/operations", anyOf: ["operations.view"] },
];

type CapabilityCollection = ReadonlySet<string> | readonly string[];

function isCapabilityArray(
  capabilities: CapabilityCollection,
): capabilities is readonly string[] {
  return Array.isArray(capabilities);
}

export function hasCapability(
  capabilities: CapabilityCollection,
  capability: Capability,
): boolean {
  if (isCapabilityArray(capabilities)) {
    return capabilities.includes(capability);
  }
  return capabilities.has(capability);
}

function capabilitiesForPath(path: string): readonly Capability[] | null {
  const matched = pathCapabilities.find(
    (item) => path === item.prefix || path.startsWith(`${item.prefix}/`),
  );
  return matched ? matched.anyOf : null;
}

export function canAccessPath(
  capabilities: CapabilityCollection,
  path: string,
): boolean {
  const required = capabilitiesForPath(path);
  if (required === null) return false;
  if (required.length === 0) return true;
  return required.some((capability) => hasCapability(capabilities, capability));
}

export function requiredCapabilitiesForPath(
  path: string,
): readonly Capability[] | null {
  return capabilitiesForPath(path);
}
