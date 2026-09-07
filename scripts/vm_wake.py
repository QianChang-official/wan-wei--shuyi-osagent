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

# 一次性 QA 脚本：经 QEMU HMP 发送 ctrl 键唤醒麒麟 V11 虚拟机屏幕。
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

def type_line(h, text, delay=0.05):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(0.4)

def main():
    h = HMP()
    # 唤醒屏幕（如果锁屏/休眠）
    h.sendkey("ctrl")
    time.sleep(1)
    h.close()
    print("wakeup sent")

if __name__ == "__main__":
    main()
