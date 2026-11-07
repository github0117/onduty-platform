import {
  Alert,
  Button,
  Card,
  Input,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
} from "antd";

import {
  gateDecisionLabels,
  gateReasonLabel,
  localizedLabel,
  providerLabels,
} from "../../../statusLabels";
import type { CustomerServiceSurfaceMode } from "../model";
import type { useReplyMutations } from "../useReplyMutations";
import type { useTicketMutations } from "../useTicketMutations";

const { Text } = Typography;
const { TextArea } = Input;

interface ManualWorkAreaPanelProps {
  viewMode: CustomerServiceSurfaceMode;
  manualStep: number;
  ticketCompleted: boolean;
  assignedAgentId: string | null | undefined;
  currentAgentId: string;
  assignment: ReturnType<typeof useTicketMutations>["assignment"];
  replySuggestion: ReturnType<typeof useReplyMutations>["replySuggestion"];
  autoSuggestionError: string;
  setViewMode: (value: CustomerServiceSurfaceMode) => void;
  optimizationStyle: "professional" | "concise" | "empathetic";
  setOptimizationStyle: (
    value: "professional" | "concise" | "empathetic",
  ) => void;
  optimizeReply: ReturnType<typeof useReplyMutations>["optimizeReply"];
  manualReplyText: string;
  setManualReplyText: (value: string) => void;
  manualReply: ReturnType<typeof useReplyMutations>["manualReply"];
  capacityReached: boolean;
  currentAgentCapacity: number;
  currentAgentLoad: number;
  cannotTakeOver: boolean;
  assignedToAnotherAgent: boolean;
}

