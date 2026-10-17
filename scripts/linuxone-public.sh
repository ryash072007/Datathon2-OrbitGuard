#!/usr/bin/env bash
# Expose the OrbitGuard console (container on 127.0.0.1:8080) on the VM's public IP, and keep it exposed across reboots.
# Installs a systemd template unit orbitguard-public@<port>: it opens <port> in iptables and runs socat from
# <public-ip>:<port> to 127.0.0.1:8080. The console has no login: anyone with the URL can use it, including the
# operator Accept / Defer / Reject buttons that write to the audit log.
#
#   sudo bash scripts/linuxone-public.sh install [ports]   # default ports: 80 8080
#   sudo bash scripts/linuxone-public.sh uninstall
#   bash scripts/linuxone-public.sh status
set -euo pipefail

UNIT=/etc/systemd/system/orbitguard-public@.service
HELPER=/usr/local/sbin/orbitguard-public
UPSTREAM=127.0.0.1:8080

need_root() { [ "$(id -u)" -eq 0 ] || { echo "error: run with sudo" >&2; exit 1; }; }

install() {
  need_root
  local ports=("$@"); [ ${#ports[@]} -gt 0 ] || ports=(80 8080)
  command -v socat >/dev/null || { apt-get update -qq && apt-get install -y -qq socat; }

  cat > "$HELPER" <<EOF
#!/usr/bin/env bash
# orbitguard-public <open|close|run> <port>. Installed by scripts/linuxone-public.sh.
set -euo pipefail
action=\$1 port=\$2
case "\$action" in
  open)  iptables -C INPUT -p tcp --dport "\$port" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "\$port" -j ACCEPT ;;
  close) while iptables -D INPUT -p tcp --dport "\$port" -j ACCEPT 2>/dev/null; do :; done ;;
  run)
    # Bind the public address only: 127.0.0.1:8080 already belongs to the container's port mapping.
    ip=\$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if (\$i == "src") print \$(i + 1)}')
    [ -n "\$ip" ] || { echo "no public IPv4 address found" >&2; exit 1; }
    exec socat TCP-LISTEN:"\$port",bind="\$ip",fork,reuseaddr TCP:$UPSTREAM ;;
  *) echo "usage: \$0 <open|close|run> <port>" >&2; exit 2 ;;
esac
EOF
  chmod 755 "$HELPER"

  cat > "$UNIT" <<EOF
[Unit]
Description=Expose the OrbitGuard console on public port %i
After=network-online.target docker.service
Wants=network-online.target

[Service]
ExecStartPre=+$HELPER open %i
ExecStart=$HELPER run %i
ExecStopPost=+$HELPER close %i
Restart=always
RestartSec=5
DynamicUser=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  for port in "${ports[@]}"; do systemctl enable --now "orbitguard-public@$port"; done
  status
}

uninstall() {
  need_root
  for unit in $(systemctl list-units --all --plain --no-legend 'orbitguard-public@*' | awk '{print $1}'); do
    systemctl disable --now "$unit"
  done
  rm -f "$UNIT" "$HELPER"
  systemctl daemon-reload
  echo "removed"
}

status() {
  systemctl list-units --all --plain --no-legend 'orbitguard-public@*' || true
  ss -ltn | awk 'NR == 1 || /:(80|8080) /'
}

case "${1:-}" in
  install) shift; install "$@" ;;
  uninstall) uninstall ;;
  status) status ;;
  *) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
