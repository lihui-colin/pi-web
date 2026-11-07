> 当前安装会自动执行单文件补丁 `srcs/patches/plugins/ds_bot/ds_bot_apply.py`，只支持 ds-bot 0.2.6 + DSH 0.2.2-alpha.2。以下旧版本问题仅为历史记录，不提供旧版本兼容。操作以 [统一补丁说明](srcs/patches/README.md) 为准。

# DSH 升级与迁移记录

## 当前生效范围（2026-11-02，ds-bot 0.2.6）

已撤销旧 Hero 历史区布局；Chief 历史使用下文原生消息流入口。头像位置、侧栏名称样式、移动侧栏网格、抽屉占位及操作按钮位置修复继续保留。用户随后反馈手机气泡未铺满，现仅对不超过640px的触屏恢复气泡 max-width:100%，桌面保持原样。实际390px视口：历史列273px、长回复气泡273px；桌面历史列960px、气泡768px，无横向溢出。

修复统一落在 `srcs/patches/plugins/ds_bot/ds_bot_apply.py`，先核验全部目标再写入；`--check` 只检查当前是否完整应用。旧 Hero 实验改动已从本轮仓库变更中清理。

提示词接口兼容补丁已适配并应用到 0.2.6，接口测试通过。它属于服务端修改，需要模块重载后生效；本次没有重启服务。以下旧 Hero 历史补丁说明是排查记录，不代表当前仍启用；不要重新执行 `ds_bot_history.py`。

### Chief 原生消息区历史入口

撤销旧入口后，空分段的 Chief 没有交接消息，原版界面没有历史入口。现使用 `python3 ds-harness/srcs/patches/plugins/ds_bot/ds_bot_apply.py`：Bot 报告历史分段是否存在，宿主在有历史时进入正常 active 会话并允许原生 Views 渲染；历史在原有 ChatFlow 前加载。没有新增 CSS、Hero 容器、固定高度或气泡规则。此补丁核验 ds-bot 0.2.6、DSH chat/conversation 0.2.2-alpha.2 的全部匹配点后再写入，保留原生插槽所有权。

