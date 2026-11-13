/* libc pieces the PS5 payload SDK's libc lacks, linked into the inFamous 2 eboot (ps5link.sh). */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* ps5_setjmp / ps5_longjmp: the SPU runtime's non-local exits (spu_context.h SPU_SETJMP). Plain
 * control flow, never across a signal handler, so no signal mask: callee-saved registers, the
 * stack, the return address, MXCSR and the x87 control word. Buffer layout (64-bit words):
 * rbx rbp r12 r13 r14 r15 rsp rip | mxcsr fpucw. */
__asm__(
    ".text\n"
    ".globl ps5_setjmp\n"
    ".type ps5_setjmp,@function\n"
    "ps5_setjmp:\n"
    "    movq (%rsp), %rdx\n"
    "    movq %rbx, 0(%rdi)\n"
    "    movq %rbp, 8(%rdi)\n"
    "    movq %r12, 16(%rdi)\n"
    "    movq %r13, 24(%rdi)\n"
    "    movq %r14, 32(%rdi)\n"
    "    movq %r15, 40(%rdi)\n"
    "    leaq 8(%rsp), %rcx\n"
    "    movq %rcx, 48(%rdi)\n"
    "    movq %rdx, 56(%rdi)\n"
    "    stmxcsr 64(%rdi)\n"
    "    fnstcw 68(%rdi)\n"
    "    xorl %eax, %eax\n"
    "    ret\n"
    ".size ps5_setjmp, .-ps5_setjmp\n"
    ".globl ps5_longjmp\n"
    ".type ps5_longjmp,@function\n"
    "ps5_longjmp:\n"
    "    movl %esi, %eax\n"
    "    testl %eax, %eax\n"
    "    jnz 1f\n"
    "    incl %eax\n"
    "1:  movq 0(%rdi), %rbx\n"
    "    movq 8(%rdi), %rbp\n"
    "    movq 16(%rdi), %r12\n"
    "    movq 24(%rdi), %r13\n"
    "    movq 32(%rdi), %r14\n"
    "    movq 40(%rdi), %r15\n"
    "    ldmxcsr 64(%rdi)\n"
    "    fldcw 68(%rdi)\n"
    "    movq 48(%rdi), %rsp\n"
    "    jmpq *56(%rdi)\n"
    ".size ps5_longjmp, .-ps5_longjmp\n");

/* cellRtc: UTC broken-down time to time_t (days-from-civil, no time zone involved). */
time_t timegm(struct tm* t)
{
    int64_t y = (int64_t)t->tm_year + 1900;
    int64_t m = t->tm_mon + 1;
    y -= m <= 2;
    const int64_t era = (y >= 0 ? y : y - 399) / 400;
    const int64_t yoe = y - era * 400;
    const int64_t doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + t->tm_mday - 1;
    const int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    const int64_t days = era * 146097 + doe - 719468;
    return (time_t)(days * 86400 + (int64_t)t->tm_hour * 3600 + t->tm_min * 60 + t->tm_sec);
}

/* ppu_fs: an anonymous scratch file. /data is the writable place for homebrew. */
FILE* tmpfile(void)
{
    static unsigned counter;
    char path[96];
    for (int tries = 0; tries < 64; tries++) {
        snprintf(path, sizeof path, "/data/ps3recomp-tmp-%d-%u", (int)getpid(),
                 __atomic_fetch_add(&counter, 1, __ATOMIC_RELAXED));
        int fd = open(path, O_RDWR | O_CREAT | O_EXCL, 0600);
        if (fd < 0) {
            if (errno == EEXIST) continue;
            return NULL;
        }
        unlink(path);
        FILE* f = fdopen(fd, "w+b");
        if (!f) close(fd);
        return f;
    }
    return NULL;
}

