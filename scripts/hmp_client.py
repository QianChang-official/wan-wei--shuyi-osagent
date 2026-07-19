"""QEMU HMP（Human Monitor Protocol）最小 TCP 客户端：供 scripts/vm_*.py 一次性 QA 脚本驱动麒麟 V11 虚拟机。"""

import json
import re
import socket
import sys
import time


class HMP:
    """Minimal QEMU Human Monitor Protocol client (text console over TCP)."""

    def __init__(self, host="127.0.0.1", port=4445, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = b""
        self._read_until_prompt()

    def _recv_more(self):
        data = self.sock.recv(65536)
        if not data:
            raise ConnectionError("HMP connection closed")
        self.buf += data

    def _read_until_prompt(self):
        """Read until the '(qemu)' prompt, returning text before it."""
        deadline = time.time() + 15
        while b"(qemu)" not in self.buf:
            if time.time() > deadline:
                raise TimeoutError("no (qemu) prompt; got: %r" % self.buf[-200:])
            self._recv_more()
        text, _, rest = self.buf.partition(b"(qemu)")
        self.buf = rest
        return text.decode(errors="replace")

    def cmd(self, command, wait=0.3):
        # HMP echoes the command back; strip echo from output.
        self.sock.sendall(command.encode() + b"\n")
        time.sleep(wait)
        out = self._read_until_prompt()
        lines = out.replace("\r", "").split("\n")
        cleaned = []
        for ln in lines:
            ln = ln.strip()
            if not ln or ln == command:
                continue
            cleaned.append(ln)
        return "\n".join(cleaned)

    def screendump(self, path="/tmp/screen.ppm"):
        return self.cmd(f"screendump {path}", wait=1.5)

    def sendkey(self, key, hold_ms=80):
        return self.cmd(f"sendkey {key} {hold_ms}")

    def type_text(self, text, delay=0.06):
        for ch in text:
            self.sendkey(char_to_qcode(ch))
            time.sleep(delay)

    def info_network(self):
        return self.cmd("info network")

    def info_usernet(self):
        return self.cmd("info usernet")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


SHIFT_MAP = {
    "A": "shift-a", "B": "shift-b", "C": "shift-c", "D": "shift-d",
    "E": "shift-e", "F": "shift-f", "G": "shift-g", "H": "shift-h",
    "I": "shift-i", "J": "shift-j", "K": "shift-k", "L": "shift-l",
    "M": "shift-m", "N": "shift-n", "O": "shift-o", "P": "shift-p",
    "Q": "shift-q", "R": "shift-r", "S": "shift-s", "T": "shift-t",
    "U": "shift-u", "V": "shift-v", "W": "shift-w", "X": "shift-x",
    "Y": "shift-y", "Z": "shift-z",
    "!": "shift-1", "@": "shift-2", "#": "shift-3", "$": "shift-4",
    "%": "shift-5", "^": "shift-6", "&": "shift-7", "*": "shift-8",
    "(": "shift-9", ")": "shift-0", "_": "shift-minus",
    "+": "shift-equal_sign", "{": "shift-bracket_left",
    "}": "shift-bracket_right", "|": "shift-backslash",
    ":": "shift-semicolon", '"': "shift-apostrophe",
    "<": "shift-comma", ">": "shift-dot", "?": "shift-slash",
    "~": "shift-grave_accent",
}

PLAIN_MAP = {
    " ": "spc", "-": "minus", "=": "equal_sign", "[": "bracket_left",
    "]": "bracket_right", "\\": "backslash", ";": "semicolon",
    "'": "apostrophe", ",": "comma", ".": "dot", "/": "slash",
    "`": "grave_accent", "\n": "ret", "\t": "tab",
}


def char_to_qcode(ch: str) -> str:
    if ch in SHIFT_MAP:
        return SHIFT_MAP[ch]
    if ch in PLAIN_MAP:
        return PLAIN_MAP[ch]
    if ch.isalnum():
        return ch.lower()
    raise ValueError(f"unsupported char for sendkey: {ch!r}")


def slirp_guest_ips(info_network_output: str):
    """Parse 'info network' to extract user-net hub id."""
    # Typical line:
    #  e1000e.0: index=0,type=nic,model=e1000e,macaddr=52:54:00:12:34:56
    #  \ net0: index=0,type=user,net=10.0.2.0
    ips = re.findall(r"net=(\d+\.\d+\.\d+)\.0", info_network_output)
    guests = []
    for net in ips:
        guests.append(f"{net}.15")
    return guests


def fetch_screendump_ppm(hmp, guest_ip, local_out, timeout=30):
    """screendump inside VM then fetch the PPM via slirp built-in TFTP (UDP 69).

    slirp exposes guest files via TFTP at the guest address? Actually slirp
    provides TFTP *server* at 10.0.2.4 for the guest to download FROM host.
    To fetch files FROM the guest we cannot use slirp. This function is kept
    for PPM located on host if VM exposes it. Prefer HTTP approach instead.
    """
    raise NotImplementedError


def http_get(url, timeout=15):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


if __name__ == "__main__":
    h = HMP()
    print("== info network ==")
    netinfo = h.info_network()
    print(netinfo)
    print("guest candidates:", slirp_guest_ips(netinfo))
    h.close()
