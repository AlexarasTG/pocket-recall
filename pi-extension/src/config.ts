import { readFile, realpath } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, relative, sep } from "node:path";

const CONFIG_PATH = join(homedir(), ".config", "pocket-recall", "pi.json");

interface PiConfigFile {
  enabledWorkspaceRoots?: unknown;
}

export async function isRecallEnabledForWorkspace(cwd: string): Promise<boolean> {
  const roots = await readEnabledWorkspaceRoots();
  if (roots.length === 0) return false;

  const resolvedCwd = await realpath(cwd);
  for (const root of roots) {
    const resolvedRoot = await realpath(root);
    const pathFromRoot = relative(resolvedRoot, resolvedCwd);
    if (pathFromRoot === "" || (!pathFromRoot.startsWith(`..${sep}`) && pathFromRoot !== ".." && !isAbsolute(pathFromRoot))) {
      return true;
    }
  }
  return false;
}

async function readEnabledWorkspaceRoots(): Promise<string[]> {
  let text: string;
  try {
    text = await readFile(CONFIG_PATH, "utf8");
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") return [];
    throw error;
  }

  const parsed: unknown = JSON.parse(text);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${CONFIG_PATH} must contain a JSON object`);
  }

  const roots = (parsed as PiConfigFile).enabledWorkspaceRoots;
  if (roots === undefined) return [];
  if (!Array.isArray(roots) || roots.some((root) => typeof root !== "string" || !isAbsolute(root))) {
    throw new Error(`${CONFIG_PATH}: enabledWorkspaceRoots must contain absolute paths`);
  }
  return roots;
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
