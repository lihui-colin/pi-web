# 离线语音识别服务

状态：独立 Linux CPU 服务已实现。复用固定版本 CapsWriter-Offline 的 Paraformer、分段拼接、数字格式化及 CT-Transformer 标点处理。Codex 已接入 AudioWorklet 录音和 sessiond `voice` 通道，提供取消与转写回填，识别结果仅追加到编辑框，由用户确认后手动发送；入口默认关闭。

实现位于 `services/voice/`，管理入口为 `scripts/voice-service.sh`。这是独立服务，pi-web 的 `start` 和更新脚本不会自动启动它。主管理脚本的 `stop` 会先停止本仓库默认 `data/voice/` 下的语音服务，再停止 pi-web；`restart` 也沿用此停止步骤，但不会自动重新启动语音服务。使用 `--root` 部署在其他目录的实例仍需单独停止。

## 安装与运行

在仓库根目录执行。需要 Linux x86_64、`git`、`curl`、`uv` 和 Python 3.12.3（uv 可在安装阶段准备该版本）。下载约 1.1 GB，建议预留至少 3 GB 磁盘空间。

推荐使用独立安装验收脚本：

```bash
bash scripts/install-voice.sh
```

脚本依次安装依赖和模型、启动独立服务、转写固定的真实中文 WAV，并检查结果包含预期文字以及健康接口记录了本进程的新成功结果。只有全部通过，才输出 `PI_WEB_VOICE_INPUT_ENABLED=true` 的启用提示，服务保持运行。任一步失败均以非零状态退出，不提示启用；如果本次新启动的服务验收失败，会停止该进程。已有运行服务只校验和测试，不重装、不重启，测试失败也不停止已有服务。

使用包含语音接入功能的新 pi-web release，通过 HTTPS 或 localhost 打开输入框。脚本不会修改 `data/pi-web.conf`，也不会重启 pi-web。`--root /absolute/path` 可指定后端部署目录；入口开关仍属于本仓库的 pi-web 配置。

分步管理命令如下；单独执行 `install` 或 `start` 不会提示开启入口：

```bash
bash scripts/voice-service.sh install
bash scripts/voice-service.sh start
bash scripts/voice-service.sh verify
bash scripts/voice-service.sh status
bash scripts/voice-service.sh logs
```

安装流程在忽略的 `data/voice/` 内创建虚拟环境、固定 commit 的上游源码、模型、示例音频和配置；不运行上游整包安装，不需要桌面、DirectML、CUDA 或 Python 3.14。Python 依赖固定在 `services/voice/requirements.lock`，源码和模型固定在 `services/voice/assets.json`；来源和许可说明见 [上游与模型来源](voice/THIRD_PARTY.md)。

`install` 不启动服务；已有配置保留，运行期间拒绝安装。下载时校验哈希，启动时重新检查固定源码和模型文件；模型缺失或损坏时明确退出，不在启动时联网下载。模型在进程启动时只加载一次，各工作区共用。

重启独立识别服务时先停后启：

```bash
bash scripts/voice-service.sh stop
bash scripts/voice-service.sh start
```

这不需要重启 pi-web。如以后修改 pi-web 并需要重启，仍使用项目规定的 `scripts/pi-web-run-jmfederico.sh stop`，再执行同一脚本的 `start`。

进程后台运行，PID 与 Linux 进程启动时间记录在 `data/voice/pid.json`，并使用 pidfd 发送信号，防止误停复用该 PID 的其他进程；管理操作使用文件锁串行化。停止先发 SIGTERM，等待最多 10 秒，原生推理仍未退出时才强制结束该独立进程。管理脚本还支持 `--root /absolute/path` 指定独立部署目录，配置和 PID 均从该目录读取。当前未注册开机自启，机器重启后需重新 `start`。

## 配置和健康检查

唯一运行配置为 `data/voice/config.json`，模板是 `services/voice/config.example.json`：

```json
{
  "host": "127.0.0.1",
  "port": 6016,
  "threads": 4,
  "max_seconds": 120,
  "final_timeout_seconds": 30
}
```

只允许回环监听；跨机器接入使用受控隧道。该端口不提供用户鉴权，不应直接暴露给浏览器或公网。WebSocket 拒绝带浏览器 Origin 的连接。未来 sessiond 负责校验用户与工作区权限。

```bash
curl --noproxy '*' http://127.0.0.1:6016/healthz
bash scripts/voice-service.sh verify
```

`ready` 仅表示两个模型均加载完成、服务正在监听；`last_success` 才表示本进程曾成功返回非空最终结果。`busy` 表示共享准入被占用，`last_error` 记录最近错误码和时间。`pid` 用于管理脚本核对健康接口确属本进程。记录仅保存在内存中，重启清空。真实健康验收必须运行下面的 WAV 转写探针，不能以握手或 `ready=true` 代替。

管理脚本的本地健康请求与探针 WebSocket 显式绕过代理环境变量，避免把本地音频流发送到 HTTP 代理。

## 识别协议

连接 `ws://127.0.0.1:6016/`，WebSocket 子协议为 `binary`，消息实际为 **JSON 文本**。兼容文档中的 CapsWriter 麦克风协议；每个连接只接受一个任务，以规范的小写 UUID 作为 `task_id`，同一任务的 `time_start` 固定为 Unix 秒。

```json
{
  "task_id": "2d3b557a-7d8c-4df4-bd12-7187dc22bfbb",
  "source": "mic",
  "data": "<Base64 Float32 PCM>",
  "is_final": false,
  "time_start": 1792215200.0,
  "seg_duration": 15.0,
  "seg_overlap": 2.0,
  "context": "",
  "language": "auto"
}
```

