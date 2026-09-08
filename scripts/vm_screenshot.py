# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

# 一次性 QA 脚本：经 QEMU HMP screendump 截取麒麟 V11 虚拟机画面并转为 PNG（依赖 PIL）。
import struct
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP, http_get


def ppm_bytes_to_png(ppm_path, out_path):
    from PIL import Image
    img = Image.open(ppm_path)
    img.save(out_path)
    return out_path


def take_screenshot(local_png):
    h = HMP()
    h.screendump(r"C:\VMs\Kylin-V11\screen.ppm")
    h.close()
    time.sleep(0.5)
    return ppm_bytes_to_png(r"C:\VMs\Kylin-V11\screen.ppm", local_png)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
    print(take_screenshot(out))
