# 安装与同步

## 分支约定

`main` 是可独立维护的纯上游分支，安装和同步脚本不更新或依赖它。`terminal-patch` 是独立根提交开始的补丁分支，只保存定制维护所需的文件。不要将这两个分支相互 merge 或 rebase；通过应用 `.patch` 文件组合代码。

`patches/0001-terminal-redraw.patch` 仅包含终端重连重绘修复及其测试；Chat 与 Workspace Panel 使用官方布局；`patches/0002-preserve-terminal-replay-modes.patch` 保留裁剪回放缓存时的终端模式，避免刷新后丢失 Codex 的滚轮输入；`patches/0003-terminal-osc52-clipboard.patch` 将 Codex 等 TUI 发出的复制请求写入浏览器所在电脑的剪贴板。`patches/base-commit` 是整组补丁的唯一上游基线，必须包含一个完整的 40 位小写十六进制 commit ID。同步和普通安装使用这个提交；`update` 会先用官方 `main` 最新提交更新该文件。补丁和基线应一起审查、验证、提交。

## 补丁分组

当前维护 8 个按功能划分的补丁：

| 编号 | 内容 |
| --- | --- |
| `0001` | 终端回放后的 TUI 重绘及测试 |
| `0002` | 回放缓存裁剪时保留终端模式及测试 |
| `0003` | OSC 52 复制请求处理，以及共用剪贴板 API 可用性检查 |
| `0004` | 终端触摸滚动及测试 |
| `0005` | Shift+← 软键 |
| `0006` | 完整 Codex 插件、移动端布局、Plan 入口、复制兼容和构建集成及测试 |
| `0007` | 添加项目弹窗中的候选目录自动换行，并显示完整已选路径 |
| `0008` | 设置中的内网 HTTPS 证书生成、CA 和服务器证书下载 |

原 `0007`–`0017` 的最终效果已合并到上述补丁，不再保留中间界面方案。共用的 `terminal/clipboard.ts` 修复归入 `0003`，其余 Codex 调整归入 `0006`。未来修改已有功能时，更新对应补丁；不要将已经被后续实现替换的中间步骤继续堆叠为新补丁。

整理补丁时，先在独立目录应用原补丁链并记录 `git write-tree`，再从相同基线应用整理后的补丁链，对比 `git write-tree`。仅整理、不改变功能时，两者必须完全一致；测试和构建按下文执行。

## 本地安装（不启动服务）

在 `terminal-patch` 工作区执行：

```bash
# 自动同步固定提交并安装
sh scripts/install.sh
```

`install.sh` 首先检查 `data/pi-web.conf`，不存在时从根目录 `pi-web.conf.example` 创建，已有配置保持不变。随后检查反向代理系统依赖，缺失时由 `install-system-deps.sh` 安装，再执行：

1. 创建独立安装仓库，以 detached HEAD 检出 `patches/base-commit` 指定的提交（先由 sync.sh 同步至 data/pi-web-upstream.git），按文件名顺序应用当前工作区 `patches/*.patch`，使用 Git 三方合并。
2. 在生成目录的 `.npmrc` 中配置 node-pty/esbuild 的安装脚本权限，安装依赖。
3. 运行测试并构建。
4. 若 PATH 中没有 `pi` 命令，全局安装 `@earendil-works/pi-coding-agent`（默认 `latest`，可设置 `PI_VERSION`）；已有 Agent 保留当前版本。安装失败会停止，不替换 pi-web。
5. 使用当前 npm 的全局安装前缀，将 `pi-web`、`pi-web-server`、`pi-web-sessiond` 链接到构建成功的新目录，替换旧的全局 npm 安装，打印安装目录和命令路径。此步骤跳过生命周期脚本和自动 peer 依赖安装，不更新 Pi Agent。

默认安装仅补装缺失的 Pi Agent，不升级已有 Agent、不推送 Git 远端，不注册 pi-web 服务、不启动或重启服务，也不会调用 `node dist/cli.js install`。安装会先执行 `sh scripts/sync.sh` 同步指定提交；同步失败即停止，不安装依赖或替换全局命令。旧的 `--port` 等服务安装参数不再接受。

每次创建的安装目录位于 `data/pi-web-releases/release.*`，可设置 `PI_WEB_INSTALL_ROOT` 改变位置。测试或构建失败会停止并保留现场，已安装或运行的版本不变。旧目录不会自动清理。

构建成功后，全局命令指向新的独立安装目录，因此不要删除正在使用的 release 目录。全局前缀需可写；使用 nvm 时替换的是当前 Node 环境中的安装。如果 `command -v pi-web` 与脚本输出的命令路径不同，请检查 PATH 中是否有其他安装抢先匹配。

