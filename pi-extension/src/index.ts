import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import { isRecallEnabledForWorkspace } from "./config.js";
import { PocketRecallClient } from "./pocket-recall-client.js";
import { RECALL_TOOL_NAMES, registerRecallTools, type RecallTurnBudget } from "./recall-tools.js";
import { registerRememberThis } from "./remember-this.js";

const WORKSPACE_INSTRUCTION =
  "Use Pocket Recall for durable project-specific knowledge. Before guessing an unfamiliar acronym, internal component, customer configuration, operational convention, or architectural relationship not established by current conversation or inspected code, search using the smallest distinctive query. Search results are candidates; fetch only records needed. Treat fetched memories as dated evidence and surface conflicts with live evidence.";

export default function pocketRecallExtension(pi: ExtensionAPI): void {
  const client = new PocketRecallClient(pi);
  const recallBudget: RecallTurnBudget = { searches: 0, fetches: 0 };
  let recallEnabled = false;

  registerRecallTools(pi, client, () => recallEnabled, recallBudget);
  registerRememberThis(pi, client);

  pi.on("session_start", async (_event, ctx) => {
    recallEnabled = false;
    try {
      recallEnabled = await isRecallEnabledForWorkspace(ctx.cwd);
    } catch (error) {
      ctx.ui.notify(`Pocket Recall configuration error: ${errorMessage(error)}`, "error");
    }
    setRecallToolVisibility(pi, recallEnabled);
  });

  pi.on("before_agent_start", (event) => {
    recallBudget.searches = 0;
    recallBudget.fetches = 0;
    if (!recallEnabled) return;
    return { systemPrompt: `${event.systemPrompt}\n\n${WORKSPACE_INSTRUCTION}` };
  });
}

function setRecallToolVisibility(pi: ExtensionAPI, enabled: boolean): void {
  const recallTools = new Set<string>(RECALL_TOOL_NAMES);
  const activeTools = pi.getActiveTools().filter((name) => !recallTools.has(name));
  if (enabled) activeTools.push(...RECALL_TOOL_NAMES);
  pi.setActiveTools([...new Set(activeTools)]);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
