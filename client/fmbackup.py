#!/usr/bin/env python3
"""fmbackup.py — restorable backup/restore of the FastMile 5G Gateway 3.2,
with built-in validation.

The gateway's rootfs is squashfs+tmpfs (ephemeral); the only restorable state
is the persistent /data overlay and the /configs DB. "Restore" is the stock
/etc/init.d/1restore boot hook: it extracts /data/sysupgrade.tgz to / and
deletes it. See docs/web-ui.md (persistence).

Device ops need a ROOT ssh shell on the gateway (set FM_SSH / FM_SSH_USER).
How to get one is out of scope for this project.

The archives hold the gateway's whole configuration, including its
passwords and Wi-Fi keys. Keep backups/ private (it is in .gitignore).

Commands:
  backup                 remote-create archive of /data + /configs, verify its
                         sha256 END-TO-END (device vs local), save under backups/
  verify   <file.tgz>    offline integrity + contents check of a saved archive
  restore  <file> --yes  snapshot current state first, push archive to
                         /data/sysupgrade.tgz, re-verify remote sha, then reboot
  restore-selftest --yes push a BENIGN marker archive through the restore channel
                         and confirm it applied after reboot (non-destructive)
  selftest               OFFLINE: round-trip the whole create/verify/restore
                         logic against a fake root — no device, safe to run now

Env: FM_SSH (e.g. root@192.168.1.1) OR FM_SSH_USER + FM_SSH_HOST[:default
     192.168.1.1] + FM_SSH_PORT[:22].
"""
import os, sys, time, json, hashlib, subprocess, tempfile, shutil

HOST = os.environ.get("FM_SSH_HOST", "192.168.1.1")
PORT = os.environ.get("FM_SSH_PORT", "22")
USER = os.environ.get("FM_SSH_USER", "")
SSH_TARGET = os.environ.get("FM_SSH", f"{USER}@{HOST}" if USER else "")
ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUPS = os.path.normpath(os.path.join(ROOT, "..", "backups"))

