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

import { createAgentSkill, listAgentSkills, updateAgentSkill } from "../../api";
import { message } from "../../feedback";
import type { AgentSkill } from "../../types";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

export function AgentSkillsCard() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AgentSkill | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [triggers, setTriggers] = useState("");
  const [tools, setTools] = useState("");
  const [definition, setDefinition] = useState("");
  const [status, setStatus] = useState("ACTIVE");
  const skills = useQuery({
    queryKey: ["agent-skills"],
    queryFn: listAgentSkills,
  });
  const definitionError = (() => {
    if (!definition.trim()) {
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(definition);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed)
      ) {
        return "执行契约必须是 JSON 对象";
      }
      return null;
    } catch (error) {
      return `JSON 解析失败：${(error as Error).message}`;
    }
  })();
  const save = useMutation({
    mutationFn: () => {
      let parsedDefinition: Record<string, unknown> | undefined;
      if (definition.trim()) {
        const parsed = JSON.parse(definition) as Record<string, unknown>;
        // Only send the contract when it actually changed; otherwise every
        // name edit would bump the contract version.
        const original = editing?.definition
          ? JSON.stringify(editing.definition)
          : null;
        if (JSON.stringify(parsed) !== original) {
          parsedDefinition = parsed;
        }
      }
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
        ? updateAgentSkill(editing.id, {
            ...input,
            expected_version: editing.version,
            ...(parsedDefinition
              ? { definition: parsedDefinition }
              : {}),
          })
        : createAgentSkill({
            code: code.trim(),
            ...input,
            ...(parsedDefinition
              ? { definition: parsedDefinition }
              : {}),
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
    setDefinition(
      skill?.definition
        ? JSON.stringify(skill.definition, null, 2)
        : "",
    );
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
            title: "契约",
            width: 130,
            render: (_, skill) =>
              skill.definition ? (
                <Tag color="blue">v{skill.definition_version} 结构化</Tag>
              ) : (
                <Tag>宽松模式</Tag>
              ),
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
            (!editing && !code.trim()) ||
            definitionError !== null,
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
          <Form.Item
            label="执行契约（JSON，可选）"
            extra="结构化步骤与完成条件；留空为宽松模式，运行时不会断言步骤完成。示例：{&quot;schema_version&quot;: 1, &quot;steps&quot;: [{&quot;id&quot;: &quot;identify_order&quot;, &quot;name&quot;: &quot;确认订单&quot;, &quot;required&quot;: true, &quot;evidence&quot;: [&quot;slot:order_id&quot;], &quot;completion&quot;: &quot;order_id != null&quot;}]}"
            validateStatus={definitionError ? "error" : undefined}
            help={definitionError ?? undefined}
          >
            <TextArea
              rows={8}
              value={definition}
              onChange={(event) => setDefinition(event.target.value)}
              placeholder='{"schema_version": 1, "steps": []}'
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
