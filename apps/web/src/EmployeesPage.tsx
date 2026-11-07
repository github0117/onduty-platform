import { Alert, Button, Card, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  activateDigitalEmployee,
  listBusinessServiceEntries,
  listDigitalEmployeeTemplates,
  listDigitalEmployees,
} from "./api";
import EmployeeProfileDrawer from "./EmployeeProfileDrawer";
import ExternalConnectorsCard from "./ExternalConnectorsCard";
import { domainLabels, employeeReadiness, workflowLabels } from "./employeeLabels";
import { AgentSkillsCard } from "./features/employees/AgentSkillsCard";
import { CreateEmployeeModal } from "./features/employees/CreateEmployeeModal";
import { EmployeeDraftsCard } from "./features/employees/EmployeeDraftsCard";
import {
  EmployeeConfigDrawer,
  ManagedTemplatesCard,
  TemplateEmployeeModal,
} from "./features/employees/ManagedTemplatesCard";
import { McpConnectorsCard } from "./features/employees/McpConnectorsCard";
import {
  DigitalEmployeeRoutingCard,
  RouteEvaluationCard,
} from "./features/employees/routing";
import { employeeSectionMeta } from "./features/employees/shared";
import { SupervisorTaskCard } from "./features/employees/SupervisorTaskCard";
import { message } from "./feedback";
import type { EmployeeSection } from "./features/employees/shared";
import type { DigitalEmployee } from "./types";

const { Paragraph, Text, Title } = Typography;

export type { EmployeeSection };

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
  const [profileEmployee, setProfileEmployee] =
    useState<DigitalEmployee | null>(null);
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: ["roster", "routing", "route-evaluation", "drafts"].includes(
      section,
    ),
  });
  const businessEntries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
    enabled: ["roster", "routing", "route-evaluation"].includes(section),
  });
  const templates = useQuery({
    queryKey: ["digital-employee-templates"],
    queryFn: listDigitalEmployeeTemplates,
    enabled: ["roster", "templates"].includes(section),
  });

  useEffect(() => {
    const employeeId = new URLSearchParams(
      window.location.search,
    ).get("employee");
    if (!employeeId || !employees.data) return;
    const linked = employees.data.find(
      (employee) => employee.id === employeeId,
    );
    if (linked) setProfileEmployee(linked);
  }, [employees.data]);

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
      width: 170,
      render: (value: string, employee) => (
        <Space direction="vertical" size={0}>
          <Button
            type="link"
            className="employee-profile-link"
            onClick={() => setProfileEmployee(employee)}
          >
            {value}
          </Button>
          <Text type="secondary">{employee.employee_key}</Text>
        </Space>
      ),
    },
    {
      title: "服务入口",
      dataIndex: "id",
      width: 210,
      render: (_value: string, employee) => {
        if (businessEntries.isLoading) {
          return <Text type="secondary">加载中</Text>;
        }
        const employeeEntries = (businessEntries.data ?? []).filter(
          (entry) =>
            entry.employees.some(
              (item) =>
                item.employee_id === employee.id && item.enabled,
            ),
        );
        if (employeeEntries.length === 0) {
          return <Text type="secondary">未加入入口</Text>;
        }
        return (
          <Space direction="vertical" size={2}>
            <Space wrap size={4}>
              {employeeEntries.map((entry) => (
                <Tag
                  key={entry.id}
                  color={employeeEntries.length > 1 ? "gold" : "default"}
                >
                  {entry.name}
                </Tag>
              ))}
            </Space>
            {employeeEntries.length > 1 && (
              <Text type="secondary">跨入口复用</Text>
            )}
          </Space>
        );
      },
    },
    {
      title: "岗位",
      dataIndex: "template_code",
      width: 150,
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
      width: 90,
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
      width: 210,
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
            width: 90,
          },
        ]
      : []),
    {
      title: "操作",
      width: 170,
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
      {section === "integrations" && (
        <>
          <ExternalConnectorsCard />
          <McpConnectorsCard />
        </>
      )}
      {section === "routing" && (
        <DigitalEmployeeRoutingCard
          employees={employees.data ?? []}
          onNavigate={onNavigate}
        />
      )}
      {section === "route-evaluation" && (
        <RouteEvaluationCard
          employees={employees.data ?? []}
          entries={businessEntries.data ?? []}
        />
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
      <EmployeeProfileDrawer
        employee={profileEmployee}
        open={Boolean(profileEmployee)}
        onClose={() => setProfileEmployee(null)}
      />
    </Space>
  );
}