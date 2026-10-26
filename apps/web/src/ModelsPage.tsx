import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Menu,
  Row,
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
  getRuntimeConfig,
  listDigitalEmployees,
  updateDigitalEmployee,
} from "./api";
import type { DigitalEmployee } from "./types";
import { message } from "./feedback";
import { employeeStatusLabels } from "./statusLabels";

const { Paragraph, Text, Title } = Typography;

interface ModelConfigState {
  classificationProvider: string;
  classificationModel: string;
  classificationFallback: string;
  classificationThreshold: number | null;
  generationProvider: string;
  generationModel: string;
  generationFallback: string;
  verifierProvider: string;
  verifierModel: string;
  verifierFallback: string;
  verifierEnforce: string;
  rerankProvider: string;
  rerankModel: string;
  rerankFallback: string;
  vectorWeight: number | null;
  lexicalWeight: number | null;
  rerankEnabled: boolean;
}

const emptyConfig: ModelConfigState = {
  classificationProvider: "inherit",
  classificationModel: "",
  classificationFallback: "inherit",
  classificationThreshold: null,
  generationProvider: "inherit",
  generationModel: "",
  generationFallback: "inherit",
  verifierProvider: "inherit",
  verifierModel: "",
  verifierFallback: "inherit",
  verifierEnforce: "inherit",
  rerankProvider: "inherit",
  rerankModel: "",
  rerankFallback: "inherit",
  vectorWeight: null,
  lexicalWeight: null,
  rerankEnabled: true,
};

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function optionalBoolean(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "inherit";
}

function booleanOrNull(value: string): boolean | null {
  return value === "inherit" ? null : value === "true";
}

function providerLabel(value: string): string {
  const labels: Record<string, string> = {
    local: "本地规则",
    openai_compatible: "OpenAI 兼容",
    external: "外部服务",
    none: "关闭",
    inherit: "继承全局",
  };
  return labels[value] ?? value;
}

function knowledgeSortingLabel(value: string): string {
  const labels: Record<string, string> = {
    inherit: "继承全局",
    local: "本地混合排序",
    external: "外部排序模型",
  };
  return labels[value] ?? value;
}

function verificationLabel(value: string): string {
  const labels: Record<string, string> = {
    inherit: "继承全局",
    none: "已关闭",
    local: "本地规则",
    external: "外部模型",
  };
  return labels[value] ?? value;
}

function integrationLabel(value: string): string {
  const labels: Record<string, string> = {
    local: "本地演示",
    http_json: "外部 HTTP 接口",
    s3: "对象存储",
    celery: "后台异步任务",
  };
  return labels[value] ?? value;
}

function readiness(configured: boolean): React.ReactNode {
  return (
    <Tag color={configured ? "green" : "default"}>
      {configured ? "已配置" : "未配置或使用本地"}
    </Tag>
  );
}

export type ModelsSection = "global" | "employees" | "integrations";

const modelSections = [
  { key: "global", label: "全局模型", path: "/models" },
  { key: "employees", label: "员工模型路由", path: "/models/employees" },
  { key: "integrations", label: "外部集成", path: "/models/integrations" },
] as const;

