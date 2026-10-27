import {
  Alert,
  Button,
  Card,
  Drawer,
  Select,
  Space,
  Steps,
  Typography,
} from "antd";

import {
  isTestIdentityMode,
  switchTestIdentity,
  testBusinessUnits,
  testIdentityProfiles,
  useAuth,
} from "./auth";
import {
  demoPerspectiveIds,
  demoPerspectiveLabels,
} from "./demoPerspectives";

const { Paragraph, Text } = Typography;

const demoGuideSteps: {
  title: string;
  description: string;
  path?: string;
}[] = [
  {
    title: "看清技术主线",
    description:
      "企业服务台 Agent 的链路：统一入口 → 按问题自动选择数字员工 → 加载该员工的 Skill、知识空间和 MCP 授权 → LangGraph 执行 → ToolCall 与 Trace 留痕。研发文档只是其中一条可核验的公开 MCP 链路。这一步不需要跳转，直接进入下一步检查员工上岗状态。",
  },
  {
    title: "检查员工上岗状态",
    description:
      "在员工名单中找到“研发支持数字员工”或“HR 入职资料数字员工”，点击姓名打开能力快照，查看上岗检查、Skill、知识、MCP 和所在业务入口。HR 员工同时服务企业服务台和内部 HR 入口，快照会标出跨入口复用。也可以在地址后加 ?employee=<员工 ID> 直接分享这名员工的快照。",
    path: "/employees/roster",
  },
  {
    title: "查看真实 MCP 工具",
    description:
      "打开 DeepWiki 连接器，确认已经发现 3 个只读工具，并查看员工授权范围。",
    path: "/employees/integrations",
  },
  {
    title: "运行企业服务台 Agent",
    description:
      "进入企业服务台，依次试“仓库文档”“入职材料”“账号被锁”，观察同一入口按问题自动分派到不同数字员工。回复后点击对话窗口标题里的员工姓名，可以直接打开这名员工在平台里的配置快照，看到对话与平台配置使用的是同一名数字员工。",
    path: "/customer-service?scenario=enterprise",
  },
  {
    title: "查看执行证据",
    description:
      "在运行与审计中查看 ToolCall、耗时、状态、Trace、引用和生产边界。",
    path: "/operations",
  },
];

export default function DemoGuideDrawer({
  step,
  onStepChange,
  onClose,
  onNavigate,
}: {
  step: number;
  onStepChange: (step: number) => void;
  onClose: () => void;
  onNavigate: (target: string) => void;
}) {
  const { testIdentity, activeBusinessUnitId, switchBusinessUnit } = useAuth();
  const currentStep = demoGuideSteps[step];
  const goToStep = (index: number) => {
    const target = demoGuideSteps[index]?.path;
    if (!target) return;
    onNavigate(target);
    onClose();
  };

  return (
    <Drawer
      title="企业服务台 Agent · 5 步技术演示"
      placement="right"
      width={520}
      open
      onClose={onClose}
    >
      {isTestIdentityMode() && (
        <>
          <Card size="small" title="演示视角" style={{ marginBottom: 16 }}>
            <Space
              direction="vertical"
              size="middle"
              style={{ width: "100%" }}
            >
              <Alert
                type="info"
                showIcon
                message="不同视角用于展示权限边界"
                description="业务执行者处理任务，管理者查看指标并审批，平台管理员配置员工与资源。真实环境不显示此切换，身份由登录系统决定。"
              />
              <Select
                aria-label="切换演示视角"
                value={testIdentity?.id}
                style={{ width: "100%" }}
                options={testIdentityProfiles
                  .filter((profile) =>
                    demoPerspectiveIds.includes(
                      profile.id as (typeof demoPerspectiveIds)[number],
                    ),
                  )
                  .map((profile) => ({
                    value: profile.id,
                    label: `${demoPerspectiveLabels[profile.id]} · ${profile.description}`,
                  }))}
                onChange={(value) => {
                  const landing = switchTestIdentity(value);
                  window.location.assign(landing);
                }}
              />
            </Space>
          </Card>
          <Card size="small" title="演示业务单元" style={{ marginBottom: 16 }}>
            <Space
              direction="vertical"
              size="middle"
              style={{ width: "100%" }}
            >
              <Alert
                type="warning"
                showIcon
                message="这里只切换演示数据所在的业务单元"
                description="正式环境由登录身份和所属业务单元自动确定。"
              />
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <Text strong>业务单元</Text>
                <Select
                  aria-label="切换业务单元"
                  value={activeBusinessUnitId}
                  style={{ width: "100%" }}
                  options={testBusinessUnits}
                  onChange={(value) => {
                    switchBusinessUnit(value).catch(() => undefined);
                  }}
                />
              </Space>
            </Space>
          </Card>
        </>
      )}
      <Alert
        type="info"
        showIcon
        message="只需要完成企业服务台这一条主链"
        description="按顺序检查员工、真实 MCP、多渠道自动分派和 Trace。对话窗口标题会显示本次由哪名数字员工处理，点击姓名即可核对它的 Skill、知识、MCP 和业务入口；HR 员工同时服务企业服务台和内部 HR 入口，可以在“业务入口与分派”页看到跨入口复用标记。电商与内容生产是另一组复用案例，不需要现场逐个演示。"
      />
      <Steps
        className="demo-guide-steps"
        direction="vertical"
        current={step}
        items={demoGuideSteps.map((step) => ({
          title: step.title,
          description: step.description,
        }))}
      />
      <Card size="small" title={currentStep.title}>
        <Paragraph type="secondary">{currentStep.description}</Paragraph>
        <Space wrap>
          {currentStep.path ? (
            <Button type="primary" onClick={() => goToStep(step)}>
              前往本步骤
            </Button>
          ) : (
            step < demoGuideSteps.length - 1 && (
              <Button
                type="primary"
                onClick={() => {
                  onStepChange(step + 1);
                  goToStep(step + 1);
                }}
              >
                直接进入下一步
              </Button>
            )
          )}
          {currentStep.path && step < demoGuideSteps.length - 1 && (
            <Button
              onClick={() => {
                onStepChange(step + 1);
                goToStep(step + 1);
              }}
            >
              直接进入下一步
            </Button>
          )}
        </Space>
      </Card>
    </Drawer>
  );
}
