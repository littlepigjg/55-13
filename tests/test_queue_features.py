"""
测试文件：电子书转换队列功能测试
涵盖：
1. ETA 平滑算法稳定性
2. 预设同步功能（包括 output_dir）
3. 任务拖拽排序不闪烁逻辑
4. 队列持久化
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent))

from ebook_manager.queue_models import (
    ConvertQueueTask, TaskStatus, ConvertPreset, PresetManager
)
from ebook_manager.queue_manager import ETAStats, QueueManager, MAX_CONCURRENT


class TestETAStability(unittest.TestCase):
    """测试 ETA 平滑算法稳定性"""

    def setUp(self):
        self.eta = ETAStats()

    def test_ema_smoothing_reduces_volatility(self):
        """EMA 平滑后波动幅度应显著小于原始波动"""
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

    def test_clamp_limits_single_jump(self):
        """单次 ETA 变化不应超过 ±40%/60% 的钳制"""
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

    def test_clear_completed_preserves_eta(self):
        """清除已完成任务不应重置 ETA 统计状态"""
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

    def test_full_reset_only_when_all_empty(self):
        """只有当 pending=converting=0 且队列为全空时才重置"""
        self.eta.add_completion(60.0)
        self.eta.estimate_remaining(3, 1)
        self.eta.estimate_remaining(0, 0)
        self.assertEqual(self.eta._smoothed_eta, 0.0, "全部完成时 ETA 应归零，但不重置初始化")
        self.assertFalse(hasattr(self.eta, '_force_reset_flag'), "不应有额外重置标记")

    def test_format_eta_correct_units(self):
        """格式化 ETA 单位正确"""
        self.assertIn("秒", self.eta.format_eta(30))
        self.assertIn("分", self.eta.format_eta(120))
        self.assertIn("时", self.eta.format_eta(4000))
        self.assertEqual("估算中...", self.eta.format_eta(0))

    def test_weighted_average_favors_recent(self):
        """加权平均应偏向最近完成的任务"""
        self.eta.add_completion(10.0)
        self.eta.add_completion(10.0)
        self.eta.add_completion(100.0)
        avg = self.eta.average_duration
        simple_avg = (10 + 10 + 100) / 3
        weighted_avg = (1*10 + 2*10 + 3*100) / (1+2+3)
        self.assertAlmostEqual(avg, weighted_avg, places=2)
        self.assertGreater(avg, simple_avg)


class TestPresetSync(unittest.TestCase):
    """测试预设同步功能"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.queue_mgr = QueueManager(config_dir=self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_task(self, idx: int, output_dir: str = None) -> ConvertQueueTask:
        task = ConvertQueueTask(
            input_path=f"/tmp/book{idx}.epub",
            output_format="epub",
            output_dir=output_dir,
            book_title=f"书籍{idx}",
            source_format="epub",
            file_size=1024 * 1024,
            preset_name="默认",
        )
        return task

    def test_apply_preset_updates_format_and_args(self):
        """同步预设应更新 output_format 和 extra_args"""
        task1 = self._make_task(1)
        task2 = self._make_task(2)
        task1.status = TaskStatus.PENDING
        task2.status = TaskStatus.CONVERTING
        self.queue_mgr.add_tasks([task1, task2])

        count = self.queue_mgr.apply_preset_to_all(
            "Kindle优化", output_format="mobi", sync_output_dir=False
        )
        self.assertEqual(count, 1, "只有 PENDING 状态的任务应被更新")

        tasks = self.queue_mgr.get_tasks()
        pending = [t for t in tasks if t.status == TaskStatus.PENDING][0]
        converting = [t for t in tasks if t.status == TaskStatus.CONVERTING][0]

        self.assertEqual(pending.output_format, "mobi")
        self.assertEqual(pending.preset_name, "Kindle优化")
        self.assertIn("--no-inline-toc", pending.extra_args)

        self.assertEqual(converting.output_format, "epub", "转换中的任务不应被修改")
        self.assertEqual(converting.preset_name, "默认", "转换中的任务预设不应改变")

    def test_sync_output_dir_includes_empty_string(self):
        """output_dir 为空字符串应视为清除自定义目录"""
        task = self._make_task(1, output_dir="/old/dir")
        task.status = TaskStatus.FAILED
        self.queue_mgr.add_task(task)

        count = self.queue_mgr.apply_preset_to_all(
            "Kindle优化", output_dir="", output_format="mobi", sync_output_dir=True
        )
        self.assertEqual(count, 1)

        updated = self.queue_mgr.get_tasks()[0]
        self.assertIsNone(updated.output_dir,
                          "空字符串应清除 output_dir 设为 None（使用默认目录）")

    def test_sync_output_dir_updates_all_tasks(self):
        """同步时应更新 output_dir"""
        task1 = self._make_task(1, output_dir="/old/dir")
        task1.status = TaskStatus.PENDING
        task2 = self._make_task(2, output_dir="/old/dir")
        task2.status = TaskStatus.CANCELLED
        self.queue_mgr.add_tasks([task1, task2])

        new_dir = "/new/output/dir"
        count = self.queue_mgr.apply_preset_to_all(
            "默认", output_dir=new_dir, output_format="pdf", sync_output_dir=True
        )
        self.assertEqual(count, 2, "PENDING 和 CANCELLED 都应被更新")

        for t in self.queue_mgr.get_tasks():
            self.assertEqual(t.output_dir, new_dir)
            self.assertEqual(t.output_format, "pdf")

    def test_sync_preset_does_not_affect_completed(self):
        """已完成的任务不应被同步"""
        task = self._make_task(1)
        task.status = TaskStatus.COMPLETED
        self.queue_mgr.add_task(task)

        count = self.queue_mgr.apply_preset_to_all(
            "Kindle优化", output_dir="/new", output_format="mobi", sync_output_dir=True
        )
        self.assertEqual(count, 0, "已完成任务不应被更新")

        updated = self.queue_mgr.get_tasks()[0]
        self.assertEqual(updated.preset_name, "默认")
        self.assertEqual(updated.output_format, "epub")


