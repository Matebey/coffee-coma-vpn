#!/bin/bash
CLIENT_IP="$ifconfig_pool_remote_ip"
CLIENT_NAME="$common_name"
/etc/openvpn/scripts/traffic_control.sh add-client $CLIENT_IP ${CLIENT_NAME//[^0-9]/}
echo "$(date) - Клиент $CLIENT_NAME ($CLIENT_IP) подключен" >> /var/log/openvpn-clients.log