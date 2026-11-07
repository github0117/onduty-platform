import { Form, Input, Modal, Select } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { createDigitalEmployee } from "../../api";
import { workflowLabels } from "../../employeeLabels";
import { message } from "../../feedback";
import { customerTools, hrTools } from "./shared";

const { TextArea } = Input;

export function CreateEmployeeModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [employeeKey, setEmployeeKey] = useState("");
  const [name, setName] = useState("");
  const [workflowKey, setWorkflowKey] = useState("customer_service_ticket_v1");
  const [queue, setQueue] = useState("MANUAL_TRIAGE");
  const [instruction, setInstruction] = useState("");
  const create = useMutation({
    mutationFn: () =>
      createDigitalEmployee({
        employee_key: employeeKey,
        name,
        workflow_key: workflowKey,
        handoff_queue: queue,
        instruction,
        tools:
          workflowKey === "hr_onboarding_document_collection_v1"
            ? hrTools
            : customerTools,
      }),
    onSuccess: async () => {
      message.success("数字员工已创建");
      setEmployeeKey("");
      setName("");
      setInstruction("");
      await onCreated();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Modal
      title="新建数字员工"
      open={open}
      onCancel={onClose}
      okText="创建"
      confirmLoading={create.isPending}
      okButtonProps={{ disabled: !employeeKey.trim() || !name.trim() }}
      onOk={() => create.mutate()}
    >
      <Form layout="vertical">
        <Form.Item label="员工名称" required>
          <Input value={name} onChange={(event) => setName(event.target.value)} />
        </Form.Item>
        <Form.Item
          label="员工标识"
          required
          extra="小写字母开头，只能使用字母、数字和下划线"
        >
          <Input
            value={employeeKey}
            onChange={(event) => setEmployeeKey(event.target.value)}
            placeholder="after_sales_agent"
          />
        </Form.Item>
        <Form.Item label="工作流" required>
          <Select
            value={workflowKey}
            options={Object.entries(workflowLabels).map(([value, label]) => ({
              value,
              label,
            }))}
            onChange={(value) => {
              setWorkflowKey(value);
              setQueue(
                value === "hr_onboarding_document_collection_v1"
                  ? "HR_SERVICE_DESK"
                  : "MANUAL_TRIAGE",
              );
            }}
          />
        </Form.Item>
        <Form.Item label="人工队列" required>
          <Input value={queue} onChange={(event) => setQueue(event.target.value)} />
        </Form.Item>
        <Form.Item
          label="角色提示词"
          extra="可选。补充该员工的角色、语气和服务边界；创建后仍可在配置中修改。"
        >
          <TextArea
            rows={4}
            maxLength={4000}
            showCount
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="例如：你是一名耐心、简洁的售后客服，先确认订单号；涉及退款只能说明流程并转人工。"
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
