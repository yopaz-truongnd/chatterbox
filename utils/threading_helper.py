"""
Bộ trợ giúp đa luồng chạy tác vụ nền (background tasks) tránh đơ GUI trong Tkinter
"""

import threading
from .logger import logger

def run_in_background(task_fn, callback_fn=None, root_widget=None, *args, **kwargs):
    """
    Chạy hàm task_fn(*args, **kwargs) trong một background thread mới.
    Nếu cung cấp callback_fn và root_widget, callback sẽ được gọi trên luồng GUI
    thông qua root_widget.after để cập nhật giao diện an toàn.
    """
    def thread_run():
        try:
            logger.info("Bắt đầu chạy tác vụ nền: %s", task_fn.__name__)
            # Thực thi hàm task
            result = task_fn(*args, **kwargs)
            
            if callback_fn and root_widget:
                # Cập nhật kết quả về GUI thread
                root_widget.after(0, lambda: callback_fn(True, result))
        except Exception as e:
            logger.error("Lỗi xảy ra trong tác vụ nền %s: %s", task_fn.__name__, e, exc_info=True)
            if callback_fn and root_widget:
                err_msg = str(e)
                root_widget.after(0, lambda err=err_msg: callback_fn(False, err))

    thread = threading.Thread(target=thread_run, daemon=True)
    thread.start()
    return thread
