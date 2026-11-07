import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  generateCustomerReplySuggestion,
  optimizeCustomerReply,
  queryLogistics,
  sendManualCustomerReply,
  ApiError,
} from "../../api";
import { message } from "../../feedback";

export interface UseReplyMutationsOptions {
  conversationId: string;
  conversationAssignedAgentId: string | null | undefined;
  currentAgentId: string;
  manualReplyText: string;
  ticketId: string;
  logisticsOrderId: string;
  trackingNumber: string;
  carrierCode: string;
  optimizationStyle: "professional" | "concise" | "empathetic";
  onManualReplySent: () => void;
  onSuggestionLoaded: (text: string) => void;
  onSuggestionFailed: (errorMessage: string) => void;
  onReplyOptimized: (text: string) => void;
}

export function useReplyMutations({
  conversationId,
  conversationAssignedAgentId,
  currentAgentId,
  manualReplyText,
  ticketId,
  logisticsOrderId,
  trackingNumber,
  carrierCode,
  optimizationStyle,
  onManualReplySent,
  onSuggestionLoaded,
  onSuggestionFailed,
  onReplyOptimized,
}: UseReplyMutationsOptions) {
  const queryClient = useQueryClient();

  const manualReply = useMutation({
    mutationFn: (resolve: boolean) => {
      if (!conversationId) throw new Error("请先选择一个会话");
      if (conversationAssignedAgentId !== currentAgentId) {
        throw new Error("请先接管会话，再进行人工回复");
      }
      if (!manualReplyText.trim()) {
        throw new Error("请输入人工回复内容");
      }
      return sendManualCustomerReply(
        conversationId,
        manualReplyText.trim(),
        resolve,
      );
    },
    onSuccess: (_conversation, resolve) => {
      onManualReplySent();
      message.success(resolve ? "回复已发送，会话已解决" : "人工回复已发送");
    },
    onError: (error: Error) => message.error(error.message),
    onSettled: () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ticket", ticketId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-conversations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-assignment-queue"],
        }),
      ]);
    },
  });
  const logistics = useMutation({
    mutationFn: () => {
      if (!logisticsOrderId.trim() && !trackingNumber.trim()) {
        throw new Error("请输入订单号或运单号");
      }
      return queryLogistics({
        orderId: logisticsOrderId.trim(),
        trackingNumber: trackingNumber.trim(),
        carrierCode: carrierCode.trim(),
      });
    },
    onError: (error: Error) => {
      if (
        error instanceof ApiError &&
        error.code === "LOGISTICS_PROVIDER_NOT_CONFIGURED"
      ) {
        message.warning("物流查询接口尚未配置，系统不会生成虚假物流状态。");
        return;
      }
      message.error(error.message);
    },
  });
  const replySuggestion = useMutation({
    mutationFn: (_options?: { silent?: boolean }) => {
      if (!conversationId) throw new Error("请先选择一个会话");
      return generateCustomerReplySuggestion(conversationId);
    },
    onSuccess: (suggestion, options) => {
      onSuggestionLoaded(suggestion.text);
      if (!options?.silent) {
        message.success(
          suggestion.fallback_used
            ? "已重新生成建议，但模型调用失败，当前为本地规则建议"
            : "AI 回复草稿已重新生成，请确认后发送",
        );
      }
    },
    onError: (error: Error, options) => {
      onSuggestionFailed(error.message);
      if (!options?.silent) {
        message.error(error.message);
      }
    },
  });
  const optimizeReply = useMutation({
    mutationFn: () => {
      if (!conversationId) throw new Error("请先选择一个会话");
      if (!manualReplyText.trim()) throw new Error("请先输入或生成回复内容");
      return optimizeCustomerReply(
        conversationId,
        manualReplyText.trim(),
        optimizationStyle,
      );
    },
    onSuccess: (result) => {
      onReplyOptimized(result.text);
      message.success("AI 已优化当前回复，请确认后再发送");
    },
    onError: (error: Error) => message.error(error.message),
  });

  return {
    manualReply,
    logistics,
    replySuggestion,
    optimizeReply,
  };
}
