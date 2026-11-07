import { Alert, Descriptions, Input, Modal, Space, Typography } from "antd";

import type { McpToolApproval } from "../../../types";
import type { useApprovalMutations } from "../useApprovalMutations";

const { Text } = Typography;
const { TextArea } = Input;

interface ApprovalDecisionModalProps {
  approvalDecision: {
    approval: McpToolApproval;
    decision: "APPROVE" | "REJECT";
  } | null;
  decideApproval: ReturnType<typeof useApprovalMutations>["decideApproval"];
  approvalNote: string;
  setApprovalNote: (value: string) => void;
  setApprovalDecision: (
    value: { approval: McpToolApproval; decision: "APPROVE" | "REJECT" } | null,
  ) => void;
}

export function ApprovalDecisionModal({
  approvalDecision,
  decideApproval,
  approvalNote,
  setApprovalNote,
  setApprovalDecision,
}: ApprovalDecisionModalProps) {
  return (
    <Modal
      open={Boolean(approvalDecision)}
      title={
        approvalDecision?.decision === "APPROVE"
          ? "审批并执行 MCP 写操作"
          : "拒绝 MCP 写操作"
      }
      okText={
        approvalDecision?.decision === "APPROVE"
          ? "确认审批并执行"
          : "确认拒绝"
      }
      okButtonProps={{
        danger: approvalDecision?.decision === "APPROVE",
        loading: decideApproval.isPending,
      }}
      onOk={() => {
        if (approvalDecision) decideApproval.mutate(approvalDecision);
      }}
      onCancel={() => {
        setApprovalDecision(null);
        setApprovalNote("");
      }}
    >
      {approvalDecision && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type={
              approvalDecision.decision === "APPROVE" ? "warning" : "info"
            }
            showIcon
            message={approvalDecision.approval.tool_id}
            description={
              approvalDecision.decision === "APPROVE"
                ? "确认后将立即调用外部 MCP 写工具，只执行一次。请核对订单、金额和业务条件。"
                : "拒绝后不会调用外部写工具。之后如需重新申请，应由业务会话重新发起。"
            }
          />
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="申请人">
              {approvalDecision.approval.requested_by}
            </Descriptions.Item>
            <Descriptions.Item label="工具参数">
              <Text code>
                {JSON.stringify(approvalDecision.approval.arguments)}
              </Text>
            </Descriptions.Item>
            <Descriptions.Item label="申请原因">
              {approvalDecision.approval.reason || "未提供"}
            </Descriptions.Item>
            <Descriptions.Item label="审批等级">
              {approvalDecision.approval.required_role === "admin"
                ? "管理员"
                : "主管或管理员"}
            </Descriptions.Item>
          </Descriptions>
          <TextArea
            rows={3}
            value={approvalNote}
            onChange={(event) => setApprovalNote(event.target.value)}
            placeholder="填写审批意见或拒绝理由"
          />
          <Text type="secondary">
            当前审批身份：页面右上角选择的测试身份或 OIDC 登录身份
          </Text>
        </Space>
      )}
    </Modal>
  );
}
