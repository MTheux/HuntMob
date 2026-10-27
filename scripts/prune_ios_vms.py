"""Inventory and prune iOS research VMs under ~/.huntmob/research/ios-vms.

Read-only inventory by default. Destructive pruning only with an explicit
target and --apply. Never touches validation evidence; refuses VMs that may
be active; preserves the tip of each checkpoint chain unless forced.
"""
import argparse
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

DEFAULT_ROOT = Path.home() / ".huntmob/research/ios-vms"

CHECKPOINT_STAMP = re.compile(r"(\d{8})-(\d{6})$")


@dataclass
class Checkpoint:
    name: str
    path: Path
    stamp: str
    is_tip: bool = False


@dataclass
class VmInfo:
    name: str
    path: Path
    checkpoints: List[Checkpoint] = field(default_factory=list)


def _stamp(name: str) -> str:
    match = CHECKPOINT_STAMP.search(name)
    return (match.group(1) + match.group(2)) if match else ""


TRACE_STAMP = re.compile(r"^native-storage-trace-(\d{8})")
ACTIVE_SOCKETS = ("qmp.sock", "usb.sock")


def _owning_vm(target: Path, vm_root: Path) -> Path:
    """The directory directly under vm_root that contains (or is) target."""
    root = vm_root.resolve()
    current = target.resolve()
    if root not in current.parents:
        raise ValueError("Target is not inside the ios-vms root: " + str(target))
    while current.parent != root:
        current = current.parent
    return current


@dataclass
class PruneResult:
    targets: List[Path]
    applied: bool
    free_before: int
    free_after: int
    archived: List[Path] = field(default_factory=list)


def prune(targets, vm_root: Path, *, apply: bool = False, archive_dir=None) -> PruneResult:
    targets = list(targets)
    guard_targets(targets, vm_root)
    free_before = shutil.disk_usage(vm_root).free
    archived: List[Path] = []
    if apply:
        for target in targets:
            if archive_dir is not None:
                archive_dir.mkdir(parents=True, exist_ok=True)
                base = archive_dir / target.name
                shutil.make_archive(str(base), "gztar",
                                    root_dir=str(target.parent), base_dir=target.name)
                archived.append(base.with_name(base.name + ".tar.gz"))
            shutil.rmtree(target)
    free_after = shutil.disk_usage(vm_root).free
    return PruneResult(targets=targets, applied=apply, free_before=free_before,
                       free_after=free_after, archived=archived)


def guard_targets(targets, vm_root: Path) -> None:
    for target in targets:
        if target.is_symlink() or not target.is_dir():
            raise ValueError("Target must be an existing non-symlink directory: " + str(target))
        vm = _owning_vm(target, vm_root)
        for name in ACTIVE_SOCKETS:
            if any(vm.rglob(name)):
                raise ValueError("Owning VM may be active (socket present): " + vm.name)


def select_targets(vms: List[VmInfo], *, whole_vms=(), superseded=(),
                   traces_before=None, force=False) -> List[Path]:
    by_name = {vm.name: vm for vm in vms}
    targets: List[Path] = []
    for name in whole_vms:
        vm = by_name[name]
        if vm.checkpoints and not force:
            raise ValueError("Removing " + name + " deletes its chain tip; pass force")
        targets.append(vm.path)
    for name in superseded:
        vm = by_name[name]
        targets.extend(c.path for c in vm.checkpoints if not c.is_tip)
    if traces_before is not None:
        cutoff = traces_before.replace("-", "")
        for vm in vms:
            match = TRACE_STAMP.match(vm.name)
            if match and match.group(1) < cutoff:
                targets.append(vm.path)
    return targets


def scan(vm_root: Path) -> List[VmInfo]:
    vms: List[VmInfo] = []
    for entry in sorted(p for p in vm_root.iterdir() if p.is_dir()):
        checkpoints = [
            Checkpoint(name=c.name, path=c, stamp=_stamp(c.name))
            for c in sorted(entry.iterdir())
            if c.is_dir() and c.name.startswith("checkpoint-")
        ]
        if checkpoints:
            tip = max(checkpoints, key=lambda c: c.stamp)
            tip.is_tip = True
        vms.append(VmInfo(name=entry.name, path=entry, checkpoints=checkpoints))
    return vms


def allocated_bytes(path: Path) -> int:
    """Blocks actually allocated on disk (matches du; a CoW-aware upper bound)."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            total += entry.stat().st_blocks * 512
    return total


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return ("%.1f %s" % (size, unit)) if unit != "B" else ("%d B" % n)
        size /= 1024
    return "%d B" % n


def print_inventory(vm_root: Path) -> None:
    usage = shutil.disk_usage(vm_root)
    print("ios-vms: %s" % vm_root)
    print("volume: %s livre de %s" % (human(usage.free), human(usage.total)))
    print("aviso: tamanho alocado (du); com CoW/APFS o reclaim real pode ser menor e so e exato com --apply\n")
    for vm in scan(vm_root):
        size = allocated_bytes(vm.path)
        tip = next((c.name for c in vm.checkpoints if c.is_tip), "-")
        print("%-52s %10s  checkpoints=%d  tip=%s"
              % (vm.name, human(size), len(vm.checkpoints), tip))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inventario e poda das VMs de pesquisa iOS (dry-run por padrao).")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--vm", action="append", default=[], help="Remove a VM inteira (exige --force se tiver cadeia)")
    parser.add_argument("--superseded", action="append", default=[], help="Remove checkpoints nao-ponta da VM")
    parser.add_argument("--traces-before", default=None, help="Remove native-storage-trace-* anteriores a YYYY-MM-DD")
    parser.add_argument("--archive", type=Path, default=None, help="Comprime em .tar.gz nesse diretorio antes de remover")
    parser.add_argument("--force", action="store_true", help="Permite remover a ponta de uma cadeia")
    parser.add_argument("--apply", action="store_true", help="Efetiva a remocao (sem isso, so mostra o plano)")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        parser.error("root inexistente: %s" % args.root)

    if not (args.vm or args.superseded or args.traces_before):
        print_inventory(args.root)
        return 0

    vms = scan(args.root)
    targets = select_targets(vms, whole_vms=args.vm, superseded=args.superseded,
                             traces_before=args.traces_before, force=args.force)
    if not targets:
        print("Nenhum alvo selecionado.")
        return 0

    print("Plano (%s):" % ("APLICAR" if args.apply else "dry-run"))
    for target in targets:
        print("  - %s  (%s alocado)" % (target.relative_to(args.root), human(allocated_bytes(target))))
    result = prune(targets, args.root, apply=args.apply, archive_dir=args.archive)
    if result.applied:
        reclaimed = result.free_after - result.free_before
        print("Removido. Reclaim real (df): %s" % human(reclaimed))
        for tarball in result.archived:
            print("  arquivado: %s" % tarball)
    else:
        print("Dry-run: nada removido. Rode de novo com --apply para efetivar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
