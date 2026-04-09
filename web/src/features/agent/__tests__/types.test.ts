import { describe, expect, it } from "vitest";

import { getAnnotationOpacity, getStaleness } from "../types";

describe("getStaleness", () => {
  it("returns fresh for recent analyses", () => {
    expect(getStaleness(new Date().toISOString())).toBe("fresh");
  });

  it("returns aging for 4-24h old analyses", () => {
    const sixHoursAgo = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString();
    expect(getStaleness(sixHoursAgo)).toBe("aging");
  });

  it("returns stale for >24h analyses", () => {
    const twoDaysAgo = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    expect(getStaleness(twoDaysAgo)).toBe("stale");
  });
});

describe("getAnnotationOpacity", () => {
  it("returns 1 for fresh", () => expect(getAnnotationOpacity("fresh")).toBe(1));
  it("returns 0.6 for aging", () => expect(getAnnotationOpacity("aging")).toBe(0.6));
  it("returns 0.3 for stale", () => expect(getAnnotationOpacity("stale")).toBe(0.3));
});
