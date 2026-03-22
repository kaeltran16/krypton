import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { PillSelect } from "./PillSelect";

vi.mock("../lib/haptics", () => ({ hapticTap: vi.fn() }));

describe("PillSelect", () => {
  it("renders all options", () => {
    render(
      <PillSelect options={["A", "B", "C"]} selected="A" onToggle={() => {}} />
    );
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
  });

  it("highlights active option", () => {
    render(
      <PillSelect options={["A", "B"]} selected="A" onToggle={() => {}} />
    );
    expect(screen.getByText("A").className).toContain("text-primary");
    expect(screen.getByText("B").className).toContain("text-on-surface-variant");
  });

  it("calls onToggle with clicked value", () => {
    const onToggle = vi.fn();
    render(
      <PillSelect options={["A", "B"]} selected="A" onToggle={onToggle} />
    );
    fireEvent.click(screen.getByText("B"));
    expect(onToggle).toHaveBeenCalledWith("B");
  });

  it("supports multi-select", () => {
    render(
      <PillSelect options={["A", "B", "C"]} selected={["A", "C"]} onToggle={() => {}} multi />
    );
    expect(screen.getByText("A").className).toContain("text-primary");
    expect(screen.getByText("B").className).toContain("text-on-surface-variant");
    expect(screen.getByText("C").className).toContain("text-primary");
  });

  it("uses custom renderLabel", () => {
    render(
      <PillSelect options={["X"]} selected="X" onToggle={() => {}} renderLabel={(v) => `Label-${v}`} />
    );
    expect(screen.getByText("Label-X")).toBeTruthy();
  });
});