export default function ModelsPage({
  section,
  onNavigate,
}: {
  section: ModelsSection;
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
  });
  const runtime = useQuery({
    queryKey: ["system-runtime"],
    queryFn: getRuntimeConfig,
  });
  const [selectedId, setSelectedId] = useState<string>();
  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<ModelConfigState>(emptyConfig);
  const selected = employees.data?.find((employee) => employee.id === selectedId);

  const selectEmployee = (employeeId: string) => {
    setSelectedId(employeeId);
    setConfigOpen(true);
  };

  useEffect(() => {
    if (!selectedId && employees.data?.length) {
      setSelectedId(employees.data[0].id);
    }
  }, [employees.data, selectedId]);

  useEffect(() => {
    if (!selected) {
      setConfig(emptyConfig);
      return;
    }
    const profile = objectValue(selected.model_profile);
    const classification = objectValue(profile.classification);
    const generation = objectValue(profile.generation);
    const verifier = objectValue(profile.claim_verifier);
    const rerank = objectValue(profile.rerank);
    setConfig({
      classificationProvider:
        typeof classification.provider === "string"
          ? classification.provider
          : "inherit",
      classificationModel:
        typeof classification.model_name === "string"
          ? classification.model_name
          : "",
      classificationFallback: optionalBoolean(classification.fallback_to_local),
      classificationThreshold: optionalNumber(classification.confidence_threshold),
      generationProvider:
        typeof generation.provider === "string" ? generation.provider : "inherit",
      generationModel:
        typeof generation.model_name === "string" ? generation.model_name : "",
      generationFallback: optionalBoolean(generation.fallback_to_local),
      verifierProvider:
        typeof verifier.provider === "string" ? verifier.provider : "inherit",
      verifierModel:
        typeof verifier.model_name === "string" ? verifier.model_name : "",
      verifierFallback: optionalBoolean(verifier.fallback_to_local),
      verifierEnforce: optionalBoolean(verifier.enforce),
      rerankProvider:
        typeof rerank.provider === "string" ? rerank.provider : "inherit",
      rerankModel:
        typeof rerank.model_name === "string" ? rerank.model_name : "",
      rerankFallback: optionalBoolean(rerank.fallback_to_local),
      vectorWeight: optionalNumber(rerank.vector_weight),
      lexicalWeight: optionalNumber(rerank.lexical_weight),
      rerankEnabled: typeof rerank.enabled === "boolean" ? rerank.enabled : true,
    });
  }, [selected]);

  const save = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error("请选择数字员工");
      const profile = { ...objectValue(selected.model_profile) };
      profile.classification = {
        ...objectValue(profile.classification),
        provider:
          config.classificationProvider === "inherit"
            ? null
            : config.classificationProvider,
        model_name: config.classificationModel.trim() || null,
        fallback_to_local: booleanOrNull(config.classificationFallback),
        confidence_threshold: config.classificationThreshold,
      };
      profile.generation = {
        ...objectValue(profile.generation),
        provider:
          config.generationProvider === "inherit"
            ? null
            : config.generationProvider,
        model_name: config.generationModel.trim() || null,
        fallback_to_local: booleanOrNull(config.generationFallback),
      };
      profile.claim_verifier = {
        ...objectValue(profile.claim_verifier),
        provider: config.verifierProvider,
        model_name: config.verifierModel.trim() || null,
        fallback_to_local: booleanOrNull(config.verifierFallback),
        enforce: booleanOrNull(config.verifierEnforce),
      };
      profile.rerank = {
        ...objectValue(profile.rerank),
        provider: config.rerankProvider,
        model_name: config.rerankModel.trim() || null,
        fallback_to_local: booleanOrNull(config.rerankFallback),
        vector_weight: config.vectorWeight,
        lexical_weight: config.lexicalWeight,
        enabled: config.rerankEnabled,
      };
      return updateDigitalEmployee(selected.id, { model_profile: profile });
    },
    onSuccess: async () => {
      message.success("模型配置已保存，后续新任务生效");
      await queryClient.invalidateQueries({ queryKey: ["digital-employees"] });
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
      title: "分类模型",
      render: (_, employee) => {
        const classification = objectValue(
          objectValue(employee.model_profile).classification,
        );
        return providerLabel(
          typeof classification.provider === "string"
            ? classification.provider
            : "inherit",
        );
      },
    },
    {
      title: "生成模型",
      render: (_, employee) => {
        const generation = objectValue(
          objectValue(employee.model_profile).generation,
        );
        return providerLabel(
          typeof generation.provider === "string"
            ? generation.provider
            : "inherit",
        );
      },
    },
    {
      title: "知识排序",
      render: (_, employee) => {
        const rerank = objectValue(objectValue(employee.model_profile).rerank);
        return providerLabel(
          typeof rerank.provider === "string" ? rerank.provider : "inherit",
        );
      },
    },
    {
      title: "操作",
      width: 110,
      render: (_, employee) => (
        <Button type="link" onClick={() => selectEmployee(employee.id)}>
          配置模型
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>模型与集成</Title>
          <Paragraph type="secondary">
            查看全局运行环境，并为每个数字员工设置独立的模型路由。
          </Paragraph>
        </div>
        <Tag color="gold">密钥不会在页面展示</Tag>
      </div>

      <Menu
        className="knowledge-subnav"
        mode="horizontal"
        selectedKeys={[
          modelSections.find((item) => item.key === section)?.path ?? "/models",
        ]}
        onClick={({ key }) => onNavigate(key)}
        items={modelSections.map((item) => ({
          key: item.path,
          label: item.label,
        }))}
      />

      {runtime.isError && (
        <Alert
          type="warning"
          showIcon
          message="全局运行配置暂不可用"
          description={(runtime.error as Error).message}
        />
      )}

      <Row gutter={[16, 16]}>
        {section === "global" && <Col xs={12} xl={6}>
          <Card className="metric-card" title="主模型">
            <Text strong>{providerLabel(runtime.data?.model_provider ?? "-")}</Text>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              {runtime.data?.model_name || "使用本地规则"}
            </Paragraph>
            <Paragraph type="secondary">
              负责理解问题、判断意图并生成最终回答。
            </Paragraph>
            {readiness(runtime.data?.model_base_url_configured ?? false)}
            <Text type="secondary">
              模型服务：
              {runtime.data?.model_base_url_configured
                ? "已配置"
                : "未配置"}
            </Text>
            <Text type="secondary">
              模型密钥：
              {runtime.data?.model_api_key_configured
                ? "已配置"
                : "未配置"}
            </Text>
          </Card>
        </Col>}
        {section === "global" && <Col xs={12} xl={6}>
          <Card className="metric-card" title="Embedding">
            <Text strong>
              {runtime.data?.embedding_provider === "local"
                ? "本地向量"
                : providerLabel(runtime.data?.embedding_provider ?? "-")}
            </Text>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              {runtime.data?.embedding_model_name || "本地向量"}
            </Paragraph>
            <Paragraph type="secondary">
              把问题和知识转成可以计算相似度的向量。
            </Paragraph>
            <Tag>{runtime.data?.embedding_dimensions ?? "-"} 维</Tag>
          </Card>
        </Col>}
        {section === "global" && <Col xs={12} xl={6}>
          <Card className="metric-card" title="知识排序与回答依据校验">
            <Space direction="vertical" size={4}>
              <Text>
                知识排序：
                {knowledgeSortingLabel(
                  runtime.data?.rerank_provider ?? "-",
                )}
              </Text>
              <Text>
                回答依据校验：
                {verificationLabel(
                  runtime.data?.claim_verifier_provider ?? "-",
                )}
              </Text>
              <Tag
                color={
                  runtime.data?.claim_verifier_provider === "none"
                    ? "default"
                    : runtime.data?.claim_verifier_enforce
                      ? "red"
                      : "gold"
                }
              >
                {runtime.data?.claim_verifier_provider === "none"
                  ? "校验已关闭"
                  : runtime.data?.claim_verifier_enforce
                    ? "无依据时禁止自动发送"
                    : "发现无依据时提示"}
              </Tag>
              <Text type="secondary">
                先选更相关的知识，再检查回答中的关键事实是否有资料支持。
              </Text>
            </Space>
          </Card>
        </Col>}
        {section === "integrations" && <Col xs={24}>
          <Card className="metric-card" title="外部集成">
            <Space direction="vertical" size={4}>
              <Text type="secondary">
                连接企业服务、客户服务、订单履约和内容运营等外部业务系统。
              </Text>
              <Text>
                工单：
                {integrationLabel(
                  runtime.data?.ticket_integration_provider ?? "-",
                )}
              </Text>
              <Text>
                渠道发布：
                {integrationLabel(
                  runtime.data?.ecommerce_channel_provider ?? "-",
                )}
              </Text>
              <Text>
                业务查询：
                {runtime.data?.logistics_query_url_configured
                  ? "已配置"
                  : "未配置"}
              </Text>
              <Text>
                低风险咨询自动回复：
                {runtime.data?.customer_service_auto_reply_enabled
                  ? "已启用"
                  : "已关闭"}
              </Text>
              {runtime.data?.customer_service_auto_reply_enabled && (
                <Tag color="green">
                  置信度 ≥{" "}
                  {Math.round(
                    (runtime.data.customer_service_auto_reply_min_confidence ??
                      0.85) * 100,
                  )}
                  % · 最多{" "}
                  {runtime.data.customer_service_auto_reply_max_characters ??
                    1200}{" "}
                  字
                </Tag>
              )}
              <Text>
                内容文案：{runtime.data?.ecommerce_content_provider ?? "-"}
                {runtime.data?.ecommerce_content_model_name
                  ? ` · ${runtime.data.ecommerce_content_model_name}`
                  : ""}
              </Text>
              <Text>
                内容图片：{runtime.data?.ecommerce_image_provider ?? "-"}
                {runtime.data?.ecommerce_image_model_name
                  ? ` · ${runtime.data.ecommerce_image_model_name}`
                  : ""}
              </Text>
              <Text>
                图片审核：{runtime.data?.ecommerce_visual_audit_provider ?? "-"}
                {runtime.data?.ecommerce_visual_audit_model_name
                  ? ` · ${runtime.data.ecommerce_visual_audit_model_name}`
                  : ""}
              </Text>
              <Text>
                配音：{runtime.data?.ecommerce_tts_provider ?? "-"}
                {runtime.data?.ecommerce_tts_model_name
                  ? ` · ${runtime.data.ecommerce_tts_model_name}`
                  : ""}
                {runtime.data?.ecommerce_tts_voice
                  ? ` · ${runtime.data.ecommerce_tts_voice}`
                  : ""}
              </Text>
              <Text>
                存储：
                {integrationLabel(
                  runtime.data?.object_storage_provider ?? "-",
                )}
              </Text>
              <Text>
                任务：
                {integrationLabel(runtime.data?.task_mode ?? "-")}
              </Text>
            </Space>
          </Card>
        </Col>}
      </Row>

      {section === "employees" && <Card className="section-card" title="员工模型路由">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={employees.data}
          loading={employees.isLoading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedId ? [selectedId] : [],
            onChange: (keys) => {
              if (typeof keys[0] === "string") {
                selectEmployee(keys[0]);
              }
            },
          }}
          onRow={(employee) => ({
            onClick: () => selectEmployee(employee.id),
            style: { cursor: "pointer" },
          })}
        />
      </Card>}

      {section === "employees" && <Drawer
        open={configOpen}
        width={900}
        title={
          selected
            ? `配置模型 · ${selected.name}`
            : "配置数字员工模型"
        }
        onClose={() => setConfigOpen(false)}
        extra={
          <Button
            type="primary"
            loading={save.isPending}
            disabled={!selected}
            onClick={() => save.mutate()}
          >
            保存当前员工配置
          </Button>
        }
      >
        {selected && (
          <Descriptions
            column={2}
            size="small"
            bordered
            style={{ marginBottom: 20 }}
          >
            <Descriptions.Item label="当前员工">
              {selected.name}
            </Descriptions.Item>
            <Descriptions.Item label="员工标识">
              {selected.employee_key}
            </Descriptions.Item>
            <Descriptions.Item label="员工状态">
              <Tag color={selected.status === "ACTIVE" ? "green" : "default"}>
                {employeeStatusLabels[selected.status] ?? "未知状态"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="配置版本">
              v{selected.config_revision}
            </Descriptions.Item>
          </Descriptions>
        )}
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 20 }}
          message="先理解三类模型配置"
          description="分类模型负责识别问题，生成模型负责组织回答；知识排序负责把更相关的资料排在前面，回答依据校验负责检查回答中的关键事实是否有引用资料支持。本地规则不调用外部模型，外部模型会逐条进行语义判断。"
        />
        <Form layout="vertical">
          <Row gutter={24}>
            <Col xs={24} xl={12}>
              <Card size="small" title="分类模型">
                <ModelEndpointFields
                  provider={config.classificationProvider}
                  model={config.classificationModel}
                  fallback={config.classificationFallback}
                  onProvider={(value) =>
                    setConfig({ ...config, classificationProvider: value })
                  }
                  onModel={(value) =>
                    setConfig({ ...config, classificationModel: value })
                  }
                  onFallback={(value) =>
                    setConfig({ ...config, classificationFallback: value })
                  }
                />
                <Form.Item label="置信度阈值">
                  <InputNumber
                    min={0}
                    max={1}
                    step={0.01}
                    value={config.classificationThreshold}
                    onChange={(value) =>
                      setConfig({ ...config, classificationThreshold: value })
                    }
                  />
                </Form.Item>
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card size="small" title="生成模型">
                <ModelEndpointFields
                  provider={config.generationProvider}
                  model={config.generationModel}
                  fallback={config.generationFallback}
                  onProvider={(value) =>
                    setConfig({ ...config, generationProvider: value })
                  }
                  onModel={(value) =>
                    setConfig({ ...config, generationModel: value })
                  }
                  onFallback={(value) =>
                    setConfig({ ...config, generationFallback: value })
                  }
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={24}>
            <Col xs={24} xl={12}>
              <Card size="small" title="回答依据校验">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="检查回答中的关键事实是否有引用资料支持"
                  description="本地规则不调用外部模型；外部模型会逐条进行语义判断。"
                />
                <Form.Item label="校验方式">
                  <Select
                    value={config.verifierProvider}
                    onChange={(value) =>
                      setConfig({ ...config, verifierProvider: value })
                    }
                    options={[
                      { value: "inherit", label: "继承全局" },
                      { value: "none", label: "关闭" },
                      { value: "local", label: "本地规则" },
                      { value: "external", label: "外部模型" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="外部校验模型">
                  <Input
                    value={config.verifierModel}
                    placeholder="留空继承全局配置"
                    onChange={(event) =>
                      setConfig({ ...config, verifierModel: event.target.value })
                    }
                  />
                </Form.Item>
                <Space size="middle">
                  <Form.Item label="外部失败时使用本地规则">
                    <TriStateSelect
                      value={config.verifierFallback}
                      onChange={(value) =>
                        setConfig({ ...config, verifierFallback: value })
                      }
                    />
                  </Form.Item>
                  <Form.Item label="严格拦截">
                    <TriStateSelect
                      value={config.verifierEnforce}
                      onChange={(value) =>
                        setConfig({ ...config, verifierEnforce: value })
                      }
                    />
                  </Form.Item>
                </Space>
              </Card>
            </Col>
            <Col xs={24} xl={12}>
              <Card size="small" title="知识排序">
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="把更相关的企业知识排到前面"
                  description="本地混合排序使用向量相似度和关键词匹配，不调用外部模型。"
                />
                <Form.Item label="排序方式">
                  <Select
                    value={config.rerankProvider}
                    onChange={(value) =>
                      setConfig({ ...config, rerankProvider: value })
                    }
                    options={[
                      { value: "inherit", label: "继承全局" },
                      { value: "local", label: "本地混合排序" },
                      { value: "external", label: "外部排序模型" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="外部排序模型">
                  <Input
                    value={config.rerankModel}
                    placeholder="留空继承全局配置"
                    onChange={(event) =>
                      setConfig({ ...config, rerankModel: event.target.value })
                    }
                  />
                </Form.Item>
                <Space size="middle" wrap>
                  <Form.Item label="向量权重">
                    <InputNumber
                      min={0}
                      max={1}
                      step={0.05}
                      value={config.vectorWeight}
                      onChange={(value) =>
                        setConfig({ ...config, vectorWeight: value })
                      }
                    />
                  </Form.Item>
                  <Form.Item label="关键词权重">
                    <InputNumber
                      min={0}
                      max={1}
                      step={0.05}
                      value={config.lexicalWeight}
                      onChange={(value) =>
                        setConfig({ ...config, lexicalWeight: value })
                      }
                    />
                  </Form.Item>
                  <Form.Item label="启用知识排序">
                    <Switch
                      checked={config.rerankEnabled}
                      onChange={(value) =>
                        setConfig({ ...config, rerankEnabled: value })
                      }
                    />
                  </Form.Item>
                </Space>
                <Form.Item label="失败时降级">
                  <TriStateSelect
                    value={config.rerankFallback}
                    onChange={(value) =>
                      setConfig({ ...config, rerankFallback: value })
                    }
                  />
                </Form.Item>
              </Card>
            </Col>
          </Row>
        </Form>
      </Drawer>}

      {section === "global" && <Card className="section-card" title="配置边界">
        <Descriptions column={1} size="small">
          <Descriptions.Item label="全局凭证">
            模型地址、API Key 和供应商凭证仍由后端环境变量或 Secret 管理。
          </Descriptions.Item>
          <Descriptions.Item label="员工配置">
            员工只能覆盖已允许的模型来源、模型名、参数和降级策略。
          </Descriptions.Item>
          <Descriptions.Item label="生效范围">
            保存后对后续新任务生效，不会重写已完成工单的审计记录。
          </Descriptions.Item>
        </Descriptions>
      </Card>}
    </Space>
  );
}

function ModelEndpointFields({
  provider,
  model,
  fallback,
  onProvider,
  onModel,
  onFallback,
}: {
  provider: string;
  model: string;
  fallback: string;
  onProvider: (value: string) => void;
  onModel: (value: string) => void;
  onFallback: (value: string) => void;
}) {
  return (
    <>
      <Form.Item label="模型来源">
        <Select
          value={provider}
          onChange={onProvider}
          options={[
            { value: "inherit", label: "继承全局" },
            { value: "local", label: "本地规则" },
            { value: "openai_compatible", label: "OpenAI 兼容" },
          ]}
        />
      </Form.Item>
      <Form.Item label="模型名">
        <Input
          value={model}
          placeholder="留空继承全局模型"
          onChange={(event) => onModel(event.target.value)}
        />
      </Form.Item>
      <Form.Item label="外部失败时使用本地规则">
        <TriStateSelect value={fallback} onChange={onFallback} />
      </Form.Item>
    </>
  );
}

function TriStateSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      value={value}
      onChange={onChange}
      style={{ width: 150 }}
      options={[
        { value: "inherit", label: "继承全局" },
        { value: "true", label: "启用" },
        { value: "false", label: "关闭" },
      ]}
    />
  );
}