/* Thread stacks out of direct memory (linked with --wrap=pthread_attr_setstacksize). ps3recomp
 * asks 256 MB per guest PPU thread and 16 MB per SPU thread, which an OS reserving lazily shrugs
 * off; on the PS5 thread stacks would come out of the ~512 MB flexible-memory budget and, refused,
 * fall back to the small default stack that deep lifted code overflows. Here every requested stack
 * is CPU direct memory of the asked size, capped at PS5_STACK_CAP_MB (default 64), set with
 * pthread_attr_setstack. Stacks are not given back: guest threads are mostly created at boot. */
#include <pthread.h>
#include <ps5platform/kernel.h>
int __real_pthread_attr_setstacksize(pthread_attr_t* attr, size_t size);
int __wrap_pthread_attr_setstacksize(pthread_attr_t* attr, size_t size)
{
    static size_t cap;
    if (!cap) {
        const char* e = getenv("PS5_STACK_CAP_MB");
        cap = (size_t)(e && atoi(e) > 0 ? atoi(e) : 64) << 20;
    }
    if (size > cap) size = cap;
    size = (size + PS5_KERNEL_DIRECT_ALIGNMENT - 1) & ~(PS5_KERNEL_DIRECT_ALIGNMENT - 1);
    if (size < (256u << 10)) return __real_pthread_attr_setstacksize(attr, size);
    int64_t phys = 0;
    if (sceKernelAllocateDirectMemory(0, sceKernelGetDirectMemorySize(), size, PS5_KERNEL_DIRECT_ALIGNMENT,
                                      PS5_KERNEL_DIRECT_TYPE_CPU, &phys) < 0)
        return __real_pthread_attr_setstacksize(attr, size);
    /* Placed with a hint, never inside the GPU window (0x200000000-0x300000000): an unhinted direct
     * map lands there (the SDK's console probe: 0x200020000), where RADV maps its own memory at fixed
     * addresses over whatever is in the way. The console runs died as the second guest thread was
     * created. Hints from 256 GB up (the guest block sits at 64 GB, the heap near 128 GB). */
    static uintptr_t next = 0x4000000000ull;
    static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
    void* at = NULL;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < 64 && !at; i++) {
        void* want = (void*)next;
        if (sceKernelMapDirectMemory(&want, size, PS5_KERNEL_PROT_CPU_READ | PS5_KERNEL_PROT_CPU_WRITE, 0, phys,
                                     PS5_KERNEL_DIRECT_ALIGNMENT) < 0 || !want) {
            next += (uintptr_t)1 << 30;
            continue;
        }
        const uintptr_t w = (uintptr_t)want;
        if (w < 0x300000000ull && w + size > 0x200000000ull) {   /* in the GPU window: not there */
            sceKernelMunmap(want, size);
            next += (uintptr_t)1 << 30;
            continue;
        }
        at = want;
        next = w + size + PS5_KERNEL_DIRECT_ALIGNMENT;          /* a gap: an unmapped page between stacks */
    }
    pthread_mutex_unlock(&lock);
    if (!at) {
        sceKernelReleaseDirectMemory(phys, size);
        return __real_pthread_attr_setstacksize(attr, size);
    }
    fprintf(stderr, "[ps5] thread stack %zu MB at %p\n", size >> 20, at);
    return pthread_attr_setstack(attr, at, size);
}

/* Short sleeps (linked with --wrap=usleep --wrap=nanosleep). On the console a usleep(3) took 1-3 ms
 * (the tenth run's log: the game's sys_timer_usleep(3) poll loop, ~1.1-2.9 ms apart), where Linux
 * returns in tens of microseconds; the game and the runtime poll with such sleeps everywhere
 * (GCM labels, SPU channels, the game's own spin-waits). Under 2 ms the deadline is met by yielding
 * in a loop instead; longer sleeps go to the system. ps5_sleep_probe logs the real timings. */
#include <sched.h>
int __real_usleep(useconds_t us);
int __real_nanosleep(const struct timespec* req, struct timespec* rem);
int __real_sched_yield(void);
static uint64_t ps5_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}
/* Spinning was the wrong answer: the thirteenth console run's profile had 52-73% of all samples in
 * sched_yield, called from this spin, in all three games -- the guest's many short polls kept
 * cores busy that the real work needed, and it ran slower than with plain sleeps. A system sleep
 * of ~100 us costs a waiting thread nothing; only a zero-length sleep yields. PS5_SPIN_SLEEPS=1
 * brings the spin back (under 2 ms) for comparison. */
