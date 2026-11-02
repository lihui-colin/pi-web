# DSH 升级与迁移记录

## ds-bot 0.2.5 与 DSH 0.2.2 系列兼容性

核查日期：2026-11-02。现场版本为 **ds-bot 0.2.5 + DSH 0.2.2-alpha.2**（25228 Web 实例）。以下结论以这个预发布版本为准，不能直接视为所有 0.2.2 正式版或后续版本的结论。数据目录为 `ds-harness/data/.dsh`，额外插件位于其 `profiles/web/node_modules/`。

### 1. 升级后前后端版本混用，fileDrag 缺失

症状：Web 启动提示四个插件未激活，聊天、附件、文档预览等待 `fileDrag`，侧栏增强等待 `documentPreviews`。

现场依据：运行中的后端启动于 14:34，磁盘上的官方 Web 配置在 15:10 更新。新配置已含 `ui-file-drag`，但旧后端返回的 HTML 插件清单没有该插件，同时加载了新版前端文件。这是升级后的进程配置与磁盘资源不一致，并非需要自行实现 `fileDrag`。

处理：核验实际进程、代理转发和活跃任务后，用本服务脚本先 `stop` 再 `start`。市场内自重启可能留下过期 PID；必须核对启动参数、用户、启动时间、`DSH_LAUNCH_ID` 与网络命名空间后恢复管理记录，不能删除 `.identity` 来绕过检查。

验收：HTTPS 返回 200，实际入口 HTML 包含 `dsh-client-ui-file-drag`，浏览器不再报上述依赖等待。仅检查 `--dump-config` 不足以证明运行实例已经更新。

### 2. 提示词组装钩子的 tools 字段被移出

症状：Chief 发送消息后出现 `This turn failed: Cannot read properties of undefined (reading 'filter')`，模型调用尚未开始。

根因：ds-bot `src/host/tools.js` 的 `filterBotAssembly` 在 `system-prompt/assemble` waterfall 内调用 `assembled.tools.filter()`。当前 DSH 的 `dsh-system-prompt/lib/index.js` 只将 `sections`、`contexts`、`variables` 交给该 waterfall，结束后才补上 provider-owned `tools`。

本地适配：只有旧接口实际提供 tools 数组时才执行原工具过滤；新接口仍过滤提示词 sections，保留 ds-bot 的 `tools.restrict` 和执行 guard。新版宿主中的 scope-local 工具声明已不能通过这个提示词钩子隐藏；补丁没有改写宿主的工具注册机制。

```sh
# 仓库根目录执行
python3 ds-harness/patches/ds_bot_prompt.py
```

脚本只接受 ds-bot 0.2.5，遇到未知源代码结构会停止。修改的是服务端模块，必须让模块重新加载；现场配置不监听插件源码，因此安排了维护重启。已验证旧、新两类组装输入及当前安装 DSH 的实际 SystemPrompt 实现，未用自动发送聊天消息作为验证。

上游依据：核对时 [DS-Bot main 的 tools.js](https://github.com/Fei2411/DS-Bot/blob/main/ds-bot/src/host/tools.js) 仍有直接读取 `assembled.tools.filter()` 的调用；本机 DSH 实现已改变接口。升级时应重新核对，而不是无条件继续套补丁。

### 3. 当前分段缺少交接消息，旧历史没有入口

症状：Chief 只显示当前失败回合，看不到之前的聊天。历史分页 API 正常不代表界面恢复：最初接口验证成功，但真实浏览器没有发出历史加载请求。

根因：ds-bot 0.2.5 的 `TriggerCell` 只在 `source.kind === "bot" && source.handoff === true` 时挂载 `EarlierParts`。现场当前分段没有这条交接消息，但 `state.json` 仍保留五段历史引用。记录仍在磁盘，丢失的是显示入口；交接消息为何缺失尚未确认，不能据此断言历史数据被升级删除。

本地适配：DSH ChatFlow 增加可选 `conversation.chat.before` 插槽；ds-bot 根据会话已有分段加载历史，交接行不再重复挂载。空会话的 Hero 区域另用现有 `conversation.hero.options` 插槽显示历史，避免删除最后一个失败回合后看不到旧分段。保留宿主原有消息、工具、回合渲染和子插槽所有权。

```sh
python3 ds-harness/patches/ds_bot_history.py
```

该脚本同时修改 ds-bot 0.2.5 的 `client.js` 和当前全局 DSH 中 `dsh-client-ui-chat@0.2.2-alpha.2/lib/client.js`，先核验两个包的版本和匹配片段再写入。前端修改刷新页面即可加载，不需要重启服务。

上游核查依据是上述两个现场发布包：ds-bot 仅在 handoff 分支挂载历史，DSH ChatFlow 尚无流前插槽。不能把宿主原有 ChatFlow 直接作为普通 React 子组件包裹后替换插槽：这样会丢失 `renderSlot` 授权；复制其 children 声明又会触发重复声明错误。

验收应使用真实浏览器：Chief 历史出现并保持、翻页返回更多内容、切到其他 Bot 再返回仍正常、无 React 渲染错误。现场两页分别返回 27 和 22 条。删除旧失败回合后已重新完成这些验证，并断言页面不再包含旧 `filter` 报错。

空分段还有一处样式适配：ds-bot 原有 CSS 隐藏 Hero 的 workspace/options 行，历史虽已请求成功仍不可见。补丁仅在该行包含 `.bt-history-hero` 时恢复显示，并将历史放在输入框上方；无历史的普通空会话保持原样。

### 4. 删除失败回合时保护会话存储格式

修复代码不会自动删除已持久化的旧报错。应区分“刷新后再次看见旧失败记录”和“新发送的消息再次失败”；只有用户明确要求才删除旧记录。

维护前备份目标会话、Bot 状态和索引，确认无运行任务，再停服修改，避免内存中的 Session 覆盖磁盘。删除范围限定为目标失败回合；历史分段应以 SHA-256 核对不变。重编号后必须处理目标会话的索引游标，但独立的 memory 用量记录应保留。

**`session.v4.jsonl.zstd` 不是任意压缩的 JSONL。** 第一帧必须恰好包含一行 session header，后续事件批次使用独立 Zstandard 帧，采用校验和。本次维护最初将 header 与事件压成同一帧，宿主拒绝读取并报 `first frame is not exactly one header line`；随后按独立 header 帧及事件帧重写并验证恢复。应同时验证压缩帧结构、宿主分页读取和实际页面；不能仅以 `zstdDecompressSync` 解压成功作为验收。优先使用上游正式编辑能力；手工维护必须保留可恢复备份。

## 迁移操作与验证清单

1. 保存配置、插件版本、会话和附件；数据只使用本服务目录。确定维护窗口，在独立维护进程中执行停服、变更、启动及就绪检查。
2. 核对上游是否已修复，再决定应用上述补丁。补丁未自动接入安装器；重新安装 DSH 或 ds-bot 会覆盖修改。
3. 执行 `python3 -m unittest discover -s ds-harness -p 'test_ds_bot_*.py'`，检查补丁幂等性与未知结构拒绝行为。
4. 按需执行 `bash ds-harness/dsh_web_run.sh stop`、`bash ds-harness/dsh_web_run.sh start`。不要把重启当作默认验证步骤；不要使用 Pi Web 或 Paseo 的脚本。
5. 核查真实 HTTPS 入口、插件激活、Chief 历史显示与翻页、会话切换。若清理过失败回合，再检查错误提示消失且历史保留。

详细补丁说明见 [patches/README.md](patches/README.md)。现场诊断、维护日志和数据备份放在 `log/`，不提交 Git。
