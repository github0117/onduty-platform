import {
  Alert,
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  checkExternalConnectorHealth,
  createExternalConnector,
  listBusinessServiceEntries,
  listDigitalEmployees,
  listExternalConnectorBindings,
  listExternalConnectorMessages,
  listExternalConnectors,
  queryExternalConnector,
  replaceExternalConnectorBindings,
  retryExternalInboundMessage,
  retryExternalOutboundMessage,
  updateExternalConnector,
} from "./api";
import { useAuth } from "./auth";
import { message } from "./feedback";
import type {
  BusinessServiceEntry,
  DigitalEmployee,
  ExternalConnector,
  ExternalConnectorBinding,
  ExternalConnectorInboundMessage,
  ExternalConnectorOutboundMessage,
  ExternalConnectorQueryResult,
} from "./types";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

type ConnectorForm = {
  connectorKey: string;
  name: string;
  connectorType: "email" | "http_json";
  direction: string;
  imapHost: string;
  imapPort: number;
  smtpHost: string;
  smtpPort: number;
  fromAddress: string;
  username: string;
  folder: string;
  baseUrl: string;
  httpPath: string;
  healthPath: string;
  secretRef: string;
  autoReplyEnabled: boolean;
  status: string;
};

const emptyForm = (): ConnectorForm => ({
  connectorKey: "",
  name: "",
  connectorType: "email",
  direction: "BIDIRECTIONAL",
  imapHost: "",
  imapPort: 993,
  smtpHost: "",
  smtpPort: 465,
  fromAddress: "",
  username: "",
  folder: "INBOX",
  baseUrl: "",
  httpPath: "",
  healthPath: "/health",
  secretRef: "",
  autoReplyEnabled: true,
  status: "ACTIVE",
});

function textValue(
  config: Record<string, unknown>,
  key: string,
  fallback = "",
): string {
  const value = config[key];
  return typeof value === "string" ? value : fallback;
}

function numberValue(
  config: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const value = config[key];
  return typeof value === "number" ? value : fallback;
}

function formFromConnector(connector: ExternalConnector): ConnectorForm {
  const config = connector.config ?? {};
  return {
    connectorKey: connector.connector_key,
    name: connector.name,
    connectorType:
      connector.connector_type === "http_json" ? "http_json" : "email",
    direction: connector.direction,
    imapHost: textValue(config, "imap_host"),
    imapPort: numberValue(config, "imap_port", 993),
    smtpHost: textValue(config, "smtp_host"),
    smtpPort: numberValue(config, "smtp_port", 465),
    fromAddress: textValue(config, "from_address"),
    username: textValue(config, "username"),
    folder: textValue(config, "folder", "INBOX"),
    baseUrl: textValue(config, "base_url"),
    httpPath: textValue(config, "path"),
    healthPath: textValue(config, "health_path", "/health"),
    secretRef: connector.secret_ref ?? "",
    autoReplyEnabled: connector.auto_reply_enabled,
    status: connector.status,
  };
}

function buildConfig(form: ConnectorForm): Record<string, unknown> {
  if (form.connectorType === "http_json") {
    return {
      base_url: form.baseUrl.trim(),
      ...(form.httpPath.trim() ? { path: form.httpPath.trim() } : {}),
      ...(form.healthPath.trim()
        ? { health_path: form.healthPath.trim() }
        : {}),
    };
  }
  return {
    imap_host: form.imapHost.trim(),
    imap_port: form.imapPort,
    smtp_host: form.smtpHost.trim() || undefined,
    smtp_port: form.smtpPort,
    from_address: form.fromAddress.trim(),
    username: form.username.trim() || undefined,
    folder: form.folder.trim() || "INBOX",
  };
}

function healthTag(connector: ExternalConnector) {
  if (!connector.last_health_status) return <Tag>未检测</Tag>;
  const healthy = connector.last_health_status === "HEALTHY";
  return (
    <Tag color={healthy ? "green" : "red"}>
      {healthy ? "正常" : "异常"}
    </Tag>
  );
}

function statusTag(status: string) {
  return (
    <Tag color={status === "ACTIVE" ? "green" : "default"}>
      {status === "ACTIVE" ? "启用" : "停用"}
    </Tag>
  );
}

