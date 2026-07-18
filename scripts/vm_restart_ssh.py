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
    run(h, "sudo systemctl restart ssh.socket ssh.service", wait=2)
    run(h, PASSWORD, delay=0.1, wait=2)
    run(h, "ss -tlnp | grep :22 || sudo ss -tlnp | grep :22", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
