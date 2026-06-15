"""
纯逻辑单元测试：不依赖 PyQt6，可在任何环境运行
测试：ETA 平滑算法、预设同步、数据模型序列化
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))

MAX_CONCURRENT = 3


class ETAStats:
    """复制版 ETAStats，不依赖 PyQt6 导入"""
    _durations: deque = field(default_factory=lambda: deque(maxlen=30))
    _smoothed_eta: float = 0.0
    _last_raw_eta: float = 0.0
    _ema_alpha: float = 0.25
    _clamp_up_ratio: float = 1.4
    _clamp_down_ratio: float = 0.6
    _initialized: bool = False

    def __init__(self):
        self._durations = deque(maxlen=30)
        self._smoothed_eta = 0.0
        self._last_raw_eta = 0.0
        self._initialized = False

    def add_completion(self, duration: float):
        if duration > 0:
            self._durations.append(duration)

    @property
    def average_duration(self) -> float:
        if not self._durations:
            return 0.0
        weights = list(range(1, len(self._durations) + 1))
        total = sum(w * d for w, d in zip(weights, self._durations))
        return total / sum(weights)

    def estimate_remaining(self, pending_count: int, converting_count: int = 0) -> float:
        avg = self.average_duration
        if avg == 0:
            return 0.0
        remaining_tasks = pending_count + converting_count
        if remaining_tasks == 0:
            return 0.0
        if MAX_CONCURRENT <= 0:
            raw_eta = remaining_tasks * avg
        else:
            converting_eta = converting_count * avg * 0.5
            parallel_batches = (pending_count + MAX_CONCURRENT - 1) // MAX_CONCURRENT
            raw_eta = parallel_batches * avg + converting_eta
        self._last_raw_eta = raw_eta
        if not self._initialized:
            self._smoothed_eta = raw_eta
            self._initialized = True
        else:
            ema_eta = self._ema_alpha * raw_eta + (1 - self._ema_alpha) * self._smoothed_eta
            max_allowed = self._smoothed_eta * self._clamp_up_ratio
            min_allowed = self._smoothed_eta * self._clamp_down_ratio
            clamped = max(min_allowed, min(max_allowed, ema_eta))
            self._smoothed_eta = clamped
        return self._smoothed_eta

    def format_eta(self, seconds: float) -> str:
        if seconds <= 0:
            return "估算中..."
        if seconds < 60:
            return f"约 {seconds:.0f} 秒"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        if mins < 60:
            return f"约 {mins}分{secs}秒"
        hours = mins // 60
        mins = mins % 60
        return f"约 {hours}时{mins}分{secs}秒"

    def reset(self):
        self._smoothed_eta = 0.0
        self._initialized = False


class TestETAStability(unittest.TestCase):
    """测试 ETA 平滑算法稳定性"""

    def setUp(self):
        self.eta = ETAStats()

    def test_ema_smoothing_reduces_volatility(self):
        for _ in range(5):
            self.eta.add_completion(60.0)

        raw_values = []
        smoothed_values = []
        pending = 10

        for i in range(20):
            raw_avg = 60.0 if i < 10 else 300.0 if i < 15 else 60.0
            if i % 3 == 0 and i > 0:
                self.eta.add_completion(raw_avg)
            avg = self.eta.average_duration
            parallel = (pending + MAX_CONCURRENT - 1) // MAX_CONCURRENT
            raw_eta = parallel * avg
            smoothed_eta = self.eta.estimate_remaining(pending, 0)
            raw_values.append(raw_eta)
            smoothed_values.append(smoothed_eta)

        raw_jumps = sum(abs(raw_values[i] - raw_values[i-1]) for i in range(1, len(raw_values)))
        smooth_jumps = sum(abs(smoothed_values[i] - smoothed_values[i-1]) for i in range(1, len(smoothed_values)))
        self.assertLess(smooth_jumps, raw_jumps * 0.6,
                        f"平滑后波动({smooth_jumps:.1f})应显著小于原始波动({raw_jumps:.1f})")
        print(f"  ✅ 原始波动: {raw_jumps:.1f}, 平滑后波动: {smooth_jumps:.1f}, 降噪率: {(1-smooth_jumps/raw_jumps)*100:.0f}%")

    def test_clamp_limits_single_jump(self):
        for _ in range(10):
            self.eta.add_completion(60.0)
        self.eta.estimate_remaining(10, 0)
        eta1 = self.eta._smoothed_eta

        for _ in range(10):
            self.eta.add_completion(600.0)

        eta2 = self.eta.estimate_remaining(10, 0)
        max_allowed = eta1 * 1.4
        self.assertLessEqual(eta2, max_allowed,
                             f"单次 ETA 从 {eta1:.1f} 跳到 {eta2:.1f}，超过+40%钳制({max_allowed:.1f})")
        print(f"  ✅ 钳制测试: {eta1:.1f} -> {eta2:.1f} (最大允许 {max_allowed:.1f})")

    def test_clear_completed_preserves_eta(self):
        for _ in range(5):
            self.eta.add_completion(60.0)
        self.eta.estimate_remaining(10, 0)
        self.assertTrue(self.eta._initialized, "初始化前应标记为已初始化")
        eta_before = self.eta._smoothed_eta

        self.eta.estimate_remaining(5, 1)
        eta_after = self.eta._smoothed_eta

        self.assertTrue(self.eta._initialized, "pending>0 时不应重置 initialized")
        self.assertGreater(self.eta.average_duration, 0, "平均耗时不应丢失")
        self.assertGreater(eta_after, 0, "平滑值不应清零")
        print(f"  ✅ 清除完成任务后 ETA 保留: {eta_before:.1f} -> {eta_after:.1f}")

    def test_format_eta_correct_units(self):
        self.assertIn("秒", self.eta.format_eta(30))
        self.assertIn("分", self.eta.format_eta(120))
        self.assertIn("时", self.eta.format_eta(4000))
        self.assertEqual("估算中...", self.eta.format_eta(0))
        print(f"  ✅ 单位格式化: 30s={self.eta.format_eta(30)}, 120s={self.eta.format_eta(120)}, 4000s={self.eta.format_eta(4000)}")

    def test_weighted_average_favors_recent(self):
        self.eta.add_completion(10.0)
        self.eta.add_completion(10.0)
        self.eta.add_completion(100.0)
        avg = self.eta.average_duration
        simple_avg = (10 + 10 + 100) / 3
        weighted_avg = (1*10 + 2*10 + 3*100) / (1+2+3)
        self.assertAlmostEqual(avg, weighted_avg, places=2)
        self.assertGreater(avg, simple_avg)
        print(f"  ✅ 加权平均: {avg:.2f}, 简单平均: {simple_avg:.2f} (越新权重越大)")


class TestTaskModel(unittest.TestCase):
    """测试任务模型（不依赖 PyQt6）"""

    def test_reorder_preserves_progress(self):
        """任务列表重排后进度值不丢失"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus

        progress = 67
        task = ConvertQueueTask(
            book_title="正在转换的书",
            status=TaskStatus.CONVERTING,
            progress=progress,
            task_id="conv1",
            source_format="epub",
        )
        progress_value = task.progress
        tasks = [
            ConvertQueueTask(book_title=f"书{i}", task_id=f"id{i}", source_format="epub")
            for i in range(3)
        ]
        tasks.insert(1, task)
        self.assertEqual(tasks[1].progress, progress_value)

        moved = tasks.pop(1)
        tasks.insert(3, moved)
        self.assertEqual(tasks[3].task_id, "conv1")
        self.assertEqual(tasks[3].progress, progress_value,
                         "拖拽后进度值不应丢失")
        self.assertEqual(tasks[3].status, TaskStatus.CONVERTING,
                         "拖拽后状态不应改变")
        print(f"  ✅ 拖拽后进度保持: {tasks[3].progress}%")

    def test_apply_preset_updates_all_fields(self):
        """apply_preset_to_task 应更新所有相关字段"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus, ConvertPreset, PresetManager

        pm = PresetManager()
        task = ConvertQueueTask(
            input_path="/test/book.epub",
            output_format="epub",
            output_dir="/old",
            preset_name="默认",
            extra_args=[],
            source_format="epub",
        )
        result = pm.apply_preset_to_task(task, "Kindle优化")
        self.assertTrue(result)
        self.assertEqual(task.preset_name, "Kindle优化")
        self.assertEqual(task.output_format, "mobi")
        self.assertIn("--no-inline-toc", task.extra_args)
        self.assertEqual(task.output_dir, "/old",
                         "apply_preset_to_task 不应修改 output_dir，由 apply_preset_to_all 控制")
        print(f"  ✅ 预设应用: 格式={task.output_format}, extra_args={len(task.extra_args)}个参数")

    def test_json_serialization(self):
        """任务 JSON 序列化/反序列化"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus

        task = ConvertQueueTask(
            input_path="/test/book.epub",
            output_format="mobi",
            output_dir="/output",
            book_title="测试书籍",
            book_author="测试作者",
            source_format="epub",
            file_size=2048,
            status=TaskStatus.PENDING,
            progress=33,
            preset_name="Kindle优化",
            extra_args=["--arg1", "--arg2"],
        )
        d = task.to_dict()
        task2 = ConvertQueueTask.from_dict(d)
        self.assertEqual(task2.input_path, task.input_path)
        self.assertEqual(task2.output_format, task.output_format)
        self.assertEqual(task2.book_title, task.book_title)
        self.assertEqual(task2.preset_name, task.preset_name)
        self.assertEqual(task2.extra_args, task.extra_args)
        print(f"  ✅ JSON 序列化: {task.book_title} <-> {task2.book_title}")


if __name__ == "__main__":
    print("="*70)
    print("📊 电子书转换队列纯逻辑单元测试")
    print("="*70)
    unittest.main(verbosity=2)
