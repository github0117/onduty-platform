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
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  ApiError,
  activateDigitalEmployee,
  createAgentSkill,
  createDigitalEmployee,
  createDigitalEmployeeFromTemplate,
  createEmployeeDraft,
  createEmployeeDraftTrial,
  evaluateEmployeeDraft,
  executeWorkforceTask,
  createMcpConnector,
  discoverMcpConnector,
  getModelBudget,
  listAgentSkills,
  listBusinessServiceEntries,
  listDigitalEmployees,
  listDigitalEmployeeTemplates,
  listDigitalEmployeeRouteDecisions,
  listDigitalEmployeeRouteRules,
  listEmployeeDraftRevisions,
  listEmployeeDrafts,
  listEmployeeKnowledgeBindings,
  listEmployeeMcpConnectors,
  listEmployeeSkills,
  listKnowledgeSpaces,
  listManagedEmployeeTemplateRevisions,
  listManagedEmployeeTemplates,
  listMcpConnectors,
  listWorkforceTasks,
  planWorkforceTask,
  promoteEmployeeDraftToTemplate,
  publishEmployeeDraft,
  publishManagedEmployeeTemplate,
  replaceBusinessServiceEntryEmployees,
  reassessWorkforceTask,
  reopenEmployeeDraft,
  reviewEmployeeDraft,
  reviewManagedEmployeeTemplate,
  reopenManagedEmployeeTemplate,
  retryWorkforceTask,
  rollbackEmployeeDraft,
  rollbackManagedEmployeeTemplate,
  updateAgentSkill,
  updateDigitalEmployeeConfiguration,
  updateEmployeeDraft,
  updateManagedEmployeeTemplate,
  updateDigitalEmployeeRouteRule,
  updateMcpConnector,
} from "./api";
import type {
  AgentSkill,
  BusinessServiceEntry,
  DigitalEmployee,
  DigitalEmployeeDraft,
  DigitalEmployeeDraftRevision,
  DigitalEmployeeRouteDecision,
  DigitalEmployeeTemplate,
  DigitalEmployeeRouteCandidate,
  DigitalEmployeeRouteRule,
  McpConnector,
  ManagedEmployeeTemplateRevision,
  WorkforceTask,
} from "./types";
import { message } from "./feedback";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

const workflowLabels: Record<string, string> = {
  customer_service_ticket_v1: "客服工单处理",
  hr_onboarding_document_collection_v1: "HR 入职资料收集",
};

const domainLabels: Record<string, string> = {
  customer_service: "客户服务",
  human_resources: "人力资源",
  finance: "财务",
  ecommerce_operations: "电商运营",
  content_media: "内容制作",
};

const templateLabels: Record<string, string> = {
  ecommerce_presales: "电商售前客服",
  ecommerce_aftersales: "电商售后客服",
  ecommerce_logistics: "物流查询客服",
  ecommerce_listing_operator: "商品上架数字员工",
  ecommerce_visual_creator: "视觉内容数字员工",
  ecommerce_operations_supervisor: "电商运营主管数字员工",
  hr_onboarding: "HR 入职专员",
};

const routeReasonLabels: Record<string, string> = {
  INTENT_MATCH: "关键词命中",
  SEMANTIC_MATCH: "语义相近",
  AMBIGUOUS_REQUIRES_HUMAN: "存在歧义，建议人工确认",
  LOW_CONFIDENCE_FALLBACK: "低置信度，转兜底员工",
  LOW_CONFIDENCE_DEFAULT: "低置信度，转默认员工",
  NO_ELIGIBLE_DEFAULT: "没有可派员工，转默认员工",
  NO_MATCH_DEFAULT: "没有匹配员工，转默认员工",
  FALLBACK: "使用兜底员工",
};

function routeReasonColor(code: string | null | undefined): string {
  if (code === "AMBIGUOUS_REQUIRES_HUMAN") return "orange";
  if (code?.startsWith("LOW_CONFIDENCE") || code === "FALLBACK") {
    return "gold";
  }
  if (code?.includes("DEFAULT")) return "volcano";
  if (code === "SEMANTIC_MATCH") return "blue";
  return "green";
}

function routeDecisionEmployee(
  row: DigitalEmployeeRouteDecision,
): DigitalEmployeeRouteCandidate | undefined {
  return (
    row.candidates.find((candidate) => candidate.selected) ??
    row.candidates.find(
      (candidate) => candidate.employee_key === row.selected_employee_key,
    )
  );
}

function normalizedRouteReason(
  reason: string | null | undefined,
  reasonCode: string | null | undefined,
  candidates: DigitalEmployeeRouteCandidate[],
): string {
  const selected =
    candidates.find((candidate) => candidate.selected) ??
    candidates.find((candidate) => candidate.employee_name);
  const value = (reason ?? "").trim();
  const englishIntentMatch = value.match(/^Matched intents?:\s*(.+)$/i);
  if (englishIntentMatch) {
    return `命中派单依据：${englishIntentMatch[1].replaceAll(",", "、")}`;
  }
  if (/^[A-Za-z]/.test(value)) {
    const matched = selected?.matched_intents ?? [];
    return matched.length > 0
      ? `命中派单依据：${matched.join("、")}`
      : routeReasonLabels[reasonCode ?? ""] ?? "系统已完成路由判断";
  }
  return (
    value ||
    (routeReasonLabels[reasonCode ?? ""] ?? "系统已完成路由判断")
  );
}

function routeDecisionReason(row: DigitalEmployeeRouteDecision): string {
  return normalizedRouteReason(
    row.reason,
    row.reason_code,
    row.candidates,
  );
}

function routeDecisionSource(row: DigitalEmployeeRouteDecision): string {
  if (row.ticket_id) return "工单路由";
  if (row.conversation_id) return "会话路由";
  return "任务编排";
}

function routeConfidenceColor(value: number): string {
  if (value >= 0.8) return "green";
  if (value >= 0.5) return "gold";
  return "red";
}

function localizedExcludedReason(reason: string): string {
  const statusLabels: Record<string, string> = {
    ACTIVE: "可用",
    TRIAL: "待复核",
    EVALUATION_FAILED: "评测未通过",
    DISABLED: "已停用",
  };
  const statusMatch = reason.match(/^员工状态为\s+(\S+)$/);
  if (statusMatch) {
    return `员工状态：${statusLabels[statusMatch[1]] ?? "不可用"}`;
  }
  if (reason.startsWith("渠道 ")) {
    return "当前渠道不在派发规则范围内";
  }
  if (/^[A-Za-z]/.test(reason)) {
    return "未满足派发条件";
  }
  return reason;
}

