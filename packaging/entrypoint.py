"""PyInstaller 打包入口。"""

from __future__ import annotations

import multiprocessing

from image_compressor.cli import main

if __name__ == "__main__":
    # tqdm 会创建 multiprocessing 锁，冻结后必须让 PyInstaller 接管
    # resource_tracker 子进程，否则子进程会再次执行本入口并解析命令行。
    multiprocessing.freeze_support()
    raise SystemExit(main())
