import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  createDigitalEmployeeRouteEvaluationCase,
  deleteDigitalEmployeeRouteEvaluationCase,
  listDigitalEmployeeRouteEvaluationCases,
  listDigitalEmployeeRouteEvaluationRuns,
  runDigitalEmployeeRouteEvaluation,
  updateDigitalEmployeeRouteEvaluationCase,
} from "../../api";
import { message } from "../../feedback";
import type { DigitalEmployeeRouteEvaluationDataset } from "../../types";
import { resolveSelectedRun } from "./routeEvaluationModel";

export {
  accuracyPercent,
  enabledCaseCount,
  filterEvaluationResults,
  resolveSelectedRun,
} from "./routeEvaluationModel";

export type RouteEvaluationCaseInput = {
  expectedEmployeeId: string;
  dataset: DigitalEmployeeRouteEvaluationDataset;
  question: string;
  notes: string;
  enabled: boolean;
};

export function useRouteEvaluation({
  entryId,
  dataset,
}: {
  entryId: string;
  dataset: DigitalEmployeeRouteEvaluationDataset;
}) {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState("");
  const cases = useQuery({
    queryKey: ["route-evaluation-cases", entryId, dataset],
    queryFn: () => listDigitalEmployeeRouteEvaluationCases(entryId, dataset),
    enabled: Boolean(entryId),
  });
  const runs = useQuery({
    queryKey: ["route-evaluation-runs", entryId, dataset],
    queryFn: () => listDigitalEmployeeRouteEvaluationRuns(entryId, dataset),
    enabled: Boolean(entryId),
  });
  const selectedRun = resolveSelectedRun(runs.data?.items, selectedRunId);
  const saveCase = useMutation({
    mutationFn: (input: {
      caseId: string | null;
      values: RouteEvaluationCaseInput;
    }) => {
      if (!entryId) throw new Error("请选择业务入口");
      if (!input.values.expectedEmployeeId) throw new Error("请选择应处理员工");
      if (!input.values.question.trim()) throw new Error("请填写评测问题");
      if (input.caseId) {
        return updateDigitalEmployeeRouteEvaluationCase(input.caseId, {
          expectedEmployeeId: input.values.expectedEmployeeId,
          dataset: input.values.dataset,
          question: input.values.question.trim(),
          notes: input.values.notes.trim(),
          enabled: input.values.enabled,
        });
      }
      return createDigitalEmployeeRouteEvaluationCase({
        serviceEntryId: entryId,
        expectedEmployeeId: input.values.expectedEmployeeId,
        dataset: input.values.dataset,
        question: input.values.question.trim(),
        notes: input.values.notes.trim(),
        enabled: input.values.enabled,
      });
    },
    onSuccess: async (_case, input) => {
      message.success(input.caseId ? "评测问题已更新" : "评测问题已添加");
      await queryClient.invalidateQueries({
        queryKey: ["route-evaluation-cases", entryId],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const removeCase = useMutation({
    mutationFn: (caseId: string) =>
      deleteDigitalEmployeeRouteEvaluationCase(caseId),
    onSuccess: async () => {
      message.success("评测问题已删除");
      await queryClient.invalidateQueries({
        queryKey: ["route-evaluation-cases", entryId],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const runEvaluation = useMutation({
    mutationFn: () => {
      if (!entryId) throw new Error("请选择业务入口");
      return runDigitalEmployeeRouteEvaluation(entryId, dataset);
    },
    onSuccess: async (run) => {
      message.success(
        `路由评测完成：准确率 ${(run.accuracy * 100).toFixed(0)}%`,
      );
      setSelectedRunId(run.id);
      await queryClient.invalidateQueries({
        queryKey: ["route-evaluation-runs", entryId],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });

  return {
    cases,
    runs,
    selectedRun,
    selectedRunId,
    setSelectedRunId,
    saveCase,
    removeCase,
    runEvaluation,
  };
}
