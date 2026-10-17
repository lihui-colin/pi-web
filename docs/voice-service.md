# 离线语音识别后台设计存档

状态：仅保留文档。独立语音服务、管理脚本、配置和依赖清单、探针及测试已从仓库移除；输入框保留禁用的麦克风按钮。下文记录原服务的设计、协议和验证方式，其中命令及 `services/voice/` 路径为历史示例，当前不可执行。后续开发见 [实施计划](语音识别.md)。

原方案为独立 Linux CPU 服务，复用固定版本 CapsWriter-Offline 的 Paraformer、分段拼接、数字格式化及 CT-Transformer 标点处理。输入框录音 UI、AudioWorklet、sessiond 的 `voice` 通道尚未接入。

## 安装与运行

在仓库根目录执行。需要 Linux x86_64、`git`、`curl`、`uv` 和 Python 3.12.3（uv 可在安装阶段准备该版本）。下载约 1.1 GB，建议预留至少 3 GB 磁盘空间。

```bash
bash scripts/voice-service.sh install
bash scripts/voice-service.sh start
bash scripts/voice-service.sh status
bash scripts/voice-service.sh logs
```

原安装流程在忽略的 `data/voice/` 内创建虚拟环境、固定 commit 的上游源码、模型、示例音频和配置；不运行上游整包安装，不需要桌面、DirectML、CUDA 或 Python 3.14。原依赖锁定清单及模型哈希清单已随实现移除；来源和许可说明保留在 [上游与模型来源](voice/THIRD_PARTY.md)。

`install` 不启动服务；已有配置保留，运行期间拒绝安装。下载时校验哈希，启动时重新检查固定源码和模型文件；模型缺失或损坏时明确退出，不在启动时联网下载。模型在进程启动时只加载一次，各工作区共用。

重启独立识别服务时先停后启：

```bash
bash scripts/voice-service.sh stop
bash scripts/voice-service.sh start
```

这不需要重启 pi-web。如以后修改 pi-web 并需要重启，仍使用项目规定的 `scripts/pi-web-run-jmfederico.sh stop`，再执行同一脚本的 `start`。

进程后台运行，PID 与 Linux 进程启动时间记录在 `data/voice/pid.json`，防止误停复用该 PID 的其他进程；管理操作使用文件锁串行化。停止先发 SIGTERM，等待最多 10 秒，原生推理仍未退出时才强制结束该独立进程。当前未注册开机自启，机器重启后需重新 `start`。

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

`ready` 仅表示两个模型均加载完成、服务正在监听；`last_success` 才表示本进程曾成功返回非空最终结果。`busy` 表示共享准入被占用，`last_error` 记录最近错误码和时间。记录仅保存在内存中，重启清空。真实健康验收必须运行下面的 WAV 转写探针，不能以握手或 `ready=true` 代替。

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

关闭连接即取消等待，不自动重放音频；原生推理不能被线程取消，所以旧计算实际完成前继续返回 `ASR_BUSY`，完成后清理状态。若原生引擎永久卡住，需要先停后启服务。后续前端的 `seq`、`recordingId`、ack 和草稿隔离属于 sessiond 适配协议，本服务不假装提供这些尚未实现的能力。

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

音频只存于内存，服务不写录音或识别全文。上游 logging 在加载前禁用，Rich 控制台设为 quiet，避免仅调整日志级别却遗漏流水线正文打印；独立服务日志仅记录启动、状态、错误码、任务 UUID、时长和耗时。`data/voice/service.log` 在启动时超过 10 MiB 会保留一个旧日志；长期运行可按运维需要配置外部日志轮换。
