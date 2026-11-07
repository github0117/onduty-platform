import { Alert, Input, Modal, Select, Space } from "antd";

import type { McpActionIncident } from "../../../types";
import type {
  IncidentResolutionOutcome,
  useApprovalMutations,
} from "../useApprovalMutations";

const { TextArea } = Input;

interface IncidentDecisionModalProps {
  incidentDecision: {
    incident: McpActionIncident;
    action: "acknowledge" | "resolve";
  } | null;
  updateIncident: ReturnType<typeof useApprovalMutations>["updateIncident"];
  incidentNote: string;
  setIncidentNote: (value: string) => void;
  incidentOutcome: IncidentResolutionOutcome;
  setIncidentOutcome: (value: IncidentResolutionOutcome) => void;
  setIncidentDecision: (
    value: {
      incident: McpActionIncident;
      action: "acknowledge" | "resolve";
    } | null,
  ) => void;
}

export function IncidentDecisionModal({
  incidentDecision,
  updateIncident,
  incidentNote,
  setIncidentNote,
  incidentOutcome,
  setIncidentOutcome,
  setIncidentDecision,
}: IncidentDecisionModalProps) {
  return (
    <Modal
      open={Boolean(incidentDecision)}
      title={
        incidentDecision?.action === "acknowledge"
          ? "确认处理执行异常"
          : "关闭执行异常"
      }
      okText={
        incidentDecision?.action === "acknowledge"
          ? "确认接手"
          : "确认关闭"
      }
      okButtonProps={{
        loading: updateIncident.isPending,
        disabled:
          incidentDecision?.action === "resolve" &&
          !incidentNote.trim(),
      }}
      onOk={() => {
        if (incidentDecision) updateIncident.mutate(incidentDecision);
      }}
      onCancel={() => {
        setIncidentDecision(null);
        setIncidentNote("");
      }}
    >
      {incidentDecision && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            message={incidentDecision.incident.tool_id}
            description={incidentDecision.incident.required_action}
          />
          {incidentDecision.action === "resolve" && (
            <Select
              value={incidentOutcome}
              onChange={setIncidentOutcome}
              options={[
                {
                  value: "NOT_EXECUTED",
                  label: "核对确认未执行",
                },
                {
                  value: "EXECUTED_AS_INTENDED",
                  label: "已执行且结果正确",
                },
                {
                  value: "EXECUTED_INCORRECTLY",
                  label: "已执行但结果错误（需补偿）",
                },
                {
                  value: "INCONCLUSIVE",
                  label: "仍无法判断",
                },
              ]}
            />
          )}
          <TextArea
            rows={4}
            value={incidentNote}
            onChange={(event) => setIncidentNote(event.target.value)}
            placeholder={
              incidentDecision.action === "resolve"
                ? "必填：记录在哪个系统核对了什么结果，以及是否确认未执行或已执行"
                : "记录接手说明或待核查事项"
            }
          />
        </Space>
      )}
    </Modal>
  );
}
