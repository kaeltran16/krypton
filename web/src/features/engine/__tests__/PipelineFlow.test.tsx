import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import PipelineFlow from "../components/PipelineFlow";

class MockResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

beforeEach(() => {
  globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;
});

describe("PipelineFlow", () => {
  it("renders an SVG with pipeline title", () => {
    render(<PipelineFlow />);
    expect(screen.getByRole("img", { name: /signal pipeline/i })).toBeInTheDocument();
    expect(screen.getAllByText("Signal Pipeline").length).toBeGreaterThanOrEqual(1);
  });

  it("renders all source nodes", () => {
    render(<PipelineFlow />);
    for (const label of ["Technical", "Order Flow", "On-Chain", "Liquidation", "Patterns", "Confluence", "News"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders processing and gate nodes", () => {
    render(<PipelineFlow />);
    for (const label of ["Regime Blend", "Agreement", "ML Gate", "LLM Gate", "Threshold", "Signal", "Discard"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders edges as SVG paths", () => {
    const { container } = render(<PipelineFlow />);
    const paths = container.querySelectorAll("path.pipeline-edge");
    // 7 source->regime + regime->agreement + agreement->ml + ml->llm + llm->threshold + threshold->signal + threshold->discard = 13
    expect(paths.length).toBe(13);
  });

  it("colors edges based on source node score", () => {
    render(
      <PipelineFlow
        nodes={{ technical: { label: "Technical", score: 42.5 } }}
      />,
    );
    expect(screen.getByText("+42.5")).toBeInTheDocument();
  });

  it("renders collapsible self-optimization zone", () => {
    render(<PipelineFlow />);
    expect(screen.getByText("Self-Optimization")).toBeInTheDocument();
    for (const label of ["Outcome Resolver", "ATR Learning", "Param Optimizer", "Regime Online"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("expands self-optimization zone on click", () => {
    render(<PipelineFlow />);
    fireEvent.click(screen.getByText("Self-Optimization"));
    for (const label of ["Outcome Resolver", "ATR Learning", "Param Optimizer", "Regime Online"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("expands node details on click and collapses on second click", () => {
    const nodes = {
      technical: {
        label: "Technical",
        score: 42.5,
        details: { trend: 18.2, mean_rev: 12.0, squeeze: 5.3, volume: 7.0 },
      },
    };
    render(<PipelineFlow nodes={nodes} />);

    fireEvent.click(screen.getByLabelText(/technical score/i));
    expect(screen.getByText("trend")).toBeInTheDocument();
    expect(screen.getByText("+18.2")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/technical score/i));
    expect(screen.queryByText("trend")).not.toBeInTheDocument();
  });

  it("only expands one node at a time", () => {
    const nodes = {
      technical: { label: "Technical", score: 42.5, details: { trend: 18.2 } },
      order_flow: { label: "Order Flow", score: -10.0, details: { funding: -5.0 } },
    };
    render(<PipelineFlow nodes={nodes} />);

    fireEvent.click(screen.getByLabelText(/technical score/i));
    expect(screen.getByText("trend")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/order flow score/i));
    expect(screen.queryByText("trend")).not.toBeInTheDocument();
    expect(screen.getByText("funding")).toBeInTheDocument();
  });

  it("shows pulsing glow on signal node when emitted", () => {
    const nodes = {
      signal: { label: "Signal", score: 55.0, emitted: true },
    };
    const { container } = render(<PipelineFlow nodes={nodes} />);
    const glowRect = container.querySelector(".signal-glow");
    expect(glowRect).toBeInTheDocument();
  });
});
