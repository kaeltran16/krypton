import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SegmentedControl } from "./SegmentedControl";

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Charlie" },
];

describe("SegmentedControl", () => {
  it("renders all options", () => {
    render(<SegmentedControl options={OPTIONS} value="a" onChange={() => {}} />);
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
    expect(screen.getByText("Charlie")).toBeTruthy();
  });

  it("marks active option with aria-pressed", () => {
    render(<SegmentedControl options={OPTIONS} value="b" onChange={() => {}} />);
    expect(screen.getByText("Beta").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Alpha").getAttribute("aria-pressed")).toBe("false");
  });

  it("calls onChange on click", () => {
    const onChange = vi.fn();
    render(<SegmentedControl options={OPTIONS} value="a" onChange={onChange} />);
    fireEvent.click(screen.getByText("Charlie"));
    expect(onChange).toHaveBeenCalledWith("c");
  });
});
