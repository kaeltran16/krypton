import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ParamRow } from "./ParamRow";

describe("ParamRow", () => {
  it("renders label and value", () => {
    render(<ParamRow label="RSI" value="65.2" />);
    expect(screen.getByText("RSI")).toBeTruthy();
    expect(screen.getByText("65.2")).toBeTruthy();
  });

  it("renders border by default", () => {
    const { container } = render(<ParamRow label="Test" value="42" />);
    expect(container.firstElementChild?.className).toContain("border-b");
  });

  it("omits border when last is true", () => {
    const { container } = render(<ParamRow label="Test" value="42" last />);
    expect(container.firstElementChild?.className).not.toContain("border-b");
  });

  it("accepts ReactNode as value", () => {
    render(<ParamRow label="Status" value={<span data-testid="custom">OK</span>} />);
    expect(screen.getByTestId("custom")).toBeTruthy();
  });
});