function RouteEvidence({
  candidates,
}: {
  candidates: DigitalEmployeeRouteCandidate[];
}) {
  if (candidates.length === 0) {
    return <Text type="secondary">旧记录未保存候选评分。</Text>;
  }
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message="派单判断方法"
        description="先看问题主体和岗位关键词，再用本地语义相似度补充；主体命中权重高于背景。候选分数接近时会提示人工确认，停用员工、停用规则和渠道不符会直接排除。"
      />
      <Table
        rowKey="employee_id"
        size="small"
        pagination={{ pageSize: 10, showSizeChanger: true }}
        dataSource={candidates}
        scroll={{ x: 760 }}
        columns={[
          {
            title: "候选员工",
            width: 180,
            render: (_value, candidate) => (
              <Space direction="vertical" size={0}>
                <Space size={4}>
                  <Text strong>{candidate.employee_name}</Text>
                  {candidate.selected && <Tag color="green">当前选中</Tag>}
                </Space>
                <Text type="secondary">{candidate.employee_key}</Text>
              </Space>
            ),
          },
          {
            title: "是否参与",
            width: 180,
            render: (_value, candidate) => {
              const excluded = candidate.excluded_reasons ?? [];
              if (excluded.length > 0) {
                return (
                  <Space wrap size={4}>
                    {excluded.map((reason) => (
                      <Tag color="red" key={reason}>
                        {localizedExcludedReason(reason)}
                      </Tag>
                    ))}
                  </Space>
                );
              }
              return (
                <Tag color={candidate.fallback ? "gold" : "green"}>
                  {candidate.fallback ? "兜底候选" : "专业候选"}
                </Tag>
              );
            },
          },
          {
            title: "评分",
            width: 125,
            render: (_value, candidate) => (
              <Space direction="vertical" size={0}>
                <Text strong>
                  综合 {(candidate.score * 100).toFixed(0)}
                </Text>
                <Text type="secondary">
                  关键词 {((candidate.keyword_score ?? 0) * 100).toFixed(0)}
                  {" · "}
                  语义 {((candidate.semantic_score ?? 0) * 100).toFixed(0)}
                </Text>
              </Space>
            ),
          },
          {
            title: "命中依据",
            render: (_value, candidate) => {
              const evidence = [
                ...(candidate.matched_subject_terms ?? []).map(
                  (term) => `主体：${term}`,
                ),
                ...(candidate.matched_body_terms ?? []).map(
                  (term) => `背景：${term}`,
                ),
                ...(candidate.matched_synonyms ?? []).map(
                  (term) => `同义词：${term}`,
                ),
              ];
              return (
                <Space wrap size={4}>
                  {evidence.length > 0 ? (
                    evidence.map((term) => <Tag key={term}>{term}</Tag>)
                  ) : (
                    <Text type="secondary">没有明确关键词命中</Text>
                  )}
                </Space>
              );
            },
          },
        ]}
      />
    </Space>
  );
}

export type EmployeeSection =
  | "roster"
  | "templates"
  | "skills"
  | "integrations"
  | "routing"
  | "supervisor"
  | "drafts";

const employeeSectionMeta: Record<
  EmployeeSection,
  { title: string; description: string }
> = {
  roster: {
    title: "数字员工名单",
    description: "查看每个岗位负责什么、当前状态以及能否参与业务。",
  },
  templates: {
    title: "岗位模板",
    description: "从标准岗位开始创建数字员工，不必填写技术字段。",
  },
  skills: {
    title: "Skill · 岗位操作规程",
    description:
      "维护员工在什么情况下做什么、调用哪些能力，以及哪些行为必须转人工。",
  },
  integrations: {
    title: "MCP · 业务系统连接",
    description:
      "管理客户、订单、工单等外部系统的连接、工具发现和员工授权。",
  },
  routing: {
    title: "业务入口与员工路由",
    description:
      "先配置业务入口可使用的员工池，再配置问题应派给哪位数字员工。",
  },
  supervisor: {
    title: "复杂任务处理",
    description: "由主管员工拆分任务、协调专业员工并汇总复核。",
  },
  drafts: {
    title: "员工上岗审核",
    description: "新岗位经过试用、能力检查和批准后才能正式参与业务。",
  },
};

const availableTools = [
  "ticket.read",
  "knowledge.search",
  "draft.create",
  "ticket.sync",
  "employee_profile.read",
];

const customerTools = availableTools.slice(0, 4);
const hrTools = availableTools;

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function objectArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function workforceStatus(value: string): string {
  return (
    {
      PENDING: "待执行",
      RUNNING: "执行中",
      SUCCEEDED: "已完成",
      FAILED: "失败",
      PLAN_READY: "待执行",
      QUEUED: "排队中",
      COMPLETED: "已完成",
      NEEDS_REVIEW: "待人工复核",
    }[value] ?? "未知状态"
  );
}

function workforceStatusColor(value: string): string {
  if (value === "SUCCEEDED" || value === "COMPLETED") return "green";
  if (value === "FAILED") return "red";
  if (value === "RUNNING" || value === "QUEUED") return "blue";
  if (value === "NEEDS_REVIEW") return "orange";
  return "default";
}

function readinessStatus(value: string): string {
  return (
    {
      READY: "就绪",
      DEGRADED: "降级",
      BLOCKED: "阻塞",
      WARNING: "注意",
      NOT_APPLICABLE: "不适用",
    }[value] ?? "未知状态"
  );
}

function readinessStatusColor(value: string): string {
  if (value === "READY") return "green";
  if (value === "BLOCKED") return "red";
  if (value === "DEGRADED" || value === "WARNING") return "orange";
  return "default";
}

function draftStatus(value: string): string {
  return (
    {
      DRAFT: "待评审",
      IN_REVIEW: "评审中",
      APPROVED: "已批准",
      REJECTED: "已拒绝",
      TRIAL: "试用中",
      EVALUATION_FAILED: "评测未通过",
      EVALUATION_PASSED: "评测通过",
      PUBLISHED: "已发布",
      ROLLED_BACK: "已回滚",
    }[value] ?? "未知状态"
  );
}

function draftStatusColor(value: string): string {
  if (value === "PUBLISHED" || value === "EVALUATION_PASSED") {
    return "green";
  }
  if (value === "REJECTED" || value === "EVALUATION_FAILED") {
    return "red";
  }
  if (
    value === "TRIAL" ||
    value === "APPROVED" ||
    value === "ROLLED_BACK"
  ) {
    return "orange";
  }
  return "blue";
}

function employeeReadiness(employee: DigitalEmployee): {
  label: string;
  color: string;
  detail: string;
} {
  if (employee.status === "DISABLED") {
    return {
      label: "已停用",
      color: "default",
      detail: "不会参与自动派单；重新启用前需要再次检查。",
    };
  }
  if (employee.status === "TRIAL") {
    return {
      label: "待上岗检查",
      color: "orange",
      detail: "先补齐知识、规程和工具，再点击“评估并激活”。",
    };
  }
  if (employee.status === "EVALUATION_FAILED") {
    const failed = employee.activation_evaluation.checks?.find(
      (check) => check.status === "FAILED",
    );
    return {
      label: "检查未通过",
      color: "red",
      detail: failed?.detail ?? "请补齐缺失资源后重新检查。",
    };
  }
  if (employee.activation_evaluation.passed === true) {
    return {
      label: "可以上岗",
      color: "green",
      detail: "最近一次能力检查已通过。",
    };
  }
  return {
    label: "已启用",
    color: "cyan",
    detail: "尚未执行完整上岗检查，建议先做一次能力评估。",
  };
}

function templateStatus(value: string): string {
  return (
    {
      DRAFT: "模板草案",
      IN_REVIEW: "模板评审中",
      APPROVED: "模板已批准",
      REJECTED: "模板已拒绝",
      PUBLISHED: "模板已发布",
      DISABLED: "模板已停用",
    }[value] ?? "未知状态"
  );
}

function templateStatusColor(value: string): string {
  if (value === "PUBLISHED") return "green";
  if (value === "REJECTED" || value === "DISABLED") return "red";
  if (value === "APPROVED" || value === "IN_REVIEW") return "orange";
  return "blue";
}

