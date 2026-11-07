import { describe, expect, it } from "vitest";

import { gateReasonLabel, localizedLabel } from "./statusLabels";

describe("gateReasonLabel", () => {
  it("maps known gate reasons to their Chinese label", () => {
    expect(gateReasonLabel("HIGH_RISK")).toBe("高风险工单");
    expect(gateReasonLabel("UNSUPPORTED_CLAIM")).toBe("存在无依据的声明");
  });

  it("resolves GROUNDING_ prefixed reasons through grounding labels", () => {
    expect(gateReasonLabel("GROUNDING_UNVERIFIED")).toBe(
      "证据状态未通过：回答未完成声明核验",
    );
  });

  it("falls back to the raw status when the grounding status is unknown", () => {
    expect(gateReasonLabel("GROUNDING_SOMETHING_NEW")).toBe(
      "证据状态未通过：SOMETHING_NEW",
    );
  });

  it("returns an unknown reason unchanged", () => {
    expect(gateReasonLabel("CUSTOM_REASON")).toBe("CUSTOM_REASON");
  });
});

describe("localizedLabel", () => {
  it("returns the mapped label for a known value", () => {
    expect(localizedLabel({ ACTIVE: "可用" }, "ACTIVE")).toBe("可用");
  });

  it("returns the raw value when no mapping exists", () => {
    expect(localizedLabel({ ACTIVE: "可用" }, "UNKNOWN")).toBe("UNKNOWN");
  });

  it("uses the fallback for empty values", () => {
    expect(localizedLabel({ ACTIVE: "可用" }, null)).toBe("-");
    expect(localizedLabel({ ACTIVE: "可用" }, undefined)).toBe("-");
    expect(localizedLabel({ ACTIVE: "可用" }, "", "无")).toBe("无");
  });
});
