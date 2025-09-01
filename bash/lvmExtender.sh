#!/usr/bin/env bash
# LVM Root Resizer
# Works on systems with LVM root after hypervisor disk expansion.

set -Eeuo pipefail

TITLE="LVM Root Resizer"
LOG="/var/log/lvm-terminal-resizer.log"
ALTLOG="$HOME/.lvm-terminal-resizer.log"
ASSUME_YES=0
DRY_RUN=0

if [[ -t 1 ]]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
  BLUE=$'\e[34m'; MAGENTA=$'\e[35m'; CYAN=$'\e[36m'; RESET=$'\e[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; MAGENTA=""; CYAN=""; RESET=""
fi

have() { command -v "$1" >/dev/null 2>&1; }

log_init() {
  if ! touch "$LOG" 2>/dev/null; then
    LOG="$ALTLOG"
    touch "$LOG" 2>/dev/null || true
  fi
}

ts() { date -Iseconds; }
log() { printf '%s | %s\n' "$(ts)" "$*" | tee -a "$LOG" >/dev/null; }
say() { printf '%s\n' "$*" | tee -a "$LOG" >&2; }
ok()  { say "${GREEN}✔${RESET} $*"; }
warn(){ say "${YELLOW}⚠${RESET} $*"; }
err() { say "${RED}✖${RESET} $*"; }

die() { err "$*"; exit 1; }

usage() {
  cat <<EOF
$TITLE
Usage: sudo $0 [--dry-run] [--assume-yes]

  --dry-run       Plan & validate only
  --assume-yes    Skip interactive approval (Bruh LGTM).

This tool:
  1) rescans the disk
  2) grows the PV partition to 100% (growpart/parted)
  3) pvresize
  4) lvextend +100%FREE on the root LV
  5) grows the filesystem (ext*/xfs/btrfs)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1;;
    --assume-yes) ASSUME_YES=1;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $arg";;
  esac
done

log_init
trap 'err "An error occurred. Check log: $LOG"' ERR

