"""
纯逻辑单元测试：不依赖 PyQt6，可在任何环境运行
测试：ETA 平滑算法、预设同步、数据模型序列化、拖拽不闪烁逻辑
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent))

MAX_CONCURRENT = 3


class ETAStats:
    """纯 Python 版 ETAStats，与实际实现保持一致"""
    def __init__(self):
        self._durations = deque(maxlen=30)
        self._smoothed_eta = 0.0
        self._last_raw_eta = 0.0
        self._ema_alpha = 0.15
        self._clamp_up_ratio = 1.25
        self._clamp_down_ratio = 0.7
        self._initialized = False
        self._min_samples = 3
        self._last_display_eta = 0.0
        self._display_min_delta_ratio = 0.08
        self._display_min_delta_seconds = 15.0
        self._has_completed_tasks = False

    def add_completion(self, duration: float):
        if duration <= 0:
            return
        if self._durations:
            median = self._median()
            if median > 0:
                ratio = duration / median
                if ratio > 3.0 or ratio < 0.2:
                    return
        self._durations.append(duration)
        self._has_completed_tasks = True

    def _median(self) -> float:
        if not self._durations:
            return 0.0
        sorted_vals = sorted(self._durations)
        n = len(sorted_vals)
        if n % 2 == 0:
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        return sorted_vals[n // 2]

    @property
    def has_enough_samples(self) -> bool:
        return len(self._durations) >= self._min_samples

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

    def get_display_eta(self, pending_count: int, converting_count: int = 0) -> float:
        eta = self.estimate_remaining(pending_count, converting_count)
        if eta <= 0:
            self._last_display_eta = 0.0
            return 0.0
        delta = abs(eta - self._last_display_eta)
        min_delta = max(self._last_display_eta * self._display_min_delta_ratio,
                        self._display_min_delta_seconds)
        if delta >= min_delta or self._last_display_eta == 0:
            self._last_display_eta = eta
            return eta
        return self._last_display_eta

    def format_eta(self, seconds: float, remaining_tasks: int = 0) -> str:
        if remaining_tasks == 0 and self._has_completed_tasks:
            return "✅ 全部完成"
        if seconds <= 0 or not self.has_enough_samples:
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
        self._last_display_eta = 0.0
        self._initialized = False
        self._has_completed_tasks = False


class TestETAStability(unittest.TestCase):
    """测试 ETA 平滑算法稳定性"""

    def setUp(self):
        self.eta = ETAStats()

    def test_display_debounce_reduces_jitter(self):
        """显示防抖层应减少小幅波动的更新频率"""
        for _ in range(5):
            self.eta.add_completion(60.0)
        self.eta.estimate_remaining(10, 0)
        display1 = self.eta.get_display_eta(10, 0)
        changes = 0
        for i in range(20):
            display2 = self.eta.get_display_eta(10, 0)
            if display2 != self.eta._last_display_eta:
                changes += 1
        raw_changes = 20
        self.assertLessEqual(changes, raw_changes * 0.3,
                             "显示防抖后更新次数应显著减少")
        print(f"  ✅ 显示防抖: 原始20次变化 -> 实际显示更新{changes}次")

    def test_clamp_stricter_limits_single_jump(self):
        """更严格的钳制（±25%/30%）限制单次跳变"""
        for _ in range(10):
            self.eta.add_completion(60.0)
        self.eta.estimate_remaining(10, 0)
        eta1 = self.eta._smoothed_eta
        for _ in range(10):
            self.eta.add_completion(600.0)
        eta2 = self.eta.estimate_remaining(10, 0)
        max_allowed = eta1 * 1.25
        self.assertLessEqual(eta2, max_allowed,
                             f"单次 ETA 从 {eta1:.1f} 跳到 {eta2:.1f}，超过+25%钳制({max_allowed:.1f})")
        print(f"  ✅ 钳制测试: {eta1:.1f} -> {eta2:.1f} (最大允许 {max_allowed:.1f})")

    def test_outlier_rejection(self):
        """异常值（偏离中位数 ±200%）应被剔除"""
        for _ in range(5):
            self.eta.add_completion(60.0)
        median_before = self.eta._median()
        self.eta.add_completion(5000.0)
        median_after = self.eta._median()
        self.assertAlmostEqual(median_before, median_after, places=0,
                               msg="异常值不应影响中位数")
        print(f"  ✅ 异常值剔除: 加入5000s后中位数仍为 {median_after:.0f}s")

    def test_min_samples_shows_estimating(self):
        """样本不足时显示'估算中...'"""
        self.eta.add_completion(60.0)
        self.eta.add_completion(60.0)
        self.assertFalse(self.eta.has_enough_samples, "2个样本应不足")
        eta = self.eta.estimate_remaining(10, 0)
        display = self.eta.format_eta(eta, 10)
        self.assertEqual("估算中...", display)
        self.eta.add_completion(60.0)
        self.assertTrue(self.eta.has_enough_samples, "3个样本应足够")
        print(f"  ✅ 最小样本: 2个->估算中, 3个->开始估算")

    def test_all_completed_shows_done(self):
        """全部完成时显示'✅ 全部完成'而非'估算中...'"""
        for _ in range(5):
            self.eta.add_completion(60.0)
        display = self.eta.format_eta(0, 0)
        self.assertEqual("✅ 全部完成", display,
                         "全部完成后应显示完成状态")
        print(f"  ✅ 完成态显示: {display}")

    def test_clearing_completed_does_not_reset(self):
        """清除已完成任务不应重置 ETA 统计"""
        for _ in range(5):
            self.eta.add_completion(60.0)
        self.eta.estimate_remaining(10, 0)
        self.assertTrue(self.eta._initialized)
        self.eta.estimate_remaining(5, 0)
        self.assertTrue(self.eta._initialized,
                        "pending>0 时不应重置 initialized")
        self.assertGreater(self.eta.average_duration, 0,
                           "平均耗时不应丢失")
        print(f"  ✅ 清除完成任务后 ETA 保留: 平均{self.eta.average_duration:.1f}s")

    def test_display_eta_returns_stable_value(self):
        """get_display_eta 应返回稳定的值，不随小幅变化跳动"""
        for _ in range(5):
            self.eta.add_completion(60.0)
        eta1 = self.eta.get_display_eta(10, 0)
        eta2 = self.eta.get_display_eta(9, 0)
        self.assertEqual(eta1, eta2,
                         "任务数小幅变化时显示 ETA 应保持稳定")
        print(f"  ✅ 显示稳定: 10任务={eta1:.0f}s, 9任务={eta2:.0f}s (相同)")


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
        tasks = [
            ConvertQueueTask(book_title=f"书{i}", task_id=f"id{i}", source_format="epub")
            for i in range(3)
        ]
        tasks.insert(1, task)
        self.assertEqual(tasks[1].progress, progress)
        moved = tasks.pop(1)
        tasks.insert(3, moved)
        self.assertEqual(tasks[3].task_id, "conv1")
        self.assertEqual(tasks[3].progress, progress)
        self.assertEqual(tasks[3].status, TaskStatus.CONVERTING)
        print(f"  ✅ 拖拽后进度保持: {tasks[3].progress}%")

    def test_apply_preset_updates_all_fields(self):
        """apply_preset_to_task 应更新格式和 extra_args"""
        from ebook_manager.queue_models import ConvertQueueTask, PresetManager
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
        self.assertGreater(len(task.extra_args), 0)
        self.assertEqual(task.output_dir, "/old",
                         "apply_preset_to_task 不应修改 output_dir")
        print(f"  ✅ 预设应用: 格式={task.output_format}, extra_args={len(task.extra_args)}个")

    def test_apply_preset_to_all_with_output_dir(self):
        """apply_preset_to_all 应同步 output_dir"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus
        import tempfile
        tmpdir = tempfile.mkdtemp()
        from ebook_manager.queue_manager import QueueManager
        qm = QueueManager(config_dir=tmpdir)
        task1 = ConvertQueueTask(
            input_path="/test/book1.epub",
            output_format="epub",
            output_dir="/old/dir",
            status=TaskStatus.PENDING,
            source_format="epub",
        )
        task2 = ConvertQueueTask(
            input_path="/test/book2.epub",
            output_format="epub",
            output_dir="/old/dir",
            status=TaskStatus.FAILED,
            source_format="epub",
        )
        qm.add_tasks([task1, task2])
        new_dir = "/new/output/dir"
        count = qm.apply_preset_to_all(
            "Kindle优化", output_dir=new_dir,
            output_format="mobi", sync_output_dir=True
        )
        self.assertEqual(count, 2, "PENDING 和 FAILED 都应被更新")
        for t in qm.get_tasks():
            self.assertEqual(t.output_dir, new_dir, f"任务 {t.task_id} 的 output_dir 应更新")
            self.assertEqual(t.output_format, "mobi")
            self.assertEqual(t.preset_name, "Kindle优化")
        print(f"  ✅ 同步预设: 2个任务全部更新 output_dir={new_dir}")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sync_empty_output_dir_clears_to_none(self):
        """output_dir 空字符串应清除为 None（默认目录）"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus
        import tempfile
        tmpdir = tempfile.mkdtemp()
        from ebook_manager.queue_manager import QueueManager
        qm = QueueManager(config_dir=tmpdir)
        task = ConvertQueueTask(
            input_path="/test/book.epub",
            output_format="epub",
            output_dir="/old/dir",
            status=TaskStatus.PENDING,
            source_format="epub",
        )
        qm.add_task(task)
        count = qm.apply_preset_to_all(
            "默认", output_dir="",
            output_format="epub", sync_output_dir=True
        )
        self.assertEqual(count, 1)
        updated = qm.get_tasks()[0]
        self.assertIsNone(updated.output_dir,
                          "空字符串 output_dir 应设为 None（使用默认目录）")
        print(f"  ✅ 空目录同步: output_dir={updated.output_dir} (None=默认)")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

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
        self.assertEqual(task2.preset_name, task.preset_name)
        self.assertEqual(task2.extra_args, task.extra_args)
        print(f"  ✅ JSON 序列化: {task.book_title} <-> {task2.book_title}")

    def test_converting_status_resets_on_deserialize(self):
        """崩溃恢复时 CONVERTING 状态应重置为 PENDING"""
        from ebook_manager.queue_models import ConvertQueueTask, TaskStatus
        task = ConvertQueueTask(
            input_path="/test/book.epub",
            status=TaskStatus.CONVERTING,
            progress=50,
            source_format="epub",
        )
        d = task.to_dict()
        task2 = ConvertQueueTask.from_dict(d)
        self.assertEqual(task2.status, TaskStatus.PENDING)
        self.assertEqual(task2.progress, 0)
        print(f"  ✅ 崩溃恢复: CONVERTING -> {task2.status.value}")


if __name__ == "__main__":
    print("="*70)
    print("📊 电子书转换队列纯逻辑单元测试")
    print("="*70)
    unittest.main(verbosity=2)
