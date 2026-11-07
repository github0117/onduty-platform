import { describe, expect, it } from "vitest";

import { splitDraftList } from "./draftList";

describe("splitDraftList", () => {
  it("splits on ascii commas, full-width commas and newlines", () => {
    expect(splitDraftList("退款,物流，发票\n售后")).toEqual([
      "退款",
      "物流",
      "发票",
      "售后",
    ]);
  });

  it("trims surrounding whitespace", () => {
    expect(splitDraftList("  退款 , 物流  ")).toEqual(["退款", "物流"]);
  });

  it("drops empty entries from consecutive separators", () => {
    expect(splitDraftList("退款,,物流，\n\n发票")).toEqual([
      "退款",
      "物流",
      "发票",
    ]);
  });

  it("returns an empty list for blank input", () => {
    expect(splitDraftList("")).toEqual([]);
    expect(splitDraftList("   \n  ")).toEqual([]);
  });

  it("keeps inner spaces inside a single value", () => {
    expect(splitDraftList("售前 咨询")).toEqual(["售前 咨询"]);
  });
});