已运行的进程需要手动重启。如果自己的启动脚本或服务配置写死了旧 release 的绝对路径，还需要将其改为新的路径。模型提供商认证和启动配置由使用者单独管理；已有 Pi Agent 的升级使用 `update --pi-only`。

`sync.sh` 先检查 `data/pi-web-upstream.git`，已有指定提交时跳过远端下载，可离线准备源码；缺失时才按 commit ID 从官方仓库获取基线，可通过 `PI_WEB_UPSTREAM_URL` 改变上游仓库地址，但不能覆盖基线版本。它不拉取最新 `main`、不修改任何分支、不推送远端，也不要求配置 `origin`。`sync.sh --local` 只使用 `data/pi-web-upstream.git` 缓存中的同一提交，缺失时明确报错。两种脚本都不会自动提交或推送 `terminal-patch` 的修改，安装前应审查补丁工作区并提交要共享的修改。

## 只同步代码并准备补丁版本

```bash
# 在 terminal-patch 分支中
release_dir=$(sh scripts/sync.sh)
cd "$release_dir"
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
NODE_OPTIONS=--no-experimental-webstorage npm test
npm run build
```

`sync.sh` 获取固定提交，在独立目录应用补丁并输出目录路径，不更新 Pi Agent、不安装依赖、不测试构建、不重启服务。Node 26 的测试需上述 `NODE_OPTIONS`，其他版本可直接运行 `npm test`。

已有的本地或远端 `main` 可以领先于补丁基线，也可以在其他 worktree 中使用；同步不修改这些分支和工作区。基线文件缺失、格式错误、提交不可获取时脚本会失败，不会回退到 `main` 或其他版本。

## Codex 终端选中即复制

Codex TUI 松开鼠标后可能显示 `Copy sent to terminal — paste to verify`，这表示已发送复制请求。补丁版 pi-web 会处理实时输出中的 OSC 52 请求，写入成功后在终端底部居中浮现 `Copied`，2 秒后自动消失；连续复制会重新计时。提示在 Fullscreen 模式下同样可见，不改变终端尺寸，也不拦截鼠标操作。它支持分段传输和 UTF-8 文本；刷新或重连时的历史回放不会再次复制旧内容。

如果浏览器阻止自动写入，终端底部居中会显示 `Automatic copy was blocked.`，保留到重试或手动关闭；点击 **Copy to clipboard** 重试。通过局域网 HTTP 访问时，浏览器通常没有异步剪贴板 API，此按钮会使用点击触发的兼容复制方式。浏览器策略仍可能拒绝写入，只有显示 `Copied` 才表示复制接口报告成功。

安装包含此补丁的版本后，重启提供网页资源的 `pi-web-server` 并刷新页面。本补丁仅修改浏览器端，不需要为此重启 `pi-web-sessiond` 或重新创建 Codex 会话。

## 升级补丁绑定的上游版本

`update` 会自动升级到官方 `main` 最新基线；也可手动选择基线。在 `terminal-patch` 工作区，先获取并选定要适配的上游提交，写入基线，然后准备补丁目录：

```bash
git fetch https://github.com/jmfederico/pi-web.git main
git rev-parse FETCH_HEAD > patches/base-commit
sh scripts/sync.sh
```

这里手动获取 `main` 仅用于选择新基线。也可以获取一个已知的完整 commit ID；后续安装始终使用写入文件的固定提交。准备成功后，在打印的 release 目录安装依赖、测试和构建；如有冲突，按下一节处理。验证通过后，将基线与适配后的补丁一起提交，其他使用者获取补丁分支的更新后执行 `install.sh`。

## 上游变化导致补丁冲突

脚本会在冲突补丁处停止并打印保留目录，后面的补丁尚未应用。可在该目录查看 `git status` 和冲突内容。

重新生成补丁时，使用独立维护工作区，从 `patches/base-commit` 指定的纯上游提交开始。按编号逐个应用补丁，每个补丁解决冲突后生成差异并做一个本地维护提交，再处理下一个：

```bash
# HEAD 必须是当前补丁应用前的状态：上游基线 + 已提交的前序补丁
# 将路径和编号替换为实际值
git apply --3way --index /补丁工作区/patches/0001-terminal-redraw.patch
# 如有冲突，编辑解决后仅暂存对应文件
git add <已解决的文件>
# 全部解决后，该命令应无输出
git diff --name-only --diff-filter=U
git diff --cached --binary --full-index HEAD > /补丁工作区/patches/0001-terminal-redraw.patch
git commit -m "Apply patch 0001"
# 对 0002、0003 依次重复，然后安装依赖、运行测试和构建
```