实际 25228 浏览器验证：桌面1602×900历史列960px且居中，手机390×844历史列273px；原生 scrollBody 滚动，历史消息由18条分页到31条；桌面切换群聊再回 Chief 正常。两种视口没有用户气泡横向溢出、页面横向溢出或 pageerror。前端刷新即可生效，聊天数据未修改。

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
# 历史独立脚本已移除；当前版本改用 srcs/patches/plugins/ds_bot/ds_bot_apply.py
```

脚本只接受 ds-bot 0.2.5，遇到未知源代码结构会停止。修改的是服务端模块，必须让模块重新加载；现场配置不监听插件源码，因此安排了维护重启。已验证旧、新两类组装输入及当前安装 DSH 的实际 SystemPrompt 实现，未用自动发送聊天消息作为验证。

上游依据：核对时 [DS-Bot main 的 tools.js](https://github.com/Fei2411/DS-Bot/blob/main/ds-bot/src/host/tools.js) 仍有直接读取 `assembled.tools.filter()` 的调用；本机 DSH 实现已改变接口。升级时应重新核对，而不是无条件继续套补丁。

### 3. 当前分段缺少交接消息，旧历史没有入口

症状：Chief 只显示当前失败回合，看不到之前的聊天。历史分页 API 正常不代表界面恢复：最初接口验证成功，但真实浏览器没有发出历史加载请求。

根因：ds-bot 0.2.5 的 `TriggerCell` 只在 `source.kind === "bot" && source.handoff === true` 时挂载 `EarlierParts`。现场当前分段没有这条交接消息，但 `state.json` 仍保留五段历史引用。记录仍在磁盘，丢失的是显示入口；交接消息为何缺失尚未确认，不能据此断言历史数据被升级删除。

本地适配：DSH ChatFlow 增加可选 `conversation.chat.before` 插槽；ds-bot 根据会话已有分段加载历史，交接行不再重复挂载。空会话的 Hero 区域另用现有 `conversation.hero.options` 插槽显示历史，避免删除最后一个失败回合后看不到旧分段。保留宿主原有消息、工具、回合渲染和子插槽所有权。

```sh
# 历史实验脚本已移除，不再应用
```

该脚本同时修改 ds-bot 0.2.5 的 `client.js` 和当前全局 DSH 中 `dsh-client-ui-chat@0.2.2-alpha.2/lib/client.js`，先核验两个包的版本和匹配片段再写入。前端修改刷新页面即可加载，不需要重启服务。

上游核查依据是上述两个现场发布包：ds-bot 仅在 handoff 分支挂载历史，DSH ChatFlow 尚无流前插槽。不能把宿主原有 ChatFlow 直接作为普通 React 子组件包裹后替换插槽：这样会丢失 `renderSlot` 授权；复制其 children 声明又会触发重复声明错误。

验收应使用真实浏览器：Chief 历史出现并保持、翻页返回更多内容、切到其他 Bot 再返回仍正常、无 React 渲染错误。现场两页分别返回 27 和 22 条。删除旧失败回合后已重新完成这些验证，并断言页面不再包含旧 `filter` 报错。

空分段还有一处样式适配：ds-bot 原有 CSS 隐藏 Hero 的 workspace/options 行，历史虽已请求成功仍不可见。补丁仅在该行包含 `.bt-history-hero` 时恢复显示，并将历史放在输入框上方；无历史的普通空会话保持原样。

2026-11-02，ds-bot 0.2.6 的 Chief 出现顶部大块空白：原历史补丁使用 `maxHeight: 60vh`，叠加 Hero 的 `justify-content:flex-end`，在 900px 高的实际页面中使历史区从 y=294 开始。已移除限高，仅对包含 `.bt-history-hero` 的祖先链分配剩余高度、允许 flex 子项收缩并让历史区内部滚动；标题保留 60px 安全间距，输入框位于底部。桌面实测历史区 y=60、高774px。不是历史数据缺失；不应通过删记录或继续限制历史区高度修复。旧补丁可原位幂等升级。

### 4. 删除失败回合时保护会话存储格式

修复代码不会自动删除已持久化的旧报错。应区分“刷新后再次看见旧失败记录”和“新发送的消息再次失败”；只有用户明确要求才删除旧记录。

维护前备份目标会话、Bot 状态和索引，确认无运行任务，再停服修改，避免内存中的 Session 覆盖磁盘。删除范围限定为目标失败回合；历史分段应以 SHA-256 核对不变。重编号后必须处理目标会话的索引游标，但独立的 memory 用量记录应保留。

**`session.v4.jsonl.zstd` 不是任意压缩的 JSONL。** 第一帧必须恰好包含一行 session header，后续事件批次使用独立 Zstandard 帧，采用校验和。本次维护最初将 header 与事件压成同一帧，宿主拒绝读取并报 `first frame is not exactly one header line`；随后按独立 header 帧及事件帧重写并验证恢复。应同时验证压缩帧结构、宿主分页读取和实际页面；不能仅以 `zstdDecompressSync` 解压成功作为验收。优先使用上游正式编辑能力；手工维护必须保留可恢复备份。

## 迁移操作与验证清单

1. 保存配置、插件版本、会话和附件；数据只使用本服务目录。确定维护窗口，在独立维护进程中执行停服、变更、启动及就绪检查。
2. 核对上游是否已修复，再决定应用上述补丁。补丁未自动接入安装器；重新安装 DSH 或 ds-bot 会覆盖修改。
3. 执行 `python3 -m unittest discover -s ds-harness/tests -p 'test_ds_bot_*.py'`，检查补丁幂等性与未知结构拒绝行为。
4. 按需执行 `bash ds-harness/dsh_web_run.sh stop`、`bash ds-harness/dsh_web_run.sh start`。不要把重启当作默认验证步骤；不要使用 Pi Web 或 Paseo 的脚本。
5. 核查真实 HTTPS 入口、插件激活、Chief 历史显示与翻页、会话切换。若清理过失败回合，再检查错误提示消失且历史保留。

详细补丁说明见 [srcs/patches/README.md](srcs/patches/README.md)。现场诊断、维护日志和数据备份放在 `log/`，不提交 Git。
