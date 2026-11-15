"""测试包引导。

把仓库内的 ``src`` 目录加入导入路径，使测试在未执行 ``pip install -e .``
（例如无网络环境）时也能直接运行：

    python -m unittest discover -s tests -t .
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
