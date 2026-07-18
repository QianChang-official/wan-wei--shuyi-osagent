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
    run(h, "pkill -f 'http.server 9000' 2>/dev/null; sleep 1", wait=2)
    run(h, "cd ~/wanwei/app/desktop/release/linux-unpacked && nohup python3 -m http.server 9000 --bind 0.0.0.0 > /tmp/http.log 2>&1 &", wait=2)
    run(h, "sleep 2 && ss -tlnp | grep 9000 || netstat -tlnp | grep 9000", wait=3)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
