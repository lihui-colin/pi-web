# 上游与模型来源

独立离线语音服务的来源记录。精确源码 commit、模型下载 URL、文件大小和 SHA-256 见 `services/voice/assets.json`；Python 依赖版本及包哈希见 `services/voice/requirements.lock`。

- CapsWriter-Offline 固定源码：`84912d5218ee5e51e216c54dc15a1cb0f466eb76`。
  https://github.com/HaujetZhao/CapsWriter-Offline/tree/84912d5218ee5e51e216c54dc15a1cb0f466eb76
  MIT，Copyright (c) 2026 Haujet Zhao。完整许可保留在 [CapsWriter-LICENSE](CapsWriter-LICENSE)。
  服务入口复用其 Paraformer 引擎、TaskPipeline、文本拼接和格式化，不修改下载的源码。
- Paraformer 中文模型：sherpa-onnx 的 `sherpa-onnx-paraformer-zh-2023-03-28` 发布包，使用 INT8 模型。
  https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-03-28
  发布者模型卡标注 MIT；其转换与原模型来源见模型卡链接。
- CT-Transformer 标点模型：sherpa-onnx 的 `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8` 发布包。
  https://huggingface.co/csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12
  转换来源为 https://modelscope.cn/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch/summary 。
  转换仓库的 README 未单列模型许可证；再分发模型时应核对原模型附带条款，不能把代码 MIT 许可自动套用到模型。
- 安装器将模型和示例音频下载到本地 `data/voice/`，不随此仓库分发。下载和启动均校验模型文件。
- Python 依赖的许可证随 wheel 安装在虚拟环境的 `.dist-info` 中。
  sherpa-onnx/sherpa-onnx-core（Apache-2.0）、NumPy（BSD-3-Clause）、websockets（BSD-3-Clause）、
  rich/colorama/markdown-it-py/mdurl（MIT）、Pygments（BSD-2-Clause）；依赖中的第三方组件沿用各包附带的声明。
