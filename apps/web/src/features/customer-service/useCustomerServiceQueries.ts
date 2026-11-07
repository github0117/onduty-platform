import { useQuery } from "@tanstack/react-query";

import {
  getCustomerAssignmentQueue,
  getCustomerConversation,
  getCustomerServiceHistoryMetrics,
  getCustomerServiceMetrics,
  getRuntimeConfig,
  getTicket,
  listCustomerAgentPresence,
  listCustomerConversations,
  listCustomerServiceAlerts,
  listCustomerServiceNotifications,
  listDigitalEmployees,
  listEcommerceCategoryProfiles,
  listEcommerceProducts,
  listEmployeeKnowledgeBindings,
  listKnowledgeSpaces,
  listMcpActionIncidents,
  listMcpToolApprovals,
} from "../../api";
import type { CustomerServiceSection } from "./model";

const terminalStates = new Set(["COMPLETED", "FAILED_TERMINAL"]);

export interface UseCustomerServiceQueriesOptions {
  isAdminSurface: boolean;
  section: CustomerServiceSection;
  approvalFilter: string;
  incidentFilter: string;
  ticketId: string;
  conversationId: string;
  employeeId: string;
  canViewApprovals: boolean;
  canViewIncidents: boolean;
  canViewEmployeeDirectory: boolean;
}

export function useCustomerServiceQueries({
  isAdminSurface,
  section,
  approvalFilter,
  incidentFilter,
  ticketId,
  conversationId,
  employeeId,
  canViewApprovals,
  canViewIncidents,
  canViewEmployeeDirectory,
}: UseCustomerServiceQueriesOptions) {
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: isAdminSurface && canViewEmployeeDirectory,
  });
  const categories = useQuery({
    queryKey: ["ecommerce-categories"],
    queryFn: listEcommerceCategoryProfiles,
    enabled: isAdminSurface,
  });
  const products = useQuery({
    queryKey: ["ecommerce-products"],
    queryFn: listEcommerceProducts,
    enabled: isAdminSurface,
  });
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: isAdminSurface,
  });
  const conversations = useQuery({
    queryKey: ["customer-conversations"],
    queryFn: listCustomerConversations,
    refetchInterval: 5_000,
    enabled: isAdminSurface,
  });
  const presence = useQuery({
    queryKey: ["customer-agent-presence"],
    queryFn: listCustomerAgentPresence,
    refetchInterval: 15_000,
    enabled: isAdminSurface,
  });
  const assignmentQueue = useQuery({
    queryKey: ["customer-assignment-queue"],
    queryFn: getCustomerAssignmentQueue,
    refetchInterval: 5_000,
    enabled: isAdminSurface,
  });
  const serviceAlerts = useQuery({
    queryKey: ["customer-service-alerts"],
    queryFn: listCustomerServiceAlerts,
    refetchInterval: 10_000,
    enabled: isAdminSurface,
  });
  const notifications = useQuery({
    queryKey: ["customer-service-notifications"],
    queryFn: listCustomerServiceNotifications,
    refetchInterval: 15_000,
    enabled: isAdminSurface,
  });
  const mcpApprovals = useQuery({
    queryKey: ["mcp-tool-approvals", approvalFilter],
    queryFn: () =>
      listMcpToolApprovals(
        approvalFilter === "ALL" ? undefined : approvalFilter,
      ),
    refetchInterval: 10_000,
    enabled: canViewApprovals && section === "approvals",
  });
  const mcpIncidents = useQuery({
    queryKey: ["mcp-action-incidents", incidentFilter],
    queryFn: () =>
      listMcpActionIncidents(
        incidentFilter === "ALL" ? undefined : incidentFilter,
      ),
    refetchInterval: 10_000,
    enabled: canViewIncidents && section === "incidents",
  });
  const metrics = useQuery({
    queryKey: ["customer-service-metrics"],
    queryFn: getCustomerServiceMetrics,
    refetchInterval: 10_000,
    enabled: isAdminSurface && section === "admin",
  });
  const historyMetrics = useQuery({
    queryKey: ["customer-service-history-metrics"],
    queryFn: () => getCustomerServiceHistoryMetrics(7),
    refetchInterval: 60_000,
    enabled: isAdminSurface && section === "admin",
  });
  const runtime = useQuery({
    queryKey: ["system-runtime"],
    queryFn: getRuntimeConfig,
    enabled: isAdminSurface,
  });
  const detail = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => getTicket(ticketId),
    enabled: isAdminSurface && Boolean(ticketId),
    refetchInterval: (query) =>
      terminalStates.has(query.state.data?.workflow_state ?? "")
        ? false
        : 2_000,
  });
  const conversationDetail = useQuery({
    queryKey: ["customer-conversation", conversationId],
    queryFn: () => getCustomerConversation(conversationId),
    enabled: isAdminSurface && Boolean(conversationId),
    refetchInterval: 10_000,
  });
  const knowledgeBindings = useQuery({
    queryKey: [
      "knowledge-bindings",
      detail.data?.employee.id ?? employeeId,
    ],
    queryFn: () =>
      listEmployeeKnowledgeBindings(detail.data?.employee.id ?? employeeId),
    enabled:
      isAdminSurface && Boolean(detail.data?.employee.id || employeeId),
  });

  return {
    employees,
    categories,
    products,
    spaces,
    conversations,
    presence,
    assignmentQueue,
    serviceAlerts,
    notifications,
    mcpApprovals,
    mcpIncidents,
    metrics,
    historyMetrics,
    runtime,
    detail,
    conversationDetail,
    knowledgeBindings,
  };
}
