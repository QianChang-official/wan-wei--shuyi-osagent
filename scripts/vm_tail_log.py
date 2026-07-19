# 一次性 QA 脚本：经 QEMU HMP 查看麒麟 V11 虚拟机构建日志 build.log 尾部。
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

def run(h, text, delay=0.06, wait=0.6):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    run(h, "tail -25 ~/wanwei/build.log", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
