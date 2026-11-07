import { Alert, Space, Table, Tag, Typography } from "antd";

import type {
  DigitalEmployeeRouteCandidate,
  DigitalEmployeeRouteDecision,
  DigitalEmployeeRouteEvaluationDataset,
} from "../../types";

const { Text } = Typography;

export const routeEvaluationDatasetLabels: Record<
  DigitalEmployeeRouteEvaluationDataset,
  string
> = {
  TUNING: "调参集",
  HOLDOUT: "留出集",
};

export const routeReasonLabels: Record<string, string> = {
  INTENT_MATCH: "关键词命中",
  SEMANTIC_MATCH: "语义相近",
  AMBIGUOUS_REQUIRES_HUMAN: "存在歧义，建议人工确认",
  LOW_CONFIDENCE_FALLBACK: "低置信度，转兜底员工",
  LOW_CONFIDENCE_DEFAULT: "低置信度，转默认员工",
  NO_ELIGIBLE_DEFAULT: "没有可派员工，转默认员工",
  NO_MATCH_DEFAULT: "没有匹配员工，转默认员工",
  FALLBACK: "使用兜底员工",
  NO_DECISION: "没有生成路由结果",
};

export function routeReasonColor(code: string | null | undefined): string {
  if (code === "AMBIGUOUS_REQUIRES_HUMAN") return "orange";
  if (code?.startsWith("LOW_CONFIDENCE") || code === "FALLBACK") {
    return "gold";
  }
  if (code?.includes("DEFAULT")) return "volcano";
  if (code === "SEMANTIC_MATCH") return "blue";
  return "green";
}

export function routeDecisionEmployee(
  row: DigitalEmployeeRouteDecision,
): DigitalEmployeeRouteCandidate | undefined {
  return (
    row.candidates.find((candidate) => candidate.selected) ??
    row.candidates.find(
      (candidate) => candidate.employee_key === row.selected_employee_key,
    )
  );
}

export function normalizedRouteReason(
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

export function routeDecisionReason(row: DigitalEmployeeRouteDecision): string {
  return normalizedRouteReason(
    row.reason,
    row.reason_code,
    row.candidates,
  );
}

export function routeDecisionSource(row: DigitalEmployeeRouteDecision): string {
  if (row.ticket_id) return "工单路由";
  if (row.conversation_id) return "会话路由";
  return "任务编排";
}

export function routeConfidenceColor(value: number): string {
  if (value >= 0.8) return "green";
  if (value >= 0.5) return "gold";
  return "red";
}

export function localizedExcludedReason(reason: string): string {
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

export function RouteEvidence({
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
        scroll={{ x: 1000 }}
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
            title: "意图归属",
            width: 220,
            render: (_value, candidate) => {
              const groups = [
                {
                  label: "显式",
                  color: "blue",
                  terms: candidate.explicit_intents ?? [],
                },
                {
                  label: "继承",
                  color: "default",
                  terms: candidate.inherited_intents ?? [],
                },
                {
                  label: "已让位",
                  color: "orange",
                  terms: candidate.suppressed_intents ?? [],
                },
              ].filter((group) => group.terms.length > 0);
              if (groups.length === 0) {
                return (
                  <Text type="secondary">未记录意图归属</Text>
                );
              }
              return (
                <Space direction="vertical" size={4}>
                  {groups.map((group) => (
                    <Space wrap size={4} key={group.label}>
                      <Text type="secondary">{group.label}</Text>
                      {group.terms.slice(0, 6).map((term) => (
                        <Tag color={group.color} key={term}>
                          {term}
                        </Tag>
                      ))}
                      {group.terms.length > 6 && (
                        <Tag>+{group.terms.length - 6}</Tag>
                      )}
                    </Space>
                  ))}
                </Space>
              );
            },
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
  | "route-evaluation"
  | "supervisor"
  | "drafts";

export const employeeSectionMeta: Record<
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
    title: "外部连接 · 邮件与业务系统",
    description:
      "接入邮件渠道和只读业务系统，管理连接健康、业务入口绑定、消息收发和员工授权。",
  },
  routing: {
    title: "业务入口与员工路由",
    description:
      "先配置业务入口可使用的员工池，再配置问题应派给哪位数字员工。",
  },
  "route-evaluation": {
    title: "路由评测集",
    description:
      "用固定问题回归验证员工分派，量化意图识别准确率并定位误派。",
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

export const availableTools = [
  "ticket.read",
  "knowledge.search",
  "draft.create",
  "ticket.sync",
  "employee_profile.read",
];

export const customerTools = availableTools.slice(0, 4);
export const hrTools = availableTools;

export function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

export function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function objectArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

export function workforceStatus(value: string): string {
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

export function workforceStatusColor(value: string): string {
  if (value === "SUCCEEDED" || value === "COMPLETED") return "green";
  if (value === "FAILED") return "red";
  if (value === "RUNNING" || value === "QUEUED") return "blue";
  if (value === "NEEDS_REVIEW") return "orange";
  return "default";
}

export function readinessStatus(value: string): string {
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

export function readinessStatusColor(value: string): string {
  if (value === "READY") return "green";
  if (value === "BLOCKED") return "red";
  if (value === "DEGRADED" || value === "WARNING") return "orange";
  return "default";
}

export function draftStatus(value: string): string {
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

export function draftStatusColor(value: string): string {
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

export function templateStatus(value: string): string {
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

export function templateStatusColor(value: string): string {
  if (value === "PUBLISHED") return "green";
  if (value === "REJECTED" || value === "DISABLED") return "red";
  if (value === "APPROVED" || value === "IN_REVIEW") return "orange";
  return "blue";
}
