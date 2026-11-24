/*
 * ps3recomp - a small DNS client for the UGC path (PS3_UGC_ONLINE only).
 *
 * The PS5 has no getaddrinfo/gethostbyname (the static libc copy reads no
 * resolv.conf), so in UGC mode a name that the PS3_UGC_SERVER override does
 * not cover (today the mission-file host r2.infamousreborn.com) is resolved
 * here: one RFC 1035 A query over connected UDP to public resolvers 1.1.1.1,
 * 8.8.8.8, 9.9.9.9 in turn (2.5 s each, 2 tries), first A record of the
 * answer (resolvers return the CNAME chain with its A records, so CNAMEs are
 * followed), results cached for the session. Ported from the launcher's
 * update downloader (tools/ps5/launcher/installer.c updl_dns), which already
 * uses only imports the PS5 build has: socket, fcntl, connect, poll, send,
 * read, close, setsockopt.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#ifndef _WIN32
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <fcntl.h>
#  include <errno.h>
#  include <poll.h>
#  include <pthread.h>
#endif

int ugc_dns_resolve(const char* name, uint8_t ip[4]);

#ifdef _WIN32
int ugc_dns_resolve(const char* name, uint8_t ip[4]) { (void)name; (void)ip; return -1; }
#else

#define UGC_DNS_TIMEOUT_MS 2500

static int dns_wait(int s, short ev, int ms)
{
    struct pollfd p = { s, ev, 0 };
    return poll(&p, 1, ms) == 1 && (p.revents & (ev | POLLHUP | POLLERR));
}

/* Connected UDP socket to server:53 (host-order address); -1 on failure. */
static int dns_socket(uint32_t server)
{
    const int s = socket(AF_INET, SOCK_DGRAM, 0);
    if (s < 0) return -1;
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_port = htons(53); sa.sin_addr.s_addr = htonl(server);
    if (connect(s, (struct sockaddr*)&sa, sizeof sa)) { close(s); return -1; }
    return s;
}

/* One A query of name to server; the first A record of the answer, 0 none. */
static uint32_t dns_query(uint32_t server, const char* name)
{
    uint8_t q[300], a[1500]; size_t n = 12;
    static uint16_t seq; const uint16_t id = (uint16_t)((uint32_t)time(NULL) * 2654435761u + ++seq * 40503u);
    memset(q, 0, 12); q[0] = (uint8_t)(id >> 8); q[1] = (uint8_t)id; q[2] = 0x01; q[5] = 1;   /* RD, one question */
    for (const char* p = name; *p; ) {
        const char* e = strchr(p, '.'); const size_t l = e ? (size_t)(e - p) : strlen(p);
        if (l == 0 || l > 63 || n + l + 6 > sizeof q) return 0;
        q[n++] = (uint8_t)l; memcpy(q + n, p, l); n += l; p += l; if (*p == '.') p++;
    }
    q[n++] = 0; q[n++] = 0; q[n++] = 1; q[n++] = 0; q[n++] = 1;   /* QTYPE A, QCLASS IN */
    for (int tries = 0; tries < 2; tries++) {
        const int s = dns_socket(server);
        if (s < 0) return 0;
        ssize_t got = -1;
        if (send(s, q, n, 0) == (ssize_t)n && dns_wait(s, POLLIN, UGC_DNS_TIMEOUT_MS)) got = read(s, a, sizeof a);
        close(s);
        if (got < 12 || a[0] != q[0] || a[1] != q[1] || !(a[2] & 0x80) || (a[3] & 0x0F)) continue;
        const int qd = a[4] << 8 | a[5], an = a[6] << 8 | a[7];
        size_t at = 12;
        for (int i = 0; i < qd + an; i++) {
            while (at < (size_t)got && a[at] && (a[at] & 0xC0) != 0xC0) at += a[at] + 1u;   /* the name */
            at += at < (size_t)got && a[at] ? 2 : 1;
            if (i < qd) { at += 4; continue; }
            if (at + 10 > (size_t)got) break;
            const int type = a[at] << 8 | a[at + 1], cls = a[at + 2] << 8 | a[at + 3], rl = a[at + 8] << 8 | a[at + 9];
            at += 10;
            if (at + (size_t)rl > (size_t)got) break;
            if (type == 1 && cls == 1 && rl == 4) return (uint32_t)a[at] << 24 | a[at + 1] << 16 | a[at + 2] << 8 | a[at + 3];
            at += (size_t)rl;   /* CNAME etc.: the A record of its target follows in the same answer */
        }
        return 0;
    }
    return 0;
}

/* Session cache. */
#define UGC_DNS_CACHE 16
static struct { char name[128]; uint32_t ip; } s_cache[UGC_DNS_CACHE];
static int s_ncache;
static pthread_mutex_t s_lock = PTHREAD_MUTEX_INITIALIZER;

/* 0 and ip[] (network order bytes) on success, -1 if no resolver answered. */
int ugc_dns_resolve(const char* name, uint8_t ip[4])
{
    static const uint32_t kResolvers[] = { 0x01010101u, 0x08080808u, 0x09090909u };   /* 1.1.1.1 8.8.8.8 9.9.9.9 */
    static const char* const kNames[] = { "1.1.1.1", "8.8.8.8", "9.9.9.9" };
    if (!name || !*name || strlen(name) >= 128) return -1;
    uint32_t v = 0; int i;
    pthread_mutex_lock(&s_lock);
    for (i = 0; i < s_ncache; i++) if (!strcmp(s_cache[i].name, name)) { v = s_cache[i].ip; break; }
    pthread_mutex_unlock(&s_lock);
    if (!v) {
        for (i = 0; i < 3 && !v; i++) {
            v = dns_query(kResolvers[i], name);
            if (v) printf("[ugc dns] %s -> %u.%u.%u.%u (resolver %s)\n", name,
                          v >> 24, (v >> 16) & 255, (v >> 8) & 255, v & 255, kNames[i]);
        }
        if (!v) { printf("[ugc dns] %s -> no answer from 1.1.1.1, 8.8.8.8, 9.9.9.9\n", name); return -1; }
        pthread_mutex_lock(&s_lock);
        if (s_ncache < UGC_DNS_CACHE) { strcpy(s_cache[s_ncache].name, name); s_cache[s_ncache].ip = v; s_ncache++; }
        pthread_mutex_unlock(&s_lock);
    }
    ip[0] = (uint8_t)(v >> 24); ip[1] = (uint8_t)(v >> 16); ip[2] = (uint8_t)(v >> 8); ip[3] = (uint8_t)v;
    return 0;
}
#endif
