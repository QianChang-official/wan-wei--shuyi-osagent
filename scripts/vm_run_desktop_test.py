# 一次性 QA 脚本：经 QEMU HMP 在麒麟 V11 虚拟机试启动 linux-unpacked 桌面端（约 12 秒后结束）。
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
    APP = "~/wanwei/app/desktop/release/linux-unpacked/wanwei-shuyi-desktop"
    # 测试能否启动（运行 10s 后 kill）
    run(h, f"{APP} --no-sandbox 2>&1 | head -30 &", wait=1)
    run(h, "APP_PID=$!; sleep 12; kill $APP_PID 2>/dev/null; echo KILLED_$APP_PID", wait=15)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
