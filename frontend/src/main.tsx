import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Bookmark,
  Bot,
  Check,
  ChevronRight,
  CircleHelp,
  Compass,
  ExternalLink,
  Flame,
  GitFork,
  Github,
  History,
  Layers3,
  LoaderCircle,
  Newspaper,
  Radio,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
  TrendingUp,
  X,
  Menu,
  Clock3,
  AlertCircle,
} from "lucide-react";
import "./styles.css";
import {
  LIBRARY_KEY,
  LEGACY_KEY,
  MAX_BACKUP_BYTES,
  emptyLibrary,
  loadLibrary,
  writeLibrary,
  makeEntry,
  mergeLibrary,
  parseLibrary,
  serializeLibrary,
  libraryMarkdown,
  referenceBatches,
  markRead,
  readStatus,
  type SavedEntry,
  type LibraryState,
  type ReadMark,
} from "./library";

type SummaryFields = {
  summary_zh?: string;
  title_zh?: string;
  summary_meta?: {
    model: string;
    generated_at: string;
    evidence: { source_id: string; quote: string; url: string }[];
  };
};
type Repo = SummaryFields & {
  id: number;
  full_name: string;
  url: string;
  description: string;
  summary: string;
  stars: number;
  forks: number;
  language: string | null;
  category: string;
  agent_types: string[];
  topics: string[];
  license: string;
  homepage?: string;
  pushed_at?: string;
  observed_at?: string;
  first_seen_at?: string;
  archived?: boolean;
  delta_stars?: number | null;
  delta_forks?: number | null;
  potential_score?: number | null;
  observation_note?: string;
  rank?: number;
  period_start?: string;
  period_end?: string;
  resource_scan?: string;
  resource_scan_report?: Resource["scan_report"];
  ranking_excluded?: boolean;
  requested_name?: string;
  aliases?: string[];
  classification?: {
    method: "manual" | "rules";
    automatic: { category: string; agent_types: string[] };
    reason: string | null;
    updated_at: string | null;
  };
  score_scope?: string;
  score_peer_count?: number;
  data_source?: string;
  score_breakdown?: { name: string; value: number; contribution: number }[];
  resources?: Resource[];
  related_news?: News[];
};
type Resource = SummaryFields & {
  id: string;
  name: string;
  description: string;
  kind: string;
  repo_name: string;
  url: string;
  path: string;
  compatibility: string;
  compatibility_status: string;
  repository_stars?: number;
  commit?: string;
  content_hash?: string;
  ecosystem?: string;
  license?: string;
  declared_version?: string | null;
  compatibility_evidence?: { field: string; quote: string; url: string }[];
  format_warnings?: string[];
  verification_status?: string;
  duplicate_count?: number;
  scan_status?: string;
  scan_report?: {
    status?: string;
    tree_complete?: boolean;
    tree_requests?: number;
    candidate_files?: number;
    read_files?: number;
    invalid_files?: number;
    reasons?: string[];
    limits?: { files: number; trees: number; depth: number };
  };
  same_content_sources?: {
    id: string;
    repo_name: string;
    path: string;
    url: string;
    commit: string;
    verification_status: string;
  }[];
  ranking_excluded?: boolean;
};
type News = SummaryFields & {
  id: string;
  title: string;
  url: string;
  summary: string;
  topic: string;
  source_name: string;
  source_kind: string;
  published_at: string | null;
  published_precision?: string;
  fetched_at?: string;
  related_repositories: string[];
  related_reports?: {
    id?: string;
    url: string;
    title: string;
    source_name: string;
    published_at?: string | null;
    published_precision?: string;
  }[];
  is_preprint?: boolean;
  first_seen_at?: string;
  raw_published_at?: string | null;
  source_updated_at?: string | null;
  content_hash?: string;
  report_count?: number;
  source_count?: number;
  matching_report_count?: number;
  grouping?: {
    method: string;
    reason: string;
    rule_version: string;
    updated_at: string | null;
  };
  versions?: {
    content_hash: string;
    observed_at: string;
    is_current: boolean;
  }[];
  version_view?: {
    content_hash: string;
    observed_at: string;
    is_current: boolean;
  };
  event_edits?: {
    id: string;
    action: string;
    created_at: string;
    data: { reason: string };
  }[];
  source_state?: Source | null;
  related_projects?: { full_name: string; url: string; tracked: boolean }[];
};
type Source = {
  id: string;
  name: string;
  url: string;
  status: string;
  last_success_at: string | null;
  error: string | null;
  item_count: number;
  enabled?: boolean;
  effective_status?: string;
  freshness?: "fresh" | "stale" | "never" | "paused";
  next_due_at?: string | null;
  cadence_note?: string;
  consecutive_failures?: number;
  last_recovered_at?: string | null;
};
type RuntimeStatus = {
  scheduler: {
    status: string;
    online: boolean;
    current_mode?: string | null;
    heartbeat_at?: string;
    started_at?: string;
    next_check_at: string | null;
    next_repository_at: string | null;
    last_cycle_at?: string | null;
    last_result?: string | null;
    error?: string | null;
  };
  repositories_stale: boolean;
  oldest_repository_update: string | null;
  source_events: {
    id: string;
    source_name: string;
    kind: string;
    occurred_at: string;
    error: string | null;
  }[];
};
type Config = {
  categories: Record<string, string>;
  agent_types: Record<string, string>;
  topics: Record<string, string>;
  languages: string[];
};
type Status = {
  counts: Record<string, number>;
  last_snapshot: string | null;
  last_news: string | null;
  github_token_configured: boolean;
  summary_mode: string;
  summary_model_configured: boolean;
  summary_attempts_today: number;
  summary_daily_limit: number;
  jobs: {
    id: string;
    kind: string;
    status: string;
    started_at: string;
    report: {
      errors?: { source: string; error: string }[];
      deferred_repositories?: number;
    };
  }[];
};
type Ranking = {
  items: Repo[];
  observing: Repo[];
  total: number;
  observing_total: number;
  as_of: string;
  stale: boolean;
  tracked_count: number;
};
type NewsResult = {
  items: News[];
  unknown_time: News[];
  total: number;
  unknown_time_total: number;
};
type Saved = SavedEntry;
type LocalLibrary = ReturnType<typeof loadLibrary>;
type ResolvedEntry = {
  type: Saved["type"];
  id: string;
  state: "current" | "excluded" | "missing";
  data: Repo | Resource | News | null;
};
function readLocalLibrary(): LocalLibrary {
  try {
    return loadLibrary(localStorage);
  } catch {
    return { state: emptyLibrary(), error: "浏览器存储不可用" };
  }
}
function downloadText(
  name: string,
  content: string,
  mime = "application/json",
) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const time = (value?: string | null) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Shanghai",
      })
    : "尚未同步";
const number = (n: number) =>
  n >= 1000
    ? (n / 1000).toFixed(n >= 10000 ? 1 : 2).replace(/\.?0+$/, "") + "k"
    : String(n);
