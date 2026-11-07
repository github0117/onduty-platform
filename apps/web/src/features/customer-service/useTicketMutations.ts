import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  acknowledgeCustomerServiceNotification,
  addCustomerConversationMessage,
  autoAssignCustomerConversations,
  createCustomerConversation,
  createKnowledgeFeedback,
  releaseCustomerConversation,
  reviewTicket,
  takeOverCustomerConversation,
  ApiError,
} from "../../api";
import { message } from "../../feedback";
import type {
  AssignmentRunResult,
  CustomerConversation,
  EcommerceProduct,
  KnowledgeSpace,
  TicketDetail,
} from "../../types";
import type { CustomerDemoScenario } from "./model";

export interface CreateTicketInput {
  subject: string;
  body: string;
  newConversation?: boolean;
  autoRoute?: boolean;
}

export interface UseTicketMutationsOptions {
  conversationId: string;
  conversationDetail: CustomerConversation | undefined;
  employeeId: string;
  demoScenario: CustomerDemoScenario;
  categoryProfileId: string;
  categoryProfileName: string | undefined;
  productId: string;
  categoryProducts: EcommerceProduct[];
  ticketId: string;
  ticketDetail: TicketDetail | undefined;
  feedbackSpace: KnowledgeSpace | null;
  currentAgentCapacity: number;
  onConversationCreated: (
    conversation: CustomerConversation,
    input: CreateTicketInput,
  ) => void;
  onReviewAnswer: (answer: string) => void;
  onAssignmentResult: (result: AssignmentRunResult) => void;
  onTakeOver: () => void;
}

export function useTicketMutations({
  conversationId,
  conversationDetail,
  employeeId,
  demoScenario,
  categoryProfileId,
  categoryProfileName,
  productId,
  categoryProducts,
  ticketId,
  ticketDetail,
  feedbackSpace,
  currentAgentCapacity,
  onConversationCreated,
  onReviewAnswer,
  onAssignmentResult,
  onTakeOver,
}: UseTicketMutationsOptions) {
  const queryClient = useQueryClient();

  const createTicket = useMutation({
    mutationFn: async (input: CreateTicketInput) => {
      const conversation = conversationId && !input.newConversation
        ? { id: conversationId }
        : await createCustomerConversation({
            employeeId: input.autoRoute ? undefined : employeeId,
            category:
              demoScenario === "ecommerce" && categoryProfileId
                ? {
                    name: categoryProfileName ?? "通用商品",
                    profileId: categoryProfileId,
                  }
                : undefined,
            scenario: demoScenario,
          });
      const updated = await addCustomerConversationMessage(conversation.id, {
        content: `${input.subject}\n${input.body}`,
        productId:
          demoScenario === "ecommerce"
            ? categoryProducts.find((product) => product.id === productId)?.id
            : undefined,
        sku:
          demoScenario === "ecommerce"
            ? categoryProducts.find((product) => product.id === productId)?.sku
            : undefined,
      });
      return updated;
    },
    onSuccess: (conversation, input) => {
      onConversationCreated(conversation, input);
      queryClient.invalidateQueries({ queryKey: ["customer-conversations"] });
      queryClient.invalidateQueries({ queryKey: ["customer-assignment-queue"] });
      message.success("测试问题已提交，接下来接管会话并查看处理结果");
    },
    onError: (error: Error) => message.error(error.message),
  });
  const review = useMutation({
    mutationFn: ({
      decision,
      text,
    }: {
      decision: "ACCEPTED" | "EDITED_AND_ACCEPTED";
      text?: string;
    }) => reviewTicket(ticketDetail!.id, ticketDetail!.version, decision, text),
    onSuccess: async (_result, variables) => {
      const answer =
        variables.decision === "EDITED_AND_ACCEPTED"
          ? variables.text
          : ticketDetail?.draft?.text;
      if (answer) {
        onReviewAnswer(answer);
      }
      message.success("审核结果已保存");
      await queryClient.invalidateQueries({
        queryKey: ["ticket", ticketId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversation", conversationId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const feedback = useMutation({
    mutationFn: (rating: "POSITIVE" | "NEGATIVE") => {
      const ticket = ticketDetail;
      if (!ticket?.draft) throw new Error("还没有可评价的回答");
      if (!feedbackSpace) {
        throw new Error("当前数字员工没有可用于反馈的知识空间绑定");
      }
      return createKnowledgeFeedback({
        employeeId: ticket.employee.id,
        knowledgeSpaceId: feedbackSpace.id,
        ticketId: ticket.id,
        query: `${ticket.subject}\n${ticket.body}`,
        answer: ticket.draft.text,
        rating,
        reasonCode: rating === "POSITIVE" ? "HELPFUL" : "WRONG_ANSWER",
      });
    },
    onSuccess: (result) => {
      message.success(
        result.repair_task_id ? "反馈已记录并生成修复任务" : "反馈已记录",
      );
    },
    onError: (error: Error) => message.error(error.message),
  });
  const assignment = useMutation({
    mutationFn: async (action: "takeover" | "release") => {
      if (!conversationId || !conversationDetail) {
        throw new Error("当前没有可操作的会话");
      }
      return action === "takeover"
        ? takeOverCustomerConversation(
            conversationId,
            conversationDetail.version,
          )
        : releaseCustomerConversation(conversationId);
    },
    onSuccess: (_result, action) => {
      message.success(action === "takeover" ? "会话已接管" : "会话已释放");
      if (action === "takeover") {
        onTakeOver();
      }
    },
    onError: (error: Error) => {
      if (error instanceof ApiError) {
        if (error.code === "AGENT_CAPACITY_REACHED") {
          message.warning(
            `当前客服已负责 ${currentAgentCapacity} 个活动会话，请先释放一个会话。`,
          );
          return;
        }
        if (
          error.code === "CONVERSATION_VERSION_CONFLICT" ||
          error.code === "CONVERSATION_ALREADY_ASSIGNED"
        ) {
          message.warning("会话状态已变化，已为你刷新最新状态。");
          return;
        }
      }
      message.error(error.message);
    },
    onSettled: () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-conversations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-assignment-queue"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-agent-presence"],
        }),
      ]);
    },
  });
  const autoAssign = useMutation({
    mutationFn: autoAssignCustomerConversations,
    onSuccess: async (result) => {
      onAssignmentResult(result);
      message.success(
        `自动分配 ${result.assigned_count} 个会话，剩余 ${result.unassigned_count} 个`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const acknowledgeNotification = useMutation({
    mutationFn: acknowledgeCustomerServiceNotification,
    onSuccess: async () => {
      message.success("主管告警已确认");
      await queryClient.invalidateQueries({
        queryKey: ["customer-service-notifications"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  return {
    createTicket,
    review,
    feedback,
    assignment,
    autoAssign,
    acknowledgeNotification,
  };
}