static int spin_sleeps(void)
{
    static int s = -1;
    if (s < 0) { const char* e = getenv("PS5_SPIN_SLEEPS"); s = e && *e == '1'; }
    return s;
}
static void ps5_spin_until(uint64_t deadline)
{
    while (ps5_now_ns() < deadline) __real_sched_yield();
}
#define PS5_SPIN_BELOW_NS 2000000ull
enum { WP_USLEEP, WP_NANOSLEEP, WP_YIELD, WP_COND, WP_CONDT, WP_MUTEX, WP_SEM, WP_KINDS };
static int s_wp_on = 1;
static void wp_note(int kind, uintptr_t ra, uint64_t ns);
int __wrap_usleep(useconds_t us)
{
    const uint64_t t0 = s_wp_on ? ps5_now_ns() : 0;
    int r = 0;
    if (us == 0) __real_sched_yield();
    else if (spin_sleeps() && (uint64_t)us * 1000ull < PS5_SPIN_BELOW_NS) ps5_spin_until(ps5_now_ns() + (uint64_t)us * 1000ull);
    else r = __real_usleep(us);
    if (t0) wp_note(us ? WP_USLEEP : WP_YIELD, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
int __wrap_nanosleep(const struct timespec* req, struct timespec* rem)
{
    const uint64_t t0 = s_wp_on ? ps5_now_ns() : 0;
    int r = 0, kind = WP_NANOSLEEP;
    if (req && req->tv_sec == 0 && req->tv_nsec == 0) { __real_sched_yield(); kind = WP_YIELD; }
    else if (spin_sleeps() && req && req->tv_sec == 0 && req->tv_nsec > 0 && (uint64_t)req->tv_nsec < PS5_SPIN_BELOW_NS) {
        ps5_spin_until(ps5_now_ns() + (uint64_t)req->tv_nsec);
        if (rem) rem->tv_sec = rem->tv_nsec = 0;
    } else r = __real_nanosleep(req, rem);
    if (t0) wp_note(kind, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
/* Yields (linked with --wrap=sched_yield): the runtime's spin-waits (sys_ppu_thread_yield, cellSync,
 * the event and timer polls, RADV) call it directly, and the profile showed a thread at ~0.9 cores
 * almost all inside the system library with no wait of any kind noted: a yield loop shows up as
 * kernel time. Each yield is noted with its call site, as "yield" in the [wait] lines. */
int __wrap_sched_yield(void)
{
    if (!s_wp_on) return __real_sched_yield();
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_sched_yield();
    wp_note(WP_YIELD, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
/* Condition-variable hand-off latency: two threads ping-pong 2000 times; half a round trip is what
 * one wait-and-wake costs (the runtime's PPU/SPU hand-offs are such waits). */
int __real_pthread_cond_wait(pthread_cond_t* c, pthread_mutex_t* m);
static pthread_mutex_t s_pp_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t s_pp_cv = PTHREAD_COND_INITIALIZER;
static volatile int s_pp_turn, s_pp_stop;
static void* pp_thread(void* a)
{
    (void)a;
    pthread_mutex_lock(&s_pp_mu);
    while (!s_pp_stop) {
        while (s_pp_turn != 1 && !s_pp_stop) __real_pthread_cond_wait(&s_pp_cv, &s_pp_mu);
        s_pp_turn = 0;
        pthread_cond_broadcast(&s_pp_cv);
    }
    pthread_mutex_unlock(&s_pp_mu);
    return NULL;
}
static void ps5_wake_probe(void)
{
    pthread_t t;
    if (pthread_create(&t, NULL, pp_thread, NULL) != 0) return;
    const uint64_t t0 = ps5_now_ns();
    pthread_mutex_lock(&s_pp_mu);
    for (int k = 0; k < 2000; k++) {
        s_pp_turn = 1;
        pthread_cond_broadcast(&s_pp_cv);
        while (s_pp_turn != 0) __real_pthread_cond_wait(&s_pp_cv, &s_pp_mu);
    }
    s_pp_stop = 1;
    pthread_cond_broadcast(&s_pp_cv);
    pthread_mutex_unlock(&s_pp_mu);
    pthread_join(t, NULL);
    printf("[ps5] condition-variable wake: %.1f us per hand-off (2000 round trips)\n",
           (double)(ps5_now_ns() - t0) / 4000.0 / 1000.0);
}

/* The console's own sleep timings, for the log: average of 20 real usleeps of each length. */
void ps5_sleep_probe(void)
{
    ps5_wake_probe();
    static const unsigned lens[] = { 3, 100, 1000, 5000 };
    for (unsigned i = 0; i < sizeof lens / sizeof lens[0]; i++) {
        const uint64_t t0 = ps5_now_ns();
        for (int k = 0; k < 20; k++) __real_usleep(lens[i]);
        printf("[ps5] system usleep(%u us) takes %.0f us\n", lens[i], (double)(ps5_now_ns() - t0) / 20000.0);
    }
    const uint64_t t0 = ps5_now_ns();
    for (int k = 0; k < 1000; k++) __real_sched_yield();
    printf("[ps5] sched_yield takes %.1f us\n", (double)(ps5_now_ns() - t0) / 1000000.0);
    /* The renderer and the trace read CLOCK_MONOTONIC several times a draw (ps3_ft_now). */
    struct timespec ts;
    const uint64_t c0 = ps5_now_ns();
    for (int k = 0; k < 10000; k++) clock_gettime(CLOCK_MONOTONIC, &ts);
    printf("[ps5] clock_gettime(CLOCK_MONOTONIC) takes %.0f ns\n", (double)(ps5_now_ns() - c0) / 10000.0);
}

/* Clock reads (linked with --wrap=clock_gettime). The runtime reads the clock in ~140 places, many
 * of them hot (GetTickCount64 / QueryPerformanceCounter / ps3_qpc_us all end here); on Linux that
 * is a vDSO read of a few ns. ps5_clock_probe times the console's clock_gettime and, when it costs
 * more than 150 ns a call, turns the monotonic and real-time clocks into TSC arithmetic
 * (sceKernelReadTsc / sceKernelGetTscFrequency) from one real reading of each. PS5_FAST_CLOCK=0
 * keeps the system's, =1 forces the TSC. */
#include <ps5platform/kernel.h>
int __real_clock_gettime(clockid_t id, struct timespec* ts);
/* Only the monotonic clocks, and each thread re-reads the system's every 16 ms and goes on from
 * there, so the TSC's arithmetic cannot drift from the kernel's (the thirteenth run took the
 * real-time clock too, from one reading at start: deadlines handed to pthread_cond_timedwait are
 * real-time and the kernel compares them with its own, so any drift lengthens every timed wait).
 * The real-time clock is always the system's. */
static int s_fast_clock;
static uint64_t s_tsc0, s_tsc_hz, s_mono0_ns, s_real0_ns, s_resync;
static __thread struct { uint64_t tsc, ns, last; } t_clk;   /* one emulated-TLS lookup per read */
/* hidden: an SDK module references clock_gettime, and lld 18 then exported the wrapper (the PS5
 * converter refuses application exports) */
__attribute__((visibility("hidden"))) int __wrap_clock_gettime(clockid_t id, struct timespec* ts)
{
    if (s_fast_clock && ts &&
        (id == CLOCK_MONOTONIC || id == CLOCK_MONOTONIC_FAST || id == CLOCK_MONOTONIC_PRECISE ||
         id == CLOCK_UPTIME || id == CLOCK_UPTIME_FAST || id == CLOCK_UPTIME_PRECISE)) {
        const uint64_t now = sceKernelReadTsc();
        uint64_t ns;
        __typeof__(t_clk)* c = &t_clk;
        if (!c->tsc || now - c->tsc > s_resync) {
            struct timespec r;
            __real_clock_gettime(CLOCK_MONOTONIC, &r);
            c->tsc = sceKernelReadTsc();
            c->ns = ns = (uint64_t)r.tv_sec * 1000000000ull + (uint64_t)r.tv_nsec;
        } else {
            ns = c->ns + (uint64_t)(((unsigned __int128)(now - c->tsc) * 1000000000u) / s_tsc_hz);
        }
        if (ns < c->last) ns = c->last;   /* never backwards across a re-read */
        c->last = ns;
        ts->tv_sec = (time_t)(ns / 1000000000u);
        ts->tv_nsec = (long)(ns % 1000000000u);
        return 0;
    }
    return __real_clock_gettime(id, ts);
}
void ps5_clock_probe(void)
{
    struct timespec a, b, t;
    __real_clock_gettime(CLOCK_MONOTONIC, &a);
    for (int i = 0; i < 20000; i++) __real_clock_gettime(CLOCK_MONOTONIC, &t);
    __real_clock_gettime(CLOCK_MONOTONIC, &b);
    const double sys_ns = ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / 20000.0;
    s_tsc_hz = sceKernelGetTscFrequency();
    const uint64_t t0 = sceKernelReadTsc();
    volatile uint64_t sink = 0;
    for (int i = 0; i < 20000; i++) sink += sceKernelReadTsc();
    const double tsc_call_ns = s_tsc_hz ? (double)(sceKernelReadTsc() - t0) * 1e9 / s_tsc_hz / 20000.0 : -1;
    (void)sink;
    const char* e = getenv("PS5_FAST_CLOCK");
    const int want = e ? atoi(e) : (sys_ns > 150.0);
    if (want && s_tsc_hz) {
        struct timespec m, r;
        __real_clock_gettime(CLOCK_MONOTONIC, &m);
        __real_clock_gettime(CLOCK_REALTIME, &r);
        s_tsc0 = sceKernelReadTsc();
        s_mono0_ns = (uint64_t)m.tv_sec * 1000000000ull + (uint64_t)m.tv_nsec;
        s_real0_ns = (uint64_t)r.tv_sec * 1000000000ull + (uint64_t)r.tv_nsec;
        s_resync = s_tsc_hz / 64;   /* ~16 ms of ticks */
        s_fast_clock = 1;
    }
    printf("[ps5] clock_gettime takes %.0f ns, sceKernelReadTsc %.0f ns (TSC %llu Hz): %s\n", sys_ns, tsc_call_ns,
           (unsigned long long)s_tsc_hz, s_fast_clock ? "the monotonic clock now comes from the TSC (re-read every 16 ms)" : "the system's clocks kept");
}
/* Copies and locks, for the log: what the console's libc gives. */
void ps5_libc_probe(void)
{
    static char src[1 << 20], dst[1 << 20];
    memset(src, 1, sizeof src);
    struct timespec a, b;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (int i = 0; i < 64; i++) { memcpy(dst, src, sizeof src); __asm__ volatile("" ::: "memory"); }
    clock_gettime(CLOCK_MONOTONIC, &b);
    const double big = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (int i = 0; i < 200000; i++) { memcpy(dst + (i & 4095) * 128, src + (i & 2047) * 64, 128); __asm__ volatile("" ::: "memory"); }
    clock_gettime(CLOCK_MONOTONIC, &b);
    const double small = ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / 200000.0;
    pthread_mutex_t mx = PTHREAD_MUTEX_INITIALIZER;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (int i = 0; i < 200000; i++) { pthread_mutex_lock(&mx); pthread_mutex_unlock(&mx); }
    clock_gettime(CLOCK_MONOTONIC, &b);
    const double lock = ((b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec)) / 200000.0;
    printf("[ps5] memcpy 1 MB: %.1f GB/s; memcpy 128 B: %.0f ns; mutex lock+unlock: %.0f ns\n",
           64.0 / 1024.0 / big, small, lock);
}

/* ppu_loader's guest-pointer trap only reads the program break to step around it; there is no brk
 * heap on the PS5. */
void* sbrk(intptr_t increment)
{
    (void)increment;
    errno = ENOMEM;
    return (void*)-1;
}

/* Off-CPU accounting: where every host thread waits, for the "[wait]" lines. The sampling profile
 * (ps5_app.c) only sees threads on a CPU; a frame that takes 100 ms while no thread is busy for
 * 100 ms is threads waiting on each other, and this says which waits, by thread and call site.
 * Every sleep, yield, condition/semaphore wait and contended mutex lock in the eboot goes through
 * here (linked with --wrap=usleep,nanosleep,pthread_cond_wait,pthread_cond_timedwait,
 * pthread_mutex_lock,sem_wait,sem_timedwait). A thread is named by ps3_host_thread_label (the
 * runtime calls it at each PPU, SPU and SPURS thread's start), else "t<n>". PS5_WAITPROF=0 turns it
 * off. */
#include <semaphore.h>
static const char* const wp_kind_name[WP_KINDS] = { "usleep", "nanosleep", "yield", "cond", "cond_timed", "mutex", "sem" };
#define WP_THR 192
static char s_wp_name[WP_THR][28];
static uintptr_t s_wp_pthr[WP_THR];
/* The highest frame address a wrapped call of the thread has had: the profile scans its stack up to
 * this (and no further than 2 KB) for the eboot code a library sample was called from. */
static uintptr_t s_wp_stack_hi[WP_THR];
static uint32_t s_wp_nthr;
static __thread int t_wp = -1;
static int wp_slot(void)
{
    if (t_wp >= 0) return t_wp;
    uint32_t s = __atomic_fetch_add(&s_wp_nthr, 1, __ATOMIC_RELAXED);
    if (s >= WP_THR) s = WP_THR - 1;   /* the rest share the last slot */
    else { snprintf(s_wp_name[s], sizeof s_wp_name[s], "t%u", s); s_wp_pthr[s] = (uintptr_t)pthread_self(); }
    t_wp = (int)s;
    return t_wp;
}
__attribute__((weak)) void ps5_pin_self(const char* kind);   /* ps5 pin (ps5_app.c); absent in the launcher */
__attribute__((weak)) void ps5_audio_spu_prio(const char* name);
__attribute__((weak)) int ps5_pin_policy(const char* name);   /* ps5 pin (ps5_app.c, PS5_PIN); absent in the launcher */
/* ps5 pin: fn on every thread that has a slot here (labelled threads; with the wait report on, every thread that
 * waited). Returns how many. pthread_setaffinity_np looks a stale handle up in libthr's thread list first (ESRCH). */
int ps5_each_thread(void (*fn)(uintptr_t pthr))
{
    const uint32_t n = s_wp_nthr < WP_THR - 1 ? s_wp_nthr : WP_THR - 1;
    int k = 0;
    for (uint32_t i = 0; i < n; i++) if (s_wp_pthr[i]) { fn(s_wp_pthr[i]); k++; }
    return k;
}
void ps3_host_thread_label(const char* name)
{
    const int s = wp_slot();
    if (s < WP_THR - 1 && name) snprintf(s_wp_name[s], sizeof s_wp_name[s], "%s", name);
    /* ps5 pin: by thread kind (ps5_app.c), only when PS5_PIN_<KIND> is set */
    if (name) {
        if (ps5_audio_spu_prio) ps5_audio_spu_prio(name);   /* audio spu prio (ps5_app.c; absent in the launcher) */
        if (ps5_pin_policy && ps5_pin_policy(name)) return;   /* ps5 pin: PS5_PIN=1 places the thread itself */
        if (!ps5_pin_self) return;   /* (the launcher links these shims without ps5_app.c: weak, see above) */
        if (!strncmp(name, "spu 1000", 8)) ps5_pin_self("SPURS1");
        else if (!strncmp(name, "spu ", 4)) ps5_pin_self("SPU");
        else if (!strcmp(name, "main")) ps5_pin_self("MAIN");
        else if (strcmp(name, "host main / rsx")) ps5_pin_self("OTHER");   /* every other labeled thread (guest PPU threads, helpers) */
    }
}
/* For the profile's signal handler: the stack bound above, by pthread_self value (0: unknown). */
uintptr_t ps5_thread_stack_hi(uintptr_t pthr)
{
    const uint32_t n = s_wp_nthr < WP_THR - 1 ? s_wp_nthr : WP_THR - 1;
    for (uint32_t i = 0; i < n; i++) if (s_wp_pthr[i] == pthr) return s_wp_stack_hi[i];
    return 0;
}
/* The label of a host thread (pthread_self value), or NULL: the profiler's thread lines. */
const char* ps5_thread_name(uintptr_t pthr)
{
    const uint32_t n = s_wp_nthr < WP_THR - 1 ? s_wp_nthr : WP_THR - 1;
    for (uint32_t i = 0; i < n; i++) if (s_wp_pthr[i] == pthr) return s_wp_name[i];
    return NULL;
}
void ps5_waitprof_enable(int on) { s_wp_on = on; }

/* Sites: one open-addressed table, key = call site | thread << 48 | kind << 56, claimed by CAS. */
#define WP_SITES 2048
static struct { uint64_t key, ns; uint32_t n; } s_wp[WP_SITES];
static void wp_note(int kind, uintptr_t ra, uint64_t ns)
{
    {   const int sl = wp_slot();
        const uintptr_t fa = (uintptr_t)__builtin_frame_address(0);
        if (sl < WP_THR - 1 && fa > s_wp_stack_hi[sl]) s_wp_stack_hi[sl] = fa; }
    const uint64_t key = ((uint64_t)ra & 0xFFFFFFFFFFFFull) | (uint64_t)wp_slot() << 48 | (uint64_t)kind << 56 | 1ull << 63;
    uint32_t h = (uint32_t)((key * 0x9E3779B97F4A7C15ull) >> 53) & (WP_SITES - 1);
    for (int p = 0; p < 64; p++, h = (h + 1) & (WP_SITES - 1)) {
        uint64_t k = __atomic_load_n(&s_wp[h].key, __ATOMIC_RELAXED);
        if (!k && __atomic_compare_exchange_n(&s_wp[h].key, &k, key, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) k = key;
        if (k == key) {
            __atomic_fetch_add(&s_wp[h].ns, ns, __ATOMIC_RELAXED);
            __atomic_fetch_add(&s_wp[h].n, 1, __ATOMIC_RELAXED);
            return;
        }
    }
}

int __real_pthread_cond_wait(pthread_cond_t* c, pthread_mutex_t* m);
int __wrap_pthread_cond_wait(pthread_cond_t* c, pthread_mutex_t* m)
{
    if (!s_wp_on) return __real_pthread_cond_wait(c, m);
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_pthread_cond_wait(c, m);
    wp_note(WP_COND, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
int __real_pthread_cond_timedwait(pthread_cond_t* c, pthread_mutex_t* m, const struct timespec* t);
int __wrap_pthread_cond_timedwait(pthread_cond_t* c, pthread_mutex_t* m, const struct timespec* t)
{
    if (!s_wp_on) return __real_pthread_cond_timedwait(c, m, t);
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_pthread_cond_timedwait(c, m, t);
    wp_note(WP_CONDT, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
int __real_pthread_mutex_lock(pthread_mutex_t* m);
int __wrap_pthread_mutex_lock(pthread_mutex_t* m)
{
    if (!s_wp_on || pthread_mutex_trylock(m) == 0) return s_wp_on ? 0 : __real_pthread_mutex_lock(m);
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_pthread_mutex_lock(m);
    wp_note(WP_MUTEX, (uintptr_t)__builtin_return_address(0), ps5_now_ns() - t0);
    return r;
}
int __real_sem_wait(sem_t* s);
int __wrap_sem_wait(sem_t* s)
{
    if (!s_wp_on) return __real_sem_wait(s);
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_sem_wait(s);
    const uint64_t d = ps5_now_ns() - t0;
    if (d > 2000) wp_note(WP_SEM, (uintptr_t)__builtin_return_address(0), d);
    return r;
}
int __real_sem_timedwait(sem_t* s, const struct timespec* t);
int __wrap_sem_timedwait(sem_t* s, const struct timespec* t)
{
    if (!s_wp_on) return __real_sem_timedwait(s, t);
    const uint64_t t0 = ps5_now_ns();
    const int r = __real_sem_timedwait(s, t);
    const uint64_t d = ps5_now_ns() - t0;
    if (d > 2000) wp_note(WP_SEM, (uintptr_t)__builtin_return_address(0), d);
    return r;
}

/* Every report: per thread, the share of the window it spent waiting and on what; then the 40
 * busiest sites (thread, kind, call site as an offset from ps5_app_setup like the profile's, ms of
 * waiting per second, calls per second). The counters restart for the next window. */
extern void ps5_app_setup(int*, char***) __attribute__((weak));
static int wp_cmp(const void* a, const void* b)
{
    const uint64_t x = ((const uint64_t*)a)[1], y = ((const uint64_t*)b)[1];
    return x < y ? 1 : x > y ? -1 : 0;
}
void ps5_waitprof_report(double secs)
{
    if (!s_wp_on || secs <= 0) return;
    static uint64_t snap[WP_SITES][3];   /* key, ns, n */
    static uint64_t thr_ns[WP_THR][WP_KINDS];
    int m = 0;
    memset(thr_ns, 0, sizeof thr_ns);
    for (int i = 0; i < WP_SITES; i++) {
        const uint64_t k = __atomic_load_n(&s_wp[i].key, __ATOMIC_RELAXED);
        if (!k) continue;
        const uint64_t ns = __atomic_exchange_n(&s_wp[i].ns, 0, __ATOMIC_RELAXED);
        const uint32_t n = __atomic_exchange_n(&s_wp[i].n, 0, __ATOMIC_RELAXED);
        if (!n) continue;
        snap[m][0] = k; snap[m][1] = ns; snap[m][2] = n; m++;
        thr_ns[(k >> 48) & 0xFF][(k >> 56) & 0x7F] += ns;
    }
    const uintptr_t anchor = ps5_app_setup ? (uintptr_t)&ps5_app_setup : 0;
    const uint32_t nthr = s_wp_nthr < WP_THR ? s_wp_nthr : WP_THR;
    for (uint32_t t = 0; t < nthr; t++) {
        uint64_t tot = 0;
        for (int k = 0; k < WP_KINDS; k++) tot += thr_ns[t][k];
        if (!tot) continue;
        char line[384];
        int len = snprintf(line, sizeof line, "[wait] thread %-22s waits %5.1f%%:", s_wp_name[t], 100.0 * tot / (secs * 1e9));
        for (int k = 0; k < WP_KINDS; k++)
            if (thr_ns[t][k] * 200 >= tot)   /* kinds of at least 0.5% */
                len += snprintf(line + len, sizeof line - len, " %s %.1f%%", wp_kind_name[k], 100.0 * thr_ns[t][k] / (secs * 1e9));
        printf("%s\n", line);
    }
    qsort(snap, (size_t)m, sizeof snap[0], wp_cmp);
    for (int i = 0; i < m && i < 40; i++) {
        const uint64_t k = snap[i][0];
        const uintptr_t ra = (uintptr_t)(k & 0xFFFFFFFFFFFFull);
        printf("[wait] site %-22s %-10s anchor%+lld %7.1f ms/s %8.0f /s\n", s_wp_name[(k >> 48) & 0xFF],
               wp_kind_name[(k >> 56) & 0x7F], (long long)(intptr_t)(ra - anchor),
               snap[i][1] / 1e6 / secs, snap[i][2] / secs);
    }
}
