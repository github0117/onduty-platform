import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createEmployeeDraft,
  executeWorkforceTask,
  listEmployeeDrafts,
  listWorkforceTasks,
  planWorkforceTask,
  reassessWorkforceTask,
  retryWorkforceTask,
} from "../../api";
import { message } from "../../feedback";
import {
  RouteEvidence,
  draftStatus,
  draftStatusColor,
  normalizedRouteReason,
  objectArray,
  readinessStatus,
  readinessStatusColor,
  routeReasonColor,
  routeReasonLabels,
  workforceStatus,
  workforceStatusColor,
} from "./shared";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export function SupervisorTaskCard() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const tasks = useQuery({
    queryKey: ["workforce-tasks"],
    queryFn: listWorkforceTasks,
    refetchInterval: 10_000,
  });
  const employeeDrafts = useQuery({
    queryKey: ["employee-drafts"],
    queryFn: listEmployeeDrafts,
  });
  const plan = useMutation({
    mutationFn: () =>
      planWorkforceTask({
        title: title.trim(),
        objective: objective.trim(),
      }),
    onSuccess: async () => {
      message.success("主管数字员工已生成任务计划和员工分工");
      setTitle("");
      setObjective("");
      await queryClient.invalidateQueries({ queryKey: ["workforce-tasks"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const execute = useMutation({
    mutationFn: (taskId: string) => executeWorkforceTask(taskId),
    onSuccess: async () => {
      message.success("主管任务已提交执行，专业员工正在处理");
      await queryClient.invalidateQueries({ queryKey: ["workforce-tasks"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const retry = useMutation({
    mutationFn: (taskId: string) => retryWorkforceTask(taskId),
    onSuccess: async () => {
      message.success("失败子任务已重置，可以重新执行");
      await queryClient.invalidateQueries({ queryKey: ["workforce-tasks"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const reassess = useMutation({
    mutationFn: (taskId: string) => reassessWorkforceTask(taskId),
    onSuccess: async (task) => {
      const gapCount = task.capability_gaps.length;
      message.success(
        gapCount > 0
          ? `能力检查已刷新，仍有 ${gapCount} 个缺口`
          : "能力检查已刷新，当前没有能力缺口",
      );
      await queryClient.invalidateQueries({
        queryKey: ["workforce-tasks"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const createDraft = useMutation({
    mutationFn: (input: {
      taskId: string;
      requiredCapability: string;
      name: string;
    }) =>
      createEmployeeDraft(input.taskId, {
        requiredCapability: input.requiredCapability,
        name: input.name,
      }),
    onSuccess: async () => {
      message.success("员工草案已创建，请继续评审和试用");
      await queryClient.invalidateQueries({
        queryKey: ["employee-drafts"],
      });
    },
    onError: async (error: Error) => {
      if (
        error instanceof ApiError &&
        error.code === "EMPLOYEE_DRAFT_EXISTS"
      ) {
        message.warning("该能力已有员工草案，请前往草案与发布页面处理");
        await queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        });
        return;
      }
      message.error(error.message);
    },
  });
  const taskItems = useMemo(
    () => tasks.data?.items ?? [],
    [tasks.data?.items],
  );
  const selectedTask =
    taskItems.find((task) => task.id === selectedTaskId) ??
    taskItems[0];
  useEffect(() => {
    if (taskItems.length === 0) {
      setSelectedTaskId("");
      return;
    }
    if (!taskItems.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(taskItems[0].id);
    }
  }, [selectedTaskId, taskItems]);
  const selectedTaskHasFailedSteps =
    selectedTask?.steps.some((step) => step.status === "FAILED") ?? false;
  const capabilityGaps = selectedTask?.capability_gaps ?? [];
  const employeeReadiness = selectedTask?.employee_readiness ?? [];
  const readinessBlocked = employeeReadiness.some(
    (employee) => employee.status === "BLOCKED",
  );
  const readinessDegraded = employeeReadiness.filter(
    (employee) => employee.status === "DEGRADED",
  );

  return (
    <Card
      className="section-card"
      title="主管数字员工"
      extra={<Tag>{tasks.data?.total ?? 0} 个任务</Tag>}
    >
      <Paragraph type="secondary">
        输入一个复杂目标，主管员工会拆解子任务，并按能力自动分配给专业数字员工。
        当前阶段生成可审核的任务计划，高风险外部动作仍需进入审批。
      </Paragraph>
      <Form layout="vertical">
        <Form.Item label="任务名称" required>
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          placeholder="例如：跨部门审批与资料补充"
          />
        </Form.Item>
        <Form.Item label="目标和要求" required>
          <TextArea
            rows={4}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="描述要解决的问题、需要哪些专业能力以及人工确认点。"
          />
        </Form.Item>
        <Button
          type="primary"
          loading={plan.isPending}
          disabled={!title.trim() || !objective.trim()}
          onClick={() => plan.mutate()}
        >
          生成任务分工
        </Button>
      </Form>
      {taskItems.length > 1 && (
        <Form.Item label="查看主管任务" style={{ marginTop: 20 }}>
          <Select
            value={selectedTask?.id}
            onChange={setSelectedTaskId}
            options={taskItems.map((task) => ({
              value: task.id,
              label: `${task.title} · ${workforceStatus(task.status)}`,
            }))}
          />
        </Form.Item>
      )}
      {selectedTask && (
        <Card
          size="small"
          title={selectedTask.title}
          style={{ marginTop: 20 }}
        >
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Space wrap>
              <Tag color="purple">
                主管：{selectedTask.supervisor_employee_name ?? "自动选择"}
              </Tag>
              <Tag color={workforceStatusColor(selectedTask.status)}>
                {workforceStatus(selectedTask.status)}
              </Tag>
              {(selectedTask.status === "PLAN_READY" ||
                selectedTask.status === "NEEDS_REVIEW") && (
                <Button
                  size="small"
                  loading={
                    reassess.isPending &&
                    reassess.variables === selectedTask.id
                  }
                  onClick={() => reassess.mutate(selectedTask.id)}
                >
                  重新检查能力与就绪度
                </Button>
              )}
              {selectedTask.status === "PLAN_READY" && (
                <Button
                  type="primary"
                  size="small"
                  loading={execute.isPending}
                  disabled={
                    capabilityGaps.length > 0 || readinessBlocked
                  }
                  onClick={() => execute.mutate(selectedTask.id)}
                >
                  执行任务分工
                </Button>
              )}
              {selectedTaskHasFailedSteps && (
                <Button
                  size="small"
                  loading={retry.isPending}
                  onClick={() => retry.mutate(selectedTask.id)}
                >
                  重试失败步骤
                </Button>
              )}
            </Space>
            {employeeReadiness.length > 0 && (
              <>
                {(readinessDegraded.length > 0 || readinessBlocked) && (
                  <Alert
                    type={readinessBlocked ? "error" : "warning"}
                    showIcon
                    message={
                      readinessBlocked
                        ? "存在阻塞执行的数字员工"
                        : `${readinessDegraded.length} 个数字员工处于降级状态`
                    }
                    description={
                      readinessBlocked
                        ? "请先恢复员工状态和工具权限，再执行任务。"
                        : "岗位能力已匹配，但知识库、Skill 或实时业务工具仍有缺失；任务可以执行，但结果可能需要人工补证。"
                    }
                  />
                )}
                <Collapse
                  size="small"
                  items={[
                    {
                      key: "employee-readiness",
                      label: `员工能力就绪度 · ${employeeReadiness.length}`,
                      children: (
                        <Space
                          direction="vertical"
                          size="middle"
                          style={{ width: "100%" }}
                        >
                          {employeeReadiness.map((employee) => (
                            <Card
                              key={employee.employee_id}
                              size="small"
                              title={employee.employee_name}
                              extra={
                                <Tag
                                  color={readinessStatusColor(
                                    employee.status,
                                  )}
                                >
                                  {readinessStatus(employee.status)}
                                </Tag>
                              }
                            >
                              <Space
                                direction="vertical"
                                size="small"
                                style={{ width: "100%" }}
                              >
                                <Space wrap>
                                  {employee.step_sequences.map(
                                    (sequence) => (
                                      <Tag key={sequence}>
                                        步骤 {sequence}
                                      </Tag>
                                    ),
                                  )}
                                </Space>
                                <Descriptions
                                  size="small"
                                  column={1}
                                  items={employee.checks.map((check) => ({
                                    key: check.key,
                                    label: (
                                      <Space size={4}>
                                        <Tag
                                          color={readinessStatusColor(
                                            check.status,
                                          )}
                                        >
                                          {readinessStatus(check.status)}
                                        </Tag>
                                        {check.label}
                                      </Space>
                                    ),
                                    children: check.detail,
                                  }))}
                                />
                              </Space>
                            </Card>
                          ))}
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            )}
            {capabilityGaps.length > 0 && (
              <>
                <Alert
                  type="warning"
                  showIcon
                  message={`发现 ${capabilityGaps.length} 个能力缺口`}
                  description="当前任务暂时由兜底或非专业员工承担。请先审核员工草案并创建缺失岗位，系统不会自动创建或上线。"
                />
                <Collapse
                  size="small"
                  items={[
                    {
                      key: "capability-gaps",
                      label: `能力缺口与员工草案 · ${capabilityGaps.length}`,
                      children: (
                        <Space
                          direction="vertical"
                          size="middle"
                          style={{ width: "100%" }}
                        >
                          {capabilityGaps.map((gap) => {
                            const existingDraft =
                              employeeDrafts.data?.items.find(
                                (draft) =>
                                  draft.source_task_id === selectedTask.id &&
                                  draft.required_capability ===
                                    gap.required_capability,
                              );
                            return (
                            <Card
                              key={
                                gap.step_id ??
                                `task-capability:${gap.required_capability}`
                              }
                              size="small"
                              title={
                                gap.sequence === null
                                  ? gap.step_title
                                  : `${gap.sequence}. ${gap.step_title}`
                              }
                              extra={<Tag color="orange">仅草案</Tag>}
                            >
                              <Space
                                direction="vertical"
                                size="small"
                                style={{ width: "100%" }}
                              >
                                <Text>
                                  缺少能力：
                                  <Text strong>
                                    {gap.required_capability}
                                  </Text>
                                </Text>
                                <Text type="secondary">
                                  当前负责人：{gap.assigned_employee_name}
                                </Text>
                                <Text type="warning">{gap.reason}</Text>
                                <Descriptions
                                  size="small"
                                  column={1}
                                  items={[
                                    {
                                      key: "template",
                                      label: "建议模板",
                                      children: gap.recommended_template_name,
                                    },
                                    {
                                      key: "capabilities",
                                      label: "建议能力",
                                      children: (
                                        <Space wrap size={4}>
                                          {gap.recommended_capabilities.map(
                                            (value) => (
                                              <Tag key={value}>{value}</Tag>
                                            ),
                                          )}
                                        </Space>
                                      ),
                                    },
                                    {
                                      key: "skills",
                                      label: "建议 Skill",
                                      children: (
                                        <Space wrap size={4}>
                                          {gap.recommended_skills.map(
                                            (value) => (
                                              <Tag color="purple" key={value}>
                                                {value}
                                              </Tag>
                                            ),
                                          )}
                                        </Space>
                                      ),
                                    },
                                    {
                                      key: "tools",
                                      label: "建议工具",
                                      children: (
                                        <Space wrap size={4}>
                                          {gap.recommended_tools.map(
                                            (value) => (
                                              <Tag color="blue" key={value}>
                                                {value}
                                              </Tag>
                                            ),
                                          )}
                                        </Space>
                                      ),
                                    },
                                  ]}
                                />
                                <Space wrap>
                                  {existingDraft ? (
                                    <>
                                      <Tag
                                        color={draftStatusColor(
                                          existingDraft.status,
                                        )}
                                      >
                                        已有草案：
                                        {draftStatus(existingDraft.status)}
                                      </Tag>
                                      <Button
                                        size="small"
                                        onClick={() =>
                                          window.location.assign(
                                            "/employees/drafts",
                                          )
                                        }
                                      >
                                        查看已有草案
                                      </Button>
                                    </>
                                  ) : (
                                    <Button
                                      size="small"
                                      type="primary"
                                      loading={
                                        createDraft.isPending &&
                                        createDraft.variables
                                          ?.requiredCapability ===
                                          gap.required_capability
                                      }
                                      disabled={employeeDrafts.isLoading}
                                      onClick={() =>
                                        createDraft.mutate({
                                          taskId: selectedTask.id,
                                          requiredCapability:
                                            gap.required_capability,
                                          name: gap.recommended_template_name,
                                        })
                                      }
                                    >
                                      {employeeDrafts.isLoading
                                        ? "正在检查草案"
                                        : "生成员工草案"}
                                    </Button>
                                  )}
                                  {!gap.recommended_template_code && (
                                    <Tag color="red">
                                      暂无现成模板，将创建自定义草案
                                    </Tag>
                                  )}
                                  <Text type="secondary">
                                    草案需经过评审、试用、评测后才能发布
                                  </Text>
                                </Space>
                              </Space>
                            </Card>
                            );
                          })}
                        </Space>
                      ),
                    },
                  ]}
                />
              </>
            )}
            {selectedTask.status === "NEEDS_REVIEW" &&
              !selectedTaskHasFailedSteps && (
                <Alert
                  type="warning"
                  showIcon
                  message="需要人工补充事实"
                  description="专业员工已完成分析，但业务记录、流程或制度依据不足。请补充真实数据后再决定是否重新执行。"
                />
              )}
            <Timeline
              items={selectedTask.steps.map((step) => {
                const toolCalls = objectArray(step.output.tool_calls);
                const citations = objectArray(step.output.citations);
                return {
                  color: workforceStatusColor(step.status),
                  children: (
                    <Space direction="vertical" size="small">
                      <Space wrap>
                        <Text strong>
                          {step.sequence}. {step.title}
                        </Text>
                        <Tag color={workforceStatusColor(step.status)}>
                          {workforceStatus(step.status)}
                        </Tag>
                      </Space>
                      <Text type="secondary">
                        负责人：{step.assigned_employee_name}
                      </Text>
                      <Space wrap size={4}>
                        <Tag>岗位能力：{step.required_capability ?? "未记录"}</Tag>
                        <Tag color={routeReasonColor(step.route_reason_code)}>
                          {routeReasonLabels[step.route_reason_code ?? ""] ??
                            "系统自动判断"}
                        </Tag>
                        {step.route_confidence !== null && (
                          <Tag>
                            置信度{" "}
                            {(step.route_confidence * 100).toFixed(0)}%
                          </Tag>
                        )}
                      </Space>
                      {step.route_reason && (
                        <Text type="secondary">
                          {normalizedRouteReason(
                            step.route_reason,
                            step.route_reason_code,
                            step.route_candidates,
                          )}
                        </Text>
                      )}
                      <Text>{step.instructions}</Text>
                      {step.route_candidates.length > 0 && (
                        <Collapse
                          size="small"
                          items={[
                            {
                              key: "route-evidence",
                              label: `为什么分配给这位员工 · ${step.route_candidates.length} 个候选`,
                              children: (
                                <RouteEvidence
                                  candidates={step.route_candidates}
                                />
                              ),
                            },
                          ]}
                        />
                      )}
                      {String(step.output.summary ?? "") && (
                        <Alert
                          style={{ marginTop: 6 }}
                          type={
                            step.output.requires_human
                              ? "warning"
                              : "success"
                          }
                          showIcon
                          message={String(step.output.summary)}
                          description={
                            Array.isArray(step.output.findings)
                              ? (step.output.findings as string[]).join("；")
                              : undefined
                          }
                        />
                      )}
                      {toolCalls.length > 0 && (
                        <Collapse
                          size="small"
                          items={[
                            {
                              key: "tools",
                              label: `工具调用 · ${toolCalls.length}`,
                              children: (
                                <Space
                                  direction="vertical"
                                  size="small"
                                  style={{ width: "100%" }}
                                >
                                  {toolCalls.map((call, index) => (
                                    <Card
                                      key={String(
                                        call.tool_call_id ?? index,
                                      )}
                                      size="small"
                                    >
                                      <Space wrap>
                                        <Tag
                                          color={workforceStatusColor(
                                            String(call.status ?? ""),
                                          )}
                                        >
                                          {workforceStatus(
                                            String(call.status ?? "UNKNOWN"),
                                          )}
                                        </Tag>
                                        <Text code>
                                          {String(
                                            call.tool_id ?? "工具规划",
                                          )}
                                        </Text>
                                        {typeof call.duration_ms ===
                                          "number" && (
                                          <Text type="secondary">
                                            {call.duration_ms}ms
                                          </Text>
                                        )}
                                      </Space>
                                      {Boolean(call.error_message) && (
                                        <Paragraph
                                          type="danger"
                                          style={{ marginTop: 8 }}
                                        >
                                          {String(call.error_message)}
                                        </Paragraph>
                                      )}
                                    </Card>
                                  ))}
                                </Space>
                              ),
                            },
                          ]}
                        />
                      )}
                      {citations.length > 0 && (
                        <Collapse
                          size="small"
                          items={[
                            {
                              key: "citations",
                              label: `证据引用 · ${citations.length}`,
                              children: (
                                <Space
                                  direction="vertical"
                                  size="small"
                                  style={{ width: "100%" }}
                                >
                                  {citations.map((citation, index) => {
                                    const sourceType = String(
                                      citation.source_type ?? "knowledge",
                                    );
                                    return (
                                      <Space
                                        key={String(
                                          citation.chunk_id ?? index,
                                        )}
                                        wrap
                                      >
                                        <Tag
                                          color={
                                            sourceType === "mcp"
                                              ? "blue"
                                              : sourceType ===
                                                  "workflow_step"
                                                ? "purple"
                                                : "default"
                                          }
                                        >
                                          {sourceType === "mcp"
                                            ? "MCP 实时结果"
                                            : sourceType === "workflow_step"
                                              ? "前序步骤"
                                              : "知识引用"}
                                        </Tag>
                                        <Text>
                                          {String(
                                            citation.title ??
                                              citation.chunk_id ??
                                              "未命名来源",
                                          )}
                                        </Text>
                                        {Boolean(citation.version) && (
                                          <Text type="secondary">
                                            {String(citation.version)}
                                          </Text>
                                        )}
                                      </Space>
                                    );
                                  })}
                                </Space>
                              ),
                            },
                          ]}
                        />
                      )}
                      {step.error_message && (
                        <Text type="danger">
                          {step.error_message}
                        </Text>
                      )}
                    </Space>
                  ),
                };
              })}
            />
            {selectedTask.result_summary && (
              <Alert
                type="info"
                showIcon
                message="主管汇总"
                description={selectedTask.result_summary}
              />
            )}
          </Space>
        </Card>
      )}
    </Card>
  );
}
