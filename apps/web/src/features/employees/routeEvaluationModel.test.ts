import { describe, expect, it } from "vitest";

import type {
  DigitalEmployeeRouteEvaluationCase,
  DigitalEmployeeRouteEvaluationRun,
} from "../../types";
import {
  accuracyPercent,
  enabledCaseCount,
  filterEvaluationResults,
  resolveSelectedRun,
} from "./routeEvaluationModel";

function makeRun(
  overrides: Partial<DigitalEmployeeRouteEvaluationRun> & { id: string },
): DigitalEmployeeRouteEvaluationRun {
  return {
    business_unit_id: "bu_test",
    service_entry_id: null,
    dataset: "TUNING",
    total: 0,
    passed: 0,
    failed: 0,
    accuracy: 0,
    failure_analysis: {
      failed_total: 0,
      out_of_pool_total: 0,
      confusions: [],
      reasons: [],
    },
    results: [],
    created_by: "test",
    created_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function makeCase(
  overrides: Partial<DigitalEmployeeRouteEvaluationCase> & { id: string },
): DigitalEmployeeRouteEvaluationCase {
  return {
    business_unit_id: "bu_test",
    service_entry_id: "entry_test",
    expected_employee_id: "emp_1",
    expected_employee_name: "客服员工",
    dataset: "TUNING",
    question: "如何退款",
    notes: "",
    enabled: true,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("resolveSelectedRun", () => {
  const latest = makeRun({ id: "run_2", accuracy: 0.5 });
  const older = makeRun({ id: "run_1", accuracy: 0.9 });

  it("returns the explicitly selected run", () => {
    expect(resolveSelectedRun([latest, older], "run_1")?.id).toBe("run_1");
  });

  it("falls back to the newest run when the id is unknown", () => {
    expect(resolveSelectedRun([latest, older], "run_missing")?.id).toBe("run_2");
    expect(resolveSelectedRun([latest, older], "")?.id).toBe("run_2");
  });

  it("returns undefined when there are no runs", () => {
    expect(resolveSelectedRun([], "run_1")).toBeUndefined();
    expect(resolveSelectedRun(undefined, "run_1")).toBeUndefined();
  });
});

describe("accuracyPercent", () => {
  it("rounds the accuracy ratio to an integer percentage", () => {
    expect(accuracyPercent(makeRun({ id: "run", accuracy: 0.8123 }))).toBe(81);
    expect(accuracyPercent(makeRun({ id: "run", accuracy: 0.815 }))).toBe(82);
  });

  it("handles the boundaries and a missing run", () => {
    expect(accuracyPercent(makeRun({ id: "run", accuracy: 0 }))).toBe(0);
    expect(accuracyPercent(makeRun({ id: "run", accuracy: 1 }))).toBe(100);
    expect(accuracyPercent(undefined)).toBe(0);
  });
});

describe("enabledCaseCount", () => {
  it("counts only enabled cases", () => {
    expect(
      enabledCaseCount([
        makeCase({ id: "case_1" }),
        makeCase({ id: "case_2", enabled: false }),
        makeCase({ id: "case_3" }),
      ]),
    ).toBe(2);
  });

  it("returns zero when cases are not loaded", () => {
    expect(enabledCaseCount(undefined)).toBe(0);
    expect(enabledCaseCount([])).toBe(0);
  });
});

describe("filterEvaluationResults", () => {
  const results = [
    { case_id: "a", matched: true },
    { case_id: "b", matched: false },
    { case_id: "c", matched: true },
  ];

  it("returns every result when the failures-only switch is off", () => {
    expect(filterEvaluationResults(results, false)).toEqual(results);
  });

  it("keeps only mismatched results when the switch is on", () => {
    expect(filterEvaluationResults(results, true)).toEqual([
      { case_id: "b", matched: false },
    ]);
  });

  it("does not mutate the source list", () => {
    const source = [{ matched: false }];
    filterEvaluationResults(source, true);
    expect(source).toEqual([{ matched: false }]);
  });
});
