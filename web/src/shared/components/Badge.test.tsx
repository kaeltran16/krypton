import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Badge } from "./Badge";

describe("Badge", () => {
  it("renders children", () => {
    render(<Badge color="long">LONG</Badge>);
    expect(screen.getByText("LONG")).toBeTruthy();
  });

  it("applies color classes for long", () => {
    const { container } = render(<Badge color="long">LONG</Badge>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("bg-long/");
    expect(el.className).toContain("text-long");
  });

  it("applies color classes for short", () => {
    const { container } = render(<Badge color="short">SHORT</Badge>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("text-short");
  });

  it("renders with border when border prop is true", () => {
    const { container } = render(<Badge color="primary" border>Test</Badge>);
    expect(container.firstElementChild?.className).toContain("border");
  });

  it("renders pill shape", () => {
    const { container } = render(<Badge color="long" pill>Test</Badge>);
    expect(container.firstElementChild?.className).toContain("rounded-full");
  });

  it("renders default rounded shape", () => {
    const { container } = render(<Badge color="long">Test</Badge>);
    expect(container.firstElementChild?.className).toContain("rounded");
    expect(container.firstElementChild?.className).not.toContain("rounded-full");
  });

  it("applies aria-label when provided", () => {
    render(<Badge color="long" aria-label="Bullish bias">+</Badge>);
    expect(screen.getByLabelText("Bullish bias")).toBeTruthy();
  });
});
