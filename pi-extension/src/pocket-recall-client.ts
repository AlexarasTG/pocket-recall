import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { connect } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

const PROTOCOL_VERSION = 1;
const MAX_REQUEST_BYTES = 65_536;
const MAX_RESPONSE_BYTES = 131_072;
const REQUEST_TIMEOUT_MS = 30_000;
const SOCKET_PATH = join(homedir(), ".local", "share", "pocket-recall", "service.sock");

export interface MemoryDraft {
  title: string;
  body: string;
  aliases: string[];
}

export interface MemoryRecord extends MemoryDraft {
  id: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface SearchCandidate {
  id: string;
  title: string;
  aliases: string[];
  updated_at: string;
  match_kind: "exact" | "lexical" | "typo" | "semantic";
  score: number;
  excerpt: string;
}

export interface SearchResults {
  candidates: SearchCandidate[];
  index_update_pending: boolean;
}

interface ServiceEnvelope {
  protocol_version?: unknown;
  request_id?: unknown;
  success?: unknown;
  result?: unknown;
  warnings?: unknown;
  error?: unknown;
}

export interface ServiceResult<T> {
  result: T;
  warnings: string[];
}

export class PocketRecallClient {
  constructor(private readonly pi: ExtensionAPI) {}

  async search(query: string, signal?: AbortSignal): Promise<ServiceResult<SearchResults>> {
    const response = await this.request("search", { query }, signal);
    return validateResult(response, parseSearchResults);
  }

  async fetch(id: string, signal?: AbortSignal): Promise<ServiceResult<MemoryRecord>> {
    const response = await this.request("memory.get", { memory_id: id }, signal);
    return validateResult(response, parseMemoryRecord);
  }

  async create(draft: MemoryDraft, signal?: AbortSignal): Promise<ServiceResult<MemoryRecord>> {
    const response = await this.request("memory.create", draft, signal);
    return validateResult(response, parseMemoryRecord);
  }

  async indexUpdatePending(signal?: AbortSignal): Promise<boolean> {
    const response = validateResult(
      await this.request("maintenance.status", {}, signal),
      parseIndexStatus,
    );
    return response.result.index_update_pending;
  }

