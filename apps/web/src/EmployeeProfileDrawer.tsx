import {
  Alert,
  Card,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Space,
  Tag,
  Typography,
} from "antd";
import { useQuery } from "@tanstack/react-query";

import {
  listBusinessServiceEntries,
  listDigitalEmployees,
  listEmployeeKnowledgeBindings,
  listEmployeeMcpConnectors,
  listEmployeeSkills,
  listKnowledgeSpaces,
} from "./api";
import {
  domainLabels,
  employeeReadiness,
  entryRoleLabels,
  templateLabels,
  workflowLabels,
} from "./employeeLabels";
import type {
  BusinessServiceEntry,
  DigitalEmployee,
  EmployeeKnowledgeBinding,
  EmployeeMcpBinding,
  EmployeeSkillBinding,
  KnowledgeSpace,
} from "./types";

const { Paragraph, Text, Title } = Typography;

function entryRoles(
  entry: BusinessServiceEntry,
  employeeId: string,
): string[] {
  return entry.employees
    .filter((item) => item.employee_id === employeeId)
    .map(
      (item) =>
        entryRoleLabels[item.role_type] ??
        item.role_type,
    );
}

export default function EmployeeProfileDrawer({
  employee,
  employeeId,
  open,
  onClose,
}: {
  employee?: DigitalEmployee | null;
  employeeId?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const resolvedId = employeeId ?? employee?.id ?? null;
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: open && Boolean(resolvedId) && !employee,
  });
  const current =
    employee ?? employees.data?.find((item) => item.id === resolvedId) ?? null;
  const entries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
    enabled: open && Boolean(resolvedId),
  });
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: open && Boolean(resolvedId),
  });
  const knowledge = useQuery({
    queryKey: ["knowledge-bindings", resolvedId],
    queryFn: () => listEmployeeKnowledgeBindings(resolvedId!),
    enabled: open && Boolean(resolvedId),
  });
  const skills = useQuery({
    queryKey: ["employee-skills", resolvedId],
    queryFn: () => listEmployeeSkills(resolvedId!),
    enabled: open && Boolean(resolvedId),
  });
  const mcp = useQuery({
    queryKey: ["employee-mcp-connectors", resolvedId],
    queryFn: () => listEmployeeMcpConnectors(resolvedId!),
    enabled: open && Boolean(resolvedId),
  });

  const employeeEntries = (entries.data ?? []).filter((entry) =>
    entry.employees.some(
      (item) => item.employee_id === resolvedId && item.enabled,
    ),
  );
  const knowledgeBindings = (knowledge.data ?? []).filter(
    (binding) => binding.enabled,
  );
  const skillBindings = (skills.data ?? []).filter(
    (binding) => binding.enabled,
  );
  const mcpBindings = (mcp.data ?? []).filter(
    (binding) => binding.enabled,
  );
  const spacesById = new Map(
    (spaces.data ?? []).map((space) => [space.id, space]),
  );
  const readiness = current ? employeeReadiness(current) : null;
  const resourceError =
    entries.isError ||
    spaces.isError ||
    knowledge.isError ||
    skills.isError ||
    mcp.isError;
  const resourceLoading =
    entries.isLoading ||
    spaces.isLoading ||
    knowledge.isLoading ||
    skills.isLoading ||
    mcp.isLoading;

  return (
    <Drawer
      title={current ? `员工快照 · ${current.name}` : "员工能力快照"}
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {!current && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {employees.isLoading && <Text type="secondary">正在加载员工信息…</Text>}
          {employees.isError && (
            <Alert
              type="error"
              showIcon
              message="员工信息加载失败"
              description={(employees.error as Error).message}
            />
          )}
          {!employees.isLoading && !employees.isError && (
            <Empty description="未找到这名数字员工" />
          )}
        </Space>
      )}
      {current && (
        <Space direction="vertical" size="large" className="page-stack">
          {resourceError && (
            <Alert
              type="error"
              showIcon
              message="部分员工资源加载失败"
              description="请检查当前身份是否有读取员工、知识或 MCP 配置的权限。"
            />
          )}
          {readiness && (
            <Alert
              type={readiness.color === "green" ? "success" : "info"}
              showIcon
              message={`上岗状态：${readiness.label}`}
              description={readiness.detail}
            />
          )}

          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="员工编码">
              <Text code>{current.employee_key}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag
                color={
                  current.status === "ACTIVE"
                    ? "green"
                    : current.status === "EVALUATION_FAILED"
                      ? "red"
                      : current.status === "TRIAL"
                        ? "orange"
                        : "default"
                }
              >
                {current.status === "ACTIVE"
                  ? "启用"
                  : current.status === "EVALUATION_FAILED"
                    ? "评测未通过"
                    : current.status === "TRIAL"
                      ? "试用中"
                      : "停用"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="岗位">
              {current.template_code
                ? templateLabels[current.template_code] ??
                  current.template_code
                : domainLabels[current.domain] ?? current.domain}
            </Descriptions.Item>
            <Descriptions.Item label="工作流">
              {workflowLabels[current.workflow_key] ??
                current.workflow_key}
            </Descriptions.Item>
            <Descriptions.Item label="服务身份" span={2}>
              {current.service_identity}
            </Descriptions.Item>
            <Descriptions.Item label="配置版本">
              v{current.config_revision}
            </Descriptions.Item>
            <Descriptions.Item label="人工队列">
              {current.handoff_queue}
            </Descriptions.Item>
            <Descriptions.Item label="资源概览" span={2}>
              <Space wrap size={6}>
                <Tag>{employeeEntries.length} 个服务入口</Tag>
                <Tag>{skillBindings.length} 个 Skill</Tag>
                <Tag>{knowledgeBindings.length} 个知识空间</Tag>
                <Tag>{mcpBindings.length} 个 MCP 连接</Tag>
              </Space>
            </Descriptions.Item>
          </Descriptions>

          <Card
            size="small"
            title="服务入口"
            extra={
              employeeEntries.length > 1 ? (
                <Tag color="gold">跨入口复用</Tag>
              ) : undefined
            }
          >
            {resourceLoading && (
              <Text type="secondary">正在加载服务入口…</Text>
            )}
            {!resourceLoading && employeeEntries.length === 0 && (
              <Text type="secondary">
                这名员工还没有加入任何业务入口，暂时不会参与自动派单。
              </Text>
            )}
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              {employeeEntries.map((entry, index) => {
                const roles = entryRoles(entry, current.id);
                const peers = entry.employees
                  .filter(
                    (item) =>
                      item.enabled && item.employee_id !== current.id,
                  )
                  .map((item) => item.employee_name);
                return (
                  <div key={entry.id}>
                    {index > 0 && <Divider style={{ margin: "12px 0" }} />}
                    <Space direction="vertical" size={4}>
                      <Space wrap size={6}>
                        <Text strong>{entry.name}</Text>
                        {roles.map((role) => (
                          <Tag key={role} color="blue">
                            {role}
                          </Tag>
                        ))}
                        <Tag>{entry.employees.length} 名员工</Tag>
                      </Space>
                      <Text type="secondary">
                        同池员工：
                        {peers.length > 0 ? peers.join("、") : "仅此员工"}
                      </Text>
                    </Space>
                  </div>
                );
              })}
            </Space>
          </Card>

          <Card size="small" title={`Skill · ${skillBindings.length} 个`}>
            {skills.isLoading ? (
              <Text type="secondary">正在加载 Skill…</Text>
            ) : skillBindings.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="未绑定 Skill"
              />
            ) : (
              <Space wrap size={6}>
                {skillBindings.map((binding: EmployeeSkillBinding) => (
                  <Tag key={binding.id} color="cyan">
                    {binding.skill_name}
                    <Text type="secondary"> · {binding.skill_code}</Text>
                  </Tag>
                ))}
              </Space>
            )}
          </Card>

          <Card
            size="small"
            title={`知识空间 · ${knowledgeBindings.length} 个`}
          >
            {knowledge.isLoading || spaces.isLoading ? (
              <Text type="secondary">正在加载知识空间…</Text>
            ) : knowledgeBindings.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="未授权知识空间"
              />
            ) : (
              <Space
                direction="vertical"
                size={8}
                style={{ width: "100%" }}
              >
                {knowledgeBindings.map(
                  (binding: EmployeeKnowledgeBinding) => {
                    const space = spacesById.get(
                      binding.knowledge_space_id,
                    ) as KnowledgeSpace | undefined;
                    return (
                      <Space
                        key={binding.id}
                        direction="vertical"
                        size={0}
                      >
                        <Space wrap size={6}>
                          <Text strong>
                            {space?.name ?? binding.knowledge_space_id}
                          </Text>
                          {space && <Tag>{space.code}</Tag>}
                          {binding.workflow_key && (
                            <Tag>
                              {workflowLabels[binding.workflow_key] ??
                                binding.workflow_key}
                            </Tag>
                          )}
                        </Space>
                        <Text type="secondary">
                          {space?.description ?? "已授权该员工检索此知识空间"}
                        </Text>
                      </Space>
                    );
                  },
                )}
              </Space>
            )}
          </Card>

          <Card size="small" title={`MCP 连接 · ${mcpBindings.length} 个`}>
            {mcp.isLoading ? (
              <Text type="secondary">正在加载 MCP 连接…</Text>
            ) : mcpBindings.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="未授权 MCP 工具"
              />
            ) : (
              <Space
                direction="vertical"
                size={10}
                style={{ width: "100%" }}
              >
                {mcpBindings.map((binding: EmployeeMcpBinding) => (
                  <Space
                    key={binding.id}
                    direction="vertical"
                    size={2}
                    style={{ width: "100%" }}
                  >
                    <Space wrap size={6}>
                      <Text strong>{binding.connector_name}</Text>
                      <Tag>{binding.connector_code}</Tag>
                      <Tag
                        color={
                          binding.write_approved ? "orange" : "green"
                        }
                      >
                        {binding.write_approved
                          ? "含写工具授权"
                          : "只读"}
                      </Tag>
                    </Space>
                    <Space wrap size={4}>
                      {binding.allowed_tools.map((tool) => (
                        <Tag key={tool}>{tool}</Tag>
                      ))}
                    </Space>
                  </Space>
                ))}
              </Space>
            )}
          </Card>

          <div>
            <Title level={5}>角色提示词</Title>
            <Paragraph className="employee-instruction">
              {current.instruction?.trim() ||
                "未配置员工级提示词，使用平台默认角色指令。"}
            </Paragraph>
          </div>
        </Space>
      )}
    </Drawer>
  );
}
