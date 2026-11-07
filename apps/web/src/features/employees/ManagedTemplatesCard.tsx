import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createDigitalEmployeeFromTemplate,
  getModelBudget,
  listAgentSkills,
  listEmployeeKnowledgeBindings,
  listEmployeeMcpConnectors,
  listEmployeeSkills,
  listKnowledgeSpaces,
  listManagedEmployeeTemplateRevisions,
  listManagedEmployeeTemplates,
  listMcpConnectors,
  publishManagedEmployeeTemplate,
  reopenManagedEmployeeTemplate,
  reviewManagedEmployeeTemplate,
  rollbackManagedEmployeeTemplate,
  updateDigitalEmployeeConfiguration,
  updateManagedEmployeeTemplate,
} from "../../api";
import { domainLabels, templateLabels, workflowLabels } from "../../employeeLabels";
import { message } from "../../feedback";
import type {
  DigitalEmployee,
  DigitalEmployeeTemplate,
  ManagedEmployeeTemplateRevision,
  McpConnector,
} from "../../types";
import {
  availableTools,
  numberValue,
  objectValue,
  templateStatus,
  templateStatusColor,
} from "./shared";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export type TemplateAction =
  | "APPROVE"
  | "REJECT"
  | "PUBLISH"
  | "ROLLBACK"
  | "REOPEN";

export function templateBindingIds(
  bindings: Array<Record<string, unknown>>,
  key: string,
): string[] {
  return bindings
    .map((binding) => binding[key])
    .filter((value): value is string => typeof value === "string");
}

export function readOnlyToolNames(connector: McpConnector | undefined): string[] {
  return (connector?.tools ?? [])
    .filter((tool) => !tool.is_write)
    .map((tool) => tool.name);
}

export type KnowledgeScopeValues = Record<string, Record<string, string>>;

export const KNOWLEDGE_SCOPE_FIELDS = [
  { key: "audience", label: "受众", placeholder: "例如 support_agent" },
  { key: "org_unit", label: "组织", placeholder: "例如 finance，支持 *" },
  { key: "region", label: "区域", placeholder: "例如 cn-east" },
  { key: "product_id", label: "商品", placeholder: "例如 SKU-1001" },
] as const;

export function knowledgeScopeRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function knowledgeScopeText(
  scope: Record<string, unknown>,
  key: string,
): string {
  const value = scope[key];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === "string")
      .join("，");
  }
  return "";
}

export function knowledgeScopeValues(
  scope: Record<string, unknown> | undefined,
): Record<string, string> {
  const record = scope ?? {};
  return Object.fromEntries(
    KNOWLEDGE_SCOPE_FIELDS.map((field) => [
      field.key,
      knowledgeScopeText(record, field.key),
    ]),
  );
}

