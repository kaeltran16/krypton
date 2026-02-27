import { describe, it, expect } from "vitest";
import { formatPrice, formatScore, formatTime } from "./format";

describe("formatPrice", () => {
  it("formats BTC-range prices with 2 decimals", () => {
    expect(formatPrice(85432.15)).toBe("85,432.15");
  });

  it("formats small prices with more precision", () => {
    expect(formatPrice(0.00045)).toBe("0.000450");
  });

  it("formats zero", () => {
    expect(formatPrice(0)).toBe("0.00");
  });
});

describe("formatScore", () => {
  it("formats positive scores with + prefix", () => {
    expect(formatScore(72)).toBe("+72");
  });

  it("formats negative scores with - prefix", () => {
    expect(formatScore(-45)).toBe("-45");
  });

  it("formats zero without prefix", () => {
    expect(formatScore(0)).toBe("0");
  });
});

describe("formatTime", () => {
  it("formats ISO timestamp to HH:MM", () => {
    expect(formatTime("2026-02-27T14:35:00Z")).toMatch(/\d{2}:\d{2}/);
  });
});
