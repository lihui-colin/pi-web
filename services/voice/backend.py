"""Headless adapter for the pinned CapsWriter pipeline (see THIRD_PARTY.md)."""
import logging
import sys
import time


class Backend:
    def __init__(self, root, threads):
        sys.path.insert(0, str(root / 'upstream'))
        # Install a non-writing logger BEFORE importing server packages. Upstream
        # setup otherwise creates file logs and pipeline prints recognition text.
        import core
        import core.logger
        quiet = logging.getLogger('capswriter-headless')
        quiet.handlers = [logging.NullHandler()]
        quiet.propagate = False
        quiet.disabled = True
        core.logger.setup_logger = lambda *a, **kw: quiet
        core.logger.get_logger = lambda *a, **kw: quiet
        core.setup_logger = core.logger.setup_logger
        core.get_logger = core.logger.get_logger
        from config_server import ServerConfig
        ServerConfig.enable_tray = False
        ServerConfig.gpu_boost_enabled = False
        ServerConfig.model_type = 'paraformer'
        from core.server.state import console
        console.quiet = True
        from core.server.engines.paraformer_onnx.asr_engine import ParaformerEngine, ParaformerConfig
        from core.server.engines.ct_transformer.punc_engine import CTTransformerPuncEngine
        from core.server.worker.pipeline import TaskPipeline
        from core.server.schema import Task
        self.Task = Task
        self.pipeline = TaskPipeline(
            ParaformerEngine(ParaformerConfig(
                paraformer=str(root / 'models/asr/model.int8.onnx'),
                tokens=str(root / 'models/asr/tokens.txt'), num_threads=threads)),
            CTTransformerPuncEngine(str(root / 'models/punc/model.int8.onnx')))

    def process(self, data, offset, final, identity):
        result = self.pipeline.process(self.Task(
            type='mic', data=data, offset=offset, overlap=2,
            task_id=identity[0], socket_id=identity[0], is_final=final,
            time_start=identity[1], time_submit=time.time()))
        return {key: getattr(result, key) for key in (
            'task_id', 'is_final', 'text', 'duration', 'time_start',
            'time_submit', 'time_complete')}

    def clear(self):
        self.pipeline.state.sessions.clear()
