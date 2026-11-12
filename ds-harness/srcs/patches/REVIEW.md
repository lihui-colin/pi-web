# DSH 补丁审查

审查基线：`7873e8070`。范围包括 12 个入口、`apply.py` / `common.py`、所有 JS helper、资产版本规划及三个固定版本 addon。对照本机及已缓存发布源码：DSH `0.2.2-rc.1`、xterm/headless `6.0.0`、serialize `0.14.0`、Bot `0.3.1`、mobile `3.3.5`；历史 alpha.2、Bot 0.2.6/0.2.7、mobile 3.2.1/3.3.0/3.3.1 通过对应兼容夹具核查。Git panel 当前未安装，核查了缓存的 1.13.1 发布包及 1.11.2/1.13.2 已有夹具和锚点。没有联网核查更高版本，结论不外推到未来版本。

## 已落实的两项修复

### P1：完整规划破坏已部署的直写模式

原 `dsh_terminal_apply.plan_changes()` 无条件规划旧增强；当前官方 UI 已有完整 direct sink 时，旧 patcher 仍能在原生锚点中插入旧工具、重绘和查询 helper。后续 `dsh_terminal_render_apply` 检测到混合 UI 后正确拒绝，导致统一安装/升级规划失败。

在实际安装副本上只读执行 `apply.plan_changes()`，基线稳定得到 `Mixed legacy terminal render candidate`。现保留旧入口的 UI/controller 同版及 headless/serialize 校验，随后对完整直写 UI 调用 direct patcher 精确验真（允许固定摘要的旧 helper 升级），跳过旧增强的三个目标。未知、残缺、混合及 alpha.2 冒充 direct 的情况仍拒绝。原版和完整旧增强的行为不变，没有删除功能，也不把旧增强自动切换成 direct。

对应 [dsh_terminal_apply.py](service/dsh_terminal_apply.py)。新增整体规划回归覆盖已部署直写模式和已知 helper 升级；审查阶段单独核对这两项调整时，原版完整安装的 11 个生成文件 SHA-256 与调整前一致；后续四项功能修复会按预期更新相应产物。

### P2：保持可见的终端重连后漏掉 fit

`dshBindTerminalRenderSink.visibility()` 原来只在 hidden → visible 时 fit。断线/只读期间的 ResizeObserver 会跳过测量，重新连接虽触发 writable/info effect，但 visible 一直为 true，因此新快照解析后仍保留旧的 Host 尺寸。

实际 helper 的隔离复现：先将 80×24 fit 到 120×30，再送入 80×24 新基线并重跑 visible effect；原实现 fitCount=1，停在 80×24。修复后 fitCount=2，回到 120×30。回归另覆盖断线期间目标宽度变到 132 的情况。

现每次原有 visible/writable/info effect 在可见时请求 gate.fit，仍等待 snapshot parse、保留双重实时 writable 校验；输出帧不触发该 effect。删除重复的 shown 状态，不增加输出热路径工作。只允许固定 SHA-256 的上一版 helper 迁移。

对应 [dsh_terminal_render.js](service/dsh_terminal_render.js) 和 [dsh_terminal_render_apply.py](service/dsh_terminal_render_apply.py)。

## 后续四项修复

以下四项均已完成源码修复和回归；当前实例的客户端和宿主修复均已发布，宿主已在检查活跃任务后通过独立维护进程重启生效。旧增强路径保持可用，但不会在当前 direct 模式上重新启用。

### P2：旧增强路径的快照重置缺少解析屏障

[dsh_terminal_apply.py](service/dsh_terminal_apply.py) 原来的 `WRITE_NEW` 在新快照到达时立即 reset，被取消代际的 `xterm.write()` 仍可能留在解析队列；基线 API 顺序会得到 `OLDFRESH`。旧形状保留作严格迁移锚点，实际生成改为 `FENCE_WRITE`：先空写排空，再核对 effect、终端、render 及 `model.pendingRender.revision` 后重置和写快照。旧回调不能重置、ACK 或复制到新代际，只读尺寸也在解析就绪后更新。

新测试实际执行生成的旧 UI effect 和 headless 6.0.0 / serialize 0.14.0，取消旧输出后仅剩 `FRESH`；覆盖模型已取消但 React 尚未提交、旧 fence/parse 回调、卸载、只读 ACK、OSC52 不回放。alpha.2 和 rc.1 完整 bundle 的迁移、语法及浏览器检查通过。当前 direct 模式继续保留，不重新叠加旧增强。

### P2：宿主合帧可超过合法的小缓冲配置

[dsh_terminal_host_batching.js](service/dsh_terminal_host_batching.js) 原先仅按 64KiB 原始数据合并，未参考 `host.maxBufferedBytes`。上游配置允许最小 1024，而 `TerminalFollower.push()` 按完整 JSON 帧字节数检查。

使用原样安装的 follower、每次发送后立即清空队列模拟快消费者：leading 首帧后在同一窗口合并 4×300B，帧尺寸为 45/1240B，1024B 配置直接失败。此问题不要求消费者变慢；正常较大默认缓冲未在该复现中失败。

现在按 JSON 头、序号位数及转义后的保守字节预算决定合并，原始大块仍交给上游处理。默认大预算由原始 64KiB 上限及编码膨胀上界保护，不逐块重复 JSON 编码；小预算才精算，分裂代理对采取保守计数。新增原样 native follower 夹具，覆盖 1024B、转义/UTF-8、序号进位、预算阈值、混合流顺序与单个原始过大块；仅接受完整摘要匹配的已发布 helper 升级。