`0001` 与 `0003` 会修改同一文件，因此不能按文件名将整个 release 的累计差异分别导出。`patches/base-commit` 始终记录纯上游提交，不要写入上述本地维护提交的 ID。全部补丁适配后，在补丁工作区重新运行 `sync.sh --local`，验证整组补丁可从上游基线顺序应用，并在新目录完成测试和构建。

然后在补丁工作区提交并推送：

```bash
cd /补丁工作区
node --test tests/*.test.mjs
git add patches
git commit -m "fix: adapt patches to upstream"
git push origin terminal-patch
sh scripts/install.sh
```

更新基线时，应验证补丁在新提交上的测试和构建，再同时提交 `patches/base-commit` 和补丁。仅运行 `sync.sh` 不会升级基线，安装始终可复现同一组上游源码与补丁。

## 运行脚本更新

```bash
bash scripts/pi-web-run-jmfederico.sh update                  # 更新 Pi Agent，并同步、构建补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --pi-only        # 只更新 Pi Agent
bash scripts/pi-web-run-jmfederico.sh update --web-only       # 只同步、构建补丁版 pi-web
bash scripts/pi-web-run-jmfederico.sh update --dry-run        # 预览操作
```

`install` 先执行 `sync.sh` 复用缓存（缺失时下载）并应用补丁；`update` 默认先将 Pi Agent 更新到 latest，再获取官方 `main` 最新提交并原子写入 `patches/base-commit`，随后调用 `sync.sh` 同步并应用补丁，随后安装依赖、测试、构建和替换全局命令。更新不需要 origin 的推送权限，也不会自动更新补丁分支；新基线如与补丁冲突，更新停止并保留新基线和冲突目录，需适配补丁后重试。拉取失败不改写基线，`--dry-run` 不拉取或改写基线。补丁冲突或测试构建失败时，不会替换已安装的 pi-web；之前已完成的 Agent 更新或源码同步不会回滚。

`update` 不启停服务。支持 `--update-relay`；update 的 Agent 目标固定为 `latest`，`PI_VERSION` 只控制普通 install 补装 Agent 的版本。pi-web 使用 `patches/base-commit`，不使用 `PI_WEB_VERSION`。更新仅通过运行脚本 `pi-web-run-jmfederico.sh update` 执行；`install.sh` 只负责安装，不接受 `update` 子命令。更新完成后，如需生效，先确认活跃会话允许中断并保存恢复信息，再执行 `bash scripts/pi-web-run-jmfederico.sh restart`；实例由当前 `data/pi-web.conf` 选择，不接受 `--port` 参数。旧的 `update-pi-web-jmfederico.sh` 已移除；`install.sh` 不带子命令时默认执行 `install`，运行管理脚本则必须指定子命令。

## 内网 HTTPS 证书面板

安装包含 `0008` 的版本后，在 **Settings → General → 内网 HTTPS 证书** 填写访问站点的 IPv4 / IPv6 地址，点击“生成证书”。服务器需要可执行的 OpenSSL 1.1.1 或更新版本。面板属于当前网关，不随所选远程工作区切换。

生成的服务器证书有效期为 397 天，内部 CA 为 10 年。可下载 CA 证书用于设备信任，也可下载服务器公钥证书；私钥只保存在服务器。重新签发沿用已有 CA，已经信任该 CA 的设备无需重新安装。面板显示的是最近一次生成结果，不判断当前 Nginx 是否正在使用该证书。

文件保存在 `$PI_WEB_DATA_DIR/certificates/`。面板提供本次服务器证书和私钥的绝对路径，将它们填入 Nginx 的 `ssl_certificate` 和 `ssl_certificate_key`，检查 Nginx 配置后重新加载 Nginx。目录权限为 0700、私钥为 0600；若 Nginx 无权读取，应由管理员将服务器证书和服务器私钥复制到受保护的 TLS 目录，不要放宽整个 CA 目录的权限，也不要复制 CA 私钥。

每台访问设备下载并信任 CA 后，使用证书内的 IP 通过 HTTPS 访问。具体安装提示可展开面板中的“如何安装和信任 CA 证书”。网页不能自动安装信任。已有代理的 `/pi-web-ca.crt` 下载地址可能指向旧 CA；本面板链接使用 `/api/certificates/ca.crt`，应以与服务端证书配套的 CA 为准。

