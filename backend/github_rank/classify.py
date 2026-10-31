import re


CATEGORIES = {
    "ai": "AI / 机器学习", "devtools": "开发工具", "frontend": "前端",
    "backend": "后端", "data": "数据 / 数据库", "devops": "DevOps / 云原生",
    "security": "安全", "productivity": "效率 / 桌面", "games": "移动 / 游戏",
    "learning": "学习 / 资料", "other": "待分类",
}
AGENT_TYPES = {"framework": "Agent 框架", "coding": "Coding Agent", "mcp": "MCP",
               "plugin": "插件 / 扩展", "skill": "Skills", "workflow": "工作流 / 评测"}
TOPICS = {"models": "模型发布", "agents": "AI Agent", "research": "前沿研究",
          "multimodal": "多模态 / 具身", "engineering": "开源 / 工程", "industry": "产业动态"}


def classify_repo(repo):
    text = " ".join([repo.get("full_name", ""), repo.get("description") or "", *repo.get("topics", [])]).lower()
    agents = []
    for kind, pattern in [
        ("skill", r"agent.skills|awesome.skills|/skills\b|skill\.md"),
        ("mcp", r"\bmcp\b|modelcontextprotocol|model.context.protocol"),
        ("coding", r"coding.agent|coding.assistant|copilot|claude.code|codex|autonomous.cod"),
        ("plugin", r"\bplugin|\bextension"),
        ("framework", r"agent.framework|multi.agent|orchestrat|langgraph|crewai|autogen"),
        ("workflow", r"agent.*(?:eval|observab|memory|workflow)|\bharness\b"),
    ]:
        if re.search(pattern, text):
            agents.append(kind)
    rules = [
        ("learning", r"awesome|tutorial|course|learning.resource|学习资料"),
        ("ai", r"\bai\b|\bllm\b|agent|machine.learning|neural|transformer|diffusion"),
        ("security", r"security|vulnerability|pentest"),
        ("data", r"database|\bsql\b|analytics|data.engineer"),
        ("devops", r"kubernetes|docker|devops|terraform|cloud.native"),
        ("frontend", r"frontend|react|\bvue\b|\bvite\b|\bcss\b"),
        ("backend", r"backend|fastapi|\bdjango\b|web.framework|http.framework"),
        ("games", r"game.engine|\bunity\b|\bgodot\b|\bandroid\b|\bios\b"),
        ("devtools", r"developer.tool|\bcli\b|\bcompiler\b|\blinter\b|\bide\b"),
        ("productivity", r"rss|productivity|desktop|note.taking"),
    ]
    return next((key for key, pattern in rules if re.search(pattern, text)), "ai" if agents else "other"), agents


def news_topic(text, kind="official"):
    text = text.lower()
    if re.search(r"agent|\bmcp\b|\bskills?\b|copilot|codex|claude.code", text):
        return "agents"
    if re.search(r"\b(?:robot\w*|vision|video\w*|image\w*|audio|multimodal)\b|多模态|图像|语音", text):
        return "multimodal"
    if kind == "paper" or re.search(r"research|benchmark|training|研究|论文", text):
        return "research"
    if re.search(r"model|gemini|claude|gpt|qwen|deepseek|模型", text):
        return "models"
    if kind == "release" or re.search(r"deploy|inference|开源|sdk", text):
        return "engineering"
    return "industry"
