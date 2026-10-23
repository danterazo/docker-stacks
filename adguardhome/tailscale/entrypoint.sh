#!/bin/sh
if (return 0 2>/dev/null); then
	printf 'Run this entrypoint with sh; do not source it\n' >&2
	return 1
fi
set -eu

ipv4=${TS_SERVICE_IPV4:?An IPv4 Service address is required}
ipv6=${TS_SERVICE_IPV6:?An IPv6 Service address is required}
chain=TS_AGH_SERVICE

prepare_family() {
	firewall=$1
	address=$2
	icmp=$3

	"$firewall" -w 5 -t mangle -C PREROUTING -d "$address" -j DROP 2>/dev/null ||
		"$firewall" -w 5 -t mangle -I PREROUTING 1 -d "$address" -j DROP
	"$firewall" -w 5 -t mangle -S "$chain" >/dev/null 2>&1 ||
		"$firewall" -w 5 -t mangle -N "$chain"
	"$firewall" -w 5 -t mangle -F "$chain"
	"$firewall" -w 5 -t mangle -A "$chain" -i tailscale0 -p tcp --dport 53 -j RETURN
	"$firewall" -w 5 -t mangle -A "$chain" -i tailscale0 -p udp --dport 53 -j RETURN
	"$firewall" -w 5 -t mangle -A "$chain" -i tailscale0 -p tcp --dport 3000 -j RETURN
	"$firewall" -w 5 -t mangle -A "$chain" -i tailscale0 -p "$icmp" -m conntrack --ctstate RELATED -j RETURN
	"$firewall" -w 5 -t mangle -A "$chain" -j DROP
	"$firewall" -w 5 -t mangle -C PREROUTING -d "$address" -j "$chain" 2>/dev/null ||
		"$firewall" -w 5 -t mangle -I PREROUTING 1 -d "$address" -j "$chain"
	"$firewall" -w 5 -t mangle -D PREROUTING -d "$address" -j DROP
}

prepare_family iptables "$ipv4/32" icmp
prepare_family ip6tables "$ipv6/128" ipv6-icmp

if ! ip -4 address show dev lo | grep -Fq "inet $ipv4/32 "; then
	ip address add "$ipv4/32" dev lo
fi
if ! ip -6 address show dev lo | grep -Fq "inet6 $ipv6/128 "; then
	ip address add "$ipv6/128" dev lo
fi

exec /usr/local/bin/containerboot "$@"
