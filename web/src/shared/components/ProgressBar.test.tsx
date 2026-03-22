import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProgressBar } from "./ProgressBar";

describe("ProgressBar", () => {
  const fill = (container: HTMLElement) =>
    container.querySelector("[role=progressbar] > div") as HTMLElement;

  it("renders with correct width style on inner fill", () => {
    const { container } = render(<ProgressBar value={75} />);
    expect(fill(container)?.getAttribute("style")).toContain("width: 75%");
  });

  it("clamps value to 0-100", () => {
    const { container } = render(<ProgressBar value={150} />);
    expect(fill(container)?.getAttribute("style")).toContain("width: 100%");
  });

  it("applies custom color class to inner fill", () => {
    const { container } = render(<ProgressBar value={50} color="bg-error" />);
    expect(fill(container)?.className).toContain("bg-error");
  });

  it("has progressbar role with aria attributes on track", () => {
    const { container } = render(<ProgressBar value={60} label="Score" />);
    const bar = container.querySelector("[role=progressbar]");
    expect(bar).toBeTruthy();
    expect(bar?.getAttribute("aria-valuenow")).toBe("60");
    expect(bar?.getAttribute("aria-label")).toBe("Score");
  });

  it("applies glow shadow to inner fill when glow is true", () => {
    const { container } = render(<ProgressBar value={50} glow />);
    expect(fill(container)?.className).toContain("shadow-primary/40");
  });

  it("track is full-width, fill is partial-width", () => {
    const { container } = render(<ProgressBar value={40} />);
    const track = container.querySelector("[role=progressbar]") as HTMLElement;
    expect(track?.style.width).toBeFalsy();
    expect(fill(container)?.getAttribute("style")).toContain("width: 40%");
  });
});