生成操作不会修改 Nginx、启用 HTTPS 或重启 pi-web。旧证书目录会保留，以免影响引用旧路径的代理；确认代理切换完成后可由管理员清理不再使用的 `server-*` 目录。备份时保护整个证书目录，尤其是 `ca/ca.key`。CA 不完整或有效期不足时会停止签发，不会自动更换设备已经信任的 CA。

若服务在生成期间异常退出，可能留下 `certificates/.generate-lock`。确认没有仍在生成的任务后才能移除该锁目录并重试。此面板沿用站点的访问边界，部署时应限制站点访问权限。


## 反向代理安装与统一启停

`sh scripts/install.sh` 自动检查 Nginx、OpenSSL、curl 和系统 CA 证书，已有组件直接复用。Debian/Ubuntu 缺少组件时通过 apt 安装；非 root 用户只在系统包阶段使用 sudo，后续 npm 构建仍使用当前用户。其他系统请先手动安装缺失组件。应用更新 `update` 不执行系统包安装；需要单独补齐组件时运行：

```bash
bash scripts/install-system-deps.sh --check    # 只检查；缺失时返回失败
bash scripts/install-system-deps.sh --dry-run  # 预览缺失组件，不提权、不联网
bash scripts/install-system-deps.sh            # 安装缺失组件
```

包安装保留已有 Nginx 配置和证书，不覆盖站点配置；使用临时 `policy-rc.d` 阻止包钩子启停服务，并让 needrestart 只报告状态。原有策略文件（包括符号链接）在成功、失败和可处理的中断后恢复。若机器断电或安装进程被强制杀死，检查 `/usr/sbin/.pi-web-policy.*` 中的备份，再恢复 `/usr/sbin/policy-rc.d`；不要在包安装仍运行时删除策略。

首次部署时，运行 `bash scripts/pi-web-run-jmfederico.sh nginx-config > /tmp/pi-web.nginx.conf`，按实际域名/IP 和证书路径调整输出，再安装到 `/etc/nginx/conf.d/pi-web.conf`。生成命令从本地配置读取 `PI_WEB_NGINX_PORT` 作为 HTTPS 监听端口、`PI_WEB_PORT` 作为回环后端端口；只输出配置，不修改系统文件或启停服务。证书可由设置面板生成；后端只绑定回环地址时，浏览器统一通过 Nginx 访问。脚本不自动生成或替换证书。

对于专用于 pi-web 的系统 Nginx，在 `data/pi-web.conf` 中配置：

```bash
PI_WEB_NGINX_ENABLED=true
PI_WEB_NGINX_PORT=25224
# 可选：覆盖自动生成的健康地址
# PI_WEB_NGINX_PROBE_URL=https://127.0.0.1:25224/api/pi-web/health
```

配置仅从该文件读取，不接受同名环境变量覆盖。模板默认关闭 Nginx 管理，供尚未配置代理的新安装使用。此开关管理整个系统 `nginx` 服务，不按后端端口隔离；本部署的 Nginx 专用于 pi-web。更改代理端口后需重新生成并安装 Nginx 配置，在允许中断的维护时机生效；默认健康地址自动跟随端口，显式设置了 `PI_WEB_NGINX_PROBE_URL` 时需同步更新该地址。

非 root 用户先在终端执行 `sudo -v`，随后使用原有管理命令：

```bash
bash scripts/pi-web-run-jmfederico.sh start
bash scripts/pi-web-run-jmfederico.sh status
bash scripts/pi-web-run-jmfederico.sh stop
bash scripts/pi-web-run-jmfederico.sh restart
```

`start` 先执行 `nginx -t`，配置错误时不创建后端进程；后端就绪后才启动 Nginx，已运行时直接复用。代理的健康接口必须返回 `ok: true`，仅 Nginx 进程存活或返回默认欢迎页面不算就绪。该探测忽略内部 CA 的信任校验，只检查代理通路，设备仍需自行安装信任 CA。代理启动或健康检查失败会返回失败，后端保持运行以保护会话。

`stop` 先停止 Nginx 并确认状态，再停止语音服务和 pi-web 后端；Nginx 停止失败时中止，不继续终止会话。`restart` 在完整停止成功后再启动。脚本通过 `service nginx` 兼容 Debian/Ubuntu 的服务管理入口，无需将整个 pi-web 进程以 root 身份运行。`status` 会同时显示 Nginx 和代理健康状态。

停止和重启会中断连接及会话；仍需遵守仓库的会话保护规则，在允许中断的时机由独立维护进程执行。本次修改脚本不会自动执行这些操作。
