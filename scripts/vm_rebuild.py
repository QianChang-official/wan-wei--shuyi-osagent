# 一次性 QA 脚本：经 QEMU HMP 在麒麟 V11 虚拟机重新拉取源码包并后台重跑 guest_build.sh。
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
    run(h, "cd ~/wanwei", wait=0.5)
    # 重新拉源码 + 重新构建（会覆盖旧 app 目录）
    run(h, "rm -rf app && mkdir -p app && curl -s -o wanwei-src.tar.gz http://10.0.2.2:8000/dl/wanwei-src.tar.gz && tar -xzf wanwei-src.tar.gz -C app", wait=5)
    run(h, "nohup bash guest_build.sh > build2.log 2>&1 &", wait=1)
    h.close()
    print("rebuild kicked off")

if __name__ == "__main__":
    main()