export default function EmployeesPage({
  section = "roster",
  advanced = false,
  onNavigate,
}: {
  section?: EmployeeSection;
  advanced?: boolean;
  onNavigate?: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [templateCode, setTemplateCode] = useState<string | null>(null);
  const [editing, setEditing] = useState<DigitalEmployee | null>(null);
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: ["roster", "routing", "drafts"].includes(section),
  });
  const templates = useQuery({
    queryKey: ["digital-employee-templates"],
    queryFn: listDigitalEmployeeTemplates,
    enabled: ["roster", "templates"].includes(section),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["digital-employees"] });
  };
  const activateEmployee = useMutation({
    mutationFn: (employeeId: string) =>
      activateDigitalEmployee(employeeId),
    onSuccess: async (employee) => {
      if (employee.status === "ACTIVE") {
        message.success("员工评测通过并已激活");
      } else {
        message.warning("员工资源检查未通过，请补充缺失的 Skill、知识库、MCP 或工具权限");
      }
      await refresh();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const columns: ColumnsType<DigitalEmployee> = [
    {
      title: "数字员工",
      dataIndex: "name",
      render: (value: string, employee) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{employee.employee_key}</Text>
        </Space>
      ),
    },
    {
      title: "岗位",
      dataIndex: "template_code",
      render: (value: string | null, employee) => (
        <Space direction="vertical" size={0}>
          <Text>
            {templates.data?.find((item) => item.code === value)?.name ??
              value ??
              workflowLabels[employee.workflow_key] ??
              employee.workflow_key}
          </Text>
          <Text type="secondary">
            {domainLabels[employee.domain] ?? employee.domain}
          </Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (value: string) => (
        <Tag
          color={
            value === "ACTIVE"
              ? "green"
              : value === "EVALUATION_FAILED"
                ? "red"
              : value === "TRIAL"
                ? "orange"
                : "default"
          }
        >
          {value === "ACTIVE"
            ? "启用"
            : value === "EVALUATION_FAILED"
              ? "评测未通过"
            : value === "TRIAL"
              ? "试用中"
              : "停用"}
        </Tag>
      ),
    },
    {
      title: "上岗检查",
      dataIndex: "status",
      width: 250,
      render: (_value: string, employee) => {
        const readiness = employeeReadiness(employee);
        return (
          <Space direction="vertical" size={2}>
            <Tag color={readiness.color}>{readiness.label}</Tag>
            <Text type="secondary">{readiness.detail}</Text>
          </Space>
        );
      },
    },
    ...(advanced
      ? [
          {
            title: "配置版本",
            dataIndex: "config_revision",
            width: 100,
          },
        ]
      : []),
    {
      title: "操作",
      width: 230,
      render: (_, employee) => (
        <Space>
          <Button type="link" onClick={() => setEditing(employee)}>
            配置
          </Button>
          {(employee.status === "TRIAL" ||
            employee.status === "EVALUATION_FAILED" ||
            employee.status === "DISABLED") && (
            <Button
              type="link"
              loading={
                activateEmployee.isPending &&
                activateEmployee.variables === employee.id
              }
              onClick={() => activateEmployee.mutate(employee.id)}
            >
              评估并激活
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>{employeeSectionMeta[section].title}</Title>
          <Paragraph type="secondary">
            {employeeSectionMeta[section].description}
          </Paragraph>
        </div>
        {section === "roster" && (
          <Button
            type="primary"
            onClick={() => setCreateOpen(true)}
          >
            新建数字员工
          </Button>
        )}
      </div>

      {employees.isError && (
        <Alert
          type="error"
          showIcon
          message="数字员工加载失败"
          description={(employees.error as Error).message}
        />
      )}

      {section === "roster" && (
        <Alert
          type="info"
          showIcon
          message="Skill 与 MCP 属于员工能力配置"
          description="Skill 定义岗位的判断和处置规程；MCP 连接订单、工单、客户等业务系统并提供可授权工具。两者都在“员工、Skill 与 MCP”页面内维护，并可在每位员工的配置中绑定。"
          action={
            <Space wrap>
              <Button onClick={() => onNavigate?.("/employees/skills")}>
                管理 Skill
              </Button>
              <Button onClick={() => onNavigate?.("/employees/integrations")}>
                管理 MCP
              </Button>
            </Space>
          }
        />
      )}

      {section === "templates" && (
        <>
        <Card className="section-card" title="选择一个岗位模板">
          <Paragraph type="secondary">
            平台内置模板和已发布的自定义模板都可以直接创建员工。模板会自动生成
            员工编码、工作流、服务身份、默认权限和配置版本。
          </Paragraph>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: 12,
            }}
          >
            {(templates.data ?? []).map((template) => (
              <Card
                key={template.code}
                size="small"
                hoverable
                onClick={() => setTemplateCode(template.code)}
              >
                <Space direction="vertical" size={8}>
                  <Space>
                    <Tag color={template.domain === "human_resources" ? "purple" : "blue"}>
                      {domainLabels[template.domain] ?? template.domain}
                    </Tag>
                    <Tag color={template.builtin ? "default" : "gold"}>
                      {template.builtin ? "平台内置" : "自定义已发布"}
                    </Tag>
                    <Text strong>{template.name}</Text>
                  </Space>
                  <Text type="secondary">{template.description}</Text>
                  <Space wrap size={4}>
                    {template.intents.slice(0, 4).map((intent) => (
                      <Tag key={intent}>{intent}</Tag>
                    ))}
                  </Space>
                  <Button
                    type="primary"
                    onClick={(event) => {
                      event.stopPropagation();
                      setTemplateCode(template.code);
                    }}
                  >
                    使用这个模板
                  </Button>
                </Space>
              </Card>
              ))}
          </div>
        </Card>
        <ManagedTemplatesCard />
        </>
      )}

      {section === "roster" && (
        <Card className="section-card" title="已登记员工">
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="员工状态不等于可以上岗"
            description="新员工需要先通过知识和工具检查。显示“可以上岗”的员工具备参与自动派单的完整检查记录；停用和试用员工不会参与正式业务。"
          />
          <Table
            rowKey="id"
            columns={columns}
            dataSource={employees.data}
            loading={employees.isLoading}
            pagination={{ pageSize: 10, showSizeChanger: true }}
          />
        </Card>
      )}

      {section === "skills" && <AgentSkillsCard />}
      {section === "integrations" && <McpConnectorsCard />}
      {section === "routing" && (
        <DigitalEmployeeRoutingCard employees={employees.data ?? []} />
      )}
      {section === "supervisor" && <SupervisorTaskCard />}
      {section === "drafts" && (
        <EmployeeDraftsCard
          onEditEmployee={(employeeId) => {
            const employee = employees.data?.find(
              (item) => item.id === employeeId,
            );
            if (employee) setEditing(employee);
          }}
        />
      )}

      <CreateEmployeeModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={refresh}
      />
      <TemplateEmployeeModal
        template={
          templates.data?.find((item) => item.code === templateCode) ??
          null
        }
        onClose={() => setTemplateCode(null)}
        onCreated={refresh}
      />
      <EmployeeConfigDrawer
        employee={editing}
        advanced={advanced}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          await Promise.all([
            refresh(),
            queryClient.invalidateQueries({
              queryKey: ["knowledge-bindings"],
            }),
            queryClient.invalidateQueries({
              queryKey: ["employee-skills"],
            }),
            queryClient.invalidateQueries({
              queryKey: ["employee-mcp-connectors"],
            }),
          ]);
          setEditing(null);
        }}
      />
    </Space>
  );
}

function AgentSkillsCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AgentSkill | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [triggers, setTriggers] = useState("");
  const [tools, setTools] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const skills = useQuery({
    queryKey: ["agent-skills"],
    queryFn: listAgentSkills,
  });
  const save = useMutation({
    mutationFn: () => {
      const input = {
        name: name.trim(),
        description: description.trim(),
        instructions: instructions.trim(),
        triggers: triggers
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
        tools: tools
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
        status,
      };
      return editing
        ? updateAgentSkill(editing.id, input)
        : createAgentSkill({
            code: code.trim(),
            ...input,
          });
    },
    onSuccess: async () => {
      message.success(editing ? "Skill 已更新" : "Skill 已创建");
      setOpen(false);
      setEditing(null);
      await queryClient.invalidateQueries({ queryKey: ["agent-skills"] });
      await queryClient.invalidateQueries({
        queryKey: ["digital-employees"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["employee-skills"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const openEditor = (skill?: AgentSkill) => {
    setEditing(skill ?? null);
    setCode(skill?.code ?? "");
    setName(skill?.name ?? "");
    setDescription(skill?.description ?? "");
    setInstructions(skill?.instructions ?? "");
    setTriggers(skill?.triggers.join(", ") ?? "");
    setTools(skill?.tools.join(", ") ?? "");
    setStatus(skill?.status ?? "ACTIVE");
    setOpen(true);
  };

  return (
    <Card
      className="section-card"
      title="Skill · 岗位操作规程"
      extra={
        <Button type="primary" onClick={() => openEditor()}>
          新建 Skill
        </Button>
      }
    >
      <Paragraph type="secondary">
         这里定义员工在什么情况下启用什么规程、可以查什么资料和使用什么工具。
      </Paragraph>
      <Table
        rowKey="id"
        size="small"
        loading={skills.isLoading}
        dataSource={skills.data}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={[
          {
            title: "Skill",
            dataIndex: "name",
            render: (value: string, skill) => (
              <Space direction="vertical" size={0}>
                <Text strong>{value}</Text>
                <Text type="secondary">{skill.code}</Text>
              </Space>
            ),
          },
          {
            title: "触发词",
            dataIndex: "triggers",
            render: (value: string[]) => (
              <Space wrap size={4}>
                {value.slice(0, 6).map((trigger) => (
                  <Tag key={trigger}>{trigger}</Tag>
                ))}
              </Space>
            ),
          },
          {
            title: "工具",
            dataIndex: "tools",
            width: 220,
            render: (value: string[]) => value.join(", ") || "仅使用知识检索",
          },
          {
            title: "版本",
            dataIndex: "version",
            width: 70,
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 90,
            render: (value: string) => (
              <Tag color={value === "ACTIVE" ? "green" : "default"}>
                {value === "ACTIVE" ? "启用" : "停用"}
              </Tag>
            ),
          },
          {
            title: "操作",
            width: 80,
            render: (_, skill) => (
              <Button type="link" onClick={() => openEditor(skill)}>
                编辑
              </Button>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? `编辑 Skill · ${editing.code}` : "新建 Skill"}
        open={open}
        width={760}
        onCancel={() => setOpen(false)}
        confirmLoading={save.isPending}
        okText="保存"
        okButtonProps={{
          disabled:
            !name.trim() ||
            !instructions.trim() ||
            (!editing && !code.trim()),
        }}
        onOk={() => save.mutate()}
      >
        <Form layout="vertical">
          <Space size="middle" align="start" className="form-row">
            <Form.Item label="Skill 编码" required>
              <Input
                value={code}
                disabled={Boolean(editing)}
                onChange={(event) => setCode(event.target.value)}
                placeholder="ecommerce-presales"
              />
            </Form.Item>
            <Form.Item label="名称" required>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="状态">
              <Select
                value={status}
                onChange={setStatus}
                options={[
                  { value: "ACTIVE", label: "启用" },
                  { value: "DISABLED", label: "停用" },
                ]}
                style={{ width: 120 }}
              />
            </Form.Item>
          </Space>
          <Form.Item label="说明">
            <Input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Form.Item>
          <Form.Item
            label="触发词"
            extra="使用逗号或换行分隔；LangGraph 会按这些词和问题分类选择 Skill。"
          >
            <TextArea
              rows={2}
              value={triggers}
              onChange={(event) => setTriggers(event.target.value)}
            />
          </Form.Item>
          <Form.Item
            label="允许工具"
            extra="使用逗号分隔。实际执行仍受员工工具白名单和权限治理。"
          >
            <Input
              value={tools}
              onChange={(event) => setTools(event.target.value)}
              placeholder="knowledge.search, logistics.query"
            />
          </Form.Item>
          <Form.Item label="Skill 指令" required>
            <TextArea
              rows={10}
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="说明执行步骤、事实来源、禁止行为和人工升级条件。"
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

function McpConnectorsCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<McpConnector | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [headerEnv, setHeaderEnv] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const connectors = useQuery({
    queryKey: ["mcp-connectors"],
    queryFn: listMcpConnectors,
  });
  const save = useMutation({
    mutationFn: () => {
      const parsedHeaders = Object.fromEntries(
        headerEnv
          .split(/\n/)
          .map((line) => line.trim())
          .filter(Boolean)
          .map((line) => {
            const index = line.indexOf("=");
            return index > 0
              ? [line.slice(0, index).trim(), line.slice(index + 1).trim()]
              : ["", ""];
          })
          .filter(([header, envName]) => header && envName),
      );
      return editing
        ? updateMcpConnector(editing.id, {
            name,
            description,
            url,
            headerEnv: parsedHeaders,
            status,
          })
        : createMcpConnector({
            code,
            name,
            description,
            url,
            headerEnv: parsedHeaders,
            status,
          });
    },
    onSuccess: async () => {
      message.success(editing ? "MCP 连接器已更新" : "MCP 连接器已创建");
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["mcp-connectors"] });
      await queryClient.invalidateQueries({
        queryKey: ["digital-employees"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["employee-mcp-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const discover = useMutation({
    mutationFn: discoverMcpConnector,
    onSuccess: async (result) => {
      if (result.healthy) {
        message.success(`MCP 健康，发现 ${result.tool_count} 个工具`);
      } else {
        message.error(`MCP 连接失败：${result.error ?? "未知错误"}`);
      }
      await queryClient.invalidateQueries({ queryKey: ["mcp-connectors"] });
      await queryClient.invalidateQueries({
        queryKey: ["digital-employees"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["employee-mcp-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const openEditor = (connector?: McpConnector) => {
    setEditing(connector ?? null);
    setCode(connector?.code ?? "");
    setName(connector?.name ?? "");
    setDescription(connector?.description ?? "");
    setUrl(connector?.url ?? "");
    setHeaderEnv(
      Object.entries(connector?.header_env ?? {})
        .map(([header, envName]) => `${header}=${envName}`)
        .join("\n"),
    );
    setStatus(connector?.status ?? "ACTIVE");
    setOpen(true);
  };

  return (
    <Card
      className="section-card"
      title="MCP · 业务系统连接"
      extra={
        <Button type="primary" onClick={() => openEditor()}>
          新建 MCP 连接器
        </Button>
      }
    >
      <Paragraph type="secondary">
         连接企业服务、客户服务、订单和工单等外部系统。密钥只保存环境变量名；
         发现工具后才能授权给数字员工。
      </Paragraph>
      <Table
        rowKey="id"
        size="small"
        loading={connectors.isLoading}
        dataSource={connectors.data}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={[
          {
            title: "连接器",
            dataIndex: "name",
            render: (value: string, connector) => (
              <Space direction="vertical" size={0}>
                <Text strong>{value}</Text>
                <Text type="secondary">{connector.code}</Text>
              </Space>
            ),
          },
          {
            title: "地址",
            dataIndex: "url",
            ellipsis: true,
            width: 320,
          },
          {
            title: "健康",
            dataIndex: "last_check_error",
            width: 90,
            render: (error: string | null, connector) =>
              connector.last_checked_at ? (
                <Tag color={error ? "red" : "green"}>
                  {error ? "异常" : "正常"}
                </Tag>
              ) : (
                <Tag>未检测</Tag>
              ),
          },
          {
            title: "工具",
            dataIndex: "tools",
            width: 150,
            render: (tools: McpConnector["tools"]) => (
              <Space size={4}>
                <Tag>{tools.length} 总</Tag>
                <Tag color="blue">
                  {tools.filter((tool) => !tool.is_write).length} 只读
                </Tag>
                {tools.some((tool) => tool.is_write) && (
                  <Tag color="orange">
                    {tools.filter((tool) => tool.is_write).length} 写
                  </Tag>
                )}
              </Space>
            ),
          },
          {
            title: "状态",
            dataIndex: "status",
            width: 80,
            render: (value: string) => (
              <Tag color={value === "ACTIVE" ? "green" : "default"}>
                {value === "ACTIVE" ? "启用" : "停用"}
              </Tag>
            ),
          },
          {
            title: "操作",
            width: 160,
            render: (_, connector) => (
              <Space>
                <Button
                  type="link"
                  loading={
                    discover.isPending &&
                    discover.variables === connector.id
                  }
                  onClick={() => discover.mutate(connector.id)}
                >
                  测试/发现
                </Button>
                <Button type="link" onClick={() => openEditor(connector)}>
                  编辑
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Modal
        title={editing ? `编辑 MCP · ${editing.code}` : "新建 MCP 连接器"}
        open={open}
        width={720}
        onCancel={() => setOpen(false)}
        confirmLoading={save.isPending}
        okText="保存"
        okButtonProps={{
          disabled: !name.trim() || !url.trim() || (!editing && !code.trim()),
        }}
        onOk={() => save.mutate()}
      >
        <Form layout="vertical">
          <Space size="middle" align="start" className="form-row">
            <Form.Item label="编码" required>
              <Input
                value={code}
                disabled={Boolean(editing)}
                onChange={(event) => setCode(event.target.value)}
                placeholder="order-center"
              />
            </Form.Item>
            <Form.Item label="名称" required>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="状态">
              <Select
                value={status}
                onChange={setStatus}
                options={[
                  { value: "ACTIVE", label: "启用" },
                  { value: "DISABLED", label: "停用" },
                ]}
                style={{ width: 120 }}
              />
            </Form.Item>
          </Space>
          <Form.Item label="说明">
            <Input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="Streamable HTTP URL" required>
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://mcp.example.com/mcp"
            />
          </Form.Item>
          <Form.Item
            label="请求头环境变量"
            extra="每行一个 header=ENV_VAR，例如 Authorization=MCP_AUTH_TOKEN。系统不会返回密钥值。"
          >
            <TextArea
              rows={3}
              value={headerEnv}
              onChange={(event) => setHeaderEnv(event.target.value)}
              placeholder="Authorization=MCP_AUTH_TOKEN"
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

function CreateEmployeeModal({
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
  const create = useMutation({
    mutationFn: () =>
      createDigitalEmployee({
        employee_key: employeeKey,
        name,
        workflow_key: workflowKey,
        handoff_queue: queue,
        tools:
          workflowKey === "hr_onboarding_document_collection_v1"
            ? hrTools
            : customerTools,
      }),
    onSuccess: async () => {
      message.success("数字员工已创建");
      setEmployeeKey("");
      setName("");
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
      </Form>
    </Modal>
  );
}

function DigitalEmployeeRoutingCard({
  employees,
}: {
  employees: DigitalEmployee[];
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<DigitalEmployeeRouteRule | null>(null);
  const [intents, setIntents] = useState("");
  const [priority, setPriority] = useState(100);
  const [fallback, setFallback] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [showAllRules, setShowAllRules] = useState(false);
  const [editingEntry, setEditingEntry] =
    useState<BusinessServiceEntry | null>(null);
  const [entryEmployeeIds, setEntryEmployeeIds] = useState<string[]>([]);
  const businessEntries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
  });
  const rules = useQuery({
    queryKey: ["digital-employee-route-rules"],
    queryFn: listDigitalEmployeeRouteRules,
  });
  const decisions = useQuery({
    queryKey: ["digital-employee-route-decisions"],
    queryFn: listDigitalEmployeeRouteDecisions,
    refetchInterval: 10_000,
  });
  const employeeName = (employeeId: string) =>
    employees.find((employee) => employee.id === employeeId)?.name ??
    employeeId.slice(0, 8);
  const employeeStatus = (employeeId: string) =>
    employees.find((employee) => employee.id === employeeId)?.status;
  const currentEmployeeIds = new Set(
    employees
      .filter(
        (employee) =>
          employee.status === "ACTIVE" || employee.status === "TRIAL",
      )
      .map((employee) => employee.id),
  );
  const currentRules = (rules.data ?? []).filter((rule) => {
    const status = employeeStatus(rule.employee_id);
    return (
      rule.enabled &&
      (status === "ACTIVE" || status === "TRIAL")
    );
  });
  const displayedRules = showAllRules ? rules.data ?? [] : currentRules;
  const save = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("请选择路由规则");
      return updateDigitalEmployeeRouteRule(editing.employee_id, {
        intents: intents
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
        categories: editing.categories,
        channels: editing.channels,
        priority,
        fallback,
        enabled,
      });
    },
    onSuccess: async () => {
      message.success("数字员工路由已保存");
      setEditing(null);
      await queryClient.invalidateQueries({
        queryKey: ["digital-employee-route-rules"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["digital-employee-route-decisions"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const openEditor = (rule: DigitalEmployeeRouteRule) => {
    setEditing(rule);
    setIntents(rule.intents.join(", "));
    setPriority(rule.priority);
    setFallback(rule.fallback);
    setEnabled(rule.enabled);
  };
  const saveEntryEmployees = useMutation({
    mutationFn: () => {
      if (!editingEntry) throw new Error("请选择业务入口");
      if (entryEmployeeIds.length === 0) {
        throw new Error("业务入口至少需要一名数字员工");
      }
      return replaceBusinessServiceEntryEmployees(
        editingEntry.id,
        entryEmployeeIds.map((employeeId, index) => ({
          employeeId,
          roleType:
            employeeId === editingEntry.default_employee_id
              ? "PRIMARY"
              : employeeId === editingEntry.fallback_employee_id
                ? "FALLBACK"
                : "SPECIALIST",
          priority: (index + 1) * 10,
        })),
      );
    },
    onSuccess: async () => {
      message.success("业务入口员工池已更新");
      setEditingEntry(null);
      await queryClient.invalidateQueries({
        queryKey: ["business-service-entries"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const openEntryEditor = (entry: BusinessServiceEntry) => {
    setEditingEntry(entry);
    setEntryEmployeeIds(
      entry.employees.map((employee) => employee.employee_id),
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        className="section-card"
        title="业务入口与员工池"
        loading={businessEntries.isLoading}
      >
        <Paragraph type="secondary">
          一个业务入口可以绑定多名数字员工。客户进入入口后，系统只会在该入口的
          员工池中选择处理人员，不再由页面写死某一个员工。
        </Paragraph>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {(businessEntries.data ?? []).map((entry) => (
            <Card
              key={entry.id}
              size="small"
              type="inner"
              title={entry.name}
              extra={
                <Button
                  size="small"
                  onClick={() => openEntryEditor(entry)}
                >
                  配置员工池
                </Button>
              }
            >
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Text type="secondary">{entry.description}</Text>
                <Space wrap size={6}>
                  <Tag color="cyan">{entry.domain}</Tag>
                  <Tag>{entry.channel}</Tag>
                  <Tag color={entry.status === "ACTIVE" ? "green" : "default"}>
                    {entry.status === "ACTIVE" ? "当前可用" : "已停用"}
                  </Tag>
                  <Tag>{entry.employees.length} 名数字员工</Tag>
                </Space>
                <Space wrap size={6}>
                  {entry.employees.map((employee) => (
                    <Tag
                      key={employee.employee_id}
                      color={
                        employee.role_type === "PRIMARY"
                          ? "blue"
                          : employee.role_type === "FALLBACK"
                            ? "gold"
                            : "default"
                      }
                    >
                      {employee.employee_name}
                      {employee.role_type === "PRIMARY"
                        ? " · 默认"
                        : employee.role_type === "FALLBACK"
                          ? " · 兜底"
                          : " · 专业"}
                    </Tag>
                  ))}
                </Space>
              </Space>
            </Card>
          ))}
        </Space>
      </Card>
      <Card
        className="section-card"
        title="意图派单规则"
      extra={
        <Space>
          <Select
            aria-label="路由规则范围"
            value={showAllRules ? "ALL" : "CURRENT"}
            onChange={(value) => setShowAllRules(value === "ALL")}
            options={[
              { value: "CURRENT", label: "当前生效" },
              { value: "ALL", label: "全部规则" },
            ]}
            style={{ width: 120 }}
          />
          <Tag>
            {displayedRules.length} / {rules.data?.length ?? 0} 条规则
          </Tag>
        </Space>
      }
    >
      <Paragraph type="secondary">
        工单没有手动指定员工时，系统先按这些意图匹配岗位；没有命中再使用兜底员工。
      </Paragraph>
      <Table
        rowKey="id"
        size="small"
        loading={rules.isLoading}
        dataSource={displayedRules}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={[
          {
            title: "数字员工",
            dataIndex: "employee_id",
            render: (value: string) => employeeName(value),
          },
          {
            title: "路由意图",
            dataIndex: "intents",
            render: (value: string[]) => value.join("、") || "未配置",
          },
          { title: "优先级", dataIndex: "priority", width: 90 },
          {
            title: "兜底",
            dataIndex: "fallback",
            width: 80,
            render: (value: boolean) => (value ? <Tag>兜底</Tag> : "-"),
          },
          {
            title: "启用",
            dataIndex: "enabled",
            width: 80,
            render: (value: boolean) => (
              <Tag color={value ? "green" : "default"}>
                {value ? "启用" : "停用"}
              </Tag>
            ),
          },
          {
            title: "操作",
            width: 100,
            render: (_value, rule) => (
              <Button type="link" onClick={() => openEditor(rule)}>
                编辑路由
              </Button>
            ),
          },
        ]}
      />
      <Title level={5} style={{ marginTop: 20 }}>
        最近路由结果
      </Title>
      <Table
        rowKey="id"
        size="small"
        loading={decisions.isLoading}
        dataSource={decisions.data?.items.slice(0, 10)}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        expandable={{
          expandedRowRender: (row) => (
            <RouteEvidence candidates={row.candidates} />
          ),
          rowExpandable: (row) => row.candidates.length > 0,
        }}
        columns={[
          {
            title: "选中员工",
            dataIndex: "selected_employee_key",
            render: (_value, row) => {
              const employee = routeDecisionEmployee(row);
              return (
                <Space direction="vertical" size={0}>
                  <Text strong>
                    {employee?.employee_name ?? "未识别员工"}
                  </Text>
                  <Text type="secondary">
                    {routeDecisionSource(row)}
                  </Text>
                </Space>
              );
            },
          },
          {
            title: "路由原因",
            dataIndex: "reason",
            render: (_value: string, row) => (
              <Space direction="vertical" size={4}>
                <Tag color={routeReasonColor(row.reason_code)}>
                  {routeReasonLabels[row.reason_code] ?? "系统自动判断"}
                </Tag>
                <Text>{routeDecisionReason(row)}</Text>
              </Space>
            ),
          },
          {
            title: "候选",
            dataIndex: "candidates",
            render: (
              value: DigitalEmployeeRouteCandidate[],
            ) => {
              const currentCandidates = value.filter((item) =>
                currentEmployeeIds.has(item.employee_id),
              );
              const names = [
                ...new Set(
                  currentCandidates
                    .map((item) => item.employee_name)
                    .filter(Boolean),
                ),
              ];
              const historicalCount =
                value.length - currentCandidates.length;
              return (
                <Space direction="vertical" size={0}>
                  <Text>
                    {names.length > 0
                      ? names.slice(0, 3).join(" / ")
                      : "当前没有可用候选"}
                  </Text>
                  <Text type="secondary">
                    共 {value.length} 个候选
                    {historicalCount > 0
                      ? `，其中 ${historicalCount} 个已停用或不可用`
                      : ""}
                    ，展开查看评分和排除原因
                  </Text>
                </Space>
              );
            },
          },
          {
            title: "置信度",
            dataIndex: "confidence",
            width: 100,
            render: (value: number) => (
              <Tag color={routeConfidenceColor(value)}>
                {(value * 100).toFixed(0)}%
              </Tag>
            ),
          },
          {
            title: "时间",
            dataIndex: "created_at",
            width: 180,
            render: (value: string) =>
              new Date(value).toLocaleString("zh-CN"),
          },
        ]}
      />
      <Modal
        open={Boolean(editing)}
        title="编辑数字员工路由"
        okText="保存路由"
        confirmLoading={save.isPending}
        okButtonProps={{ disabled: !editing }}
        onOk={() => save.mutate()}
        onCancel={() => setEditing(null)}
      >
        <Form layout="vertical">
          <Form.Item label="数字员工">
            <Text strong>
              {editing ? employeeName(editing.employee_id) : "-"}
            </Text>
          </Form.Item>
          <Form.Item
            label="路由意图"
            extra="使用逗号或换行分隔，例如：退款、投诉、权限变更。"
          >
            <TextArea
              rows={4}
              value={intents}
              onChange={(event) => setIntents(event.target.value)}
            />
          </Form.Item>
          <Space size="middle" align="start">
            <Form.Item label="优先级">
              <InputNumber
                min={0}
                max={1000}
                value={priority}
                onChange={(value) => setPriority(value ?? 100)}
              />
            </Form.Item>
            <Form.Item label="规则状态">
              <Checkbox
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              >
                启用
              </Checkbox>
            </Form.Item>
            <Form.Item label="兜底员工">
              <Checkbox
                checked={fallback}
                onChange={(event) => setFallback(event.target.checked)}
              >
                无匹配时使用
              </Checkbox>
            </Form.Item>
          </Space>
        </Form>
      </Modal>
      </Card>
      <Modal
        open={Boolean(editingEntry)}
        title={`配置员工池 · ${editingEntry?.name ?? ""}`}
        okText="保存员工池"
        confirmLoading={saveEntryEmployees.isPending}
        okButtonProps={{ disabled: entryEmployeeIds.length === 0 }}
        onOk={() => saveEntryEmployees.mutate()}
        onCancel={() => setEditingEntry(null)}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="员工池决定业务入口可以派给谁"
            description="默认员工和兜底员工保持入口现有配置；其他启用的员工作为专业员工参与意图路由。"
          />
          <Select
            mode="multiple"
            aria-label="选择业务入口数字员工"
            style={{ width: "100%" }}
            value={entryEmployeeIds}
            onChange={setEntryEmployeeIds}
            options={employees
              .filter((employee) =>
                ["ACTIVE", "TRIAL"].includes(employee.status),
              )
              .map((employee) => ({
                value: employee.id,
                label: `${employee.name} · ${
                  employee.status === "ACTIVE" ? "可用" : "试用"
                }`,
              }))}
          />
        </Space>
      </Modal>
    </Space>
  );
}

function SupervisorTaskCard() {
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
  const taskItems = tasks.data?.items ?? [];
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

type DraftAction =
  | "APPROVE"
  | "REJECT"
  | "REOPEN"
  | "TRIAL"
  | "EVALUATE"
  | "PUBLISH"
  | "ROLLBACK";

function EmployeeDraftsCard({
  onEditEmployee,
}: {
  onEditEmployee: (employeeId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [reviewTarget, setReviewTarget] = useState<{
    draft: DigitalEmployeeDraft;
    decision: "APPROVE" | "REJECT";
  } | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [editTarget, setEditTarget] =
    useState<DigitalEmployeeDraft | null>(null);
  const [editName, setEditName] = useState("");
  const [editCapabilities, setEditCapabilities] = useState("");
  const [editIntents, setEditIntents] = useState("");
  const [editSkillCodes, setEditSkillCodes] = useState("");
  const [editTools, setEditTools] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{
    draft: DigitalEmployeeDraft;
    action: DraftAction;
  } | null>(null);
  useEffect(() => {
    const targetRequested =
      new URLSearchParams(window.location.search).get("drafts") === "1";
    if (!targetRequested) return;
    const timer = window.setTimeout(() => {
      document
        .getElementById("employee-drafts")
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 400);
    return () => window.clearTimeout(timer);
  }, []);
  const drafts = useQuery({
    queryKey: ["employee-drafts"],
    queryFn: listEmployeeDrafts,
    refetchInterval: 10_000,
  });
  const action = useMutation({
    mutationFn: (input: {
      draftId: string;
      action: DraftAction;
      note?: string;
    }): Promise<DigitalEmployeeDraft> => {
      if (input.action === "APPROVE" || input.action === "REJECT") {
        return reviewEmployeeDraft(input.draftId, {
          decision: input.action,
          note: input.note ?? "",
        });
      }
      if (input.action === "TRIAL") {
        return createEmployeeDraftTrial(input.draftId);
      }
      if (input.action === "REOPEN") {
        return reopenEmployeeDraft(input.draftId);
      }
      if (input.action === "EVALUATE") {
        return evaluateEmployeeDraft(input.draftId);
      }
      if (input.action === "PUBLISH") {
        return publishEmployeeDraft(input.draftId);
      }
      return rollbackEmployeeDraft(input.draftId);
    },
    onSuccess: async (_draft, input) => {
      const labels: Record<DraftAction, string> = {
        APPROVE: "员工草案已批准",
        REJECT: "员工草案已拒绝",
        REOPEN: "员工草案已重新打开",
        TRIAL: "试用员工已创建",
        EVALUATE: "员工评测已完成",
        PUBLISH: "数字员工已正式发布",
        ROLLBACK: "数字员工已回滚停用",
      };
      message.success(labels[input.action]);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["employee-draft-revisions"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["digital-employees"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const promoteToTemplate = useMutation({
    mutationFn: (draftId: string) =>
      promoteEmployeeDraftToTemplate(draftId),
    onSuccess: async () => {
      message.success(
        "已生成模板草案，请到岗位模板页面完成批准和发布",
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
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
  const editDraft = useMutation({
    mutationFn: (draft: DigitalEmployeeDraft) =>
      updateEmployeeDraft(draft.id, {
        name: editName.trim(),
        capabilities: editCapabilities
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        intents: editIntents
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        skillCodes: editSkillCodes
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
        toolAllowlist: editTools
          .split(/[,，\n]/)
          .map((value) => value.trim())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      message.success("员工草案已更新");
      setEditTarget(null);
      await queryClient.invalidateQueries({
        queryKey: ["employee-drafts"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["employee-draft-revisions"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const items = drafts.data?.items ?? [];

  const confirmAction = (
    draft: DigitalEmployeeDraft,
    draftAction: DraftAction,
  ) => {
    setConfirmTarget({ draft, action: draftAction });
  };

  const button = (
    draft: DigitalEmployeeDraft,
    draftAction: DraftAction,
    label: string,
    type: "primary" | "default" | "dashed" = "default",
  ) => (
    <Button
      size="small"
      type={type}
      danger={draftAction === "REJECT" || draftAction === "ROLLBACK"}
      loading={
        action.isPending &&
        action.variables?.draftId === draft.id &&
        action.variables.action === draftAction
      }
      onClick={() => {
        if (draftAction === "APPROVE" || draftAction === "REJECT") {
          setReviewNote("");
          setReviewTarget({
            draft,
            decision: draftAction,
          });
          return;
        }
        if (draftAction === "TRIAL" || draftAction === "EVALUATE") {
          action.mutate({
            draftId: draft.id,
            action: draftAction,
          });
          return;
        }
        confirmAction(draft, draftAction);
      }}
    >
      {label}
    </Button>
  );

  return (
    <Card
      id="employee-drafts"
      className="section-card"
      title="员工草案与发布流程"
      extra={<Tag>{drafts.data?.total ?? 0} 个草案</Tag>}
    >
      <Paragraph type="secondary">
        草案依次经过评审、试用、评测和发布。发布的对象是单个数字员工实例，
        不会自动生成可复用岗位模板。试用员工不会参与自动路由；
        评测通过后才能正式上线，发布后支持回滚停用。
      </Paragraph>
      {drafts.isError && (
        <Alert
          type="error"
          showIcon
          message="员工草案加载失败"
          description={(drafts.error as Error).message}
        />
      )}
      {items.length === 0 ? (
        <Alert
          type="info"
          showIcon
          message="暂无员工草案"
          description="在主管任务的能力缺口中选择“生成员工草案”。"
        />
      ) : (
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%" }}
        >
          {items.map((draft) => {
            const evaluationChecks =
              draft.evaluation.checks ?? [];
            return (
              <Card
                key={draft.id}
                size="small"
                title={draft.name}
                extra={
                  <Tag color={draftStatusColor(draft.status)}>
                    {draftStatus(draft.status)}
                  </Tag>
                }
              >
                <Space
                  direction="vertical"
                  size="small"
                  style={{ width: "100%" }}
                >
                  <Space wrap>
                    <Tag color="purple">
                      {draft.required_capability}
                    </Tag>
                    <Tag>
                      {draft.template_code
                        ? `模板 ${draft.template_code}`
                        : "自定义岗位"}
                    </Tag>
                    <Tag>{draft.domain}</Tag>
                    <Tag color="geekblue">v{draft.revision}</Tag>
                  </Space>
                  <Text type="secondary">
                    创建人：{draft.created_by}
                    {draft.reviewed_by
                      ? ` · 评审人：${draft.reviewed_by}`
                      : ""}
                  </Text>
                  <Space wrap size={4}>
                    {draft.capabilities.map((capability) => (
                      <Tag key={capability}>{capability}</Tag>
                    ))}
                  </Space>
                  {evaluationChecks.length > 0 && (
                    <Collapse
                      size="small"
                      items={[
                        {
                          key: "evaluation",
                          label: `评测结果 · ${
                            draft.evaluation.passed ? "通过" : "未通过"
                          }`,
                          children: (
                            <Descriptions
                              size="small"
                              column={1}
                              items={evaluationChecks.map((check) => ({
                                key: check.key,
                                label: (
                                  <Space size={4}>
                                    <Tag
                                      color={
                                        check.status === "PASSED"
                                          ? "green"
                                          : "red"
                                      }
                                    >
                                      {check.status === "PASSED"
                                        ? "通过"
                                        : "失败"}
                                    </Tag>
                                    {check.label}
                                  </Space>
                                ),
                                children: check.detail,
                              }))}
                            />
                          ),
                        },
                      ]}
                    />
                  )}
                  <DraftRevisionHistory draftId={draft.id} />
                  <Space wrap>
                    {(draft.status === "DRAFT" ||
                      draft.status === "IN_REVIEW") && (
                      <>
                        {draft.status === "DRAFT" && (
                          <Button
                            size="small"
                            onClick={() => {
                              setEditTarget(draft);
                              setEditName(draft.name);
                              setEditCapabilities(
                                draft.capabilities.join("\n"),
                              );
                              setEditIntents(draft.intents.join("\n"));
                              setEditSkillCodes(
                                draft.skill_codes.join("\n"),
                              );
                              setEditTools(
                                draft.tool_allowlist.join("\n"),
                              );
                            }}
                          >
                            编辑草案
                          </Button>
                        )}
                        {button(
                          draft,
                          "APPROVE",
                          "批准草案",
                          "primary",
                        )}
                        {button(draft, "REJECT", "拒绝")}
                      </>
                    )}
                    {draft.status === "APPROVED" &&
                      button(draft, "TRIAL", "创建试用员工", "primary")}
                    {draft.status === "REJECTED" &&
                      button(draft, "REOPEN", "重新打开草案", "primary")}
                    {(draft.status === "TRIAL" ||
                      draft.status === "EVALUATION_FAILED") &&
                      button(draft, "EVALUATE", "执行评测", "primary")}
                    {draft.status === "EVALUATION_PASSED" && (
                      <>
                        {button(
                          draft,
                          "PUBLISH",
                          "发布为数字员工",
                          "primary",
                        )}
                        {button(
                          draft,
                          "EVALUATE",
                          "重新评测",
                        )}
                      </>
                    )}
                    {draft.status === "PUBLISHED" &&
                      button(draft, "ROLLBACK", "回滚停用")}
                    {(draft.status === "PUBLISHED" ||
                      draft.status === "ROLLED_BACK") &&
                      !draft.promoted_template_id && (
                        <Button
                          size="small"
                          type="dashed"
                          loading={promoteToTemplate.isPending}
                          onClick={() =>
                            promoteToTemplate.mutate(draft.id)
                          }
                        >
                          沉淀为岗位模板
                        </Button>
                      )}
                    {draft.promoted_template_id && (
                      <Tag color="cyan">已沉淀为岗位模板</Tag>
                    )}
                    {draft.employee_id && (
                      <Button
                        size="small"
                        onClick={() =>
                          onEditEmployee(draft.employee_id!)
                        }
                      >
                        配置试用员工
                      </Button>
                    )}
                  </Space>
                </Space>
              </Card>
            );
          })}
        </Space>
      )}
      <Modal
        open={Boolean(confirmTarget)}
        title={
          confirmTarget
            ? {
                APPROVE: "确认批准该员工草案？",
                REJECT: "确认拒绝该员工草案？",
                REOPEN: "确认重新打开该草案并继续修改？",
                TRIAL: "确认创建试用员工？试用员工不会参与自动路由。",
                EVALUATE:
                  "重新检查员工状态、Skill、知识库和 MCP 就绪度？",
                PUBLISH:
                  "确认正式发布该数字员工？发布后将参与自动路由。",
                ROLLBACK: "确认回滚并停用该数字员工？",
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
              draftId: confirmTarget.draft.id,
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
            {confirmTarget.draft.name} ·{" "}
            {confirmTarget.draft.required_capability}
          </Text>
        )}
      </Modal>
      <Modal
        open={Boolean(reviewTarget)}
        title={
          reviewTarget?.decision === "REJECT"
            ? "拒绝员工草案"
            : "批准员工草案"
        }
        okText={
          reviewTarget?.decision === "REJECT" ? "确认拒绝" : "确认批准"
        }
        cancelText="取消"
        confirmLoading={action.isPending}
        okButtonProps={{
          danger: reviewTarget?.decision === "REJECT",
          disabled:
            reviewTarget?.decision === "REJECT" &&
            !reviewNote.trim(),
        }}
        onCancel={() => setReviewTarget(null)}
        onOk={async () => {
          if (!reviewTarget) return;
          try {
            await action.mutateAsync({
              draftId: reviewTarget.draft.id,
              action: reviewTarget.decision,
              note: reviewNote.trim(),
            });
            setReviewTarget(null);
          } catch {
            // The mutation displays the API error and keeps the dialog open.
          }
        }}
      >
        <Space direction="vertical" size="small" style={{ width: "100%" }}>
          <Text>
            {reviewTarget?.draft.name} ·{" "}
            {reviewTarget?.draft.required_capability}
          </Text>
          <TextArea
            rows={4}
            value={reviewNote}
            onChange={(event) => setReviewNote(event.target.value)}
            placeholder={
              reviewTarget?.decision === "REJECT"
                ? "请填写拒绝原因，便于后续重新打开和修订"
                : "可填写批准意见"
            }
          />
        </Space>
      </Modal>
      <Modal
        open={Boolean(editTarget)}
        title="编辑员工草案"
        okText="保存草案"
        cancelText="取消"
        width={720}
        confirmLoading={editDraft.isPending}
        okButtonProps={{ disabled: !editName.trim() }}
        onCancel={() => setEditTarget(null)}
        onOk={() => {
          if (editTarget) editDraft.mutate(editTarget);
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Form layout="vertical">
            <Form.Item label="草案名称" required>
              <Input
                value={editName}
                onChange={(event) => setEditName(event.target.value)}
              />
            </Form.Item>
            <Form.Item
              label="岗位能力"
              extra="每行一个，或在逗号后继续填写"
            >
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
                value={editSkillCodes}
                onChange={(event) =>
                  setEditSkillCodes(event.target.value)
                }
              />
            </Form.Item>
            <Form.Item label="工具白名单" extra="每行一个">
              <TextArea
                rows={3}
                value={editTools}
                onChange={(event) => setEditTools(event.target.value)}
              />
            </Form.Item>
          </Form>
        </Space>
      </Modal>
    </Card>
  );
}

function DraftRevisionHistory({
  draftId,
}: {
  draftId: string;
}) {
  const revisions = useQuery({
    queryKey: ["employee-draft-revisions", draftId],
    queryFn: () => listEmployeeDraftRevisions(draftId),
  });
  const items: DigitalEmployeeDraftRevision[] =
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
                color: draftStatusColor(revision.status),
                children: (
                  <Space direction="vertical" size={0}>
                    <Space wrap>
                      <Text strong>v{revision.revision}</Text>
                      <Tag color={draftStatusColor(revision.status)}>
                        {draftStatus(revision.status)}
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

type TemplateAction =
  | "APPROVE"
  | "REJECT"
  | "PUBLISH"
  | "ROLLBACK"
  | "REOPEN";

function ManagedTemplatesCard() {
  const queryClient = useQueryClient();
  const [editTemplate, setEditTemplate] =
    useState<DigitalEmployeeTemplate | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editCapabilities, setEditCapabilities] = useState("");
  const [editIntents, setEditIntents] = useState("");
  const [editSkills, setEditSkills] = useState("");
  const [editTools, setEditTools] = useState("");
  const [confirmTarget, setConfirmTarget] = useState<{
    template: DigitalEmployeeTemplate;
    action: TemplateAction;
  } | null>(null);
  const templates = useQuery({
    queryKey: ["managed-employee-templates"],
    queryFn: listManagedEmployeeTemplates,
    refetchInterval: 10_000,
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
        </Form>
      </Modal>
    </Card>
  );
}

function TemplateRevisionHistory({
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

function TemplateEmployeeModal({
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
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
    enabled: Boolean(template),
  });
  useEffect(() => {
    if (!template) return;
    setName(template.name);
    setKnowledgeSpaceIds([]);
  }, [template]);
  const create = useMutation({
    mutationFn: () => {
      if (!template) throw new Error("请选择员工模板");
      return createDigitalEmployeeFromTemplate({
        name: name.trim(),
        templateCode: template.code,
        knowledgeSpaceIds,
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
          </Form>
        </Space>
      )}
    </Modal>
  );
}

function EmployeeConfigDrawer({
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
  const [skillIds, setSkillIds] = useState<string[]>([]);
  const [mcpConnectorIds, setMcpConnectorIds] = useState<string[]>([]);
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
    setKnowledgeSpaceIds(
      (knowledgeBindings.data ?? [])
        .filter((binding) => binding.enabled)
        .map((binding) => binding.knowledge_space_id),
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
    setMcpConnectorIds(
      (mcpBindings.data ?? [])
        .filter((binding) => binding.enabled)
        .map((binding) => binding.connector_id),
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
      const defaultKnowledgeScope = objectValue(
        objectValue(employee.knowledge_policy).default_scope,
      );
      const defaultWorkflow =
        typeof defaultKnowledgeScope.workflow === "string"
          ? defaultKnowledgeScope.workflow
          : null;
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
          return {
            knowledge_space_id: knowledgeSpaceId,
            workflow_key: existing?.workflow_key ?? defaultWorkflow,
            scope: existing?.scope ?? {},
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
              existing?.allowed_tools ??
              (connector?.tools ?? [])
                .filter((tool) => !tool.is_write)
                .map((tool) => tool.name),
            write_approved: existing?.write_approved ?? false,
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
                onChange={setKnowledgeSpaceIds}
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
              <Form.Item
                label="MCP（业务工具）"
                extra="连接订单、客户、工单等外部系统；仅授权已发现的工具，写工具仍需单独审批。"
              >
                <Select
                  mode="multiple"
                  allowClear
                  value={mcpConnectorIds}
                  onChange={setMcpConnectorIds}
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
