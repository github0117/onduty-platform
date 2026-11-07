import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createEmployeeDraftTrial,
  evaluateEmployeeDraft,
  listEmployeeDrafts,
  promoteEmployeeDraftToTemplate,
  publishEmployeeDraft,
  reopenEmployeeDraft,
  reviewEmployeeDraft,
  rollbackEmployeeDraft,
  updateEmployeeDraft,
} from "../../api";
import { message } from "../../feedback";
import type { DigitalEmployeeDraft } from "../../types";
import { splitDraftList } from "./draftList";

export type DraftAction =
  | "APPROVE"
  | "REJECT"
  | "REOPEN"
  | "TRIAL"
  | "EVALUATE"
  | "PUBLISH"
  | "ROLLBACK";

const draftActionMessages: Record<DraftAction, string> = {
  APPROVE: "员工草案已批准",
  REJECT: "员工草案已拒绝",
  REOPEN: "员工草案已重新打开",
  TRIAL: "试用员工已创建",
  EVALUATE: "员工评测已完成",
  PUBLISH: "数字员工已正式发布",
  ROLLBACK: "数字员工已回滚停用",
};

export type DraftUpdateInput = {
  draftId: string;
  name: string;
  capabilities: string;
  intents: string;
  skillCodes: string;
  tools: string;
};

export function useEmployeeDrafts() {
  const queryClient = useQueryClient();
  const drafts = useQuery({
    queryKey: ["employee-drafts"],
    queryFn: listEmployeeDrafts,
    refetchInterval: 10_000,
  });
  const action = useMutation({
    mutationFn: (input: {
      draftId: string;
      action: DraftAction;
      note?: string;
    }): Promise<DigitalEmployeeDraft> => {
      if (input.action === "APPROVE" || input.action === "REJECT") {
        return reviewEmployeeDraft(input.draftId, {
          decision: input.action,
          note: input.note ?? "",
        });
      }
      if (input.action === "TRIAL") {
        return createEmployeeDraftTrial(input.draftId);
      }
      if (input.action === "REOPEN") {
        return reopenEmployeeDraft(input.draftId);
      }
      if (input.action === "EVALUATE") {
        return evaluateEmployeeDraft(input.draftId);
      }
      if (input.action === "PUBLISH") {
        return publishEmployeeDraft(input.draftId);
      }
      return rollbackEmployeeDraft(input.draftId);
    },
    onSuccess: async (_draft, input) => {
      message.success(draftActionMessages[input.action]);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["employee-draft-revisions"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["digital-employees"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const promoteToTemplate = useMutation({
    mutationFn: (draftId: string) =>
      promoteEmployeeDraftToTemplate(draftId),
    onSuccess: async () => {
      message.success(
        "已生成模板草案，请到岗位模板页面完成批准和发布",
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["managed-employee-templates"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["digital-employee-templates"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const updateDraft = useMutation({
    mutationFn: (input: DraftUpdateInput) =>
      updateEmployeeDraft(input.draftId, {
        name: input.name.trim(),
        capabilities: splitDraftList(input.capabilities),
        intents: splitDraftList(input.intents),
        skillCodes: splitDraftList(input.skillCodes),
        toolAllowlist: splitDraftList(input.tools),
      }),
    onSuccess: async () => {
      message.success("员工草案已更新");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["employee-drafts"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["employee-draft-revisions"],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });

  return {
    drafts,
    items: drafts.data?.items ?? [],
    total: drafts.data?.total ?? 0,
    action,
    promoteToTemplate,
    updateDraft,
  };
}
