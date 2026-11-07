import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  actOnMcpActionIncident,
  decideMcpToolApproval,
  reconcileMcpActionIncident,
  requestMcpActionCompensation,
  ApiError,
} from "../../api";
import { message } from "../../feedback";
import type { McpActionIncident, McpToolApproval } from "../../types";
import { approvalStatusLabels } from "./model";

export type IncidentResolutionOutcome =
  | "EXECUTED_AS_INTENDED"
  | "NOT_EXECUTED"
  | "EXECUTED_INCORRECTLY"
  | "INCONCLUSIVE";

export interface UseApprovalMutationsOptions {
  approvalNote: string;
  incidentNote: string;
  incidentOutcome: IncidentResolutionOutcome;
  compensationToolId: string;
  compensationArguments: string;
  compensationNote: string;
  onApprovalDecisionHandled: () => void;
  onIncidentActionHandled: () => void;
  onCompensationRequested: () => void;
}

export function useApprovalMutations({
  approvalNote,
  incidentNote,
  incidentOutcome,
  compensationToolId,
  compensationArguments,
  compensationNote,
  onApprovalDecisionHandled,
  onIncidentActionHandled,
  onCompensationRequested,
}: UseApprovalMutationsOptions) {
  const queryClient = useQueryClient();

  const decideApproval = useMutation({
    mutationFn: (input: {
      approval: McpToolApproval;
      decision: "APPROVE" | "REJECT";
    }) =>
      decideMcpToolApproval(input.approval.id, {
        decision: input.decision,
        expectedVersion: input.approval.version,
        note: approvalNote.trim(),
      }),
    onSuccess: async (approval) => {
      onApprovalDecisionHandled();
      message.success(
        approval.status === "SUCCEEDED"
          ? "审批通过，写工具已执行一次"
          : approval.status === "REJECTED"
            ? "审批已拒绝，写工具未执行"
            : `审批已处理：${approvalStatusLabels[approval.status] ?? approval.status}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mcp-tool-approvals"] }),
        queryClient.invalidateQueries({ queryKey: ["tool-calls"] }),
      ]);
    },
    onError: (error: Error) => {
      if (error instanceof ApiError) {
        if (error.code === "MCP_APPROVAL_SELF_APPROVAL_DENIED") {
          message.error("申请人与审批人不能是同一个账号，请更换审批人。");
          return;
        }
        if (error.code === "MCP_APPROVAL_VERSION_CONFLICT") {
          message.warning("审批单状态已变化，请刷新后重新确认。");
          void queryClient.invalidateQueries({
            queryKey: ["mcp-tool-approvals"],
          });
          return;
        }
      }
      message.error(error.message);
    },
  });
  const updateIncident = useMutation({
    mutationFn: (input: {
      incident: McpActionIncident;
      action: "acknowledge" | "resolve";
    }) =>
      actOnMcpActionIncident(input.incident.id, input.action, {
        expectedVersion: input.incident.version,
        note: incidentNote.trim(),
        outcome:
          input.action === "resolve" ? incidentOutcome : undefined,
      }),
    onSuccess: async (incident) => {
      onIncidentActionHandled();
      message.success(
        incident.status === "RESOLVED"
          ? "事故已关闭，处理结论已留档"
          : "事故已确认，已分配给当前处理人",
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["mcp-action-incidents"],
        }),
        queryClient.invalidateQueries({ queryKey: ["tool-calls"] }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const reconcileIncident = useMutation({
    mutationFn: (incident: McpActionIncident) =>
      reconcileMcpActionIncident(incident.id, {
        expectedVersion: incident.version,
      }),
    onSuccess: async (incident) => {
      message.success(
        incident.reconciliation_status === "SUCCEEDED"
          ? "对账查询完成，请根据真实结果填写事故结论"
          : "对账失败，请检查只读工具和参数",
      );
      await queryClient.invalidateQueries({
        queryKey: ["mcp-action-incidents"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const requestCompensation = useMutation({
    mutationFn: (incident: McpActionIncident) => {
      let parsedArguments: Record<string, unknown>;
      try {
        parsedArguments = JSON.parse(compensationArguments) as Record<
          string,
          unknown
        >;
      } catch {
        throw new Error("补偿参数必须是合法 JSON 对象");
      }
      return requestMcpActionCompensation(incident.id, {
        expectedVersion: incident.version,
        toolId: compensationToolId.trim() || undefined,
        arguments: parsedArguments,
        note: compensationNote.trim(),
      });
    },
    onSuccess: async (incident) => {
      onCompensationRequested();
      message.success(
        `补偿审批已创建：${incident.compensation_approval_id?.slice(0, 8)}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["mcp-action-incidents"],
        }),
        queryClient.invalidateQueries({ queryKey: ["mcp-tool-approvals"] }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });

  return {
    decideApproval,
    updateIncident,
    reconcileIncident,
    requestCompensation,
  };
}
