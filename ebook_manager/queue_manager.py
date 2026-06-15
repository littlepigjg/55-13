import os
import sys
import json
import time
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Dict, Callable, Deque
from collections import deque
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot, QMutex, QMutexLocker,
    QTimer
)

from .queue_models import (
    ConvertQueueTask, TaskStatus, PresetManager, ConvertPreset
)

EBOOK_CONVERT = "ebook-convert"
MAX_CONCURRENT = 3
LOG_DIR_NAME = "conversion_logs"


def setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ebook_converter")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger
    log_file = log_dir / f"conversion_{time.strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


class ConvertWorkerSignals(QObject):
    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int)
    task_completed = pyqtSignal(str, str)
    task_failed = pyqtSignal(str, str)
    task_output = pyqtSignal(str, str)


class ConvertRunnable(QRunnable):
    def __init__(self, task: ConvertQueueTask, logger: logging.Logger):
        super().__init__()
        self._task = task
        self._logger = logger
        self.signals = ConvertWorkerSignals()
        self._cancel_flag = False
        self._process: Optional[subprocess.Popen] = None
        self._mutex = QMutex()

    def cancel(self):
        with QMutexLocker(self._mutex):
            self._cancel_flag = True
            if self._process and self._process.poll() is None:
                try:
                    self._process.terminate()
                    self._process.kill()
                except Exception:
                    pass

    @pyqtSlot()
    def run(self):
        task = self._task
        self.signals.task_started.emit(task.task_id)
        self._logger.info(f"开始转换: {task.input_path} -> {task.output_format}")

        try:
            if not self._check_calibre():
                err = "Calibre (ebook-convert) 未安装或不在 PATH 中"
                self._logger.error(err)
                self.signals.task_failed.emit(task.task_id, err)
                return

            if not os.path.exists(task.input_path):
                err = f"输入文件不存在: {task.input_path}"
                self._logger.error(err)
                self.signals.task_failed.emit(task.task_id, err)
                return

            output_path = task.resolved_output_path
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            cmd = [EBOOK_CONVERT, task.input_path, output_path]
            if task.extra_args:
                cmd.extend(task.extra_args)

            self.signals.task_progress.emit(task.task_id, 10)

            flags = 0
            if os.name == "nt":
                flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

            with QMutexLocker(self._mutex):
                if self._cancel_flag:
                    self.signals.task_failed.emit(task.task_id, "用户取消")
                    return
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=flags,
                    bufsize=1,
                )

            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            while True:
                with QMutexLocker(self._mutex):
                    if self._cancel_flag:
                        try:
                            self._process.kill()
                        except Exception:
                            pass
                        self._logger.info(f"任务已取消: {task.input_path}")
                        self.signals.task_failed.emit(task.task_id, "用户取消")
                        return

                if self._process.poll() is not None:
                    try:
                        remaining_out, remaining_err = self._process.communicate(timeout=5)
                        if remaining_out:
                            stdout_lines.append(remaining_out)
                        if remaining_err:
                            stderr_lines.append(remaining_err)
                    except Exception:
                        pass
                    break

                try:
                    line = self._process.stdout.readline()
                    if line:
                        stdout_lines.append(line)
                        self.signals.task_output.emit(task.task_id, line.strip())
                        self.signals.task_progress.emit(task.task_id, 50)
                    else:
                        time.sleep(0.1)
                except Exception:
                    time.sleep(0.1)

            self.signals.task_progress.emit(task.task_id, 90)

            returncode = self._process.returncode
            if returncode == 0 and os.path.exists(output_path):
                self._logger.info(f"转换成功: {output_path}")
                self.signals.task_progress.emit(task.task_id, 100)
                self.signals.task_completed.emit(task.task_id, output_path)
            else:
                stderr_text = "\n".join(stderr_lines[-20:]) if stderr_lines else ""
                stdout_text = "\n".join(stdout_lines[-10:]) if stdout_lines else ""
                err = stderr_text or stdout_text or f"转换失败，返回码: {returncode}"
                if len(err) > 500:
                    err = err[-500:]
                self._logger.error(f"转换失败: {task.input_path}\n{err}")
                self.signals.task_failed.emit(task.task_id, err)

        except Exception as e:
            err_msg = f"异常错误: {str(e)}"
            self._logger.exception(f"转换异常: {task.input_path}")
            self.signals.task_failed.emit(task.task_id, err_msg)

    def _check_calibre(self) -> bool:
        try:
            result = subprocess.run(
                [EBOOK_CONVERT, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


@dataclass
class ETAStats:
    _durations: deque = field(default_factory=lambda: deque(maxlen=30))
    _smoothed_eta: float = 0.0
    _last_raw_eta: float = 0.0
    _ema_alpha: float = 0.15
    _clamp_up_ratio: float = 1.25
    _clamp_down_ratio: float = 0.7
    _initialized: bool = False
    _min_samples: int = 3
    _last_display_eta: float = 0.0
    _display_min_delta_ratio: float = 0.08
    _display_min_delta_seconds: float = 15.0
    _has_completed_tasks: bool = False

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


class QueueManager(QObject):
    tasks_changed = pyqtSignal()
    task_added = pyqtSignal(str)
    task_removed = pyqtSignal(str)
    task_status_changed = pyqtSignal(str, str)
    task_progress_changed = pyqtSignal(str, int)
    overall_progress_changed = pyqtSignal(int, int, int, int, str)
    queue_started = pyqtSignal()
    queue_finished = pyqtSignal()
    log_message = pyqtSignal(str)

    def __init__(self, config_dir: Optional[str] = None):
        super().__init__()
        self._config_dir = Path(config_dir) if config_dir else Path.home() / ".ebook_manager"
        self._config_dir.mkdir(parents=True, exist_ok=True)

        self._tasks: List[ConvertQueueTask] = []
        self._tasks_mutex = QMutex()

        self._runnables: Dict[str, ConvertRunnable] = {}

        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(MAX_CONCURRENT)

        self._preset_manager = PresetManager(str(self._config_dir))
        self._logger = setup_logger(self._config_dir / LOG_DIR_NAME)

        self._eta_stats = ETAStats()
        self._is_running = False
        self._autostart = True

        self._save_timer = QTimer(self)
        self._save_timer.setInterval(3000)
        self._save_timer.timeout.connect(self.save_queue)

        self._restore_from_disk()

    @property
    def preset_manager(self) -> PresetManager:
        return self._preset_manager

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def max_concurrent(self) -> int:
        return MAX_CONCURRENT

    def set_autostart(self, auto: bool):
        self._autostart = auto

    def get_tasks(self) -> List[ConvertQueueTask]:
        with QMutexLocker(self._tasks_mutex):
            return list(self._tasks)

    def get_task(self, task_id: str) -> Optional[ConvertQueueTask]:
        with QMutexLocker(self._tasks_mutex):
            for t in self._tasks:
                if t.task_id == task_id:
                    return t
        return None

    def add_task(self, task: ConvertQueueTask) -> str:
        with QMutexLocker(self._tasks_mutex):
            self._tasks.append(task)
        task_id = task.task_id
        self.task_added.emit(task_id)
        self.tasks_changed.emit()
        self._emit_overall_progress()
        if self._autostart and task.status == TaskStatus.PENDING:
            QTimer.singleShot(100, self._process_queue)
        return task_id

    def add_tasks(self, tasks: List[ConvertQueueTask]) -> List[str]:
        ids = []
        with QMutexLocker(self._tasks_mutex):
            for task in tasks:
                self._tasks.append(task)
                ids.append(task.task_id)
        for tid in ids:
            self.task_added.emit(tid)
        self.tasks_changed.emit()
        self._emit_overall_progress()
        if self._autostart:
            QTimer.singleShot(100, self._process_queue)
        return ids

    def remove_task(self, task_id: str) -> bool:
        self.cancel_task(task_id)
        with QMutexLocker(self._tasks_mutex):
            for i, t in enumerate(self._tasks):
                if t.task_id == task_id:
                    del self._tasks[i]
                    self.task_removed.emit(task_id)
                    self.tasks_changed.emit()
                    self._emit_overall_progress()
                    return True
        return False

    def clear_completed(self):
        with QMutexLocker(self._tasks_mutex):
            to_remove = [
                t.task_id for t in self._tasks
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
        for tid in to_remove:
            self.remove_task(tid)

    def cancel_task(self, task_id: str):
        runnable = self._runnables.get(task_id)
        if runnable:
            runnable.cancel()
        with QMutexLocker(self._tasks_mutex):
            for t in self._tasks:
                if t.task_id == task_id and t.status == TaskStatus.PENDING:
                    t.mark_cancelled()
                    self.task_status_changed.emit(task_id, t.status.value)
        self.tasks_changed.emit()
        self._emit_overall_progress()

    def cancel_all(self):
        for tid in list(self._runnables.keys()):
            self.cancel_task(tid)
        with QMutexLocker(self._tasks_mutex):
            for t in self._tasks:
                if t.status == TaskStatus.PENDING:
                    t.mark_cancelled()
                    self.task_status_changed.emit(t.task_id, t.status.value)
        self.tasks_changed.emit()
        self._emit_overall_progress()

    def retry_task(self, task_id: str):
        task = self.get_task(task_id)
        if not task:
            return
        if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            return
        if task.retry_count >= task.max_retries:
            task.retry_count = 0
        task.reset_for_retry()
        self.task_status_changed.emit(task_id, task.status.value)
        self.tasks_changed.emit()
        self._emit_overall_progress()
        if self._autostart:
            QTimer.singleShot(100, self._process_queue)

    def move_task(self, task_id: str, target_index: int):
        with QMutexLocker(self._tasks_mutex):
            current_idx = -1
            for i, t in enumerate(self._tasks):
                if t.task_id == task_id:
                    current_idx = i
                    break
            if current_idx < 0:
                return
            task = self._tasks.pop(current_idx)
            target_index = max(0, min(target_index, len(self._tasks)))
            self._tasks.insert(target_index, task)
        self.tasks_changed.emit()

    def apply_preset_to_all(self, preset_name: str, output_dir: Optional[str] = None,
                            output_format: Optional[str] = None,
                            sync_output_dir: bool = False) -> int:
        preset = self._preset_manager.get(preset_name)
        if not preset:
            return 0
        count = 0
        with QMutexLocker(self._tasks_mutex):
            for t in self._tasks:
                if t.status not in (TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    continue
                self._preset_manager.apply_preset_to_task(t, preset_name)
                if sync_output_dir:
                    t.output_dir = output_dir if output_dir else None
                if output_format:
                    t.output_format = output_format.lower()
                count += 1
        if count > 0:
            self.tasks_changed.emit()
            self._emit_overall_progress()
        return count

    def start(self):
        self._save_timer.start()
        self._process_queue()

    def stop(self):
        self._save_timer.stop()
        self.save_queue()

    def _process_queue(self):
        with QMutexLocker(self._tasks_mutex):
            tasks = list(self._tasks)

        running_count = sum(
            1 for t in tasks if t.status == TaskStatus.CONVERTING
        )
        pending = [
            t for t in tasks if t.status == TaskStatus.PENDING
        ]

        if running_count == 0 and not pending:
            if self._is_running:
                self._is_running = False
                self.queue_finished.emit()
            return

        if not self._is_running and (running_count > 0 or pending):
            self._is_running = True
            self.queue_started.emit()

        slots_available = MAX_CONCURRENT - running_count
        if slots_available <= 0 or not pending:
            return

        for task in pending[:slots_available]:
            self._start_task(task)

    def _start_task(self, task: ConvertQueueTask):
        task.mark_started()
        self.task_status_changed.emit(task.task_id, task.status.value)

        runnable = ConvertRunnable(task, self._logger)
        runnable.signals.task_started.connect(self._on_task_started)
        runnable.signals.task_progress.connect(self._on_task_progress)
        runnable.signals.task_completed.connect(self._on_task_completed)
        runnable.signals.task_failed.connect(self._on_task_failed)
        runnable.signals.task_output.connect(self._on_task_output)

        self._runnables[task.task_id] = runnable
        self._pool.start(runnable)
        self.tasks_changed.emit()

    @pyqtSlot(str)
    def _on_task_started(self, task_id: str):
        self.log_message.emit(f"开始转换: {task_id}")
        self._emit_overall_progress()

    @pyqtSlot(str, int)
    def _on_task_progress(self, task_id: str, progress: int):
        task = self.get_task(task_id)
        if task:
            task.progress = progress
            self.task_progress_changed.emit(task_id, progress)
            self._emit_overall_progress()

    @pyqtSlot(str, str)
    def _on_task_completed(self, task_id: str, output_path: str):
        task = self.get_task(task_id)
        if task:
            task.mark_completed(output_path)
            self._eta_stats.add_completion(task.duration_seconds)
            self.task_status_changed.emit(task_id, task.status.value)
            self._logger.info(f"任务完成: {task.input_path} 用时 {task.formatted_duration}")
        self._runnables.pop(task_id, None)
        self.tasks_changed.emit()
        self._emit_overall_progress()
        QTimer.singleShot(50, self._process_queue)

    @pyqtSlot(str, str)
    def _on_task_failed(self, task_id: str, error: str):
        task = self.get_task(task_id)
        if task:
            if task.retry_count < task.max_retries and error != "用户取消":
                task.retry_count += 1
                self._logger.info(f"任务重试 ({task.retry_count}/{task.max_retries}): {task.input_path}")
                self.log_message.emit(f"任务重试 ({task.retry_count}/{task.max_retries}): {Path(task.input_path).name}")
                task.reset_for_retry()
                self.task_status_changed.emit(task_id, task.status.value)
                self._runnables.pop(task_id, None)
                QTimer.singleShot(1000, self._process_queue)
                self.tasks_changed.emit()
                self._emit_overall_progress()
                return
            task.mark_failed(error)
            self.task_status_changed.emit(task_id, task.status.value)
            self._logger.error(f"任务失败: {task.input_path} - {error}")
            if error != "用户取消":
                self.log_message.emit(f"任务失败: {Path(task.input_path).name} - {error[:100]}")
        self._runnables.pop(task_id, None)
        self.tasks_changed.emit()
        self._emit_overall_progress()
        QTimer.singleShot(50, self._process_queue)

    @pyqtSlot(str, str)
    def _on_task_output(self, task_id: str, output: str):
        pass

    def _emit_overall_progress(self):
        with QMutexLocker(self._tasks_mutex):
            tasks = list(self._tasks)
        total = len(tasks)
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        converting = sum(1 for t in tasks if t.status == TaskStatus.CONVERTING)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        cancelled = sum(1 for t in tasks if t.status == TaskStatus.CANCELLED)
        pending = total - completed - converting - failed - cancelled

        current_task = ""
        for t in tasks:
            if t.status == TaskStatus.CONVERTING:
                current_task = t.display_name
                break

        if total > 0:
            done = completed + failed + cancelled
            avg_progress = 0
            for t in tasks:
                if t.status == TaskStatus.COMPLETED:
                    avg_progress += 100
                elif t.status == TaskStatus.CONVERTING:
                    avg_progress += t.progress
            overall_pct = int((avg_progress / total)) if total > 0 else 0
        else:
            overall_pct = 0

        if total == 0 and pending == 0 and converting == 0:
            self._eta_stats.reset()

        eta_seconds = self._eta_stats.get_display_eta(pending, converting)
        remaining = pending + converting
        eta_str = self._eta_stats.format_eta(eta_seconds, remaining)

        self.overall_progress_changed.emit(
            overall_pct, total, completed, converting,
            f"{current_task} | {eta_str}" if current_task else eta_str
        )

    def _get_queue_file(self) -> Path:
        return self._config_dir / "conversion_queue.json"

    def save_queue(self):
        tasks = self.get_tasks()
        if not tasks:
            try:
                if self._get_queue_file().exists():
                    self._get_queue_file().unlink()
            except Exception:
                pass
            return
        try:
            data = {
                "saved_at": time.time(),
                "version": "1.0",
                "tasks": [t.to_dict() for t in tasks],
            }
            with open(self._get_queue_file(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._logger.error(f"保存队列失败: {e}")

    def _restore_from_disk(self):
        queue_file = self._get_queue_file()
        if not queue_file.exists():
            return
        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            restored = 0
            for item in data.get("tasks", []):
                task = ConvertQueueTask.from_dict(item)
                if os.path.exists(task.input_path):
                    if task.status == TaskStatus.CONVERTING:
                        task.status = TaskStatus.PENDING
                        task.progress = 0
                        task.started_at = None
                    with QMutexLocker(self._tasks_mutex):
                        self._tasks.append(task)
                    restored += 1
                    self.task_added.emit(task.task_id)
            if restored > 0:
                self._logger.info(f"恢复了 {restored} 个未完成的转换任务")
                self.log_message.emit(f"已恢复 {restored} 个未完成任务")
                self.tasks_changed.emit()
                self._emit_overall_progress()
        except Exception as e:
            self._logger.error(f"恢复队列失败: {e}")

    def get_log_dir(self) -> Path:
        return self._config_dir / LOG_DIR_NAME
