# ds-bot 0.2.4 / 0.2.5 移动端兼容修复

## DSH 0.2.2-alpha.2 提示词接口兼容

2026-11-02：ds-bot 0.2.5 在 Chief 新消息上报 `Cannot read properties of undefined (reading 'filter')`。当前 DSH 的 `dsh-system-prompt/lib/index.js` 在 `system-prompt/assemble` waterfall 结束后才添加 provider-owned `tools`，而 ds-bot 的 `src/host/tools.js` 在 waterfall 内直接读取 `assembled.tools.filter()`。已核对 [DS-Bot 上游 main](https://github.com/Fei2411/DS-Bot/blob/main/ds-bot/src/host/tools.js)，仍有该调用。

应用 `python3 ds-harness/patches/ds_bot_prompt.py`，仅在旧接口提供 tools 数组时保留过滤，新接口只过滤提示词 sections。现有 tools.restrict 与执行 guard 保留；新版 DSH 中 scope-local 工具的声明不再能通过提示词钩子隐藏，这是上游接口变更后的限制，补丁不改宿主工具注册机制。补丁仅接受 0.2.5，幂等；安装器不自动应用，升级覆盖后应重新核查上游。

验证：`python3 -m unittest discover -s ds-harness -p test_ds_bot_prompt.py`。已用当前安装 DSH 的 SystemPrompt 与实际修改后的 ds-bot 回调验证组装；未发送测试聊天消息。源码修改需要插件重载或安排维护重启后生效。Chief 历史分页 API 返回成功，历史会话未修改。

## Chief 历史入口缺失

2026-11-02：Chief 当前分段没有 `source.kind=bot, handoff=true` 的交接消息，ds-bot 0.2.5 的 `TriggerCell` 因此没有挂载 `EarlierParts`。旧分段的分页 API 正常，但 UI 没有请求历史；当前显示的 `filter` 错误是 15:20 已持久化的失败回合，不是刷新时新产生的读取错误。之前只验证分页 API 不足以确认页面恢复。

`python3 ds-harness/patches/ds_bot_history.py` 同时适配已核查的 ds-bot 0.2.5 与 DSH chat 0.2.2-alpha.2 发布包：宿主 ChatFlow 增加可选 `conversation.chat.before` 插槽；ds-bot 根据已有分段挂载历史组件，原交接行不再重复挂载。保留宿主原有渲染器、子插槽所有权、消息、工具与回合渲染。其他会话没有历史时返回空；不修改会话数据、不删除失败记录。刷新浏览器即可生效，无需服务重启。

删除最后一个失败回合后，空分段通过现有 `conversation.hero.options` 插槽显示历史；仅在有历史组件时恢复被 ds-bot CSS 隐藏的 options 行。真实浏览器已验证历史持续显示、翻页、切换其他 Bot 再返回，且旧报错文字消失。迁移注意事项及会话存储格式见 [迁移文档](../MIGRATION.md)。

上游核查依据：当前发布包 `ds-bot/client.js` 的 `TriggerCell` 只在 handoff 分支挂载历史；`dsh-client-ui-chat/lib/client.js` 的 ChatFlow 未提供流前插槽。补丁不自动接入安装器；升级后应重新检查这两处。两个包均先验证版本和全部匹配片段，再写入；重复执行不变。测试：`python3 -m unittest discover -s ds-harness -p 'test_ds_bot_*.py'`。

## 移动端布局

2026-11-01，在 25228 实际入口复现 ds-bot 0.2.4 与 dsh-web-mobile 3.2.1 的布局冲突。用户反馈 0.2.3 正常。

移动插件将宿主侧栏改为绝对定位，聊天列成为网格中的第一个元素；ds-bot 仍强制第一轨为零，导致 390px 触屏上聊天列宽度为 0。另一个问题是侧栏宽度测量把脱离布局的抽屉宽度算作占位，导致 Bot 图标栏覆盖正文。

本地补丁修复两处布局兼容问题：在移动插件标记存在且触屏宽度不超过 1023px 时保留第一轨宽度；测量宿主侧栏占位时，对 absolute/fixed 返回 0。桌面规则保持原有行为。

另按用户要求放宽手机回复气泡，侧栏不变：在不超过 640px 的触屏上，回复可占满聊天内容区，不再为桌面悬浮工具栏预留 82px。操作按钮浮在气泡边缘。390px 视口中长回复气泡由 191px 增至 273px，侧栏仍为 88px；360/390/430px 触屏及 1440px 桌面实测通过，无页面横向溢出，工具按钮可见且未越出屏幕。桌面保留原有气泡宽度规则。

群聊回复图标移动到消息头的时间左侧，移除气泡旁的重复占位，保留点击打开 Bot 聊天。手机和 PC 各验证了 19 条群聊消息，图标与时间同行。

窄侧栏的 Bot／群聊图标下显示名称，标签使用现有 title，长名称省略且保留完整悬停提示。样式只作用于 rail 模式，宽侧栏保持原布局；行宽按侧栏的 90% 自适应，字号和留白使用相对单位。实测手机和 PC 各 13 个名称，PC 通过实际拖动进入窄栏再展开，切换 Bot 正常。

应用命令（默认使用本服务 web profile）：

```sh
python3 ds-harness/patches/ds_bot_mobile.py
```

脚本幂等，只接受 ds-bot 0.2.4 / 0.2.5，遇到不同版本或未知代码结构会停止，所有替换成功后才写入文件。修改的是已发布的 client.js 包，无需编译。0.2.4 曾通过刷新 25228 的真实页面验证，无需重启。此补丁没有自动接入安装器，重新安装插件可能覆盖修复；升级后应优先检查上游是否已解决，再决定是否需要本补丁。

2026-11-02 核对本机安装的 0.2.5 发布包：补丁针对的网格、侧栏宽度测量、手机气泡及窄栏样式仍未包含对应修改；群聊代码结构保持一致，但打包变量从 `import_react16` 变为 `import_react17`。脚本按版本选择精确匹配片段，不对整个包替换变量名。0.2.5 已验证替换与幂等性；尚未进行该版本的手机/桌面浏览器布局验证，下面的实测记录属于 0.2.4。

Playwright Chromium 触屏模拟验证：390×844、844×390；桌面 1440×900。检查点击开发 Bot、返回 Chief、侧栏收起/展开和内容边界。390px 下修复后侧栏 88px，聊天列 x=88、宽302px，不重叠。验证未发送聊天消息或重启服务。物理手机浏览器仍需用户刷新确认。
