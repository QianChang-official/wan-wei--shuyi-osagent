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
    # 在 guest 起一个只读文件 HTTP 服务器，让宿主机下载
    run(h, "cd ~/wanwei/app/desktop/release/linux-unpacked && nohup python3 -m http.server 9000 --bind 10.0.2.15 > /tmp/http.log 2>&1 &", wait=1.5)
    run(h, "echo HTTP_PID=$!", wait=1)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
