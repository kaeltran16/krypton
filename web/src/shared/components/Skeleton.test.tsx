import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Skeleton } from "./Skeleton";

describe("Skeleton", () => {
  it("renders with default height", () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild!;
    expect(el.className).toContain("animate-pulse");
    expect(el.className).toContain("bg-surface-container");
    expect(el.className).toContain("rounded-lg");
  });

  it("applies custom height", () => {
    const { container } = render(<Skeleton height="h-28" />);
    expect(container.firstElementChild?.className).toContain("h-28");
  });

  it("renders multiple skeletons when count > 1", () => {
    const { container } = render(<Skeleton count={3} height="h-20" />);
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBe(3);
  });

  it("respects reduced motion", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild?.className).toContain("motion-reduce:animate-none");
  });
});
