import os
from pathlib import Path
import time


def test_controlled_timeout():
    Path("timeout.pid").write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(60)
