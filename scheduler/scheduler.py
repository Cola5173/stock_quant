"""
交易调度器
基于 APScheduler，每个交易日收盘后自动执行完整流程
"""
import logging
import os
import signal
import sys
import time

from config import settings

logger = logging.getLogger(__name__)

PID_FILE = os.path.join(settings.LOG_DIR, "scheduler.pid")


class TradingScheduler:
    """交易调度器"""

    def __init__(self, strategy: str = "b1", source: str = "akshare"):
        self.strategy = strategy
        self.source = source
        self.scheduler = None

    def start(self):
        """启动调度器"""
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger

        # 配置日志
        self._setup_logging()

        self.scheduler = BlockingScheduler()

        # 每个工作日 15:30 执行
        self.scheduler.add_job(
            self._run_daily_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=15,
                minute=30,
            ),
            id='daily_scan',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

        # 写入 PID 文件
        self._write_pid()

        # 注册退出信号
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info(f"调度器已启动 (策略: {self.strategy}, 数据源: {self.source})")
        logger.info("每个工作日 15:30 自动执行")
        print(f"调度器已启动，PID: {os.getpid()}")
        print("每个工作日 15:30 自动执行")
        print("按 Ctrl+C 停止")

        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器已停止")
        finally:
            self._remove_pid()

    def _run_daily_job(self):
        """执行每日任务"""
        from scheduler.jobs import daily_job
        daily_job(strategy=self.strategy, source=self.source)

    def _setup_logging(self):
        """配置日志"""
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        log_file = os.path.join(settings.LOG_DIR, "scheduler.log")

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        )

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def _write_pid(self):
        """写入 PID 文件"""
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

    def _remove_pid(self):
        """删除 PID 文件"""
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

    def _handle_signal(self, signum, frame):
        """处理退出信号"""
        logger.info(f"收到信号 {signum}，正在停止调度器...")
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
        self._remove_pid()
        sys.exit(0)

    @staticmethod
    def stop():
        """停止调度器"""
        if not os.path.exists(PID_FILE):
            print("调度器未运行")
            return

        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        try:
            os.kill(pid, signal.SIGTERM)
            print(f"已发送停止信号到 PID {pid}")
            # 等待进程退出
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except OSError:
                    print("调度器已停止")
                    return
            print("调度器未在预期时间内停止")
        except OSError:
            print(f"PID {pid} 不存在，清理 PID 文件")
            os.remove(PID_FILE)

    @staticmethod
    def status():
        """查看调度器状态"""
        if not os.path.exists(PID_FILE):
            print("调度器未运行")
            return

        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        try:
            os.kill(pid, 0)
            print(f"调度器运行中，PID: {pid}")
        except OSError:
            print(f"PID {pid} 不存在（调度器已异常退出）")
            os.remove(PID_FILE)
