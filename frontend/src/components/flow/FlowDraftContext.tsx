// frontend/src/components/flow/FlowDraftContext.tsx
"use client";

import { createContext, useContext } from "react";

const FlowDraftContext = createContext(false);

export const FlowDraftProvider = FlowDraftContext.Provider;

export function useFlowDraft(): boolean {
  return useContext(FlowDraftContext);
}
