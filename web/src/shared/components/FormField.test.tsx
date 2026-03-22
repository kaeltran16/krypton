import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FormField } from "./FormField";

describe("FormField", () => {
  it("renders label text", () => {
    render(
      <FormField label="Name">
        <input />
      </FormField>
    );
    expect(screen.getByText("Name")).toBeTruthy();
  });

  it("renders children (input)", () => {
    render(
      <FormField label="Email">
        <input data-testid="email-input" />
      </FormField>
    );
    expect(screen.getByTestId("email-input")).toBeTruthy();
  });

  it("applies uppercase tracking to label", () => {
    const { container } = render(
      <FormField label="Test">
        <input />
      </FormField>
    );
    const label = container.querySelector("span");
    expect(label?.className).toContain("uppercase");
    expect(label?.className).toContain("tracking-widest");
  });
});
