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
  Modal,
  Progress,
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
import { useEffect, useRef, useState } from "react";

import {
  acceptEcommerceAssetVisualReview,
  archiveEcommerceAsset,
  createEcommerceListingBatchJob,
  createEcommerceCategoryProfile,
  createEcommerceListing,
  createEcommerceProduct,
  createEcommerceVideoRenderJob,
  downloadCategoryImportTemplate,
  downloadEcommerceProductImportTemplate,
  downloadEcommerceListingPackage,
  fetchEcommerceAssetBlob,
  generateEcommerceStoryboard,
  generateEcommerceProductImage,
  generateEcommerceProductImages,
  getEcommerceMetrics,
  getEcommerceListing,
  importEcommerceProducts,
  listEcommerceImageGenerations,
  listEcommerceCategoryProfiles,
  listEcommerceListingBatchJobs,
  listEcommerceListings,
  listEcommerceProducts,
  listEcommerceProductAssets,
  listEcommerceVideoRenderJobs,
  listDigitalEmployees,
  previewEcommerceProductImport,
  reviewEcommerceListing,
  retryEcommerceVideoRenderJob,
  retryEcommerceListing,
  setPrimaryEcommerceAsset,
  syncProductKnowledgeCards,
  updateEcommerceListingContent,
  uploadEcommerceProductAsset,
} from "./api";
import type {
  EcommerceListingDetail,
  EcommerceCategoryProfile,
  EcommerceListingBatchJob,
  EcommerceListingItem,
  EcommerceProduct,
  EcommerceProductAsset,
  EcommerceProductImportPreview,
  EcommerceProductImportRow,
  DigitalEmployee,
} from "./types";
import { message } from "./feedback";
import {
  assetStatusLabels,
  assetTypeLabels,
  batchStatusLabels,
  channelLabels,
  localizedLabel,
  productStatusLabels,
} from "./statusLabels";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

const listingStatusLabels: Record<string, string> = {
  PENDING_REVIEW: "待审核",
  NEEDS_HUMAN: "需人工",
  PUBLISHING: "发布中",
  PUBLISHED: "已发布",
  REJECTED: "已退回",
  FAILED: "发布失败",
};

const videoJobStatusLabels: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "渲染中",
  SUCCEEDED: "已完成",
  FAILED: "渲染失败",
};

function statusColor(status: string): string {
  if (status === "PUBLISHED") return "green";
  if (status === "NEEDS_HUMAN" || status === "FAILED") return "red";
  if (status === "PENDING_REVIEW" || status === "PUBLISHING") return "blue";
  return "default";
}

function videoJobStatusColor(status: string): string {
  if (status === "SUCCEEDED") return "green";
  if (status === "FAILED") return "red";
  if (status === "RUNNING") return "blue";
  return "gold";
}

export type EcommerceSection =
  | "overview"
  | "products"
  | "listings"
  | "insights";

const ecommerceSections = [
  { key: "overview", label: "运营入口", path: "/ecommerce" },
  { key: "products", label: "商品与素材工作区", path: "/ecommerce/products" },
  { key: "listings", label: "上架审核协作", path: "/ecommerce/listings" },
  { key: "insights", label: "主管运营看板", path: "/ecommerce/insights" },
] as const;

