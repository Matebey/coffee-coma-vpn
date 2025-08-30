#!/bin/bash
CLIENT_IP="$ifconfig_pool_remote_ip"
CLIENT_NAME="$common_name"
echo "$(date) - Клиент $CLIENT_NAME ($CLIENT_IP) отключен" >> /var/log/openvpn-clients.log