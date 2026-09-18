# 安装与同步

## 分支约定

`main` 是纯上游分支，只进行 fast-forward 同步。`terminal-patch` 是独立根提交开始的补丁分支，只保存定制维护所需的文件。不要将这两个分支相互 merge 或 rebase；通过应用 `.patch` 文件组合代码。

`patches/0001-swap-chat-workspace.patch` 包含面板交换功能及其测试。`patches/base-commit` 记录补丁制作时的上游基线，仅供更新补丁时参考，不固定安装版本。

## 安装或更新运行版本

在 `terminal-patch` 工作区执行：

```bash
sh install.sh
# 将参数传给最终的服务安装命令
sh install.sh --port 8504
```

执行顺序：

1. 全局更新 `@earendil-works/pi-coding-agent@latest`。
2. 从官方上游拉取最新 `main`，fast-forward 本地 `main`，再推送到 `origin/main`。
3. 从纯上游 `main` 克隆独立安装目录，按文件名顺序应用当前工作区 `patches/*.patch`，使用 Git 三方合并。
4. 在生成目录的 `.npmrc` 中配置 node-pty/esbuild 的安装脚本权限，安装依赖，运行测试并构建。
5. 调用构建产物的 `node dist/cli.js install` 安装用户服务。

首次安装还需自行完成 Pi 的模型提供商认证。服务默认监听 `127.0.0.1:8504`。远程访问可在本机运行 `ssh -L 8504:127.0.0.1:8504 用户@服务器`，再打开本机的 http://127.0.0.1:8504。

服务安装可能重启 session daemon，更新前先结束需要保留的运行中任务。脚本测试与构建失败时不会执行服务安装，但 Pi Agent 和 `main` 可能已经更新；脚本不自动回滚这两步。

每次创建的安装目录位于 `~/.local/share/pi-web-opt/release.*`。正在使用的目录不能删除，服务直接运行其中的构建产物；旧目录不会自动清理。

可设置 `PI_WEB_INSTALL_ROOT` 改变安装目录，或设置 `PI_WEB_UPSTREAM_URL` 改变上游仓库地址。`origin` 使用当前仓库配置。脚本不会自动提交或推送 `terminal-patch` 的修改；安装前应审查补丁工作区并提交要共享的修改。

## 只同步代码并准备补丁版本

```bash
# 在 terminal-patch 分支中
release_dir=$(sh sync.sh)
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

如果 `main` 在另一个 worktree 中检出，Git 会拒绝通过 fetch 更新它。先在那个干净的 worktree 中切换到 detached HEAD，或在那里显式执行 `git fetch upstream` 和 `git merge --ff-only upstream/main`，再重新同步。不要丢弃未提交的工作。

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
sh install.sh
```

安装脚本每次都会重新获取最新上游，并执行测试和构建。`main` 更新采用 fast-forward，`terminal-patch` 的维护通常增加新提交，两者正常同步都不需要强制推送。