export default function EcommercePage({
  technicalMode = false,
  section,
  onNavigate,
}: {
  technicalMode?: boolean;
  section: EcommerceSection;
  onNavigate: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const requestedListingId = new URLSearchParams(window.location.search).get(
    "listing",
  );
  const [productOpen, setProductOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [listingOpen, setListingOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(
    requestedListingId,
  );
  const [assetProduct, setAssetProduct] = useState<EcommerceProduct | null>(null);
  const [generateProduct, setGenerateProduct] =
    useState<EcommerceProduct | null>(null);
  const products = useQuery({
    queryKey: ["ecommerce-products"],
    queryFn: listEcommerceProducts,
  });
  const categories = useQuery({
    queryKey: ["ecommerce-categories"],
    queryFn: listEcommerceCategoryProfiles,
  });
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
  });
  const listings = useQuery({
    queryKey: ["ecommerce-listings"],
    queryFn: listEcommerceListings,
    refetchInterval: 5_000,
  });
  const batchJobs = useQuery({
    queryKey: ["ecommerce-listing-batch-jobs"],
    queryFn: listEcommerceListingBatchJobs,
    refetchInterval: (query) => {
      const latest = query.state.data?.items[0];
      return latest &&
        (latest.status === "QUEUED" || latest.status === "RUNNING")
        ? 1_000
        : false;
    },
  });
  const latestBatch = batchJobs.data?.items[0];
  const completedBatchId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (
      !latestBatch ||
      !["SUCCEEDED", "PARTIAL", "FAILED"].includes(latestBatch.status) ||
      completedBatchId.current === latestBatch.id
    ) {
      return;
    }
    completedBatchId.current = latestBatch.id;
    void queryClient.invalidateQueries({
      queryKey: ["ecommerce-listings"],
    });
    void queryClient.invalidateQueries({
      queryKey: ["ecommerce-metrics"],
    });
  }, [latestBatch, queryClient]);
  const imageUsage = useQuery({
    queryKey: ["ecommerce-image-generations"],
    queryFn: listEcommerceImageGenerations,
  });
  const metrics = useQuery({
    queryKey: ["ecommerce-metrics"],
    queryFn: getEcommerceMetrics,
    refetchInterval: 10_000,
  });
  const detail = useQuery({
    queryKey: ["ecommerce-listing", selectedTaskId],
    queryFn: () => getEcommerceListing(selectedTaskId!),
    enabled: Boolean(selectedTaskId),
  });
  const syncProductKnowledge = useMutation({
    mutationFn: () => syncProductKnowledgeCards(),
    onSuccess: async (result) => {
      message.success(
        `商品知识同步完成：更新 ${result.synced}，未变化 ${result.unchanged}，失败 ${result.failed}`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["knowledge", "spaces"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["knowledge", "documents"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const items = listings.data?.items ?? [];
  const stats = {
    products: products.data?.length ?? 0,
    review: items.filter((item) => item.status === "PENDING_REVIEW").length,
    human: items.filter((item) => item.status === "NEEDS_HUMAN").length,
    published: items.filter((item) => item.status === "PUBLISHED").length,
  };
  const employeeName = (employeeId: string | null) =>
    employees.data?.find((employee) => employee.id === employeeId)?.name ??
    (employeeId ? "已停用员工" : "未分配");

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["ecommerce-products"] });
    await queryClient.invalidateQueries({ queryKey: ["ecommerce-listings"] });
    await queryClient.invalidateQueries({
      queryKey: ["ecommerce-image-generations"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["ecommerce-metrics"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["ecommerce-listing", selectedTaskId],
    });
  };

  const productColumns: ColumnsType<EcommerceProduct> = [
    {
      title: "商品",
      dataIndex: "name",
      render: (value: string, product) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary">{product.sku}</Text>
        </Space>
      ),
    },
    { title: "品牌", dataIndex: "brand", width: 120 },
    { title: "类目", dataIndex: "category", width: 130 },
    {
      title: "价格",
      dataIndex: "price",
      width: 100,
      render: (value: number) => `¥${Number(value).toFixed(2)}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (value: string) => productStatusLabels[value] ?? "未知状态",
    },
    {
      title: "操作",
      width: 180,
      fixed: "right",
      render: (_, product) => (
        <Space size={0}>
          <Button type="link" onClick={() => setAssetProduct(product)}>
            素材
          </Button>
          <Button type="link" onClick={() => setGenerateProduct(product)}>
            AI 主图
          </Button>
        </Space>
      ),
    },
  ];

  const listingColumns: ColumnsType<EcommerceListingItem> = [
    {
      title: "商品",
      dataIndex: "product_name",
      render: (value: string, task) => (
        <Button type="link" onClick={() => setSelectedTaskId(task.id)}>
          {value}
        </Button>
      ),
    },
    { title: "SKU", dataIndex: "sku", width: 140 },
    {
      title: "市场",
      dataIndex: "market_code",
      width: 90,
      render: (value: string, task) => (
        <Tag color={value === "US" ? "blue" : "default"}>
          {value} · {task.currency}
        </Tag>
      ),
    },
    {
      title: "渠道",
      dataIndex: "channel",
      width: 150,
      render: (value: string) => localizedLabel(channelLabels, value),
    },
    {
      title: "负责数字员工",
      dataIndex: "owner_employee_id",
      width: 170,
      render: (value: string | null) => (
        <Tag color={value ? "cyan" : "default"}>
          {employeeName(value)}
        </Tag>
      ),
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      width: 80,
      render: (value: string) => (
        <Tag color={value === "R2" ? "red" : value === "R1" ? "gold" : "green"}>
          {value}
        </Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={statusColor(value)}>
          {listingStatusLabels[value] ?? "未知状态"}
        </Tag>
      ),
    },
    {
      title: "外部编号",
      dataIndex: "external_listing_id",
      width: 150,
      render: (value: string | null) => value ?? "-",
    },
  ];

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>
            {technicalMode ? "电商运营技术视图" : "电商运营数字员工工作区"}
          </Title>
          <Paragraph type="secondary">
            {technicalMode
              ? "查看商品、Listing、模型生成、合规审核、素材和异步渲染之间的技术处理链。"
              : "商品上架、视觉内容和运营主管数字员工共同完成资料校验、内容生产、审核发布和质量复核。"}
          </Paragraph>
        </div>
        <Space>
          {technicalMode && <Tag color="cyan">TECH</Tag>}
          <Tag color="cyan">
            AI 图片 {imageUsage.data?.total_images ?? 0} 张 · 费用{" "}
            {Number(imageUsage.data?.estimated_cost ?? 0).toFixed(3)}
          </Tag>
          {section === "products" && (
            <>
              <Button
                loading={syncProductKnowledge.isPending}
                onClick={() => syncProductKnowledge.mutate()}
              >
                同步商品知识
              </Button>
              <Button onClick={() => setProductOpen(true)}>新增商品</Button>
              <Button onClick={() => setCategoryOpen(true)}>品类档案</Button>
              <Button onClick={() => setImportOpen(true)}>批量导入 CSV</Button>
            </>
          )}
          {section === "listings" && (
            <>
              <Button
                disabled={!products.data?.length}
                onClick={() => setBatchOpen(true)}
              >
                批量生成上架
              </Button>
              <Button
                type="primary"
                disabled={!products.data?.length}
                onClick={() => setListingOpen(true)}
              >
                创建上架任务
              </Button>
            </>
          )}
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        message="当前业务入口：国内电商运营入口"
        description="商品上架数字员工负责资料校验和上架内容，视觉内容数字员工负责主图、分镜与视频，电商运营主管数字员工负责质量、返工和异常复核。"
      />

      <Menu
        className="knowledge-subnav"
        mode="horizontal"
        selectedKeys={[
          ecommerceSections.find((item) => item.key === section)?.path ??
            "/ecommerce",
        ]}
        onClick={({ key }) => onNavigate(key)}
        items={ecommerceSections.map((item) => ({
          key: item.path,
          label: item.label,
        }))}
      />

      {(products.isError || listings.isError || metrics.isError) && (
        <Alert
          type="error"
          showIcon
          message="电商数据加载失败"
          description={
            (products.error ?? listings.error ?? metrics.error)?.message
          }
        />
      )}

      {section === "overview" && (
        <Row gutter={[16, 16]}>
          {[
            {
              title: "商品与素材",
              description: "维护商品资料、品类、商品图片和视频素材。",
              path: "/ecommerce/products",
              button: "进入商品管理",
            },
            {
              title: "上架与审核",
              description: "创建上架任务、审核内容和处理发布失败。",
              path: "/ecommerce/listings",
              button: "进入上架审核",
            },
            {
              title: "运营指标",
              description: "查看发布成功率、人工介入率和视频渲染质量。",
              path: "/ecommerce/insights",
              button: "查看运营指标",
            },
          ].map((item) => (
            <Col xs={24} md={8} key={item.title}>
              <Card
                className="knowledge-overview-card"
                title={item.title}
                extra={
                  <Button
                    type="link"
                    onClick={() => onNavigate(item.path)}
                  >
                    {item.button}
                  </Button>
                }
              >
                <Paragraph type="secondary">{item.description}</Paragraph>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      {technicalMode && section === "insights" && (
        <Card
          className="section-card"
          title="技术处理链"
          extra={<Tag color="cyan">LIVE DATA</Tag>}
        >
          <Descriptions
            size="small"
            column={2}
            items={[
              {
                key: "entities",
                label: "核心实体",
                children: "商品 → 知识空间 → Listing → 审核 → 素材/视频",
              },
              {
                key: "batch",
                label: "批量任务",
                children: latestBatch
                  ? `${batchStatusLabels[latestBatch.status] ?? "未知状态"} · ${latestBatch.succeeded_count}/${latestBatch.total_count}`
                  : "暂无运行中的批量任务",
              },
              {
                key: "image",
                label: "图片生成",
                children: `${imageUsage.data?.total_images ?? 0} 张 · 费用 ${Number(
                  imageUsage.data?.estimated_cost ?? 0,
                ).toFixed(3)}`,
              },
              {
                key: "review",
                label: "审核门禁",
                children: "宣传语规则、商品完整性、图片视觉审核",
              },
              {
                key: "render",
                label: "异步渲染",
                children: `成功率 ${
                  metrics.data
                    ? `${(metrics.data.video_success_rate * 100).toFixed(1)}%`
                    : "-"
                } · 成功 ${metrics.data?.video_succeeded ?? 0} / 失败 ${
                  metrics.data?.video_failed ?? 0
                }`,
              },
              {
                key: "storage",
                label: "素材对象",
                children: "商品主图、分镜、视频、字幕和背景音乐统一进入对象存储",
              },
            ]}
          />
        </Card>
      )}

      {section === "insights" && <Row gutter={[16, 16]}>
        {[
          ["商品总数", stats.products],
          ["待审核上架", stats.review],
          ["需要人工", stats.human],
          ["已发布", stats.published],
        ].map(([title, value]) => (
          <Col xs={12} xl={6} key={String(title)}>
            <Card className="metric-card">
              <Statistic title={title} value={value} />
            </Card>
          </Col>
        ))}
      </Row>}
      {section === "listings" && latestBatch && (
        <Card size="small" title="最近批量上架任务">
          <Space direction="vertical" className="page-stack">
            <Space wrap>
              <Tag color={videoJobStatusColor(latestBatch.status)}>
                {batchStatusLabels[latestBatch.status] ?? "未知状态"}
              </Tag>
              <Text>
                成功 {latestBatch.succeeded_count} / 失败{" "}
                {latestBatch.failed_count} / 总计 {latestBatch.total_count}
              </Text>
              <Text type="secondary">
                {localizedLabel(channelLabels, latestBatch.channel)} ·{" "}
                {latestBatch.market_code}
              </Text>
            </Space>
            <Progress
              percent={Math.round(
                ((latestBatch.succeeded_count + latestBatch.failed_count) /
                  Math.max(1, latestBatch.total_count)) *
                  100,
              )}
              status={
                latestBatch.status === "PARTIAL" ||
                latestBatch.status === "FAILED"
                  ? "exception"
                  : latestBatch.status === "SUCCEEDED"
                    ? "success"
                    : "active"
              }
            />
            <Space wrap>
              {latestBatch.items.map((item) => (
                <Tag
                  key={item.id}
                  color={
                    item.status === "SUCCEEDED"
                      ? "green"
                      : item.status === "FAILED"
                        ? "red"
                        : "blue"
                  }
                >
                  {products.data?.find(
                    (product) => product.id === item.product_id,
                  )?.name ?? item.product_id.slice(0, 8)}
                  ：{batchStatusLabels[item.status] ?? "未知状态"}
                </Tag>
              ))}
            </Space>
            {latestBatch.error_message && (
              <Text type="danger">{latestBatch.error_message}</Text>
            )}
            {latestBatch.items.some((item) => item.listing_task_id) && (
              <Space wrap>
                {latestBatch.items
                  .filter((item) => item.listing_task_id)
                  .map((item) => (
                    <Button
                      key={item.id}
                      size="small"
                      onClick={() =>
                        setSelectedTaskId(item.listing_task_id!)
                      }
                    >
                      查看任务 {item.listing_task_id!.slice(0, 8)}
                    </Button>
                  ))}
              </Space>
            )}
          </Space>
        </Card>
      )}
      {section === "insights" && <Row gutter={[16, 16]}>
        {[
          [
            "发布成功率",
            metrics.data
              ? `${(metrics.data.publication_success_rate * 100).toFixed(1)}%`
              : "-",
            metrics.data
              ? `${metrics.data.published} 成功 · ${metrics.data.failed} 失败`
              : "",
          ],
          [
            "平均上架耗时",
            formatDuration(metrics.data?.average_publish_seconds),
            "创建至发布",
          ],
          [
            "人工介入率",
            metrics.data
              ? `${(metrics.data.human_intervention_rate * 100).toFixed(1)}%`
              : "-",
            `${metrics.data?.needs_human ?? 0} 个任务当前待人工`,
          ],
          [
            "视频渲染成功率",
            metrics.data
              ? `${(metrics.data.video_success_rate * 100).toFixed(1)}%`
              : "-",
            `${metrics.data?.video_succeeded ?? 0} 成功 · ${
              metrics.data?.video_failed ?? 0
            } 失败`,
          ],
        ].map(([title, value, description]) => (
          <Col xs={12} xl={6} key={title}>
            <Card className="metric-card">
              <Statistic title={title} value={value} />
              <Text type="secondary">{description}</Text>
            </Card>
          </Col>
        ))}
      </Row>}

      {section === "products" && <Card className="section-card" title="商品资料">
        <Table
          rowKey="id"
          columns={productColumns}
          dataSource={products.data}
          loading={products.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: "请先新增商品" }}
          scroll={{ x: 900 }}
        />
      </Card>}

      {section === "listings" && <Card className="section-card" title="上架任务">
        <Table
          rowKey="id"
          columns={listingColumns}
          dataSource={listings.data?.items}
          loading={listings.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: "暂无上架任务" }}
        />
      </Card>}

      <CreateProductModal
        open={productOpen}
        onClose={() => setProductOpen(false)}
        onCreated={refresh}
      />
      <ImportProductsModal
        open={importOpen}
        categories={categories.data ?? []}
        onClose={() => setImportOpen(false)}
        onImported={refresh}
      />
      <CategoryProfilesModal
        open={categoryOpen}
        categories={categories.data ?? []}
        onClose={() => setCategoryOpen(false)}
        onCreated={async () => {
          await queryClient.invalidateQueries({
            queryKey: ["ecommerce-categories"],
          });
        }}
      />
      <CreateListingBatchModal
        open={batchOpen}
        products={products.data ?? []}
        onClose={() => setBatchOpen(false)}
        onCreated={async () => {
          await queryClient.invalidateQueries({
            queryKey: ["ecommerce-listing-batch-jobs"],
          });
        }}
      />
      <CreateListingModal
        open={listingOpen}
        products={products.data ?? []}
        onClose={() => setListingOpen(false)}
        onCreated={async (task) => {
          await refresh();
          setSelectedTaskId(task.id);
        }}
      />
      <ListingDrawer
        task={detail.data ?? null}
        loading={detail.isLoading}
        onClose={() => setSelectedTaskId(null)}
        onReviewed={refresh}
      />
      <ProductAssetDrawer
        product={assetProduct}
        employees={employees.data ?? []}
        onClose={() => setAssetProduct(null)}
      />
      <GenerateProductImageModal
        product={generateProduct}
        onClose={() => setGenerateProduct(null)}
        onGenerated={(product) => {
          setGenerateProduct(null);
          setAssetProduct(product);
        }}
      />
    </Space>
  );
}

function CategoryProfilesModal({
  open,
  categories,
  onClose,
  onCreated,
}: {
  open: boolean;
  categories: EcommerceCategoryProfile[];
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [required, setRequired] = useState("");
  const [presales, setPresales] = useState("");
  const [aftersales, setAftersales] = useState("");
  const [claims, setClaims] = useState("");
  const splitValues = (value: string) =>
    value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
  const create = useMutation({
    mutationFn: () =>
      createEcommerceCategoryProfile({
        code,
        name,
        requiredAttributes: splitValues(required),
        presalesKeywords: splitValues(presales),
        aftersalesKeywords: splitValues(aftersales),
        restrictedClaims: splitValues(claims),
      }),
    onSuccess: async () => {
      message.success("品类档案已创建");
      setCode("");
      setName("");
      setRequired("");
      setPresales("");
      setAftersales("");
      setClaims("");
      await onCreated();
    },
    onError: (error: Error) => message.error(error.message),
  });
  return (
    <Modal
      title="电商品类档案"
      open={open}
      width={900}
      onCancel={onClose}
      footer={null}
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: true }}
          dataSource={categories}
          columns={[
            { title: "品类", dataIndex: "name" },
            { title: "编码", dataIndex: "code" },
            {
              title: "必填属性",
              dataIndex: "required_attributes",
              render: (values: string[]) => values.join("、"),
            },
            {
              title: "渠道",
              dataIndex: "channel",
              render: (value: string) =>
                localizedLabel(channelLabels, value),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: string) =>
                productStatusLabels[value] ?? "未知状态",
            },
          ]}
        />
        <Card size="small" title="新建品类">
          <Form layout="vertical">
            <Space wrap>
              <Form.Item label="品类编码">
                <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="vacuum_cup" />
              </Form.Item>
              <Form.Item label="品类名称">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="保温杯" />
              </Form.Item>
            </Space>
            <Form.Item label="必填属性（逗号分隔）">
              <TextArea rows={2} value={required} onChange={(e) => setRequired(e.target.value)} />
            </Form.Item>
            <Form.Item label="售前关键词">
              <TextArea rows={2} value={presales} onChange={(e) => setPresales(e.target.value)} />
            </Form.Item>
            <Form.Item label="售后关键词">
              <TextArea rows={2} value={aftersales} onChange={(e) => setAftersales(e.target.value)} />
            </Form.Item>
            <Form.Item label="禁用宣传语">
              <TextArea rows={2} value={claims} onChange={(e) => setClaims(e.target.value)} />
            </Form.Item>
            <Button
              type="primary"
              loading={create.isPending}
              disabled={!code.trim() || !name.trim() || splitValues(required).length === 0}
              onClick={() => create.mutate()}
            >
              创建品类档案
            </Button>
          </Form>
        </Card>
      </Space>
    </Modal>
  );
}

function CreateProductModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("家居日用");
  const [brand, setBrand] = useState("演示品牌");
  const [price, setPrice] = useState<number | null>(39.9);
  const [attributes, setAttributes] = useState('{"材质":"食品级硅胶","颜色":"奶油白"}');
  const create = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(attributes) as Record<string, unknown>;
      } catch {
        throw new Error("商品属性必须是合法 JSON");
      }
      return createEcommerceProduct({
        sku,
        name,
        category,
        brand,
        price: price ?? 0,
        attributes: parsed,
      });
    },
    onSuccess: async () => {
      message.success("商品资料已创建");
      setSku("");
      setName("");
      await onCreated();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Modal
      title="新增商品"
      open={open}
      onCancel={onClose}
      okText="创建商品"
      confirmLoading={create.isPending}
      okButtonProps={{ disabled: !sku.trim() || !name.trim() || price === null }}
      onOk={() => create.mutate()}
    >
      <Form layout="vertical">
        <Form.Item
          label="SKU"
          htmlFor="ecommerce-product-sku"
          required
        >
          <Input
            id="ecommerce-product-sku"
            value={sku}
            onChange={(event) => setSku(event.target.value)}
          />
        </Form.Item>
        <Form.Item
          label="商品名称"
          htmlFor="ecommerce-product-name"
          required
        >
          <Input
            id="ecommerce-product-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Form.Item>
        <Space size="middle" className="form-row" align="start">
          <Form.Item label="类目">
            <Input value={category} onChange={(event) => setCategory(event.target.value)} />
          </Form.Item>
          <Form.Item label="品牌">
            <Input value={brand} onChange={(event) => setBrand(event.target.value)} />
          </Form.Item>
          <Form.Item label="价格">
            <InputNumber min={0} value={price} onChange={setPrice} />
          </Form.Item>
        </Space>
        <Form.Item label="商品属性 JSON">
          <TextArea
            autoSize={{ minRows: 4, maxRows: 8 }}
            value={attributes}
            onChange={(event) => setAttributes(event.target.value)}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function ImportProductsModal({
  open,
  categories,
  onClose,
  onImported,
}: {
  open: boolean;
  categories: EcommerceCategoryProfile[];
  onClose: () => void;
  onImported: () => Promise<void>;
}) {
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState("");
  const [categoryProfileId, setCategoryProfileId] = useState("");
  const [preview, setPreview] =
    useState<EcommerceProductImportPreview | null>(null);
  const previewImport = useMutation({
    mutationFn: (input: { csv: string; categoryProfileId: string }) =>
      previewEcommerceProductImport(
        input.csv,
        input.categoryProfileId || undefined,
      ),
    onSuccess: (result) => setPreview(result),
    onError: (error: Error) => message.error(error.message),
  });
  const runImport = useMutation({
    mutationFn: () =>
      importEcommerceProducts(csvText, categoryProfileId || undefined),
    onSuccess: async (result) => {
      message.success(
        `导入完成：创建 ${result.created_count} 个，跳过 ${result.skipped_count} 个`,
      );
      await onImported();
      setCsvText("");
      setFileName("");
      setPreview(null);
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });
  const downloadTemplate = async () => {
    try {
      const blob = categoryProfileId
        ? await downloadCategoryImportTemplate(categoryProfileId)
        : await downloadEcommerceProductImportTemplate();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = categoryProfileId
        ? `${categories.find((item) => item.id === categoryProfileId)?.code ?? "products"}-products.csv`
        : "ecommerce-products.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error((error as Error).message);
    }
  };
  const columns: ColumnsType<EcommerceProductImportRow> = [
    { title: "行", dataIndex: "row_number", width: 55 },
    { title: "SKU", dataIndex: "sku", width: 150 },
    { title: "商品", dataIndex: "name" },
    { title: "类目", dataIndex: "category", width: 100 },
    {
      title: "结果",
      dataIndex: "valid",
      width: 90,
      render: (valid: boolean) => (
        <Tag color={valid ? "green" : "red"}>
          {valid ? "可导入" : "需修正"}
        </Tag>
      ),
    },
    {
      title: "问题",
      dataIndex: "errors",
      width: 240,
      render: (errors: string[]) => errors.join("；") || "-",
    },
  ];

  return (
    <Modal
      title="批量导入商品"
      open={open}
      width={960}
      onCancel={onClose}
      okText="确认导入有效行"
      confirmLoading={runImport.isPending}
      okButtonProps={{
        disabled:
          !csvText || !preview || preview.valid_rows === 0,
      }}
      onOk={() => runImport.mutate()}
    >
      <Space direction="vertical" size="middle" className="page-stack">
        <Select
          value={categoryProfileId || undefined}
          onChange={setCategoryProfileId}
          placeholder="选择品类（推荐）"
          options={categories.map((category) => ({
            value: category.id,
            label: `${category.name} · ${category.code}`,
          }))}
        />
        <Alert
          type="info"
          showIcon
          message="先下载模板，填写后上传预览"
          description="仅创建商品资料，不会自动调用千问生成上架任务。无主图、缺资料等问题会在创建上架任务时再次检查。"
          action={
            <Button size="small" onClick={downloadTemplate}>
              下载 CSV 模板
            </Button>
          }
        />
        <Upload
          accept=".csv,text/csv"
          showUploadList={false}
          beforeUpload={(file) => {
            if (file.size > 5 * 1024 * 1024) {
              message.error("CSV 文件不能超过 5 MB");
              return Upload.LIST_IGNORE;
            }
            void file.text().then((text) => {
              setCsvText(text);
              setFileName(file.name);
              setPreview(null);
              previewImport.mutate({
                csv: text,
                categoryProfileId,
              });
            });
            return Upload.LIST_IGNORE;
          }}
        >
          <Button type="primary" loading={previewImport.isPending}>
            选择 CSV 并预览
          </Button>
        </Upload>
        {fileName && <Text type="secondary">当前文件：{fileName}</Text>}
        {preview && (
          <>
            <Space>
              <Tag>总行数 {preview.total_rows}</Tag>
              <Tag color="green">可导入 {preview.valid_rows}</Tag>
              <Tag color="red">需修正 {preview.invalid_rows}</Tag>
            </Space>
            {preview.invalid_rows > 0 && (
              <Alert
                type="warning"
                showIcon
                message="无效行会跳过"
                description="修正 CSV 后重新上传，或先导入当前有效行。"
              />
            )}
            <Table
              rowKey="row_number"
              size="small"
              columns={columns}
              dataSource={preview.rows}
              pagination={{ pageSize: 8, showSizeChanger: false }}
              scroll={{ x: 850 }}
            />
          </>
        )}
      </Space>
    </Modal>
  );
}

function CreateListingBatchModal({
  open,
  products,
  onClose,
  onCreated,
}: {
  open: boolean;
  products: EcommerceProduct[];
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [productIds, setProductIds] = useState<string[]>([]);
  const [channel, setChannel] = useState("local_shop");
  const create = useMutation({
    mutationFn: () =>
      createEcommerceListingBatchJob({
        productIds,
        channel,
      }),
    onSuccess: async (job: EcommerceListingBatchJob) => {
      message.success(`批量任务已提交，共 ${job.total_count} 个商品`);
      setProductIds([]);
      await onCreated();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });
  return (
    <Modal
      title="批量生成上架任务"
      open={open}
      width={680}
      onCancel={onClose}
      okText="提交批量任务"
      confirmLoading={create.isPending}
      okButtonProps={{ disabled: productIds.length === 0 }}
      onOk={() => create.mutate()}
    >
      <Space direction="vertical" size="middle" className="page-stack">
        <Alert
          type="warning"
          showIcon
          message="批量任务会逐条调用已配置的文案模型"
          description="一次最多 10 个商品。没有主图或资料不完整的商品仍会创建任务，但会进入人工处理。"
        />
        <Form layout="vertical">
          <Form.Item label="选择商品" required>
            <Select
              mode="multiple"
              value={productIds}
              onChange={(values: string[]) =>
                setProductIds(values.slice(0, 10))
              }
              placeholder="最多选择 10 个商品"
              optionFilterProp="label"
              options={products.map((product) => ({
                value: product.id,
                label: `${product.name} · ${product.sku}`,
              }))}
            />
          </Form.Item>
          <Form.Item label="目标渠道">
            <Select
              value={channel}
              onChange={setChannel}
              options={[
                {
                  value: "local_shop",
                  label: "通用电商资料任务",
                },
                {
                  value: "ecommerce_demo",
                  label: "国内电商演示渠道",
                },
              ]}
            />
          </Form.Item>
        </Form>
        <Text type="secondary">
          已选择 {productIds.length} / 10 个商品
        </Text>
      </Space>
    </Modal>
  );
}

function CreateListingModal({
  open,
  products,
  onClose,
  onCreated,
}: {
  open: boolean;
  products: EcommerceProduct[];
  onClose: () => void;
  onCreated: (task: EcommerceListingDetail) => Promise<void>;
}) {
  const [productId, setProductId] = useState<string>();
  const [channel, setChannel] = useState("local_shop");
  const [marketCode, setMarketCode] = useState("CN");
  const [salePrice, setSalePrice] = useState<number | null>(null);
  const selectedProduct = products.find((product) => product.id === productId);
  const create = useMutation({
    mutationFn: () =>
      createEcommerceListing({
        productId: productId!,
        channel,
        marketCode,
        salePrice: salePrice ?? undefined,
      }),
    onSuccess: async (task) => {
      message.success("上架内容已生成");
      await onCreated(task);
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });
  return (
    <Modal
      title="创建上架任务"
      open={open}
      onCancel={onClose}
      okText="生成上架内容"
      confirmLoading={create.isPending}
      okButtonProps={{
        disabled:
          !productId || (marketCode === "US" && salePrice === null),
      }}
      onOk={() => create.mutate()}
    >
      <Form layout="vertical">
        <Form.Item label="商品" required>
          <Select
            value={productId}
            onChange={(value) => {
              setProductId(value);
              const product = products.find((item) => item.id === value);
              setSalePrice(
                marketCode === "CN" ? product?.price ?? null : null,
              );
            }}
            options={products.map((product) => ({
              value: product.id,
              label: `${product.name} · ${product.sku}`,
            }))}
          />
        </Form.Item>
        <Form.Item label="目标市场">
          <Select
            value={marketCode}
            onChange={(value) => {
              setMarketCode(value);
              setSalePrice(
                value === "CN"
                  ? selectedProduct?.price ?? null
                  : null,
              );
            }}
            options={[
              { value: "CN", label: "中国站 · 中文 / CNY" },
              {
                value: "US",
                label: "Amazon US · 后续开放",
                disabled: true,
              },
            ]}
          />
        </Form.Item>
        {marketCode === "US" && (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="美国站资料要求"
              description="商品需包含 localizations.en-US，以及 hs_code、origin_country、weight_kg 和 package_dimensions_cm，否则会转人工审核。"
            />
            <Form.Item label="美国站售价（USD）" required>
              <InputNumber
                min={0}
                prefix="$"
                value={salePrice}
                onChange={setSalePrice}
              />
            </Form.Item>
          </>
        )}
        <Form.Item label="发布渠道">
          <Select
            value={channel}
            onChange={setChannel}
            options={[
              { value: "local_shop", label: "本地演示店铺（不对外发布）" },
              {
                value: "ecommerce_demo",
                label: "国内电商演示渠道（不对外发布）",
              },
            ]}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function ListingDrawer({
  task,
  loading,
  onClose,
  onReviewed,
}: {
  task: EcommerceListingDetail | null;
  loading: boolean;
  onClose: () => void;
  onReviewed: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [backgroundMusicAssetId, setBackgroundMusicAssetId] =
    useState<string>();
  const [backgroundMusicVolume, setBackgroundMusicVolume] =
    useState<number>(0.18);
  const focusVideo =
    new URLSearchParams(window.location.search).get("video") === "1";
  const review = useMutation({
    mutationFn: (decision: "ACCEPTED" | "REJECTED") =>
      reviewEcommerceListing(task!.id, task!.version, decision),
    onSuccess: async (result) => {
      message.success(
        result.status === "PUBLISHING" ? "已审核，正在发布" : "任务已退回",
      );
      await onReviewed();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });
  const exportPackage = useMutation({
    mutationFn: () => downloadEcommerceListingPackage(task!.id),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `listing-${task!.sku.toLowerCase()}-${task!.id.slice(0, 8)}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      message.success("上架资料包已下载");
    },
    onError: (error: Error) => message.error(error.message),
  });
  const assets = useQuery({
    queryKey: ["ecommerce-assets", task?.product_id],
    queryFn: () => listEcommerceProductAssets(task!.product_id),
    enabled: Boolean(task),
  });
  const storyboardAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.metadata.listing_task_id === task?.id &&
      asset.metadata.source === "STORYBOARD_GENERATED",
  );
  const blockedStoryboards = storyboardAssets.filter((asset) =>
    ["NEEDS_REVIEW", "ERROR"].includes(
      String(asset.metadata.visual_audit_status ?? ""),
    ),
  );
  const videoAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.metadata.listing_task_id === task?.id &&
      asset.metadata.source === "STORYBOARD_VIDEO",
  );
  const subtitleAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.metadata.listing_task_id === task?.id &&
      asset.metadata.source === "STORYBOARD_SUBTITLE",
  );
  const backgroundMusicAssets = (assets.data ?? []).filter(
    (asset) =>
      asset.asset_type === "AUDIO" &&
      asset.metadata.asset_role === "BACKGROUND_MUSIC",
  );
  const renderJobs = useQuery({
    queryKey: ["ecommerce-video-render-jobs", task?.id],
    queryFn: () => listEcommerceVideoRenderJobs(task!.id),
    enabled: Boolean(task),
    refetchInterval: (query) => {
      const latest = query.state.data?.items[0];
      return latest &&
        (latest.status === "QUEUED" || latest.status === "RUNNING")
        ? 1_000
        : false;
    },
  });
  const latestRenderJob = renderJobs.data?.items[0];
  const syncedJobId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (
      !latestRenderJob ||
      latestRenderJob.status !== "SUCCEEDED" ||
      syncedJobId.current === latestRenderJob.id
    ) {
      return;
    }
    syncedJobId.current = latestRenderJob.id;
    void queryClient.invalidateQueries({
      queryKey: ["ecommerce-assets", task?.product_id],
    });
  }, [latestRenderJob, queryClient, task?.product_id]);
  useEffect(() => {
    if (!focusVideo || !task || !videoAssets.length) return;
    const timer = window.setTimeout(() => {
      document
        .getElementById(`storyboard-video-${task.id}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [focusVideo, task, videoAssets.length]);
  const storyboard = useMutation({
    mutationFn: () => generateEcommerceStoryboard(task!.id),
    onSuccess: async () => {
      message.success("短视频分镜图已生成");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", task?.product_id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-image-generations"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const renderVideo = useMutation({
    mutationFn: () =>
      createEcommerceVideoRenderJob(task!.id, {
        backgroundMusicAssetId,
        backgroundMusicVolume,
      }),
    onSuccess: async (job) => {
      message.success(
        `渲染任务已提交 · ${videoJobStatusLabels[job.status] ?? "已进入队列"}`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-video-render-jobs", task?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const retryRender = useMutation({
    mutationFn: (jobId: string) => retryEcommerceVideoRenderJob(jobId),
    onSuccess: async (job) => {
      message.success(
        `渲染任务已重新提交 · ${videoJobStatusLabels[job.status] ?? "已进入队列"}`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-video-render-jobs", task?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const acceptVisual = useMutation({
    mutationFn: (assetId: string) =>
      acceptEcommerceAssetVisualReview(assetId),
    onSuccess: async () => {
      message.success("已确认该分镜视觉可用");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", task?.product_id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const renderActive =
    latestRenderJob?.status === "QUEUED" ||
    latestRenderJob?.status === "RUNNING";
  const retry = useMutation({
    mutationFn: () => retryEcommerceListing(task!.id, task!.version),
    onSuccess: async () => {
      message.success("已重新提交发布");
      await onReviewed();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Drawer
      width={720}
      open={Boolean(task) || loading}
      onClose={onClose}
      title={task ? `上架任务 · ${task.product_name}` : "上架任务"}
      extra={
        task && (
          <Space>
            <Button
              size="small"
              loading={exportPackage.isPending}
              onClick={() => exportPackage.mutate()}
            >
              下载上架包
            </Button>
            <Button
              size="small"
              disabled={
                !["PENDING_REVIEW", "NEEDS_HUMAN", "REJECTED"].includes(
                  task.status,
                )
              }
              onClick={() => setEditOpen(true)}
            >
              编辑内容
            </Button>
            <Tag color={statusColor(task.status)}>
              {listingStatusLabels[task.status] ?? task.status}
            </Tag>
          </Space>
        )
      }
    >
      {loading && <Text type="secondary">正在加载…</Text>}
      {task && (
        <Space direction="vertical" size="large" className="page-stack">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="SKU">{task.sku}</Descriptions.Item>
            <Descriptions.Item label="渠道">
              {localizedLabel(channelLabels, task.channel)}
            </Descriptions.Item>
            <Descriptions.Item label="市场">
              {task.market_code} · {task.locale}
            </Descriptions.Item>
            <Descriptions.Item label="售价">
              {task.currency} {task.sale_price.toFixed(2)}
            </Descriptions.Item>
            <Descriptions.Item label="风险">{task.risk_level}</Descriptions.Item>
            <Descriptions.Item label="人工原因">
              {task.human_reason ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="外部编号" span={2}>
              {task.external_listing_id ?? "-"}
            </Descriptions.Item>
          </Descriptions>

          {task.human_reason && (
            <Alert
              type="warning"
              showIcon
              message="该任务需要人工确认"
              description={
                task.human_reason === "RESTRICTED_CLAIM"
                  ? `发现受限宣传用语：${task.compliance.restricted_claims?.join("、")}`
                  : task.human_reason === "MISSING_PRODUCT_IMAGE"
                    ? "商品尚未上传图片素材，不能直接提交发布。"
                    : task.human_reason === "VISUAL_REVIEW_REQUIRED"
                      ? `主图视觉审核未通过：${String(
                          task.compliance.primary_image_visual_audit_status ??
                            "",
                        )}`
                    : "缺少可用于审核的平台规则知识。"
              }
            />
          )}

          <Card size="small" title="商品标题">
            <Title level={4}>{task.content.title}</Title>
          </Card>
          <Card size="small" title="核心卖点">
            <Space direction="vertical">
              {task.content.selling_points?.map((point) => (
                <Text key={point}>• {point}</Text>
              ))}
            </Space>
          </Card>
          <Card size="small" title="详情描述">
            <Paragraph>{task.content.detail_description}</Paragraph>
          </Card>
          <Card
            size="small"
            title="短视频脚本"
            extra={
              <Space wrap>
                <Select
                  allowClear
                  size="small"
                  style={{ width: 150 }}
                  placeholder="无背景音乐"
                  value={backgroundMusicAssetId}
                  onChange={setBackgroundMusicAssetId}
                  options={backgroundMusicAssets.map((asset) => ({
                    value: asset.id,
                    label: asset.filename,
                  }))}
                />
                <InputNumber
                  size="small"
                  min={0}
                  max={1}
                  step={0.02}
                  value={backgroundMusicVolume}
                  onChange={(value) =>
                    setBackgroundMusicVolume(value ?? 0.18)
                  }
                  style={{ width: 72 }}
                  title="背景音乐音量"
                />
                <Button
                  size="small"
                  loading={storyboard.isPending}
                  disabled={storyboardAssets.length > 0}
                  onClick={() => storyboard.mutate()}
                >
                  {storyboardAssets.length ? "分镜已生成" : "生成分镜图"}
                </Button>
                <Button
                  size="small"
                  type="primary"
                  loading={renderVideo.isPending || retryRender.isPending}
                  disabled={
                    !storyboardAssets.length ||
                    renderActive ||
                    blockedStoryboards.length > 0
                  }
                  onClick={() => {
                    if (latestRenderJob?.status === "FAILED") {
                      retryRender.mutate(latestRenderJob.id);
                    } else {
                      renderVideo.mutate();
                    }
                  }}
                >
                  {latestRenderJob?.status === "QUEUED"
                    ? "等待渲染"
                    : latestRenderJob?.status === "RUNNING"
                      ? "正在渲染"
                      : latestRenderJob?.status === "FAILED"
                        ? "重试渲染"
                        : latestRenderJob?.status === "SUCCEEDED"
                          ? "重新生成预览"
                          : "生成竖屏预览"}
                </Button>
              </Space>
            }
          >
            <Space direction="vertical" className="page-stack">
              {task.content.short_video_script?.map((scene) => (
                <Card size="small" key={`${scene.second}-${scene.line}`}>
                  <Tag>{scene.second}s</Tag>
                  <Text strong>{scene.visual}</Text>
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    {scene.line}
                  </Paragraph>
                </Card>
              ))}
            </Space>
            {latestRenderJob && (
              <div style={{ marginTop: 16 }}>
                <Space wrap>
                  <Text strong>异步渲染任务</Text>
                  <Tag color={videoJobStatusColor(latestRenderJob.status)}>
                    {videoJobStatusLabels[latestRenderJob.status] ??
                      latestRenderJob.status}
                  </Tag>
                  <Text type="secondary">
                    {latestRenderJob.scene_count} 个场景 ·{" "}
                    {latestRenderJob.duration_seconds.toFixed(1)} 秒
                  </Text>
                </Space>
                {(latestRenderJob.status === "QUEUED" ||
                  latestRenderJob.status === "RUNNING") && (
                  <Progress
                    percent={latestRenderJob.progress}
                    status="active"
                    size="small"
                    style={{ marginTop: 8 }}
                  />
                )}
                {latestRenderJob.status === "FAILED" && (
                  <Alert
                    type="error"
                    showIcon
                    style={{ marginTop: 8 }}
                    message="视频渲染失败，可直接重试"
                    description={
                      latestRenderJob.error_message ?? "Worker 未返回详细原因"
                    }
                  />
                )}
              </div>
            )}
            {storyboardAssets.length > 0 && (
              <>
                {blockedStoryboards.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginTop: 16 }}
                    message={`${blockedStoryboards.length} 张分镜需要视觉确认`}
                    description="图片中存在文字、水印或视觉审核失败。请逐张确认可用，或重新生成分镜后再合成视频。"
                  />
                )}
                <div className="storyboard-grid">
                  {storyboardAssets
                    .sort(
                      (left, right) =>
                        Number(left.metadata.scene_index) -
                        Number(right.metadata.scene_index),
                    )
                    .map((asset) => (
                      <StoryboardAssetCard
                        asset={asset}
                        key={asset.id}
                        onAcceptVisual={() => acceptVisual.mutate(asset.id)}
                      />
                    ))}
                </div>
              </>
            )}
            {videoAssets.length > 0 && (
              <div
                id={`storyboard-video-${task.id}`}
                style={{ marginTop: 16 }}
              >
                <Text strong>竖屏预览视频</Text>
                {videoAssets.map((asset) => (
                  <StoryboardVideoCard
                    asset={asset}
                    subtitle={subtitleAssets.find(
                      (item) =>
                        item.id === asset.metadata.subtitle_asset_id,
                    )}
                    key={asset.id}
                  />
                ))}
              </div>
            )}
          </Card>
          <Card size="small" title="平台规则依据">
            <Space wrap>
              {task.citations.map((citation) => (
                <Tag key={`${citation.document_id}-${citation.version}`}>
                  《{citation.title}》v{citation.version}
                </Tag>
              ))}
              {!task.citations.length && <Text type="secondary">未检索到规则</Text>}
            </Space>
          </Card>
          {(task.status === "PENDING_REVIEW" || task.status === "NEEDS_HUMAN") && (
            <Space>
              <Button
                type="primary"
                loading={review.isPending}
                onClick={() => review.mutate("ACCEPTED")}
              >
                通过并发布
              </Button>
              <Button
                danger
                loading={review.isPending}
                onClick={() => review.mutate("REJECTED")}
              >
                退回
              </Button>
            </Space>
          )}
          {task.status === "FAILED" && (
            <Alert
              type="error"
              showIcon
              message="渠道发布失败"
              description={task.error_message ?? "请检查渠道配置后重试。"}
              action={
                <Button loading={retry.isPending} onClick={() => retry.mutate()}>
                  重新发布
                </Button>
              }
            />
          )}
          <EditListingContentModal
            open={editOpen}
            task={task}
            onClose={() => setEditOpen(false)}
            onSaved={async () => {
              await queryClient.invalidateQueries({
                queryKey: ["ecommerce-listing", task.id],
              });
              await queryClient.invalidateQueries({
                queryKey: ["ecommerce-listings"],
              });
              await queryClient.invalidateQueries({
                queryKey: ["ecommerce-metrics"],
              });
              setEditOpen(false);
            }}
          />
        </Space>
      )}
    </Drawer>
  );
}

function EditListingContentModal({
  open,
  task,
  onClose,
  onSaved,
}: {
  open: boolean;
  task: EcommerceListingDetail;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [sellingPoints, setSellingPoints] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  useEffect(() => {
    if (!open) return;
    setTitle(task.content.title ?? "");
    setSellingPoints((task.content.selling_points ?? []).join("\n"));
    setDescription(task.content.detail_description ?? "");
    setHashtags((task.content.hashtags ?? []).join("，"));
  }, [open, task]);
  const save = useMutation({
    mutationFn: () =>
      updateEcommerceListingContent(task.id, task.version, {
        title: title.trim(),
        sellingPoints: sellingPoints
          .split("\n")
          .map((point) => point.trim())
          .filter(Boolean),
        detailDescription: description.trim(),
        hashtags: hashtags
          .split(/[，,]/)
          .map((tag) => tag.trim())
          .filter(Boolean),
      }),
    onSuccess: async (updated) => {
      message.success(
        updated.status === "PENDING_REVIEW"
          ? "内容已保存并重新进入审核"
          : "内容已保存，仍需人工处理",
      );
      await onSaved();
    },
    onError: (error: Error) => message.error(error.message),
  });
  return (
    <Modal
      title="编辑上架内容"
      open={open}
      onCancel={onClose}
      okText="保存并重新检查"
      confirmLoading={save.isPending}
      okButtonProps={{
        disabled:
          !title.trim() ||
          !description.trim() ||
          !sellingPoints
            .split("\n")
            .map((point) => point.trim())
            .filter(Boolean).length,
      }}
      onOk={() => save.mutate()}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="保存后会重新执行受限宣传语检查，短视频脚本保持不变。"
      />
      <Form layout="vertical">
        <Form.Item label="商品标题" required>
          <Input
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="核心卖点（每行一条）" required>
          <TextArea
            autoSize={{ minRows: 4, maxRows: 8 }}
            value={sellingPoints}
            onChange={(event) => setSellingPoints(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="详情描述" required>
          <TextArea
            autoSize={{ minRows: 5, maxRows: 12 }}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="话题标签（逗号分隔）">
          <Input
            value={hashtags}
            onChange={(event) => setHashtags(event.target.value)}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}

function ProductAssetDrawer({
  product,
  employees,
  onClose,
}: {
  product: EcommerceProduct | null;
  employees: DigitalEmployee[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [generateOpen, setGenerateOpen] = useState(false);
  const [archiveTarget, setArchiveTarget] =
    useState<EcommerceProductAsset | null>(null);
  const [prompt, setPrompt] = useState(
    "奶油白色背景，柔和棚拍光，突出产品质感和核心卖点，简洁电商主图",
  );
  const assets = useQuery({
    queryKey: ["ecommerce-assets", product?.id],
    queryFn: () => listEcommerceProductAssets(product!.id),
    enabled: Boolean(product),
  });
  const upload = useMutation({
    mutationFn: (file: File) =>
      uploadEcommerceProductAsset(product!.id, file),
    onSuccess: async () => {
      message.success("商品素材已上传");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-image-generations"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const generate = useMutation({
    mutationFn: () =>
      generateEcommerceProductImage(product!.id, prompt),
    onSuccess: async () => {
      message.success("AI 商品主图已生成");
      setGenerateOpen(false);
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-image-generations"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const setPrimary = useMutation({
    mutationFn: (assetId: string) => setPrimaryEcommerceAsset(assetId),
    onSuccess: async () => {
      message.success("已设为商品主图");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const archive = useMutation({
    mutationFn: (assetId: string) => archiveEcommerceAsset(assetId),
    onSuccess: async () => {
      message.success("素材已归档");
      setArchiveTarget(null);
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const acceptVisual = useMutation({
    mutationFn: (assetId: string) =>
      acceptEcommerceAssetVisualReview(assetId),
    onSuccess: async () => {
      message.success("已确认图片视觉可用");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Drawer
      width={760}
      open={Boolean(product)}
      onClose={onClose}
      title={product ? `商品素材 · ${product.name}` : "商品素材"}
      extra={
        <Space>
          <Button onClick={() => setGenerateOpen(true)}>AI 生成主图</Button>
          <Upload
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm,video/quicktime,audio/wav,audio/mpeg,audio/mp3"
            showUploadList={false}
            beforeUpload={(file) => {
              upload.mutate(file);
              return Upload.LIST_IGNORE;
            }}
          >
            <Button type="primary" loading={upload.isPending}>
              上传素材
            </Button>
          </Upload>
        </Space>
      }
    >
      <Space direction="vertical" size="large" className="page-stack">
        <Alert
          type="info"
          showIcon
          message="素材统一存入对象存储"
          description="支持 JPG、PNG、WebP、MP4、WebM、MOV、WAV 和 MP3，单个文件不超过 100 MB。上传音频会作为背景音乐候选。"
        />
        {assets.isError && (
          <Alert
            type="error"
            showIcon
            message="素材加载失败"
            description={(assets.error as Error).message}
          />
        )}
        {assets.data?.length ? (
          <div className="asset-grid">
            {assets.data.map((asset) => (
              <AssetCard
                asset={asset}
                ownerName={
                  employees.find(
                    (employee) => employee.id === asset.owner_employee_id,
                  )?.name ?? "未分配数字员工"
                }
                key={asset.id}
                onPrimary={() => setPrimary.mutate(asset.id)}
                onAcceptVisual={() => acceptVisual.mutate(asset.id)}
                onArchive={() => setArchiveTarget(asset)}
              />
            ))}
          </div>
        ) : (
          <Text type="secondary">暂无素材，请上传商品主图、细节图或短视频。</Text>
        )}
      </Space>
      <Modal
        title="归档该素材？"
        open={Boolean(archiveTarget)}
        onCancel={() => setArchiveTarget(null)}
        onOk={() => {
          if (archiveTarget) archive.mutate(archiveTarget.id);
        }}
        okText="归档"
        cancelText="取消"
        confirmLoading={archive.isPending}
        okButtonProps={{ danger: true }}
      >
        <Text>
          归档后“{archiveTarget?.filename ?? "该素材"}”不再出现在当前素材列表，
          对象存储和审计记录仍会保留。
        </Text>
      </Modal>
      <Modal
        title="AI 生成商品主图"
        open={generateOpen}
        onCancel={() => setGenerateOpen(false)}
        okText="生成主图"
        confirmLoading={generate.isPending}
        okButtonProps={{ disabled: prompt.trim().length < 3 }}
        onOk={() => generate.mutate()}
      >
        <Alert
          type="info"
          showIcon
          message="主图会自动进行文字视觉审核"
          description="使用已配置的文生图模型生成，并通过千问 OCR 检查图中是否包含额外文字。审核异常的主图需要人工处理。"
          style={{ marginBottom: 16 }}
        />
        <TextArea
          autoSize={{ minRows: 5, maxRows: 8 }}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </Modal>
    </Drawer>
  );
}

function GenerateProductImageModal({
  product,
  onClose,
  onGenerated,
}: {
  product: EcommerceProduct | null;
  onClose: () => void;
  onGenerated: (product: EcommerceProduct) => void;
}) {
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState(
    "奶油白背景，柔和棚拍光，突出产品质感和核心卖点，简洁电商主图",
  );
  const [count, setCount] = useState<number | null>(3);
  const generate = useMutation({
    mutationFn: () =>
      generateEcommerceProductImages(product!.id, prompt, count ?? 1),
    onSuccess: async () => {
      message.success("AI 商品候选图已生成");
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-assets", product?.id],
      });
      await queryClient.invalidateQueries({
        queryKey: ["ecommerce-image-generations"],
      });
      if (product) onGenerated(product);
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Modal
      title={product ? `AI 生成主图 · ${product.name}` : "AI 生成主图"}
      open={Boolean(product)}
      onCancel={onClose}
      okText="生成主图"
      confirmLoading={generate.isPending}
      okButtonProps={{ disabled: prompt.trim().length < 3 }}
      onOk={() => generate.mutate()}
    >
      <Alert
        type="info"
        showIcon
        message="生成后自动进入商品素材库"
        description="未配置远程图片模型时使用本地演示生成器，生成成功后会自动打开素材预览。"
        style={{ marginBottom: 16 }}
      />
      <TextArea
        autoSize={{ minRows: 5, maxRows: 8 }}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
      />
      <Space style={{ marginTop: 12 }}>
        <Text>候选数量</Text>
        <InputNumber
          min={1}
          max={4}
          value={count}
          onChange={setCount}
        />
      </Space>
    </Modal>
  );
}

function AssetCard({
  asset,
  ownerName,
  onPrimary,
  onAcceptVisual,
  onArchive,
}: {
  asset: EcommerceProductAsset;
  ownerName: string;
  onPrimary: () => void;
  onAcceptVisual: () => void;
  onArchive: () => void;
}) {
  const objectUrl = useObjectUrl(asset.id);
  return (
    <Card size="small" title={asset.filename}>
      <div className="asset-preview">
        {!objectUrl && <Text type="secondary">正在加载预览…</Text>}
        {objectUrl && asset.asset_type === "IMAGE" && (
          <img src={objectUrl} alt={asset.filename} />
        )}
        {objectUrl && asset.asset_type === "VIDEO" && (
          <video src={objectUrl} controls />
        )}
        {objectUrl && asset.asset_type === "AUDIO" && (
          <audio src={objectUrl} controls />
        )}
      </div>
      <Space wrap style={{ marginTop: 12 }}>
        <Tag color="cyan">负责：{ownerName}</Tag>
        <Tag>{assetTypeLabels[asset.asset_type] ?? "素材"}</Tag>
        <Tag>{formatBytes(asset.size_bytes)}</Tag>
        <Tag color="green">
          {assetStatusLabels[asset.status] ?? "未知状态"}
        </Tag>
        {typeof asset.metadata.width === "number" &&
          typeof asset.metadata.height === "number" && (
            <Tag>
              {asset.metadata.width}×{asset.metadata.height}
            </Tag>
          )}
        {asset.metadata.is_primary === true && <Tag color="gold">主图</Tag>}
        {asset.metadata.asset_role === "BACKGROUND_MUSIC" && (
          <Tag color="purple">背景音乐</Tag>
        )}
        {typeof asset.metadata.quality_score === "number" && (
          <Tag>质量 {Math.round(asset.metadata.quality_score * 100)}</Tag>
        )}
        {asset.metadata.visual_audit_status === "PASS" && (
          <Tag color="green">视觉通过</Tag>
        )}
        {asset.metadata.visual_audit_status === "NEEDS_REVIEW" && (
          <Tag color="red">图中含文字</Tag>
        )}
        {asset.metadata.visual_audit_status === "ERROR" && (
          <Tag color="orange">视觉审核失败</Tag>
        )}
        {asset.metadata.visual_audit_status === "ACCEPTED" && (
          <Tag color="green">人工确认视觉</Tag>
        )}
      </Space>
      <Space style={{ marginTop: 10 }}>
        {asset.asset_type === "IMAGE" && asset.metadata.is_primary !== true && (
          <Button size="small" onClick={onPrimary}>
            设为主图
          </Button>
        )}
        {asset.asset_type === "IMAGE" &&
          ["NEEDS_REVIEW", "ERROR"].includes(
            String(asset.metadata.visual_audit_status ?? ""),
          ) && (
            <Button size="small" onClick={onAcceptVisual}>
              确认视觉可用
            </Button>
          )}
        <Button size="small" danger onClick={onArchive}>
          归档
        </Button>
      </Space>
    </Card>
  );
}

function StoryboardAssetCard({
  asset,
  onAcceptVisual,
}: {
  asset: EcommerceProductAsset;
  onAcceptVisual: () => void;
}) {
  const objectUrl = useObjectUrl(asset.id);
  return (
    <Card
      size="small"
      title={`分镜 ${String(asset.metadata.scene_index ?? "-")}`}
    >
      <div className="asset-preview">
        {objectUrl && <img src={objectUrl} alt={asset.filename} />}
      </div>
      <Space direction="vertical" size={2} style={{ marginTop: 10 }}>
        <Tag>{String(asset.metadata.scene_seconds ?? "")}</Tag>
        {asset.metadata.visual_audit_status === "PASS" && (
          <Tag color="green">视觉通过</Tag>
        )}
        {asset.metadata.visual_audit_status === "NEEDS_REVIEW" && (
          <Tag color="red">图中含文字</Tag>
        )}
        {asset.metadata.visual_audit_status === "ERROR" && (
          <Tag color="orange">视觉审核失败</Tag>
        )}
        {asset.metadata.visual_audit_status === "ACCEPTED" && (
          <Tag color="green">人工确认视觉</Tag>
        )}
        <Text strong>{String(asset.metadata.scene_visual ?? "")}</Text>
        <Text type="secondary">{String(asset.metadata.scene_line ?? "")}</Text>
        {["NEEDS_REVIEW", "ERROR"].includes(
          String(asset.metadata.visual_audit_status ?? ""),
        ) && (
          <Button size="small" onClick={onAcceptVisual}>
            确认视觉可用
          </Button>
        )}
      </Space>
    </Card>
  );
}

function StoryboardVideoCard({
  asset,
  subtitle,
}: {
  asset: EcommerceProductAsset;
  subtitle?: EcommerceProductAsset;
}) {
  const objectUrl = useObjectUrl(asset.id);
  const subtitleUrl = useObjectUrl(subtitle?.id);
  return (
    <Card size="small" title={asset.filename} style={{ marginTop: 10 }}>
      <div className="asset-preview storyboard-video">
        {objectUrl && (
          <video src={objectUrl} controls crossOrigin="anonymous">
            {subtitleUrl && (
              <track
                kind="subtitles"
                src={subtitleUrl}
                srcLang="zh-CN"
                label="中文"
                default
              />
            )}
          </video>
        )}
      </div>
      <Space wrap style={{ marginTop: 10 }}>
        <Tag>{formatBytes(asset.size_bytes)}</Tag>
        <Tag>{String(asset.metadata.resolution ?? "")}</Tag>
        <Tag>{String(asset.metadata.duration_seconds ?? "")} 秒</Tag>
        {asset.metadata.effect === "slow_zoom_with_fade" && (
          <Tag color="purple">缓慢推近 · 淡入淡出</Tag>
        )}
        {subtitle && (
          <Tag color="cyan">
            字幕 {String(subtitle.metadata.cue_count ?? "")} 条
          </Tag>
        )}
        {asset.metadata.voiceover_status === "SUCCEEDED" && (
          <Tag color="blue">
            配音 {String(asset.metadata.voiceover_voice ?? "")}
          </Tag>
        )}
        {asset.metadata.audio_mix === "voiceover_with_ducking" && (
          <Tag color="purple">BGM 自动闪避</Tag>
        )}
        {asset.metadata.background_music_volume !== undefined && (
          <Tag>
            BGM {Math.round(Number(asset.metadata.background_music_volume) * 100)}%
          </Tag>
        )}
      </Space>
    </Card>
  );
}

function useObjectUrl(assetId: string | undefined) {
  const blob = useQuery({
    queryKey: ["ecommerce-asset-blob", assetId],
    queryFn: () => fetchEcommerceAssetBlob(assetId!),
    enabled: Boolean(assetId),
    staleTime: 60_000,
  });
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    if (!blob.data) return;
    const next = URL.createObjectURL(blob.data);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob.data]);
  return url;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(value?: number | null): string {
  if (value === null || value === undefined) return "-";
  if (value < 60) return `${value.toFixed(1)} 秒`;
  if (value < 3600) return `${(value / 60).toFixed(1)} 分钟`;
  return `${(value / 3600).toFixed(1)} 小时`;
}