  private async request(
    operation: string,
    arguments_: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<ServiceResult<unknown>> {
    try {
      return await this.exchange(operation, arguments_, signal);
    } catch (error) {
      if (!isUnavailableSocketError(error)) throw error;
      await this.startService(signal);
      return this.exchange(operation, arguments_, signal);
    }
  }

  private async startService(signal?: AbortSignal): Promise<void> {
    const result = await this.pi.exec("memory", ["maintenance", "status"], {
      signal,
      timeout: REQUEST_TIMEOUT_MS,
    });
    if (result.code !== 0) {
      const detail = result.stderr.trim() || result.stdout.trim() || `exit code ${result.code}`;
      throw new Error(`Could not start Pocket Recall: ${detail}`);
    }
  }

  private exchange(
    operation: string,
    arguments_: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<ServiceResult<unknown>> {
    const requestId = randomUUID();
    const request = `${JSON.stringify({
      protocol_version: PROTOCOL_VERSION,
      request_id: requestId,
      operation,
      arguments: arguments_,
    })}\n`;
    if (Buffer.byteLength(request) > MAX_REQUEST_BYTES) {
      throw new Error("Pocket Recall request is too large");
    }

    return new Promise((resolve, reject) => {
      const socket = connect(SOCKET_PATH);
      let response = Buffer.alloc(0);
      let settled = false;

      const finish = (error?: Error, value?: ServiceResult<unknown>) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        signal?.removeEventListener("abort", abort);
        if (error) reject(error);
        else if (value) resolve(value);
        else reject(new Error("Pocket Recall request completed without a result"));
      };
      const abort = () => finish(new Error("Pocket Recall request cancelled"));

      socket.setTimeout(REQUEST_TIMEOUT_MS);
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) {
        abort();
        return;
      }

      socket.on("connect", () => socket.write(request));
      socket.on("data", (chunk: Buffer) => {
        response = Buffer.concat([response, chunk]);
        if (response.length > MAX_RESPONSE_BYTES) {
          finish(new Error("Pocket Recall response is too large"));
          return;
        }
        const newline = response.indexOf(10);
        if (newline === -1) return;
        try {
          finish(undefined, parseEnvelope(response.subarray(0, newline).toString("utf8"), requestId));
        } catch (error) {
          finish(asError(error));
        }
      });
      socket.on("timeout", () => finish(new Error("Pocket Recall request timed out")));
      socket.on("error", (error) => finish(error));
      socket.on("end", () => finish(new Error("Pocket Recall closed the connection without a response")));
    });
  }
}

function parseEnvelope(text: string, requestId: string): ServiceResult<unknown> {
  const parsed: unknown = JSON.parse(text);
  if (!isObject(parsed)) {
    throw new Error("Pocket Recall returned an invalid response envelope");
  }
  const message: ServiceEnvelope = parsed;
  if (message.protocol_version !== PROTOCOL_VERSION || message.request_id !== requestId) {
    throw new Error("Pocket Recall returned an invalid response envelope");
  }
  if (message.success === true && "result" in message) {
    const warnings = message.warnings ?? [];
    if (!Array.isArray(warnings) || warnings.some((warning) => typeof warning !== "string")) {
      throw new Error("Pocket Recall returned invalid warnings");
    }
    return { result: message.result, warnings };
  }
  if (message.success !== false || !isObject(message.error)) {
    throw new Error("Pocket Recall returned an invalid response envelope");
  }
  const serviceError = message.error;
  if (typeof serviceError.code !== "string" || typeof serviceError.message !== "string") {
    throw new Error("Pocket Recall returned an invalid error");
  }
  throw new Error(`Pocket Recall ${serviceError.code}: ${serviceError.message}`);
}

function validateResult<T>(
  response: ServiceResult<unknown>,
  parseResult: (value: unknown) => T,
): ServiceResult<T> {
  return { result: parseResult(response.result), warnings: response.warnings };
}

function parseMemoryRecord(value: unknown): MemoryRecord {
  if (
    !isObject(value) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string" ||
    typeof value.body !== "string" ||
    !isStringArray(value.aliases) ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string" ||
    (value.deleted_at !== null && typeof value.deleted_at !== "string")
  ) {
    throw new Error("Pocket Recall returned an invalid memory record");
  }
  return {
    id: value.id,
    title: value.title,
    body: value.body,
    aliases: value.aliases,
    created_at: value.created_at,
    updated_at: value.updated_at,
    deleted_at: value.deleted_at,
  };
}

function parseSearchResults(value: unknown): SearchResults {
  if (!isObject(value) || !Array.isArray(value.candidates) || typeof value.index_update_pending !== "boolean") {
    throw new Error("Pocket Recall returned invalid search results");
  }
  return {
    candidates: value.candidates.map(parseSearchCandidate),
    index_update_pending: value.index_update_pending,
  };
}

function parseSearchCandidate(value: unknown): SearchCandidate {
  if (
    !isObject(value) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string" ||
    !isStringArray(value.aliases) ||
    typeof value.updated_at !== "string" ||
    !isMatchKind(value.match_kind) ||
    typeof value.score !== "number" ||
    !Number.isFinite(value.score) ||
    typeof value.excerpt !== "string"
  ) {
    throw new Error("Pocket Recall returned an invalid search candidate");
  }
  return {
    id: value.id,
    title: value.title,
    aliases: value.aliases,
    updated_at: value.updated_at,
    match_kind: value.match_kind,
    score: value.score,
    excerpt: value.excerpt,
  };
}

function parseIndexStatus(value: unknown): { index_update_pending: boolean } {
  if (!isObject(value) || typeof value.index_update_pending !== "boolean") {
    throw new Error("Pocket Recall returned an invalid index status");
  }
  return { index_update_pending: value.index_update_pending };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isMatchKind(value: unknown): value is SearchCandidate["match_kind"] {
  return value === "exact" || value === "lexical" || value === "typo" || value === "semantic";
}

function isUnavailableSocketError(error: unknown): boolean {
  return isNodeError(error) && (error.code === "ENOENT" || error.code === "ECONNREFUSED");
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
