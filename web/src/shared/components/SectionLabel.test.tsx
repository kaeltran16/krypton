import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { SectionLabel } from "./SectionLabel";

describe("SectionLabel", () => {
  it("renders text content", () => {
    render(<SectionLabel>Summary</SectionLabel>);
    expect(screen.getByText("Summary")).toBeTruthy();
  });

  it("uses uppercase tracking styling", () => {
    const { container } = render(<SectionLabel>Test</SectionLabel>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("uppercase");
    expect(el.className).toContain("tracking-wider");
  });

  it("renders as h3 by default", () => {
    const { container } = render(<SectionLabel>Test</SectionLabel>);
    expect(container.querySelector("h3")).toBeTruthy();
  });

  it("renders as custom heading level", () => {
    const { container } = render(<SectionLabel as="h2">Test</SectionLabel>);
    expect(container.querySelector("h2")).toBeTruthy();
    expect(container.querySelector("h3")).toBeNull();
  });
});
