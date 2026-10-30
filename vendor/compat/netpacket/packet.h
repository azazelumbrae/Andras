#pragma once
/* macOS no tiene AF_PACKET: se declara lo justo para compilar; en ejecución las
   funciones de socket de paquete fallan y el resto de técnicas siguen sirviendo. */
#include <sys/types.h>
#include <sys/socket.h>
#include <net/if.h>
#define ETH_P_IP 0x0800
#define ETH_P_IPV6 0x86DD
#define ETH_P_ARP 0x0806
#define ETH_P_ALL 0x0003
struct sockaddr_ll {
    unsigned short sll_family;
    unsigned short sll_protocol;
    int sll_ifindex;
    unsigned short sll_hatype;
    unsigned char sll_pkttype;
    unsigned char sll_halen;
    unsigned char sll_addr[8];
};
