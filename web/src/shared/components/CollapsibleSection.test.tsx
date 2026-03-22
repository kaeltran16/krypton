import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { CollapsibleSection } from "./CollapsibleSection";

describe("CollapsibleSection", () => {
  it("renders title", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="OK" open={false} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("Pipeline")).toBeTruthy();
  });

  it("shows summary when closed", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="3 signals" open={false} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("3 signals")).toBeTruthy();
  });

  it("hides summary when open", () => {
    render(
      <CollapsibleSection title="Pipeline" summary="3 signals" open={true} onToggle={() => {}}>
        <p>Content</p>
      </CollapsibleSection>
    );
    expect(screen.queryByText("3 signals")).toBeNull();
  });

  it("shows children when open", () => {
    render(
      <CollapsibleSection title="Test" open={true} onToggle={() => {}}>
        <p>Inner content</p>
      </CollapsibleSection>
    );
    expect(screen.getByText("Inner content")).toBeTruthy();
  });

  it("hides children when closed", () => {
    render(
      <CollapsibleSection title="Test" open={false} onToggle={() => {}}>
        <p>Inner content</p>
      </CollapsibleSection>
    );
    expect(screen.queryByText("Inner content")).toBeNull();
  });

  it("calls onToggle when clicked", () => {
    const onToggle = vi.fn();
    render(
      <CollapsibleSection title="Test" open={false} onToggle={onToggle}>
        <p>Content</p>
      </CollapsibleSection>
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
