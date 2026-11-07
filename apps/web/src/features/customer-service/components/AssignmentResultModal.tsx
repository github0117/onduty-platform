import {
  Alert,
  Button,
  Card,
  Collapse,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import type { AssignmentRunResult } from "../../../types";

const { Text } = Typography;

interface AssignmentResultModalProps {
  assignmentResult: AssignmentRunResult | null;
  setAssignmentResult: (value: AssignmentRunResult | null) => void;
}

export function AssignmentResultModal({
  assignmentResult,
  setAssignmentResult,
}: AssignmentResultModalProps) {
  return (
    <Modal
      open={Boolean(assignmentResult)}
      title="主管补派结果"
      footer={
        <Button onClick={() => setAssignmentResult(null)}>知道了</Button>
      }
      onCancel={() => setAssignmentResult(null)}
      width={760}
    >
      {assignmentResult && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="人工客服自动分配不是按关键词随意分人"
            description="系统会先按客服技能和高风险权限筛选，再比较当前会话负载。后台每 10 秒自动执行；这里的手动补派用于立即处理或验证。"
          />
          <Space wrap>
            <Tag color="green">
              本次分配 {assignmentResult.assigned_count}
            </Tag>
            <Tag color="gold">
              仍待处理 {assignmentResult.unassigned_count}
            </Tag>
          </Space>
          {assignmentResult.assignments.length === 0 ? (
            <Alert
              type="warning"
              showIcon
              message="本次没有可分配会话"
              description="请检查客服是否在线、是否开启自动接单、技能和风险权限是否覆盖，以及当前并发是否已满。"
            />
          ) : (
            assignmentResult.assignments.map((assignment) => (
              <Card
                key={assignment.conversation_id}
                size="small"
                title={`会话 ${assignment.conversation_id.slice(0, 8)}`}
                extra={<Tag>{assignment.priority}</Tag>}
              >
                <Space
                  direction="vertical"
                  size="small"
                  style={{ width: "100%" }}
                >
                  <Text strong>分配给：{assignment.agent_id}</Text>
                  <Text type="secondary">{assignment.reason}</Text>
                  <Collapse
                    size="small"
                    items={[
                      {
                        key: "candidates",
                        label: `查看 ${assignment.candidates.length} 位候选人的筛选依据`,
                        children: (
                          <Table
                            rowKey="agent_id"
                            size="small"
                            pagination={{ pageSize: 10, showSizeChanger: true }}
                            dataSource={assignment.candidates}
                            scroll={{ x: 620 }}
                            columns={[
                              {
                                title: "人工客服",
                                dataIndex: "agent_id",
                                render: (value: string, candidate) => (
                                  <Space size={4}>
                                    <Text strong>{value}</Text>
                                    {candidate.selected && (
                                      <Tag color="green">已选中</Tag>
                                    )}
                                  </Space>
                                ),
                              },
                              {
                                title: "筛选结果",
                                render: (_value, candidate) =>
                                  candidate.eligible ? (
                                    <Tag color="green">可接单</Tag>
                                  ) : (
                                    <Space wrap size={4}>
                                      {candidate.excluded_reasons.map(
                                        (reason) => (
                                          <Tag color="red" key={reason}>
                                            {reason}
                                          </Tag>
                                        ),
                                      )}
                                    </Space>
                                  ),
                              },
                              {
                                title: "负载",
                                render: (_value, candidate) =>
                                  `${candidate.load}/${candidate.max_conversations}`,
                              },
                              {
                                title: "风险权限",
                                dataIndex: "risk_clearance",
                              },
                              {
                                title: "技能",
                                dataIndex: "skills",
                                render: (value: string[]) =>
                                  value.join("、") || "未限定",
                              },
                            ]}
                          />
                        ),
                      },
                    ]}
                  />
                </Space>
              </Card>
            ))
          )}
        </Space>
      )}
    </Modal>
  );
}