export function ManualWorkAreaPanel({
  viewMode,
  manualStep,
  ticketCompleted,
  assignedAgentId,
  currentAgentId,
  assignment,
  replySuggestion,
  autoSuggestionError,
  setViewMode,
  optimizationStyle,
  setOptimizationStyle,
  optimizeReply,
  manualReplyText,
  setManualReplyText,
  manualReply,
  capacityReached,
  currentAgentCapacity,
  currentAgentLoad,
  cannotTakeOver,
  assignedToAnotherAgent,
}: ManualWorkAreaPanelProps) {
  return (
    <Card size="small" title="你的处理区" style={{ marginTop: 16 }}>
      <Steps
        size="small"
        current={manualStep}
        items={[
          { title: "选择会话" },
          { title: "接管会话" },
          { title: "人工回复" },
          { title: "标记解决" },
        ]}
      />
      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        message="人工回复写入当前沙盒会话"
        description="回复只记录为演示环境的人工客服消息；企业消息渠道与外部业务系统消息渠道尚未连接生产系统，不会发送给真实用户、员工或业务系统。"
      />
      {ticketCompleted ? (
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%", marginTop: 12 }}
        >
          <Alert
            type="success"
            showIcon
            message="当前工单已解决，无需继续人工处理"
          />
          {assignedAgentId === currentAgentId && (
            <Button
              loading={assignment.isPending}
              onClick={() => assignment.mutate("release")}
            >
              释放会话并腾出名额
            </Button>
          )}
        </Space>
      ) : assignedToAnotherAgent ? (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message={`该会话已由 ${assignedAgentId ?? "其他客服"} 接管`}
          description="不能重复接管；请选择其他待处理会话，或由当前负责人释放后再操作。"
        />
      ) : assignedAgentId === currentAgentId ? (
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%", marginTop: 12 }}
        >
          <Space wrap>
            <Button
              loading={replySuggestion.isPending}
              onClick={() =>
                replySuggestion.mutate({ silent: false })
              }
            >
              重新生成 AI 草稿
            </Button>
            <Tag color={replySuggestion.data ? "green" : "blue"}>
              {replySuggestion.isPending
                ? "AI 正在自动生成"
                : replySuggestion.data
                  ? "已自动生成，等待人工确认"
                  : "选中会话后自动生成"}
            </Tag>
          </Space>
          {replySuggestion.isPending && !replySuggestion.data && (
            <Alert
              type="info"
              showIcon
              message="正在根据买家问题、知识库和最近会话生成回复草稿…"
            />
          )}
          {autoSuggestionError && !replySuggestion.isPending && (
            <Alert
              type="warning"
              showIcon
              message="AI 草稿自动生成失败"
              description={`${autoSuggestionError}；可以点击“重新生成 AI 草稿”再试。`}
            />
          )}
          {replySuggestion.data && (
            <Alert
              type={replySuggestion.data.fallback_used ? "warning" : "success"}
              showIcon
              message={
                replySuggestion.data.fallback_used
                  ? "模型调用失败，已使用本地规则建议"
                  : `${localizedLabel(
                      providerLabels,
                      replySuggestion.data.provider,
                      "大模型",
                    )} · ${replySuggestion.data.model} · Skill ${
                      replySuggestion.data.skill
                    }`
              }
              description={
                <Space direction="vertical" size={2}>
                  {replySuggestion.data.gate && (
                    <Text
                      type={
                        replySuggestion.data.gate.decision === "AUTO_SEND"
                          ? "success"
                          : "warning"
                      }
                    >
                      发送门禁：
                      {localizedLabel(
                        gateDecisionLabels,
                        replySuggestion.data.gate.decision,
                        replySuggestion.data.gate.decision,
                      )}
                      {replySuggestion.data.gate.reasons.length > 0
                        ? `（${replySuggestion.data.gate.reasons
                            .map(gateReasonLabel)
                            .join("；")}）`
                        : "（证据与 Skill 校验均通过）"}
                    </Text>
                  )}
                  <Text>
                    {replySuggestion.data.citations.length > 0
                      ? `知识依据：${replySuggestion.data.citations
                          .map((citation) => citation.title)
                          .join("、")}`
                      : "本次建议没有知识引用，请谨慎使用。"}
                  </Text>
                  <Text type="secondary">
                    LangGraph：{replySuggestion.data.trace.join(" → ")}
                  </Text>
                  {replySuggestion.data.tool_calls.length > 0 && (
                    <Text type="secondary">
                      MCP 工具：
                      {replySuggestion.data.tool_calls
                        .map(
                          (call) =>
                            `${call.tool_id}（${call.status}，${call.duration_ms}ms${
                              call.approval_id
                                ? `，审批单 ${call.approval_id.slice(0, 8)}${
                                    call.approval_required_role === "admin"
                                      ? "（需管理员）"
                                      : ""
                                  }`
                                : ""
                            }）`,
                        )
                        .join("；")}
                    </Text>
                  )}
                  {replySuggestion.data.tool_calls.some(
                    (call) =>
                      call.status === "APPROVAL_REQUIRED" &&
                      call.approval_id,
                  ) && (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => setViewMode("admin")}
                    >
                      打开审批中心
                    </Button>
                  )}
                </Space>
              }
            />
          )}
          <Space wrap>
            <Select
              value={optimizationStyle}
              onChange={setOptimizationStyle}
              style={{ width: 130 }}
              options={[
                { value: "professional", label: "更专业" },
                { value: "concise", label: "更简洁" },
                { value: "empathetic", label: "更亲和" },
              ]}
            />
            <Button
              loading={optimizeReply.isPending}
              disabled={!manualReplyText.trim()}
              onClick={() => optimizeReply.mutate()}
            >
              2. 按需优化草稿
            </Button>
            <Text type="secondary">
              只改写现有内容，不新增时效、金额或承诺
            </Text>
          </Space>
          {optimizeReply.data && (
            <Alert
              type="success"
              showIcon
              message={`AI 优化完成 · ${optimizeReply.data.model}`}
              description="优化结果已回填到编辑框，请核对事实后发送。"
            />
          )}
          <Text strong>人工确认与编辑</Text>
          <TextArea
            rows={4}
            value={manualReplyText}
            onChange={(event) => setManualReplyText(event.target.value)}
            placeholder="例如：您好，我已经核实订单，正在为您登记退款申请……"
          />
          <Space wrap>
            <Button
              type="primary"
              loading={manualReply.isPending}
              disabled={!manualReplyText.trim()}
              onClick={() => manualReply.mutate(true)}
            >
              3. 发送并标记解决
            </Button>
            <Button
              loading={manualReply.isPending}
              disabled={!manualReplyText.trim()}
              onClick={() => manualReply.mutate(false)}
            >
              仅发送，不关闭
            </Button>
            {String(viewMode) !== "guide" && (
              <Button
                loading={assignment.isPending}
                onClick={() => assignment.mutate("release")}
              >
                释放会话
              </Button>
            )}
          </Space>
        </Space>
      ) : (
        <Space
          direction="vertical"
          size="middle"
          style={{ width: "100%", marginTop: 12 }}
        >
          <Text type="secondary">
            AI 已自动准备回复草稿；接管会话后即可修改和发送。
          </Text>
          {replySuggestion.isPending && (
            <Alert
              type="info"
              showIcon
              message="AI 正在自动生成回复草稿…"
            />
          )}
          {replySuggestion.data && (
            <Alert
              type="success"
              showIcon
              message="AI 已预生成回复草稿"
              description={replySuggestion.data.text}
            />
          )}
          {autoSuggestionError && !replySuggestion.isPending && (
            <Alert
              type="warning"
              showIcon
              message="AI 草稿生成失败"
              description={autoSuggestionError}
            />
          )}
          <Space wrap>
            <Button
              type="primary"
              loading={assignment.isPending}
              disabled={
                !currentAgentId ||
                assignedToAnotherAgent ||
                cannotTakeOver
              }
              onClick={() => assignment.mutate("takeover")}
            >
              {capacityReached
                ? `已达 ${currentAgentCapacity} 个会话上限`
                : "接管并开始处理"}
            </Button>
            <Text type="secondary">
              当前负责 {currentAgentLoad} / {currentAgentCapacity} 个活动会话
            </Text>
          </Space>
          {capacityReached && (
            <Alert
              type="warning"
              showIcon
              message="当前客服已满载"
              description="请先打开一个由自己负责的会话并点击“释放会话”，再接管新会话。"
            />
          )}
        </Space>
      )}
    </Card>
  );
}
