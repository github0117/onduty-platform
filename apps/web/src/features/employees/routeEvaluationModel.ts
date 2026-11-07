import type {
  DigitalEmployeeRouteEvaluationCase,
  DigitalEmployeeRouteEvaluationRun,
} from "../../types";

/** 选中指定运行；未选中或已被删除时回退到最近一次运行。 */
export function resolveSelectedRun(
  runs: DigitalEmployeeRouteEvaluationRun[] | undefined,
  selectedRunId: string,
): DigitalEmployeeRouteEvaluationRun | undefined {
  return runs?.find((item) => item.id === selectedRunId) ?? runs?.[0];
}

/** 准确率转成整数百分比，用于统计卡片与颜色阈值。 */
export function accuracyPercent(
  run: DigitalEmployeeRouteEvaluationRun | undefined,
): number {
  return run ? Math.round(run.accuracy * 100) : 0;
}

/** 启用中的评测问题数。 */
export function enabledCaseCount(
  cases: DigitalEmployeeRouteEvaluationCase[] | undefined,
): number {
  return (cases ?? []).filter((item) => item.enabled).length;
}

/** 「只看误派」开关：关闭时返回全部结果，打开时只保留未命中的。 */
export function filterEvaluationResults<T extends { matched: boolean }>(
  results: T[],
  failuresOnly: boolean,
): T[] {
  return results.filter((item) => !failuresOnly || !item.matched);
}
