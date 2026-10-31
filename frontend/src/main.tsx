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
  related_reports?: { url: string; title: string; source_name: string }[];
  is_preprint?: boolean;
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
type Saved = {
  type: "project" | "resource" | "news";
  id: string;
  data: Repo | Resource | News;
};

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
    ? (n / 1000).toFixed(n >= 10000 ? 1 : 2).replace(/0$/, "") + "k"
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
  const [sidebar, setSidebar] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [saved, setSaved] = useState<Saved[]>(() => {
    try {
      const data = JSON.parse(
        localStorage.getItem("github-rank:saved") || "[]",
      );
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  });
  const [notice, setNotice] = useState("");
  const path = route.split("?")[0],
    params = new URLSearchParams(route.split("?")[1] || "");
  const isNews = path === "/news",
    isAgents = path === "/agents",
    isHome = path === "/",
    isSaved = path === "/saved",
    isArchive = path === "/archive",
    isDetail = path.startsWith("/projects/");
  const kind = params.get("kind") === "potential" ? "potential" : "hot";
  const window = params.get("window") || (isNews ? "7d" : "7d");
  const category = params.get("category") || "",
    query = params.get("q") || "",
    agentType = params.get("agent_type") || "";
  const topic = params.get("topic") || "",
    sort = params.get("sort") || "latest",
    source = params.get("source") || "";
  const resourcesView = isAgents && params.get("view") === "resources";
  const language = params.get("language") || "";
  const minStars = params.get("min_stars") || "";
  const maxStars = params.get("max_stars") || "";
  const config = useLoad<Config>("/api/config", revision);
  const status = useLoad<Status>("/api/data-status", revision);
  const sources = useLoad<{ items: Source[] }>("/api/news/sources", revision);
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
  const resources = useLoad<{ items: Resource[]; total: number }>(
    "/api/agent-resources?" +
      new URLSearchParams({
        q: query,
        kind: agentType === "skill" || agentType === "plugin" ? agentType : "",
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

  function navigate(url: string) {
    history.pushState({}, "", url);
    setRoute(location.pathname + location.search);
    setSidebar(false);
    globalThis.scrollTo({ top: 0 });
  }
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    if (
      key === "view" &&
      value === "resources" &&
      !["skill", "plugin"].includes(next.get("agent_type") || "")
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
  function toggle(type: Saved["type"], id: string, data: Saved["data"]) {
    const exists = saved.some((s) => s.type === type && s.id === id);
    const next = exists
      ? saved.filter((s) => !(s.type === type && s.id === id))
      : [...saved, { type, id, data }];
    try {
      localStorage.setItem("github-rank:saved", JSON.stringify(next));
      setSaved(next);
      setNotice(exists ? "已取消收藏" : "已保存到本机收藏");
    } catch {
      setNotice("浏览器存储不可用，收藏未保存");
    }
  }
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
        {!compact && saveButton("news", item.id, item)}
      </div>
      <a
        className="news-title"
        href={safeUrl(item.url)}
        target="_blank"
        rel="noreferrer"
      >
        {item.title_zh || item.title}
        <ArrowUpRight size={16} />
      </a>
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
            <span>{item.related_reports.length + 1} 个来源</span>
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
          {r.kind === "skill" ? "AGENT SKILL" : "PLUGIN"}
        </span>
        {saveButton("resource", r.id, r)}
      </div>
      <a
        href={safeUrl(r.url)}
        target="_blank"
        rel="noreferrer"
        className="resource-title"
      >
        {r.name}
        <ArrowUpRight size={16} />
      </a>
      <p>{r.summary_zh || r.description}</p>
      <SummaryEvidence meta={r.summary_meta} />
      <div className="resource-repo">
        <Github size={13} />
        {r.repo_name}
      </div>
      <div className="resource-foot">
        <span>作者声明适配，未测试</span>
        <span>
          仓库 <Star size={12} />
          {number(r.repository_stars || 0)}
        </span>
      </div>
    </article>
  );
  const formal = rankings.data?.items || [],
    observing = rankings.data?.observing || [];
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
                        ? "项目详情"
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
                    <span className="live-pill">持续同步</span>
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
                        Skills / 插件
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
                    ([k]) => !resourcesView || ["skill", "plugin"].includes(k),
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
              <div className="repo-grid wide">
                {resources.data?.items.map(resourceCard)}
              </div>
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
              <div className="news-list">
                {news.data?.items.map((n) => newsCard(n))}
              </div>
              {!news.loading && !news.data?.items.length && (
                <Empty
                  title="这个时间段还没有匹配的资讯"
                  description="试试更长的时间范围，或查看下方发布时间未知的内容。"
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
                        来源没有可靠的发布时间，这些内容不计入上方的近期资讯。
                      </p>
                    </div>
                  </div>
                  <div className="news-list">
                    {news.data.unknown_time.map((n) => newsCard(n))}
                  </div>
                </>
              )}
            </>
          )}
          {isSaved && (
            <>
              {!saved.length && (
                <Empty
                  title="下一次发现，从这里继续"
                  description="点击项目、Skill 或资讯卡片上的收藏按钮，即可保存在当前浏览器。"
                />
              )}
              <div className="repo-grid wide">
                {saved
                  .filter((s) => s.type === "project")
                  .map((s) => repoCard(s.data as Repo))}
                {saved
                  .filter((s) => s.type === "resource")
                  .map((s) => resourceCard(s.data as Resource))}
              </div>
              <div className="news-list">
                {saved
                  .filter((s) => s.type === "news")
                  .map((s) => newsCard(s.data as News))}
              </div>
              {!!saved.length && (
                <p className="muted-note">
                  收藏保留保存时的内容快照，项目最新数据请打开详情查看。
                </p>
              )}
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
          {isDetail && (
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
                  </div>
                  <span
                    className={
                      "source-status " + (s.effective_status || s.status)
                    }
                  >
                    {s.enabled === false
                      ? "已暂停"
                      : s.status === "ok"
                        ? "已同步"
                        : s.status === "error"
                          ? "需检查"
                          : "待采集"}
                  </span>
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
