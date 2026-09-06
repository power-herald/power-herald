#!/bin/sh

user_id=$(id -u)
sudo sysctl net.ipv4.ping_group_range="$user_id $user_id"