function inboundStatusTag(status: string) {
  const colors: Record<string, string> = {
    RECEIVED: "blue",
    PROCESSING: "processing",
    PROCESSED: "green",
    FAILED: "red",
  };
  return <Tag color={colors[status] ?? "default"}>{status}</Tag>;
}

function outboundStatusTag(status: string) {
  const colors: Record<string, string> = {
    QUEUED: "blue",
    SENT: "green",
    FAILED: "red",
  };
  return <Tag color={colors[status] ?? "default"}>{status}</Tag>;
}

export default function ExternalConnectorsCard() {
  const { hasCapability } = useAuth();
  const canWrite = hasCapability("mcp.connectors.write");
  const canSeeEmployees = hasCapability("employees.view");
  const queryClient = useQueryClient();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<ExternalConnector | null>(null);
  const [form, setForm] = useState<ConnectorForm>(emptyForm());

  const [bindingConnector, setBindingConnector] =
    useState<ExternalConnector | null>(null);
  const [bindingDraft, setBindingDraft] = useState<
    Array<{
      serviceEntryId: string;
      employeeId: string | null;
      allowedOperations: string[];
      writeApproved: boolean;
    }>
  >([]);
  const [newEntryId, setNewEntryId] = useState<string | null>(null);
  const [newEmployeeId, setNewEmployeeId] = useState<string | null>(null);

  const [messageConnector, setMessageConnector] =
    useState<ExternalConnector | null>(null);

  const [queryConnector, setQueryConnector] =
    useState<ExternalConnector | null>(null);
  const [queryText, setQueryText] = useState('{"order_id": "O-1001"}');
  const [queryResult, setQueryResult] =
    useState<ExternalConnectorQueryResult | null>(null);

  const connectors = useQuery({
    queryKey: ["external-connectors"],
    queryFn: listExternalConnectors,
    refetchInterval: 15000,
  });
  const entries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
    enabled: bindingConnector !== null,
  });
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: bindingConnector !== null && canSeeEmployees,
  });
  const bindings = useQuery({
    queryKey: ["external-connector-bindings", bindingConnector?.id],
    queryFn: () => listExternalConnectorBindings(bindingConnector!.id),
    enabled: bindingConnector !== null,
  });
  useEffect(() => {
    if (!bindings.data) return;
    setBindingDraft(
      bindings.data.map((binding) => ({
        serviceEntryId: binding.service_entry_id ?? "",
        employeeId: binding.employee_id,
        allowedOperations: binding.allowed_operations,
        writeApproved: binding.write_approved,
      })),
    );
  }, [bindings.data]);
  const messages = useQuery({
    queryKey: ["external-connector-messages", messageConnector?.id],
    queryFn: () => listExternalConnectorMessages(messageConnector!.id),
    enabled: messageConnector !== null,
    refetchInterval: 10000,
  });

  const save = useMutation({
    mutationFn: () => {
      const config = buildConfig(form);
      const secretRef = form.secretRef.trim();
      if (editing) {
        return updateExternalConnector(editing.id, {
          name: form.name.trim(),
          direction: form.direction,
          config,
          ...(secretRef ? { secretRef } : {}),
          autoReplyEnabled: form.autoReplyEnabled,
          status: form.status,
          expectedVersion: editing.version,
        });
      }
      return createExternalConnector({
        connectorKey: form.connectorKey.trim(),
        name: form.name.trim(),
        connectorType: form.connectorType,
        direction: form.direction,
        config,
        secretRef: secretRef || null,
        autoReplyEnabled: form.autoReplyEnabled,
        status: form.status,
      });
    },
    onSuccess: async () => {
      message.success(editing ? "外部连接已更新" : "外部连接已创建");
      setEditorOpen(false);
      await queryClient.invalidateQueries({
        queryKey: ["external-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const toggle = useMutation({
    mutationFn: (connector: ExternalConnector) =>
      updateExternalConnector(connector.id, {
        status: connector.status === "ACTIVE" ? "DISABLED" : "ACTIVE",
        expectedVersion: connector.version,
      }),
    onSuccess: async (connector) => {
      message.success(
        connector.status === "ACTIVE" ? "外部连接已启用" : "外部连接已停用",
      );
      await queryClient.invalidateQueries({
        queryKey: ["external-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const health = useMutation({
    mutationFn: checkExternalConnectorHealth,
    onSuccess: async (result) => {
      if (result.healthy) {
        message.success(`连接正常：${result.detail}`);
      } else {
        message.error(`连接异常：${result.detail}`);
      }
      await queryClient.invalidateQueries({
        queryKey: ["external-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const saveBindings = useMutation({
    mutationFn: () =>
      replaceExternalConnectorBindings(bindingConnector!.id, bindingDraft),
    onSuccess: async () => {
      message.success("业务入口绑定已保存");
      await queryClient.invalidateQueries({
        queryKey: ["external-connector-bindings", bindingConnector?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const retryInbound = useMutation({
    mutationFn: (row: ExternalConnectorInboundMessage) =>
      retryExternalInboundMessage(messageConnector!.id, row.id),
    onSuccess: async (row) => {
      if (row.status === "PROCESSED") {
        message.success("入站消息已重新处理");
      } else {
        message.error(`重新处理失败：${row.error_message ?? row.status}`);
      }
      await queryClient.invalidateQueries({
        queryKey: ["external-connector-messages", messageConnector?.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["external-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const retryOutbound = useMutation({
    mutationFn: (row: ExternalConnectorOutboundMessage) =>
      retryExternalOutboundMessage(messageConnector!.id, row.id),
    onSuccess: async (row) => {
      if (row.status === "SENT") {
        message.success("出站消息已发送");
      } else {
        message.error(`发送失败：${row.last_error ?? row.status}`);
      }
      await queryClient.invalidateQueries({
        queryKey: ["external-connector-messages", messageConnector?.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["external-connectors"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const runQuery = useMutation({
    mutationFn: () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(queryText);
      } catch {
        throw new Error("查询参数必须是 JSON 对象，例如 {\"order_id\": \"O-1001\"}");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("查询参数必须是 JSON 对象");
      }
      return queryExternalConnector(
        queryConnector!.id,
        Object.fromEntries(
          Object.entries(parsed as Record<string, unknown>).map(
            ([key, value]) => [key, String(value)],
          ),
        ),
      );
    },
    onSuccess: (result) => {
      setQueryResult(result);
      message.success(`查询成功（HTTP ${result.status_code}）`);
    },
    onError: (error: Error) => message.error(error.message),
  });

  const openEditor = (connector?: ExternalConnector) => {
    setEditing(connector ?? null);
    setForm(connector ? formFromConnector(connector) : emptyForm());
    setEditorOpen(true);
  };

  const openBindings = (connector: ExternalConnector) => {
    setBindingDraft([]);
    setNewEntryId(null);
    setNewEmployeeId(null);
    setBindingConnector(connector);
  };

  const openMessages = (connector: ExternalConnector) => {
    setMessageConnector(connector);
  };

  const openQuery = (connector: ExternalConnector) => {
    setQueryResult(null);
    setQueryText('{"order_id": "O-1001"}');
    setQueryConnector(connector);
  };

  const entryName = (entryId: string | null) =>
    entries.data?.find((entry) => entry.id === entryId)?.name ?? entryId ?? "";
  const employeeName = (employeeId: string | null) =>
    employees.data?.find((employee) => employee.id === employeeId)?.name ??
    employeeId ??
    "";
  const boundEntryIds = new Set(
    bindingDraft.map((binding) => binding.serviceEntryId),
  );

  const columns: ColumnsType<ExternalConnector> = [
    {
      title: "连接",
      dataIndex: "name",
      render: (value: string, connector) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{connector.connector_key}</Text>
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "connector_type",
      width: 130,
      render: (value: string, connector) => (
        <Space direction="vertical" size={0}>
          <Tag color={value === "email" ? "blue" : "purple"}>
            {value === "email" ? "邮件" : "只读 HTTP"}
          </Tag>
          <Text type="secondary">{connector.direction}</Text>
        </Space>
      ),
    },
    {
      title: "自动回复",
      dataIndex: "auto_reply_enabled",
      width: 90,
      render: (value: boolean, connector) =>
        connector.connector_type === "email" ? (
          <Tag color={value ? "green" : "default"}>
            {value ? "开启" : "关闭"}
          </Tag>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: "密钥",
      dataIndex: "secret_configured",
      width: 100,
      render: (value: boolean, connector) =>
        connector.secret_ref ? (
          <Tag color={value ? "green" : "orange"}>
            {value ? "已配置" : "变量缺失"}
          </Tag>
        ) : (
          <Text type="secondary">未使用</Text>
        ),
    },
    {
      title: "健康",
      dataIndex: "last_health_status",
      width: 150,
      render: (_, connector) => (
        <Space direction="vertical" size={0}>
          {healthTag(connector)}
          <Text type="secondary" ellipsis style={{ maxWidth: 130 }}>
            {connector.last_health_error ??
              (connector.last_health_at
                ? new Date(connector.last_health_at).toLocaleString()
                : "尚未检测")}
          </Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (value: string) => statusTag(value),
    },
    {
      title: "操作",
      width: 260,
      render: (_, connector) => (
        <Space wrap>
          {connector.connector_type === "http_json" && (
            <Button type="link" onClick={() => openQuery(connector)}>
              查询
            </Button>
          )}
          <Button
            type="link"
            onClick={() => openMessages(connector)}
          >
            消息
          </Button>
          {canWrite && (
            <>
              <Button
                type="link"
                loading={
                  health.isPending && health.variables === connector.id
                }
                onClick={() => health.mutate(connector.id)}
              >
                检测
              </Button>
              <Button type="link" onClick={() => openBindings(connector)}>
                绑定入口
              </Button>
              <Button type="link" onClick={() => openEditor(connector)}>
                编辑
              </Button>
              <Button
                type="link"
                loading={
                  toggle.isPending && toggle.variables?.id === connector.id
                }
                onClick={() => toggle.mutate(connector)}
              >
                {connector.status === "ACTIVE" ? "停用" : "启用"}
              </Button>
            </>
          )}
          {!canWrite && <Text type="secondary">只读</Text>}
        </Space>
      ),
    },
  ];

  const inboundColumns: ColumnsType<ExternalConnectorInboundMessage> = [
    {
      title: "主题 / 发件人",
      dataIndex: "subject",
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value || "（无主题）"}</Text>
          <Text type="secondary">{row.external_user_id}</Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          {inboundStatusTag(value)}
          <Text type="secondary">尝试 {row.attempt_count}</Text>
        </Space>
      ),
    },
    {
      title: "关联对象",
      width: 200,
      render: (_, row) => (
        <Space direction="vertical" size={0}>
          <Text type="secondary">
            对话 {row.conversation_id?.slice(0, 8) ?? "—"}
          </Text>
          <Text type="secondary">
            工单 {row.ticket_id?.slice(0, 8) ?? "—"}
          </Text>
        </Space>
      ),
    },
    {
      title: "错误",
      dataIndex: "error_message",
      render: (value: string | null) =>
        value ? <Text type="danger">{value}</Text> : "—",
    },
    {
      title: "接收时间",
      dataIndex: "created_at",
      width: 170,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "操作",
      width: 100,
      render: (_, row) =>
        canWrite && row.status === "FAILED" ? (
          <Button
            type="link"
            loading={retryInbound.isPending && retryInbound.variables?.id === row.id}
            onClick={() => retryInbound.mutate(row)}
          >
            重试
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  const outboundColumns: ColumnsType<ExternalConnectorOutboundMessage> = [
    {
      title: "收件人 / 主题",
      dataIndex: "recipient",
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{row.subject}</Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string, row) => (
        <Space direction="vertical" size={0}>
          {outboundStatusTag(value)}
          <Text type="secondary">尝试 {row.attempt_count}</Text>
        </Space>
      ),
    },
    {
      title: "错误",
      dataIndex: "last_error",
      render: (value: string | null) =>
        value ? <Text type="danger">{value}</Text> : "—",
    },
    {
      title: "发送时间",
      dataIndex: "sent_at",
      width: 170,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString() : "—",
    },
    {
      title: "操作",
      width: 100,
      render: (_, row) =>
        canWrite && row.status === "FAILED" ? (
          <Button
            type="link"
            loading={
              retryOutbound.isPending &&
              retryOutbound.variables?.id === row.id
            }
            onClick={() => retryOutbound.mutate(row)}
          >
            重试
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <Card
      className="section-card"
      title="外部连接 · 邮件与只读业务系统"
      extra={
        canWrite ? (
          <Button type="primary" onClick={() => openEditor()}>
            新建外部连接
          </Button>
        ) : undefined
      }
    >
      <Paragraph type="secondary">
        统一管理邮件渠道（IMAP 收信 / SMTP 回信）和只读 HTTP JSON 业务系统。
        密钥只保存环境变量名，系统不会返回密钥值；写入操作仍走既有审批链路。
      </Paragraph>
      {connectors.isError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="外部连接加载失败"
          description={(connectors.error as Error).message}
        />
      )}
      <Table
        rowKey="id"
        size="small"
        loading={connectors.isLoading}
        dataSource={connectors.data}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={columns}
        locale={{ emptyText: "还没有外部连接。邮件渠道接入后会自动接收并生成客服对话。" }}
      />

      <Modal
        title={editing ? `编辑外部连接 · ${editing.connector_key}` : "新建外部连接"}
        open={editorOpen}
        width={760}
        onCancel={() => setEditorOpen(false)}
        confirmLoading={save.isPending}
        okText="保存"
        okButtonProps={{
          disabled:
            !form.name.trim() ||
            (!editing && !form.connectorKey.trim()) ||
            (form.connectorType === "email" &&
              (!form.imapHost.trim() || !form.fromAddress.trim())) ||
            (form.connectorType === "http_json" && !form.baseUrl.trim()),
        }}
        onOk={() => save.mutate()}
      >
        <Form layout="vertical">
          <Space size="middle" align="start" className="form-row">
            <Form.Item label="编码" required>
              <Input
                value={form.connectorKey}
                disabled={Boolean(editing)}
                onChange={(event) =>
                  setForm({ ...form, connectorKey: event.target.value })
                }
                placeholder="support-mail"
              />
            </Form.Item>
            <Form.Item label="名称" required>
              <Input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="客服支持邮箱"
              />
            </Form.Item>
            <Form.Item label="类型">
              <Select
                value={form.connectorType}
                disabled={Boolean(editing)}
                onChange={(value: "email" | "http_json") =>
                  setForm({
                    ...form,
                    connectorType: value,
                    direction: value === "http_json" ? "INBOUND" : form.direction,
                  })
                }
                options={[
                  { value: "email", label: "邮件（IMAP + SMTP）" },
                  { value: "http_json", label: "只读 HTTP JSON" },
                ]}
                style={{ width: 220 }}
              />
            </Form.Item>
            <Form.Item label="状态">
              <Select
                value={form.status}
                onChange={(value: string) => setForm({ ...form, status: value })}
                options={[
                  { value: "ACTIVE", label: "启用" },
                  { value: "DISABLED", label: "停用" },
                ]}
                style={{ width: 110 }}
              />
            </Form.Item>
          </Space>
          {form.connectorType === "email" ? (
            <>
              <Space size="middle" align="start" className="form-row" wrap>
                <Form.Item label="IMAP 主机" required>
                  <Input
                    value={form.imapHost}
                    onChange={(event) =>
                      setForm({ ...form, imapHost: event.target.value })
                    }
                    placeholder="imap.example.com"
                  />
                </Form.Item>
                <Form.Item label="IMAP 端口">
                  <InputNumber
                    min={1}
                    max={65535}
                    value={form.imapPort}
                    onChange={(value) =>
                      setForm({ ...form, imapPort: value ?? 993 })
                    }
                  />
                </Form.Item>
                <Form.Item label="SMTP 主机">
                  <Input
                    value={form.smtpHost}
                    onChange={(event) =>
                      setForm({ ...form, smtpHost: event.target.value })
                    }
                    placeholder="留空则使用 IMAP 主机"
                  />
                </Form.Item>
                <Form.Item label="SMTP 端口">
                  <InputNumber
                    min={1}
                    max={65535}
                    value={form.smtpPort}
                    onChange={(value) =>
                      setForm({ ...form, smtpPort: value ?? 465 })
                    }
                  />
                </Form.Item>
              </Space>
              <Space size="middle" align="start" className="form-row" wrap>
                <Form.Item label="发件地址" required>
                  <Input
                    value={form.fromAddress}
                    onChange={(event) =>
                      setForm({ ...form, fromAddress: event.target.value })
                    }
                    placeholder="support@example.com"
                  />
                </Form.Item>
                <Form.Item label="登录账号">
                  <Input
                    value={form.username}
                    onChange={(event) =>
                      setForm({ ...form, username: event.target.value })
                    }
                    placeholder="默认与发件地址相同"
                  />
                </Form.Item>
                <Form.Item label="收件文件夹">
                  <Input
                    value={form.folder}
                    onChange={(event) =>
                      setForm({ ...form, folder: event.target.value })
                    }
                    placeholder="INBOX"
                  />
                </Form.Item>
                <Form.Item label="方向">
                  <Select
                    value={form.direction}
                    onChange={(value: string) =>
                      setForm({ ...form, direction: value })
                    }
                    options={[
                      { value: "BIDIRECTIONAL", label: "收信 + 回信" },
                      { value: "INBOUND", label: "仅收信" },
                      { value: "OUTBOUND", label: "仅回信" },
                    ]}
                    style={{ width: 150 }}
                  />
                </Form.Item>
              </Space>
              <Form.Item label="自动回复">
                <Switch
                  checked={form.autoReplyEnabled}
                  onChange={(checked) =>
                    setForm({ ...form, autoReplyEnabled: checked })
                  }
                />
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  只有数字员工完成回答且工单完成时才会自动回信
                </Text>
              </Form.Item>
            </>
          ) : (
            <Space size="middle" align="start" className="form-row" wrap>
              <Form.Item label="Base URL" required>
                <Input
                  value={form.baseUrl}
                  onChange={(event) =>
                    setForm({ ...form, baseUrl: event.target.value })
                  }
                  placeholder="https://orders.example.com"
                  style={{ width: 320 }}
                />
              </Form.Item>
              <Form.Item label="查询路径">
                <Input
                  value={form.httpPath}
                  onChange={(event) =>
                    setForm({ ...form, httpPath: event.target.value })
                  }
                  placeholder="/api/orders"
                  style={{ width: 260 }}
                />
              </Form.Item>
              <Form.Item label="健康检查路径">
                <Input
                  value={form.healthPath}
                  onChange={(event) =>
                    setForm({ ...form, healthPath: event.target.value })
                  }
                  placeholder="/health"
                  style={{ width: 220 }}
                />
              </Form.Item>
            </Space>
          )}
          <Form.Item
            label="密钥环境变量名"
            extra={
              editing
                ? "留空表示保留当前密钥；密钥值只从运行环境读取，不写入数据库。"
                : "填写环境变量名，例如 SUPPORT_MAIL_PASSWORD；运行环境未配置时健康检查会明确报错。"
            }
          >
            <Input
              value={form.secretRef}
              onChange={(event) =>
                setForm({ ...form, secretRef: event.target.value })
              }
              placeholder="SUPPORT_MAIL_PASSWORD"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={`业务入口绑定 · ${bindingConnector?.name ?? ""}`}
        open={bindingConnector !== null}
        width={720}
        onClose={() => setBindingConnector(null)}
        extra={
          <Button
            type="primary"
            loading={saveBindings.isPending}
            disabled={!bindingDraft.length && !bindings.data?.length}
            onClick={() => saveBindings.mutate()}
          >
            保存绑定
          </Button>
        }
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="绑定后才允许接收该业务入口的来信"
          description="未绑定业务入口的来信会被记录为失败并明确提示；不会静默丢弃。"
        />
        <Space size="middle" align="start" wrap style={{ marginBottom: 16 }}>
          <Select
            value={newEntryId}
            placeholder="选择业务入口"
            style={{ width: 240 }}
            loading={entries.isLoading}
            onChange={setNewEntryId}
            options={(entries.data ?? [])
              .filter((entry: BusinessServiceEntry) => !boundEntryIds.has(entry.id))
              .map((entry) => ({ value: entry.id, label: `${entry.name}（${entry.code}）` }))}
          />
          {canSeeEmployees && (
            <Select
              value={newEmployeeId}
              placeholder="指定数字员工（可选）"
              style={{ width: 240 }}
              allowClear
              loading={employees.isLoading}
              onChange={(value: string | null) => setNewEmployeeId(value)}
              options={(employees.data ?? [])
                .filter((employee: DigitalEmployee) => employee.status === "ACTIVE")
                .map((employee) => ({
                  value: employee.id,
                  label: `${employee.name}（${employee.employee_key}）`,
                }))}
            />
          )}
          <Button
            disabled={!newEntryId}
            onClick={() => {
              if (!newEntryId) return;
              setBindingDraft([
                ...bindingDraft,
                {
                  serviceEntryId: newEntryId,
                  employeeId: newEmployeeId,
                  allowedOperations: [],
                  writeApproved: false,
                },
              ]);
              setNewEntryId(null);
              setNewEmployeeId(null);
            }}
          >
            添加
          </Button>
        </Space>
        <Table
          rowKey={(row) => row.serviceEntryId}
          size="small"
          loading={bindings.isLoading}
          dataSource={bindingDraft}
          pagination={false}
          columns={[
            {
              title: "业务入口",
              dataIndex: "serviceEntryId",
              render: (value: string) => entryName(value),
            },
            {
              title: "指定员工",
              dataIndex: "employeeId",
              render: (value: string | null) =>
                value ? employeeName(value) : "使用入口默认员工",
            },
            {
              title: "写权限",
              dataIndex: "writeApproved",
              width: 100,
              render: (value: boolean) => (
                <Tag color={value ? "orange" : "default"}>
                  {value ? "已批准" : "只读"}
                </Tag>
              ),
            },
            {
              title: "操作",
              width: 80,
              render: (_, row) => (
                <Button
                  type="link"
                  danger
                  onClick={() =>
                    setBindingDraft(
                      bindingDraft.filter(
                        (binding) =>
                          binding.serviceEntryId !== row.serviceEntryId,
                      ),
                    )
                  }
                >
                  移除
                </Button>
              ),
            },
          ]}
          locale={{ emptyText: "尚未绑定业务入口" }}
        />
      </Drawer>

      <Drawer
        title={`消息记录 · ${messageConnector?.name ?? ""}`}
        open={messageConnector !== null}
        width={900}
        onClose={() => setMessageConnector(null)}
      >
        <Paragraph type="secondary">
          每 10 秒自动刷新。失败消息会保留错误原因，可人工重试；重复 Message-ID 只会入库一次。
        </Paragraph>
        <Text strong>入站邮件</Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          loading={messages.isLoading}
          dataSource={messages.data?.inbound ?? []}
          pagination={false}
          columns={inboundColumns}
          locale={{ emptyText: "还没有收到外部消息" }}
        />
        <Text strong style={{ display: "block", marginTop: 24 }}>
          出站回复
        </Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          loading={messages.isLoading}
          dataSource={messages.data?.outbound ?? []}
          pagination={false}
          columns={outboundColumns}
          locale={{ emptyText: "还没有出站回复" }}
        />
      </Drawer>

      <Drawer
        title={`只读查询 · ${queryConnector?.name ?? ""}`}
        open={queryConnector !== null}
        width={640}
        onClose={() => setQueryConnector(null)}
      >
        <Paragraph type="secondary">
          只读 GET 查询，不会写入外部系统。参数以 JSON 对象提交，值会转换为字符串。
        </Paragraph>
        <TextArea
          rows={4}
          value={queryText}
          onChange={(event) => setQueryText(event.target.value)}
        />
        <Button
          type="primary"
          style={{ marginTop: 12 }}
          loading={runQuery.isPending}
          onClick={() => runQuery.mutate()}
        >
          执行查询
        </Button>
        {queryResult && (
          <pre
            style={{
              marginTop: 16,
              padding: 12,
              background: "#f5f5f5",
              borderRadius: 8,
              overflow: "auto",
              maxHeight: 360,
            }}
          >
            {JSON.stringify(queryResult, null, 2)}
          </pre>
        )}
      </Drawer>
    </Card>
  );
}
