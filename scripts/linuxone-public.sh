#!/usr/bin/env bash
# Expose the OrbitGuard console (container on 127.0.0.1:8080) on the VM's public IP, and keep it exposed across reboots.
# Installs a systemd template unit orbitguard-public@<port>: it opens <port> in iptables and runs socat from
# <public-ip>:<port> to 127.0.0.1:8080. The console has no login: anyone with the URL can use it, including the
# operator Accept / Defer / Reject buttons that write to the audit log.
#
#   sudo bash scripts/linuxone-public.sh install [ports]   # default ports: 80 8080
#   sudo bash scripts/linuxone-public.sh https             # HTTPS on 443 with a Let's Encrypt IP certificate
#   sudo bash scripts/linuxone-public.sh uninstall
#   bash scripts/linuxone-public.sh status
set -euo pipefail

UNIT=/etc/systemd/system/orbitguard-public@.service
HELPER=/usr/local/sbin/orbitguard-public
UPSTREAM=127.0.0.1:8080
TLS_DIR=/etc/orbitguard-tls
TLS_UNIT=/etc/systemd/system/orbitguard-tls.service
RENEW_UNIT=/etc/systemd/system/orbitguard-tls-renew.service
RENEW_TIMER=/etc/systemd/system/orbitguard-tls-renew.timer

public_ip() { ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}'; }

# Browsers try https:// first for a typed address, so port 80 alone fails for most visitors. Let's Encrypt issues
# short-lived (about 6 day) certificates for bare IP addresses; the challenge runs over TLS-ALPN on port 443, so the
# HTTPS proxy is stopped for a few seconds at each renewal (every 12 h check, renews when under 4 days remain).
https() {
  need_root
  local ip; ip=$(public_ip); [ -n "$ip" ] || { echo "error: no public IPv4 address" >&2; exit 1; }
  if [ ! -x /usr/local/bin/lego ]; then
    # lego publishes no s390x binary and Ubuntu's 4.9 predates IP certificates, so build it in the official
    # Go image (multi-arch, includes s390x).
    docker run --rm -v /usr/local/bin:/out -e GOBIN=/out -e CGO_ENABLED=0 golang:1.25 \
      go install -ldflags="-s -w" github.com/go-acme/lego/v4/cmd/lego@v4.35.2
  fi
  iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
  systemctl stop orbitguard-tls 2>/dev/null || true
  lego --accept-tos --disable-cn --path "$TLS_DIR" --domains "$ip" --tls --tls.port :443 run --profile shortlived

  cat > "$TLS_UNIT" <<EOF
[Unit]
Description=OrbitGuard console over HTTPS on $ip:443
After=network-online.target docker.service
Wants=network-online.target

[Service]
ExecStartPre=/bin/sh -c 'iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT'
ExecStart=/usr/bin/socat OPENSSL-LISTEN:443,bind=$ip,fork,reuseaddr,verify=0,cert=$TLS_DIR/certificates/$ip.crt,key=$TLS_DIR/certificates/$ip.key TCP:$UPSTREAM
Restart=always
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF
  cat > "$RENEW_UNIT" <<EOF
[Unit]
Description=Renew the OrbitGuard Let's Encrypt IP certificate

[Service]
Type=oneshot
ExecStartPre=/bin/systemctl stop orbitguard-tls
ExecStart=/usr/local/bin/lego --accept-tos --disable-cn --path $TLS_DIR --domains $ip --tls --tls.port :443 renew --days 4 --profile shortlived
ExecStopPost=/bin/systemctl start orbitguard-tls
EOF
  cat > "$RENEW_TIMER" <<EOF
[Unit]
Description=Check the OrbitGuard certificate twice a day

[Timer]
OnBootSec=5min
OnUnitActiveSec=12h
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now orbitguard-tls orbitguard-tls-renew.timer
  status
  echo "open https://$ip"
}

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
  systemctl disable --now orbitguard-tls orbitguard-tls-renew.timer 2>/dev/null || true
  while iptables -D INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; do :; done
  rm -f "$UNIT" "$HELPER" "$TLS_UNIT" "$RENEW_UNIT" "$RENEW_TIMER"
  systemctl daemon-reload
  echo "removed"
}

status() {
  systemctl list-units --all --plain --no-legend 'orbitguard-public@*' 'orbitguard-tls*' || true
  ss -ltn | awk 'NR == 1 || /:(80|443|8080) /'
}

case "${1:-}" in
  install) shift; install "$@" ;;
  https) https ;;
  uninstall) uninstall ;;
  status) status ;;
  *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
