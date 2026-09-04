import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import type { PocketRecallClient } from "./pocket-recall-client.js";

export const RECALL_TOOL_NAMES = ["pocket_recall_search", "pocket_recall_fetch"] as const;
const MAX_CALLS_PER_USER_TURN = 3;

export interface RecallTurnBudget {
  searches: number;
  fetches: number;
}

export function registerRecallTools(
  pi: ExtensionAPI,
  client: PocketRecallClient,
  isEnabled: () => boolean,
  budget: RecallTurnBudget,
): void {
  pi.registerTool({
    name: "pocket_recall_search",
    label: "Pocket Recall Search",
    description:
      "Search user-approved durable knowledge. Use focused terms before guessing project-specific terminology or conventions. Returns compact candidates, not complete memories.",
    parameters: Type.Object({
      query: Type.String({ description: "Smallest distinctive query for the needed knowledge", minLength: 1 }),
    }),
    async execute(_toolCallId, params, signal) {
      consumeBudget("searches", budget, isEnabled);
      const response = await client.search(params.query, signal);
      const warning = response.result.index_update_pending
        ? "\nIndex update pending; results may be incomplete."
        : "";
      return {
        content: [{ type: "text", text: `${JSON.stringify(response.result, null, 2)}${warning}` }],
      };
    },
  });

  pi.registerTool({
    name: "pocket_recall_fetch",
    label: "Pocket Recall Fetch",
    description:
      "Fetch one complete active memory selected from search results. Fetch only records relevant to the current task.",
    parameters: Type.Object({
      id: Type.String({ description: "Memory ID returned by pocket_recall_search", minLength: 1 }),
    }),
    async execute(_toolCallId, params, signal) {
      consumeBudget("fetches", budget, isEnabled);
      const response = await client.fetch(params.id, signal);
      return {
        content: [{ type: "text", text: JSON.stringify(response.result, null, 2) }],
      };
    },
  });
}

function consumeBudget(
  kind: keyof RecallTurnBudget,
  budget: RecallTurnBudget,
  isEnabled: () => boolean,
): void {
  if (!isEnabled()) {
    throw new Error("Pocket Recall automatic recall is disabled outside configured workspaces");
  }
  if (budget[kind] >= MAX_CALLS_PER_USER_TURN) {
    const operation = kind === "searches" ? "searches" : "fetches";
    throw new Error(`Pocket Recall allows at most ${MAX_CALLS_PER_USER_TURN} ${operation} per user turn`);
  }
  budget[kind] += 1;
}
