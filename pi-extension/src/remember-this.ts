import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import type { MemoryDraft, PocketRecallClient } from "./pocket-recall-client.js";

const SAVE_TOOL_NAME = "pocket_recall_save";
const BODY_CHARACTER_LIMIT = 1_000;

type RememberIntentState = "waiting" | "saving" | undefined;

export function registerRememberThis(pi: ExtensionAPI, client: PocketRecallClient): void {
  let intentState: RememberIntentState;

  const hideSaveTool = () => {
    pi.setActiveTools(pi.getActiveTools().filter((name) => name !== SAVE_TOOL_NAME));
  };
  const clearIntent = () => {
    intentState = undefined;
    hideSaveTool();
  };

  pi.registerTool({
    name: SAVE_TOOL_NAME,
    label: "Pocket Recall Save",
    description:
      "Structure the statement supplied through /remember_this as one durable memory. This tool is available only for that explicit user request.",
    parameters: Type.Object({
      title: Type.String({ description: "Short descriptive title", minLength: 1 }),
      body: Type.String({ description: "Self-contained durable knowledge, at most 1000 characters", minLength: 1 }),
      aliases: Type.Array(Type.String({ minLength: 1 }), {
        description: "Alternative names, acronyms, or exact identifiers",
      }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (intentState !== "waiting") {
        throw new Error("pocket_recall_save requires one active /remember_this intent");
      }
      intentState = "saving";

      try {
        if (!ctx.hasUI) {
          throw new Error("Saving a memory requires interactive approval UI");
        }
        const draft = await editDraft(ctx, {
          title: params.title,
          body: params.body,
          aliases: params.aliases,
        });
        if (!draft) {
          return {
            content: [{ type: "text", text: "Memory creation cancelled; nothing was saved." }],
          };
        }

        const bodyCharacters = countUnicodeCodePoints(draft.body);
        const approved = await ctx.ui.confirm(
          "Create memory",
          `${JSON.stringify(draft, null, 2)}\n\nBody: ${bodyCharacters} / ${BODY_CHARACTER_LIMIT} characters`,
        );
        if (!approved) {
          return {
            content: [{ type: "text", text: "Memory creation cancelled; nothing was saved." }],
          };
        }

        const saved = await client.create(draft, signal);
        let indexMessage = "Search index update pending";
        let indexStatusWarning: string | undefined;
        try {
          indexMessage = (await client.indexUpdatePending(signal))
            ? "Search index update pending"
            : "Search index is up to date";
        } catch (error) {
          indexStatusWarning = `Index status unavailable: ${errorMessage(error)}`;
        }
        const warnings = [...saved.warnings, ...(indexStatusWarning ? [indexStatusWarning] : [])];
        const warningText = warnings.length > 0 ? `\n${warnings.join("\n")}` : "";
        return {
          content: [
            {
              type: "text",
              text: `Memory saved\nID: ${saved.result.id}\n${indexMessage}${warningText}`,
            },
          ],
        };
      } finally {
        clearIntent();
      }
    },
  });
  hideSaveTool();

  pi.registerCommand("remember_this", {
    description: "Propose a user-approved Pocket Recall memory",
    handler: async (args, ctx) => {
      const statement = args.trim();
      if (!statement) {
        ctx.ui.notify("Usage: /remember_this <statement>", "error");
        return;
      }
      if (!ctx.hasUI) {
        ctx.ui.notify("/remember_this requires interactive approval UI", "error");
        return;
      }

      await ctx.waitForIdle();
      if (intentState) {
        ctx.ui.notify("Another /remember_this request is still active", "error");
        return;
      }

      intentState = "waiting";
      pi.setActiveTools([...new Set([...pi.getActiveTools(), SAVE_TOOL_NAME])]);
      try {
        pi.sendUserMessage(
          [
            "The user explicitly requested creation of one Pocket Recall memory.",
            "Structure only the statement below; do not infer or add unsupported facts.",
            `Call ${SAVE_TOOL_NAME} exactly once with a concise title, self-contained body, and useful aliases.`,
            "",
            "Statement:",
            statement,
          ].join("\n"),
        );
      } catch (error) {
        clearIntent();
        throw error;
      }
    },
  });

  pi.on("agent_settled", () => {
    if (intentState === "waiting") clearIntent();
  });
  pi.on("session_shutdown", clearIntent);
}

async function editDraft(
  ctx: ExtensionContext,
  proposedDraft: MemoryDraft,
): Promise<MemoryDraft | undefined> {
  let editorText = JSON.stringify(proposedDraft, null, 2);
  while (true) {
    const edited = await ctx.ui.editor("Edit memory draft", editorText);
    if (edited === undefined) return undefined;
    editorText = edited;
    try {
      return parseDraft(edited);
    } catch (error) {
      ctx.ui.notify(errorMessage(error), "error");
    }
  }
}

function parseDraft(text: string): MemoryDraft {
  const value: unknown = JSON.parse(text);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Memory draft must be a JSON object");
  }
  const draft = value as Record<string, unknown>;
  if (typeof draft.title !== "string" || !draft.title.trim()) {
    throw new Error("Memory title must contain text");
  }
  if (typeof draft.body !== "string" || !draft.body.trim()) {
    throw new Error("Memory body must contain text");
  }
  if (!Array.isArray(draft.aliases) || draft.aliases.some((alias) => typeof alias !== "string" || !alias.trim())) {
    throw new Error("Memory aliases must be an array of non-empty strings");
  }
  const fields = [draft.title, draft.body, ...draft.aliases] as string[];
  if (fields.some((field) => field.includes("\0"))) {
    throw new Error("Memory text must not contain null characters");
  }
  const bodyCharacters = countUnicodeCodePoints(draft.body);
  if (bodyCharacters > BODY_CHARACTER_LIMIT) {
    throw new Error(`Memory body has ${bodyCharacters} characters; the limit is ${BODY_CHARACTER_LIMIT}`);
  }
  return { title: draft.title, body: draft.body, aliases: draft.aliases as string[] };
}

function countUnicodeCodePoints(value: string): number {
  return Array.from(value).length;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
