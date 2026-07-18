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
    run(h, "curl -s -o guest_build.sh http://10.0.2.2:8000/scripts/guest_build.sh", wait=3)
    # 后台执行并写日志，避免终端阻塞；立即返回
    run(h, "nohup bash guest_build.sh > build.log 2>&1 &", wait=1)
    run(h, "echo BUILD_STARTED pid=$!", wait=1)
    h.close()
    print("build kicked off")

if __name__ == "__main__":
    main()
