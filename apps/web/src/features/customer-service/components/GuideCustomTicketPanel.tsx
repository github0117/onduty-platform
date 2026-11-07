import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";

import type { useTicketMutations } from "../useTicketMutations";

const { Text } = Typography;
const { TextArea } = Input;

interface GuideCustomTicketPanelProps {
  subject: string;
  setSubject: (value: string) => void;
  body: string;
  setBody: (value: string) => void;
  createTicket: ReturnType<typeof useTicketMutations>["createTicket"];
  displayedMessages: { role: "BUYER" | "ASSISTANT"; text: string }[];
}

export function GuideCustomTicketPanel({
  subject,
  setSubject,
  body,
  setBody,
  createTicket,
  displayedMessages,
}: GuideCustomTicketPanelProps) {
  return (
    <Card
      className="section-card"
      title="或自定义一个测试问题"
      extra={
        <Text type="secondary">
          提交后自动跳到当前会话
        </Text>
      }
    >
      <Form layout="vertical">
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="新手模式已使用默认数字员工和当前业务场景"
          description="只填写问题和内容即可。需要切换员工或业务场景时，进入“日常会话”或“运营看板”。"
        />
        <Form.Item label="问题标题">
          <Input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
        </Form.Item>
        <Form.Item label="问题内容">
          <TextArea
            rows={4}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </Form.Item>
        <Space wrap>
          <Button
            type="primary"
            loading={createTicket.isPending}
            disabled={!subject.trim() || !body.trim()}
            onClick={() =>
              createTicket.mutate({
                subject,
                body,
                autoRoute: true,
              })
            }
          >
            {displayedMessages.length ? "继续提问" : "提交给数字员工"}
          </Button>
        </Space>
      </Form>
    </Card>
  );
}