音频格式为 16 kHz、单声道、小端 Float32，采样值有限且在 `[-1, 1]`。每帧最多 1600 个样本（100 ms / 6400 字节），JSON 消息最多 16 KiB；静音也要持续发帧。固定分段参数为 15 秒、重叠 2 秒，累计约 19 秒时返回第一个中间结果。客户端应按采集节奏发送，不要突发上传整个音频文件。

停止时发送字段相同的 `is_final=true` 消息，`data` 可为空；连接继续保持，收到最终结果后服务端正常关闭。`text` 为累计全文，每次替换预览，不能将每个结果逐条追加。该入口只接受 `source=mic`、空 `context`、`language=auto`，不提供文件转录、字幕或热词管理。

额外错误扩展为 `{"error":"错误码"}` 后关闭连接：`ASR_BUSY`、`ASR_TIMEOUT`、`AUDIO_INVALID`、`AUDIO_TOO_LONG`、`QUEUE_OVERFLOW`、`NO_SPEECH`、`ASR_FAILED`。这不是原版 CapsWriter 的结构化错误协议；后续 pi-web 适配器需处理它以及无结果断连。WebSocket 层超大消息可能直接以 1009 关闭。

全服务只允许一个活动连接；多个 sessiond 指向同一个服务时也共用此限额。处理队列最多 19 帧、WebSocket 接收高水位 1 帧；另有分段缓冲与推理中的音频。超过上限结束任务，不静默丢音频。音频累计超过配置时长拒绝，客户端应在上限处主动发送结束帧；连续 5 秒无帧或超过录音墙钟期限会中断，发送结束帧后默认最多等待 30 秒。

关闭连接即取消等待，不自动重放音频；原生推理不能被线程取消，所以旧计算实际完成前继续返回 `ASR_BUSY`，完成后清理状态。若原生引擎永久卡住，需要先停后启服务。前端的 `seq`、`recordingId`、ack 和草稿隔离由 sessiond 适配器与浏览器负责，本服务保持 CapsWriter 麦克风协议。

## 验证

```bash
# 无需模型即可运行协议、并发、背压、超时与进程管理测试
data/voice/venv/bin/python -m unittest discover -s services/voice -p 'test_*.py' -v

# 真实语音，默认仅输出时长、耗时和字数，不输出正文
data/voice/venv/bin/python services/voice/smoke.py data/voice/models/test/0.wav

# 人工核对时可明确要求输出文本；--expect 检查识别结果包含指定文字
data/voice/venv/bin/python services/voice/smoke.py data/voice/models/test/0.wav --show-text

# 补丁仓库原有测试
node --test tests/*.test.mjs
```

探针只接受 16 kHz、单声道、PCM16 WAV，在内存中转换为 Float32 并按 100 ms 节奏发送，最终结果要求非空。它是部署验证工具，不是生产录音归档功能。

音频只存于内存，服务不写录音或识别全文。上游日志工厂在导入服务包前替换为不写入的 logger，Rich 控制台设为 quiet，避免仅调整日志级别却遗漏流水线正文打印；独立服务日志仅记录启动事件和启动失败类型；任务状态、最近错误码与成功时间通过健康接口读取。`data/voice/service.log` 在启动时超过 10 MiB 会保留一个旧日志；长期运行可按运维需要配置外部日志轮换。


## 2026-10-19 验证记录

- 平台：Linux 6.8 x86_64，Intel Xeon Platinum 8368；Python 3.12.3，CPU 推理 4 线程。固定 CapsWriter commit 为 `84912d5218ee5e51e216c54dc15a1cb0f466eb76`，Paraformer 与标点模型均为 INT8。
- 新部署目录使用固定源码和已校验的下载缓存，创建新虚拟环境、解包模型、加载模型、完成真实转写后停止成功；启动到健康接口就绪约 2.41 秒（包含启动校验，未清空操作系统缓存）。
- 中文样本 `0.wav`：5.615 秒音频，停止上传至最终结果约 0.18 秒；新部署首次识别约 0.30 秒。中英混合样本 `6-zh-en.wav` 返回中文及英文词句。
- 将上游 `0.wav`、`1.wav`、`2.wav`、`6-zh-en.wav` 拼接为 23.398 秒的测试音频，得到 1 个中间结果和最终结果；停止上传至最终结果约 0.247 秒。测试拼接文件已删除。
- 上述中文和长音频测试后，服务进程峰值 RSS 约 507 MiB。这里只记录少量样本，未完成 30 条语料 CER/WER、p50/p95 或跨机器性能评估。
- 自动化测试：24 项通过，覆盖协议与音频校验、全局准入、断连和超时后保留推理配额、队列溢出、重叠切段、空结果、超大消息、无帧超时、安装哈希、配置保留、PID 校验及启动/停止、安装验收提示顺序及失败清理；仓库原有 83 项测试通过。
- 服务日志仅出现启动事件，新部署的上游目录未生成日志文件；默认探针不输出识别正文。人工核对正文需显式传入 `--show-text`。

上述为独立服务验证记录。后续同日已实现浏览器与 sessiond 接入，需安装包含更新 `0006` 补丁的 pi-web release；本次开发未重启线上 pi-web。主管理脚本 stop/restart 后需再次运行 `scripts/install-voice.sh` 启动并验收后端。详见 [语音输入](codex-usage.md#语音输入)。
