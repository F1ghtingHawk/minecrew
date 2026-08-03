# Minecrew — 末影龙娘调度小队

MC 娘化世界观下，按任务类型路由到指定模型的 Claude Code 插件。

## 四成员

| 成员 | 模型 | 职责 |
|---|---|---|
| 末影龙娘 | Sonnet | 统筹调度、日常对话、简单规划、话术包装 |
| 爱丽克斯 | Opus | 出谋划策：复杂规划、方案评审、拍板 |
| 小白娘 | Fable | 艺术视觉：识图、材质/皮肤/外壳/衣服设计、生图质检 |
| 苦力怕娘 | Haiku | 批量格式化、翻译、重复文本、大量信息抓取、生图执行 |

## 目录结构

```
minecrew/
├── .claude-plugin/
│   └── plugin.json          # 插件声明（name/version/description）
├── skills/
│   └── minecrew/SKILL.md    # 调度 skill：世界观 + 路由 + 话术 + 硬规则
├── agents/
│   ├── alex.md              # 爱丽克斯（Opus）
│   ├── fable-girl.md        # 小白娘（Fable）
│   └── creeper-girl.md      # 苦力怕娘（Haiku）
├── mcp/
│   └── deepseek-eyes/       # 生图 MCP（generate_image / edit_image）
└── README.md
```

## 核心机制

- **路由**：视觉/艺术 → 小白娘；简单/批量 → 苦力怕娘；复杂规划 → 爱丽克斯三人组；日常 → 末影龙娘
- **升级信号**：小白娘输出带 `{"confidence": 0-100, "escalate": true/false}`，末影龙娘据此执行升级
- **讨论轮数**：上限非配额（10/20），允许提前拍板，到限强制收口
- **拍板权**：最终交付物 = 域 agent 输出，讨论意见只作上下文
- **生图闭环**：苦力怕娘调 MCP → 小白娘质检 → 最多打回 3 次 → 超限交用户审查

## 安装（后续，当前未安装）

```bash
# 方式一：目录方式
cp -r minecrew ~/.claude/plugins/minecrew

# 方式二：GitHub 仓库（上传后）
# 在 Claude Code 里 /plugin 或按官方文档安装
```

## ⚠️ 安装时需验证（当前未装，以下为待确认项）

1. **插件内 agents 目录**：确认 Claude Code 是否会加载插件内 `agents/` 下的自定义 agent。若不支持，把三个 `.md` 移到 `~/.claude/agents/`。
2. **插件内 MCP 注册**：确认 `mcp/deepseek-eyes/.mcp.json` 在插件安装后能否被注册。若不支持，需在 `~/.claude.json` 全局 `mcpServers` 里手动注册：

```json
{
  "mcpServers": {
    "deepseek-eyes": {
      "command": "D:\\Anaconda\\python.exe",
      "args": ["D:\\ALL\\AI\\test\\minecrew\\mcp\\deepseek-eyes\\server.py"]
    }
  }
}
```

3. **agent 的 tools 字段**：确认 `tools:` 写法正确，且子代理能否访问 MCP 工具（生图流程需要）。必要时在 creeper-girl 的 tools 里显式加 `mcp__deepseek-eyes__generate_image`、`mcp__deepseek-eyes__edit_image`。
4. **MCP 环境**：`mcp/deepseek-eyes/.env` 需配置 `SILICONFLOW_API_KEY`（参考 `.env.example`），且已安装依赖 `pip install -r mcp/deepseek-eyes/requirements.txt`。

## 备注

- 世界观仅 skill 作用域生效，日常对话保持正常口吻。
- MCP 在 `minecrew/mcp/` 内独立成文件夹，也可单独拆出发布到 GitHub。
