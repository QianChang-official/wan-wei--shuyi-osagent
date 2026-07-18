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
    run(h, "curl -s -o guest_setup2.sh http://10.0.2.2:8000/scripts/guest_setup2.sh", wait=3)
    run(h, "bash guest_setup2.sh 2>&1 | tee setup2.log | tail -20", wait=90)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
