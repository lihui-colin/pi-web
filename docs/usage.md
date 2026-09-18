# 安装与同步

## 分支约定

`main` 是纯上游分支，只进行 fast-forward 同步。`terminal-patch` 是独立根提交开始的补丁分支，只保存定制维护所需的文件。不要将这两个分支相互 merge 或 rebase；通过应用 `.patch` 文件组合代码。

`patches/0001-swap-chat-workspace.patch` 包含面板交换功能及其测试。`patches/base-commit` 记录补丁制作时的上游基线，仅供更新补丁时参考，不固定安装版本。

## 本地安装（不启动服务）

在 `terminal-patch` 工作区执行：

```bash
# 首次安装前初始化 main；需要更新上游时也单独执行此命令
sh scripts/sync.sh
# 使用现有本地 main 安装
sh scripts/install.sh
```

`install.sh` 的执行顺序：

1. 从现有本地 `main` 克隆独立安装目录，按文件名顺序应用当前工作区 `patches/*.patch`，使用 Git 三方合并。
2. 在生成目录的 `.npmrc` 中配置 node-pty/esbuild 的安装脚本权限，安装依赖。
3. 运行测试并构建。
4. 使用当前 npm 的全局安装前缀，将 `pi-web`、`pi-web-server`、`pi-web-sessiond` 链接到构建成功的新目录，替换旧的全局 npm 安装，打印安装目录和命令路径。此步骤跳过生命周期脚本和自动 peer 依赖安装，不更新 Pi Agent。

安装脚本不更新 Pi Agent、不拉取或推送 Git 远端，不注册、启动或重启服务，也不会调用 `node dist/cli.js install`。若本地 `main` 不存在，会提示先运行 `sh scripts/sync.sh`；上游同步与安装分开执行。旧的 `--port` 等服务安装参数不再接受。

每次创建的安装目录位于 `~/.local/share/pi-web-opt/release.*`，可设置 `PI_WEB_INSTALL_ROOT` 改变位置。测试或构建失败会停止并保留现场，已安装或运行的版本不变。旧目录不会自动清理。

构建成功后，全局命令指向新的独立安装目录，因此不要删除正在使用的 release 目录。全局前缀需可写；使用 nvm 时替换的是当前 Node 环境中的安装。如果 `command -v pi-web` 与脚本输出的命令路径不同，请检查 PATH 中是否有其他安装抢先匹配。

已运行的进程需要手动重启。如果自己的启动脚本或服务配置写死了旧 release 的绝对路径，还需要将其改为新的路径。Pi Agent 安装、模型提供商认证和启动配置由使用者单独管理。

`sync.sh` 才负责获取官方上游并推送 `origin/main`。它使用当前仓库的 `origin` 配置，可通过 `PI_WEB_UPSTREAM_URL` 改变上游仓库地址。两种脚本都不会自动提交或推送 `terminal-patch` 的修改，安装前应审查补丁工作区并提交要共享的修改。

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

`sync.sh` 会更新本地和 origin 的 `main`，应用补丁并输出准备目录路径，不更新 Pi Agent、不安装依赖、不测试构建、不重启服务。Node 26 的测试需上述 `NODE_OPTIONS`，其他版本可直接运行 `npm test`。

手动同步纯上游分支的等价命令：

```bash
# 保持当前工作区位于 terminal-patch
# 如果尚未配置 upstream，先添加一次：
git remote add upstream https://github.com/jmfederico/pi-web.git
git fetch upstream main:refs/heads/main
git push origin main
```

`sync.sh` 支持 `main` 在另一个 worktree 中检出的情况：它先获取上游提交，确认 `main` 没有超出上游的提交，再在该工作区执行 `git merge --ff-only`。若有已跟踪文件的未提交改动，脚本会停止，提示先提交或暂存；不会自动 stash、reset 或切换分支。无冲突的未跟踪文件会保留。

上面的手动 fetch 命令仅适用于 `main` 没有被检出的情况。若 `main` 正在另一个 worktree 使用，可直接运行 `sh scripts/sync.sh`，或在那个干净的工作区执行 `git fetch upstream`、`git merge --ff-only upstream/main`，再推送 `main`。

如果本地或 origin 的 `main` 存在不属于上游的提交，fast-forward 或 push 会失败。审查差异并保存有用改动后再处理，不要用无条件强制推送覆盖远端。

## 上游变化导致补丁冲突

脚本会停止，打印保留的安装目录；纯上游 `main` 中不会写入补丁，也不会执行服务安装。在保留目录中查看 `git status`，解决冲突并测试，再生成替换补丁：

```bash
cd /脚本打印的/release.目录
git status
# 编辑并解决冲突后，仅暂存补丁涉及的文件
git add <已解决的文件>
# 全部解决后，该命令应无输出
git diff --name-only --diff-filter=U
printf '\nallow-scripts=node-pty,esbuild\n' >> .npmrc
npm ci --include=dev
NODE_OPTIONS=--no-experimental-webstorage npm test
npm run build

# 将路径替换为 terminal-patch 工作区的实际位置
git diff --cached --binary --full-index HEAD > /补丁工作区/patches/0001-swap-chat-workspace.patch
git rev-parse HEAD > /补丁工作区/patches/base-commit
```

当前只有一个补丁，上述命令将修复后的完整定制更新为该补丁。将来拆成多个补丁时，应逐一重新生成，避免把相同修改重复放入多个补丁。

然后在补丁工作区提交并推送：

```bash
cd /补丁工作区
node --test tests/*.test.mjs
git add patches
git commit -m "fix: adapt layout patch to upstream"
git push origin terminal-patch
sh scripts/install.sh
```

需要更新上游时先运行 `sync.sh`；安装脚本始终使用已有本地 `main`，应用补丁后执行测试和构建。`main` 更新采用 fast-forward，`terminal-patch` 的维护通常增加新提交，两者正常同步都不需要强制推送。

## 统一入口更新

```bash
bash scripts/install.sh update                  # 更新 Pi Agent，并同步、构建补丁版 pi-web
bash scripts/install.sh update --pi-only        # 只更新 Pi Agent
bash scripts/install.sh update --web-only       # 只同步、构建补丁版 pi-web
bash scripts/install.sh update --dry-run        # 预览操作
bash scripts/install.sh update --no-restart     # 不停止或重启服务
```

`install` 使用已有本地 `main`；`update` 默认先更新 Pi Agent，再调用 `sync.sh` 同步官方源码和 `origin/main`、应用补丁，随后安装依赖、测试、构建和替换全局命令。更新需要 origin 的推送权限。补丁冲突或测试构建失败时，不会替换已安装的 pi-web；之前已完成的 Agent 更新或源码同步不会回滚。

`update` 默认只重启原先正在运行的服务；`--restart` 会在更新后启动服务，`--no-restart` 保持服务原有状态。更新失败时可能保留已停止的服务，修复后可通过运行脚本启动。支持 `--update-relay` 和 `PI_VERSION`（Agent 目标版本，默认 `latest`）。pi-web 使用上游 `main`，不再使用 `PI_WEB_VERSION`。运行脚本的 `update` 命令也转入此统一入口。旧的 `update-pi-web-jmfederico.sh` 已移除；不带子命令仍默认执行 `install`。
