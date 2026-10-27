import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Drawer,
  Empty,
  Input,
  Menu,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  archiveKnowledgeDocument,
  createKnowledgeDocument,
  createKnowledgeEvaluationCase,
  createKnowledgeSpace,
  createKnowledgeVersion,
  listDigitalEmployees,
  listKnowledgeDocuments,
  listKnowledgeEvaluationCases,
  listKnowledgeEvaluationRuns,
  listKnowledgeFeedback,
  listKnowledgeFeedbackClusters,
  listKnowledgeRepairTasks,
  listKnowledgeSpaces,
  listKnowledgeVersions,
  publishKnowledgeVersion,
  restoreKnowledgeDocument,
  searchKnowledge,
  runKnowledgeEvaluation,
  updateKnowledgeRepairTask,
  verifyKnowledgeRepairTask,
  updateKnowledgeDocument,
  updateKnowledgeEvaluationCase,
  uploadKnowledgeVersion,
} from "./api";
import type {
  KnowledgeDocument,
  KnowledgeEvaluationCase,
  KnowledgeFeedback,
  KnowledgeFeedbackCluster,
  KnowledgeHit,
  KnowledgeRepairTask,
  KnowledgeSpace,
  KnowledgeVersion,
} from "./types";
import { useAuth } from "./auth";
import { message } from "./feedback";
import {
  channelLabels,
  feedbackRatingLabels,
  feedbackReasonLabels,
  knowledgeDocumentStatusLabels,
  knowledgeDocumentTypeLabels,
  knowledgeSyncStatusLabels,
  knowledgeVersionStatusLabels,
  localizedLabel,
} from "./statusLabels";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const knowledgeDomainLabels: Record<string, string> = {
  enterprise_service: "企业服务",
  customer_service: "客户服务",
  it_support: "IT 与权限",
  finance: "财务",
  hr_service: "人事",
  general: "通用",
  ecommerce: "电商",
  e2e: "测试",
};

const knowledgeDomainOrder: Record<string, number> = {
  enterprise_service: 0,
  customer_service: 1,
  it_support: 2,
  finance: 3,
  hr_service: 4,
  general: 5,
  ecommerce: 8,
  e2e: 9,
};

function localizedFeedbackText(value: string): string {
  return Object.entries(feedbackReasonLabels).reduce(
    (localized, [code, label]) => localized.replaceAll(code, label),
    value,
  );
}

function statusColor(status: string): string {
  if (status === "ACTIVE") return "green";
  if (status === "PROCESSING") return "blue";
  if (status === "FAILED") return "red";
  if (status === "SUPERSEDED") return "default";
  return "gold";
}

