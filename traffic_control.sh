#!/bin/bash
INTERFACE="tun0"
DOWNLOAD_SPEED="10mbit"
UPLOAD_SPEED="10mbit"

clean_tc() {
    tc qdisc del dev $INTERFACE root 2>/dev/null
    tc qdisc del dev eth0 root 2>/dev/null
    tc qdisc del dev eth0 ingress 2>/dev/null
}

setup_tc() {
    clean_tc
    tc qdisc add dev $INTERFACE root handle 1: htb default 10
    tc class add dev $INTERFACE parent 1: classid 1:1 htb rate $UPLOAD_SPEED
    tc class add dev $INTERFACE parent 1:1 classid 1:10 htb rate $UPLOAD_SPEED
    tc qdisc add dev eth0 handle ffff: ingress
    tc filter add dev eth0 parent ffff: protocol ip prio 50 u32 match ip src 0.0.0.0/0 police rate $DOWNLOAD_SPEED burst 100k drop flowid :1
    echo "✅ Ограничение скорости настроено"
}

add_client_limit() {
    CLIENT_IP=$1
    CLIENT_ID=$2
    tc class add dev $INTERFACE parent 1:1 classid 1:$CLIENT_ID htb rate $UPLOAD_SPEED
    tc filter add dev $INTERFACE parent 1: protocol ip prio 1 u32 match ip src $CLIENT_IP flowid 1:$CLIENT_ID
    tc filter add dev eth0 parent ffff: protocol ip prio 1 u32 match ip dst $CLIENT_IP police rate $DOWNLOAD_SPEED burst 100k drop flowid :1
    echo "✅ Ограничение для $CLIENT_IP установлено"
}

case "$1" in
    "setup") setup_tc ;;
    "add-client") add_client_limit $2 $3 ;;
    "clean") clean_tc ;;
    *) echo "Использование: $0 {setup|add-client IP ID|clean}" ;;
esac