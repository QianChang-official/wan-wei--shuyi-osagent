# 一次性 QA 脚本：经 QEMU HMP 检查麒麟 V11 虚拟机内 linux-unpacked 可执行文件的 kysec 安全属性与 dmesg。
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

def run(h, text, delay=0.06, wait=1.0):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    # 按下回车让新命令出现
    h.sendkey("ret")
    time.sleep(1)
    # 检查安全策略/ostree 状态
    run(h, "ls -la /home/wanwei/wanwei/app/desktop/release/linux-unpacked/wanwei-shuyi-desktop", wait=1)
    run(h, "file /home/wanwei/wanwei/app/desktop/release/linux-unpacked/wanwei-shuyi-desktop", wait=1)
    run(h, "getfattr -n security.kysec /home/wanwei/wanwei/app/desktop/release/linux-unpacked/wanwei-shuyi-desktop 2>&1 | head -3", wait=1)
    run(h, "dmesg | tail -5", wait=1)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
