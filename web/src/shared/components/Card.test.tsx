import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Card } from "./Card";

describe("Card", () => {
  it("renders children with default styling", () => {
    const { container } = render(<Card>Hello</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("bg-surface-container");
    expect(el.className).toContain("rounded-lg");
  });

  it("applies padding variants", () => {
    const { container } = render(<Card padding="sm">Content</Card>);
    expect(container.firstElementChild?.className).toContain("p-3");
  });

  it("applies surface variant", () => {
    const { container } = render(<Card variant="low">Content</Card>);
    expect(container.firstElementChild?.className).toContain("bg-surface-container-low");
  });

  it("renders left accent border", () => {
    const { container } = render(<Card accent="primary">Content</Card>);
    expect(container.firstElementChild?.className).toContain("border-l-2");
    expect(container.firstElementChild?.className).toContain("border-l-primary");
  });

  it("merges custom className", () => {
    const { container } = render(<Card className="overflow-hidden">Content</Card>);
    expect(container.firstElementChild?.className).toContain("overflow-hidden");
  });

  it("renders as section when asSection is true", () => {
    const { container } = render(<Card asSection>Content</Card>);
    expect(container.querySelector("section")).toBeTruthy();
  });
});
