import { Alert, Input, Modal, Space } from "antd";

import type { McpActionIncident } from "../../../types";
import type { useApprovalMutations } from "../useApprovalMutations";

const { TextArea } = Input;

interface CompensationModalProps {
  compensationIncident: McpActionIncident | null;
  setCompensationIncident: (value: McpActionIncident | null) => void;
  requestCompensation: ReturnType<
    typeof useApprovalMutations
  >["requestCompensation"];
  compensationToolId: string;
  setCompensationToolId: (value: string) => void;
  compensationArguments: string;
  setCompensationArguments: (value: string) => void;
  compensationNote: string;
  setCompensationNote: (value: string) => void;
}

export function CompensationModal({
  compensationIncident,
  setCompensationIncident,
  requestCompensation,
  compensationToolId,
  setCompensationToolId,
  compensationArguments,
  setCompensationArguments,
  compensationNote,
  setCompensationNote,
}: CompensationModalProps) {
  return (
    <Modal
      open={Boolean(compensationIncident)}
      title="提交 MCP 补偿审批"
      okText="创建补偿审批"
      okButtonProps={{
        danger: true,
        loading: requestCompensation.isPending,
        disabled: !compensationNote.trim(),
      }}
      onOk={() => {
        if (compensationIncident) {
          requestCompensation.mutate(compensationIncident);
        }
      }}
      onCancel={() => setCompensationIncident(null)}
    >
      {compensationIncident && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="error"
            showIcon
            message="补偿会创建新的管理员审批单"
            description="补偿工具不会自动执行。新审批必须由另一名管理员批准，执行成功后才允许把原事故标记为“执行结果错误”并关闭。"
          />
          <Input
            value={compensationToolId}
            onChange={(event) =>
              setCompensationToolId(event.target.value)
            }
            placeholder="补偿工具 ID；留空则使用 reverse/compensate 工具"
          />
          <TextArea
            rows={5}
            value={compensationArguments}
            onChange={(event) =>
              setCompensationArguments(event.target.value)
            }
            placeholder='补偿参数 JSON，例如 {"order_id":"...","amount":59.9}'
          />
          <TextArea
            rows={3}
            value={compensationNote}
            onChange={(event) => setCompensationNote(event.target.value)}
            placeholder="必填：说明为什么需要补偿及核对依据"
          />
        </Space>
      )}
    </Modal>
  );
}
