/*
 * ps3recomp - minimal TLS 1.2 client (UGC server), see ugc_tls.c.
 * Does NO certificate verification; authenticates nothing.
 */
#ifndef PS3RECOMP_UGC_TLS_H
#define PS3RECOMP_UGC_TLS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int      fd;
    int      ready;
    uint64_t wseq, rseq;
    uint8_t  cli_random[32], srv_random[32], master[48];
    uint8_t  cli_mac[20], srv_mac[20], cli_key[16], srv_key[16];
    uint8_t  hsbuf[16384]; int hslen;      /* handshake transcript for Finished */
    uint8_t  rec[20000];   int reclen;     /* last record plaintext */
    uint8_t  recbuf[20000]; int recoff, pend;  /* buffered app data for ugc_tls_read */
} ugc_tls;

/* Handshake over an already-connected TCP socket `fd`, SNI = `sni`.
 * 0 on success; negative on failure (-2 alert, -3 no cert key, others internal). */
int  ugc_tls_connect(ugc_tls* t, int fd, const char* sni);
int  ugc_tls_write(ugc_tls* t, const void* buf, int len);   /* app data out */
int  ugc_tls_read (ugc_tls* t, void* buf, int len);         /* app data in; 0 = closed */
void ugc_tls_close(ugc_tls* t);

#ifdef __cplusplus
}
#endif

#endif
