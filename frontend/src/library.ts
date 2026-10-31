export type EntityKind = "project" | "resource" | "news";
export type Snapshot = {
  id: string | number;
  url: string;
  full_name?: string;
  name?: string;
  title?: string;
  description?: string;
  summary?: string;
  repo_name?: string;
  source_name?: string;
  content_hash?: string;
};
export type SavedEntry = {
  type: EntityKind;
  id: string;
  data: Snapshot;
  saved_at: string | null;
};
export type ReadMark = { read_at: string; content_hash: string | null };
export type LibraryState = {
  format: "github-rank-library";
  version: 1;
  entries: SavedEntry[];
  reading: Record<string, ReadMark>;
};
type StorageLike = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
};
export const LIBRARY_KEY = "github-rank:library:v1";
export const LEGACY_KEY = "github-rank:saved";
export const MAX_BACKUP_BYTES = 4 * 1024 * 1024;
const hashPattern = /^[a-f0-9]{64}$/;
const repoPattern = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export function emptyLibrary(): LibraryState {
  return {
    format: "github-rank-library",
    version: 1,
    entries: [],
    reading: {},
  };
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("记录格式无效");
  return value as Record<string, unknown>;
}
function timestamp(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(value) ||
    Number.isNaN(Date.parse(value))
  )
    throw new Error("记录时间无效");
  return new Date(value).toISOString();
}
function identifier(kind: EntityKind, value: unknown): string {
  const id = String(value);
  if (
    kind === "project"
      ? !/^[1-9]\d{0,15}$/.test(id) || !Number.isSafeInteger(Number(id))
      : !/^[a-f0-9]{32}$/.test(id)
  )
    throw new Error("条目 ID 无效");
  return id;
}
function webUrl(value: unknown): string {
  if (typeof value !== "string" || value.length > 2000)
    throw new Error("来源链接无效");
  const url = new URL(value);
  if (
    !["https:", "http:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new Error("来源链接无效");
  return url.href;
}
function snapshot(kind: EntityKind, id: string, value: unknown): Snapshot {
  const raw = object(value);
  if (String(raw.id) !== id) throw new Error("快照 ID 与收藏不一致");
  const data: Snapshot = {
    id: kind === "project" ? Number(id) : id,
    url: webUrl(raw.url),
  };
  for (const [key, limit] of [
    ["description", 1000],
    ["summary", 600],
    ["source_name", 120],
    ["repo_name", 250],
  ] as const) {
    if (typeof raw[key] === "string") data[key] = raw[key].slice(0, limit);
  }
  if (kind === "project") {
    if (
      typeof raw.full_name !== "string" ||
      raw.full_name.length > 250 ||
      !repoPattern.test(raw.full_name)
    )
      throw new Error("仓库名称无效");
    data.full_name = raw.full_name;
    data.url = "https://github.com/" + raw.full_name;
  } else {
    const field = kind === "news" ? "title" : "name";
    if (
      typeof raw[field] !== "string" ||
      !raw[field].trim() ||
      raw[field].length > 500
    )
      throw new Error("条目名称无效");
    data[field] = raw[field];
    if (kind === "resource" && new URL(data.url).hostname !== "github.com")
      throw new Error("资源原文件必须来自 GitHub");
  }
  if (
    typeof raw.content_hash === "string" &&
    hashPattern.test(raw.content_hash)
  )
    data.content_hash = raw.content_hash;
  return data;
}
export function makeEntry(
  type: EntityKind,
  id: string,
  data: Snapshot,
  now = new Date().toISOString(),
): SavedEntry {
  return {
    type,
    id: identifier(type, id),
    data: snapshot(type, id, data),
    saved_at: timestamp(now),
  };
}
export function parseLibrary(raw: string): LibraryState {
  if (new TextEncoder().encode(raw).length > MAX_BACKUP_BYTES)
    throw new Error("备份超过 4 MB");
  const value: unknown = JSON.parse(raw);
  const packet = Array.isArray(value)
    ? { entries: value, reading: {} }
    : object(value);
  if (
    !Array.isArray(value) &&
    (packet.format !== "github-rank-library" || packet.version !== 1)
  )
    throw new Error("不支持此备份版本");
  if (!Array.isArray(packet.entries) || packet.entries.length > 500)
    throw new Error("最多保留 500 条收藏");
  const state = emptyLibrary(),
    seen = new Set<string>();
  for (const row of packet.entries) {
    const entry = object(row);
    if (!["project", "resource", "news"].includes(String(entry.type)))
      throw new Error("收藏类型无效");
    const type = entry.type as EntityKind,
      id = identifier(type, entry.id),
      key = type + ":" + id;
    if (seen.has(key)) continue;
    seen.add(key);
    state.entries.push({
      type,
      id,
      data: snapshot(type, id, entry.data),
      saved_at: entry.saved_at == null ? null : timestamp(entry.saved_at),
    });
  }
  const reading = object(packet.reading ?? {});
  if (Object.keys(reading).length > 5000)
    throw new Error("备份最多包含 5000 条阅读记录");
  for (const [key, value] of Object.entries(reading)) {
    const id = identifier("news", key),
      mark = object(value);
    if (
      mark.content_hash != null &&
      (typeof mark.content_hash !== "string" ||
        !hashPattern.test(mark.content_hash))
    )
      throw new Error("阅读版本 hash 无效");
    state.reading[id] = {
      read_at: timestamp(mark.read_at),
      content_hash:
        mark.content_hash == null ? null : (mark.content_hash as string),
    };
  }
  return state;
}
export function loadLibrary(storage: StorageLike): {
  state: LibraryState;
  error?: string;
  raw?: string;
} {
  let raw: string | null = null;
  try {
    raw = storage.getItem(LIBRARY_KEY);
    if (raw === null) raw = storage.getItem(LEGACY_KEY);
    return {
      state: raw === null ? emptyLibrary() : parseLibrary(raw),
      raw: raw ?? undefined,
    };
  } catch (error) {
    return {
      state: emptyLibrary(),
      error: error instanceof Error ? error.message : "本机存储不可用",
      raw: raw ?? undefined,
    };
  }
}
export function serializeLibrary(state: LibraryState): string {
  const raw = JSON.stringify(state, null, 2);
  parseLibrary(raw);
  return raw;
}
export function writeLibrary(storage: StorageLike, state: LibraryState): void {
  storage.setItem(LIBRARY_KEY, serializeLibrary(state));
}
export function mergeLibrary(
  current: LibraryState,
  incoming: LibraryState,
): LibraryState {
  const entries = new Map(current.entries.map((e) => [e.type + ":" + e.id, e]));
  for (const entry of incoming.entries)
    if (!entries.has(entry.type + ":" + entry.id))
      entries.set(entry.type + ":" + entry.id, entry);
  const reading = { ...current.reading };
  for (const [id, mark] of Object.entries(incoming.reading))
    if (!reading[id] || mark.read_at > reading[id].read_at) reading[id] = mark;
  const newest = Object.fromEntries(
    Object.entries(reading)
      .sort((a, b) => b[1].read_at.localeCompare(a[1].read_at))
      .slice(0, 5000),
  );
  return parseLibrary(
    JSON.stringify({
      ...emptyLibrary(),
      entries: [...entries.values()],
      reading: newest,
    }),
  );
}
export function markRead(
  state: LibraryState,
  id: string,
  digest?: string | null,
  now = new Date().toISOString(),
): LibraryState {
  identifier("news", id);
  if (digest != null && !hashPattern.test(digest))
    throw new Error("阅读版本 hash 无效");
  return mergeLibrary(
    {
      ...state,
      reading: {
        ...state.reading,
        [id]: { read_at: timestamp(now), content_hash: digest || null },
      },
    },
    emptyLibrary(),
  );
}
export function readStatus(
  mark: ReadMark | undefined,
  digest?: string | null,
): "unread" | "read" | "updated" {
  if (!mark) return "unread";
  return mark.content_hash && digest && mark.content_hash !== digest
    ? "updated"
    : "read";
}
export function libraryMarkdown(state: LibraryState): string {
  const clean = (value: string) =>
    value.replace(/[\r\n]+/g, " ").replace(/[[\]<>\\]/g, "\\$&");
  const lines = [
    "# GitHub Rank 收藏",
    "",
    "导出保存时的原始信息快照；不表示最新指标。",
    "",
  ];
  for (const entry of state.entries) {
    const title =
      entry.data.full_name || entry.data.name || entry.data.title || entry.id;
    lines.push(
      "- [" +
        clean(title) +
        "](" +
        entry.data.url.replace(/[()]/g, (c) => (c === "(" ? "%28" : "%29")) +
        ") · " +
        entry.type,
    );
    const description = entry.data.description || entry.data.summary;
    if (description) lines.push("  " + clean(description));
  }
  return lines.join("\n") + "\n";
}
export function referenceBatches(entries: SavedEntry[]): string[] {
  const paths: string[] = [];
  for (let offset = 0; offset < entries.length; offset += 100) {
    const batch = entries.slice(offset, offset + 100),
      params = new URLSearchParams();
    for (const [kind, key] of [
      ["project", "projects"],
      ["resource", "resources"],
      ["news", "news"],
    ] as const) {
      const ids = batch.filter((e) => e.type === kind).map((e) => e.id);
      if (ids.length) params.set(key, ids.join(","));
    }
    paths.push("/api/library?" + params.toString());
  }
  return paths;
}
