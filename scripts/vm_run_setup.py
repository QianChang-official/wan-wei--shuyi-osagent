import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

PASSWORD = "@Qwe123asdf"

def run(h, text, delay=0.06, wait=0.6):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    run(h, "mkdir -p ~/wanwei && cd ~/wanwei", wait=0.8)
    run(h, "curl -s -o guest_setup.sh http://10.0.2.2:8000/scripts/guest_setup.sh", wait=3)
    run(h, "ls -l guest_setup.sh && head -2 guest_setup.sh", wait=1)
    run(h, "bash guest_setup.sh 2>&1 | tee setup.log | tail -15", wait=90)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
