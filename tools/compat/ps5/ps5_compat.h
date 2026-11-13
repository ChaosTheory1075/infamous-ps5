/* Force-included (-include) when ps3recomp is built for the PS5 (x86_64-sie-ps5, payload SDK libc,
 * FreeBSD-derived). Fills the few POSIX/Linux names the runtime uses that the SDK lacks. */
#pragma once

#include <sys/types.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <signal.h>
#include <time.h>

/* FreeBSD dropped MAP_NORESERVE (MAP_RESERVED0040); its anonymous mappings never reserve swap. */
#ifndef MAP_NORESERVE
#define MAP_NORESERVE 0
#endif

/* win32_compat.c parks threads for SuspendThread with this signal (Linux: SIGRTMIN + 4). */
#ifndef PS3_SUSPEND_SIGNAL
#define PS3_SUSPEND_SIGNAL (SIGRTMIN + 4)
#endif

/* C11 timespec_get. */
#ifndef TIME_UTC
#define TIME_UTC 1
static inline int timespec_get(struct timespec* ts, int base)
{
    if (base != TIME_UTC) return 0;
    return clock_gettime(CLOCK_REALTIME, ts) == 0 ? base : 0;
}
#endif

/* spu_context.h's SPU_SETJMP / SPU_LONGJMP on the PS5 (ps5_shims.c: no signal-mask save). */
#ifdef __cplusplus
extern "C" {
#endif
int  ps5_setjmp(void* env) __attribute__((returns_twice));
void ps5_longjmp(void* env, int v) __attribute__((noreturn));
#ifdef __cplusplus
}
#endif
