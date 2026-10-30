#pragma once
#include <sys/socket.h>
#include <stdint.h>
#define NETLINK_ROUTE 0
#define NETLINK_NETFILTER 12
#ifndef AF_NETLINK
#define AF_NETLINK 30
#define PF_NETLINK AF_NETLINK
#endif
#ifndef AF_PACKET
#define AF_PACKET 17
#define PF_PACKET AF_PACKET
#endif
struct sockaddr_nl {
    unsigned short nl_family;
    unsigned short nl_pad;
    uint32_t nl_pid;
    uint32_t nl_groups;
};
