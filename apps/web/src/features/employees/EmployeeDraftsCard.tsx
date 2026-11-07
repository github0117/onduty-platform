import {
  Alert,
  Button,
  Card,
  Collapse,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  createEmployeeDraftTrial,
  evaluateEmployeeDraft,
  listEmployeeDraftRevisions,
  listEmployeeDrafts,
  promoteEmployeeDraftToTemplate,
  publishEmployeeDraft,
  reopenEmployeeDraft,
  restoreEmployeeDraftRevision,
  reviewEmployeeDraft,
  rollbackEmployeeDraft,
  updateEmployeeDraft,
} from "../../api";
import { message } from "../../feedback";
import type {
  DigitalEmployeeDraft,
  DigitalEmployeeDraftRevision,
} from "../../types";
import { draftStatus, draftStatusColor } from "./shared";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export type DraftAction =
  | "APPROVE"
  | "REJECT"
  | "REOPEN"
  | "TRIAL"
  | "EVALUATE"
  | "PUBLISH"
  | "ROLLBACK";

export function EmployeeDraftsCard({
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
                  <DraftRevisionHistory draft={draft} />
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

export type DraftContent = {
  name: string;
  capabilities: string[];
  intents: string[];
  skill_codes: string[];
  tool_allowlist: string[];
};

export const draftContentLabels: Record<keyof DraftContent, string> = {
  name: "名称",
  capabilities: "能力",
  intents: "路由意图",
  skill_codes: "Skill 编码",
  tool_allowlist: "工具白名单",
};

export function readDraftContent(
  source: Record<string, unknown>,
): DraftContent {
  const readList = (key: string): string[] => {
    const value = source[key];
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  };
  return {
    name: typeof source.name === "string" ? source.name : "",
    capabilities: readList("capabilities"),
    intents: readList("intents"),
    skill_codes: readList("skill_codes"),
    tool_allowlist: readList("tool_allowlist"),
  };
}

export function formatDraftContentValue(value: string | string[]): string {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join("、") : "（空）";
  }
  return value || "（空）";
}

export function draftContentDiff(
  snapshot: Record<string, unknown>,
  draft: DigitalEmployeeDraft,
): { key: string; label: string; before: string; after: string }[] {
  const previous = readDraftContent(snapshot);
  const current: DraftContent = {
    name: draft.name,
    capabilities: draft.capabilities,
    intents: draft.intents,
    skill_codes: draft.skill_codes,
    tool_allowlist: draft.tool_allowlist,
  };
  return (
    Object.keys(draftContentLabels) as (keyof DraftContent)[]
  )
    .filter(
      (key) =>
        JSON.stringify(previous[key]) !==
        JSON.stringify(current[key]),
    )
    .map((key) => ({
      key,
      label: draftContentLabels[key],
      before: formatDraftContentValue(previous[key]),
      after: formatDraftContentValue(current[key]),
    }));
}

export function DraftRevisionHistory({
  draft,
}: {
  draft: DigitalEmployeeDraft;
}) {
  const queryClient = useQueryClient();
  const [preview, setPreview] =
    useState<DigitalEmployeeDraftRevision | null>(null);
  const revisions = useQuery({
    queryKey: ["employee-draft-revisions", draft.id],
    queryFn: () => listEmployeeDraftRevisions(draft.id),
  });
  const restore = useMutation({
    mutationFn: (revision: number) =>
      restoreEmployeeDraftRevision(draft.id, revision),
    onSuccess: async (_draft, revision) => {
      message.success(`已回退到 v${revision}`);
      setPreview(null);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["employee-draft-revisions"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const items: DigitalEmployeeDraftRevision[] =
    revisions.data ?? [];
  if (items.length === 0) return null;
  const rows = preview
    ? draftContentDiff(preview.snapshot, draft)
    : [];
  const canRestore =
    draft.status === "DRAFT" &&
    preview !== null &&
    preview.revision !== draft.revision &&
    rows.length > 0;
  return (
    <>
      <Collapse
        size="small"
        items={[
          {
            key: "revisions",
            label: `版本历史 · ${items.length}`,
            children: (
              <Timeline
                items={items.map((revision) => {
                  const changed = draftContentDiff(
                    revision.snapshot,
                    draft,
                  );
                  return {
                    color: draftStatusColor(revision.status),
                    children: (
                      <Space direction="vertical" size={4}>
                        <Space wrap>
                          <Text strong>v{revision.revision}</Text>
                          <Tag
                            color={draftStatusColor(revision.status)}
                          >
                            {draftStatus(revision.status)}
                          </Tag>
                        </Space>
                        <Text>
                          {revision.change_note || "状态更新"}
                        </Text>
                        <Text type="secondary">
                          {revision.created_by} ·{" "}
                          {new Date(
                            revision.created_at,
                          ).toLocaleString()}
                        </Text>
                        <Button
                          size="small"
                          onClick={() => setPreview(revision)}
                        >
                          {changed.length > 0
                            ? `对比版本 · ${changed.length} 项变更`
                            : "查看版本快照"}
                        </Button>
                      </Space>
                    ),
                  };
                })}
              />
            ),
          },
        ]}
      />
      <Modal
        open={preview !== null}
        title={
          preview
            ? `版本对比 · v${preview.revision} → 当前 v${draft.revision}`
            : "版本对比"
        }
        width={760}
        onCancel={() => setPreview(null)}
        footer={[
          <Button key="close" onClick={() => setPreview(null)}>
            关闭
          </Button>,
          <Button
            key="restore"
            type="primary"
            disabled={!canRestore}
            loading={restore.isPending}
            onClick={() => {
              if (preview) restore.mutate(preview.revision);
            }}
          >
            回退到此版本
          </Button>,
        ]}
      >
        {preview && (
          <Space
            direction="vertical"
            size="middle"
            style={{ width: "100%" }}
          >
            <Text type="secondary">
              左侧是所选版本，右侧是当前草案。回退只恢复名称、能力、
              路由意图、Skill 编码和工具白名单，不会改变评审状态，
              也不会删除历史版本。
            </Text>
            {rows.length > 0 ? (
              <Table
                size="small"
                pagination={false}
                rowKey="key"
                dataSource={rows}
                columns={[
                  {
                    title: "字段",
                    dataIndex: "label",
                    width: 120,
                  },
                  {
                    title: `所选版本 v${preview.revision}`,
                    dataIndex: "before",
                    render: (value: string) => (
                      <Text>{value}</Text>
                    ),
                  },
                  {
                    title: `当前 v${draft.revision}`,
                    dataIndex: "after",
                    render: (value: string) => (
                      <Text>{value}</Text>
                    ),
                  },
                ]}
              />
            ) : (
              <Alert
                type="success"
                showIcon
                message="该版本与当前草案内容一致"
              />
            )}
            {draft.status !== "DRAFT" && (
              <Alert
                type="info"
                showIcon
                message={`当前草案状态为 ${draftStatus(
                  draft.status,
                )}，只有 DRAFT 状态可以回退内容。`}
              />
            )}
          </Space>
        )}
      </Modal>
    </>
  );
}