const colors: Record<string, string> = {
  Python: "#4b83b6",
  TypeScript: "#3178c6",
  JavaScript: "#d5b234",
  Go: "#00a2b9",
  Rust: "#b26b45",
  HTML: "#e76f51",
  Shell: "#78a65a",
};
function safeUrl(url?: string) {
  try {
    const u = new URL(url || "");
    return ["https:", "http:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}
function useLoad<T>(url: string, revision = 0) {
  const [state, setState] = useState<{
    data?: T;
    loading: boolean;
    error?: string;
  }>({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: undefined }));
    const timer = setTimeout(() => {
      fetch(url, { signal: controller.signal })
        .then(async (r) => {
          if (!r.ok) throw new Error(`请求失败 (${r.status})`);
          return r.json();
        })
        .then((data) => setState({ data, loading: false }))
        .catch((e) => {
          if (e.name !== "AbortError")
            setState({ loading: false, error: e.message });
        });
    }, 150);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [url, revision]);
  return state;
}

function App() {
  const [route, setRoute] = useState(location.pathname + location.search);
  const [revision, setRevision] = useState(0);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [runtimeRevision, setRuntimeRevision] = useState(0);
  useEffect(() => {
    if (!sourcesOpen) return;
    setRuntimeRevision((r) => r + 1);
    const timer = setInterval(() => setRuntimeRevision((r) => r + 1), 15000);
    return () => clearInterval(timer);
  }, [sourcesOpen]);
  const [sidebar, setSidebar] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [localLibrary, setLocalLibrary] =
    useState<LocalLibrary>(readLocalLibrary);
  const saved = localLibrary.state.entries,
    reading = localLibrary.state.reading;
  const [resolvedLibrary, setResolvedLibrary] = useState<{
    items: ResolvedEntry[];
    loading: boolean;
    error?: string;
  }>({ items: [], loading: false });
  const [notice, setNotice] = useState("");
  const path = route.split("?")[0],
    params = new URLSearchParams(route.split("?")[1] || "");
  const isNews = path === "/news",
    isAgents = path === "/agents",
    isHome = path === "/",
    isSaved = path === "/saved",
    isArchive = path === "/archive",
    isProjectDetail = path.startsWith("/projects/"),
    isResourceDetail = path.startsWith("/resources/"),
    isNewsDetail = path.startsWith("/news/"),
    isDetail = isProjectDetail || isResourceDetail || isNewsDetail;
  const kind = params.get("kind") === "potential" ? "potential" : "hot";
  const window = params.get("window") || (isNews ? "7d" : "7d");
  const category = params.get("category") || "",
    query = params.get("q") || "",
    agentType = params.get("agent_type") || "";
  const topic = params.get("topic") || "",
    sort = params.get("sort") || "latest",
    source = params.get("source") || "";
  const resourcesView = isAgents && params.get("view") === "resources";
  const readingFilter = ["unread", "read", "updated"].includes(
    params.get("read") || "",
  )
    ? params.get("read")!
    : "all";
  const savedType = ["project", "resource", "news"].includes(
    params.get("type") || "",
  )
    ? params.get("type")!
    : "all";
  const refsKey = saved.map((s) => s.type + ":" + s.id).join(",");
  useEffect(() => {
    const handler = (event: StorageEvent) => {
      if (
        event.key === LIBRARY_KEY ||
        event.key === LEGACY_KEY ||
        event.key === null
      )
        setLocalLibrary(readLocalLibrary());
    };
    addEventListener("storage", handler);
    return () => removeEventListener("storage", handler);
  }, []);
  useEffect(() => {
    if (!isSaved) return;
    const controller = new AbortController();
    setResolvedLibrary({ items: [], loading: !!refsKey });
    Promise.allSettled(
      referenceBatches(saved).map(async (url) => {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error("收藏同步失败");
        return (await response.json()).items as ResolvedEntry[];
      }),
    ).then((results) => {
      if (controller.signal.aborted) return;
      setResolvedLibrary({
        items: results.flatMap((r) =>
          r.status === "fulfilled" ? r.value : [],
        ),
        loading: false,
        error: results.some((r) => r.status === "rejected")
          ? "部分内容暂时无法更新，以下保留保存时的参考快照。"
          : undefined,
      });
    });
    return () => controller.abort();
  }, [isSaved, refsKey, revision]);
  const resourcePage = Math.min(
    1001,
    Math.max(1, Math.floor(Number(params.get("page") || "1")) || 1),
  );
  const language = params.get("language") || "";
  const minStars = params.get("min_stars") || "";
  const maxStars = params.get("max_stars") || "";
  const config = useLoad<Config>("/api/config", revision);
  const status = useLoad<Status>(
    "/api/data-status",
    revision + runtimeRevision,
  );
  const sources = useLoad<{ items: Source[] }>(
    "/api/news/sources",
    revision + runtimeRevision,
  );
  const runtime = useLoad<RuntimeStatus>(
    "/api/runtime-status",
    revision + runtimeRevision,
  );
  const rankedParams = new URLSearchParams({
    kind,
    window: window === "30d" ? "30d" : "7d",
    category,
    q: query,
    agent_type: isAgents ? agentType || "any" : agentType,
    language,
    min_stars: minStars || "0",
  });
  if (maxStars) rankedParams.set("max_stars", maxStars);
  if (params.get("run_id")) rankedParams.set("run_id", params.get("run_id")!);
  const rankings = useLoad<Ranking>("/api/rankings?" + rankedParams, revision);
  const news = useLoad<NewsResult>(
    "/api/news?" +
      new URLSearchParams({
        window: isNews ? window : "7d",
        topic: isAgents ? "agents" : topic,
        sort,
        source,
        q: isNews ? query : "",
      }),
    revision,
  );
  const resources = useLoad<{
    items: Resource[];
    total: number;
    matching_source_total: number;
  }>(
    "/api/agent-resources?" +
      new URLSearchParams({
        q: query,
        kind: ["skill", "plugin", "mcp"].includes(agentType) ? agentType : "",
        offset: String((resourcePage - 1) * 100),
      }),
    revision,
  );
  const archives = useLoad<{
    items: {
      id: string;
      created_at: string;
      window_days: number;
      algorithm: string;
    }[];
  }>("/api/archives", revision);
  const cfg = config.data;
  const matchesReading = (item: News) => {
    const state = readStatus(reading[item.id], item.content_hash);
    return (
      readingFilter === "all" ||
      (readingFilter === "unread" ? state !== "read" : state === readingFilter)
    );
  };
  const visibleNews = news.data?.items.filter(matchesReading) || [];
  const visibleUnknown = news.data?.unknown_time.filter(matchesReading) || [];

  function navigate(url: string) {
    history.pushState({}, "", url);
    setRoute(location.pathname + location.search);
    setSidebar(false);
    globalThis.scrollTo({ top: 0 });
  }
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (key !== "page") next.delete("page");
    value ? next.set(key, value) : next.delete(key);
    if (
      key === "view" &&
      value === "resources" &&
      !["skill", "plugin", "mcp"].includes(next.get("agent_type") || "")
    )
      next.delete("agent_type");
    const url = path + (next.size ? "?" + next : "");
    if (["q", "min_stars", "max_stars"].includes(key)) {
      history.replaceState({}, "", url);
      setRoute(location.pathname + location.search);
    } else navigate(url);
  }
  useEffect(() => {
    const handler = () => setRoute(location.pathname + location.search);
    addEventListener("popstate", handler);
    return () => removeEventListener("popstate", handler);
  }, []);
  useEffect(() => {
    document.title = `GitHub Rank · ${isNews ? "AI 前沿资讯" : isAgents ? "AI Agent 专栏" : isSaved ? "我的收藏" : "发现值得关注的开源项目"}`;
  }, [route]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 3000);
    return () => clearTimeout(timer);
  }, [notice]);
  function commitLibrary(
    state: LibraryState,
    message: string,
    recover = false,
  ) {
    if (localLibrary.error && !recover) {
      setNotice("原记录无法读取，请在收藏页导出原始记录或导入有效备份。");
      return;
    }
    try {
      writeLibrary(localStorage, state);
      setLocalLibrary({ state });
      setNotice(message);
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message + "，原记录已保留"
          : "存储失败，原记录已保留",
      );
    }
  }
  function toggle(type: Saved["type"], id: string, data: Saved["data"]) {
    const exists = saved.some((s) => s.type === type && s.id === id);
    try {
      const next = exists
        ? saved.filter((s) => !(s.type === type && s.id === id))
        : [...saved, makeEntry(type, id, data)];
      if (next.length > 500) throw new Error("最多保留 500 条收藏");
      commitLibrary(
        { ...localLibrary.state, entries: next },
        exists ? "已取消收藏" : "已保存到本机收藏",
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "收藏未保存");
    }
  }
  function markArticle(item: News) {
    commitLibrary(
      markRead(
        localLibrary.state,
        item.id,
        item.version_view?.content_hash || item.content_hash,
      ),
      "已标记当前查看版本为已读",
    );
  }
  function markUnread(id: string) {
    const next = { ...reading };
    delete next[id];
    commitLibrary({ ...localLibrary.state, reading: next }, "已标为未读");
  }
  async function importBackup(file: File) {
    try {
      if (file.size > MAX_BACKUP_BYTES) throw new Error("备份超过 4 MB");
      const next = mergeLibrary(
        localLibrary.state,
        parseLibrary(await file.text()),
      );
      commitLibrary(next, "备份已合并到本机收藏", true);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "导入失败，原记录已保留",
      );
    }
  }
  const readingTabs = (
    <div className="reading-tabs" aria-label="阅读状态筛选">
      {[
        ["all", "全部"],
        ["unread", "未读 / 有更新"],
        ["read", "已读"],
        ["updated", "有更新"],
      ].map(([value, label]) => (
        <button
          key={value}
          className={readingFilter === value ? "active" : ""}
          onClick={() => filter("read", value === "all" ? "" : value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
  const hasSaved = (type: string, id: string) =>
    saved.some((s) => s.type === type && s.id === id);
  const saveButton = (type: Saved["type"], id: string, data: Saved["data"]) => (
    <button
      className={"icon-btn save " + (hasSaved(type, id) ? "selected" : "")}
      aria-label={hasSaved(type, id) ? "取消收藏" : "收藏"}
      onClick={() => toggle(type, id, data)}
    >
      <Bookmark size={17} fill={hasSaved(type, id) ? "currentColor" : "none"} />
    </button>
  );
  const repoCard = (repo: Repo) => (
    <article className="repo-card" key={repo.id}>
      <div className="card-top">
        <span className="repo-avatar">
          {repo.full_name.split("/")[0].slice(0, 2).toUpperCase()}
        </span>
        <span className="eyebrow">
          {cfg?.categories[repo.category] || repo.category}
        </span>
        {saveButton("project", String(repo.id), repo)}
      </div>
      <button
        className="repo-title"
        onClick={() => navigate("/projects/" + repo.full_name)}
      >
        <span>{repo.full_name.split("/")[0]} /</span>
        <strong>{repo.full_name.split("/")[1]}</strong>
        <ArrowUpRight size={17} />
      </button>
      <p className="repo-description">{repo.summary_zh || repo.description}</p>
      <SummaryEvidence meta={repo.summary_meta} />
      <div className="repo-tags">
        {repo.classification?.method === "manual" && <span>人工修订</span>}
        {repo.agent_types.slice(0, 2).map((t) => (
          <span key={t}>{cfg?.agent_types[t] || t}</span>
        ))}
        {repo.topics
          .filter((t) => !repo.agent_types.includes(t))
          .slice(0, repo.agent_types.length ? 1 : 3)
          .map((t) => (
            <span key={t}>{t}</span>
          ))}
      </div>
      <div className="card-bottom">
        <span className="language">
          <i style={{ background: colors[repo.language || ""] || "#a0a7b3" }} />
          {repo.language || "未标注"}
        </span>
        <span>
          <Star size={14} />
          {number(repo.stars)}
        </span>
        <span>
          <GitFork size={14} />
          {number(repo.forks)}
        </span>
        {repo.delta_stars != null ? (
          <span className="growth">+{number(repo.delta_stars)}</span>
        ) : (
          <span className="observing">观察中</span>
        )}
      </div>
      {repo.potential_score != null && (
        <div className="potential-line">
          <Sparkles size={13} /> 潜力分 {repo.potential_score}{" "}
          <small>· {repo.score_scope}</small>
        </div>
      )}
    </article>
  );
  const newsCard = (item: News, compact = false) => (
    <article key={item.id} className={compact ? "news-compact" : "news-card"}>
      <div className="news-meta">
        <span className={"topic " + item.topic}>
          {cfg?.topics[item.topic] || item.topic}
        </span>
        <span>{item.source_name}</span>
        <span>
          {item.published_at
            ? item.published_precision === "day"
              ? item.published_at.slice(5, 10).replace("-", "/") + "（仅日期）"
              : time(item.published_at)
            : "发布时间未知"}
        </span>
        <a
          className="news-original"
          href={safeUrl(item.url)}
          target="_blank"
          rel="noreferrer"
        >
          原文 <ArrowUpRight size={12} />
        </a>
        {!compact && saveButton("news", item.id, item)}
        {!compact && (
          <ReadButton
            mark={reading[item.id]}
            digest={item.content_hash}
            onRead={() => markArticle(item)}
            onUnread={() => markUnread(item.id)}
          />
        )}
      </div>
      <button
        className="news-title"
        onClick={() => navigate("/news/" + item.id)}
      >
        {item.title_zh || item.title}
        <ArrowUpRight size={16} />
      </button>
      {!compact && (item.summary_zh || item.summary) && (
        <p>
          {(item.summary_zh || item.summary).slice(0, 320)}
          {(item.summary_zh || item.summary).length > 320 ? "…" : ""}
        </p>
      )}
      {!compact && <SummaryEvidence meta={item.summary_meta} />}
      {!compact && (
        <div className="news-footer">
          <span>
            {item.is_preprint
              ? "预印本 · 未标注同行评审"
              : item.summary_zh
                ? "AI 中文摘要 · 保留原文"
                : "来源原文摘要"}
          </span>
          {!!item.related_reports?.length && (
            <span>
              {item.source_count ? item.source_count + " 个来源 · " : ""}
              {item.report_count || item.related_reports.length + 1} 篇报道
            </span>
          )}
          {item.related_repositories.slice(0, 2).map((url) => (
            <a key={url} href={safeUrl(url)} target="_blank" rel="noreferrer">
              <Github size={13} />
              {url.replace("https://github.com/", "")}
            </a>
          ))}
        </div>
      )}
    </article>
  );
  const resourceCard = (r: Resource) => (
    <article className="resource-card" key={r.id}>
      <div className="card-top">
        <span className="resource-icon">
          <Layers3 size={20} />
        </span>
        <span className="eyebrow">
          {r.kind === "skill"
            ? "AGENT SKILL"
            : r.kind === "mcp"
              ? "MCP SERVER"
              : "PLUGIN"}
        </span>
        {saveButton("resource", r.id, r)}
      </div>
      <button
        onClick={() => navigate("/resources/" + r.id)}
        className="resource-title"
      >
        {r.name}
        <ArrowUpRight size={16} />
      </button>
      <p>{r.summary_zh || r.description}</p>
      <SummaryEvidence meta={r.summary_meta} />
      <div className="resource-labels">
        <span>
          {r.verification_status === "current"
            ? "本轮已核对"
            : r.verification_status === "previous"
              ? "保留上次记录"
              : "待重新扫描"}
        </span>
        {(r.duplicate_count || 0) > 1 && (
          <span>{r.duplicate_count} 个同内容来源</span>
        )}
        <a href={safeUrl(r.url)} target="_blank" rel="noreferrer">
          原文件 <ArrowUpRight size={12} />
        </a>
      </div>
      <div className="resource-repo">
        <Github size={13} />
        {r.repo_name}
      </div>
      <div className="resource-foot">
        <span>
          {r.compatibility_evidence?.length
            ? "作者声明，未测试"
            : r.content_hash
              ? "未声明兼容要求"
              : "待核对兼容声明"}
        </span>
        <span>
          仓库 <Star size={12} />
          {number(r.repository_stars || 0)}
        </span>
      </div>
    </article>
  );
  const formal = rankings.data?.items || [],
    observing = rankings.data?.observing || [];
  const resolvedById = new Map(
    resolvedLibrary.items.map((item) => [item.type + ":" + item.id, item]),
  );
  const visibleSaved = saved.filter((entry) => {
    if (savedType !== "all" && entry.type !== savedType) return false;
    const current = resolvedById.get(entry.type + ":" + entry.id)?.data;
    const data = current || entry.data;
    const text = [
      "full_name" in data ? data.full_name : "",
      "name" in data ? data.name : "",
      "title" in data ? data.title : "",
      "description" in data ? data.description : "",
      "summary" in data ? data.summary : "",
    ]
      .join(" ")
      .toLowerCase();
    if (query && !text.includes(query.toLowerCase())) return false;
    return (
      entry.type !== "news" ||
      savedType !== "news" ||
      matchesReading(data as News)
    );
  });
  function savedCard(entry: Saved) {
    const resolved = resolvedById.get(entry.type + ":" + entry.id);
    const current = resolved?.data;
    return (
      <section
        className={"saved-entry " + (entry.type === "news" ? "saved-news" : "")}
        key={entry.type + ":" + entry.id}
      >
        <div className="saved-entry-meta">
          <span>
            {entry.saved_at
              ? "收藏于 " + time(entry.saved_at)
              : "旧收藏 · 保存时间未记录"}
          </span>
          <span
            className={resolved?.state === "excluded" ? "library-warning" : ""}
          >
            {resolved?.state === "excluded"
              ? "已从公开发现页排除"
              : current
                ? "当前库内记录"
                : resolved?.state === "missing"
                  ? "库中未找到"
                  : resolvedLibrary.loading
                    ? "正在更新"
                    : "暂时无法更新"}
          </span>
        </div>
        {current ? (
          entry.type === "project" ? (
            repoCard(current as Repo)
          ) : entry.type === "resource" ? (
            resourceCard(current as Resource)
          ) : (
            newsCard(current as News)
          )
        ) : (
          <article className="library-snapshot">
            <div className="card-top">
              <span className="eyebrow">保存时的参考快照</span>
              {saveButton(entry.type, entry.id, entry.data)}
            </div>
            <h3>
              {entry.data.full_name || entry.data.name || entry.data.title}
            </h3>
            <p>
              {entry.data.description || entry.data.summary || "未保存介绍"}
            </p>
            <a href={safeUrl(entry.data.url)} target="_blank" rel="noreferrer">
              保存时的来源链接 <ArrowUpRight size={13} />
            </a>
            <small>
              链接可能已改名或失效；未将旧指标和摘要作为当前数据展示。
            </small>
          </article>
        )}
      </section>
    );
  }
  const displayedRepos = isHome
    ? (formal.length ? formal : observing).slice(0, 6)
    : formal;
  const successSources = (sources.data?.items || []).filter(
    (s) => s.status === "ok" && s.enabled !== false,
  ).length;
  const nav = [
    { name: "发现", path: "/", icon: Compass, active: isHome },
    {
      name: "热门榜单",
      path: "/rankings?kind=hot",
      icon: Flame,
      active: path === "/rankings" && kind === "hot",
    },
    {
      name: "潜力项目",
      path: "/rankings?kind=potential",
      icon: TrendingUp,
      active: path === "/rankings" && kind === "potential",
    },
    { name: "AI Agent 专栏", path: "/agents", icon: Bot, active: isAgents },
    { name: "AI 前沿资讯", path: "/news", icon: Newspaper, active: isNews },
  ];

  return (
    <div className="app-shell">
      {sidebar && (
        <div className="sidebar-backdrop" onClick={() => setSidebar(false)} />
      )}
      <aside className={"sidebar " + (sidebar ? "open" : "")}>
        <button className="brand" onClick={() => navigate("/")}>
          <span className="brand-mark">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>
            GitHub<span className="brand-light">Rank</span>
            <small>发现开源的下一站</small>
          </span>
        </button>
        <div className="nav-label">探索 / EXPLORE</div>
        <nav>
          {nav.map((n) => (
            <button
              key={n.name}
              className={n.active ? "active" : ""}
              onClick={() => navigate(n.path)}
            >
              <n.icon size={19} />
              <span>{n.name}</span>
              {n.active && <ChevronRight size={14} />}
              {n.name === "AI 前沿资讯" && !n.active && (
                <span className="new-tag">NEW</span>
              )}
            </button>
          ))}
        </nav>
        <div className="nav-divider" />
        <div className="nav-label">我的空间</div>
        <nav>
          <button
            className={isSaved ? "active" : ""}
            onClick={() => navigate("/saved")}
          >
            <Bookmark size={18} />
            <span>我的收藏</span>
            <small>{saved.length}</small>
          </button>
          <button
            className={isArchive ? "active" : ""}
            onClick={() => navigate("/archive")}
          >
            <History size={18} />
            <span>历史榜单</span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="source-note">
            <span className="status-dot" />
            关注真实数据<small>每个趋势，都有迹可循。</small>
          </div>
          <button onClick={() => setSourcesOpen(true)}>
            <Radio size={16} />
            数据源与同步状态
            <ArrowUpRight size={14} />
          </button>
          <div className="sidebar-version">
            GitHub Rank <span>v0.1 · LOCAL</span>
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button
            className="icon-btn mobile-menu"
            aria-label="打开导航"
            onClick={() => setSidebar(true)}
          >
            <Menu size={22} />
          </button>
          <div className="breadcrumbs">
            探索 <ChevronRight size={13} />
            <span>
              {isNews
                ? "AI 前沿资讯"
                : isAgents
                  ? "AI Agent 专栏"
                  : isSaved
                    ? "我的收藏"
                    : isArchive
                      ? "历史榜单"
                      : isDetail
                        ? isNewsDetail
                          ? "资讯详情"
                          : isResourceDetail
                            ? "资源详情"
                            : "项目详情"
                        : isHome
                          ? "发现"
                          : kind === "potential"
                            ? "潜力项目"
                            : "热门榜单"}
            </span>
          </div>
          <div className="topbar-right">
            <span className="local-tag">
              <span className="status-dot" /> 本地工作台
            </span>
            <button
              className="icon-btn"
              title="重新读取本地数据"
              aria-label="重新读取本地数据"
              onClick={() => setRevision((n) => n + 1)}
            >
              <RefreshCw size={16} />
            </button>
            <button
              className="profile"
              onClick={() => setSourcesOpen(true)}
              aria-label="数据状态"
            >
              G
            </button>
          </div>
        </header>
        <div className="content">
          <section className="page-heading">
            <div>
              <div className="heading-kicker">
                <span className="green-line" />
                {isNews
                  ? "THE AI FRONTIER"
                  : isAgents
                    ? "BUILD WITH AGENTS"
                    : isSaved
                      ? "YOUR COLLECTION"
                      : isArchive
                        ? "TREND ARCHIVE"
                        : "YOUR OPEN SOURCE RADAR"}
              </div>
              <h1>
                {isNews ? (
                  "AI 前沿资讯"
                ) : isAgents ? (
                  "AI Agent，能力的下一步。"
                ) : isSaved ? (
                  "留住每一次发现。"
                ) : isArchive ? (
                  "回看趋势的每一步。"
                ) : isDetail ? (
                  "从发现，到深入了解。"
                ) : isHome ? (
                  <>
                    好项目，值得更早发现<span>。</span>
                  </>
                ) : kind === "potential" ? (
                  "发现正在积蓄势能的项目。"
                ) : (
                  "看看开源世界正在发生什么。"
                )}
              </h1>
              <p>
                {isNews
                  ? "聚合一手发布、研究进展与开源动态，快速了解 AI 正在发生什么。"
                  : isAgents
                    ? "框架、编程助手、MCP、插件与 Skills，在这里连接你的下一种能力。"
                    : isSaved
                      ? "收藏保存在当前浏览器，随时回到值得继续探索的项目与资讯。"
                      : isArchive
                        ? "每次发布保留独立快照，统计周期和算法版本都可以追溯。"
                        : isDetail
                          ? "原始介绍、实测指标与资源链接，帮助你判断是否值得继续探索。"
                          : "追踪近期热门，寻找早期潜力，让每一次探索都有方向。"}
              </p>
            </div>
            <button
              className="outline-button heading-action"
              onClick={() => setSourcesOpen(true)}
            >
              <Radio size={15} />
              数据来源
              <ArrowUpRight size={14} />
            </button>
          </section>
          {status.error && (
            <div className="error-banner">
              <AlertCircle size={18} />
              后端暂不可用：{status.error}。请确认 API 服务已启动。
              <button onClick={() => setRevision((n) => n + 1)}>重试</button>
            </div>
          )}

          {isHome && (
            <>
              <section className="stats-grid">
                {[
                  {
                    label: "正在追踪",
                    value: status.data?.counts.repositories || 0,
                    suffix: "个项目",
                    icon: Github,
                    note: "持续积累每日快照",
                    color: "green",
                  },
                  {
                    label: "本周入榜",
                    value: rankings.data?.total || 0,
                    suffix: "个项目",
                    icon: TrendingUp,
                    note: "完整 7 天观测后入榜",
                    color: "orange",
                  },
                  {
                    label: "Agent 资源",
                    value: status.data?.counts.resources || 0,
                    suffix: "项能力",
                    icon: Bot,
                    note: "Skills 与插件的原始路径",
                    color: "violet",
                  },
                  {
                    label: "前沿资讯",
                    value: status.data?.counts.news || 0,
                    suffix: "条记录",
                    icon: Newspaper,
                    note: `${successSources} 个来源同步成功`,
                    color: "blue",
                  },
                ].map((s) => (
                  <div className="stat-card" key={s.label}>
                    <div className="stat-label">
                      {s.label}
                      <span className={"stat-icon " + s.color}>
                        <s.icon size={18} />
                      </span>
                    </div>
                    <div className="stat-value">
                      {s.value}
                      <small>{s.suffix}</small>
                    </div>
                    <div className="stat-note">
                      <span className="tiny-dot" />
                      {s.note}
                    </div>
                  </div>
                ))}
              </section>
              <div className="dashboard-grid">
                <section>
                  <div className="section-heading">
                    <div>
                      <h2>
                        <Flame size={20} className="orange-text" />
                        {formal.length ? "本周热门项目" : "从这里开始探索"}
                      </h2>
                      <p>
                        {formal.length
                          ? "最近 7 天净增长，发现持续获得关注的项目。"
                          : "真实项目已开始观察，完整历史积累后发布增长榜。"}
                      </p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => navigate("/rankings")}
                    >
                      查看全部
                      <ArrowRight size={14} />
                    </button>
                  </div>
                  <div className="category-chips">
                    <button
                      className={!category ? "active" : ""}
                      onClick={() => filter("category", "")}
                    >
                      全部领域
                    </button>
                    {Object.entries(cfg?.categories || {})
                      .filter(([k]) =>
                        ["ai", "devtools", "frontend", "productivity"].includes(
                          k,
                        ),
                      )
                      .map(([k, v]) => (
                        <button
                          className={category === k ? "active" : ""}
                          key={k}
                          onClick={() => filter("category", k)}
                        >
                          {v}
                        </button>
                      ))}
                  </div>
                  <Loading state={rankings} />
                  <div className="repo-grid">
                    {displayedRepos.map(repoCard)}
                  </div>
                  {!rankings.loading && !displayedRepos.length && (
                    <Empty
                      title="发现从第一条真实数据开始"
                      description="运行采集任务后，项目会出现在这里。增长榜会等待完整历史，不使用演示数据。"
                    />
                  )}
                  <div className="observing-foot">
                    <Clock3 size={14} />
                    仓库快照 {time(status.data?.last_snapshot)} · 当前总 Star
                    仅供参考
                  </div>
                  <div className="agent-callout">
                    <div className="agent-callout-icon">
                      <Bot size={28} />
                    </div>
                    <div>
                      <span>THE AGENT ECOSYSTEM</span>
                      <h3>把下一种能力，加入你的工具箱。</h3>
                      <p>探索 Agent、MCP 与 Skills，找到适合你的构建方式。</p>
                    </div>
                    <button
                      onClick={() => navigate("/agents")}
                      aria-label="探索 AI Agent 专栏"
                    >
                      <ArrowUpRight size={22} />
                    </button>
                  </div>
                </section>
                <aside className="news-panel">
                  <div className="section-heading">
                    <h2>
                      <Radio size={18} className="green-text" />
                      AI 前沿速览
                    </h2>
                    <span className="live-pill">
                      {runtime.data?.scheduler.online
                        ? "定时采集中"
                        : "本地资讯"}
                    </span>
                  </div>
                  <div className="news-panel-subtitle">
                    近 7 天 · 官方发布与研究进展
                  </div>
                  <Loading state={news} />
                  {news.data?.items.slice(0, 5).map((n) => newsCard(n, true))}
                  {!news.loading && !news.data?.items.length && (
                    <Empty
                      title="该周期暂无已知时间的资讯"
                      description="可前往资讯页查看时间未知的来源内容。"
                      compact
                    />
                  )}
                  <button
                    className="news-panel-more"
                    onClick={() => navigate("/news")}
                  >
                    浏览全部资讯
                    <ArrowRight size={15} />
                  </button>
                  <div className="source-mini">
                    <div className="source-mini-icons">
                      <span>A</span>
                      <span>G</span>
                      <span>H</span>
                      <span>ar</span>
                    </div>
                    <span>
                      一手来源，保留原文。
                      <button onClick={() => setSourcesOpen(true)}>
                        查看同步状态
                        <ArrowUpRight size={11} />
                      </button>
                    </span>
                  </div>
                </aside>
              </div>
            </>
          )}

          {!isHome && !isDetail && !isSaved && !isArchive && (
            <>
              <div className="filter-bar">
                <div className="segmented">
                  {isNews ? (
                    <>
                      <button
                        className={sort === "latest" ? "active" : ""}
                        onClick={() => filter("sort", "latest")}
                      >
                        <Clock3 size={14} />
                        最新
                      </button>
                      <button
                        className={sort === "important" ? "active" : ""}
                        onClick={() => filter("sort", "important")}
                      >
                        <Sparkles size={14} />
                        重点
                      </button>
                    </>
                  ) : isAgents ? (
                    <>
                      <button
                        className={!resourcesView ? "active" : ""}
                        onClick={() => filter("view", "")}
                      >
                        仓库排行
                      </button>
                      <button
                        className={resourcesView ? "active" : ""}
                        onClick={() => filter("view", "resources")}
                      >
                        Skills / 插件 / MCP
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className={kind === "hot" ? "active" : ""}
                        onClick={() => filter("kind", "hot")}
                      >
                        <Flame size={14} />
                        热门
                      </button>
                      <button
                        className={kind === "potential" ? "active" : ""}
                        onClick={() => filter("kind", "potential")}
                      >
                        <TrendingUp size={14} />
                        潜力
                      </button>
                    </>
                  )}
                </div>
                <div className="filter-right">
                  <select
                    aria-label="统计周期"
                    value={window}
                    onChange={(e) => filter("window", e.target.value)}
                  >
                    {isNews && <option value="24h">最近 24 小时</option>}
                    <option value="7d">最近 7 天</option>
                    <option value="30d">最近 30 天</option>
                    {isNews && <option value="all">全部已采集</option>}
                  </select>
                  <div className="search-input">
                    <Search size={15} />
                    <input
                      aria-label="搜索"
                      placeholder={
                        isNews ? "搜索 AI 资讯…" : "搜索项目或关键词…"
                      }
                      value={query}
                      onChange={(e) => filter("q", e.target.value)}
                    />
                    {query && (
                      <button
                        onClick={() => filter("q", "")}
                        aria-label="清除搜索"
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                  <button
                    className={"outline-button " + (advanced ? "pressed" : "")}
                    onClick={() => setAdvanced(!advanced)}
                  >
                    <SlidersHorizontal size={15} />
                    筛选
                  </button>
                </div>
              </div>
              <div className="category-chips">
                <button
                  className={
                    !(isNews ? topic : isAgents ? agentType : category)
                      ? "active"
                      : ""
                  }
                  onClick={() =>
                    filter(
                      isNews ? "topic" : isAgents ? "agent_type" : "category",
                      "",
                    )
                  }
                >
                  全部{isNews ? "资讯" : isAgents ? "类型" : "领域"}
                </button>
                {Object.entries(
                  isNews
                    ? cfg?.topics || {}
                    : isAgents
                      ? cfg?.agent_types || {}
                      : cfg?.categories || {},
                )
                  .filter(
                    ([k]) =>
                      !resourcesView || ["skill", "plugin", "mcp"].includes(k),
                  )
                  .map(([k, v]) => (
                    <button
                      key={k}
                      className={
                        (isNews ? topic : isAgents ? agentType : category) === k
                          ? "active"
                          : ""
                      }
                      onClick={() =>
                        filter(
                          isNews
                            ? "topic"
                            : isAgents
                              ? "agent_type"
                              : "category",
                          k,
                        )
                      }
                    >
                      {v}
                    </button>
                  ))}
              </div>
              {advanced && (
                <div className="advanced-filters">
                  {isNews ? (
                    <label>
                      资讯来源
                      <select
                        value={source}
                        onChange={(e) => filter("source", e.target.value)}
                      >
                        <option value="">全部来源</option>
                        {sources.data?.items.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <>
                      <label>
                        主分类
                        <select
                          value={category}
                          onChange={(e) => filter("category", e.target.value)}
                        >
                          <option value="">全部分类</option>
                          {Object.entries(cfg?.categories || {}).map(
                            ([k, v]) => (
                              <option key={k} value={k}>
                                {v}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      {!resourcesView && (
                        <>
                          <label>
                            语言
                            <select
                              aria-label="项目语言"
                              value={language}
                              onChange={(e) =>
                                filter("language", e.target.value)
                              }
                            >
                              <option value="">全部语言</option>
                              {cfg?.languages?.map((l) => (
                                <option key={l} value={l}>
                                  {l}
                                </option>
                              ))}
                              <option value="__unknown__">未标注</option>
                            </select>
                          </label>
                          <label>
                            Star 区间
                            <input
                              aria-label="最低 Star"
                              type="number"
                              min="0"
                              placeholder="不限"
                              value={minStars}
                              onChange={(e) =>
                                filter("min_stars", e.target.value)
                              }
                            />
                            <span>—</span>
                            <input
                              aria-label="最高 Star"
                              type="number"
                              min="0"
                              placeholder="不限"
                              value={maxStars}
                              onChange={(e) =>
                                filter("max_stars", e.target.value)
                              }
                            />
                          </label>
                        </>
                      )}
                      <span>
                        <CircleHelp size={15} />
                        按真实观测周期排行；无历史项目在观察列表中。
                      </span>
                    </>
                  )}
                </div>
              )}
            </>
          )}

          {(path === "/rankings" || (isAgents && !resourcesView)) && (
            <>
              <div className="list-header">
                <span>
                  {rankings.data?.total || 0} 个正式入榜项目 ·{" "}
                  {window === "30d" ? "30" : "7"} 天观测窗口
                </span>
                <a
                  className="text-button"
                  href={
                    "/api/exports?" +
                    new URLSearchParams({
                      ...Object.fromEntries(rankedParams),
                      format: "markdown",
                    })
                  }
                >
                  <ArrowDownToLine size={14} />
                  导出榜单
                </a>
              </div>
              <Loading state={rankings} />
              {rankings.data?.stale && (
                <div className="info-banner">
                  当前端点已超过 36 小时，请检查采集任务。
                </div>
              )}
              <div className="repo-grid wide">{formal.map(repoCard)}</div>
              {!rankings.loading && !formal.length && (
                <div className="info-banner">
                  <Clock3 size={19} />
                  <div>
                    <strong>趋势需要时间，让数据先积累。</strong>
                    <p>
                      {kind === "potential"
                        ? "潜力分需要双周期历史和至少 30 个合格参照样本。"
                        : "正式榜单需要完整的起止观测端点。"}
                      下方观察列表按当前总 Star 排序。
                    </p>
                  </div>
                </div>
              )}
              {!!observing.length && (
                <>
                  <div className="section-heading observing-heading">
                    <h2>
                      项目观察列表 <span>{rankings.data?.observing_total}</span>
                    </h2>
                    <small>当前总 Star 排序</small>
                  </div>
                  <div className="repo-grid wide">
                    {observing.map(repoCard)}
                  </div>
                </>
              )}
              {!rankings.loading && !formal.length && !observing.length && (
                <Empty
                  title="还没有匹配的项目"
                  description="试试其他分类或关键词，也可以先运行一次采集任务。"
                />
              )}
            </>
          )}
          {resourcesView && (
            <>
              <div className="info-banner">
                <Layers3 size={19} />
                <div>
                  <strong>每个资源，都保留它的原始出处。</strong>
                  <p>
                    这里展示关联仓库的 Star，不将其作为单个 Skill
                    的使用或安装量。
                  </p>
                </div>
              </div>
              <Loading state={resources} />
              <p className="muted-note">
                {resources.data?.total || 0} 项资源 · 匹配{" "}
                {resources.data?.matching_source_total || 0}{" "}
                个来源文件；相同类型与文件内容合并展示，详情可查看全部来源。
              </p>
              <div className="repo-grid wide">
                {resources.data?.items.map(resourceCard)}
              </div>
              {(resources.data?.total || 0) > 100 && (
                <div className="resource-pagination">
                  <button
                    className="outline-button"
                    disabled={resourcePage <= 1}
                    onClick={() => filter("page", String(resourcePage - 1))}
                  >
                    上一页
                  </button>
                  <span>
                    第 {resourcePage} /{" "}
                    {Math.ceil((resources.data?.total || 0) / 100)} 页
                  </span>
                  <button
                    className="outline-button"
                    disabled={
                      resourcePage * 100 >= (resources.data?.total || 0)
                    }
                    onClick={() => filter("page", String(resourcePage + 1))}
                  >
                    下一页
                  </button>
                </div>
              )}
              {!resources.loading && !resources.data?.items.length && (
                <Empty
                  title="暂无匹配的资源"
                  description="资源扫描需要访问仓库目录和元数据；可在数据状态中检查扫描情况。"
                />
              )}
            </>
          )}
          {isNews && (
            <>
              {readingTabs}
              <div className="list-header">
                <span>{news.data?.total || 0} 条资讯 · 按原始发布时间筛选</span>
                <button
                  className="text-button"
                  onClick={() => setSourcesOpen(true)}
                >
                  <Radio size={14} />
                  来源状态
                </button>
              </div>
              <Loading state={news} />
              {readingFilter !== "all" && (
                <p className="muted-note">
                  当前已加载内容中匹配 {visibleNews.length} 条近期资讯、
                  {visibleUnknown.length}{" "}
                  条时间待确认资讯。阅读状态仅存于本机，“未读”包含有更新的记录。
                </p>
              )}
              <div className="news-list">
                {visibleNews.map((n) => newsCard(n))}
              </div>
              {!news.loading && !visibleNews.length && (
                <Empty
                  title="当前筛选下没有匹配的资讯"
                  description="试试其他阅读状态、更长的时间范围，或查看下方发布时间待确认的内容。"
                />
              )}
              {!!news.data?.unknown_time.length && (
                <>
                  <div className="section-heading observing-heading">
                    <div>
                      <h2>
                        发布时间待确认{" "}
                        <span>{news.data.unknown_time_total}</span>
                      </h2>
                      <p>
                        来源缺少精确发布时间，这些内容不计入上方的近期资讯。
                      </p>
                    </div>
                  </div>
                  <div className="news-list">
                    {visibleUnknown.map((n) => newsCard(n))}
                  </div>
                </>
              )}
            </>
          )}
          {isSaved && (
            <>
              <section className="library-toolbar">
                <div>
                  <h2>留住发现，接着阅读</h2>
                  <p>
                    收藏按 ID
                    更新库内内容；保存时的快照可作参考。仅保存在当前浏览器与站点地址下。
                  </p>
                </div>
                <div className="library-actions">
                  <button
                    className="outline-button"
                    disabled={!!localLibrary.error}
                    onClick={() =>
                      downloadText(
                        "github-rank-library.json",
                        serializeLibrary(localLibrary.state),
                      )
                    }
                  >
                    <ArrowDownToLine size={14} />
                    备份 JSON
                  </button>
                  <button
                    className="outline-button"
                    disabled={!!localLibrary.error}
                    onClick={() =>
                      downloadText(
                        "github-rank-saved.md",
                        libraryMarkdown(localLibrary.state),
                        "text/markdown;charset=utf-8",
                      )
                    }
                  >
                    导出 Markdown
                  </button>
                  <label className="outline-button import-backup">
                    导入备份
                    <input
                      type="file"
                      accept=".json,application/json"
                      aria-label="导入收藏备份"
                      onChange={(e) => {
                        const file = e.currentTarget.files?.[0];
                        if (file) void importBackup(file);
                        e.currentTarget.value = "";
                      }}
                    />
                  </label>
                </div>
                <small>
                  备份含收藏与阅读记录；导入会合并并保留本机已有收藏。最多 500
                  条收藏、最近 5000 条阅读记录。
                </small>
              </section>
              {localLibrary.error && (
                <div className="curation-notice" role="alert">
                  <AlertCircle size={17} />
                  <div>
                    本机记录读取失败：{localLibrary.error}
                    。原始内容仍保留，可导出排查后导入有效备份恢复。
                  </div>
                  {localLibrary.raw && (
                    <button
                      className="text-button"
                      onClick={() =>
                        downloadText(
                          "github-rank-library-unreadable.txt",
                          localLibrary.raw!,
                          "text/plain",
                        )
                      }
                    >
                      导出原始记录
                    </button>
                  )}
                </div>
              )}
              <div className="library-filters">
                <div className="reading-tabs" aria-label="收藏类型筛选">
                  {[
                    ["all", "全部"],
                    ["project", "项目"],
                    ["resource", "Agent 资源"],
                    ["news", "资讯"],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      className={savedType === value ? "active" : ""}
                      onClick={() =>
                        filter("type", value === "all" ? "" : value)
                      }
                    >
                      {label}{" "}
                      <small>
                        {value === "all"
                          ? saved.length
                          : saved.filter((s) => s.type === value).length}
                      </small>
                    </button>
                  ))}
                </div>
                <label className="library-search">
                  <Search size={15} />
                  <input
                    aria-label="搜索收藏"
                    value={query}
                    placeholder="搜索收藏"
                    onChange={(e) => filter("q", e.target.value)}
                  />
                </label>
              </div>
              {savedType === "news" && readingTabs}
              {resolvedLibrary.loading && (
                <p className="muted-note" role="status">
                  正在读取收藏的最新记录…
                </p>
              )}
              {resolvedLibrary.error && (
                <p className="library-warning" role="alert">
                  {resolvedLibrary.error}
                </p>
              )}
              {!saved.length && (
                <Empty
                  title="下一次发现，从这里继续"
                  description="点击项目、Skill 或资讯卡片上的收藏按钮，即可保存在当前浏览器。"
                />
              )}
              {!!saved.length && !visibleSaved.length && (
                <Empty
                  title="没有匹配的收藏"
                  description="试试其他类型、关键词或阅读状态。"
                />
              )}
              <div className="repo-grid wide">
                {visibleSaved.filter((s) => s.type !== "news").map(savedCard)}
              </div>
              <div className="news-list saved-news-list">
                {visibleSaved.filter((s) => s.type === "news").map(savedCard)}
              </div>
            </>
          )}
          {isArchive && (
            <>
              <Loading state={archives} />
              <div className="archive-list">
                {archives.data?.items.map((run) => (
                  <button
                    key={run.id}
                    onClick={() =>
                      navigate(
                        "/rankings?" +
                          new URLSearchParams({
                            run_id: run.id,
                            window: run.window_days + "d",
                          }),
                      )
                    }
                  >
                    <span className="archive-icon">
                      <History size={20} />
                    </span>
                    <div>
                      <strong>最近 {run.window_days} 天 · 榜单快照</strong>
                      <small>
                        {time(run.created_at)} · {run.algorithm}
                      </small>
                    </div>
                    <span className="archive-view">
                      查看快照
                      <ArrowRight size={16} />
                    </span>
                  </button>
                ))}
              </div>
              {!archives.loading && !archives.data?.items.length && (
                <Empty
                  title="还没有已发布快照"
                  description="采集任务结束后会保存独立的榜单快照，包括当时的观察状态。"
                />
              )}
            </>
          )}
          {isNewsDetail && (
            <NewsDetail
              path={path}
              versionHash={params.get("version_hash") || ""}
              revision={revision}
              cfg={cfg}
              navigate={navigate}
              saveButton={saveButton}
              reading={reading}
              onMarkRead={markArticle}
              onMarkUnread={markUnread}
            />
          )}
          {isResourceDetail && (
            <ResourceDetail
              path={path}
              revision={revision}
              navigate={navigate}
              saveButton={saveButton}
            />
          )}
          {isProjectDetail && (
            <ProjectDetail
              path={path}
              revision={revision}
              cfg={cfg}
              navigate={navigate}
              saveButton={saveButton}
              newsCard={newsCard}
              resourceCard={resourceCard}
            />
          )}
          <footer className="page-footer">
            <span>
              <span className="status-dot" />
              数据有来源，趋势可追溯。
            </span>
            <span>GitHub Rank · 为好奇心而构建</span>
          </footer>
        </div>
      </main>
      {notice && (
        <div className="toast" role="status">
          <Check size={16} />
          {notice}
        </div>
      )}
      {sourcesOpen && (
        <div className="modal-backdrop" onClick={() => setSourcesOpen(false)}>
          <section
            className="source-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="source-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <span className="heading-kicker">DATA TRANSPARENCY</span>
                <h2 id="source-title">数据源与同步状态</h2>
              </div>
              <button
                className="icon-btn"
                aria-label="关闭"
                onClick={() => setSourcesOpen(false)}
              >
                <X size={21} />
              </button>
            </div>
            <div className="scheduler-panel">
              <div className="scheduler-heading">
                <h3>
                  <Clock3 size={16} /> 定时采集
                </h3>
                <span
                  className={
                    "source-status " +
                    (runtime.data?.scheduler.online ? "ok" : "paused")
                  }
                >
                  {runtime.loading && !runtime.data
                    ? "读取中"
                    : {
                        running: runtime.data?.scheduler.current_mode
                          ? "采集中"
                          : "运行中",
                        stopping: "正在停止",
                        stopped: "已停止",
                        stale: "心跳中断",
                        failed: "异常退出",
                        never: "未启动",
                      }[runtime.data?.scheduler.status || "never"] ||
                      "状态未知"}
                </span>
              </div>
              <Loading state={runtime} />
              <dl>
                <dt>最近心跳</dt>
                <dd>
                  {runtime.data?.scheduler.heartbeat_at
                    ? time(runtime.data.scheduler.heartbeat_at)
                    : "暂无心跳"}
                </dd>
                <dt>下次检查</dt>
                <dd>
                  {runtime.data?.scheduler.next_check_at
                    ? time(runtime.data.scheduler.next_check_at)
                    : runtime.data?.scheduler.current_mode &&
                        runtime.data.scheduler.online
                      ? "本轮完成后安排"
                      : "暂无计划"}
                </dd>
                <dt>每日仓库采集</dt>
                <dd>
                  {runtime.data?.scheduler.next_repository_at
                    ? new Date(
                        runtime.data.scheduler.next_repository_at,
                      ).getTime() < Date.now()
                      ? "已到期，随本轮检查执行"
                      : time(runtime.data.scheduler.next_repository_at)
                    : "启动调度后安排"}
                </dd>
                <dt>最近一轮</dt>
                <dd>
                  {runtime.data?.scheduler.last_result
                    ? ({
                        ok: "完成",
                        partial: "部分完成",
                        failed: "失败",
                        deferred: "等待其他采集任务",
                        cancelled: "已取消",
                      }[runtime.data.scheduler.last_result] ||
                        runtime.data.scheduler.last_result) +
                      " · " +
                      time(runtime.data.scheduler.last_cycle_at)
                    : "尚无记录"}
                </dd>
              </dl>
              {runtime.data?.scheduler.error && (
                <p className="runtime-warning">
                  最近错误：{runtime.data.scheduler.error}
                </p>
              )}
              {runtime.data?.repositories_stale && (
                <p className="runtime-warning">
                  部分仓库已超过 36 小时未更新，请检查采集任务。
                </p>
              )}
              <p className="scheduler-help">
                双击“启动采集.cmd” /
                “停止采集.cmd”控制后台任务。网页服务独立运行；此面板每 15
                秒更新。
              </p>
            </div>
            <div className="modal-summary">
              <span>
                <Github size={17} />
                仓库快照<strong>{time(status.data?.last_snapshot)}</strong>
              </span>
              <span>
                <Newspaper size={17} />
                资讯同步<strong>{time(status.data?.last_news)}</strong>
              </span>
            </div>
            <p className="muted-note">
              {status.data?.github_token_configured
                ? "已配置服务端 GitHub Token。"
                : "使用公开接口，小批量采集受未认证额度限制。"}
              {status.data?.summary_model_configured
                ? `已配置本地摘要模型；今日调用 ${status.data.summary_attempts_today}/${status.data.summary_daily_limit}，成功结果按缓存展示。`
                : "当前摘要方式：原文与中文模板，未配置模型。"}
            </p>
            <div className="sources-list">
              {sources.data?.items.map((s) => (
                <div key={s.id}>
                  <span
                    className={"status-dot " + (s.effective_status || s.status)}
                  />
                  <div>
                    <a href={safeUrl(s.url)} target="_blank" rel="noreferrer">
                      {s.name}
                      <ArrowUpRight size={12} />
                    </a>
                    <small>
                      {s.enabled === false
                        ? "已暂停采集，保留已有内容。"
                        : s.error || `最后成功：${time(s.last_success_at)}`}
                    </small>
                    {s.enabled !== false && (
                      <small>
                        {s.cadence_note}
                        {s.next_due_at
                          ? ` · ${new Date(s.next_due_at).getTime() < Date.now() ? "已到检查时间" : "下次 " + time(s.next_due_at)}`
                          : ""}
                        {!!s.consecutive_failures &&
                          ` · 连续失败 ${s.consecutive_failures} 次`}
                        {s.last_recovered_at &&
                          ` · 最近恢复 ${time(s.last_recovered_at)}`}
                      </small>
                    )}
                  </div>
                  <span
                    className={
                      "source-status " +
                      (s.freshness === "stale"
                        ? "error"
                        : s.effective_status || s.status)
                    }
                  >
                    {s.enabled === false
                      ? "已暂停"
                      : s.freshness === "stale"
                        ? "数据过期"
                        : s.status === "ok"
                          ? "已同步"
                          : s.status === "error"
                            ? "需检查"
                            : "待采集"}
                  </span>
                </div>
              ))}
            </div>
            <h3 className="jobs-title">来源故障与恢复</h3>
            <div className="jobs-list">
              {!runtime.data?.source_events.length && (
                <p className="muted-note">尚无故障或恢复记录。</p>
              )}
              {runtime.data?.source_events.slice(0, 6).map((event) => (
                <div key={event.id}>
                  <span>{event.source_name}</span>
                  <span>
                    {event.kind === "recovered" ? "已恢复" : "采集失败"} ·{" "}
                    {time(event.occurred_at)}
                  </span>
                  {event.error && <small>{event.error}</small>}
                </div>
              ))}
            </div>
            <h3 className="jobs-title">最近采集任务</h3>
            <div className="jobs-list">
              {status.data?.jobs.slice(0, 5).map((j) => (
                <div key={j.id}>
                  <span>
                    {j.kind} · {time(j.started_at)}
                  </span>
                  <span>
                    {j.status === "ok"
                      ? "完成"
                      : j.status === "partial"
                        ? "部分完成"
                        : j.status === "cancelled"
                          ? "已取消"
                          : j.status === "interrupted"
                            ? "中断后已接管"
                            : j.status === "running"
                              ? "进行中"
                              : "失败"}
                  </span>
                  {j.report.errors?.map((e, i) => (
                    <small key={i}>
                      {e.source}：{e.error}
                    </small>
                  ))}
                  {!!j.report.deferred_repositories && (
                    <small>
                      另有 {j.report.deferred_repositories} 个候选等待下次采集。
                    </small>
                  )}
                </div>
              ))}
            </div>
            <div className="modal-foot">
              <CircleHelp size={14} />
              刷新按钮只重新读取本地数据；上游采集由独立任务执行。
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Loading({ state }: { state: { loading: boolean; error?: string } }) {
  return state.error ? (
    <div className="error-banner">
      <AlertCircle size={17} />
      {state.error}
    </div>
  ) : state.loading ? (
    <div className="loading">
      <LoaderCircle size={18} />
      正在读取数据…
    </div>
  ) : null;
}

function SummaryEvidence({ meta }: { meta?: SummaryFields["summary_meta"] }) {
  if (!meta) return null;
  return (
    <details className="summary-evidence">
      <summary>
        <Sparkles size={12} />
        AI 中文摘要 · 查看引用
      </summary>
      <small>
        {meta.model} · {time(meta.generated_at)}
      </small>
      {meta.evidence.map((e, i) => (
        <div key={i}>
          <a href={safeUrl(e.url)} target="_blank" rel="noreferrer">
            原始依据
            <ArrowUpRight size={11} />
          </a>
          <blockquote>{e.quote}</blockquote>
        </div>
      ))}
      <small>模型生成内容，可对照原文核实。</small>
    </details>
  );
}
function Empty({
  title,
  description,
  compact = false,
}: {
  title: string;
  description: string;
  compact?: boolean;
}) {
  return (
    <div className={"empty-state " + (compact ? "compact" : "")}>
      <span>
        <Compass size={compact ? 22 : 28} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
function newsDate(value?: string | null, precision?: string) {
  if (!value) return "发布时间未知";
  if (precision === "day") return value.slice(0, 10) + "（仅日期）";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "来源时间不可解析";
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  });
}

function ReadButton({
  mark,
  digest,
  onRead,
  onUnread,
}: {
  mark?: ReadMark;
  digest?: string;
  onRead: () => void;
  onUnread: () => void;
}) {
  const state = readStatus(mark, digest);
  return (
    <button
      className={"reading-button " + state}
      onClick={state === "read" ? onUnread : onRead}
      title={
        mark ? "标记时间：" + time(mark.read_at) : "打开详情不会自动标记已读"
      }
    >
      {state === "read" ? (
        <Check size={13} />
      ) : state === "updated" ? (
        <RefreshCw size={13} />
      ) : (
        <Clock3 size={13} />
      )}
      {state === "read"
        ? "已读 · 标为未读"
        : state === "updated"
          ? "有更新 · 标为已读"
          : "标为已读"}
    </button>
  );
}

function NewsDetail({
  path,
  versionHash,
  revision,
  cfg,
  navigate,
  saveButton,
  reading,
  onMarkRead,
  onMarkUnread,
}: {
  path: string;
  versionHash: string;
  revision: number;
  cfg?: Config;
  navigate: (url: string) => void;
  reading: Record<string, ReadMark>;
  onMarkRead: (item: News) => void;
  onMarkUnread: (id: string) => void;
  saveButton: (
    t: Saved["type"],
    id: string,
    data: Saved["data"],
  ) => React.ReactNode;
}) {
  const id = path.replace("/news/", "");
  const detail = useLoad<News>(
    "/api/news/" +
      encodeURIComponent(id) +
      (versionHash ? "?version_hash=" + encodeURIComponent(versionHash) : ""),
    revision,
  );
  const item = detail.data;
  if (!item)
    return (
      <>
        <Loading state={detail} />
        <button className="outline-button" onClick={() => navigate("/news")}>
          返回资讯
        </button>
      </>
    );
  const historical = item.version_view && !item.version_view.is_current;
  const source = item.source_state;
  return (
    <>
      <div className="detail-hero">
        <div>
          <span className="eyebrow">
            {cfg?.topics[item.topic] || item.topic} · {item.source_name}
          </span>
          <h2>{item.title_zh || item.title}</h2>
          {item.title_zh && item.title_zh !== item.title && <p>{item.title}</p>}
          <div className="detail-tags">
            <span>{newsDate(item.published_at, item.published_precision)}</span>
            <span>
              {item.is_preprint
                ? "预印本 · 未标注同行评审"
                : item.source_kind === "release"
                  ? "项目 Release"
                  : "来源发布"}
            </span>
            <span>
              {item.grouping?.method === "manual" ? "人工分组" : "自动分组"}
            </span>
          </div>
        </div>
        <div className="detail-actions">
          {saveButton("news", item.id, item)}
          <ReadButton
            mark={reading[item.id]}
            digest={item.version_view?.content_hash || item.content_hash}
            onRead={() => onMarkRead(item)}
            onUnread={() => onMarkUnread(item.id)}
          />
          <a
            className="primary-button"
            href={safeUrl(item.url)}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} />
            阅读原文
          </a>
          <button className="outline-button" onClick={() => navigate("/news")}>
            返回资讯
          </button>
        </div>
      </div>
      {historical && (
        <div className="curation-notice" role="status">
          <History size={16} />
          <div>
            正在查看本地采集版本：{newsDate(item.version_view?.observed_at)}
            。下方关联报道与分组依据显示当前状态。
          </div>
          <button
            className="text-button"
            onClick={() => navigate("/news/" + item.id)}
          >
            查看最新记录
          </button>
        </div>
      )}
      <div className="resource-detail-columns">
        <section className="detail-panel">
          <h3>{item.summary_zh ? "AI 中文摘要" : "来源摘要 · 非全文"}</h3>
          <p className="news-detail-summary">
            {item.summary_zh ||
              item.summary ||
              "来源未提供摘要，请打开原文核对内容。"}
          </p>
          <SummaryEvidence meta={item.summary_meta} />
          {item.summary_zh && (
            <details className="news-original-summary">
              <summary>查看来源原始摘要</summary>
              <p>{item.summary}</p>
            </details>
          )}
          <h3>
            当前事件关联{" "}
            <small>
              {item.report_count || 1} 篇 · {item.source_count || 1} 个来源
            </small>
          </h3>
          <p>关联报道保留各自的发布时间；可能不在列表当前筛选范围内。</p>
          <div className="news-related">
            <div className="news-related-current">
              <strong>{item.source_name} · 当前条目</strong>
              <span>
                {newsDate(item.published_at, item.published_precision)}
              </span>
            </div>
            {item.related_reports?.map((report) => (
              <div key={report.id || report.url}>
                <span>
                  {report.source_name} ·{" "}
                  {newsDate(report.published_at, report.published_precision)}
                </span>
                {report.id ? (
                  <button onClick={() => navigate("/news/" + report.id)}>
                    {report.title}
                    <ArrowRight size={13} />
                  </button>
                ) : (
                  <strong>{report.title}</strong>
                )}
                <a href={safeUrl(report.url)} target="_blank" rel="noreferrer">
                  原文 <ArrowUpRight size={12} />
                </a>
              </div>
            ))}
          </div>
          {!!item.related_projects?.length && (
            <>
              <h3>原文关联项目</h3>
              <p>仅使用来源明确提供的 GitHub 链接，不根据名称相似推测。</p>
              <div className="news-related">
                {item.related_projects.map((project) => (
                  <div key={project.url}>
                    {project.tracked ? (
                      <button
                        onClick={() =>
                          navigate("/projects/" + project.full_name)
                        }
                      >
                        <Github size={14} />
                        {project.full_name}
                        <ArrowRight size={13} />
                      </button>
                    ) : (
                      <a
                        href={safeUrl(project.url)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <Github size={14} />
                        {project.full_name}
                        <ArrowUpRight size={12} />
                      </a>
                    )}
                    <span>
                      {project.tracked ? "已跟踪项目" : "外部仓库，尚未跟踪"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
        <section className="detail-panel">
          <h3>时间与来源证据</h3>
          <dl>
            <dt>原发布时间</dt>
            <dd>{newsDate(item.published_at, item.published_precision)}</dd>
            <dt>来源日期原值</dt>
            <dd>{item.raw_published_at || "来源未提供"}</dd>
            <dt>来源更新时间</dt>
            <dd>
              {item.source_updated_at
                ? newsDate(item.source_updated_at)
                : "未提供独立更新时间"}
            </dd>
            <dt>首次发现</dt>
            <dd>{newsDate(item.first_seen_at)}</dd>
            <dt>{historical ? "当前记录抓取" : "最近抓取"}</dt>
            <dd>{newsDate(item.fetched_at)}</dd>
            <dt>来源当前状态</dt>
            <dd>
              {!source
                ? "未记录"
                : source.enabled === false
                  ? "已暂停"
                  : source.freshness === "stale"
                    ? "数据过期"
                    : source.status === "error"
                      ? "采集失败"
                      : source.status === "ok"
                        ? "最近检查成功"
                        : "待采集"}
            </dd>
          </dl>
          <p className="muted-note">
            精确时间以北京时间显示；仅日期不补造时分。发现、抓取和来源更新时间均不替代首次发布时间。
          </p>
          <h3>分组依据</h3>
          <p>{item.grouping?.reason}</p>
          <span className="method-tag">
            {item.grouping?.rule_version || "待确认"} ·{" "}
            {item.grouping?.method === "manual" ? "人工修订" : "保守自动规则"}
          </span>
          <h3>
            本地采集版本 <small>{item.versions?.length || 0} 条</small>
          </h3>
          <p>
            记录本地保存的内容与解析元数据，不等于作者修改次数；查看旧版本不会改写最新记录。
          </p>
          <div className="news-version-list">
            {item.versions?.map((version) => (
              <button
                key={version.content_hash}
                className={
                  (
                    versionHash
                      ? version.content_hash === versionHash
                      : version.is_current
                  )
                    ? "selected"
                    : ""
                }
                onClick={() =>
                  navigate(
                    "/news/" +
                      item.id +
                      (version.is_current
                        ? ""
                        : "?version_hash=" + version.content_hash),
                  )
                }
              >
                <span>{newsDate(version.observed_at)}</span>
                <small>
                  {version.content_hash.slice(0, 12)} ·{" "}
                  {version.is_current ? "当前" : "历史记录"}
                </small>
              </button>
            ))}
          </div>
          <h3>事件修订记录</h3>
          {!item.event_edits?.length ? (
            <p>尚无人工分组修订。</p>
          ) : (
            item.event_edits.map((edit) => (
              <div className="news-edit" key={edit.id}>
                <strong>
                  {{
                    merge: "合并分组",
                    split: "拆分条目",
                    reset: "恢复自动规则",
                  }[edit.action] || edit.action}{" "}
                  · {newsDate(edit.created_at)}
                </strong>
                <p>{edit.data.reason}</p>
              </div>
            ))
          )}
          <dl>
            <dt>条目 ID</dt>
            <dd className="resource-hash">{item.id}</dd>
          </dl>
        </section>
      </div>
    </>
  );
}

const scanLabels: Record<string, string> = {
  complete: "完整扫描",
  partial: "部分扫描",
  failed: "扫描失败",
  not_scanned: "尚未扫描",
};
const verificationLabels: Record<string, string> = {
  current: "本轮已核对",
  previous: "保留上次记录，尚未重新核对",
  unknown: "待重新扫描",
};
const scanReasons: Record<string, string> = {
  resource_file_limit: "达到文件数量上限",
  tree_request_limit: "达到目录请求上限",
  tree_depth_or_queue_limit: "达到目录深度或队列上限",
  file_size_limit: "文件超过读取大小上限",
  file_fetch_failed: "部分文件读取失败",
  nonrecursive_tree_truncated: "逐层目录仍被上游截断",
  tree_unavailable: "目录访问失败",
  page_is_partial: "公开页面只提供部分目录",
  page_directory_unavailable: "部分公开目录无法读取",
  batch_resource_budget: "本批资源请求额度已用完",
  missing_commit: "未获取到证据 commit",
};

function ResourceDetail({
  path,
  revision,
  navigate,
  saveButton,
}: {
  path: string;
  revision: number;
  navigate: (url: string) => void;
  saveButton: (
    t: Saved["type"],
    id: string,
    data: Saved["data"],
  ) => React.ReactNode;
}) {
  const detail = useLoad<Resource>(
    "/api/agent-resources/" +
      encodeURIComponent(path.replace("/resources/", "")),
    revision,
  );
  const item = detail.data;
  if (!item)
    return (
      <>
        <Loading state={detail} />
        <button
          className="outline-button"
          onClick={() => navigate("/agents?view=resources")}
        >
          返回资源目录
        </button>
      </>
    );
  const scan = item.scan_report;
  return (
    <>
      <div className="detail-hero">
        <div>
          <span className="eyebrow">
            {item.kind === "skill"
              ? "AGENT SKILL"
              : item.kind === "mcp"
                ? "MCP SERVER"
                : "PLUGIN"}
          </span>
          <h2>{item.name}</h2>
          <p>{item.summary_zh || item.description}</p>
          <div className="detail-tags">
            <span>{item.ecosystem || "待核对格式"}</span>
            <span>
              {verificationLabels[item.verification_status || "unknown"]}
            </span>
            <span>{item.license || "许可未声明"}</span>
          </div>
        </div>
        <div className="detail-actions">
          {saveButton("resource", item.id, item)}
          <a
            className="primary-button"
            href={safeUrl(item.url)}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink size={16} />
            查看原文件
          </a>
          <button
            className="outline-button"
            onClick={() => navigate("/projects/" + item.repo_name)}
          >
            所属仓库
          </button>
        </div>
      </div>
      {item.ranking_excluded && (
        <div className="curation-notice excluded">
          所属仓库已从当前目录排除，此处保留资源的历史出处。
        </div>
      )}
      <div className="resource-detail-columns">
        <section className="detail-panel">
          <h3>兼容要求与证据</h3>
          <p>
            {item.compatibility_evidence?.length
              ? item.compatibility
              : item.content_hash
                ? "原文件未提供可识别的兼容要求。"
                : "旧记录尚未保存字段证据，需要重新扫描原文件。"}
          </p>
          <span className="method-tag">
            {item.compatibility_status} · 生态格式不代表已验证运行兼容性
          </span>
          {item.compatibility_evidence?.map((e, index) => (
            <blockquote className="resource-evidence" key={e.field + index}>
              <span>{e.field}</span>
              <p>{e.quote}</p>
              <a href={safeUrl(e.url)} target="_blank" rel="noreferrer">
                查看字段原文 <ArrowUpRight size={12} />
              </a>
            </blockquote>
          ))}
          <h3>来源与版本</h3>
          <dl>
            <dt>所属仓库</dt>
            <dd>{item.repo_name}</dd>
            <dt>原始路径</dt>
            <dd>{item.path}</dd>
            <dt>证据 commit</dt>
            <dd className="resource-hash">{item.commit || "待核对"}</dd>
            <dt>作者版本</dt>
            <dd>{item.declared_version || "未声明"}</dd>
            <dt>文件 SHA-256</dt>
            <dd className="resource-hash">
              {item.content_hash || "旧记录未保存"}
            </dd>
          </dl>
          <SummaryEvidence meta={item.summary_meta} />
          {!!item.format_warnings?.length && (
            <>
              <h3>格式提醒</h3>
              {item.format_warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </>
          )}
        </section>
        <section className="detail-panel">
          <h3>扫描覆盖</h3>
          <dl>
            <dt>最近仓库扫描</dt>
            <dd>
              {scanLabels[item.scan_status || "not_scanned"] || "尚未扫描"}
            </dd>
            <dt>本条记录</dt>
            <dd>{verificationLabels[item.verification_status || "unknown"]}</dd>
            <dt>候选文件读取</dt>
            <dd>
              {scan
                ? (scan.read_files || 0) + " / " + (scan.candidate_files || 0)
                : "旧记录未保存"}
            </dd>
            <dt>目录覆盖</dt>
            <dd>
              {scan
                ? scan.tree_complete
                  ? "已遍历完整目录"
                  : "目录未完整覆盖"
                : "待重新扫描"}
            </dd>
            <dt>目录请求</dt>
            <dd>{scan?.tree_requests ?? "—"}</dd>
          </dl>
          {scan?.limits && (
            <p className="muted-note">
              本轮上限：{scan.limits.files} 个文件、{scan.limits.trees}{" "}
              次目录请求、{scan.limits.depth} 层深度。
            </p>
          )}
          {!!scan?.reasons?.length && (
            <p className="runtime-warning">
              {scan.reasons.map((r) => scanReasons[r] || r).join("；")}
            </p>
          )}
          <h3>
            同内容来源 <small>{item.duplicate_count || 1} 处</small>
          </h3>
          <p>按资源类型与原文件字节 hash 匹配，不据此判断原创或转载关系。</p>
          <div className="resource-origins">
            {item.same_content_sources?.map((source) => (
              <div key={source.id}>
                <a href={safeUrl(source.url)} target="_blank" rel="noreferrer">
                  {source.repo_name}
                  <ArrowUpRight size={13} />
                </a>
                <small>{source.path}</small>
                <span>{verificationLabels[source.verification_status]}</span>
                {source.id !== item.id && (
                  <button onClick={() => navigate("/resources/" + source.id)}>
                    查看此来源详情 <ArrowRight size={12} />
                  </button>
                )}
              </div>
            ))}
          </div>
          <p className="muted-note">
            关联仓库 Star：
            {item.repository_stars == null
              ? "未获取"
              : number(item.repository_stars)}
            。资源没有独立安装或使用量。
          </p>
        </section>
      </div>
    </>
  );
}

function ProjectDetail({
  path,
  revision,
  cfg,
  navigate,
  saveButton,
  newsCard,
  resourceCard,
}: {
  path: string;
  revision: number;
  cfg?: Config;
  navigate: (s: string) => void;
  saveButton: (
    t: Saved["type"],
    id: string,
    data: Saved["data"],
  ) => React.ReactNode;
  newsCard: (n: News) => React.ReactNode;
  resourceCard: (r: Resource) => React.ReactNode;
}) {
  const name = path.replace("/projects/", "");
  const detail = useLoad<Repo>("/api/projects/" + name, revision);
  const history = useLoad<{
    items: { observed_at: string; stars: number; day: string }[];
  }>("/api/projects/" + name + "/history", revision);
  const repo = detail.data;
  const ranking = useLoad<Ranking>(
    "/api/rankings?window=7d&q=" + encodeURIComponent(repo?.full_name || name),
    revision,
  );
  const metrics = [
    ...(ranking.data?.items || []),
    ...(ranking.data?.observing || []),
  ].find((r) => r.id === repo?.id);
  if (!repo)
    return (
      <>
        <Loading state={detail} />
        <button className="outline-button" onClick={() => navigate("/")}>
          返回发现
        </button>
      </>
    );
  const points = history.data?.items || [],
    min = Math.min(...points.map((p) => p.stars)),
    max = Math.max(...points.map((p) => p.stars));
  const paths: string[] = [];
  points.forEach((p, i) => {
    const x = 20 + (i * 760) / Math.max(points.length - 1, 1),
      y = 155 - ((p.stars - min) / Math.max(max - min, 1)) * 120;
    const gap =
      i === 0 ||
      new Date(p.day).getTime() - new Date(points[i - 1].day).getTime() >
        1.5 * 86400000;
    paths.push(`${gap ? "M" : "L"}${x},${y}`);
  });
  return (
    <>
      <div className="detail-hero">
        <div>
          <span className="eyebrow">{cfg?.categories[repo.category]}</span>
          <h2>{repo.full_name}</h2>
          <p>{repo.description}</p>
          <div className="detail-tags">
            {repo.agent_types.map((t) => (
              <span key={t}>{cfg?.agent_types[t]}</span>
            ))}
            <span>{repo.language || "未标注语言"}</span>
            <span>{repo.license}</span>
          </div>
        </div>
        <div className="detail-actions">
          {saveButton("project", String(repo.id), repo)}
          <a
            className="primary-button"
            href={safeUrl(repo.url)}
            target="_blank"
            rel="noreferrer"
          >
            <Github size={17} />
            打开 GitHub
            <ArrowUpRight size={14} />
          </a>
          {safeUrl(repo.homepage) && (
            <a
              className="outline-button"
              href={safeUrl(repo.homepage)}
              target="_blank"
              rel="noreferrer"
            >
              官网
              <ExternalLink size={14} />
            </a>
          )}
        </div>
      </div>
      {repo.requested_name &&
        repo.requested_name.toLowerCase() !== repo.full_name.toLowerCase() && (
          <div className="curation-notice" role="status">
            <History size={16} />
            <div>
              仓库已更名为 {repo.full_name}。旧链接仍可查看同一仓库的历史记录。
            </div>
            <button
              className="text-link"
              onClick={() => navigate("/projects/" + repo.full_name)}
            >
              打开当前地址 <ArrowRight size={13} />
            </button>
          </div>
        )}
      {repo.ranking_excluded && (
        <div className="curation-notice excluded" role="status">
          <AlertCircle size={16} />
          <div>
            已从当前项目列表、榜单和资源目录排除，历史记录保留。
            {repo.classification?.reason && (
              <p>修订说明：{repo.classification.reason}</p>
            )}
          </div>
        </div>
      )}
      <section className="detail-metrics">
        {[
          ["当前 Star", number(repo.stars)],
          ["当前 Fork", number(repo.forks)],
          [
            "近 7 天净增",
            repo.ranking_excluded
              ? "已排除"
              : metrics?.delta_stars != null
                ? (metrics.delta_stars > 0 ? "+" : "") + metrics.delta_stars
                : "观察中",
          ],
          [
            "潜力分",
            repo.ranking_excluded
              ? "已排除"
              : metrics?.potential_score != null
                ? String(metrics.potential_score)
                : "待积累",
          ],
        ].map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </section>
      <div className="detail-columns">
        <section className="detail-panel">
          <h3>项目速读</h3>
          <p>{repo.summary_zh || repo.summary}</p>
          {repo.summary_meta ? (
            <SummaryEvidence meta={repo.summary_meta} />
          ) : (
            <span className="method-tag">
              中文模板 · 功能以作者原始介绍为准
            </span>
          )}
          {repo.classification && (
            <>
              <h3>分类依据</h3>
              <dl>
                <dt>当前分类</dt>
                <dd>
                  {cfg?.categories[repo.category] || repo.category} ·{" "}
                  {repo.classification.method === "manual"
                    ? "人工修订"
                    : "自动规则"}
                </dd>
                {repo.classification.method === "manual" && (
                  <>
                    <dt>自动识别</dt>
                    <dd>
                      {cfg?.categories[
                        repo.classification.automatic.category
                      ] || repo.classification.automatic.category}{" "}
                      ·{" "}
                      {repo.classification.automatic.agent_types
                        .map((t) => cfg?.agent_types[t] || t)
                        .join(" / ") || "无 Agent 标签"}
                    </dd>
                    <dt>修订说明</dt>
                    <dd>{repo.classification.reason}</dd>
                    <dt>修订时间</dt>
                    <dd>{time(repo.classification.updated_at || undefined)}</dd>
                  </>
                )}
              </dl>
            </>
          )}
          <h3>观测依据</h3>
          <dl>
            <dt>最近快照</dt>
            <dd>{time(repo.observed_at)}</dd>
            <dt>最近推送</dt>
            <dd>{time(repo.pushed_at)}</dd>
            <dt>快照来源</dt>
            <dd>
              {repo.data_source === "github_public_page"
                ? "GitHub 公开页面 · 精确计数"
                : "GitHub API"}
            </dd>
            <dt>资源扫描</dt>
            <dd>
              {{
                complete: "完整扫描",
                partial: "部分扫描",
                failed: "扫描失败",
                not_scanned: "尚未扫描",
              }[repo.resource_scan || "not_scanned"] || "尚未扫描"}
            </dd>
            {repo.resource_scan_report && (
              <>
                <dt>资源文件读取</dt>
                <dd>
                  {repo.resource_scan_report.read_files || 0} /{" "}
                  {repo.resource_scan_report.candidate_files || 0} 个候选；
                  {repo.resource_scan_report.tree_complete
                    ? "目录完整"
                    : "目录不完整"}
                </dd>
              </>
            )}
          </dl>
          <p className="muted-note">{metrics?.observation_note}</p>
          {metrics?.score_breakdown?.map((s) => (
            <div className="score-row" key={s.name}>
              <span>{s.name}</span>
              <div>
                <i style={{ width: s.value * 100 + "%" }} />
              </div>
              <strong>{s.contribution}</strong>
            </div>
          ))}
        </section>
        <section className="detail-panel">
          <h3>
            Star 观测曲线 <small>每日总数</small>
          </h3>
          {points.length >= 2 ? (
            <>
              <svg
                viewBox="0 0 800 180"
                className="history-chart"
                role="img"
                aria-label="每日 Star 总数观测曲线"
              >
                <path
                  d="M20 155H780 M20 95H780 M20 35H780"
                  stroke="#e6eae7"
                  fill="none"
                />
                <path
                  d={paths.join(" ")}
                  fill="none"
                  stroke="#168264"
                  strokeWidth="3"
                />
              </svg>
              <div className="chart-labels">
                <span>
                  {points[0].day} · {min}
                </span>
                <span>
                  {points[points.length - 1].day} · {max}
                </span>
              </div>
              <p className="muted-note">
                缺少观测的日期断线显示。总数差表示净变化。
              </p>
            </>
          ) : (
            <Empty
              title="第一条快照，已经开始记录"
              description="至少积累两天数据后展示趋势曲线。正式周榜需要完整 7 天端点。"
              compact
            />
          )}
        </section>
      </div>
      {!!repo.resources?.length && (
        <>
          <div className="section-heading observing-heading">
            <h2>仓库中的 Skills / 插件</h2>
          </div>
          <div className="repo-grid wide">
            {repo.resources.map(resourceCard)}
          </div>
        </>
      )}
      {!!repo.related_news?.length && (
        <>
          <div className="section-heading observing-heading">
            <h2>相关资讯</h2>
          </div>
          <div className="news-list">{repo.related_news.map(newsCard)}</div>
        </>
      )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
