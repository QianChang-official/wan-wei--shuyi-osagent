# Kylin VM Test Plan

This plan establishes a repeatable virtual-machine baseline for the Kylin desktop
delivery path. It does not claim target-hardware certification, Kylin SDK support,
or production readiness until those are measured on the required environment.

## Test Image and Host Boundary

- Image: `Kylin-Desktop-V11-2603-Release-20260228-X86_64.iso`
- Local image SHA-256: `9D00C0C605E023AA879D895E3AA430D1DFD3EAFDED6273CF297BC1874F9A29C4`
- Virtualization: QEMU for Windows with the WHPX accelerator
- VM profile: 8 vCPU, 16 GiB RAM, 120 GiB dynamically allocated qcow2 disk
- Network: QEMU user-mode NAT with an emulated `e1000e` NIC

The QEMU launcher is `scripts/start_kylin_vm.ps1`. It stores the VM disk and log
outside the repository at `C:\VMs\Kylin-V11` and does not modify the ISO. The
launcher exposes QMP only on `127.0.0.1:5959` so `scripts/send_qemu_keys.ps1` can
reliably send guest keyboard input without exposing a remote management port.

Start the installer:

```powershell
.\scripts\start_kylin_vm.ps1 -Mode install
```

After installation and ISO ejection, boot the disk:

```powershell
.\scripts\start_kylin_vm.ps1 -Mode boot
```

## Evidence to Collect

Record actual commands, versions, screenshots where useful, and pass/fail output.
Do not replace a failed or unrun item with a planned result.

| Area | Evidence |
| --- | --- |
| Boot and desktop | successful installer completion, kernel version, desktop session, shutdown and reboot |
| Network | DHCP/NAT address, DNS lookup, HTTPS request, package repository reachability |
| Runtime | Python, SQLite, Node, npm, Docker availability and versions |
| Native AI SDK | bridge build, `pkg-config` versions, embedding/upsert/search/delete smoke, fallback proof |
| Backend | `bash scripts/setup.sh`, application startup, `/health/ready`, `bash scripts/smoke.sh` |
| Frontend | `npm --prefix frontend/console-vue ci`, production build, committed dist consistency |
| Memory runtime | SQLite/FTS initialization, MemoryArena-Lite, audit and workflow smoke paths |
| Operations | backup creation, SHA-256 verification, stopped-writer restore rehearsal |
| Security | production API-key requirement, protected metrics, SSRF/rate-limit regression tests |

## Result Classification

- `vm_verified`: observed in this QEMU/WHPX VM and supported by captured evidence.
- `target_hardware_pending`: requires the specified Kylin hardware/desktop target.
- `sdk_pending`: requires an installed and licensed Kylin SDK or vendor component.
- `blocked`: installation, network, package, hardware, or permission issue prevented the test.

Copy verified observations into `docs/COMPATIBILITY_TEST_REPORT.md` only after the
corresponding command has completed. Keep VM-specific evidence separate from target
hardware and vendor SDK claims.
