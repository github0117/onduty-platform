export type Capability =
  | "platform.overview"
  | "platform.management"
  | "service.chat"
  | "service.workbench"
  | "service.admin"
  | "service.approvals"
  | "service.incidents"
  | "ecommerce.view"
  | "tickets.view"
  | "knowledge.view"
  | "knowledge.write"
  | "employees.view"
  | "employees.write"
  | "models.view"
  | "operations.view";

const capabilitiesByRole: Record<string, readonly Capability[]> = {
  agent: [
    "service.chat",
    "service.workbench",
    "ecommerce.view",
    "tickets.view",
    "knowledge.view",
  ],
  supervisor: [
    "platform.management",
    "service.chat",
    "service.workbench",
    "service.admin",
    "service.approvals",
    "service.incidents",
    "ecommerce.view",
    "tickets.view",
    "knowledge.view",
    "operations.view",
  ],
  knowledge_operator: [
    "platform.management",
    "knowledge.view",
    "knowledge.write",
    "employees.view",
    "employees.write",
  ],
  business_manager: [
    "platform.management",
    "service.chat",
    "ecommerce.view",
    "tickets.view",
    "knowledge.view",
    "operations.view",
  ],
  admin: [
    "platform.overview",
    "platform.management",
    "service.chat",
    "service.workbench",
    "service.admin",
    "service.approvals",
    "service.incidents",
    "ecommerce.view",
    "tickets.view",
    "knowledge.view",
    "knowledge.write",
    "employees.view",
    "employees.write",
    "models.view",
    "operations.view",
  ],
  auditor: [
    "platform.management",
    "service.admin",
    "service.approvals",
    "service.incidents",
    "knowledge.view",
    "operations.view",
  ],
};

const pathCapabilities: Array<{
  prefix: string;
  capability: Capability;
}> = [
  { prefix: "/overview", capability: "platform.overview" },
  { prefix: "/customer-service/workbench", capability: "service.workbench" },
  { prefix: "/customer-service/admin", capability: "service.admin" },
  { prefix: "/customer-service/approvals", capability: "service.approvals" },
  { prefix: "/customer-service/incidents", capability: "service.incidents" },
  { prefix: "/customer-service", capability: "service.chat" },
  { prefix: "/ecommerce", capability: "ecommerce.view" },
  { prefix: "/tickets", capability: "tickets.view" },
  { prefix: "/knowledge", capability: "knowledge.view" },
  { prefix: "/employees", capability: "employees.view" },
  { prefix: "/models", capability: "models.view" },
  { prefix: "/operations", capability: "operations.view" },
];

export function hasCapability(
  role: string,
  capability: Capability,
): boolean {
  return capabilitiesByRole[role]?.includes(capability) ?? false;
}

export function canAccessPath(role: string, path: string): boolean {
  const matched = pathCapabilities.find(
    (item) => path === item.prefix || path.startsWith(`${item.prefix}/`),
  );
  return matched ? hasCapability(role, matched.capability) : false;
}

export function capabilityForPath(path: string): Capability | null {
  return (
    pathCapabilities.find(
      (item) => path === item.prefix || path.startsWith(`${item.prefix}/`),
    )?.capability ?? null
  );
}
