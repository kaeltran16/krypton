import { beforeEach, describe, expect, it } from "vitest";

import { useAgentStore } from "../store";
import type { AgentAnalysis } from "../types";

function createAnalysis(overrides: Partial<AgentAnalysis> = {}): AgentAnalysis {
  return {
    id: 1,
    type: "brief",
    pair: null,
    narrative: "Test narrative",
    annotations: [],
    metadata: {},
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("useAgentStore", () => {
  beforeEach(() => {
    useAgentStore.setState({ analyses: [], selectedId: null, loading: false });
  });

  it("adds analysis to front of list", () => {
    const a1 = createAnalysis({ id: 1 });
    const a2 = createAnalysis({ id: 2 });
    useAgentStore.getState().addAnalysis(a1);
    useAgentStore.getState().addAnalysis(a2);
    expect(useAgentStore.getState().analyses[0].id).toBe(2);
  });

  it("caps analyses at 50", () => {
    for (let index = 0; index < 55; index += 1) {
      useAgentStore.getState().addAnalysis(createAnalysis({ id: index }));
    }
    expect(useAgentStore.getState().analyses.length).toBeLessThanOrEqual(50);
  });

  it("selects analysis by id", () => {
    const a1 = createAnalysis({ id: 1 });
    const a2 = createAnalysis({ id: 2 });
    useAgentStore.getState().setAnalyses([a1, a2]);
    useAgentStore.getState().selectAnalysis(2);
    expect(useAgentStore.getState().getSelected()?.id).toBe(2);
  });

  it("returns first analysis when no selection", () => {
    const a1 = createAnalysis({ id: 1 });
    useAgentStore.getState().setAnalyses([a1]);
    expect(useAgentStore.getState().getSelected()?.id).toBe(1);
  });

  it("auto-selects new analysis on add", () => {
    const a1 = createAnalysis({ id: 1 });
    useAgentStore.getState().addAnalysis(a1);
    expect(useAgentStore.getState().selectedId).toBe(1);
  });
});
