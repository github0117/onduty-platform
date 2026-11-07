import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createMcpConnector,
  discoverMcpConnector,
  listMcpConnectors,
  updateMcpConnector,
} from "../../api";
import { useAuth } from "../../auth";
import { message } from "../../feedback";
import type { McpConnector } from "../../types";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export function McpConnectorsCard() {
  const queryClient = useQueryClient();
  const { hasCapability } = useAuth();
  const canWrite = hasCapability("mcp.connectors.write");
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
      title="MCP · 工具型业务系统连接"
      extra={
        canWrite ? (
          <Button type="primary" onClick={() => openEditor()}>
            新建 MCP 连接器
          </Button>
        ) : undefined
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
            render: (_, connector) =>
              canWrite ? (
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
              ) : (
                <Text type="secondary">只读</Text>
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
