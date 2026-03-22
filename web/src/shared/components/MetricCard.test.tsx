import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { MetricCard } from "./MetricCard";

describe("MetricCard", () => {
  it("renders label and value", () => {
    render(<MetricCard label="Win Rate" value="65%" />);
    expect(screen.getByText("Win Rate")).toBeTruthy();
    expect(screen.getByText("65%")).toBeTruthy();
  });

  it("applies custom value color", () => {
    render(<MetricCard label="PnL" value="+5%" color="text-long" />);
    const valueEl = screen.getByText("+5%");
    expect(valueEl.className).toContain("text-long");
  });

  it("renders label with uppercase styling", () => {
    render(<MetricCard label="Score" value="80" />);
    expect(screen.getByText("Score")).toBeTruthy();
    expect(screen.getByText("80")).toBeTruthy();
  });
});