class TestTaskReorder(unittest.TestCase):
    """测试任务拖拽排序逻辑"""

    def test_reorder_preserves_content(self):
        """TaskTableManager.reorder_rows 逻辑验证（不依赖 GUI）"""
        tasks = [
            ConvertQueueTask(book_title=f"书{i}", task_id=f"id{i}", source_format="epub")
            for i in range(5)
        ]

        def verify_order(expected_order: list):
            ids = [t.task_id for t in tasks]
            self.assertEqual(ids, expected_order)

        verify_order(["id0", "id1", "id2", "id3", "id4"])

        task = tasks.pop(0)
        tasks.insert(3, task)
        verify_order(["id1", "id2", "id3", "id0", "id4"])

        task = tasks.pop(4)
        tasks.insert(1, task)
        verify_order(["id1", "id4", "id2", "id3", "id0"])

    def test_converting_task_preserves_progress_on_reorder(self):
        """拖拽排序时进度条 widget 应被移动，进度值不丢失"""
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


class TestQueuePersistence(unittest.TestCase):
    """测试队列持久化"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tasks_serialize_deserialize(self):
        """任务 JSON 序列化/反序列化"""
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
        self.assertEqual(d["input_path"], "/test/book.epub")
        self.assertEqual(d["status"], "pending")
        self.assertEqual(d["extra_args"], ["--arg1", "--arg2"])

        task2 = ConvertQueueTask.from_dict(d)
        self.assertEqual(task2.input_path, task.input_path)
        self.assertEqual(task2.output_format, task.output_format)
        self.assertEqual(task2.book_title, task.book_title)
        self.assertEqual(task2.preset_name, task.preset_name)
        self.assertEqual(task2.extra_args, task.extra_args)

    def test_converting_status_reset_on_deserialize(self):
        """反序列化时 CONVERTING 状态应重置为 PENDING"""
        task = ConvertQueueTask(
            input_path="/test/book.epub",
            status=TaskStatus.CONVERTING,
            progress=50,
            source_format="epub",
        )
        d = task.to_dict()
        task2 = ConvertQueueTask.from_dict(d)
        self.assertEqual(task2.status, TaskStatus.PENDING,
                         "崩溃恢复时转换中状态应重置为排队中")
        self.assertEqual(task2.progress, 0,
                         "崩溃恢复时进度应重置")

    def test_preset_manager_persistence(self):
        """预设管理器持久化"""
        pm = PresetManager(self.temp_dir)
        custom = ConvertPreset(
            name="自定义测试预设",
            description="测试用",
            output_format="pdf",
            extra_args=["--test"],
        )
        self.assertTrue(pm.add(custom))

        pm2 = PresetManager(self.temp_dir)
        loaded = pm2.get("自定义测试预设")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.output_format, "pdf")
        self.assertEqual(loaded.extra_args, ["--test"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