[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Must run as root. Try: sudo $0"

need_tools=(lsblk findmnt lvs pvs vgs pvresize lvextend df)
missing=()
for t in "${need_tools[@]}"; do have "$t" || missing+=("$t"); done
if ! have growpart && ! have parted; then missing+=("(growpart or parted)"); fi
[[ ${#missing[@]} -eq 0 ]] || die "Missing tools: ${missing[*]}
Ubuntu quick fix:
  apt-get update && apt-get install -y lvm2 cloud-guest-utils parted"

say "${BOLD}${CYAN}$TITLE${RESET}"
say "Log: $LOG"
say

ROOT_SRC="$(findmnt -no SOURCE / || true)"
ROOT_FS="$(findmnt -no FSTYPE / || true)"
[[ -n "$ROOT_SRC" ]] || die "Cannot detect / mount source"
[[ "$ROOT_SRC" == /dev/mapper/* || "$ROOT_SRC" == /dev/*/*-* ]] || die "Root is not on LVM: $ROOT_SRC"

read -r VG LV <<<"$(lvs --noheadings -o vg_name,lv_name "$ROOT_SRC" | awk '{$1=$1;print}')"
[[ -n "${VG:-}" && -n "${LV:-}" ]] || die "Failed to detect VG/LV for $ROOT_SRC"
LV_PATH="/dev/$VG/$LV"

mapfile -t PV_LIST < <(pvs --noheadings -o pv_name -S "vg_name=$VG" | awk '{$1=$1;print}')
[[ ${#PV_LIST[@]} -gt 0 ]] || die "No PVs found in VG $VG"

if [[ ${#PV_LIST[@]} -gt 1 ]]; then
  say "${YELLOW}Multiple PVs detected in VG $VG:${RESET}"
  printf '  - %s\n' "${PV_LIST[@]}"
  say
  ROOT_DISK="$(lsblk -no PKNAME "$ROOT_SRC" 2>/dev/null || true)"
  ROOT_DISK="/dev/${ROOT_DISK:-}"
  CHOSEN=""
  for pv in "${PV_LIST[@]}"; do
    PK="$(lsblk -no PKNAME "$pv" 2>/dev/null || true)"
    [[ "/dev/${PK:-}" == "$ROOT_DISK" ]] && CHOSEN="$pv" && break
  done
  PV="${CHOSEN:-${PV_LIST[0]}}"
  warn "Defaulting to PV: $PV"
else
  PV="${PV_LIST[0]}"
fi

DISK=""; PART=""
if [[ "$PV" =~ ^/dev/(nvme[0-9]+n[0-9]+)p([0-9]+)$ ]]; then
  DISK="/dev/${BASH_REMATCH[1]}"; PART="${BASH_REMATCH[2]}"
elif [[ "$PV" =~ ^/dev/([a-zA-Z]+)([0-9]+)$ ]]; then
  DISK="/dev/${BASH_REMATCH[1]}"; PART="${BASH_REMATCH[2]}"
elif [[ "$PV" =~ ^/dev/(sd[a-z]+)$ ]]; then
  DISK="/dev/${BASH_REMATCH[1]}"; PART=""
else
  DISK="$(lsblk -no PKNAME "$PV" 2>/dev/null || true)"
  [[ -n "$DISK" ]] && DISK="/dev/$DISK"
fi
[[ -n "$DISK" ]] || die "Cannot resolve backing disk for PV $PV"

numfmt_wrap(){ numfmt --to=iec "${1:-0}" 2>/dev/null || echo "${1:-0}B"; }
DISK_SIZE_B="$(lsblk -bno SIZE "$DISK")"
PV_SIZE_B="$(lsblk -bno SIZE "$PV")"
VG_FREE_B="$(vgs --noheadings -o vg_free --units b "$VG" | tr -dc '0-9')"
DF_ROOT="$(df -h / | awk 'NR==1; NR==2')"

cat <<EOF | tee -a "$LOG"
${BOLD}Detected layout:${RESET}
  Root mount     : /
  Root device    : $ROOT_SRC
  Filesystem     : $ROOT_FS
  VG / LV        : $VG / $LV
  LV path        : $LV_PATH
  PV             : $PV
  Disk           : $DISK ${PART:+(partition $PART)}

${BOLD}Sizes (before):${RESET}
  Disk size      : $(numfmt_wrap "$DISK_SIZE_B")
  PV size        : $(numfmt_wrap "$PV_SIZE_B")
  VG free        : $(numfmt_wrap "$VG_FREE_B")
  df -h /        : $DF_ROOT

${BOLD}Actions:${RESET}
  1) Rescan $DISK so the kernel sees new capacity
  2) Grow ${PART:+partition ${PART} on }$DISK to 100% (using $(have growpart && echo growpart || echo parted))
  3) pvresize $PV
  4) lvextend -l +100%FREE $LV_PATH
  5) Grow filesystem on /
EOF

if (( DRY_RUN )); then
  ok "Dry run: no changes will be made."
  exit 0
fi

if (( ! ASSUME_YES )); then
  say
  read -rp "$(printf "%s" "${BOLD}Type 'proceed' to continue, anything else to abort: ${RESET}")" CONFIRM
  [[ "$CONFIRM" == "proceed" ]] || die "User aborted."
fi

say
say "${BOLD}${BLUE}Step 1/5:${RESET} Rescan $DISK"
if [[ -e "/sys/class/block/$(basename "$DISK")/device/rescan" ]]; then
  echo 1 >"/sys/class/block/$(basename "$DISK")/device/rescan" || true
fi
have blockdev && blockdev --rereadpt "$DISK" || true
ok "Rescan attempted."

if [[ -n "${PART:-}" ]]; then
  say
  say "${BOLD}${BLUE}Step 2/5:${RESET} Grow partition $PART on $DISK to 100%"
  if have growpart; then
    log "growpart $DISK $PART"
    growpart "$DISK" "$PART"
  else
    partprobe "$DISK" || true
    PARTDEV="$PV"
    log "parted -s $DISK unit % print"
    parted -s "$DISK" unit % print >/dev/null
    log "parted -s $DISK resizepart $PART 100%"
    parted -s "$DISK" resizepart "$PART" 100%
    partprobe "$DISK" || true
  fi
  ok "Partition grown."
else
  warn "PV appears to be whole-disk; skipping partition resize."
fi

say
say "${BOLD}${BLUE}Step 3/5:${RESET} pvresize $PV"
log "pvresize $PV"
pvresize "$PV"
ok "PV resized."

say
say "${BOLD}${BLUE}Step 4/5:${RESET} lvextend +100%FREE on $LV_PATH"
log "lvextend -l +100%FREE -r? (fs grow handled next)"
lvextend -l +100%FREE "$LV_PATH"
ok "LV extended."

say
say "${BOLD}${BLUE}Step 5/5:${RESET} Grow filesystem on / ($ROOT_FS)"
case "$ROOT_FS" in
  ext2|ext3|ext4)
    log "resize2fs $LV_PATH"
    resize2fs "$LV_PATH"
    ;;
  xfs)
    have xfs_growfs || die "xfs_growfs not found. Install xfsprogs."
    log "xfs_growfs /"
    xfs_growfs /
    ;;
  btrfs)
    have btrfs || die "btrfs tool not found."
    log "btrfs filesystem resize max /"
    btrfs filesystem resize max /
    ;;
  *)
    die "Unsupported filesystem: $ROOT_FS. Grow it manually."
    ;;
esac
ok "Filesystem grown."

say
DF_AFTER="$(df -h / | awk 'NR==1; NR==2')"
VG_FREE_AFTER="$(vgs --noheadings -o vg_free --units b "$VG" | tr -dc '0-9')"

cat <<EOF | tee -a "$LOG"
${BOLD}${GREEN}Success!${RESET}
${BOLD}Sizes (after):${RESET}
  VG free        : $(numfmt_wrap "$VG_FREE_AFTER")
  df -h /        : $DF_AFTER

Log saved to: $LOG
EOF