function KnowledgeVersions({
  document,
  readOnly = false,
  canWrite = true,
}: {
  document: KnowledgeDocument;
  readOnly?: boolean;
  canWrite?: boolean;
}) {
  const writeBlocked = readOnly || !canWrite;
  const queryClient = useQueryClient();
  const [versionOpen, setVersionOpen] = useState(false);
  const [versionLabel, setVersionLabel] = useState("");
  const [content, setContent] = useState("");
  const versions = useQuery({
    queryKey: ["knowledge", document.id, "versions"],
    queryFn: () => listKnowledgeVersions(document.id),
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === "PROCESSING") ? 2_000 : false,
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["knowledge", document.id] });
    queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
  };

  const createVersion = useMutation({
    mutationFn: () => createKnowledgeVersion(document.id, versionLabel, content),
    onSuccess: () => {
      message.success("知识版本已切分并入库");
      setVersionOpen(false);
      setVersionLabel("");
      setContent("");
      refresh();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const publish = useMutation({
    mutationFn: (version: KnowledgeVersion) =>
      publishKnowledgeVersion(document.id, version.id),
    onSuccess: () => {
      message.success("知识版本已发布");
      refresh();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const upload = useMutation({
    mutationFn: ({ label, file }: { label: string; file: File }) =>
      uploadKnowledgeVersion(document.id, label, file),
    onSuccess: () => {
      message.success("文件已上传，正在异步解析和向量化");
      refresh();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const columns: ColumnsType<KnowledgeVersion> = [
    {
      title: "版本",
      dataIndex: "version_label",
      width: 90,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 130,
      render: (value: string) => (
        <Tag color={statusColor(value)}>
          {knowledgeVersionStatusLabels[value] ?? "未知状态"}
        </Tag>
      ),
    },
    {
      title: "来源",
      dataIndex: "source_filename",
      render: (value: string | null, record) => (
        <Space direction="vertical" size={0}>
          <Text>{value ?? "文本 API"}</Text>
          <Text type="secondary">
            {record.parser_name ?? record.embedding_model}
          </Text>
        </Space>
      ),
    },
    {
      title: "Chunks",
      dataIndex: "chunk_count",
      width: 90,
    },
    {
      title: "生效时间",
      dataIndex: "effective_from",
      width: 190,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "操作",
      width: 120,
      render: (_value, record) =>
        !writeBlocked && record.status === "DRAFT" ? (
          <Button
            size="small"
            type="primary"
            loading={publish.isPending}
            onClick={() => publish.mutate(record)}
          >
            发布
          </Button>
        ) : null,
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        {!writeBlocked && (
          <>
            <Button type="primary" onClick={() => setVersionOpen(true)}>
              新建文本版本
            </Button>
            <Input
              placeholder="上传版本号，例如 2.0"
              value={versionLabel}
              onChange={(event) => setVersionLabel(event.target.value)}
              style={{ width: 220 }}
            />
            <Upload
              accept=".txt,.md,.markdown,.html,.htm,.docx,.pdf"
              showUploadList={false}
              beforeUpload={(file) => {
                if (!versionLabel.trim()) {
                  message.warning("请先填写版本号");
                  return Upload.LIST_IGNORE;
                }
                upload.mutate({ label: versionLabel, file });
                return Upload.LIST_IGNORE;
              }}
            >
              <Button loading={upload.isPending}>上传文件</Button>
            </Upload>
          </>
        )}
        {writeBlocked && (
          <Text type="secondary">
            {canWrite
              ? "当前为只读状态，恢复文档后才能新增或发布版本。"
              : "当前角色可以查看知识内容和版本，但不能新增或发布版本。"}
          </Text>
        )}
      </Space>

      {versions.data?.some((item) => item.ingestion_error) && (
        <Alert
          type="warning"
          showIcon
          message="部分版本处理失败"
          description={versions.data.find((item) => item.ingestion_error)?.ingestion_error}
        />
      )}
      <Table
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={versions.data}
        loading={versions.isLoading}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        locale={{ emptyText: <Empty description="暂无版本" /> }}
      />

      <Modal
        title="新建文本知识版本"
        open={versionOpen}
        onCancel={() => setVersionOpen(false)}
        onOk={() => createVersion.mutate()}
        confirmLoading={createVersion.isPending}
        okButtonProps={{ disabled: !versionLabel.trim() || !content.trim() }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Input
            placeholder="版本号"
            value={versionLabel}
            onChange={(event) => setVersionLabel(event.target.value)}
          />
          <TextArea
            rows={10}
            placeholder="输入 SOP、FAQ 或制度正文"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </Space>
      </Modal>
    </Space>
  );
}

export type KnowledgeSection =
  | "overview"
  | "spaces"
  | "documents"
  | "search"
  | "evaluation"
  | "repairs";

const knowledgeSections = [
  { key: "overview", label: "知识概览", path: "/knowledge" },
  { key: "spaces", label: "知识空间", path: "/knowledge/spaces" },
  { key: "documents", label: "知识文档", path: "/knowledge/documents" },
  { key: "search", label: "检索调试", path: "/knowledge/search" },
  { key: "evaluation", label: "质量评测", path: "/knowledge/evaluation" },
  { key: "repairs", label: "修复与反馈", path: "/knowledge/repairs" },
] as const;

const repairStatusLabels: Record<
  string,
  { label: string; color: string }
> = {
  OPEN: { label: "待修复", color: "gold" },
  IN_REPAIR: { label: "修复中", color: "orange" },
  VERIFIED: { label: "验证通过", color: "blue" },
  CLOSED: { label: "已关闭", color: "green" },
};

type FaqImportRow = {
  rowNumber: number;
  question: string;
  answer: string;
  valid: boolean;
  error: string | null;
};

function parseCsvCells(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (char === "," && !quoted) {
      row.push(cell.trim());
      cell = "";
      continue;
    }
    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function parseFaqCsv(text: string): FaqImportRow[] {
  const parsed = parseCsvCells(text);
  if (parsed.length === 0) return [];
  const header = parsed[0].map((cell) => cell.toLowerCase());
  const questionIndex = header.findIndex(
    (cell) => cell === "question" || cell === "问题" || cell === "标准问题",
  );
  const answerIndex = header.findIndex(
    (cell) => cell === "answer" || cell === "答案" || cell === "标准答案",
  );
  const startIndex = questionIndex >= 0 && answerIndex >= 0 ? 1 : 0;
  const effectiveQuestionIndex = questionIndex >= 0 ? questionIndex : 0;
  const effectiveAnswerIndex = answerIndex >= 0 ? answerIndex : 1;
  return parsed.slice(startIndex).map((row, offset) => {
    const question = (row[effectiveQuestionIndex] ?? "").trim();
    const answer = (row[effectiveAnswerIndex] ?? "").trim();
    const error =
      !question && !answer
        ? "问题与答案为空"
        : !question
          ? "缺少问题"
          : !answer
            ? "缺少答案"
            : `${question}\n${answer}`.length < 10
              ? "内容过短，至少需要 10 个字符"
              : null;
    return {
      rowNumber: offset + startIndex + 1,
      question,
      answer,
      valid: error === null,
      error,
    };
  });
}

export default function KnowledgePage({
  section,
  onNavigate,
}: {
  section: KnowledgeSection;
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const { hasCapability } = useAuth();
  const canWriteKnowledge = hasCapability("knowledge.write");
  const [selected, setSelected] = useState<KnowledgeDocument | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [spaceOpen, setSpaceOpen] = useState(false);
  const [evaluationOpen, setEvaluationOpen] = useState(false);
  const [evaluationFromRepair, setEvaluationFromRepair] = useState(false);
  const [evaluationName, setEvaluationName] = useState("");
  const [evaluationQuery, setEvaluationQuery] = useState("");
  const [evaluationSpaceId, setEvaluationSpaceId] = useState("");
  const [evaluationExpectedTitles, setEvaluationExpectedTitles] = useState("");
  const [evaluationScope, setEvaluationScope] = useState("{}");
  const [evaluationNoGrounding, setEvaluationNoGrounding] = useState(false);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("SOP");
  const [spaceId, setSpaceId] = useState("");
  const [documentSpaceFilter, setDocumentSpaceFilter] = useState(
    () => new URLSearchParams(window.location.search).get("space") ?? "",
  );
  const [documentStatusFilter, setDocumentStatusFilter] = useState("ACTIVE");
  const [spaceStatusFilter, setSpaceStatusFilter] = useState("ACTIVE");
  const [evaluationCaseFilter, setEvaluationCaseFilter] =
    useState("ACTIVE");
  const [spaceCode, setSpaceCode] = useState("");
  const [spaceName, setSpaceName] = useState("");
  const [spaceDescription, setSpaceDescription] = useState("");
  const [spaceChannel, setSpaceChannel] = useState("");
  const [spaceCategory, setSpaceCategory] = useState("");
  const [spaceCategoryProfileId, setSpaceCategoryProfileId] = useState("");
  const [spaceWorkflow, setSpaceWorkflow] = useState("");
  const [spaceEvaluationRequired, setSpaceEvaluationRequired] = useState(true);
  const [query, setQuery] = useState("");
  const [searchSpaceId, setSearchSpaceId] = useState("");
  const [searchEmployeeId, setSearchEmployeeId] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searchMeta, setSearchMeta] = useState("");
  const [faqImportOpen, setFaqImportOpen] = useState(false);
  const [faqImportSpaceId, setFaqImportSpaceId] = useState("");
  const [faqImportFileName, setFaqImportFileName] = useState("");
  const [faqImportRows, setFaqImportRows] = useState<FaqImportRow[]>([]);
  const [faqImporting, setFaqImporting] = useState(false);
  const [repairVerificationTask, setRepairVerificationTask] =
    useState<KnowledgeRepairTask | null>(null);
  const [repairExpectedTitles, setRepairExpectedTitles] = useState<string[]>(
    [],
  );
  const [repairVerificationRunning, setRepairVerificationRunning] =
    useState(false);

  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
  });
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
  });
  const documents = useQuery({
    queryKey: ["knowledge", "documents"],
    queryFn: () => listKnowledgeDocuments(),
  });
  const evaluationCases = useQuery({
    queryKey: ["knowledge", "evaluation-cases"],
    queryFn: listKnowledgeEvaluationCases,
  });
  const evaluationRuns = useQuery({
    queryKey: ["knowledge", "evaluation-runs"],
    queryFn: listKnowledgeEvaluationRuns,
  });
  const repairTasks = useQuery({
    queryKey: ["knowledge", "repair-tasks"],
    queryFn: listKnowledgeRepairTasks,
  });
  const feedback = useQuery({
    queryKey: ["knowledge", "feedback"],
    queryFn: listKnowledgeFeedback,
  });
  const feedbackClusters = useQuery({
    queryKey: ["knowledge", "feedback-clusters"],
    queryFn: listKnowledgeFeedbackClusters,
  });
  const activeSpaces = useMemo(
    () =>
      (spaces.data ?? []).filter(
        (space) => space.status === "ACTIVE" && space.domain !== "e2e",
      ),
    [spaces.data],
  );
  const activeSpaceIds = useMemo(
    () => new Set(activeSpaces.map((space) => space.id)),
    [activeSpaces],
  );
  const displayedSpaces = useMemo(
    () =>
      (spaceStatusFilter === "ACTIVE"
        ? activeSpaces
        : spaceStatusFilter === "ALL"
          ? spaces.data ?? []
          : (spaces.data ?? []).filter(
              (space) => space.status === "DISABLED",
            ))
        .slice()
        .sort(
          (left, right) =>
            (knowledgeDomainOrder[left.domain] ?? 6) -
              (knowledgeDomainOrder[right.domain] ?? 6) ||
            left.name.localeCompare(right.name, "zh-CN"),
        ),
    [activeSpaces, spaceStatusFilter, spaces.data],
  );
  useEffect(() => {
    if (!spaceId && activeSpaces.length) {
      setSpaceId(activeSpaces[0].id);
    }
  }, [activeSpaces, spaceId]);
  useEffect(() => {
    if (!evaluationSpaceId && activeSpaces.length) {
      setEvaluationSpaceId(activeSpaces[0].id);
    }
  }, [activeSpaces, evaluationSpaceId]);
  useEffect(() => {
    if (!faqImportSpaceId && activeSpaces.length) {
      setFaqImportSpaceId(activeSpaces[0].id);
    }
  }, [activeSpaces, faqImportSpaceId]);

  const importFaqRows = async () => {
    const validRows = faqImportRows.filter((row) => row.valid);
    if (!faqImportSpaceId || validRows.length === 0) return;
    setFaqImporting(true);
    let created = 0;
    const failures: string[] = [];
    for (const row of validRows) {
      try {
        const document = await createKnowledgeDocument({
          title: `FAQ · ${row.question}`,
          docType: "FAQ",
          spaceId: faqImportSpaceId,
          scope: {
            source: "faq_csv",
            source_filename: faqImportFileName,
            source_row: row.rowNumber,
          },
        });
        const version = await createKnowledgeVersion(
          document.id,
          "import-v1",
          `# 问题\n\n${row.question}\n\n# 标准答案\n\n${row.answer}`,
        );
        await publishKnowledgeVersion(document.id, version.id);
        created += 1;
      } catch (error) {
        failures.push(
          `第 ${row.rowNumber} 行：${(error as Error).message}`,
        );
      }
    }
    setFaqImporting(false);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] }),
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] }),
    ]);
    if (failures.length === 0) {
      message.success(`FAQ 批量导入完成：已发布 ${created} 条知识`);
      setFaqImportOpen(false);
      setFaqImportRows([]);
      setFaqImportFileName("");
      return;
    }
    message.warning(
      `FAQ 导入完成：成功 ${created} 条，失败 ${failures.length} 条。${failures[0]}`,
    );
  };

  const createSpace = useMutation({
    mutationFn: () =>
      createKnowledgeSpace({
        code: spaceCode,
        name: spaceName,
        description: spaceDescription,
        channel: spaceChannel,
        category: spaceCategory,
        categoryProfileId: spaceCategoryProfileId,
        workflowKey: spaceWorkflow,
        evaluationRequired: spaceEvaluationRequired,
      }),
    onSuccess: (space) => {
      message.success("知识空间已创建");
      setSpaceOpen(false);
      setSpaceCode("");
      setSpaceName("");
      setSpaceDescription("");
      setSpaceCategoryProfileId("");
      setSpaceId(space.id);
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const createEvaluation = useMutation({
    mutationFn: () => {
      let scope: Record<string, string>;
      try {
        scope = JSON.parse(evaluationScope) as Record<string, string>;
      } catch {
        throw new Error("检索上下文必须是 JSON 对象");
      }
      return createKnowledgeEvaluationCase({
        name: evaluationName,
        query: evaluationQuery,
        knowledgeSpaceId: evaluationSpaceId,
        expectedTitles: evaluationExpectedTitles
          .split("\n")
          .map((title) => title.trim())
          .filter(Boolean),
        expectNoGrounding: evaluationNoGrounding,
        scope,
      });
    },
    onSuccess: () => {
      message.success(
        evaluationFromRepair
          ? "回归评测案例已创建，请点击“运行全部评测”"
          : "评测案例已创建",
      );
      const returnToEvaluation = evaluationFromRepair;
      setEvaluationOpen(false);
      setEvaluationFromRepair(false);
      setEvaluationName("");
      setEvaluationQuery("");
      setEvaluationExpectedTitles("");
      setEvaluationScope("{}");
      setEvaluationNoGrounding(false);
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "evaluation-cases"],
      });
      if (returnToEvaluation) onNavigate("/knowledge/evaluation");
    },
    onError: (error: Error) => message.error(error.message),
  });
  const runEvaluation = useMutation({
    mutationFn: () => runKnowledgeEvaluation(),
    onSuccess: (run) => {
      message[
        run.verdict === "PASS" ? "success" : "warning"
      ](
        `评测${run.verdict === "PASS" ? "通过" : "未通过"}：${run.passed_cases}/${run.case_count}`,
      );
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "evaluation-runs"],
      });
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "repair-tasks"],
      });
    },
    onError: (error: Error) => {
      if (
        error instanceof ApiError &&
        error.code === "KNOWLEDGE_EVALUATION_CASES_EMPTY"
      ) {
        message.warning(
          "至少启用一个评测案例后才能运行评测，请先启用案例或新建案例。",
        );
        queryClient.invalidateQueries({
          queryKey: ["knowledge", "evaluation-cases"],
        });
        return;
      }
      message.error(error.message);
    },
  });
  const updateRepair = useMutation({
    mutationFn: ({
      taskId,
      status,
    }: {
      taskId: string;
      status: string;
    }) => updateKnowledgeRepairTask(taskId, { status }),
    onSuccess: () => {
      message.success("修复任务状态已更新");
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "repair-tasks"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const verifyRepair = useMutation({
    mutationFn: (taskId: string) => verifyKnowledgeRepairTask(taskId),
    onSuccess: (task) => {
      if (task.status === "VERIFIED") {
        message.success("验证通过，可以关闭修复任务");
      } else {
        message.warning(
          "验证未通过，仍需继续修复。请修改或补充知识后再次验证。",
        );
      }
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "repair-tasks"],
      });
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "evaluation-runs"],
      });
    },
    onError: (error: Error) => {
      if (
        error instanceof ApiError &&
        error.code === "KNOWLEDGE_EVALUATION_CASES_EMPTY"
      ) {
        message.warning(
          "暂时无法重新评测：请先在“质量评测”中启用至少一个评测案例。",
        );
        queryClient.invalidateQueries({
          queryKey: ["knowledge", "evaluation-cases"],
        });
        return;
      }
      message.error(error.message);
    },
  });
  const updateEvaluationCase = useMutation({
    mutationFn: ({
      caseId,
      enabled,
    }: {
      caseId: string;
      enabled: boolean;
    }) => updateKnowledgeEvaluationCase(caseId, enabled),
    onSuccess: () => {
      message.success("评测案例状态已更新");
      queryClient.invalidateQueries({
        queryKey: ["knowledge", "evaluation-cases"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const openRepairVerification = (task: KnowledgeRepairTask) => {
    const relatedCase = evaluationCases.data?.find(
      (item) => item.id === task.evaluation_case_id,
    );
    if (relatedCase?.enabled) {
      verifyRepair.mutate(task.id);
      return;
    }
    setRepairVerificationTask(task);
    setRepairExpectedTitles(
      relatedCase?.expected_titles.length
        ? relatedCase.expected_titles
        : task.expected_titles,
    );
  };
  const openRepairKnowledge = async (task: KnowledgeRepairTask) => {
    if (task.status === "OPEN") {
      try {
        await updateKnowledgeRepairTask(task.id, {
          status: "IN_REPAIR",
        });
        await queryClient.invalidateQueries({
          queryKey: ["knowledge", "repair-tasks"],
        });
      } catch (error) {
        message.error((error as Error).message);
        return;
      }
    }
    const query = task.knowledge_space_id
      ? `?space=${encodeURIComponent(task.knowledge_space_id)}`
      : "";
    onNavigate(`/knowledge/documents${query}`);
  };
  const runRepairVerification = async () => {
    const task = repairVerificationTask;
    if (!task || repairExpectedTitles.length === 0) return;
    setRepairVerificationRunning(true);
    try {
      const relatedCase = evaluationCases.data?.find(
        (item) => item.id === task.evaluation_case_id,
      );
      if (relatedCase && !relatedCase.enabled) {
        await updateKnowledgeEvaluationCase(relatedCase.id, true);
      } else if (!relatedCase) {
        await createKnowledgeEvaluationCase({
          name: `回归评测 · ${task.title}`.slice(0, 300),
          query: task.query,
          knowledgeSpaceId:
            task.knowledge_space_id ?? activeSpaces[0]?.id ?? "",
          expectedTitles: repairExpectedTitles,
          expectNoGrounding: false,
          scope: {},
        });
      }
      const run = await runKnowledgeEvaluation(
        task.knowledge_space_id ?? undefined,
      );
      const passed = run.verdict === "PASS";
      await updateKnowledgeRepairTask(task.id, {
        status: passed ? "VERIFIED" : "IN_REPAIR",
        resolutionNote: passed
          ? `自动回归评测 ${run.id} 通过：${run.passed_cases}/${run.case_count}`
          : `自动回归评测 ${run.id} 未通过：${run.failed_cases} 个失败`,
      });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["knowledge", "repair-tasks"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["knowledge", "evaluation-cases"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["knowledge", "evaluation-runs"],
        }),
      ]);
      setRepairVerificationTask(null);
      message[passed ? "success" : "warning"](
        passed
          ? `修复验证通过：${run.passed_cases}/${run.case_count} 个案例通过，可以关闭任务`
          : `修复验证未通过：仍有 ${run.failed_cases} 个案例失败，请继续修复知识`,
      );
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setRepairVerificationRunning(false);
    }
  };
  const createDocument = useMutation({
    mutationFn: () => createKnowledgeDocument({ title, docType, spaceId }),
    onSuccess: (document) => {
      message.success("知识文档已创建");
      setCreateOpen(false);
      setTitle("");
      setSelected(document);
      queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const updateDocument = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("未选择文档");
      return updateKnowledgeDocument(selected.id, {
        title,
        docType,
        spaceId,
      });
    },
    onSuccess: (document) => {
      message.success("知识文档已更新");
      setEditOpen(false);
      setSelected(document);
      queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const archiveDocument = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("未选择文档");
      return archiveKnowledgeDocument(selected.id);
    },
    onSuccess: (document) => {
      message.success("知识文档已归档");
      setArchiveOpen(false);
      setSelected(document);
      queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const restoreDocument = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error("未选择文档");
      return restoreKnowledgeDocument(selected.id);
    },
    onSuccess: (document) => {
      message.success("知识文档已恢复，可以继续检索和发布版本");
      setSelected(document);
      queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "spaces"] });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const search = useMutation({
    mutationFn: () =>
      searchKnowledge(query, {
        spaceId: searchSpaceId || undefined,
        employeeId: searchEmployeeId || undefined,
      }),
    onSuccess: (result) => {
      setHits(result.items);
      setSearchMeta(
        `${result.embedding_model} · ${result.reranker} · ${
          result.retrieval_mode === "hybrid" ? "混合检索" : "向量检索"
        }`,
      );
    },
    onError: (error: Error) => message.error(error.message),
  });

  const spaceNames = new Map(
    (spaces.data ?? []).map((space) => [space.id, space.name]),
  );
  const spaceColumns: ColumnsType<KnowledgeSpace> = [
    {
      title: "知识空间",
      dataIndex: "name",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{record.code}</Text>
        </Space>
      ),
    },
    {
      title: "业务领域",
      dataIndex: "domain",
      width: 110,
      render: (value: string) => (
        <Tag color={value === "ecommerce" ? "gold" : "blue"}>
          {knowledgeDomainLabels[value] ?? value}
        </Tag>
      ),
    },
    {
      title: "渠道 / 主题",
      render: (_value, record) => (
        <Space wrap size={4}>
          {record.channel && (
            <Tag>
              {localizedLabel(channelLabels, record.channel)}
            </Tag>
          )}
          {record.category && <Tag>{record.category}</Tag>}
        </Space>
      ),
    },
    {
      title: "工作流",
      dataIndex: "workflow_key",
      render: (value: string | null) => value ?? "通用",
    },
    {
      title: "文档",
      dataIndex: "document_count",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (value: string) => (
        <Tag color={value === "ACTIVE" ? "green" : "default"}>
          {value === "ACTIVE" ? "可用" : "已停用"}
        </Tag>
      ),
    },
    {
      title: "发布门禁",
      dataIndex: "evaluation_required",
      width: 110,
      render: (value: boolean) => (
        <Tag color={value ? "orange" : "default"}>
          {value ? "需评测" : "不启用"}
        </Tag>
      ),
    },
  ];
  const columns: ColumnsType<KnowledgeDocument> = [
    {
      title: "文档",
      dataIndex: "title",
      render: (value: string, record) => (
        <Button type="link" onClick={() => setSelected(record)}>
          {value}
        </Button>
      ),
    },
    {
      title: "类型",
      dataIndex: "doc_type",
      width: 100,
      render: (value: string) =>
        knowledgeDocumentTypeLabels[value] ?? "其他资料",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (value: string) => (
        <Tag color={statusColor(value)}>
          {knowledgeDocumentStatusLabels[value] ?? "未知状态"}
        </Tag>
      ),
    },
    {
      title: "知识空间",
      dataIndex: "space_id",
      width: 180,
      render: (value: string | null) =>
        value ? (spaceNames.get(value) ?? value) : "未归类",
    },
    {
      title: "来源同步",
      dataIndex: "sync_status",
      width: 130,
      render: (value: string | null, record) =>
        record.source_type ? (
          <Tag color={value === "SYNCED" ? "blue" : "red"}>
            {value
              ? (knowledgeSyncStatusLabels[value] ?? "未知状态")
              : "尚未同步"}
          </Tag>
        ) : (
          <Text type="secondary">手工维护</Text>
        ),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 190,
      render: (value: string) => new Date(value).toLocaleString(),
    },
  ];
  const evaluationColumns: ColumnsType<KnowledgeEvaluationCase> = [
    {
      title: "评测问题",
      dataIndex: "name",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{localizedFeedbackText(value)}</Text>
          <Paragraph
            type="secondary"
            ellipsis={{ rows: 2, tooltip: record.query }}
            style={{ margin: 0, maxWidth: 680 }}
          >
            {record.query}
          </Paragraph>
        </Space>
      ),
    },
    {
      title: "知识空间",
      dataIndex: "knowledge_space_id",
      width: 180,
      render: (value: string | null) =>
        value ? (spaceNames.get(value) ?? value) : "跨空间",
    },
    {
      title: "预期",
      width: 220,
      render: (_value, record) =>
        record.expect_no_grounding
          ? "应无召回"
          : record.expected_titles.join("、"),
    },
    {
      title: "状态",
      dataIndex: "enabled",
      width: 90,
      render: (value: boolean) => (
        <Tag color={value ? "green" : "default"}>
          {value ? "启用" : "停用"}
        </Tag>
      ),
    },
    {
      title: "操作",
      width: 90,
      render: (_value, record) =>
        canWriteKnowledge ? (
          <Button
            type="link"
            loading={updateEvaluationCase.isPending}
            onClick={() =>
              updateEvaluationCase.mutate({
                caseId: record.id,
                enabled: !record.enabled,
              })
            }
          >
            {record.enabled ? "停用" : "启用"}
          </Button>
        ) : (
          <Text type="secondary">只读</Text>
        ),
    },
  ];
  const repairColumns: ColumnsType<KnowledgeRepairTask> = [
    {
      title: "问题",
      dataIndex: "title",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{localizedFeedbackText(value)}</Text>
          <Paragraph
            type="secondary"
            ellipsis={{ rows: 2, tooltip: record.query }}
            style={{ margin: 0, maxWidth: 680 }}
          >
            {record.query}
          </Paragraph>
          {(record.occurrence_count ?? 1) > 1 && (
            <Tag color="orange">
              相同问题出现 {record.occurrence_count} 次
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: "知识空间",
      dataIndex: "knowledge_space_id",
      width: 170,
      render: (value: string | null) =>
        value ? (spaceNames.get(value) ?? value) : "跨空间",
    },
    {
      title: "优先级",
      dataIndex: "priority",
      width: 90,
      render: (value: string) => (
        <Tag color={value === "P1" ? "orange" : "default"}>{value}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string) => {
        const status = repairStatusLabels[value];
        return (
          <Tag color={status?.color ?? "default"}>
            {status?.label ?? "未知状态"}
          </Tag>
        );
      },
    },
    {
      title: "操作",
      width: 240,
      render: (_value, record) => {
        if (!canWriteKnowledge) {
          return <Text type="secondary">只读</Text>;
        }
        if (record.status === "CLOSED") return null;
        if (record.status === "VERIFIED") {
          return (
            <Button
              type="link"
              loading={updateRepair.isPending}
              onClick={() =>
                updateRepair.mutate({ taskId: record.id, status: "CLOSED" })
              }
            >
              关闭任务
            </Button>
          );
        }
        if (record.status === "IN_REPAIR") {
          return (
            <Space direction="vertical" size={0}>
              <Button
                type="link"
                onClick={() => void openRepairKnowledge(record)}
              >
                补充知识
              </Button>
              <Button
                type="primary"
                size="small"
                loading={
                  verifyRepair.isPending ||
                  repairVerificationRunning
                }
                onClick={() => openRepairVerification(record)}
              >
                一键验证修复
              </Button>
            </Space>
          );
        }
        return (
          <Space direction="vertical" size={0}>
            <Button
              type="link"
              onClick={() => void openRepairKnowledge(record)}
            >
              补充知识
            </Button>
            <Button
              type="link"
              loading={updateRepair.isPending}
              onClick={() =>
                updateRepair.mutate({
                  taskId: record.id,
                  status: "IN_REPAIR",
                })
              }
            >
              开始修复
            </Button>
          </Space>
        );
      },
    },
  ];
  const feedbackColumns: ColumnsType<KnowledgeFeedback> = [
    {
      title: "用户问题",
      dataIndex: "query",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text>{value}</Text>
          <Text type="secondary">
            {record.details ??
              feedbackReasonLabels[record.reason_code] ??
              "未说明原因"}
          </Text>
        </Space>
      ),
    },
    {
      title: "评价",
      dataIndex: "rating",
      width: 100,
      render: (value: string) => (
        <Tag color={value === "NEGATIVE" ? "red" : "green"}>
          {feedbackRatingLabels[value] ?? "已反馈"}
        </Tag>
      ),
    },
    {
      title: "知识空间",
      dataIndex: "knowledge_space_id",
      width: 170,
      render: (value: string | null) =>
        value ? (spaceNames.get(value) ?? value) : "-",
    },
    {
      title: "修复任务",
      dataIndex: "repair_task_id",
      width: 130,
      render: (value: string | null) => (value ? "已生成" : "-"),
    },
  ];
  const feedbackClusterColumns: ColumnsType<KnowledgeFeedbackCluster> = [
    {
      title: "知识空间",
      dataIndex: "knowledge_space_id",
      render: (value: string | null) =>
        value ? (spaceNames.get(value) ?? value) : "跨空间",
    },
    {
      title: "原因",
      dataIndex: "reason_code",
      render: (value: string) => (
        <Tag color="red">
          {feedbackReasonLabels[value] ?? "其他问题"}
        </Tag>
      ),
    },
    {
      title: "数量",
      dataIndex: "count",
      width: 80,
    },
    {
      title: "最近问题",
      dataIndex: "latest_query",
    },
    {
      title: "修复任务",
      dataIndex: "repair_task_ids",
      width: 110,
      render: (value: string[]) => (value.length ? `${value.length} 个` : "-"),
    },
  ];
  const latestEvaluation = evaluationRuns.data?.items[0];
  const enabledEvaluationCases =
    evaluationCases.data?.filter((item) => item.enabled) ?? [];
  const displayedEvaluationCases = (
    evaluationCaseFilter === "ALL"
      ? evaluationCases.data ?? []
      : (evaluationCases.data ?? []).filter((item) =>
          evaluationCaseFilter === "ACTIVE"
            ? item.enabled
            : !item.enabled,
        )
  );

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div>
        <Typography.Title level={2}>知识库工作台</Typography.Title>
        <Paragraph type="secondary">
          按任务进入独立页面。先管理知识空间和文档，再调试检索，
          最后查看评测质量、修复任务与知识使用反馈。
        </Paragraph>
        <Menu
          className="knowledge-subnav"
          mode="horizontal"
          selectedKeys={[
            knowledgeSections.find((item) => item.key === section)?.path ??
              "/knowledge",
          ]}
          onClick={({ key }) => onNavigate(key)}
          items={knowledgeSections.map((item) => ({
            key: item.path,
            label: item.label,
          }))}
        />
      </div>

      {!canWriteKnowledge && (
        <Alert
          type="info"
          showIcon
          message="当前角色为知识只读视图"
          description="可以查看空间、文档、版本、检索和评测结果；创建、发布、归档和修复操作仅对知识运营或平台管理员开放。"
        />
      )}

      {section === "overview" && (
        <>
          <Alert
            type="info"
            showIcon
            message="先确认你现在要做什么"
            description="知识来源包括制度、SOP、FAQ、产品资料、业务规则和外部知识系统。可以手工录入、上传文件或批量导入问答。"
          />
          <Row gutter={[16, 16]}>
            {[
              {
                title: "知识空间",
                value: activeSpaces.length,
                suffix: "个",
                description: "按渠道、品类和业务归属整理知识。",
                path: "/knowledge/spaces",
                button: "管理知识空间",
              },
              {
                title: "知识文档",
                value: documents.data?.length ?? 0,
                suffix: "份",
                description: "维护制度、SOP、FAQ、产品资料和业务规则。",
                path: "/knowledge/documents",
                button: "管理知识文档",
              },
              {
                title: "已启用评测",
                value: enabledEvaluationCases.length,
                suffix: "条",
                description: "用固定问题验证召回和拒答质量。",
                path: "/knowledge/evaluation",
                button: "查看质量评测",
              },
              {
                title: "待处理修复",
                value:
                  repairTasks.data?.items.filter(
                    (item) => item.status !== "CLOSED",
                  ).length ?? 0,
                suffix: "个",
                description: "集中处理评测失败和线上负反馈。",
                path: "/knowledge/repairs",
                button: "处理修复任务",
              },
            ].map((item) => (
              <Col xs={24} md={12} xl={6} key={item.title}>
                <Card
                  className="knowledge-overview-card"
                  extra={
                    <Button
                      type="link"
                      onClick={() => onNavigate(item.path)}
                    >
                      {item.button}
                    </Button>
                  }
                >
                  <Statistic
                    title={item.title}
                    value={item.value}
                    suffix={item.suffix}
                  />
                  <Paragraph
                    type="secondary"
                    style={{ margin: "12px 0 0" }}
                  >
                    {item.description}
                  </Paragraph>
                </Card>
              </Col>
            ))}
          </Row>
          <Card title="推荐操作顺序">
            <Space direction="vertical">
              <Text>1. 在“知识空间”创建资料归属。</Text>
              <Text>2. 在“知识文档”创建版本并发布。</Text>
              <Text>3. 在“检索调试”确认数字员工能命中正确资料。</Text>
              <Text>4. 在“质量评测”运行固定问题，失败后到“修复与反馈”处理。</Text>
            </Space>
          </Card>
        </>
      )}

      {section === "spaces" && (
      <Card
        title="知识空间"
        extra={
          <Space>
            <Select
              aria-label="知识空间状态"
              value={spaceStatusFilter}
              onChange={setSpaceStatusFilter}
              options={[
                { value: "ACTIVE", label: "当前可用" },
                { value: "DISABLED", label: "已停用" },
                { value: "ALL", label: "全部状态" },
              ]}
              style={{ width: 130 }}
            />
            {canWriteKnowledge && (
              <Button type="primary" onClick={() => setSpaceOpen(true)}>
                新建知识空间
              </Button>
            )}
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          message="知识空间是资料归属，不代表资料来源"
          description="你可以为制度政策、操作流程、常见问答、产品资料或任意业务主题建立空间；文档和导入内容都归属到空间后供数字员工使用。"
          style={{ marginBottom: 16 }}
        />
        <Table
          rowKey="id"
          columns={spaceColumns}
          dataSource={displayedSpaces}
          loading={spaces.isLoading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          locale={{
            emptyText: (
              <Empty description="先创建知识空间，再归类文档并绑定数字员工" />
            ),
          }}
          scroll={{ x: 880 }}
        />
      </Card>
      )}

      {section === "documents" && (
        <>
          <Alert
            type="info"
            showIcon
            message="通用知识从这里接入"
            description="支持制度与政策、SOP 操作流程、FAQ 问答和产品文档。创建文档后，可录入文本版本或上传 TXT、Markdown、HTML、DOCX、PDF 文件。"
          />
          <Card
            title="资料接入方式"
            extra={
              <Space>
                {canWriteKnowledge && (
                  <>
                    <Button onClick={() => setFaqImportOpen(true)}>
                      批量导入 FAQ CSV
                    </Button>
                    <Button
                      type="primary"
                      disabled={!activeSpaces.length}
                      onClick={() => setCreateOpen(true)}
                    >
                      新建文档
                    </Button>
                  </>
                )}
              </Space>
            }
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Text strong>制度与业务规则</Text>
                <Paragraph type="secondary">
                  录入客户服务、退换货、财务、人事、IT 等制度，适合使用“制度”类型。
                </Paragraph>
              </Col>
              <Col xs={24} md={8}>
                <Text strong>SOP、FAQ 与客服问答</Text>
                <Paragraph type="secondary">
                  录入操作流程和常见问答；一问一答资料可通过 CSV 批量导入。
                </Paragraph>
              </Col>
              <Col xs={24} md={8}>
                <Text strong>外部知识源</Text>
                <Paragraph type="secondary">
                  支持为飞书、Confluence、共享盘和业务 API 增加连接器；当前尚未接通。
                </Paragraph>
              </Col>
            </Row>
          </Card>
          <Card
            title="知识文档"
            extra={
              <Space wrap>
                <Select
                  value={documentStatusFilter}
                  onChange={setDocumentStatusFilter}
                  style={{ width: 140 }}
                  options={[
                    { value: "ACTIVE", label: "当前可用" },
                    { value: "ARCHIVED", label: "已归档" },
                    { value: "ALL", label: "全部状态" },
                  ]}
                />
                <Select
                  allowClear
                  value={documentSpaceFilter || undefined}
                  onChange={(value) => setDocumentSpaceFilter(value ?? "")}
                  placeholder="按知识空间筛选"
                  style={{ width: 260 }}
                  options={activeSpaces.map((space) => ({
                    value: space.id,
                    label: `${space.name} · ${space.code}`,
                  }))}
                />
              </Space>
            }
          >
            {documentSpaceFilter && (
              <Alert
                type="info"
                showIcon
                message="正在查看指定知识空间的文档"
                description="点击目标文档，进入版本管理后新增文本版本或上传文件；发布新版本后返回修复任务点击“一键验证修复”。"
                style={{ marginBottom: 16 }}
              />
            )}
            <Table
              rowKey="id"
              columns={columns}
              dataSource={(documents.data ?? []).filter(
                (document) =>
                  (!documentSpaceFilter ||
                    document.space_id === documentSpaceFilter) &&
                  (documentStatusFilter === "ALL" ||
                    document.space_id === documentSpaceFilter ||
                    !document.space_id ||
                    activeSpaceIds.has(document.space_id)) &&
                  (documentStatusFilter === "ALL" ||
                    document.status === documentStatusFilter),
              )}
              loading={documents.isLoading}
              pagination={{ pageSize: 10, showSizeChanger: true }}
              locale={{
                emptyText: (
                  <Empty
                    description={
                      documentSpaceFilter
                        ? "该知识空间暂无文档，请点击“新建文档”补充"
                        : documentStatusFilter === "ARCHIVED"
                          ? "暂无已归档知识文档"
                          : "暂无当前可用的知识文档"
                    }
                  />
                ),
              }}
              scroll={{ x: 700 }}
            />
          </Card>
        </>
      )}

      {section === "search" && (
          <Card title="检索调试" extra={<Text type="secondary">{searchMeta}</Text>}>
            <Alert
              type="info"
              showIcon
              message="这里只验证检索结果"
              description="可以先按知识空间或数字员工权限过滤，再输入业务问题查看命中的文档、片段和分数。"
              style={{ marginBottom: 16 }}
            />
            <Space direction="vertical" size="small" style={{ width: "100%" }}>
              <Select
                allowClear
                value={searchSpaceId || undefined}
                onChange={(value) => setSearchSpaceId(value ?? "")}
                placeholder="选择知识空间（不选则全部）"
                options={activeSpaces.map((space) => ({
                  value: space.id,
                  label: `${space.name} · ${space.code}`,
                }))}
                style={{ width: "100%" }}
              />
              <Select
                allowClear
                value={searchEmployeeId || undefined}
                onChange={(value) => setSearchEmployeeId(value ?? "")}
                placeholder="按数字员工绑定权限过滤（可选）"
                options={(employees.data ?? []).map((employee) => ({
                  value: employee.id,
                  label: employee.name,
                }))}
                style={{ width: "100%" }}
              />
              <Space.Compact style={{ width: "100%" }}>
                <Input
                  placeholder="输入业务问题"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onPressEnter={() => query.trim() && search.mutate()}
                />
                <Button
                  type="primary"
                  loading={search.isPending}
                  disabled={!query.trim()}
                  onClick={() => search.mutate()}
                >
                  检索
                </Button>
              </Space.Compact>
            </Space>
            <Space direction="vertical" size="middle" style={{ width: "100%", marginTop: 16 }}>
              {hits.map((hit) => (
                <Card key={hit.chunk_id} size="small" title={`${hit.title} · v${hit.version}`}>
                  <Paragraph ellipsis={{ rows: 4 }}>{hit.content}</Paragraph>
                  <Text type="secondary">Score {hit.score.toFixed(3)}</Text>
                </Card>
              ))}
              {!hits.length && <Empty description="输入问题查看召回结果" />}
            </Space>
          </Card>
      )}

      {section === "evaluation" && (
      <Card
        title="知识评测"
        extra={
          <Space>
            <Select
              aria-label="评测案例范围"
              value={evaluationCaseFilter}
              onChange={setEvaluationCaseFilter}
              options={[
                { value: "ACTIVE", label: "当前启用" },
                { value: "DISABLED", label: "已停用" },
                { value: "ALL", label: "全部案例" },
              ]}
              style={{ width: 120 }}
            />
            <Tag color={enabledEvaluationCases.length ? "green" : "default"}>
              已启用 {enabledEvaluationCases.length}
            </Tag>
            {canWriteKnowledge && (
              <>
                <Button
                  onClick={() => {
                    setEvaluationFromRepair(false);
                    setEvaluationOpen(true);
                  }}
                >
                  新建评测案例
                </Button>
                <Button
                  type="primary"
                  loading={runEvaluation.isPending}
                  disabled={
                    evaluationCases.isLoading ||
                    enabledEvaluationCases.length === 0
                  }
                  onClick={() => runEvaluation.mutate()}
                >
                  运行全部评测
                </Button>
              </>
            )}
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          message="测试案例怎么建"
          description="一条案例由“业务问题、所属知识空间、预期命中文档”组成。创建并启用后，点击右上角“运行全部评测”开始测试；评测失败会自动进入修复队列。"
          style={{ marginBottom: 16 }}
        />
        {latestEvaluation && (
          <Alert
            type={latestEvaluation.verdict === "PASS" ? "success" : "warning"}
            showIcon
            message={`最近评测：${latestEvaluation.verdict} · ${latestEvaluation.passed_cases}/${latestEvaluation.case_count} 通过`}
            description={[
              `Recall@K ${latestEvaluation.recall_at_k?.toFixed(3) ?? "-"}`,
              `MRR ${latestEvaluation.mrr?.toFixed(3) ?? "-"}`,
              `正确拒答率 ${latestEvaluation.no_grounding_accuracy?.toFixed(3) ?? "-"}`,
            ].join(" · ")}
            style={{ marginBottom: 16 }}
          />
        )}
        {!evaluationCases.isLoading &&
          (evaluationCases.data?.length ?? 0) > 0 &&
          enabledEvaluationCases.length === 0 && (
            <Alert
              type="warning"
              showIcon
              message="暂无可运行的评测案例"
              description="当前案例均已停用。请启用至少一个案例后再运行全部评测。"
              style={{ marginBottom: 16 }}
            />
          )}
        <Table
          rowKey="id"
          size="small"
          columns={evaluationColumns}
          dataSource={displayedEvaluationCases}
          loading={evaluationCases.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{
            emptyText: (
              <Empty description="先创建并启用至少一个评测案例" />
            ),
          }}
        />
      </Card>
      )}

      {section === "repairs" && (
      <>
      <Card
        title="知识修复队列"
        extra={<Text type="secondary">{repairTasks.data?.total ?? 0} 个任务</Text>}
      >
        <Alert
          type="info"
          showIcon
          message="一键验证怎么用"
          description="先修改或补充知识，再点击任务右侧“一键验证修复”。系统会自动创建或启用回归案例、运行评测并更新修复结果；必要时只需选择正确知识文档。"
          style={{ marginBottom: 16 }}
        />
        <Table
          rowKey="id"
          size="small"
          columns={repairColumns}
          dataSource={repairTasks.data?.items}
          loading={repairTasks.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="评测失败后会自动生成修复任务" /> }}
        />
      </Card>

      <Card
        title="知识使用反馈"
        extra={<Text type="secondary">{feedback.data?.total ?? 0} 条</Text>}
      >
        {(feedbackClusters.data?.items.length ?? 0) > 0 && (
          <Table
            rowKey={(record) =>
              `${record.knowledge_space_id ?? "all"}:${record.reason_code}`
            }
            size="small"
            columns={feedbackClusterColumns}
            dataSource={feedbackClusters.data?.items}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            loading={feedbackClusters.isLoading}
            style={{ marginBottom: 16 }}
          />
        )}
        <Table
          rowKey="id"
          size="small"
          columns={feedbackColumns}
          dataSource={feedback.data?.items}
          loading={feedback.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂时没有知识使用反馈" /> }}
        />
      </Card>
      </>
      )}

      {section === "documents" && selected && (
        <Drawer
          width={820}
          title={`版本管理 · ${selected.title}`}
          open
          onClose={() => setSelected(null)}
          extra={
            <Space>
              <Tag color={selected.status === "ARCHIVED" ? "default" : "green"}>
                {knowledgeDocumentStatusLabels[selected.status] ?? "未知状态"}
              </Tag>
              {!canWriteKnowledge && <Tag>只读</Tag>}
              {canWriteKnowledge &&
                (selected.status === "ARCHIVED" ? (
                  <Button
                    type="primary"
                    loading={restoreDocument.isPending}
                    onClick={() => restoreDocument.mutate()}
                  >
                    恢复使用
                  </Button>
                ) : (
                  <>
                    <Button
                      onClick={() => {
                        setTitle(selected.title);
                        setDocType(selected.doc_type);
                        setSpaceId(selected.space_id ?? "");
                        setEditOpen(true);
                      }}
                    >
                      编辑
                    </Button>
                    <Button
                      danger
                      loading={archiveDocument.isPending}
                      onClick={() => setArchiveOpen(true)}
                    >
                      归档
                    </Button>
                  </>
                ))}
            </Space>
          }
        >
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            {selected.status === "ARCHIVED" && (
              <Alert
                type="warning"
                showIcon
                message="该文档已归档"
                description="当前不会参与知识检索，也不能新增或发布版本；历史版本仍可查看。"
              />
            )}
            <KnowledgeVersions
              document={selected}
              readOnly={selected.status === "ARCHIVED"}
              canWrite={canWriteKnowledge}
            />
          </Space>
        </Drawer>
      )}

      <Modal
        title="批量导入 FAQ 知识"
        open={faqImportOpen}
        onCancel={() => {
          if (!faqImporting) setFaqImportOpen(false);
        }}
        onOk={() => void importFaqRows()}
        okText="导入并发布"
        cancelText="取消"
        width={900}
        confirmLoading={faqImporting}
        okButtonProps={{
          disabled:
            !faqImportSpaceId ||
            !faqImportRows.some((row) => row.valid) ||
            faqImporting,
        }}
      >
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%" }}
        >
          <Alert
            type="info"
            showIcon
            message="通用问答资料"
            description="CSV 使用 question,answer 两列。导入后会为每条问答创建 FAQ 文档、生成知识版本并发布；单次最多 200 条。"
          />
          <Select
            value={faqImportSpaceId || undefined}
            onChange={setFaqImportSpaceId}
            placeholder="选择这批 FAQ 要归属的知识空间"
            options={activeSpaces.map((space) => ({
              value: space.id,
              label: `${space.name} · ${space.code}`,
            }))}
            style={{ width: "100%" }}
          />
          <Upload
            accept=".csv,text/csv"
            showUploadList={false}
            beforeUpload={(file) => {
              if (file.size > 5 * 1024 * 1024) {
                message.error("FAQ CSV 不能超过 5 MB");
                return Upload.LIST_IGNORE;
              }
              void file.text().then((text) => {
                const parsedRows = parseFaqCsv(text).slice(0, 200);
                setFaqImportFileName(file.name);
                setFaqImportRows(parsedRows);
              });
              return Upload.LIST_IGNORE;
            }}
          >
            <Button>选择 FAQ CSV</Button>
          </Upload>
          {faqImportFileName && (
            <Space wrap>
              <Text>当前文件：{faqImportFileName}</Text>
              <Tag>共 {faqImportRows.length} 行</Tag>
              <Tag color="green">
                可导入 {faqImportRows.filter((row) => row.valid).length} 条
              </Tag>
              <Tag color="red">
                需修正 {faqImportRows.filter((row) => !row.valid).length} 条
              </Tag>
            </Space>
          )}
          {faqImportRows.length > 0 && (
            <Table
              rowKey="rowNumber"
              size="small"
              pagination={{ pageSize: 8, showSizeChanger: false }}
              dataSource={faqImportRows}
              columns={[
                { title: "行", dataIndex: "rowNumber", width: 55 },
                { title: "问题", dataIndex: "question" },
                { title: "标准答案", dataIndex: "answer" },
                {
                  title: "检查",
                  dataIndex: "valid",
                  width: 220,
                  render: (valid: boolean, row) =>
                    valid ? (
                      <Tag color="green">可导入</Tag>
                    ) : (
                      <Text type="danger">{row.error}</Text>
                    ),
                },
              ]}
              scroll={{ x: 760 }}
            />
          )}
        </Space>
      </Modal>

      <Modal
        title="新建知识文档"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createDocument.mutate()}
        confirmLoading={createDocument.isPending}
        okButtonProps={{ disabled: !title.trim() || !spaceId }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Input
            placeholder="文档标题"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Select
            value={docType}
            onChange={setDocType}
            options={[
              { value: "SOP", label: "SOP · 操作流程" },
              { value: "FAQ", label: "FAQ · 常见问答" },
              { value: "POLICY", label: "制度 · 政策规则" },
              { value: "PRODUCT", label: "产品 · 产品资料" },
            ]}
          />
          <Select
            value={spaceId || undefined}
            onChange={setSpaceId}
            placeholder="选择知识空间"
            options={activeSpaces.map((space) => ({
              value: space.id,
              label: `${space.name} · ${space.code}`,
            }))}
          />
        </Space>
      </Modal>

      <Modal
        title="编辑知识文档"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => updateDocument.mutate()}
        confirmLoading={updateDocument.isPending}
        okButtonProps={{ disabled: !title.trim() || !spaceId }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Input
            placeholder="文档标题"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Select
            value={docType}
            onChange={setDocType}
            options={[
              { value: "SOP", label: "SOP · 操作流程" },
              { value: "FAQ", label: "FAQ · 常见问答" },
              { value: "POLICY", label: "制度 · 政策规则" },
              { value: "PRODUCT", label: "产品 · 产品资料" },
            ]}
          />
          <Select
            value={spaceId || undefined}
            onChange={setSpaceId}
            placeholder="选择知识空间"
            options={activeSpaces.map((space) => ({
              value: space.id,
              label: `${space.name} · ${space.code}`,
            }))}
          />
        </Space>
      </Modal>

      <Modal
        title="归档知识文档？"
        open={archiveOpen}
        onCancel={() => setArchiveOpen(false)}
        onOk={() => archiveDocument.mutate()}
        okText="归档"
        cancelText="取消"
        confirmLoading={archiveDocument.isPending}
        okButtonProps={{ danger: true }}
      >
        <Paragraph>
          归档后文档会立即退出检索，历史版本、引用与审计记录会保留。
        </Paragraph>
      </Modal>

      <Modal
        title={
          evaluationFromRepair
            ? "建立回归评测案例"
            : "新建知识评测案例"
        }
        open={evaluationOpen}
        onCancel={() => {
          setEvaluationOpen(false);
          setEvaluationFromRepair(false);
        }}
        onOk={() => createEvaluation.mutate()}
        confirmLoading={createEvaluation.isPending}
        okButtonProps={{
          disabled:
            !evaluationName.trim() ||
            !evaluationQuery.trim() ||
            !evaluationSpaceId ||
            (!evaluationNoGrounding && !evaluationExpectedTitles.trim()),
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {evaluationFromRepair && (
            <Alert
              type="info"
              showIcon
              message="这是修复任务的回归测试"
              description="原问题和使用空间已自动带入。请补全期望命中的文档；创建后到质量评测页点击“运行全部评测”。"
            />
          )}
          <Input
            placeholder="案例名称，例如 制度条款召回"
            value={evaluationName}
            onChange={(event) => setEvaluationName(event.target.value)}
          />
          <Select
            value={evaluationSpaceId || undefined}
            onChange={setEvaluationSpaceId}
            placeholder="选择知识空间"
            options={activeSpaces.map((space) => ({
              value: space.id,
              label: `${space.name} · ${space.code}`,
            }))}
          />
          <TextArea
            rows={3}
            placeholder="要验证的业务问题"
            value={evaluationQuery}
            onChange={(event) => setEvaluationQuery(event.target.value)}
          />
          <TextArea
            rows={3}
            placeholder="预期命中的文档标题，一行一个"
            value={evaluationExpectedTitles}
            onChange={(event) => setEvaluationExpectedTitles(event.target.value)}
          />
          <Checkbox
            checked={evaluationNoGrounding}
            onChange={(event) => setEvaluationNoGrounding(event.target.checked)}
          >
            这是无答案问题，预期不应召回知识
          </Checkbox>
          <TextArea
            rows={3}
            placeholder={'检索上下文 JSON，例如 {"product_id":"..."}'}
            value={evaluationScope}
            onChange={(event) => setEvaluationScope(event.target.value)}
          />
        </Space>
      </Modal>

      <Modal
        title="新建知识空间"
        open={spaceOpen}
        onCancel={() => setSpaceOpen(false)}
        onOk={() => createSpace.mutate()}
        confirmLoading={createSpace.isPending}
        okButtonProps={{ disabled: !spaceCode.trim() || !spaceName.trim() }}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Input
            placeholder="空间编码，例如 refund_policy"
            value={spaceCode}
            onChange={(event) => setSpaceCode(event.target.value)}
          />
          <Input
            placeholder="空间名称，例如 客服制度知识"
            value={spaceName}
            onChange={(event) => setSpaceName(event.target.value)}
          />
          <TextArea
            rows={3}
            placeholder="说明该空间负责哪些知识、哪些数字员工可以绑定"
            value={spaceDescription}
            onChange={(event) => setSpaceDescription(event.target.value)}
          />
          <Input
            placeholder="来源渠道（可选），例如官网、客服系统、飞书"
            value={spaceChannel}
            onChange={(event) => setSpaceChannel(event.target.value)}
          />
          <Input
            placeholder="业务主题（可选），例如退款政策、服务流程"
            value={spaceCategory}
            onChange={(event) => setSpaceCategory(event.target.value)}
          />
          <Input
            placeholder="适用工作流（可选），例如客服工单、入职办理"
            value={spaceWorkflow}
            onChange={(event) => setSpaceWorkflow(event.target.value)}
          />
          <Checkbox
            checked={spaceEvaluationRequired}
            onChange={(event) => setSpaceEvaluationRequired(event.target.checked)}
          >
            发布前必须通过知识评测
          </Checkbox>
        </Space>
      </Modal>

      <Modal
        title="一键验证修复"
        open={Boolean(repairVerificationTask)}
        onCancel={() => {
          if (!repairVerificationRunning) setRepairVerificationTask(null);
        }}
        onOk={() => void runRepairVerification()}
        okText="开始自动验证"
        cancelText="取消"
        width={720}
        confirmLoading={repairVerificationRunning}
        okButtonProps={{
          disabled:
            repairExpectedTitles.length === 0 ||
            repairVerificationRunning,
        }}
      >
        {repairVerificationTask && (
          <Space
            direction="vertical"
            size="middle"
            style={{ width: "100%" }}
          >
            <Alert
              type="info"
              showIcon
              message="系统会自动完成剩下的步骤"
              description="自动创建或启用回归案例 → 运行该知识空间的评测 → 根据结果更新修复任务。你只需要确认什么文档才算正确答案。"
            />
            <div>
              <Text strong>原失败问题</Text>
              <Paragraph style={{ marginTop: 6 }}>
                {repairVerificationTask.query}
              </Paragraph>
            </div>
            <div>
              <Text strong>正确的知识文档</Text>
              <Paragraph type="secondary">
                选择修复后应当命中的文档。保存的文档标题会作为回归评测的预期结果。
              </Paragraph>
              <Select
                mode="multiple"
                value={repairExpectedTitles}
                onChange={setRepairExpectedTitles}
                placeholder="选择至少一个正确文档"
                options={(documents.data ?? [])
                  .filter(
                    (item) =>
                      !repairVerificationTask.knowledge_space_id ||
                      item.space_id ===
                        repairVerificationTask.knowledge_space_id,
                  )
                  .map((item) => ({
                    value: item.title,
                    label: item.title,
                  }))}
                style={{ width: "100%" }}
              />
            </div>
          </Space>
        )}
      </Modal>
    </Space>
  );
}

