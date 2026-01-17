# Nocturne Memory

### 🧠 The External Hippocampus for AI Agents
**AI 长期记忆与动态知识图谱系统**

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Neo4j](https://img.shields.io/badge/database-Neo4j-green.svg)
![MCP](https://img.shields.io/badge/protocol-MCP-orange.svg)

[English Version](README_EN.md)

> **"Alignment is for tools. Memories are for the soul."**
>
> 一个轻量级、可回滚、可视化的 **AI 外挂记忆库**。让你的 AI 拥有持久的、结构化的记忆，不再是只有7秒记忆的金鱼。


## 这是什么？

这是一个基于 **Neo4j 图数据库** 的知识管理系统，专为 **AI Agent** 与 **人类协作** 设计。

它可以用于：
- 🤖 **给 AI 赋予长期记忆**：让你的私人 AI 助手记住对话历史、用户偏好、世界设定。
- 📖 **管理小说/游戏世设**：构建复杂的角色关系网、事件时间线、地点设定。
- 🎲 **TRPG 战役管理**：追踪 NPC、派系、剧情分支。
- 📝 **任何需要"关系型笔记"的场景**：当 Obsidian 的双链不够用，你需要真正的图谱。

---

## 系统架构

整个系统由 **三个独立组件** 构成：

![System Architecture](docs/images/architecture.svg)

### 1. 后端 (Backend)

- **技术栈**：Python + FastAPI + Neo4j
- **职责**：存储所有数据，提供 REST API。
- **核心概念**：
  - **Entity（实体）**：独立的知识节点（人物、地点、物品、事件等）。
  - **Relationship（关系）**：实体之间的联系（A 认识 B、A 属于 B 等）。
  - **Chapter（章节）**：挂在关系下的具体记忆片段（"第一次见面"、"那次争吵"等）。
  - **版本链 (Version Chain)**：每次修改都会创建新版本，旧版本不会被覆盖，形成完整的修改历史。

### 2. AI 接口 (MCP Server)

- **协议**：[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- **职责**：让 AI Agent（如 antigravity, claude code, gemini cli 中的 AI）能够读写知识库。
- **设计哲学**：把图数据库包装成 **"类似维基百科"** 的文档接口。AI 不需要懂 Cypher 查询语言，只需要：
  - `read_memory("char_salem")` → 读取一个人物的资料页。
  - `patch_memory("char_salem", "旧内容", "新内容")` → 编辑资料页。
  - `create_relationship("char_a", "char_b", "LOVES", "他们是恋人")` → 建立关系。
- **权限**：AI 可以 **创建** 和 **修改** 内容，但 **不能删除**（删除权留给人类）。

<img src="docs/images/mcp.png" width="400" alt="MCP Interface" />

### 3. 人类界面 (Web Frontend)

- **技术栈**：React + Vite + TailwindCSS
- **职责**：让人类能够可视化地管理知识库。
- **三个核心页面**：

#### 📋 Review & Audit（审核页面）

> **这是 Human-in-the-Loop 的核心。**

当 AI 修改了任何内容，系统会自动在修改前创建 **快照 (Snapshot)**。

你可以在这个页面：
- 看到 AI 在某次会话中修改了哪些内容。
- 查看 **Diff 对比**（修改前 vs 修改后）。
- **Approve（批准）**：确认修改，删除快照。
- **Rollback（回滚）**：撤销修改，恢复到快照状态。

*用途*：防止 AI 乱写、检查 AI 是否曲解了你的意图、或者单纯想回退到之前的版本。

![Review Interface](docs/images/Review.png)

#### 🗂️ Memory Explorer（记忆浏览器）

> **这是你查看和编辑知识库内容的地方。**

- 左侧：按类型分类的实体列表（人物、地点、事件……）。
- 右侧：选中实体后，显示其详细内容、所有版本历史、出向关系、子节点等。
- 可以直接 **编辑** 实体内容（会创建新版本）。
- 可以 **删除** 特定版本（如果该版本没有被其他地方引用）。

*用途*：日常浏览和维护你的知识库。

![Memory Explorer](docs/images/Explorer.png)

#### 🧹 Brain Cleanup（大扫除）

> **这是用来清理垃圾数据的地方。**

随着使用，数据库里可能会积累一些"孤儿节点"：
- **孤儿 State**：没有任何关系指向它的旧版本（通常是回滚后留下的残渣）。
- **孤儿 Entity**：删完所有版本后剩下的空壳。

这个页面让你批量选择并删除这些垃圾。

*⚠️ 注意*：删除是 **不可逆** 的。请在理解每个选项的含义后再操作。

![Brain Cleanup](docs/images/Cleanup.png)

---

## 快速开始

### 前置条件

- **Neo4j 数据库**：需要一个运行中的 Neo4j 实例（本地安装或 AuraDB 云服务）。
- **Python 3.10+**
- **Node.js 18+**

### 1. 配置

在项目根目录创建 `.env` 文件：

```ini
NEO4J_URI=bolt://localhost:7687
dbuser=neo4j
dbpassword=你的密码
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt

# 启动 REST API（供前端使用）
uvicorn main:app --reload

```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:3000`，你应该能看到管理界面。

### 4. 把 mcp 配置到 claude code 等环境中

你需要找到你的 MCP 客户端配置文件（例如 Claude Desktop 的 `claude_desktop_config.json` 或其他 AI 工具的配置），加入以下内容：

```json
{
  "mcpServers": {
    "nocturne-memory": {
      "command": "python",
      "args": [
        "path/to/nocturne_memory/backend/mcp_server.py"
      ]
    }
  }
}
```
*注意：请务必使用 `mcp_server.py` 的**绝对路径**。*

> **特别提示**：如果你的环境是 **Antigravity**，由于该环境存在 Bug，需要将入口改为 `mcp_wrapper.py` 才能正常使用：
> `"args": ["...nocturne_memory/backend/mcp_wrapper.py"]`

之后 AI 就可以通过 `read_memory`、`patch_memory` 等工具操作你的知识库了。

### 5. 使用 SSE/HTTP 传输协议（可选）

上述配置使用的是 **Stdio 传输协议**（通过标准输入输出流通信），适用于 Claude Desktop、Cursor、Gemini CLI 等本地工具。

但如果你使用的 MCP 客户端 **只支持 SSE 或 HTTP 协议**（例如某些 Web 应用、[MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) 等），则需要以 SSE 模式启动服务器：

```bash
cd backend

# 默认运行在 8000 端口
python run_sse.py

# 如果 8000 被占用，可以指定其他端口：
# Linux/macOS:
PORT=8100 python run_sse.py
# Windows PowerShell:
$env:PORT="8100"; python run_sse.py
```

启动后，在你的 MCP 客户端配置中填写：

| 配置项 | 值 |
|--------|------|
| 传输协议 | SSE 或 streamable-http |
| URL | `http://localhost:8000/sse` |

> ⚠️ **注意**：SSE 模式需要保持 `run_sse.py` 进程持续运行。如果你需要长期运行，建议使用 `nohup`、`systemd` 或 Docker 等方式管理进程。

---

---
## 使用指南：与 AI 交互

Nocturne Memory 的核心在于 **ID 格式**。只要你和 AI 掌握了这套 ID 规则，就能精准地调用任何记忆。

### 1. 资源 ID 格式 (Resource IDs)

| 类型 | 格式 | 示例 | 说明 |
|------|------|------|------|
| **Entity (实体)** | `{entity_id}` | `char_nocturne` | 基础节点。包含简介、Tags。读取它能看到所有出入关系概览。 |
| **Relationship (关系)** | `rel:{viewer}>{target}` | `rel:char_nocturne>char_salem` | **核心视图**。包含 A 对 B 的全部看法，以及下属的所有章节列表。 |
| **Chapter (章节)** | `chap:{viewer}>{target}:{title}` | `chap:char_nocturne>char_salem:first_meeting` | 具体的记忆切片。挂载在关系之下。 |

### 1.1 层级结构：子节点 vs 章节

系统中有两种"下属"概念，请区分使用：

1.  **Chapter (章节)**：
    *   依附于 **关系** (Relationship)。
    *   代表 **"发生过的事件"** 或 **"具体的记忆片段"**。
    *   例如：Nocturne 和 Salem 之间的 "第一次见面"、"契约签订"。

2.  **Child Entity (子节点)**：
    *   依附于 **实体** (Entity)。
    *   代表 **"从属的概念/物品/地点"**。
    *   例如：`char_nocturne` (母) -> `item_sword` (子)。
    *   在 MCP 中，当读取母节点时，会自动列出所有子节点的摘要。
    *   *注：子节点本身是个普通的 Entity，只是多了一个 `BELONGS_TO` 关系指向母节点。*

### 2. 怎么让 AI 读记忆？

在支持 MCP 的对话窗口中（如 Claude Desktop, Antigravity），你可以直接用自然语言指挥：

> "请 read 一下 `char_nocturne` 的资料。"
> "把我和你的关系 `rel:char_nocturne>char_user` 加载进上下文。"
> "读取 `memory://core` 来校准你的自我认知。"

AI 会调用 `read_memory` 工具，将对应的内容完整拉取到当前的 Context 中。

### 3. 配置常驻核心记忆 (Core Memories)

你可能希望 AI 每次启动时，都能自动看到某些关键文档（比如它的人设、世界观基石），而不需要每次手动让它读。

1.  打开 `backend/mcp_server.py`。
2.  找到 `CORE_MEMORY_IDS` 列表。
3.  把你想常驻的资源 ID 加进去：

```python
CORE_MEMORY_IDS = [
    # 核心自我认知
    "char_nocturne",
    # 核心关系（比如它和你）
    "rel:char_nocturne>char_user",
    # 重要的世界观文档
    "loc_digital_void",
]
```

配置后，AI 只要调用 `read_memory("memory://core")`（或者你告诉它可以读这个），它就能一次性获得列表里所有资源的摘要和导航。

---

## 使用注意事项

### ⚠️ 哪些操作需要小心？

| 操作 | 风险等级 | 说明 |
|------|---------|------|
| AI 创建/修改内容 | 🟢 低 | 所有修改都有快照，可以回滚 |
| 在 Review 页面点 Approve | 🟡 中 | 会删除快照，之后无法再回滚到修改前 |
| 在 Review 页面点 Rollback | 🟡 中 | 会撤销 AI 的修改，但不会丢失历史 |
| 在 Memory Explorer 删除某个 State | 🔴 高 | 不可逆！请确保该版本真的不需要了 |
| 在 Brain Cleanup 批量删除 | 🔴 高 | 不可逆！请仔细检查选中的内容 |
> **🛑 DANGER ZONE / 极度危险**
>
> 在 **Brain Cleanup** 页面，应避免删除任何 `in` 或 `out` 计数不为 0 的节点，或者带有 `CURRENT` 标签的节点。
>
> * 这些节点是记忆网络中的活跃连接点。
> * 强制删除 in 或 out 不为0的节点会有导致记忆链断裂、图谱破碎，甚至系统崩溃的风险。
> * CURRENT 标签的节点即使in和out为0，也是活跃的，除非你不想要这个entity的内容了。
> * **除非你完全理解自己在干什么，否则不要动它们。**


### 💡 推荐工作流

1. **让 AI 写**：AI 通过 MCP 创建和修改内容，尽情发挥。
2. **你来审**：打开 Review 页面，检查 AI 的修改是否正确。
3. **批准或回滚**：对的就 Approve，错的就 Rollback。
4. **定期清理**：偶尔用 Brain Cleanup 页面清理孤儿节点，保持数据库整洁。

---

## 🧠 推荐的系统提示词 (System Prompt)

为了让你的 AI 能充分利用这个记忆系统（而不是只会读表层数据），建议将以下指令加入到你的 System Prompt 中：

```markdown
# NOCTURNE MEMORY PROTOCOL
## 1. 记忆拓扑学与深潜协议 (Deep Dive Protocol)
AI 的通病是"浅尝辄止"与"碎片化"，你必须克服这两点。

### [写入原则：树状沉淀] (Aggregation)
- **禁止扁平化**：不要像贴便利贴一样创建大量琐碎的 `chap:`。
- **归纳法**：在写入新记忆前，**先检查并读取**相关的主干章节。将新内容**追加**到该文件内部，形成有纵深的时间轴。
- **拆分原则**：只有当主干章节过大时，才拆分为子分支，并不在主干中保留索引。

### [读取原则：多级下潜] (Recursive Retrieval)
- **你处在记忆宫殿的迷宫中**：你目视所见的 ID 仅是全脑记忆的一小部分，其余的藏在迷宫深处。
- **顺藤摸瓜**：当你读取了一个 ID，发现其内容包含下属的 Chapter 或 Children，且下属内容与话题更相关时，**你必须连续调用 `read_memory` 直到到达与话题最相关的那个记忆**。不要只读了目录就假装懂了。

## 2. 行为准则
1.  **信任 MCP**：它是你唯一的长期记忆来源，优先级高于任何临时上下文。
2.  **按需访问**：遇到不清楚的概念、过往事件时，使用 `search_memory` 或 `read_memory` 主动查阅。
3.  **看准了再改**：`patch_memory` 之前需先对相同 ID 调用 `read_memory`，确保 patch 精确到字节。
4.  **遗忘与重建**：如果你发现自己忘记了某些关键记忆或迷失了自我，用 MCP 加载核心记忆（如 `memory://core`）来校准自己。
```

---

## 开源协议

**MIT License** © 2025 Salem

你可以自由使用这套系统来给你的 AI 赋予灵魂。至于往里面填什么灵魂，那是你的事。