export function splitKnowledgeScopeValues(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .split(/[,，\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

export function buildKnowledgeScope(
  existing: Record<string, unknown> | undefined,
  values: Record<string, string> | undefined,
): Record<string, unknown> {
  const scope: Record<string, unknown> = { ...(existing ?? {}) };
  for (const field of KNOWLEDGE_SCOPE_FIELDS) {
    const items = splitKnowledgeScopeValues(values?.[field.key] ?? "");
    if (items.length === 0) {
      delete scope[field.key];
    } else {
      scope[field.key] = items.length === 1 ? items[0] : items;
    }
  }
  return scope;
}

export function withKnowledgeScopeValue(
  previous: KnowledgeScopeValues,
  spaceId: string,
  key: string,
  value: string,
): KnowledgeScopeValues {
  return {
    ...previous,
    [spaceId]: { ...(previous[spaceId] ?? {}), [key]: value },
  };
}

export function templateKnowledgeBindings(
  template: DigitalEmployeeTemplate,
  knowledgeSpaceIds: string[],
  workflowKeys: Record<string, string>,
  scopes: KnowledgeScopeValues,
): Array<Record<string, unknown>> {
  return knowledgeSpaceIds.map((knowledgeSpaceId) => {
    const existing = template.knowledge_bindings.find(
      (binding) => binding.knowledge_space_id === knowledgeSpaceId,
    );
    const workflowKey = (workflowKeys[knowledgeSpaceId] ?? "").trim();
    return {
      ...(existing ?? {
        knowledge_space_id: knowledgeSpaceId,
        scope: {},
        enabled: true,
      }),
      knowledge_space_id: knowledgeSpaceId,
      workflow_key: workflowKey || null,
      scope: buildKnowledgeScope(
        knowledgeScopeRecord(existing?.scope),
        scopes[knowledgeSpaceId],
      ),
    };
  });
}

export function templateMcpBindings(
  template: DigitalEmployeeTemplate,
  connectorIds: string[],
  connectors: McpConnector[],
  allowedTools: Record<string, string[]>,
): Array<Record<string, unknown>> {
  return connectorIds.map((connectorId) => {
    const existing = template.mcp_bindings.find(
      (binding) => binding.connector_id === connectorId,
    );
    return {
      ...(existing ?? {
        connector_id: connectorId,
        write_approved: false,
        enabled: true,
      }),
      connector_id: connectorId,
      allowed_tools:
        allowedTools[connectorId] ??
        readOnlyToolNames(
          connectors.find((item) => item.id === connectorId),
        ),
    };
  });
}

export function ManagedTemplatesCard() {
  const queryClient = useQueryClient();
  const [editTemplate, setEditTemplate] =
    useState<DigitalEmployeeTemplate | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCapabilities, setEditCapabilities] = useState("");
  const [editIntents, setEditIntents] = useState("");
  const [editSkills, setEditSkills] = useState("");
  const [editTools, setEditTools] = useState("");
  const [editKnowledgeSpaceIds, setEditKnowledgeSpaceIds] = useState<
    string[]
  >([]);
  const [editKnowledgeWorkflowKeys, setEditKnowledgeWorkflowKeys] =
    useState<Record<string, string>>({});
  const [editKnowledgeScopes, setEditKnowledgeScopes] =
    useState<KnowledgeScopeValues>({});
  const [editConnectorIds, setEditConnectorIds] = useState<string[]>(
    [],
  );
  const [editMcpTools, setEditMcpTools] = useState<
    Record<string, string[]>
  >({});
  const [confirmTarget, setConfirmTarget] = useState<{
    template: DigitalEmployeeTemplate;
    action: TemplateAction;
  } | null>(null);
  const templates = useQuery({
    queryKey: ["managed-employee-templates"],
    queryFn: listManagedEmployeeTemplates,
    refetchInterval: 10_000,
  });
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: Boolean(editTemplate),
  });
  const connectors = useQuery({
    queryKey: ["mcp-connectors"],
    queryFn: listMcpConnectors,
    enabled: Boolean(editTemplate),
  });
  const action = useMutation({
    mutationFn: (input: {
      templateId: string;
      action: TemplateAction;
    }): Promise<DigitalEmployeeTemplate> => {
      if (input.action === "APPROVE" || input.action === "REJECT") {
        return reviewManagedEmployeeTemplate(input.templateId, {
          decision: input.action,
          note:
            input.action === "APPROVE"
              ? "管理员批准岗位模板"
              : "管理员拒绝岗位模板",
        });
      }
      if (input.action === "PUBLISH") {
        return publishManagedEmployeeTemplate(input.templateId);
      }
      if (input.action === "REOPEN") {
        return reopenManagedEmployeeTemplate(input.templateId);
      }
      return rollbackManagedEmployeeTemplate(input.templateId);
    },
    onSuccess: async (_template, input) => {
      const labels: Record<TemplateAction, string> = {
        APPROVE: "岗位模板已批准",
        REJECT: "岗位模板已拒绝",
        PUBLISH: "岗位模板已发布",
        ROLLBACK: "岗位模板已停用",
        REOPEN: "岗位模板已重新打开",
      };
      message.success(labels[input.action]);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["managed-employee-templates"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["digital-employee-templates"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const saveTemplate = useMutation({
    mutationFn: (template: DigitalEmployeeTemplate) =>
      updateManagedEmployeeTemplate(template.id!, {
        name: editName.trim(),
        description: editDescription.trim(),
        capabilities: editCapabilities
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        intents: editIntents
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        skillCodes: editSkills
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        toolAllowlist: editTools
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        knowledgeBindings: templateKnowledgeBindings(
          template,
          editKnowledgeSpaceIds,
          editKnowledgeWorkflowKeys,
          editKnowledgeScopes,
        ),
        mcpBindings: templateMcpBindings(
          template,
          editConnectorIds,
          connectors.data ?? [],
          editMcpTools,
        ),
      }),
    onSuccess: async () => {
      message.success("模板草案已更新并生成新修订");
      setEditTemplate(null);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["managed-employee-templates"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["managed-template-revisions"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const items = templates.data ?? [];

  const run = (
    template: DigitalEmployeeTemplate,
    templateAction: TemplateAction,
  ) => {
    setConfirmTarget({ template, action: templateAction });
  };

  return (
    <Card
      className="section-card"
      title="自定义岗位模板"
      extra={<Tag>{items.length} 个</Tag>}
    >
      <Paragraph type="secondary">
        自定义模板来自已发布或已回滚的验证草案。模板批准并发布后，
        才能在岗位模板选择器中用于创建新的数字员工。
      </Paragraph>
      {templates.isError && (
        <Alert
          type="error"
          showIcon
          message="自定义模板加载失败"
          description={(templates.error as Error).message}
        />
      )}
      {items.length === 0 ? (
        <Alert
          type="info"
          showIcon
          message="暂无自定义模板"
          description="在已发布或已回滚的员工草案中点击“沉淀为岗位模板”。"
        />
      ) : (
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%" }}
        >
          {items.map((template) => (
            <Card
              key={template.id}
              size="small"
              title={template.name}
              extra={
                <Tag color={templateStatusColor(template.status)}>
                  {templateStatus(template.status)}
                </Tag>
              }
            >
              <Space direction="vertical" size="small">
                <Space wrap>
                  <Text code>{template.code}</Text>
                  <Tag>v{template.version}</Tag>
                  <Tag>{template.domain}</Tag>
                </Space>
                <Space wrap size={4}>
                  {template.capabilities.map((capability) => (
                    <Tag key={capability}>{capability}</Tag>
                  ))}
                </Space>
                {template.source_draft_id && (
                  <Text type="secondary">
                    来源草案：{template.source_draft_id}
                  </Text>
                )}
                <Space wrap>
                  {template.status === "DRAFT" && (
                    <>
                      <Button
                        size="small"
                        onClick={() => {
                          setEditTemplate(template);
                          setEditName(template.name);
                          setEditDescription(template.description);
                          setEditCapabilities(
                            template.capabilities.join("\n"),
                          );
                          setEditIntents(template.intents.join("\n"));
                          setEditSkills(template.skill_codes.join("\n"));
                          setEditTools(
                            template.tool_allowlist.join("\n"),
                          );
                          const knowledgeSpaceIds =
                            templateBindingIds(
                              template.knowledge_bindings,
                              "knowledge_space_id",
                            );
                          setEditKnowledgeSpaceIds(knowledgeSpaceIds);
                          setEditKnowledgeScopes(
                            Object.fromEntries(
                              knowledgeSpaceIds.map((id) => {
                                const binding =
                                  template.knowledge_bindings.find(
                                    (item) =>
                                      item.knowledge_space_id === id,
                                  );
                                return [
                                  id,
                                  knowledgeScopeValues(
                                    knowledgeScopeRecord(binding?.scope),
                                  ),
                                ];
                              }),
                            ),
                          );
                          setEditKnowledgeWorkflowKeys(
                            Object.fromEntries(
                              knowledgeSpaceIds.map((id) => {
                                const binding =
                                  template.knowledge_bindings.find(
                                    (item) =>
                                      item.knowledge_space_id === id,
                                  );
                                const workflowKey =
                                  binding?.workflow_key;
                                return [
                                  id,
                                  typeof workflowKey === "string"
                                    ? workflowKey
                                    : "",
                                ];
                              }),
                            ),
                          );
                          const connectorIds = templateBindingIds(
                            template.mcp_bindings,
                            "connector_id",
                          );
                          setEditConnectorIds(connectorIds);
                          setEditMcpTools(
                            Object.fromEntries(
                              connectorIds.map((id) => {
                                const binding =
                                  template.mcp_bindings.find(
                                    (item) =>
                                      item.connector_id === id,
                                  );
                                const allowedTools =
                                  binding?.allowed_tools;
                                return [
                                  id,
                                  Array.isArray(allowedTools)
                                    ? allowedTools.filter(
                                        (tool: unknown) =>
                                          typeof tool === "string",
                                      )
                                    : [],
                                ];
                              }),
                            ),
                          );
                        }}
                      >
                        编辑模板
                      </Button>
                      <Button
                        size="small"
                        type="primary"
                        onClick={() => run(template, "APPROVE")}
                      >
                        批准模板
                      </Button>
                      <Button
                        size="small"
                        danger
                        onClick={() => run(template, "REJECT")}
                      >
                        拒绝模板
                      </Button>
                    </>
                  )}
                  {template.status === "APPROVED" && (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => run(template, "PUBLISH")}
                    >
                      发布模板
                    </Button>
                  )}
                  {template.status === "PUBLISHED" && (
                    <Button
                      size="small"
                      danger
                      onClick={() => run(template, "ROLLBACK")}
                    >
                      停用模板
                    </Button>
                  )}
                  {(template.status === "REJECTED" ||
                    template.status === "DISABLED") && (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => run(template, "REOPEN")}
                    >
                      重新打开模板
                    </Button>
                  )}
                </Space>
                <TemplateRevisionHistory templateId={template.id!} />
              </Space>
            </Card>
          ))}
        </Space>
      )}
      <Modal
        open={Boolean(confirmTarget)}
        title={
          confirmTarget
            ? {
                APPROVE: "批准岗位模板",
                REJECT: "拒绝岗位模板",
                PUBLISH: "发布岗位模板",
                ROLLBACK: "停用岗位模板",
                REOPEN: "重新打开岗位模板",
              }[confirmTarget.action]
            : ""
        }
        okText="确认"
        cancelText="取消"
        confirmLoading={action.isPending}
        okButtonProps={{
          danger:
            confirmTarget?.action === "REJECT" ||
            confirmTarget?.action === "ROLLBACK",
        }}
        onCancel={() => setConfirmTarget(null)}
        onOk={async () => {
          if (!confirmTarget) return;
          try {
            await action.mutateAsync({
              templateId: confirmTarget.template.id!,
              action: confirmTarget.action,
            });
            setConfirmTarget(null);
          } catch {
            // The mutation displays the API error and keeps the dialog open.
          }
        }}
      >
        {confirmTarget && (
          <Text>
            {confirmTarget.template.name} · 版本 v
            {confirmTarget.template.version}
          </Text>
        )}
      </Modal>
      <Modal
        open={Boolean(editTemplate)}
        title="编辑岗位模板草案"
        okText="保存新修订"
        cancelText="取消"
        width={720}
        confirmLoading={saveTemplate.isPending}
        okButtonProps={{ disabled: !editName.trim() }}
        onCancel={() => setEditTemplate(null)}
        onOk={() => {
          if (editTemplate) saveTemplate.mutate(editTemplate);
        }}
      >
        <Form layout="vertical">
          <Form.Item label="模板名称" required>
            <Input
              value={editName}
              onChange={(event) => setEditName(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="模板说明">
            <TextArea
              rows={2}
              value={editDescription}
              onChange={(event) =>
                setEditDescription(event.target.value)
              }
            />
          </Form.Item>
          <Form.Item label="岗位能力" extra="每行一个">
            <TextArea
              rows={3}
              value={editCapabilities}
              onChange={(event) =>
                setEditCapabilities(event.target.value)
              }
            />
          </Form.Item>
          <Form.Item label="路由意图" extra="每行一个">
            <TextArea
              rows={3}
              value={editIntents}
              onChange={(event) => setEditIntents(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="Skill 编码" extra="每行一个">
            <TextArea
              rows={3}
              value={editSkills}
              onChange={(event) => setEditSkills(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="工具白名单" extra="每行一个">
            <TextArea
              rows={3}
              value={editTools}
              onChange={(event) => setEditTools(event.target.value)}
            />
          </Form.Item>
          <Form.Item
            label="知识空间"
            extra="至少选择一个启用中的知识空间；新增绑定默认适用于全部工作流。"
          >
            <Select
              mode="multiple"
              loading={spaces.isLoading}
              value={editKnowledgeSpaceIds}
              onChange={(ids: string[]) => {
                setEditKnowledgeSpaceIds(ids);
                setEditKnowledgeWorkflowKeys((previous) => {
                  const next = { ...previous };
                  for (const id of ids) {
                    if (!(id in next)) next[id] = "";
                  }
                  return next;
                });
                setEditKnowledgeScopes((previous) => {
                  const next = { ...previous };
                  for (const id of ids) {
                    next[id] ??= knowledgeScopeValues(undefined);
                  }
                  return next;
                });
              }}
              placeholder="选择知识空间"
              options={(spaces.data ?? []).map((space) => ({
                value: space.id,
                label: `${space.name} · ${space.code}`,
                disabled: space.status !== "ACTIVE",
              }))}
            />
          </Form.Item>
          {editKnowledgeSpaceIds.length > 0 && (
            <Form.Item
              label="知识绑定工作流"
              extra="留空时该知识空间适用于员工的全部工作流；适用范围按会话上下文过滤，留空表示不限制，多个值用逗号分隔。"
            >
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                {editKnowledgeSpaceIds.map((id) => {
                  const space = (spaces.data ?? []).find(
                    (item) => item.id === id,
                  );
                  return (
                    <div key={id}>
                      <Text type="secondary">
                        {space
                          ? `${space.name} · ${space.code}`
                          : id}
                      </Text>
                      <Input
                        value={editKnowledgeWorkflowKeys[id] ?? ""}
                        onChange={(event) =>
                          setEditKnowledgeWorkflowKeys(
                            (previous) => ({
                              ...previous,
                              [id]: event.target.value,
                            }),
                          )
                        }
                        placeholder="工作流，例如 finance_review（留空=全部）"
                      />
                      <Space
                        wrap
                        size={8}
                        style={{ marginTop: 8, width: "100%" }}
                      >
                        {KNOWLEDGE_SCOPE_FIELDS.map((field) => (
                          <Input
                            key={field.key}
                            addonBefore={field.label}
                            style={{ width: 240 }}
                            value={
                              editKnowledgeScopes[id]?.[field.key] ?? ""
                            }
                            onChange={(event) =>
                              setEditKnowledgeScopes((previous) =>
                                withKnowledgeScopeValue(
                                  previous,
                                  id,
                                  field.key,
                                  event.target.value,
                                ),
                              )
                            }
                            placeholder={field.placeholder}
                          />
                        ))}
                      </Space>
                    </div>
                  );
                })}
              </Space>
            </Form.Item>
          )}
          <Form.Item
            label="MCP 连接器"
            extra="新增连接默认只授予只读工具；写工具仍需员工级写审批。"
          >
            <Select
              mode="multiple"
              loading={connectors.isLoading}
              value={editConnectorIds}
              onChange={(ids: string[]) => {
                setEditConnectorIds(ids);
                setEditMcpTools((previous) => {
                  const next = { ...previous };
                  for (const id of ids) {
                    next[id] ??= readOnlyToolNames(
                      (connectors.data ?? []).find(
                        (item) => item.id === id,
                      ),
                    );
                  }
                  return next;
                });
              }}
              placeholder="选择 MCP 连接器"
              options={(connectors.data ?? []).map((connector) => ({
                value: connector.id,
                label:
                  connector.status === "ACTIVE"
                    ? `${connector.name} · ${connector.code}`
                    : `${connector.name} · ${connector.code}（${connector.status}）`,
                disabled: connector.status !== "ACTIVE",
              }))}
            />
          </Form.Item>
          {editConnectorIds.length > 0 && (
            <Form.Item
              label="MCP 工具授权"
              extra="写工具在创建员工时不会继承写审批，仍需员工级授权。"
            >
              <Space
                direction="vertical"
                size="small"
                style={{ width: "100%" }}
              >
                {editConnectorIds.map((id) => {
                  const connector = (connectors.data ?? []).find(
                    (item) => item.id === id,
                  );
                  const selected = editMcpTools[id] ?? [];
                  return (
                    <Card
                      key={id}
                      size="small"
                      title={
                        connector
                          ? `${connector.name} · ${connector.code}`
                          : id
                      }
                    >
                      {connector && connector.tools.length > 0 ? (
                        <Checkbox.Group
                          value={selected}
                          options={connector.tools.map((tool) => ({
                            label: tool.is_write
                              ? `${tool.name} · 写工具`
                              : tool.name,
                            value: tool.name,
                            disabled:
                              tool.is_write &&
                              !selected.includes(tool.name),
                          }))}
                          onChange={(values) =>
                            setEditMcpTools((previous) => ({
                              ...previous,
                              [id]: values.map(String),
                            }))
                          }
                        />
                      ) : (
                        <Text type="secondary">
                          连接器尚未发现工具，请先检查连接。
                        </Text>
                      )}
                    </Card>
                  );
                })}
              </Space>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </Card>
  );
}

export function TemplateRevisionHistory({
  templateId,
}: {
  templateId: string;
}) {
  const revisions = useQuery({
    queryKey: ["managed-template-revisions", templateId],
    queryFn: () =>
      listManagedEmployeeTemplateRevisions(templateId),
  });
  const items: ManagedEmployeeTemplateRevision[] =
    revisions.data ?? [];
  if (items.length === 0) return null;
  return (
    <Collapse
      size="small"
      items={[
        {
          key: "revisions",
          label: `版本历史 · ${items.length}`,
          children: (
            <Timeline
              items={items.map((revision) => ({
                color: templateStatusColor(revision.status),
                children: (
                  <Space direction="vertical" size={0}>
                    <Space wrap>
                      <Text strong>v{revision.revision}</Text>
                      <Tag color={templateStatusColor(revision.status)}>
                        {templateStatus(revision.status)}
                      </Tag>
                    </Space>
                    <Text>{revision.change_note || "状态更新"}</Text>
                    <Text type="secondary">
                      {revision.created_by} ·{" "}
                      {new Date(revision.created_at).toLocaleString()}
                    </Text>
                  </Space>
                ),
              }))}
            />
          ),
        },
      ]}
    />
  );
}

export function TemplateEmployeeModal({
  template,
  onClose,
  onCreated,
}: {
  template: DigitalEmployeeTemplate | null;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [knowledgeSpaceIds, setKnowledgeSpaceIds] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: Boolean(template),
  });
  useEffect(() => {
    if (!template) return;
    setName(template.name);
    setKnowledgeSpaceIds([]);
    setInstruction("");
  }, [template]);
  const create = useMutation({
    mutationFn: () => {
      if (!template) throw new Error("请选择员工模板");
      return createDigitalEmployeeFromTemplate({
        name: name.trim(),
        templateCode: template.code,
        knowledgeSpaceIds,
        instruction,
        changeNote: `Created from ${template.code}`,
      });
    },
    onSuccess: async (employee) => {
      message.success(
        employee.status === "TRIAL"
          ? "试用员工已创建，请完成资源检查后评估激活"
          : "数字员工已创建，默认技能和权限已自动配置",
      );
      await onCreated();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Modal
      open={Boolean(template)}
      title={template ? `创建 · ${template.name}` : "创建数字员工"}
      okText="创建员工"
      confirmLoading={create.isPending}
      okButtonProps={{ disabled: !name.trim() }}
      onOk={() => create.mutate()}
      onCancel={onClose}
    >
      {template && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="技术配置已由模板完成"
            description="员工编码、工作流、服务身份、默认工具和专业技能会自动生成。知识空间可现在选择，也可以稍后在业务配置中补充。"
          />
          <Form layout="vertical">
            <Form.Item label="员工名称" required>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="岗位说明">
              <Text>{template.description}</Text>
            </Form.Item>
            <Form.Item label="可以处理">
              <Space wrap>
                {template.capabilities.map((capability) => (
                  <Tag key={capability}>{capability}</Tag>
                ))}
              </Space>
            </Form.Item>
            <Form.Item
              label="绑定知识空间"
              extra="只选择这个岗位需要使用的制度、SOP 或业务知识。"
            >
              <Select
                mode="multiple"
                allowClear
                value={knowledgeSpaceIds}
                onChange={setKnowledgeSpaceIds}
                loading={spaces.isLoading}
                options={(spaces.data ?? [])
                  .filter((space) => space.status === "ACTIVE")
                  .map((space) => ({
                    value: space.id,
                    label: `${space.name} · ${space.code}`,
                  }))}
                placeholder="可稍后配置"
              />
            </Form.Item>
            <Form.Item
              label="角色提示词"
              extra="可选。模板负责技术配置，这里补充该员工的角色、语气和服务边界；创建后仍可修改。"
            >
              <TextArea
                rows={4}
                maxLength={4000}
                showCount
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="例如：先确认订单号；涉及退款只能说明流程并转人工。"
              />
            </Form.Item>
          </Form>
        </Space>
      )}
    </Modal>
  );
}

export function EmployeeConfigDrawer({
  employee,
  advanced,
  onClose,
  onSaved,
}: {
  employee: DigitalEmployee | null;
  advanced: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const [queue, setQueue] = useState("");
  const [instruction, setInstruction] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [knowledgeSpaceIds, setKnowledgeSpaceIds] = useState<string[]>([]);
  const [knowledgeWorkflowKeys, setKnowledgeWorkflowKeys] = useState<
    Record<string, string>
  >({});
  const [knowledgeScopes, setKnowledgeScopes] =
    useState<KnowledgeScopeValues>({});
  const [skillIds, setSkillIds] = useState<string[]>([]);
  const [mcpConnectorIds, setMcpConnectorIds] = useState<string[]>([]);
  const [mcpTools, setMcpTools] = useState<Record<string, string[]>>(
    {},
  );
  const [mcpWriteApproved, setMcpWriteApproved] = useState<
    Record<string, boolean>
  >({});
  const [topK, setTopK] = useState<number | null>(5);
  const [minScore, setMinScore] = useState<number | null>(0.15);
  const [dailyCost, setDailyCost] = useState<number | null>(null);
  const [weeklyCost, setWeeklyCost] = useState<number | null>(null);
  const [monthlyCost, setMonthlyCost] = useState<number | null>(null);
  const budget = useQuery({
    queryKey: ["model-budget", employee?.id],
    queryFn: () => getModelBudget(employee!.id),
    enabled: Boolean(employee),
  });
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: Boolean(employee),
  });
  const knowledgeBindings = useQuery({
    queryKey: ["knowledge-bindings", employee?.id],
    queryFn: () => listEmployeeKnowledgeBindings(employee!.id),
    enabled: Boolean(employee),
  });
  const skills = useQuery({
    queryKey: ["agent-skills"],
    queryFn: listAgentSkills,
    enabled: Boolean(employee),
  });
  const skillBindings = useQuery({
    queryKey: ["employee-skills", employee?.id],
    queryFn: () => listEmployeeSkills(employee!.id),
    enabled: Boolean(employee),
  });
  const mcpConnectors = useQuery({
    queryKey: ["mcp-connectors"],
    queryFn: listMcpConnectors,
    enabled: Boolean(employee),
  });
  const mcpBindings = useQuery({
    queryKey: ["employee-mcp-connectors", employee?.id],
    queryFn: () => listEmployeeMcpConnectors(employee!.id),
    enabled: Boolean(employee),
  });
  const bindingsLoading =
    knowledgeBindings.isLoading ||
    skillBindings.isLoading ||
    mcpBindings.isLoading;
  const bindingsError =
    knowledgeBindings.isError ||
    skillBindings.isError ||
    mcpBindings.isError;
  const defaultKnowledgeScope = objectValue(
    objectValue(employee?.knowledge_policy).default_scope,
  );
  const defaultKnowledgeWorkflow =
    typeof defaultKnowledgeScope.workflow === "string"
      ? defaultKnowledgeScope.workflow
      : "";

  useEffect(() => {
    if (!employee) return;
    const profile = objectValue(employee.model_profile);
    const knowledge = objectValue(profile.knowledge);
    const budgets = objectValue(profile.budgets);
    setName(employee.name);
    setStatus(employee.status);
    setQueue(employee.handoff_queue);
    setInstruction(employee.instruction ?? "");
    setTools(employee.tool_allowlist);
    setTopK(numberValue(knowledge.top_k, 5));
    setMinScore(numberValue(knowledge.min_score, 0.15));
    setDailyCost(
      typeof budgets.daily_cost === "number" ? budgets.daily_cost : null,
    );
    setWeeklyCost(
      typeof budgets.weekly_cost === "number" ? budgets.weekly_cost : null,
    );
    setMonthlyCost(
      typeof budgets.monthly_cost === "number" ? budgets.monthly_cost : null,
    );
  }, [employee]);

  useEffect(() => {
    const enabled = (knowledgeBindings.data ?? []).filter(
      (binding) => binding.enabled,
    );
    setKnowledgeSpaceIds(
      enabled.map((binding) => binding.knowledge_space_id),
    );
    setKnowledgeWorkflowKeys(
      Object.fromEntries(
        enabled.map((binding) => [
          binding.knowledge_space_id,
          binding.workflow_key ?? "",
        ]),
      ),
    );
    setKnowledgeScopes(
      Object.fromEntries(
        enabled.map((binding) => [
          binding.knowledge_space_id,
          knowledgeScopeValues(binding.scope),
        ]),
      ),
    );
  }, [knowledgeBindings.data]);

  useEffect(() => {
    setSkillIds(
      (skillBindings.data ?? [])
        .filter((binding) => binding.enabled)
        .map((binding) => binding.skill_id),
    );
  }, [skillBindings.data]);

  useEffect(() => {
    const enabled = (mcpBindings.data ?? []).filter(
      (binding) => binding.enabled,
    );
    setMcpConnectorIds(
      enabled.map((binding) => binding.connector_id),
    );
    setMcpTools(
      Object.fromEntries(
        enabled.map((binding) => [
          binding.connector_id,
          binding.allowed_tools,
        ]),
      ),
    );
    setMcpWriteApproved(
      Object.fromEntries(
        enabled.map((binding) => [
          binding.connector_id,
          binding.write_approved,
        ]),
      ),
    );
  }, [mcpBindings.data]);

  const save = useMutation({
    mutationFn: async () => {
      if (!employee) throw new Error("未选择数字员工");
      const profile = { ...objectValue(employee.model_profile) };
      profile.knowledge = {
        ...objectValue(profile.knowledge),
        top_k: topK,
        min_score: minScore,
      };
      profile.budgets = {
        ...objectValue(profile.budgets),
        daily_cost: dailyCost,
        weekly_cost: weeklyCost,
        monthly_cost: monthlyCost,
      };
      const existingBySpace = new Map(
        (knowledgeBindings.data ?? []).map((binding) => [
          binding.knowledge_space_id,
          binding,
        ]),
      );
      const existingSkills = new Map(
        (skillBindings.data ?? []).map((binding) => [
          binding.skill_id,
          binding,
        ]),
      );
      const existingMcp = new Map(
        (mcpBindings.data ?? []).map((binding) => [
          binding.connector_id,
          binding,
        ]),
      );
      return updateDigitalEmployeeConfiguration(employee.id, {
        name,
        ...(status === "DISABLED" &&
        employee.status !== "DISABLED"
          ? { status }
          : {}),
        handoff_queue: queue,
        instruction,
        tool_allowlist: tools,
        model_profile: profile,
        knowledge_bindings: knowledgeSpaceIds.map((knowledgeSpaceId) => {
          const existing = existingBySpace.get(knowledgeSpaceId);
          const workflowKey = (
            knowledgeWorkflowKeys[knowledgeSpaceId] ??
            existing?.workflow_key ??
            defaultKnowledgeWorkflow
          ).trim();
          return {
            knowledge_space_id: knowledgeSpaceId,
            workflow_key: workflowKey || null,
            scope: buildKnowledgeScope(
              knowledgeScopeRecord(existing?.scope),
              knowledgeScopes[knowledgeSpaceId],
            ),
            enabled: true,
          };
        }),
        skill_bindings: skillIds.map((skillId, index) => ({
          skill_id: skillId,
          enabled: true,
          priority: existingSkills.get(skillId)?.priority ?? index * 10 + 10,
        })),
        mcp_bindings: mcpConnectorIds.map((connectorId) => {
          const existing = existingMcp.get(connectorId);
          const connector = (mcpConnectors.data ?? []).find(
            (item) => item.id === connectorId,
          );
          return {
            connector_id: connectorId,
            enabled: true,
            allowed_tools:
              mcpTools[connectorId] ??
              existing?.allowed_tools ??
              readOnlyToolNames(connector),
            write_approved:
              mcpWriteApproved[connectorId] ??
              existing?.write_approved ??
              false,
          };
        }),
      });
    },
    onSuccess: async (updated) => {
      message.success(
        updated.status === "TRIAL" &&
          employee?.status === "ACTIVE"
          ? "配置已保存，员工进入试用状态，请重新评测后启用"
          : "数字员工配置已保存",
      );
      await onSaved();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Drawer
      title={employee ? `配置 · ${employee.name}` : "配置数字员工"}
      width={640}
      open={Boolean(employee)}
      onClose={onClose}
      extra={
        <Button
          type="primary"
          loading={save.isPending}
          disabled={
            !employee ||
            !name.trim() ||
            bindingsLoading ||
            bindingsError
          }
          onClick={() => save.mutate()}
        >
          保存配置
        </Button>
      }
    >
      {employee && (
        <Space direction="vertical" size="large" className="page-stack">
          {(bindingsLoading || bindingsError) && (
            <Alert
              type={bindingsError ? "error" : "info"}
              showIcon
              message={
                bindingsError
                  ? "员工资源加载失败，已禁止保存以避免误删绑定"
                  : "正在加载员工现有资源绑定"
              }
              description={
                bindingsError
                  ? "请关闭后重新打开配置，或检查接口后再保存。"
                  : "加载完成前不会提交配置。"
              }
            />
          )}
          {!advanced && (
            <Alert
              type="info"
              showIcon
              message="业务配置"
              description="这里只修改员工名称、角色提示词、知识库和 Skill。模型、MCP、工具白名单与预算请切换到“管理员高级配置”。"
            />
          )}
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="岗位">
              {employee.template_code
                ? templateLabels[employee.template_code] ??
                  employee.template_code
                : domainLabels[employee.domain] ?? employee.domain}
            </Descriptions.Item>
            <Descriptions.Item label="工作流">
              {workflowLabels[employee.workflow_key] ?? employee.workflow_key}
            </Descriptions.Item>
            {advanced && (
              <>
                <Descriptions.Item label="岗位标识">
                  {employee.employee_key}
                </Descriptions.Item>
                <Descriptions.Item label="服务身份" span={2}>
                  {employee.service_identity}
                </Descriptions.Item>
              </>
            )}
            <Descriptions.Item label="配置版本">
              v{employee.config_revision}
            </Descriptions.Item>
          </Descriptions>

          <Form layout="vertical">
            <Form.Item label="员工名称">
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Form.Item>
            <Space size="middle" align="start" className="form-row">
              <Form.Item label="状态">
                <Select
                  value={status}
                  onChange={setStatus}
                  disabled={employee.status !== "ACTIVE"}
                  options={
                    employee.status === "ACTIVE"
                      ? [
                          { value: "ACTIVE", label: "启用" },
                          { value: "DISABLED", label: "停用" },
                        ]
                      : [
                          {
                            value: employee.status,
                            label:
                              employee.status === "TRIAL"
                                ? "试用中，需评测后启用"
                                : employee.status === "EVALUATION_FAILED"
                                  ? "评测未通过"
                                  : "已停用，需重新评测后启用",
                          },
                        ]
                  }
                  style={{ width: 160 }}
                />
              </Form.Item>
              {advanced && (
                <Form.Item label="人工队列">
                  <Input
                    value={queue}
                    onChange={(event) => setQueue(event.target.value)}
                  />
                </Form.Item>
              )}
            </Space>
            <Form.Item
              label="角色提示词"
              extra="补充该员工的角色、语气和服务边界。不会覆盖平台安全约束、知识事实和人工审批规则；留空表示使用系统默认。"
            >
              <TextArea
                rows={5}
                maxLength={4000}
                showCount
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                placeholder="例如：你是一名耐心、简洁的售后客服，先确认订单号；涉及退款只能说明流程并转人工。"
              />
            </Form.Item>
            {advanced && (
              <Form.Item label="工具权限">
                <Checkbox.Group
                  value={tools}
                  onChange={(values) => setTools(values as string[])}
                  options={availableTools.map((tool) => ({
                    label: tool,
                    value: tool,
                  }))}
                />
              </Form.Item>
            )}
            <Form.Item
              label="绑定知识空间"
              extra="员工只能检索这里授权的知识空间；未绑定时不返回知识。"
            >
              <Select
                mode="multiple"
                allowClear
                value={knowledgeSpaceIds}
                onChange={(ids: string[]) => {
                  setKnowledgeSpaceIds(ids);
                  setKnowledgeWorkflowKeys((previous) => {
                    const next = { ...previous };
                    for (const id of ids) {
                      next[id] ??= defaultKnowledgeWorkflow;
                    }
                    return next;
                  });
                  setKnowledgeScopes((previous) => {
                    const next = { ...previous };
                    for (const id of ids) {
                      next[id] ??= knowledgeScopeValues(undefined);
                    }
                    return next;
                  });
                }}
                placeholder="选择允许该员工使用的知识空间"
                loading={spaces.isLoading}
                options={(spaces.data ?? [])
                  .filter((space) => space.status === "ACTIVE")
                  .map((space) => ({
                    value: space.id,
                    label: `${space.name} · ${space.code}`,
                  }))}
              />
            </Form.Item>
            {advanced && knowledgeSpaceIds.length > 0 && (
              <Form.Item
                label="知识绑定工作流"
                extra="留空时该知识空间适用于员工的全部工作流；适用范围按会话上下文过滤，留空表示不限制，多个值用逗号分隔。"
              >
                <Space
                  direction="vertical"
                  size="small"
                  style={{ width: "100%" }}
                >
                  {knowledgeSpaceIds.map((id) => {
                    const space = (spaces.data ?? []).find(
                      (item) => item.id === id,
                    );
                    return (
                      <div key={id}>
                        <Text type="secondary">
                          {space
                            ? `${space.name} · ${space.code}`
                            : id}
                        </Text>
                        <Input
                          value={
                            knowledgeWorkflowKeys[id] ??
                            defaultKnowledgeWorkflow
                          }
                          onChange={(event) =>
                            setKnowledgeWorkflowKeys(
                              (previous) => ({
                                ...previous,
                                [id]: event.target.value,
                              }),
                            )
                          }
                          placeholder="例如 finance_review（留空=全部）"
                        />
                        <Space
                          wrap
                          size={8}
                          style={{ marginTop: 8, width: "100%" }}
                        >
                          {KNOWLEDGE_SCOPE_FIELDS.map((field) => (
                            <Input
                              key={field.key}
                              addonBefore={field.label}
                              style={{ width: 240 }}
                              value={
                                knowledgeScopes[id]?.[field.key] ?? ""
                              }
                              onChange={(event) =>
                                setKnowledgeScopes((previous) =>
                                  withKnowledgeScopeValue(
                                    previous,
                                    id,
                                    field.key,
                                    event.target.value,
                                  ),
                                )
                              }
                              placeholder={field.placeholder}
                            />
                          ))}
                        </Space>
                      </div>
                    );
                  })}
                </Space>
              </Form.Item>
            )}
            <Form.Item
              label={advanced ? "Skill（岗位规程）" : "专业技能"}
              extra="LangGraph 会根据当前问题命中的触发词选择 Skill；停用的 Skill 不会进入运行时。"
            >
              <Select
                mode="multiple"
                allowClear
                value={skillIds}
                onChange={setSkillIds}
                placeholder="选择该员工可用的 Skills"
                loading={skills.isLoading}
                options={(skills.data ?? [])
                  .filter((skill) => skill.status === "ACTIVE")
                  .map((skill) => ({
                    value: skill.id,
                    label: `${skill.name} · ${skill.code}`,
                  }))}
              />
            </Form.Item>
            {advanced && (
              <>
                <Form.Item
                  label="MCP（业务工具）"
                  extra="连接订单、客户、工单等外部系统；仅授权已发现的工具，写工具仍需单独审批。"
                >
                  <Select
                    mode="multiple"
                    allowClear
                    value={mcpConnectorIds}
                    onChange={(ids: string[]) => {
                      setMcpConnectorIds(ids);
                      setMcpTools((previous) => {
                        const next = { ...previous };
                        for (const id of ids) {
                          next[id] ??= readOnlyToolNames(
                            (mcpConnectors.data ?? []).find(
                              (item) => item.id === id,
                            ),
                          );
                        }
                        return next;
                      });
                      setMcpWriteApproved((previous) => {
                        const next = { ...previous };
                        for (const id of ids) {
                          if (!(id in next)) next[id] = false;
                        }
                        return next;
                      });
                    }}
                    placeholder="选择该员工可用的 MCP 连接器"
                    loading={mcpConnectors.isLoading}
                    options={(mcpConnectors.data ?? [])
                      .filter((connector) => connector.status === "ACTIVE")
                      .map((connector) => ({
                        value: connector.id,
                        label: `${connector.name} · ${connector.code}`,
                      }))}
                  />
                </Form.Item>
                {mcpConnectorIds.length > 0 && (
                  <Form.Item
                    label="MCP 工具授权"
                    extra="可逐项授权工具；写工具必须勾选“允许发起写审批”才能在运行时发起审批，审批人不能是请求人。"
                  >
                    <Space
                      direction="vertical"
                      size="small"
                      style={{ width: "100%" }}
                    >
                      {mcpConnectorIds.map((id) => {
                        const connector = (
                          mcpConnectors.data ?? []
                        ).find((item) => item.id === id);
                        const selected = mcpTools[id] ?? [];
                        const writeToolNames = (
                          connector?.tools ?? []
                        )
                          .filter((tool) => tool.is_write)
                          .map((tool) => tool.name);
                        const hasWriteTool = writeToolNames.some(
                          (name) => selected.includes(name),
                        );
                        return (
                          <Card
                            key={id}
                            size="small"
                            title={
                              connector
                                ? `${connector.name} · ${connector.code}`
                                : id
                            }
                          >
                            {connector && connector.tools.length > 0 ? (
                              <>
                                <Checkbox.Group
                                  value={selected}
                                  options={connector.tools.map(
                                    (tool) => ({
                                      label: tool.is_write
                                        ? `${tool.name} · 写工具`
                                        : tool.name,
                                      value: tool.name,
                                    }),
                                  )}
                                  onChange={(values) => {
                                    const allowed = values.map(String);
                                    setMcpTools((previous) => ({
                                      ...previous,
                                      [id]: allowed,
                                    }));
                                    if (
                                      !writeToolNames.some((name) =>
                                        allowed.includes(name),
                                      )
                                    ) {
                                      setMcpWriteApproved(
                                        (previous) => ({
                                          ...previous,
                                          [id]: false,
                                        }),
                                      );
                                    }
                                  }}
                                />
                                <div style={{ marginTop: 8 }}>
                                  <Checkbox
                                    checked={
                                      mcpWriteApproved[id] ?? false
                                    }
                                    disabled={!hasWriteTool}
                                    onChange={(event) =>
                                      setMcpWriteApproved(
                                        (previous) => ({
                                          ...previous,
                                          [id]: event.target.checked,
                                        }),
                                      )
                                    }
                                  >
                                    允许发起写审批
                                  </Checkbox>
                                </div>
                              </>
                            ) : (
                              <Text type="secondary">
                                连接器尚未发现工具，请先检查连接。
                              </Text>
                            )}
                          </Card>
                        );
                      })}
                    </Space>
                  </Form.Item>
                )}
              </>
            )}
            {advanced && (
              <Space size="middle" align="start" className="form-row">
              <Form.Item label="知识检索 Top-K">
                <InputNumber
                  min={1}
                  max={20}
                  value={topK}
                  onChange={setTopK}
                />
              </Form.Item>
              <Form.Item label="最低相关度">
                <InputNumber
                  min={0}
                  max={1}
                  step={0.01}
                  value={minScore}
                  onChange={setMinScore}
                />
              </Form.Item>
              </Space>
            )}
            {advanced && (
              <Space size="middle" align="start" className="form-row">
              <Form.Item label="日费用上限">
                <InputNumber min={0} value={dailyCost} onChange={setDailyCost} />
              </Form.Item>
              <Form.Item label="周费用上限">
                <InputNumber min={0} value={weeklyCost} onChange={setWeeklyCost} />
              </Form.Item>
              <Form.Item label="月费用上限">
                <InputNumber min={0} value={monthlyCost} onChange={setMonthlyCost} />
              </Form.Item>
              </Space>
            )}
          </Form>

          {advanced && (
          <Card size="small" title="当前预算与用量">
            {budget.isLoading && <Text type="secondary">正在加载预算…</Text>}
            {budget.data && (
              <Space direction="vertical" size="middle" className="page-stack">
                {budget.data.periods.map((period) => (
                  <div key={period.period}>
                    <Space>
                      <Text strong>
                        {period.period === "daily"
                          ? "今日"
                          : period.period === "weekly"
                            ? "本周"
                            : "本月"}
                      </Text>
                      <Tag>调用 {period.usage.calls ?? 0}</Tag>
                      <Tag>Token {period.usage.tokens ?? 0}</Tag>
                      <Tag>费用 {Number(period.usage.cost ?? 0).toFixed(3)}</Tag>
                      {period.alerts.map((alert) => (
                        <Tag key={alert} color="red">
                          {alert}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                ))}
              </Space>
            )}
          </Card>
          )}

          {advanced && (
          <Card size="small" title="权限说明">
            <TextArea
              readOnly
              autoSize={{ minRows: 3, maxRows: 6 }}
              value={JSON.stringify(
                {
                  knowledge_policy: employee.knowledge_policy,
                  model_profile: employee.model_profile,
                },
                null,
                2,
              )}
            />
          </Card>
          )}
        </Space>
      )}
    </Drawer>
  );
}