# top-level paths captured (relative to /) — the restorable config state
PATHS = ["data", "configs"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ssh(cmd, **kw):
    if not SSH_TARGET:
        sys.exit("no ssh target: set FM_SSH or FM_SSH_USER (a root shell "
                 "on the gateway is required)")
    full = ["ssh", "-p", PORT, "-o", "StrictHostKeyChecking=accept-new",
            SSH_TARGET, cmd]
    return subprocess.run(full, **kw)


def ssh_out(cmd):
    r = ssh(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.exit(f"ssh failed ({r.returncode}): {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode(errors="replace").strip()


# ---- archive helpers (single-sourced; used by device ops AND selftest) ----

def tar_create_cmd(root, paths, out):
    # deterministic-ish; create then sha on the same host so the checksum
    # covers the exact bytes we download
    sel = " ".join(paths)
    return f"cd {root} && tar czf {out} {sel} && sha256sum {out} | cut -d' ' -f1"


def tar_apply_cmd(root, archive):
    # exactly what 1restore does, minus the rm
    return f"cd {root} && tar xzf {archive}"


def verify_archive(path):
    """Offline: gzip integrity, tar listing, size, sha. Returns a dict; raises
    on hard failure."""
    info = {"file": path, "bytes": os.path.getsize(path),
            "sha256": sha256_file(path)}
    g = subprocess.run(["gzip", "-t", path], stderr=subprocess.PIPE)
    if g.returncode != 0:
        raise ValueError(f"gzip integrity FAILED: {g.stderr.decode().strip()}")
    t = subprocess.run(["tar", "-tzf", path], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if t.returncode != 0:
        raise ValueError(f"tar listing FAILED: {t.stderr.decode().strip()}")
    members = [m for m in t.stdout.decode(errors="replace").splitlines() if m]
    tops = sorted({m.split("/")[0] for m in members})
    info["members"] = len(members)
    info["top_level"] = tops
    if info["bytes"] == 0 or not members:
        raise ValueError("archive is empty")
    return info


# ---- device operations ----

def do_backup():
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(BACKUPS, ts)
    os.makedirs(out, exist_ok=True)
    remote = f"/data/.fmbackup-{ts}.tgz"
    local = os.path.join(out, "data-configs.tgz")
    print(f"== creating {remote} on device ({' '.join(PATHS)}) ==")
    remote_sha = ssh_out(tar_create_cmd("/", PATHS, remote))
    print(f"   remote sha256: {remote_sha}")
    with open(local, "wb") as f:
        r = ssh(f"cat {remote}", stdout=f)
    if r.returncode != 0:
        sys.exit("download failed")
    ssh_out(f"rm -f {remote}")                     # clean up device temp
    local_sha = sha256_file(local)
    print(f"   local  sha256: {local_sha}")
    # check 1: end-to-end integrity across the transport
    if local_sha != remote_sha:
        sys.exit("INTEGRITY MISMATCH device vs local — backup NOT trustworthy")
    # check 2 + 3: offline gzip + tar structure
    info = verify_archive(local)
    info.update({"remote_sha256": remote_sha, "timestamp": ts,
                 "paths": PATHS, "ssh_target": SSH_TARGET})
    # optional canonical OpenWrt config archive, if sysupgrade present & root
    sb = ssh(f"sysupgrade -b /data/.fmsb-{ts}.tgz 2>/dev/null && "
             f"cat /data/.fmsb-{ts}.tgz; rm -f /data/.fmsb-{ts}.tgz",
             stdout=subprocess.PIPE).stdout
    if sb:
        open(os.path.join(out, "sysupgrade-config.tgz"), "wb").write(sb)
        info["sysupgrade_bytes"] = len(sb)
        print(f"   + sysupgrade -b config ({len(sb)}B)")
    json.dump(info, open(os.path.join(out, "_backup.json"), "w"), indent=2)
    print(f"\nVERIFIED backup ({info['members']} members, top={info['top_level']})")
    print(f"written to: {out}")


def do_verify(path):
    try:
        info = verify_archive(path)
    except ValueError as e:
        sys.exit(f"INVALID archive: {e}")
    print(json.dumps(info, indent=2))
    print("\nOK: gzip + tar structure valid, non-empty.")


def _require_yes(argv):
    if "--yes" not in argv:
        sys.exit("refusing without --yes (this overwrites config and REBOOTS)")


def do_restore(path, argv):
    _require_yes(argv)
    verify_archive(path)                           # never push a bad archive
    local_sha = sha256_file(path)
    print("== safety snapshot of current state first ==")
    do_backup()
    print(f"\n== pushing {path} -> /data/sysupgrade.tgz ==")
    with open(path, "rb") as f:
        r = ssh("cat > /data/sysupgrade.tgz", stdin=f)
    if r.returncode != 0:
        sys.exit("upload failed")
    remote_sha = ssh_out("sha256sum /data/sysupgrade.tgz | cut -d' ' -f1")
    if remote_sha != local_sha:
        ssh_out("rm -f /data/sysupgrade.tgz")
        sys.exit("uploaded sha mismatch — aborted, removed partial upload")
    print(f"   verified on device: {remote_sha}")
    ssh_out("sync")
    print("== rebooting; 1restore will apply it at boot ==")
    ssh("reboot")
    print("sent. reconnect after it comes back up to confirm.")


def do_restore_selftest(argv):
    _require_yes(argv)
    ts = time.strftime("%Y%m%d-%H%M%S")
    marker = f"/data/fm-restore-proof-{ts}"
    print(f"== building benign marker archive (adds {marker}) ==")
    # stage data/fm-restore-proof-* on the device, archive, push, reboot
    stage = f"/data/.fmproof-{ts}"
    ssh_out(f"mkdir -p {stage}/data && echo {ts} > {stage}/data/fm-restore-proof-{ts} "
            f"&& cd {stage} && tar czf /data/sysupgrade.tgz data && sync")
    ssh_out(f"rm -rf {stage}")
    print("== rebooting to apply the marker via 1restore ==")
    ssh("reboot")
    print(f"sent. after it returns, run:  ssh {SSH_TARGET} cat {marker}")
    print(f"expected contents: {ts}  (proves the restore channel applied our archive)")


# ---- OFFLINE selftest: validate the whole logic with no device ----

def _sh(cmd):
    r = subprocess.run(["sh", "-c", cmd], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    return r.returncode, r.stdout.decode(), r.stderr.decode()


def do_selftest():
    tmp = tempfile.mkdtemp(prefix="fmbackup-selftest-")
    passed, failed = [], []

    def check(name, cond):
        (passed if cond else failed).append(name)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    try:
        # 1. fake device root with data/ + configs/
        dev = os.path.join(tmp, "dev")
        for p in PATHS:
            os.makedirs(os.path.join(dev, p))
        open(os.path.join(dev, "data", "uci_ddns"), "w").write("config ddns\n")
        os.makedirs(os.path.join(dev, "data", "overlay"))
        open(os.path.join(dev, "data", "overlay", "x"), "wb").write(os.urandom(2048))
        open(os.path.join(dev, "configs", "tr181.db"), "wb").write(os.urandom(4096))

        # 2. create archive the way the device would, then verify offline
        arc = os.path.join(tmp, "backup.tgz")
        rc, sha, err = _sh(tar_create_cmd(dev, PATHS, arc))
        check("create archive", rc == 0)
        remote_sha = sha.strip()
        info = verify_archive(arc)
        check("gzip+tar valid, non-empty", info["members"] > 0)
        check("top-level == data,configs", info["top_level"] == ["configs", "data"])
        check("device-sha == local-sha (transport integrity model)",
              remote_sha == sha256_file(arc))

        # 3. corruption is detected (the 'triple check' catching damage)
        bad = os.path.join(tmp, "bad.tgz")
        shutil.copy(arc, bad)
        with open(bad, "r+b") as f:
            f.seek(info["bytes"] // 2); f.write(b"\x00\xff\x00\xff")
        corrupt_caught = False
        try:
            verify_archive(bad)
        except ValueError:
            corrupt_caught = True
        check("corruption rejected by verify", corrupt_caught)

        # 4. restore applies exactly like 1restore (tar xzf to a fresh root)
        dev2 = os.path.join(tmp, "dev2"); os.makedirs(dev2)
        rc, _, err = _sh(tar_apply_cmd(dev2, arc))
        check("restore extracts without error", rc == 0)

        # 5. round-trip fidelity: restored tree == original tree
        rc, out, _ = _sh(f"diff -r {dev} {dev2}")
        check("restored tree identical to original (byte-for-byte)", rc == 0)

        # 6. marker-restore semantics (what restore-selftest does on-device)
        stage = os.path.join(tmp, "stage"); os.makedirs(os.path.join(stage, "data"))
        open(os.path.join(stage, "data", "fm-restore-proof"), "w").write("ok")
        proof = os.path.join(tmp, "proof.tgz")
        _sh(f"cd {stage} && tar czf {proof} data")
        dev3 = os.path.join(tmp, "dev3"); os.makedirs(dev3)
        _sh(tar_apply_cmd(dev3, proof))
        check("marker archive applies to /data",
              os.path.isfile(os.path.join(dev3, "data", "fm-restore-proof")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(passed)} passed, {len(failed)} failed.")
    if failed:
        print("FAILED:", ", ".join(failed)); sys.exit(1)
    print("ALL OFFLINE CHECKS PASSED")
    print("(validates archive create/verify/restore logic + integrity + "
          "round-trip fidelity; SSH transport & real reboot are proven "
          "on-device once root is available.)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "backup":
        do_backup()
    elif cmd == "verify":
        do_verify(sys.argv[2])
    elif cmd == "restore":
        do_restore(sys.argv[2], sys.argv[3:])
    elif cmd == "restore-selftest":
        do_restore_selftest(sys.argv[2:])
    elif cmd == "selftest":
        do_selftest()
    else:
        sys.exit(__doc__)