### P2：会话首次接管会重建编辑器并丢焦点

[dsh_composer_metadata_apply.py](service/dsh_composer_metadata_apply.py) 原来的 `WRAPPER` 用 `props.sessionId` 给整个 `DshComposerFrame` 设置 key。上游 renderer 特意在 undefined → 第一个 session id 接管时保留组件身份；本地 key 却重建了包含 `DshInputBar` 的整棵树。

使用实际前端 React 和原生 `ComposerContentEditable` 的隔离验证：原生 sameNode=true / focused=true / additionalMounts=0；包装后 false / false / 1。该结论限首次接管；上游本来就会在不同已有会话间重挂载。没有声称 host 缓存的草稿丢失。

现去掉输入树祖先的会话 key，仅在 layout effect 中按 sessionId 重置披露状态。真实前端 React/DOM 和原生 ContentEditable 回归确认首次接管 sameNode=true、focused=true、additionalMounts=0，并覆盖组合事件和普通会话切换。此处验证节点身份与合成 composition 事件，不声称操作系统 IME 自动化。已发布 helper 和旧 wrapper 必须成对识别后才能升级，残缺及未知混装继续拒绝。

### P2：上下文详情 portal 被误判为披露外部点击

[dsh_composer_metadata.js](service/dsh_composer_metadata.js) 原来的 `dismissOutside` 仅识别 DOM 祖先/id/aria-controls，不能识别原生 ContextMeter 放到 document.body 的 portal。

手机披露展开 → 打开 context meter → 点击详情扩展按钮：外层披露 open=true → false，anchorVisible=true → false，原生弹层仍为 1 个；下一次定位刷新从 (58,733) 跳到 (12,12)。复现使用原生 ContextMeter、真实 AnchoredPosition/OutsidePointer hooks，Tooltip 为返回 children 的包装 stub；弹层 fixed 定位 CSS 为隔离夹具。

现在由 ContextMeter 显式标记本披露的 owner，并将该 owner 纳入 inside 判定；不同 owner 和普通外点照常关闭。owner 不可见时立即停止渲染并清理子弹层，防止主动折叠、换会话或响应式隐藏后留下漂浮弹层。真实原生定位/关闭 hook 回归覆盖 owned/unrelated portal、内部按钮、resize/scroll、Esc、主动折叠、会话切换、桌面可用性和卸载监听/observer 清理。

## 精简与上游复用结论

| 范围 | 核查结论 |
| --- | --- |
| shared planner / publisher | 版本校验、替换、资源指纹、原子替换和回滚已集中；本轮没有发现值得再加通用抽象的重复。 |
| 终端三层队列 | 宿主在 headless 解析后合帧，浏览器维护代际/序号/ACK/预算，sink 维护 xterm parse 屏障；职责不同，分别保留。 |
| 终端两种 UI | 可共享快照屏障设计，继续保留旧增强功能；此次先修安装模式冲突，不删除旧分支。 |
| keyboard / queries / snapshot | 复用 headless 查询解析和 serialize；serialize 仍缺鼠标编码、光标隐藏和同步输出，补充 helper 不可整体删除。 |
| WebGL / search / links | 使用固定摘要的官方 addon，无需重写或手工压缩；WebGL 命中透传、DOM fallback 和 context-loss 清理仍必要。 |
| Bot | 0.3.1 已有历史/安全 prompt/touch 操作栏，补丁已正确退役重复部分；表现偏好及历史版本迁移仍有效。 |
| mobile | 3.3.5 已有 Enter/IME 仲裁，继续复用；xterm 隐藏输入面的兼容尚未原生覆盖。 |
| Git panel | 可选包缺失跳过，保留 pill 移除及已核验版本锚点；无新增确定问题。 |
| resources / context details | rc.1 仍为 hostname-only 查询，仍无本地 context.details 槽位；现有补丁不构成已证实的上游重复。 |
| sidebar navigator | 显式父状态、多个 navigator 聚合、stale cleanup 及 specificity 保留正确；现有验证证明行为等价，未证明实际终端延迟改善。 |
| composer disclosure | 已去掉输入树祖先 key，并明确 portal 归属及 owner 隐藏时的清理，减少无用重建和生命周期分叉。 |

## 验证与生效边界

修复后完整运行 264 项 Python 回归，2 项旧 UMD 浏览器测试因未提供对应依赖跳过，其余通过。运行时启用了真实 native composer 生命周期、rc.1 旧增强浏览器、WebGL/DOM fallback、触屏焦点及 headless 屏障检查；alpha.2 旧增强浏览器另行通过。结果在不入库的 `ds-harness/data/patch-review/`。

客户端 conversation 和终端 lazy/entry 三个文件先行备份并发布。随后用户要求继续，在核对 292 个会话无执行中 DSH 任务、明确一个保留终端会被结束后，独立维护进程备份并发布宿主 `lib/index.js`，按 stop → start 完成重启。新 Host、依赖服务和 HTTPS 200 就绪；完整补丁检查通过，运行安装已无待应用目标。重启后的正常手机页面检查确认文字/中下部空白/边缘聚焦与输入正常且无浏览器异常，宿主真实类缓冲专项复测通过。此前保留终端需重新打开，当前 direct 模式不启用旧增强。恢复与部署记录在 `data/patch-review/host-budget-rollout-result.json` 及 `all-fixes-deployment-plan.json`。仓库变更尚未提交或推送。
