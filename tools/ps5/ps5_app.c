/* inFamous 2 on the PS5: what run.sh does on a computer (paths, environment, log), plus the guest
 * address space in direct memory. Called from main.cpp under __PROSPERO__.
 *
 * App folder (/app0 = the homebrew folder, writable):
 *   game/PS3_GAME/                 the disc's PS3_GAME with the updates laid over it, EBOOT.elf in USRDIR
 *   game/dev_hdd0/game/NPUA80638/  PARAM.SFO + USRDIR/patch/psarc (the updates' archives)
 *   game/dev_hdd0/...              the game's own install (BCUS98125_INSTALL) and saves land here
 *   game/dev_flash/sys/external/   firmware modules (.sprx) the game loads
 *   env.txt                        optional VAR=value lines, applied before the defaults
 *   logs/infamous2.log             stdout + stderr
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <ps5platform/context.h>
#include <ps5platform/kernel.h>

#define APP "/app0"

static uint8_t* s_guest_base;   /* ps5_map_guest_vm's block: fault addresses inside it are guest addresses */
static int s_log_fd = 2;        /* the log's descriptor (fileno(stderr) after freopen; not always 2) */
static char s_dbg_dump[160] = APP "/logs/dbg_dump.txt";   /* the debug server's scratch file (this game's logs/) */
void ps5_app_setup(int* argc, char*** argv);

/* Crash report: which signal, the faulting address (as a guest address when it is one), the host
 * instruction and the code addresses found on the stack, each as an offset from ps5_app_setup (the
 * log's "anchor" line gives that function's address; nm on Infamous2Recomp.eboot.elf turns the
 * offsets into names). Written with write(2) to the log; one report, then the default action. */
static void crash_line(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
static void crash_line(const char* fmt, ...)
{
    char b[256];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(b, sizeof b, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof b - 1) n = sizeof b - 1;
    if (n > 0) write(s_log_fd, b, (size_t)n);
}

static void crash_handler(int sig, siginfo_t* si, void* uctx)
{
    static volatile int once;
    if (once++) return;
    const char* name = sig == SIGSEGV ? "SIGSEGV" : sig == SIGBUS ? "SIGBUS" : sig == SIGILL ? "SIGILL"
                     : sig == SIGFPE ? "SIGFPE" : sig == SIGABRT ? "SIGABRT" : "?";
    const uintptr_t anchor = (uintptr_t)&ps5_app_setup;
    const uintptr_t addr = (uintptr_t)si->si_addr;
    /* No stdio here: another thread may hold a stream's lock, and the report would never be written. */
    crash_line("\n[ps5] CRASH: %s (signal %d, code %d) at address %p", name, sig, si->si_code, si->si_addr);
    if (s_guest_base && addr >= (uintptr_t)s_guest_base && addr - (uintptr_t)s_guest_base < ((uintptr_t)1 << 32))
        crash_line(" = guest 0x%08x", (unsigned)(addr - (uintptr_t)s_guest_base));
    crash_line(", thread %p\n", (void*)pthread_self());
    const ucontext_t* uc = (const ucontext_t*)uctx;
    const uintptr_t rip = (uintptr_t)uc->uc_mcontext.mc_rip, rsp = (uintptr_t)uc->uc_mcontext.mc_rsp;
    crash_line("[ps5]   rip %p (anchor%+lld) rsp %p rbp %p\n", (void*)rip, (long long)(rip - anchor),
               (void*)rsp, (void*)(uintptr_t)uc->uc_mcontext.mc_rbp);
    /* Return addresses: stack words that point into the executable (within 512 MB of the anchor). */
    crash_line("[ps5]   stack code addresses (anchor+offset):");
    const uintptr_t* sp = (const uintptr_t*)(rsp & ~(uintptr_t)7);
    int found = 0;
    for (int i = 0; i < 8192 && found < 40; i++) {
        const uintptr_t w = sp[i];
        if (w > anchor - ((uintptr_t)1 << 29) && w < anchor + ((uintptr_t)1 << 29) && w != anchor) {
            crash_line(" %+lld", (long long)(w - anchor));
            found++;
        }
    }
    crash_line("\n[ps5] end of crash report\n");
}

/* Self-test at start: a read of a reserved, unmapped page, on this thread and on a new one, caught
 * by a handler that steps over the 2-byte load (as the SDK's probe does). Says in the log whether
 * signal handlers run in this app at all, and on other threads. */
static volatile int s_st_hits;
static void selftest_handler(int sig, siginfo_t* si, void* uctx)
{
    ucontext_t* uc = (ucontext_t*)uctx;
    s_st_hits++;
    crash_line("[ps5] crash-handler self-test: signal %d at %p, rip %p, thread %p\n", sig, si->si_addr,
               (void*)(uintptr_t)uc->uc_mcontext.mc_rip, (void*)pthread_self());
    uc->uc_mcontext.mc_rip += 2;   /* movb (%rax), %al = 8a 00 */
}
static void selftest_fault(void* at)
{
    __asm__ volatile("movb (%%rax), %%al" : "+a"(at) : : "memory");
}
static void* selftest_thread(void* at)
{
    selftest_fault(at);
    return NULL;
}
static void crash_selftest(void)
{
    void* va = NULL;
    if (sceKernelReserveVirtualRange(&va, 64 * 1024, 0, PS5_KERNEL_DIRECT_ALIGNMENT) != 0 || !va) {
        printf("[ps5] crash-handler self-test: no page to test with\n");
        return;
    }
    struct sigaction sa, old_segv, old_bus;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = selftest_handler;
    sa.sa_flags = SA_SIGINFO;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGSEGV, &sa, &old_segv);
    sigaction(SIGBUS, &sa, &old_bus);
    selftest_fault(va);
    const int main_hits = s_st_hits;
    pthread_t t;
    if (pthread_create(&t, NULL, selftest_thread, va) == 0) pthread_join(t, NULL);
    printf("[ps5] crash-handler self-test: main thread %s, second thread %s\n",
           main_hits ? "caught" : "NOT caught", s_st_hits > main_hits ? "caught" : "NOT caught");
    sigaction(SIGSEGV, &old_segv, NULL);
    sigaction(SIGBUS, &old_bus, NULL);
    sceKernelMunmap(va, 64 * 1024);
}

/* Self-test of the wait the console runs ended in: a thread blocks in pthread_cond_wait until this
 * one signals it, first on a default stack, then on a 64 MB stack from ps5_shims.c (as the guest
 * threads get), then a timed wait. Every step is logged before it is taken. */
static pthread_mutex_t s_ct_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t s_ct_cond = PTHREAD_COND_INITIALIZER;
static int s_ct_go;
static void* cond_waiter(void* arg)
{
    printf("[ps5] cond self-test (%s): waiter locking\n", (const char*)arg);
    pthread_mutex_lock(&s_ct_lock);
    printf("[ps5] cond self-test (%s): waiter in pthread_cond_wait\n", (const char*)arg);
    while (!s_ct_go) pthread_cond_wait(&s_ct_cond, &s_ct_lock);
    pthread_mutex_unlock(&s_ct_lock);
    printf("[ps5] cond self-test (%s): waiter woke\n", (const char*)arg);
    return NULL;
}
static void cond_selftest_one(const char* name, size_t stack)
{
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    if (stack) pthread_attr_setstacksize(&attr, stack);
    s_ct_go = 0;
    pthread_t t;
    if (pthread_create(&t, &attr, cond_waiter, (void*)name) != 0) {
        printf("[ps5] cond self-test (%s): pthread_create failed\n", name);
        pthread_attr_destroy(&attr);
        return;
    }
    pthread_attr_destroy(&attr);
    usleep(200 * 1000);
    printf("[ps5] cond self-test (%s): signalling\n", name);
    pthread_mutex_lock(&s_ct_lock);
    s_ct_go = 1;
    pthread_cond_signal(&s_ct_cond);
    pthread_mutex_unlock(&s_ct_lock);
    pthread_join(t, NULL);
    printf("[ps5] cond self-test (%s): OK\n", name);
}
/* Self-test of contention, which the console runs had never had before they ended: four threads
 * printing to the log at once (on an unbuffered stderr each line is many small writes, the stream
 * lock held across them) and taking one mutex in turn. */
static pthread_mutex_t s_mx_lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned long s_mx_count;
static void* contention_worker(void* arg)
{
    const int id = (int)(intptr_t)arg;
    for (int i = 0; i < 200; i++) {
        fprintf(stderr, "[ps5] contention self-test: thread %d line %d of 200 (stderr)\n", id, i);
        for (int k = 0; k < 100; k++) {
            pthread_mutex_lock(&s_mx_lock);
            s_mx_count++;
            pthread_mutex_unlock(&s_mx_lock);
        }
    }
    return NULL;
}
static void contention_selftest(void)
{
    printf("[ps5] contention self-test: starting 4 threads\n");
    pthread_t t[4];
    int n = 0;
    for (int i = 0; i < 4; i++)
        if (pthread_create(&t[n], NULL, contention_worker, (void*)(intptr_t)i) == 0) n++;
    for (int i = 0; i < n; i++) pthread_join(t[i], NULL);
    printf("[ps5] contention self-test: OK (%d threads, mutex count %lu of %d)\n", n, s_mx_count, n * 200 * 100);
}

static void cond_selftest(void)
{
    cond_selftest_one("default stack", 0);
    cond_selftest_one("64 MB direct-memory stack", (size_t)256 << 20);
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ts.tv_nsec += 20 * 1000 * 1000;
    if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
    printf("[ps5] cond self-test (timed): waiting 20 ms\n");
    pthread_mutex_lock(&s_ct_lock);
    const int rc = pthread_cond_timedwait(&s_ct_cond, &s_ct_lock, &ts);
    pthread_mutex_unlock(&s_ct_lock);
    printf("[ps5] cond self-test (timed): returned %d (ETIMEDOUT is %d)\n", rc, ETIMEDOUT);
}

static void install_crash_handler(void)
{
    /* The main thread's handler runs on its own stack, so a stack overflow there is reported too. */
    static char altstack[64 * 1024];
    stack_t ss = { .ss_sp = altstack, .ss_size = sizeof altstack, .ss_flags = 0 };
    sigaltstack(&ss, NULL);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = crash_handler;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK | SA_RESETHAND;
    sigemptyset(&sa.sa_mask);
    const int sigs[] = { SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT };
    for (unsigned i = 0; i < sizeof sigs / sizeof sigs[0]; i++) sigaction(sigs[i], &sa, NULL);
}

/* Sampling profiler (PS5_PROFILE, on by default for now; PS5_PROFILE=0 turns it off): ITIMER_PROF
 * sends SIGPROF to the thread using CPU every 4 ms of CPU time, the handler drops its rip into a
 * ring, and the status thread prints the busiest 256-byte spans as offsets from ps5_app_setup
 * ("[ps5] profile:" lines; tools/ps5/readlog.sh names them with nm). Outside the eboot (libc,
 * libkernel, ...) is one line by 16 MB region. */
#include <sys/time.h>
#include <dlfcn.h>
/* ps5 pin / ps5 cpumap: shared state (the code is after ps5_pin_self below). s_cpumap_on: the profile's
 * SIGPROF handler also records which CPU the sampled thread is on (cpuid's initial APIC id; only after
 * the start-up probe showed cpuid runs and tells the CPUs apart). */
static volatile int s_cpumap_on;
static unsigned char s_apic_cpu[256];     /* APIC id -> logical CPU + 1 (0: not one of ours) */
static signed char s_cpu_sib[64];         /* logical CPU -> its SMT sibling, -1: none allowed */
static inline uint32_t ps5_apic_now(void)
{
    uint32_t a, b, c, d;
    __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(c), "=d"(d) : "a"(1u), "c"(0u));
    (void)a; (void)c; (void)d;
    return b >> 24;
}
#define PROF_RING (1u << 16)
static unsigned char s_prof_apic[PROF_RING];   /* ps5 cpumap: APIC id of the sampled CPU (0xFF: not recorded) */
static uintptr_t s_prof_ring[PROF_RING];
static uintptr_t s_prof_caller[PROF_RING];   /* the word at rsp: a leaf library call's return address */
static uintptr_t s_prof_thr[PROF_RING];      /* pthread_self of the sampled thread */
static volatile uint32_t s_prof_n;
/* A sample inside a library function that has its own frame: the word at rsp is not a return
 * address, and the line used to say only "(library)". The thread's stack is then searched upwards,
 * at most 2 KB and never past the highest frame ps5_shims.c saw the thread at, for the first word
 * pointing into the eboot's code (_start, first in the link, to etext): the eboot call it is under. */
extern uintptr_t ps5_thread_stack_hi(uintptr_t pthr);
extern void _start(void);
extern char etext[] __attribute__((weak));
static uintptr_t s_prof_text_lo, s_prof_text_hi;
/* A return address follows a call: E8 rel32, or FF /2 (indirect, 2-7 bytes). Pointers into the
 * read-only data passed the range test alone (the first console run's "called from" was a
 * .rodata address). Everything from _start up to this file's bss is mapped (the eboot's
 * segments are contiguous), so the bytes before w can be read. */
static inline __attribute__((unused)) int prof_after_call(const unsigned char* w)
{
    if (w[-5] == 0xE8) return 1;
    for (int k = 2; k <= 7; k++)
        if (w[-k] == 0xFF && ((w[-k + 1] >> 3) & 7) == 2) return 1;
    return 0;
}
static void prof_handler(int sig, siginfo_t* si, void* uctx)
{
    (void)sig; (void)si;
    const ucontext_t* uc = (const ucontext_t*)uctx;
    const uint32_t i = __atomic_fetch_add(&s_prof_n, 1, __ATOMIC_RELAXED) & (PROF_RING - 1);
    const uintptr_t rip = (uintptr_t)uc->uc_mcontext.mc_rip, rsp = (uintptr_t)uc->uc_mcontext.mc_rsp;
    const uintptr_t thr = (uintptr_t)pthread_self();
    uintptr_t ra = *(const uintptr_t*)rsp;
    const uintptr_t lo = s_prof_text_lo, hi = s_prof_text_hi;
    /* The stack scan is off: its return-address check read the bytes before a candidate, and the
     * console maps game code execute-only (every game crashed at launch, 2026-11-01). */
    (void)lo; (void)hi; (void)thr;
    s_prof_ring[i] = rip;
    s_prof_caller[i] = ra;
    s_prof_thr[i] = thr;
    s_prof_apic[i] = s_cpumap_on ? (unsigned char)ps5_apic_now() : 0xFF;   /* ps5 cpumap */
}
/* By thread: the busiest threads of the window, each with its share of the samples and its three
 * hottest 256-byte eboot spans (or "outside" for library/kernel code). A thread at ~4 ms x
 * (15 s / 4 ms) = 100% of one core is the one to look at. tools/ps5/profthr.sh names the spans. */
static void prof_report_threads(uint32_t now, uint32_t n, uintptr_t anchor)
{
    enum { T = 48, S = 48 };
    /* ck/cc: for library samples, the eboot code the leaf call came from (the word at rsp) */
    static struct { uintptr_t thr; uint32_t c; uintptr_t key[S]; uint32_t kc[S]; uintptr_t ck[S]; uint32_t cc[S]; } th[T];
    int nt = 0;
    memset(th, 0, sizeof th);
    for (uint32_t k = 0; k < n; k++) {
        const uint32_t i = (now - n + k) & (PROF_RING - 1);
        const uintptr_t t = s_prof_thr[i], rip = s_prof_ring[i];
        int j = 0;
        while (j < nt && th[j].thr != t) j++;
        if (j == nt) { if (nt == T) continue; th[nt].thr = t; nt++; }
        th[j].c++;
        const intptr_t off = (intptr_t)(rip - anchor);
        const uintptr_t key = (off > -(1l << 29) && off < (1l << 29)) ? (uintptr_t)(off + (1l << 29)) >> 8 : 0;
        int s = 0;
        while (s < S && th[j].kc[s] && th[j].key[s] != key) s++;
        if (s < S) { th[j].key[s] = key; th[j].kc[s]++; }
        if (!key) {
            const intptr_t roff = (intptr_t)(s_prof_caller[i] - anchor);
            const uintptr_t ck = (roff > -(1l << 29) && roff < (1l << 29)) ? (uintptr_t)(roff + (1l << 29)) >> 8 : 0;
            s = 0;
            while (s < S && th[j].cc[s] && th[j].ck[s] != ck) s++;
            if (s < S) { th[j].ck[s] = ck; th[j].cc[s]++; }
        }
    }
    /* samples per core-second at the 4 ms CPU-time timer */
    const double per_core = 1000.0 / 4.0 * 15.0;
    extern const char* ps5_thread_name(uintptr_t pthr);
    for (int r = 0; r < 12; r++) {
        int b = -1;
        for (int j = 0; j < nt; j++) if (th[j].c && (b < 0 || th[j].c > th[b].c)) b = j;
        if (b < 0) break;
        char line[1024];
        const char* name = ps5_thread_name(th[b].thr);
        int len = snprintf(line, sizeof line, "[ps5] profile thread %d (%s): %4.1f%% of samples (~%.2f cores)",
                           r, name ? name : "?", 100.0 * th[b].c / n, th[b].c / per_core);
        const int deep = r < 3;               /* the three busiest: 24 entries and library callers */
        for (int q = 0; q < (deep ? 24 : 8); q++) {
            int m = -1;
            for (int s = 0; s < S; s++) if (th[b].kc[s] && (m < 0 || th[b].kc[s] > th[b].kc[m])) m = s;
            if (m < 0) break;
            if (th[b].key[m])
                len += snprintf(line + len, sizeof line - len, " | %4.1f%% anchor%+lld", 100.0 * th[b].kc[m] / th[b].c,
                                (long long)(intptr_t)((th[b].key[m] << 8) - ((uintptr_t)1 << 29)));
            else
                len += snprintf(line + len, sizeof line - len, " | %4.1f%% outside", 100.0 * th[b].kc[m] / th[b].c);
            th[b].kc[m] = 0;
        }
        printf("%s\n", line);
        if (deep) {
            len = snprintf(line, sizeof line, "[ps5] profile thread %d library called from:", r);
            for (int q = 0; q < 12; q++) {
                int m = -1;
                for (int s = 0; s < S; s++) if (th[b].cc[s] && (m < 0 || th[b].cc[s] > th[b].cc[m])) m = s;
                if (m < 0) break;
                if (th[b].ck[m])
                    len += snprintf(line + len, sizeof line - len, " | %4.1f%% anchor%+lld", 100.0 * th[b].cc[m] / th[b].c,
                                    (long long)(intptr_t)((th[b].ck[m] << 8) - ((uintptr_t)1 << 29)));
                else
                    len += snprintf(line + len, sizeof line - len, " | %4.1f%% (library)", 100.0 * th[b].cc[m] / th[b].c);
                th[b].cc[m] = 0;
            }
            printf("%s\n", line);
        }
        th[b].c = 0;
    }
}
/* ps5 cpumap (PS5_CPUMAP=1, or with PS5_PIN): per busy thread, the CPUs its samples ran on, and an estimate of
 * how much of the time its SMT sibling was busy with another of our threads ("sibling busy"): the sum over the
 * CPUs c it ran on of P(it on c) x sum over the other threads U of busy(U) x P(U on sibling(c)). Samples are
 * per CPU time, not simultaneous, so this assumes the threads place independently: a guide, not a measurement.
 * busy(U) = samples x 4 ms / wall seconds of the window. One line per thread, the 12 busiest. */
static void prof_report_cpus(uint32_t now, uint32_t n)
{
    if (!s_cpumap_on) return;
    enum { T = 48, C = 64 };
    static struct { uintptr_t thr; uint32_t c; uint16_t on[C]; } th[T];
    static double last_wall;
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    const double wall = ts.tv_sec + ts.tv_nsec / 1e9, dt = last_wall ? wall - last_wall : 0;
    last_wall = wall;
    if (dt <= 0.5) return;
    int nt = 0;
    memset(th, 0, sizeof th);
    for (uint32_t k = 0; k < n; k++) {
        const uint32_t i = (now - n + k) & (PROF_RING - 1);
        if (s_prof_apic[i] == 0xFF || !s_apic_cpu[s_prof_apic[i]]) continue;
        const int cpu = s_apic_cpu[s_prof_apic[i]] - 1;
        const uintptr_t t = s_prof_thr[i];
        int j = 0;
        while (j < nt && th[j].thr != t) j++;
        if (j == nt) { if (nt == T) continue; th[nt].thr = t; nt++; }
        th[j].c++;
        if (cpu < C && th[j].on[cpu] < 65535) th[j].on[cpu]++;
    }
    extern const char* ps5_thread_name(uintptr_t pthr);
    static int done[T];
    static double shares[T];
    memset(done, 0, sizeof done);
    for (int b = 0; b < nt; b++) {   /* all estimates first: the printing below clears the histograms */
        double share = 0;
        for (int c = 0; c < C; c++) {
            if (!th[b].on[c] || s_cpu_sib[c] < 0) continue;
            const int s = s_cpu_sib[c];
            double sib = 0;
            for (int u = 0; u < nt; u++)
                if (u != b && th[u].c) sib += (th[u].c * 0.004 / dt) * ((double)th[u].on[s] / th[u].c);
            share += ((double)th[b].on[c] / th[b].c) * (sib > 1 ? 1 : sib);
        }
        shares[b] = share;
    }
    for (int r = 0; r < 12; r++) {
        int b = -1;
        for (int j = 0; j < nt; j++) if (!done[j] && th[j].c && (b < 0 || th[j].c > th[b].c)) b = j;
        if (b < 0) break;
        done[b] = 1;
        const double share = shares[b];
        char line[512];
        const char* name = ps5_thread_name(th[b].thr);
        int len = snprintf(line, sizeof line, "[ps5] cpumap thread %d (%s): busy %.2f, sibling busy %.2f |", r,
                           name ? name : "?", th[b].c * 0.004 / dt, share);
        for (int q = 0; q < 4; q++) {
            int m = -1;
            for (int c = 0; c < C; c++) if (th[b].on[c] && (m < 0 || th[b].on[c] > th[b].on[m])) m = c;
            if (m < 0) break;
            len += snprintf(line + len, sizeof line - len, " cpu%d %.0f%%", m, 100.0 * th[b].on[m] / th[b].c);
            th[b].on[m] = 0;
        }
        printf("%s\n", line);
    }
}
/* Outside the eboot: the library symbol nearest below each sample (dladdr, when the console's
 * loader has it), and which eboot code the leaf call came from. */
extern int dladdr(const void*, Dl_info*) __attribute__((weak));
static void prof_report_outside(uint32_t now, uint32_t n, uintptr_t anchor)
{
    enum { K = 12 };
    struct { uintptr_t key; uint32_t c; } sym[64], cal[64];
    int nsym = 0, ncal = 0;
    uint32_t outside = 0;
    for (uint32_t k = 0; k < n; k++) {
        const uint32_t i = (now - n + k) & (PROF_RING - 1);
        const uintptr_t rip = s_prof_ring[i], ra = s_prof_caller[i];
        const intptr_t off = (intptr_t)(rip - anchor);
        if (off > -(1l << 29) && off < (1l << 29)) continue;
        outside++;
        uintptr_t key = rip & ~(uintptr_t)0xFF;
        if (dladdr) { Dl_info di; if (dladdr((void*)rip, &di) && di.dli_saddr) key = (uintptr_t)di.dli_saddr; }
        int j = 0;
        while (j < nsym && sym[j].key != key) j++;
        if (j < nsym) sym[j].c++; else if (nsym < 64) { sym[nsym].key = key; sym[nsym].c = 1; nsym++; }
        const intptr_t roff = (intptr_t)(ra - anchor);
        if (roff > -(1l << 29) && roff < (1l << 29)) {
            const uintptr_t ck = (uintptr_t)roff & ~(uintptr_t)0xFF;
            j = 0;
            while (j < ncal && cal[j].key != ck) j++;
            if (j < ncal) cal[j].c++; else if (ncal < 64) { cal[ncal].key = ck; cal[ncal].c = 1; ncal++; }
        }
    }
    if (!outside) return;
    for (int r = 0; r < K && nsym; r++) {
        int b = 0;
        for (int j = 1; j < nsym; j++) if (sym[j].c > sym[b].c) b = j;
        if (!sym[b].c) break;
        Dl_info di = { 0 };
        const int ok = dladdr && dladdr((void*)sym[b].key, &di);
        printf("[ps5] profile: outside %5.1f%% at %p %s+0x%lx (%s)\n", 100.0 * sym[b].c / n, (void*)sym[b].key,
               ok && di.dli_sname ? di.dli_sname : "?", ok && di.dli_saddr ? (unsigned long)(sym[b].key - (uintptr_t)di.dli_saddr) : 0ul,
               ok && di.dli_fname ? di.dli_fname : "?");
        sym[b].c = 0;
    }
    for (int r = 0; r < K && ncal; r++) {
        int b = 0;
        for (int j = 1; j < ncal; j++) if (cal[j].c > cal[b].c) b = j;
        if (!cal[b].c) break;
        printf("[ps5] profile: called from %5.1f%% anchor%+lld\n", 100.0 * cal[b].c / n, (long long)(intptr_t)cal[b].key);
        cal[b].c = 0;
    }
}
static int prof_cmp(const void* a, const void* b)
{
    const uintptr_t x = *(const uintptr_t*)a, y = *(const uintptr_t*)b;
    return x < y ? -1 : x > y;
}
static void prof_start(void)
{
    if (getenv("PS5_PROFILE") && !strcmp(getenv("PS5_PROFILE"), "0")) return;
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = prof_handler;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigemptyset(&sa.sa_mask);
    s_prof_text_lo = (uintptr_t)&_start;
    s_prof_text_hi = etext ? (uintptr_t)etext : (uintptr_t)s_prof_ring;   /* bss: mapped up to here */
    if (s_prof_text_hi <= s_prof_text_lo) s_prof_text_lo = 0;
    printf("[ps5] profile: eboot code %p-%p (etext %s)\n", (void*)s_prof_text_lo, (void*)s_prof_text_hi, etext ? "found" : "missing");
    if (sigaction(SIGPROF, &sa, NULL) != 0) { printf("[ps5] profile: no SIGPROF handler\n"); return; }
    struct itimerval it = { { 0, 4000 }, { 0, 4000 } };
    const int r = setitimer(ITIMER_PROF, &it, NULL);
    printf("[ps5] profile: setitimer(ITIMER_PROF, 4 ms) -> %d%s\n", r, r ? " (no profile)" : "");
}
static void prof_report(void)
{
    static uintptr_t buf[PROF_RING];
    static uint32_t last;
    const uint32_t now = s_prof_n, n = now - last > PROF_RING ? PROF_RING : now - last;
    if (!n) return;
    const uintptr_t anchor = (uintptr_t)&ps5_app_setup;
    for (uint32_t k = 0; k < n; k++) {
        const uintptr_t rip = s_prof_ring[(now - n + k) & (PROF_RING - 1)];
        const intptr_t off = (intptr_t)(rip - anchor);
        /* eboot: 256-byte spans keyed by offset; elsewhere: 16 MB regions, tagged by the top bit */
        buf[k] = (off > -(1l << 29) && off < (1l << 29)) ? (uintptr_t)(off + (1l << 29)) >> 8
                                                          : ((uintptr_t)1 << 63) | (rip >> 24);
    }
    last = now;
    prof_report_threads(now, n, anchor);
    prof_report_cpus(now, n);   /* ps5 cpumap */
    prof_report_outside(now, n, anchor);
    qsort(buf, n, sizeof buf[0], prof_cmp);
    uintptr_t top_key[15] = { 0 };
    uint32_t top_n[15] = { 0 };
    for (uint32_t k = 0; k < n;) {
        uint32_t j = k;
        while (j < n && buf[j] == buf[k]) j++;
        const uint32_t c = j - k;
        for (int t = 0; t < 15; t++)
            if (c > top_n[t]) {
                memmove(&top_n[t + 1], &top_n[t], (14 - t) * sizeof top_n[0]);
                memmove(&top_key[t + 1], &top_key[t], (14 - t) * sizeof top_key[0]);
                top_n[t] = c; top_key[t] = buf[k];
                break;
            }
        k = j;
    }
    printf("[ps5] profile: %u samples\n", n);
    for (int t = 0; t < 15 && top_n[t]; t++) {
        if (top_key[t] >> 63)
            printf("[ps5] profile: %5.1f%% outside eboot, region %p\n", 100.0 * top_n[t] / n,
                   (void*)((top_key[t] & ~((uintptr_t)1 << 63)) << 24));
        else
            printf("[ps5] profile: %5.1f%% anchor%+lld\n", 100.0 * top_n[t] / n,
                   (long long)(intptr_t)((top_key[t] << 8) - ((uintptr_t)1 << 29)));
    }
}

/* Where the threads may run. The PS3 emulator for the PS5 (PS5SX3, RPCS3) places its threads itself
 * and reports 13 usable CPUs (0-12); on inFamous it keeps ~7 of them busy at 30-40 fps. Here: log the
 * main thread's CPU mask and priority as the console gave them, then widen the mask to every usable
 * CPU (PS5_CPU_MASK, default 0x1fff = CPUs 0-12) before any game thread exists, so the threads it
 * creates inherit it. */
#include <sys/cpuset.h>
#include <pthread_np.h>
#include <sys/resource.h>
#include <sys/sysctl.h>
static unsigned long long mask_of(const cpuset_t* s)
{
    unsigned long long m = 0;
    for (int c = 0; c < 64 && c < CPU_SETSIZE; c++)
        if (CPU_ISSET(c, s)) m |= 1ull << c;
    return m;
}
/* ps5 cpuset size: the SDK's cpuset_t is 32 bytes (CPU_MAXSIZE 256); the console's kernel
 * returns ERANGE (34) for it, so every launch until 2026-11-06 kept the console's default mask. Try
 * the kernel's sizes (16, 8, 32 bytes) and use the first one that works. */
static size_t s_cpuset_size;
static int ps5_get_mask(unsigned long long* m)
{
    static const size_t sizes[] = { 16, 8, 32 };
    for (unsigned i = 0; i < 3; i++) {
        if (s_cpuset_size && sizes[i] != s_cpuset_size) continue;
        unsigned char buf[32] = { 0 };
        const int r = pthread_getaffinity_np(pthread_self(), sizes[i], (cpuset_t*)buf);
        if (r == 0) { s_cpuset_size = sizes[i]; memcpy(m, buf, 8); return 0; }
        printf("[ps5] threads: pthread_getaffinity_np size %zu -> %d\n", sizes[i], r);
    }
    return -1;
}
static int ps5_set_mask(unsigned long long m)
{
    if (!s_cpuset_size) { unsigned long long d; if (ps5_get_mask(&d)) return -1; }
    unsigned char buf[32] = { 0 };
    memcpy(buf, &m, 8);
    return pthread_setaffinity_np(pthread_self(), s_cpuset_size, (const cpuset_t*)buf);
}
/* audio spu prio: inFAMOUS 1's audio SPURS (group 0x1001) threads above the game's FIFO 700 (PS5_AUDIO_SPU_PRIO,
 * default 640), called from ps3_host_thread_label (ps5_shims.c) as each thread names itself. */
void ps5_audio_spu_prio(const char* name)
{
    /* DONTFLIP (audio tuning): keep the if1-only gate below -- see ~/inFamous/DONTFLIP.md. */
    if (strncmp(name, "spu 1001", 8)) return;
    if (strcmp(PS5_GAME_DIR, "if1")) return;   /* inFAMOUS 1's audio fix only: in inFAMOUS 2 the raised audio SPU crashed the game (SPURS abort after the karma movie, 2026-11-08) */
    static int prio = -1;
    if (prio < 0) { const char* e = getenv("PS5_AUDIO_SPU_PRIO"); prio = e && *e ? atoi(e) : 640; }
    if (prio < 256 || prio > 767) return;
    int pol = 0; struct sched_param sp = { 0 };
    pthread_getschedparam(pthread_self(), &pol, &sp);
    const int was = sp.sched_priority; sp.sched_priority = prio;
    const int rc = pthread_setschedparam(pthread_self(), pol, &sp);
    printf("[ps5] %s: priority %d -> %d (rc %d)\n", name, was, prio, rc);
}
/* Pin the calling thread (ps5 pin): PS5_PIN_<NAME>=<cpu mask> (hex), logged once per name. */
void ps5_pin_self(const char* name)
{
    char key[64]; snprintf(key, sizeof key, "PS5_PIN_%s", name);
    const char* e = getenv(key);
    if (!e || !*e) return;
    const unsigned long long m = strtoull(e, NULL, 16);
    const int r = ps5_set_mask(m);
    unsigned long long now = 0; ps5_get_mask(&now);
    printf("[ps5] pin %s: CPUs 0x%llx -> %d (now 0x%llx)\n", name, m, r, now);
}

/* ps5 pin (PS5_PIN, default off; 2026-11-11 agent_affinity): give the frame-limiting threads a physical core each.
 * Console if2 log 11-11: RSX thread 0.89 busy, main PPU 0.73, five SPURS SPUs ~0.68, be async 0.36; 5.9 of 13 CPUs
 * busy, every thread FIFO 700 on mask 0x1fff, nothing pinned. Whether the console's scheduler keeps two busy
 * threads off one core is unknown (kern.sched.topology_spec does not exist there); two busy SMT siblings each lose
 * ~25-40%. Here a critical thread gets BOTH CPUs of one core (its sibling stays idle or takes only mostly-sleeping
 * helpers); everything else goes to the rest ("pool"). Sets of CPUs, never one CPU: no thread can be starved
 * behind a same-priority FIFO thread pinned to the same single CPU.
 *   PS5_PIN=1           the game's table below; PS5_PIN=rsx | main | rsx,main to choose; 0 / unset = off.
 *   PS5_PIN_RSX_CPU=<n> / PS5_PIN_MAIN_CPU=<n>  use the core holding CPU n (default: the last / second-last full
 *                       core, away from CPU 0).
 *   PS5_CPUMAP=1        without PS5_PIN: only the topology probe and the "[ps5] cpumap" lines (today's placement).
 * Topology: each allowed CPU is visited once at start-up (main thread only, before any game thread) and cpuid's
 * APIC id read there; CPUs whose APIC ids differ only in the SMT bits are one core. Any doubt (probe fault, ids
 * not distinct, a core of more than 2 CPUs, < 2 full cores free, pool < 4 CPUs) = no pinning, one log line why.
 * The RSX thread (main.cpp's frame_clock) never labels itself: it is created by this thread after
 * ps5_app_setup and inherits its mask, so this thread takes the RSX set at the end of ps5_app_setup (pin_host_main) and moves to the main set when
 * sys_ppu_thread.c labels it "main". A watchdog in the status thread undoes everything (pool CPUs saturated and
 * no frame presented for ~6 s). */
static const struct { const char* game; const char* isolate; } k_pin_table[] = {
    { "infamous2",   "rsx,main" },   /* RSX thread = the wall (0.89), main second (0.73) */
    { "infamousfob", "rsx,main" },   /* same engine and thread mix */
    { "infamous",    "main" },       /* main PPU = the wall (0.91-0.98); RSX 0.65 stays with the 6+2 SPUs */
};
static int s_pin_rsx, s_pin_main, s_pin_on;
static unsigned long long s_pin_allowed, s_set_rsx, s_set_main, s_set_pool;
static int s_topo_ok;
static uint64_t s_probe_jb[10];
extern int ps5_setjmp(uint64_t* jb) __attribute__((returns_twice));   /* ps5_shims.c */
extern void ps5_longjmp(uint64_t* jb, int v) __attribute__((noreturn));
static volatile uintptr_t s_probe_thr;   /* the probing thread: only its fault is the probe's */
static void probe_fault(int sig, siginfo_t* si, void* uc)
{
    if ((uintptr_t)pthread_self() == s_probe_thr) ps5_longjmp(s_probe_jb, 1);
    /* Another thread's real crash during the probe's few ms: the crash report as before, then the default
     * action (what the crash handler's SA_RESETHAND does), so the re-executed fault ends the process. */
    crash_handler(sig, si, uc);
    struct sigaction d; memset(&d, 0, sizeof d); d.sa_handler = SIG_DFL; sigemptyset(&d.sa_mask);
    sigaction(sig, &d, NULL);
}
static int popc(unsigned long long m) { int n = 0; for (; m; m &= m - 1) n++; return n; }
/* Visit every allowed CPU, read its APIC id; fills s_apic_cpu / s_cpu_sib. Returns 0 when the topology is usable. */
static int topo_probe(unsigned long long allowed, int core_of[64])
{
    static unsigned char apic[64];
    struct sigaction sa, o_ill, o_segv, o_bus;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = probe_fault;
    sa.sa_flags = SA_SIGINFO | SA_NODEFER;   /* the handler leaves by a jump: nothing may stay blocked */
    s_probe_thr = (uintptr_t)pthread_self();
    sigemptyset(&sa.sa_mask);
    sigaction(SIGILL, &sa, &o_ill); sigaction(SIGSEGV, &sa, &o_segv); sigaction(SIGBUS, &sa, &o_bus);
    volatile int bad = 0;
    volatile uint32_t tpc = 2;
    volatile int c = 0;
    if (ps5_setjmp(s_probe_jb) == 0) {
        uint32_t a, b, cx, d;
        __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(cx), "=d"(d) : "a"(0x80000000u), "c"(0u));
        if (a >= 0x8000001Eu) {
            __asm__ volatile("cpuid" : "=a"(a), "=b"(b), "=c"(cx), "=d"(d) : "a"(0x8000001Eu), "c"(0u));
            tpc = ((b >> 8) & 0xFF) + 1;   /* AMD: threads per core */
        }
        for (c = 0; c < 64 && !bad; c++) {
            if (!(allowed >> c & 1)) continue;
            if (ps5_set_mask(1ull << c)) { bad = 2; break; }
            usleep(200);                   /* off the CPU and back: now on CPU c */
            const uint32_t a1 = ps5_apic_now();
            usleep(200);
            const uint32_t a2 = ps5_apic_now();
            if (a1 != a2) { bad = 3; break; }
            apic[c] = (unsigned char)a1;
        }
    } else bad = 1;
    sigaction(SIGILL, &o_ill, NULL); sigaction(SIGSEGV, &o_segv, NULL); sigaction(SIGBUS, &o_bus, NULL);
    s_probe_thr = 0;
    /* Back to the full mask. This thread's mask is what every later thread inherits: a failure here would leave
     * the whole game on one CPU, so retry, and say so loudly if it still fails. */
    int rr = ps5_set_mask(allowed);
    if (rr) { usleep(1000); rr = ps5_set_mask(allowed); }
    if (rr) { unsigned long long now = 0; ps5_get_mask(&now);
              printf("[ps5] pin topology: RESTORING THE MASK FAILED (rc %d, now 0x%llx)\n", rr, now); return -1; }
    if (bad) { printf("[ps5] pin topology: probe failed (%s, cpu %d)\n",
                      bad == 1 ? "cpuid faulted" : bad == 2 ? "set mask failed" : "APIC id not stable", (int)c); return -1; }
    if (tpc < 1 || tpc > 2) { printf("[ps5] pin topology: %u threads per core: not handled\n", (unsigned)tpc); return -1; }
    memset(s_apic_cpu, 0, sizeof s_apic_cpu);
    for (int i = 0; i < 64; i++) { s_cpu_sib[i] = -1; core_of[i] = -1; }
    char line[1024]; int len = snprintf(line, sizeof line, "[ps5] pin topology: %u threads/core;", (unsigned)tpc);
    for (int i = 0; i < 64; i++) {
        if (!(allowed >> i & 1)) continue;
        if (s_apic_cpu[apic[i]]) { printf("[ps5] pin topology: CPUs %d and %d both report APIC id %u\n",
                                          s_apic_cpu[apic[i]] - 1, i, apic[i]); return -1; }
        s_apic_cpu[apic[i]] = (unsigned char)(i + 1);
        core_of[i] = apic[i] / tpc;
        len += snprintf(line + len, sizeof line - len, " cpu%d=apic%u", i, apic[i]);
    }
    printf("%s\n", line);
    len = snprintf(line, sizeof line, "[ps5] pin topology: cores (CPUs):");
    for (int i = 0; i < 64; i++) {
        if (core_of[i] < 0) continue;
        int n = 0;
        for (int j = 0; j < 64; j++) if (core_of[j] == core_of[i]) { n++; if (j != i) s_cpu_sib[i] = (signed char)j; }
        if (n > 2) { printf("[ps5] pin topology: core %d has %d CPUs\n", core_of[i], n); return -1; }
        if (s_cpu_sib[i] < 0) len += snprintf(line + len, sizeof line - len, " [%d alone]", i);
        else if (s_cpu_sib[i] > i) len += snprintf(line + len, sizeof line - len, " [%d %d]", i, s_cpu_sib[i]);
    }
    printf("%s\n", line);
    return 0;
}
/* The core (both CPUs) for one critical thread: the core of CPU env (if set and full), else the highest full core
 * not yet used. 0 = none. */
static unsigned long long pin_pick_core(const char* env, unsigned long long used)
{
    const char* e = getenv(env);
    if (e && *e) {
        const int c = atoi(e);
        if (c >= 0 && c < 64 && (s_pin_allowed >> c & 1) && s_cpu_sib[c] >= 0) {
            const unsigned long long m = (1ull << c) | (1ull << s_cpu_sib[c]);
            if (!(m & used)) return m;
        }
        printf("[ps5] pin: %s=%s is not a free full core of ours; picking one\n", env, e);
    }
    for (int c = 63; c >= 0; c--) {
        if (!(s_pin_allowed >> c & 1) || s_cpu_sib[c] < 0) continue;
        const unsigned long long m = (1ull << c) | (1ull << s_cpu_sib[c]);
        if (!(m & used) && !(m & 1ull)) return m;   /* never CPU 0's core (assumed busiest with kernel work) */
    }
    return 0;
}
/* Called once from ps5_app_setup after place_threads, before any game thread exists. */
static void pin_setup(const char* game)
{
    const char* p = getenv("PS5_PIN");
    const char* cm = getenv("PS5_CPUMAP");
    const int want_map = cm && *cm && strcmp(cm, "0");
    const int want_pin = p && *p && strcmp(p, "0");
    if (!want_pin && !want_map) return;
    if (ps5_get_mask(&s_pin_allowed) || !s_pin_allowed) { printf("[ps5] pin: off (no CPU mask)\n"); return; }
    int core_of[64];
    if (topo_probe(s_pin_allowed, core_of)) { printf("[ps5] pin: off (topology unknown)\n"); return; }
    s_topo_ok = 1;
    if (want_map || want_pin) s_cpumap_on = 1;   /* the cpumap lines come with the profile (PS5_PROFILE) */
    if (getenv("PS5_PROFILE") && !strcmp(getenv("PS5_PROFILE"), "0"))
        printf("[ps5] cpumap: no lines: the profile is off (PS5_PROFILE=0 / diagnostics=0)\n");
    if (!want_pin) return;
    const char* iso = NULL;
    if (!strcmp(p, "1")) {
        for (unsigned i = 0; i < sizeof k_pin_table / sizeof k_pin_table[0]; i++)
            if (!strcmp(game, k_pin_table[i].game)) iso = k_pin_table[i].isolate;
        if (!iso) { printf("[ps5] pin: off (no table entry for %s)\n", game); return; }
    } else iso = p;
    const int rsx = strstr(iso, "rsx") != NULL, mainp = strstr(iso, "main") != NULL;
    if (!rsx && !mainp) { printf("[ps5] pin: off (PS5_PIN=%s names neither rsx nor main)\n", p); return; }
    unsigned long long used = 0;
    if (rsx) { s_set_rsx = pin_pick_core("PS5_PIN_RSX_CPU", used); used |= s_set_rsx; }
    if (mainp) { s_set_main = pin_pick_core("PS5_PIN_MAIN_CPU", used); used |= s_set_main; }
    s_set_pool = s_pin_allowed & ~used;
    if ((rsx && !s_set_rsx) || (mainp && !s_set_main) || popc(s_set_pool) < 4) {
        printf("[ps5] pin: off (allowed 0x%llx: not enough full cores; rsx 0x%llx main 0x%llx pool 0x%llx)\n",
               s_pin_allowed, s_set_rsx, s_set_main, s_set_pool);
        s_set_rsx = s_set_main = s_set_pool = 0;
        return;
    }
    s_pin_rsx = rsx; s_pin_main = mainp;
    s_pin_on = 1;
    printf("[ps5] pin: on (%s; isolate %s): allowed 0x%llx, rsx 0x%llx, main 0x%llx, pool 0x%llx\n",
           p, iso, s_pin_allowed, s_set_rsx, s_set_main, s_set_pool);
}
/* Last thing in ps5_app_setup, after its own threads (status, debug server, the SDK's stack reaper) were made on the
 * full mask: this thread takes the RSX set (main.cpp's frame_clock, made next, inherits it), the main set when it is
 * labelled "main". */
static void pin_host_main(void)
{
    if (!s_pin_on) return;
    const unsigned long long first = s_pin_rsx ? s_set_rsx : s_set_pool;
    const int r = ps5_set_mask(first);
    printf("[ps5] pin: host main -> 0x%llx (rc %d)\n", first, r);
}
/* From ps3_host_thread_label (ps5_shims.c) as each thread names itself. Returns 1 when PS5_PIN handled the thread
 * (the PS5_PIN_<KIND> masks are then not applied). One log line per pinned thread (the first 96). */
int ps5_pin_policy(const char* name)
{
    if (!s_pin_on || !name) return 0;
    if (!strcmp(name, "host main / rsx")) return 1;
    unsigned long long m;
    if (!strcmp(name, "main")) m = s_pin_main ? s_set_main : s_set_pool;
    else if (!strcmp(name, "ps5 status")) m = s_pin_allowed;   /* the watchdog: every CPU, so it runs unless all 13 are held */
    else if (!strcmp(name, "vk present pacer")) m = s_pin_rsx ? s_set_rsx : s_set_pool;   /* mostly sleeping, paces the RSX thread's presents */
    else m = s_set_pool;   /* SPUs, be async, texhash helper, audio, guest PPU threads, pipeline builders */
    const int r = ps5_set_mask(m);
    static int logged;
    if (__atomic_fetch_add(&logged, 1, __ATOMIC_RELAXED) < 96)
        printf("[ps5] pin: %s -> CPUs 0x%llx (rc %d)\n", name, m, r);
    return 1;
}
/* Status thread, every second: undo the pinning when the pool looks saturated and frames stopped. */
extern unsigned ppu_boot_frames_presented(void) __attribute__((weak));   /* main.cpp */
static void pin_undo_one(uintptr_t pthr)
{
    unsigned char buf[32] = { 0 };
    memcpy(buf, &s_pin_allowed, 8);
    pthread_setaffinity_np((pthread_t)pthr, s_cpuset_size, (const cpuset_t*)buf);
}
static void pin_watchdog(void)
{
    if (!s_pin_on) return;
    static double last_wall, last_cpu;
    static unsigned last_f;
    static int stuck;
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    const double wall = ts.tv_sec + ts.tv_nsec / 1e9;
    if (last_wall && wall - last_wall < 3.0) return;
    struct rusage ru; getrusage(RUSAGE_SELF, &ru);
    const double cpu = ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
    const unsigned f = ppu_boot_frames_presented ? ppu_boot_frames_presented() : 0;
    if (last_wall) {
        const double busy = (cpu - last_cpu) / (wall - last_wall);
        /* No frame for 2 windows with the pool saturated, or for 3 windows (~9 s) after the first frame whatever the
         * load (a thread starved inside a 2-CPU set does not saturate the pool). A spurious un-pin is harmless. */
        const int sat = busy >= popc(s_set_pool) - 0.5;
        if (f == last_f) stuck++; else stuck = 0;
        if ((stuck >= 2 && sat) || (stuck >= 3 && f > 0)) {
            extern int ps5_each_thread(void (*fn)(uintptr_t pthr));   /* ps5_shims.c */
            s_pin_on = 0;
            const int n = ps5_each_thread(pin_undo_one);
            ps5_set_mask(s_pin_allowed);
            printf("[ps5] pin: WATCHDOG: no frame for %.0f s with %.1f CPUs busy (pool %d): %d threads back on 0x%llx\n",
                   2 * (wall - last_wall), busy, popc(s_set_pool), n, s_pin_allowed);
        }
    }
    last_wall = wall; last_cpu = cpu; last_f = f;
}
static void place_threads(void)
{
    int ncpu = 0;
    size_t len = sizeof ncpu;
    if (sysctlbyname("hw.ncpu", &ncpu, &len, NULL, 0) != 0) ncpu = -1;
    unsigned long long m0 = 0;
    const int g = ps5_get_mask(&m0);
    int policy = -1;
    struct sched_param sp = { 0 };
    pthread_getschedparam(pthread_self(), &policy, &sp);
    printf("[ps5] threads: hw.ncpu %d; main thread CPUs 0x%llx (get %d, set size %zu), policy %d, priority %d\n",
           ncpu, m0, g, s_cpuset_size, policy, sp.sched_priority);
    const char* e = getenv("PS5_CPU_MASK");
    const unsigned long long want = e ? strtoull(e, NULL, 0) : 0x1fffull;
    if (!want) return;
    const int r = ps5_set_mask(want);
    unsigned long long now = 0; ps5_get_mask(&now);
    printf("[ps5] threads: main thread CPUs set to 0x%llx -> %d (now 0x%llx); new threads inherit it\n",
           want, r, now);
}
/* CPU cores the whole process used since the last call (user + system time over wall time). */
static double cores_used(void)
{
    static double last_cpu, last_wall;
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
    const double cpu = ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    const double wall = ts.tv_sec + ts.tv_nsec / 1e9;
    const double c = last_wall ? (cpu - last_cpu) / (wall - last_wall) : 0;
    last_cpu = cpu;
    last_wall = wall;
    return c;
}

/* Debug server (PS5_DEBUG_PORT): port 9990 only with the launcher's DIAGNOSTICS on (apply_launcher_settings);
 * with it off, none unless env.txt asks (PS5_DEBUG_PORT=9990); PS5_DEBUG_PORT=0 = never. No password: anyone on
 * the LAN can read guest memory and press buttons, so a release does not listen by default (2026-11-11).
 * A text protocol on the console's network so the running game can be inspected from the PC (any line-based TCP client). One client
 * at a time, one command per line:
 *   ping                      game name and uptime
 *   threads                   every guest thread, SPU context and event queue (the PS3_THREAD_DUMP dump)
 *   regs <tid>                one guest thread's registers (tid as "threads" prints it, decimal)
 *   spuregs <ctx>             one SPU context's pc, status and 128 registers (ctx = "spu ctxN")
 *   mem <ea> <len>            guest memory as hex, 16 bytes a line (len <= 1 MB; hex numbers)
 *   rmem <ea> <len>           the same raw: "OK <len>\n" then the bytes (len <= 64 MB)
 *   ls <ctx> <lsa> <len>      an SPU context's local store as hex (ctx = the dump's "spu ctxN")
 *   shot                      the next present writes a screenshot (logs/shot.NNN.ppm)
 *   prof                      a profiler report into the log now
 *   flush                     flush the log to disk
 * It never writes guest memory; pad / rec / play (below) do inject controller input. */
#include <sys/socket.h>
#include <netinet/in.h>
static const char* s_game_name = "?";
static time_t s_t0;
static int dbg_send(int fd, const void* p, size_t n)
{
    const char* c = (const char*)p;
    while (n) {
        const ssize_t w = send(fd, c, n, 0);
        if (w <= 0) return -1;
        c += w; n -= (size_t)w;
    }
    return 0;
}
static int dbg_printf(int fd, const char* fmt, ...)
{
    char b[512];
    va_list ap;
    va_start(ap, fmt);
    const int n = vsnprintf(b, sizeof b, fmt, ap);
    va_end(ap);
    return dbg_send(fd, b, n < 0 ? 0 : (size_t)(n < (int)sizeof b ? n : (int)sizeof b - 1));
}
static int dbg_hex(int fd, const uint8_t* base, uint32_t ea, uint32_t len)
{
    char line[96];
    for (uint32_t o = 0; o < len; o += 16) {
        int n = snprintf(line, sizeof line, "%08X:", ea + o);
        for (uint32_t k = 0; k < 16 && o + k < len; k++) n += snprintf(line + n, sizeof line - n, " %02X", base[o + k]);
        line[n++] = '\n';
        if (dbg_send(fd, line, (size_t)n)) return -1;
    }
    return 0;
}
static char s_root[64];   /* defined below (tentative definition) */
static void dbg_command(int fd, char* cmd)
{
    unsigned a = 0, b = 0, c = 0;
    if (!strcmp(cmd, "ping")) {
        dbg_printf(fd, "pong %s up %lds\n", s_game_name, (long)(time(NULL) - s_t0));
    } else if (!strcmp(cmd, "threads")) {
        extern void ps3_thread_dump_to(FILE*, const char*);
        FILE* f = fopen(s_dbg_dump, "w");
        if (!f) { dbg_printf(fd, "ERR cannot open the dump file\n"); return; }
        ps3_thread_dump_to(f, "debug server");
        fclose(f);
        f = fopen(s_dbg_dump, "r");
        if (!f) { dbg_printf(fd, "ERR cannot reopen the dump file\n"); return; }
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof buf, f)) > 0) if (dbg_send(fd, buf, n)) break;
        fclose(f);
    } else if (sscanf(cmd, "regs %u", &a) == 1 || sscanf(cmd, "spuregs %u", &b) == 1) {
        extern int ps3_thread_regs_to(FILE*, int);
        extern int spu_ctx_regs_to(FILE*, int);
        FILE* f = fopen(s_dbg_dump, "w");
        if (!f) { dbg_printf(fd, "ERR cannot open the dump file\n"); return; }
        const int ok = !strncmp(cmd, "spuregs", 7) ? spu_ctx_regs_to(f, (int)b) : ps3_thread_regs_to(f, (int)a);
        fclose(f);
        if (!ok) { dbg_printf(fd, "ERR no such live thread\n"); return; }
        f = fopen(s_dbg_dump, "r");
        if (!f) { dbg_printf(fd, "ERR cannot reopen the dump file\n"); return; }
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof buf, f)) > 0) if (dbg_send(fd, buf, n)) break;
        fclose(f);
    } else if (sscanf(cmd, "mem %x %x", &a, &b) == 2) {
        if (!s_guest_base || b > (1u << 20) || (uint64_t)a + b > 0x100000000ull) { dbg_printf(fd, "ERR range\n"); return; }
        dbg_hex(fd, s_guest_base + a, a, b);
    } else if (sscanf(cmd, "rmem %x %x", &a, &b) == 2) {
        if (!s_guest_base || b > (64u << 20) || (uint64_t)a + b > 0x100000000ull) { dbg_printf(fd, "ERR range\n"); return; }
        if (dbg_printf(fd, "OK %u\n", b) == 0) dbg_send(fd, s_guest_base + a, b);
        return;
    } else if (sscanf(cmd, "ls %u %x %x", &a, &b, &c) == 3) {
        extern const uint8_t* spu_ctx_ls(int);
        const uint8_t* ls = spu_ctx_ls((int)a);
        if (!ls || b >= 0x40000u || c > 0x40000u - b) { dbg_printf(fd, "ERR no such context or range\n"); return; }
        dbg_hex(fd, ls + b, b, c);
    } else if (!strcmp(cmd, "shot")) {
        extern int g_vk_dump_now;
        g_vk_dump_now = 1;
        dbg_printf(fd, "OK the next present writes logs/shot.NNN.ppm\n");
    } else if (!strcmp(cmd, "prof")) {
        prof_report();
        fflush(stdout);
        dbg_printf(fd, "OK in the log\n");
    } else if (!strcmp(cmd, "flush")) {
        fflush(stdout); fflush(stderr); fsync(s_log_fd);
        dbg_printf(fd, "OK\n");
    } else if (!strncmp(cmd, "pad ", 4)) {
        /* pad <mask> [polls] [lx ly rx ry]: mask as PAD_SCRIPT (DIGITAL2 << 8 | DIGITAL1); sticks
         * 0..255, -1 leaves one alone (tools/patch_devpad.py) */
        extern void ps3_devpad_press(unsigned, int, int, int, int, int);
        unsigned m = 0; int polls = 6, lx = -1, ly = -1, rx = -1, ry = -1;
        if (sscanf(cmd + 4, "%x %d %d %d %d %d", &m, &polls, &lx, &ly, &rx, &ry) < 1) { dbg_printf(fd, "ERR pad <mask> [polls] [lx ly rx ry]\n"); return; }
        ps3_devpad_press(m, polls, lx, ly, rx, ry);
        dbg_printf(fd, "OK\n");
    } else if (!strncmp(cmd, "rec", 3) || !strncmp(cmd, "play", 4)) {
        /* rec <file> | rec off ; play <file> | play off (files under the game's logs folder) */
        extern int ps3_devpad_record(const char*);
        extern int ps3_devpad_replay(const char*);
        const int rec = cmd[0] == 'r';
        const char* arg = cmd + (rec ? 3 : 4);
        while (*arg == ' ') arg++;
        char path[400] = "";
        if (*arg && strcmp(arg, "off")) {
            if (strchr(arg, '/') || strstr(arg, "..")) { dbg_printf(fd, "ERR a plain file name\n"); return; }
            snprintf(path, sizeof path, "%s/logs/%s", s_root, arg);
        }
        const int r = rec ? ps3_devpad_record(path[0] ? path : NULL) : ps3_devpad_replay(path[0] ? path : NULL);
        dbg_printf(fd, r ? "ERR cannot open %s\n" : "OK %s\n", path[0] ? path : "off");
        if (r) return;
    } else {
        dbg_printf(fd, "ERR commands: ping threads regs spuregs mem rmem ls shot prof flush pad rec play\n");
        return;
    }
    dbg_printf(fd, ".\n");   /* end of the reply */
}
static void* dbg_server(void* arg)
{
    const int port = (int)(intptr_t)arg;
    const int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) { printf("[ps5] debug server: socket failed (%d)\n", errno); return NULL; }
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in sa;
    memset(&sa, 0, sizeof sa);
    sa.sin_len = sizeof sa;
    sa.sin_family = AF_INET;
    sa.sin_port = (uint16_t)(((port & 0xFF) << 8) | ((port >> 8) & 0xFF));   /* network order */
    sa.sin_addr.s_addr = 0;                                                 /* any address */
    if (bind(s, (struct sockaddr*)&sa, sizeof sa) != 0 || listen(s, 2) != 0) {
        printf("[ps5] debug server: bind/listen on port %d failed (%d)\n", port, errno);
        close(s);
        return NULL;
    }
    printf("[ps5] debug server listening on port %d\n", port);
    for (;;) {
        const int c = accept(s, NULL, NULL);
        if (c < 0) { sleep(1); continue; }
        char buf[512];
        size_t have = 0;
        for (;;) {
            const ssize_t r = recv(c, buf + have, sizeof buf - 1 - have, 0);
            if (r <= 0) break;
            have += (size_t)r;
            buf[have] = 0;
            char* nl;
            while ((nl = strchr(buf, '\n'))) {
                *nl = 0;
                if (nl > buf && nl[-1] == '\r') nl[-1] = 0;
                if (!strcmp(buf, "quit")) { have = 0; goto done; }
                dbg_command(c, buf);
                have -= (size_t)(nl + 1 - buf);
                memmove(buf, nl + 1, have + 1);
            }
            if (have >= sizeof buf - 1) have = 0;   /* an over-long line: drop it */
        }
    done:
        close(c);
    }
    return NULL;
}

/* Status line every 15 s: uptime and the memory budgets that are the likeliest to run out. The frame
 * rate is in the renderer's own "[rsx fps]" lines, the controller in PAD_TRACE's. The log is also
 * pushed to the disk every 10 s (fsync), so a console that goes down keeps all but the last few. */
static void* status_thread(void* arg)
{
    (void)arg;
    extern void ps3_host_thread_label(const char* name);
    ps3_host_thread_label("ps5 status");
    const time_t t0 = time(NULL);
    for (unsigned s = 1;; s++) {
        sleep(1);
        fflush(stdout);
        fflush(stderr);
        if (s % 10 == 0) fsync(s_log_fd);
        pin_watchdog();   /* ps5 pin */
        if (s % 15) continue;
        size_t flex = 0, dmem = 0;
        int64_t at = 0;
        sceKernelAvailableFlexibleMemorySize(&flex);
        sceKernelAvailableDirectMemorySize(0, sceKernelGetDirectMemorySize(), PS5_KERNEL_DIRECT_ALIGNMENT, &at, &dmem);
        printf("[ps5] status: up %lds, CPU %.2f cores, flexible memory free %zu MB, direct memory largest free block %zu MB\n",
               (long)(time(NULL) - t0), cores_used(), flex >> 20, dmem >> 20);
        prof_report();
        extern void ps5_waitprof_report(double secs);
        ps5_waitprof_report(15.0);
    }
    return NULL;
}

static void env_default(const char* k, const char* v)
{
    if (!getenv(k)) setenv(k, v, 1);
}

/* env.txt: one VAR=value per line, '#' comments; set as given (the defaults below fill the rest). */
static void load_env_file(const char* path)
{
    FILE* f = fopen(path, "r");
    if (!f) return;
    char line[512];
    while (fgets(line, sizeof line, f)) {
        char* s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (*s == '#' || *s == '\n' || *s == '\r' || !*s) continue;
        s[strcspn(s, "\r\n")] = 0;
        char* eq = strchr(s, '=');
        if (!eq || eq == s) continue;
        *eq = 0;
        setenv(s, eq + 1, 1);
        printf("[ps5] env.txt: %s=%s\n", s, eq + 1);
    }
    fclose(f);
}

/* Where this game's files are. inFamous: ReCharged (one app, PPSA95463) keeps each game in its own
 * folder -- /app0/if1, /app0/if2, /app0/fob: game/, cache/, logs/, env.txt -- and its launcher
 * (eboot.bin) starts if1.bin / if2.bin / fob.bin. Built for one game (PS5_GAME_DIR, from
 * ps5link.sh); without that folder the program is a single-game app with everything in /app0
 * (the separate test apps PPSA95460-62). */
#ifndef PS5_GAME_DIR
#define PS5_GAME_DIR "if2"
#endif
static char s_root[64] = APP;   /* /app0 or /app0/<game dir> */
static char s_path_buf[16][160];
static int s_path_n;
/* s_root + suffix, in one of 16 kept buffers (the environment keeps the pointers setenv copies). */
static const char* rootp(const char* suffix)
{
    char* b = s_path_buf[s_path_n++ & 15];
    snprintf(b, sizeof s_path_buf[0], "%s%s", s_root, suffix);
    return b;
}

/* The launcher's choices (/app0/launcher.ini, key = value), as this game's settings. env.txt still
 * wins: these only fill what it left unset. */
static int s_dlc = 1;   /* launcher DLC COSTUMES (ini dlc): the DLC unlock files, see ps5_dlc_unlocks */
static void apply_launcher_settings(void)
{
    FILE* f = fopen(APP "/launcher.ini", "r");
    char line[256], lang[16] = "";
    /* The defaults = the launcher's first-run ones (launcher.c RELEASE_DEFAULTS, 2026-11-11): diagnostics 0,
     * fps_counter 0, no movie skipped. They stand for a key the file hasn't and for no file at all (was: no
     * file = nothing applied, so the profilers and diagnostic logging ran). Rule: profilers / ftrace / frame
     * dumps only with diagnostics = 1 in the file (or set in env.txt). */
    int skip_intro = 0, skip_movies = 0, gpu = 1, diag = 0, fps = 0, fg = 0, ups = 1, look = 0, aa = 1, aniso = 16, ds = 1, sharp = 0;   /* ds: DualSense extras (quick menu) */   /* look: vk look 0/1/2 */   /* ups: upscaler, 1 FSR 1 / 0 bilinear */   /* fg: frame generation (off: ghosting at 25 fps, 2026-11-07) */   /* fps: the counter, 0 off / 1 simple / 2 detailed */
    while (f && fgets(line, sizeof line, f)) {
        char key[64]; int v = 0; char sv[32];
        if (sscanf(line, " %63[a-z_] = %d", key, &v) == 2) {
            if (!strcmp(key, "skip_intro")) skip_intro = v;
            else if (!strcmp(key, "skip_movies")) skip_movies = v;
            else if (!strcmp(key, "gpu_effects")) gpu = v;
            else if (!strcmp(key, "diagnostics")) diag = v;
            else if (!strcmp(key, "fps_counter")) fps = v < 0 ? 0 : v > 2 ? 2 : v;
            else if (!strcmp(key, "frame_generation")) fg = v != 0;
            else if (!strcmp(key, "upscaler")) ups = v != 0;
            else if (!strcmp(key, "anti_aliasing")) aa = v == 2 ? 2 : v != 0;   /* 0 off, 1 FXAA, 2 SMAA */
            else if (!strcmp(key, "dualsense")) ds = v != 0;
            else if (!strcmp(key, "aniso")) aniso = v == 1 ? 16 : v;   /* 0 / 2 / 4 / 8 / 16 (1 = the old "on" = 16) */
            else if (!strcmp(key, "sharpness")) sharp = v;   /* 0 high / 1 medium / 2 low */
            else if (!strcmp(key, "look")) look = v < 0 ? 0 : v > 11 ? 11 : v;
            else if (!strcmp(key, "dlc")) s_dlc = v != 0;
        } else if (sscanf(line, " language = %15s", sv) == 1) {
            snprintf(lang, sizeof lang, "%s", sv);
        }
    }
    if (f) fclose(f);
    printf("[ps5] launcher.ini%s: skip_intro=%d skip_movies=%d gpu_effects=%d diagnostics=%d fps_counter=%d language=%s\n",
           f ? "" : " (none: defaults)", skip_intro, skip_movies, gpu, diag, fps, lang[0] ? lang : "(default)");
    if (!diag) env_default("PS5_DEBUG_PORT", "0");   /* release: no LAN debug server unless diagnostics = 1 or env.txt sets it */
    { char v[4]; snprintf(v, sizeof v, "%d", fps); env_default("PS3_FPS_COUNTER", v); }   /* vk overlay (libs/video/vk_overlay.inc) */
    env_default("PS3_FRAMEGEN", fg ? "1" : "0");   /* vk framegen (libs/video/vk_framegen.cpp, MihawkGen) */
    printf("[ps5] frame generation %s (launcher), PS3_FRAMEGEN=%s in effect\n", fg ? "on" : "off", getenv("PS3_FRAMEGEN") ? getenv("PS3_FRAMEGEN") : "?");
    env_default("PS3_UPSCALER", ups ? "1" : "0");
    env_default("PS3_AA", aa == 2 ? "2" : aa ? "1" : "0");   /* vk smaa: 2 */
    env_default("PS3_DUALSENSE", ds ? "1" : "0");   /* ds rumble / ds light (libs/input/cellPad.c) */   /* vk aa (vk_fsr.inc) */
    { char a[8]; snprintf(a, sizeof a, "%d", aniso > 16 ? 16 : aniso < 0 ? 0 : aniso); env_default("PS3_ANISO", a); }   /* vk aniso */
    env_default("PS3_FSR_SHARP", sharp == 2 ? "1.0" : sharp == 1 ? "0.5" : "0");   /* vk fsr RCAS stops (launcher SHARPNESS) */
    { char lk[4]; snprintf(lk, sizeof lk, "%d", look); env_default("PS3_LOOK", lk); }   /* vk looks: 0..11 */   /* vk look (libs/video/vk_fsr.inc) */   /* vk fsr (libs/video/vk_fsr.inc) */
    if (!diag) env_default("PS3RECOMP_SPIRV_MISS_DIR", "");   /* release: no logs/spvmiss/<key>.hlsl (up to 200 a run, never removed) */
    if (skip_movies) env_default("PS3_SKIP_MOVIES", "all");
    else if (skip_intro) env_default("PS3_SKIP_MOVIES", "intro");
    if (lang[0]) env_default("PS3_LANG", lang);
    if (!gpu) { env_default("PS3RECOMP_ENG_GPU_LIGHT", ""); env_default("PS3RECOMP_ENG_GPU_SSAO", ""); }
    if (!diag) { env_default("PS3_FTRACE", ""); env_default("PS3RECOMP_VK_DUMP", "");
                 env_default("PS5_WAITPROF", "0"); env_default("PS5_PROFILE", "0"); }   /* release: no wait/SIGPROF profilers (2026-11-10 audit) */
    /* PS5_CPUMAP is NOT switched on with diagnostics (t34 review, finding 1: the probe moves the main thread over every CPU and was
     * never run on a console). For one dedicated run: PS5_CPUMAP=1 in the game's env.txt. */
    if (diag) env_default("PS3_SNAP_DIR", rootp("/logs"));   /* snap combo (SELECT+R3 held): only with diagnostics = 1, see ps5_app_setup */
}

/* The game's own EBOOT.elf is built into this program (ps5link.sh: ps5_eboot.S, .incbin of the decrypted
 * EBOOT the port was made from), so the installer needs no keys or licence files: it is written to
 * game/PS3_GAME/USRDIR/EBOOT.elf here when that file is missing or differs (a byte compare, ~10 MB). */
extern const unsigned char ps5_eboot_start[] __attribute__((weak));
extern const unsigned char ps5_eboot_end[] __attribute__((weak));
/* DLC costumes and powers (inFAMOUS 2, FoB): the game unlocks each one when its file exists in
 * /dev_hdd0/game/<dir>/USRDIR/dlc/ulf (it stats it, asks sceNpDrm, opens it; an empty file does, BC-250
 * logs 2026-11-08). The launcher's DLC COSTUMES setting: on = the files are made here at start, off = our
 * empty ones are removed (a real one, like FoB's own unlock_review.edat, is never touched). Not the
 * reviewer unlock-all (unlock_review) nor the UGC betas. inFAMOUS 1 has no DLC files. */
static void ps5_dlc_unlocks(void)
{
    const char* dir = !strcmp(PS5_GAME_DIR, "if2") ? "BCUS98125" : !strcmp(PS5_GAME_DIR, "fob") ? "NPUA80657" : NULL;
    if (!dir) return;
    static const char* const names[] = { "lightning_hook", "sniper_blast", "electrocution_grenade", "stalker_grenade",
        "kessler_skin", "infamous_cole_skin", "gold_amp", "bonus_minis", "skin_pack_1", "kevin_butler_skin", "reaper_skin",
        "zombie_skin", "amp_1_skin", "amp_2_skin", "amp_3_skin", "bonus_1_skin", "bonus_2_skin", "bonus_3_skin", "bonus_4_skin",
        "bonus_5_skin", "bonus_6_skin", "bonus_7_skin", "bonus_8_skin", "bonus_9_skin", "bonus_10_skin" };
    char p[256];
    static const char* const parts[] = { "/game/dev_hdd0", "/game/dev_hdd0/game", "", "/USRDIR", "/USRDIR/dlc", "/USRDIR/dlc/ulf" };
    if (s_dlc)
        for (int i = 0; i < 6; i++) {
            if (i < 2) snprintf(p, sizeof p, "%s%s", s_root, parts[i]);
            else snprintf(p, sizeof p, "%s/game/dev_hdd0/game/%s%s", s_root, dir, parts[i]);
            mkdir(p, 0777);
        }
    int made = 0, removed = 0;
    for (size_t i = 0; i < sizeof names / sizeof names[0]; i++) {
        snprintf(p, sizeof p, "%s/game/dev_hdd0/game/%s/USRDIR/dlc/ulf/unlock_%s.edat", s_root, dir, names[i]);
        struct stat st;
        const int have = stat(p, &st) == 0;
        if (s_dlc && !have) { FILE* f = fopen(p, "wb"); if (f) { fclose(f); made++; } }
        else if (!s_dlc && have && st.st_size == 0 && unlink(p) == 0) removed++;
    }
    printf("[ps5] DLC costumes %s (launcher): %d unlock files made, %d removed\n", s_dlc ? "on" : "off", made, removed);
}

static void ps5_put_eboot(const char* path)
{
    if (!ps5_eboot_start || !ps5_eboot_end || ps5_eboot_end <= ps5_eboot_start) { printf("[ps5] eboot: none built in\n"); return; }
    const size_t n = (size_t)(ps5_eboot_end - ps5_eboot_start);
    FILE* f = fopen(path, "rb");
    if (f) {
        static unsigned char buf[1 << 20];
        size_t off = 0, r;
        int same = 1;
        while (same && (r = fread(buf, 1, sizeof buf, f)) > 0) {
            if (off + r > n || memcmp(buf, ps5_eboot_start + off, r)) same = 0;
            off += r;
        }
        fclose(f);
        if (same && off == n) return;
    }
    char tmp[200];
    snprintf(tmp, sizeof tmp, "%s.new", path);
    FILE* w = fopen(tmp, "wb");
    if (!w || fwrite(ps5_eboot_start, 1, n, w) != n) { if (w) fclose(w); printf("[ps5] eboot: can't write %s\n", tmp); return; }
    fclose(w);
    if (rename(tmp, path)) { printf("[ps5] eboot: can't rename %s (%d)\n", tmp, errno); return; }
    printf("[ps5] eboot: wrote the built-in EBOOT.elf (%zu bytes) to %s\n", n, path);
}

void ps5_app_setup(int* argc, char*** argv)
{
    {   struct stat st;
        if (stat(APP "/" PS5_GAME_DIR "/game", &st) == 0) snprintf(s_root, sizeof s_root, APP "/" PS5_GAME_DIR); }
    mkdir(rootp("/logs"), 0777);
    snprintf(s_dbg_dump, sizeof s_dbg_dump, "%s/logs/dbg_dump.txt", s_root);
    /* The log is named after the game: infamous.log, infamous2.log, infamousfob.log (from the build's
     * game, or in a single-game app the title id in sce_sys/param.json); the previous run's is kept
     * as <name>.prev.log. Both streams append: with stdout opened "w" it wrote at its own offset,
     * over the lines stderr had added. */
    const char* game = !strcmp(PS5_GAME_DIR, "if1") ? "infamous" : !strcmp(PS5_GAME_DIR, "fob") ? "infamousfob" : "infamous2";
    FILE* pj = strcmp(s_root, APP) ? NULL : fopen(APP "/sce_sys/param.json", "r");
    if (pj) {
        char buf[4096];
        const size_t n = fread(buf, 1, sizeof buf - 1, pj);
        buf[n] = 0;
        fclose(pj);
        if (strstr(buf, "PPSA95461")) game = "infamousfob";
        else if (strstr(buf, "PPSA95462")) game = "infamous";
        else if (strstr(buf, "PPSA95460")) game = "infamous2";
    }
    /* Game groups (user, 2026-11-08): inFAMOUS 2 and Festival of Blood share one engine and get the SAME
     * defaults (G_IF2FAM); inFAMOUS 1 is its own game (G_IF1). A default goes on one group's line only, so a
     * change for 2/FoB never touches 1 and the reverse. DONTFLIP: do not merge the groups again. */
    const int G_IF1 = !strcmp(game, "infamous");
    const int G_IF2FAM = !strcmp(game, "infamous2") || !strcmp(game, "infamousfob");
    char log[160], prev[160];
    snprintf(log, sizeof log, "%s/logs/%s.log", s_root, game);
    snprintf(prev, sizeof prev, "%s/logs/%s.prev.log", s_root, game);
    rename(log, prev);
    /* freopen, not open + dup2 onto 1 and 2: on the console the latter left the log empty (the
     * PS5's stdout/stderr do not write through descriptors 1 and 2). */
    /* Both line-buffered: one write per line. Unbuffered, the console's stderr writes a character
     * at a time at about 1 ms each, with the stream lock held across the line: the ninth console
     * run's self-test managed ~10 lines a second from four threads, and every earlier run looked
     * like a crash where the second guest thread began to log and the two queued on the stream.
     * The crash report does not go through stdio.
     * With a NULL buffer of size 0 the console's libc still wrote unbuffered (the 31 Oct logs break
     * every line at each printf conversion, other threads' text in between), so each line cost a
     * write per segment with the stream lock held. Now our own 64 KB buffers, fully buffered, and
     * the status thread flushes both every second (PS5_LOG_LINEBUF=1: line-buffered instead). */
    {
        static char outbuf[1 << 16], errbuf[1 << 16];
        const int mode = getenv("PS5_LOG_LINEBUF") && *getenv("PS5_LOG_LINEBUF") == '1' ? _IOLBF : _IOFBF;
        if (freopen(log, "a", stdout)) setvbuf(stdout, outbuf, mode, sizeof outbuf);
        if (freopen(log, "a", stderr)) setvbuf(stderr, errbuf, mode, sizeof errbuf);
    }
    if (fileno(stderr) >= 0) s_log_fd = fileno(stderr);
    crash_selftest();
    install_crash_handler();

    load_env_file(rootp("/env.txt"));
    if (strcmp(s_root, APP)) printf("[ps5] inFamous: ReCharged layout: this game's files are in %s\n", s_root);
    apply_launcher_settings();   /* first: diagnostics=0 turns the profilers off (PS5_WAITPROF/PS5_PROFILE) */
    {   /* the wait report (ps5_shims.c): this thread goes on to run the RSX FIFO and present */
        extern void ps5_waitprof_enable(int on);
        extern void ps3_host_thread_label(const char* name);
        ps5_waitprof_enable(!(getenv("PS5_WAITPROF") && !strcmp(getenv("PS5_WAITPROF"), "0")));
        ps3_host_thread_label("host main / rsx");
    }
    mkdir(rootp("/game/dev_hdd0"), 0777);
    mkdir(rootp("/game/gamedata"), 0777);
    mkdir(rootp("/cache"), 0777);
    mkdir(rootp("/cache/shaders"), 0777);

    /* Paths (run.sh's). */
    env_default("PS3_VFS_ROOT", rootp("/game"));
    env_default("PS3_HDD0_ROOT", rootp("/game/dev_hdd0"));
    env_default("PS3_DEV_FLASH", rootp("/game/dev_flash"));
    env_default("PS3_GAMEDATA_ROOT", rootp("/game/gamedata"));
    env_default("PS3_TITLE", "inFAMOUS 2");
    env_default("PS3_LANG", "en");
    /* Renderer: the shared draw engine on the Vulkan backend, the game's own shaders. */
    env_default("PS3RECOMP_RSX_ENGINE", "dispatch");
    env_default("PS3RECOMP_VK_GUEST_PROGRAMS", "1");
    env_default("PS3RECOMP_SPIRV_CACHE", rootp("/cache/shaders"));
    /* RADV's compiled-shader cache (radv_ps5_platform.c sets /app0/radv-shader-cache unless set). */
    env_default("MESA_SHADER_CACHE_DIR", rootp("/radv-shader-cache"));
    /* run.sh's game settings. */
    env_default("GCM_SEMA_ACQUIRE", "1");
    env_default("GCM_SEMA_ACQUIRE_MS", "200");
    env_default("GCM_PARK_GRACE_MS", "1000");
    env_default("PS3_ASPECT_HUD_AFTER", "136d0d1989147bd8");
    /* The console's output is stereo: inFAMOUS 1, told 5.1/7.1 exists, mixed for surround speakers
     * and our 7.1 -> stereo fold lost its side and rear placement (left sounds heard only far left,
     * the image leaning right). Told stereo, it pans for two speakers itself, as on a PS3 with a
     * stereo output. inFAMOUS 1 only (measured); PS3_AUDIO_OUT_CH= (empty) in env.txt = as before. */
    if (!strcmp(game, "infamous")) env_default("PS3_AUDIO_OUT_CH", "2");
    /* inFAMOUS 1's second SPURS instance (the WWS job manager, group 0x1001) gets 2 SPUs instead of 1
     * (tools/if1_spurs2_spus.py): its one SPU (8197) was the console's critical path at 97-98% busy.
     * BC-250 spawn: 8197 79.5% -> 53.8% + 27.4% on the new SPU, same picture. PS3_IF1_SPURS2_SPUS=
     * (empty) in env.txt = 1 SPU as before. */
    if (!strcmp(game, "infamous")) env_default("PS3_IF1_SPURS2_SPUS", "2");
    /* inFAMOUS 1's gameplay SPURS instance (group 0x1000) on 8 SPUs instead of 5 (tools/if1_spurs1_spus.py
     * + the runtime's PS3_SPU_GROUP_CAP): its job batches are throughput-bound (console trace 11-04/11-06:
     * all 5 busy at once ~46% of the time, none ~24%), the main PPU thread waits on them 20-60% of each
     * frame, and the console runs ~6.8 of its 13 CPUs. PS3_IF1_SPURS1_SPUS= (empty) in env.txt = 5. */
    if (!strcmp(game, "infamous")) { env_default("PS3_IF1_SPURS1_SPUS", "6")   /* 2026-11-11: 7th SPU = 0.22 thread, 87% waiting, 15.5k wakes/s on the console; BC 6 = 7 */; env_default("PS3_SPU_GROUP_CAP", "8");   /* 7 (2026-11-10, 13 thr BC: 8 -> 29.0, 7 -> 30.9, 6 -> 30.9, 5 -> 27.7 fps; the 8th never got work on the console) */
                                      /* SPURS_MAXCONT_FIX=5:8 (+ the per-SPU priority fill) HANGS the load: the
                                       * game's job manager keeps per-SPU state for 5 SPUs (BC-250 2/2 hangs,
                                       * 2026-11-07). Off. */ }
    /* (if2 and FoB too since 2026-11-07: BC-250 if2 boat deck 56 -> 59.6 fps, FoB Pyre Night 21.0 -> 22.2, pictures checked.)
     * The backend's Vulkan recording on its own thread (libs/video/rsx_be_async.c): ~40% of the RSX thread's
     * per-draw work moves to one of the console's idle cores (no gain on the BC-250 only because that box
     * has none). Picture checked on the night save, 0 snapshot mismatches. PS3RECOMP_BE_ASYNC=0 = old. */
    if (G_IF1) env_default("PS3RECOMP_BE_ASYNC", "1");
    if (G_IF2FAM) env_default("PS3RECOMP_BE_ASYNC", "1");
    /* A SPURS event-flag wait over 150 ms re-kicks the parked SPU kernels (runtime/syscalls/sys_event.c
     * "evq kick"): the lost wake-up behind the logo boot hang, streaming stalls and falling through unloaded
     * collision. "[evq kick]" lines count them. PS3_EVQ_KICK_MS=0 = off. */
    env_default("PS3_EVQ_KICK_MS", "150");
    /* spu call fast (inline return check after a lifted call): job replay harness 2026-11-05, 60 captured
     * if1 jobs: -8.2% cycles, outputs byte-identical. if1 only until if2/FoB are measured. */
    if (!strcmp(game, "infamous")) env_default("PS3_SPU_CALL_FAST", "1");
    /* if2: 40 captured ovl-210 jobs (work/jr_ab_if2.sh, 2026-11-08): 9.06 -> 8.69 Mcycles (-4.1%), byte-identical.
     * if2 only (FoB not measured yet). PS3_SPU_CALL_FAST=0 in env.txt = off. */
    if (G_IF2FAM) env_default("PS3_SPU_CALL_FAST", "1");
    /* FoB: 60 captured ovl-208 jobs: 1.618 -> 1.573 Mcycles (-2.8%), byte-identical (2026-11-08). */
    /* inFAMOUS 1's sun-shadow cascades: front faces culled, no polygon offset -> a wall facing away from
     * the sun meets its own depth; a small compare bias removes the acne (blue dot grids on shaded walls,
     * 2026-11-05, tools/patch_shadow_bias.py). */
    if (!strcmp(game, "infamous")) env_default("PS3RECOMP_ENG_SHADOW_BIAS", "0.001");
    /* ...and its sun-shadow map (depth target 0F340000) drawn with the opposite winding: without it the
     * faces turned away from the sun fail their own test and lose the sky light (black walls with blue
     * arcs, Cole a black silhouette from behind; the real PS3 video has them lit). tools/patch_cull_flip_zeta.py,
     * 2026-11-05. PS3RECOMP_ENG_CULL_FLIP_ZETA= (empty) in env.txt = as before. */
    if (!strcmp(game, "infamous")) env_default("PS3RECOMP_ENG_CULL_FLIP_ZETA", "0F340000");
    /* ...and shadow casters under 2 map texels skipped (tools/patch_eng_shadow_cull.py): ~16% of the plain
     * caster draws on the route, mostly the far cascade's specks; the RSX thread is the console's limit in
     * the dense streets (drain 80-100% of each second). PS3RECOMP_ENG_SHADOW_CULL= (empty) = all drawn. */
    if (!strcmp(game, "infamous")) env_default("PS3RECOMP_ENG_SHADOW_CULL", "0F340000:2:4");
    /* ...the far cascades (3rd pass on) at 4 texels: RSX drain 35.3 -> 33.7 ms/frame in an in-run A/B. And the
     * casters after the first of each pass replayed from it (tools/patch_eng_caster_fast.py): drain 36.0 ->
     * 30.3 ms/frame (-16%) in an in-run A/B, picture unchanged; =2 also skips their vertex fetch (patch_eng_caster_fast2.py): a further -6..-8% drain. PS3RECOMP_ENG_CASTER_FAST=0 = old. */
    if (!strcmp(game, "infamous")) env_default("PS3RECOMP_ENG_CASTER_FAST", "3");   /* t35: mode 3 = mode 2 with the content check kept (casterfix); verify: 698k taken, 0 MISMATCH */
    /* The unused legacy rsx_state machine fed only the methods with visible effects (channel methods < 0x200,
     * the back-end labels): drain 31.2 -> 27.6 ms/frame (-11.5%) in an in-run A/B (cellGcmSys.c "gcm legacy
     * lean", 2026-11-05). PS3_GCM_LEGACY_LEAN=0 = every method, as before. */
    if (G_IF1) env_default("PS3_GCM_LEGACY_LEAN", "1");
    if (G_IF2FAM) env_default("PS3_GCM_LEGACY_LEAN", "1");
    /* Audio threads above the game's FIFO 700 (cellAudio.c "audio ps5 prio": mixer + sceAudioOut feeder, 640), and
     * the feeder's silence padding counted in the log: the explosion crackle lead. PS3_AUDIO_PRIO=0 = 700. */
    /* DONTFLIP (audio tuning): PS3_AUDIO_PRIO / QUEUE / PACE and the spu 1001 priority are inFAMOUS 1 ONLY. As defaults for
     * every game they crashed inFAMOUS 2 (SPURS abort after the karma movie, 2026-11-08). See ~/inFamous/DONTFLIP.md. */
    if (!strcmp(game, "infamous")) env_default("PS3_AUDIO_PRIO", "640");
    /* inFAMOUS 1 audio (2026-11-09): the console delivers some blocks 100-150 ms late although the audio SPU is idle (a
     * scheduling stall); a 36-block (~190 ms) queue and a 1-block hold reserve bridge those with real audio instead of a
     * faded repeat (the "bass interference"). PS3_AUDIO_QUEUE=20 / PS3_AUDIO_HOLD_MIN=2 in env.txt = the 11-07 values. */
    /* if1 job-list wait (2026-11-09): the main thread's job-list poll (func_0041FC38 -> func_0041D028, 1/3 of the main
     * thread) waits 30 us between checks instead of spinning: on 5 cores (PS5-like) 16.4 -> 17.4 fps (+7%); the 11-05
     * "no gain" was measured on 8 free cores. PS3_IF1_JL_WAIT_US=0 = spin. */
    if (G_IF1) env_default("PS3_IF1_JL_WAIT_US", "30");
    if (!strcmp(game, "infamous")) { env_default("PS3_AUDIO_QUEUE", "36"); env_default("PS3_AUDIO_PACE", "8"); env_default("PS3_AUDIO_HOLD_MIN", "1"); }
    /* if2/FoB audio cut-outs (2026-11-10): the user's if2 log shows bursts of late blocks played as silence while fps falls
     * to 18-23 (89 late / 157 silence in 1315 s): QUEUE 8 + HOLD_MIN 2 leave 32 ms of slack. if1's 187 ms (QUEUE 36,
     * HOLD_MIN 1) ended them there. ONLY these two: no PS3_AUDIO_PRIO, no PACE, no spu 1001 priority (DONTFLIP: that set
     * crashed if2 after the karma movie). PS3_AUDIO_QUEUE=8 / PS3_AUDIO_HOLD_MIN=2 in env.txt = the old values. */
    if (G_IF2FAM) { env_default("PS3_AUDIO_QUEUE", "36"); env_default("PS3_AUDIO_HOLD_MIN", "1"); }
    /* flip cap (2026-11-10): the console's fps sits on whole-vblank plateaus (if1 21.8 / 25.0): a 34 ms frame waited for the
     * 3rd vblank (50 ms). GCM_FLIP_IMMEDIATE=2 completes the flip at present, never sooner than 33.3 ms after the last one
     * (main.cpp "flip cap"). env.txt GCM_FLIP_IMMEDIATE=0 = the old vblank-only flips. One line per game group. */
    if (G_IF1) env_default("GCM_FLIP_IMMEDIATE", "2");
    if (G_IF2FAM) env_default("GCM_FLIP_IMMEDIATE", "2");
    /* if1 brightness (2026-11-10, user: PS5 "way darker" than the PS3): output gamma 0.85 in the post pass (vk_fsr.inc
     * "vk gamma"; runs after FSR). PS3_VK_GAMMA=1 in env.txt = off. */
    if (G_IF1) env_default("PS3_VK_GAMMA", "0.85");
    /* if1 audio (2026-11-10): the RPCS3 "Unstable audio" patch blr's 13 Boomrang voice/level sites (stale levels to 15
     * callers; RPCS3 itself warns "Lightning sounds might be distorted") = the user's distortion on explosions/lightning.
     * Off now that the game has 13 threads: audio SPUs 13+7% -> 35+16% of a core, if1 29.9 -> 28.9 fps on the BC-250.
     * PS3_IF1_AUDIO_PATCH=1 in env.txt = the patch again. */
    if (G_IF1) env_default("PS3_IF1_AUDIO_PATCH", "0");
    /* vk stencil (2026-11-11): a real stencil plane for the engine's depth targets. inFAMOUS 2 / Festival of Blood tag
     * characters with stencil bit 0x80 and use it for the character shadow bias, the ambient term (x1.0 characters,
     * x0.35 world) and to clip per-character effects to the silhouette. Without it: faceted blue self-shadow and the
     * "black box" around shocked enemies / staked vampires / everyone in vampire vision (user footage I2PS5.mp4 2:34,
     * 11:48). inFAMOUS 1 is NOT given it (unverified there). PS3_VK_STENCIL=0 in env.txt = the old picture. */
    if (G_IF2FAM) env_default("PS3_VK_STENCIL", "1");
    /* if1 stencil (2026-11-11, agent_vpconf + BC A/B): inFAMOUS 1 tags its G-buffer with a 3-bit stencil ID (write mask
     * 0x07) and rewrites the colour target's alpha under stencil NOTEQUAL ref 4 mask 4; without a stencil plane the tagged
     * pixels (Cole) lost that alpha = the "Cole is darker/greyer" the user reported. BC: jacket/skin clearly brighter
     * (work/dbg/if1_cole.png), fps 30.4 vs 30.0 (stA/stB x2, no cost). Tag bits are 0x07 here, not if2's 0xE0.
     * PS3_VK_STENCIL=0 in env.txt = the old picture. */
    if (G_IF1) { env_default("PS3_VK_STENCIL", "1"); env_default("PS3_VK_STENCIL_TEXMASK", "07"); }
    /* occ query OFF (2026-11-11, t31 regression the user caught in 10 s: if2 new game, FBI agent scene after the comic):
     * with real occlusion queries (cellGcmSys.c "occ query", PS3_GCM_REPORT_MEM unset = 2) the lamp glare sprite is drawn
     * THROUGH characters standing in front of the lamp. 0 = no report written = no glare, the t30 picture. Do not turn
     * this back on until the BC-250 shows that scene (cut.sh, 187 s) clean with it. DONTFLIP. */
    if (G_IF2FAM) env_default("PS3_GCM_REPORT_MEM", "0");
    /* eng overlay bias (t33, 2026-11-11): inFAMOUS 2 / Festival of Blood draw decals, tram rails, wall trims and car detail as
     * overlay layers (depth test LEQUAL, no depth write, no polygon offset) separated from the surface below only by a
     * projection z scale of ~0.9999998 = 1.6-3 steps of the PS3's 24-bit depth. Our float depth path can be off by more, and
     * whole layers flipped on and off (owner clips 11-11 15:14 rails, 16:01 wall base). -8 steps for exactly those draws
     * (>= 2 colour targets, colour written, not inside an occlusion count). PS3RECOMP_ENG_OVERLAY_BIAS=0 in env.txt = old. */
    if (G_IF2FAM) { env_default("PS3RECOMP_ENG_OVERLAY_BIAS", "-8"); env_default("PS3RECOMP_ENG_OVERLAY_BIAS_MINRT", "2"); }
    /* overlay class test (2026-11-12, t35): the bias above let overlay layers that sit just behind a character pass the
     * depth test and REPLACE the character stencil class with 0 = dark bands on Cole's neck and dark blocks on his jacket
     * in close-ups (clean on a PS3; present since t33). A biased overlay is now drawn only where the class bits are
     * already 0 (world), so rails/streets keep the flicker fix. PS3RECOMP_ENG_OVERLAY_BIAS_CLASS0=0 in env.txt = t34. */
    /* =2 (t35b, review agent_c0review): only the character bit 0x80 rejects the overlay; world surfaces with other class
     * bits (0x20 on ordinary world materials in gameplay) keep their decals/rails/trims as on the PS3. =1 = any class bit. */
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_OVERLAY_BIAS_CLASS0", "2");
    /* t34 RSX-thread work (2026-11-11): the console's fps limit is the RSX command thread (if2; close second in if1). All three
     * read with getenv at their use site; each verified on the BC-250 with its counting mode (0 mismatches in 11-22M checks per
     * game): eng dirty = skip the render-state decode on draw-fast replays while no non-neutral register changed (44-74% of
     * replays); ba dedup = do not queue a backend state call whose bytes repeat the previous one (96% of state calls); vbuf
     * async = vertex-buffer creates no longer wait for the worker (19 waits/frame in slow console scenes). Off switches for
     * env.txt: PS3_ENG_DIRTY=0, PS3_BA_DEDUP=0, PS3_BA_VBUF_ASYNC=0. */
    if (G_IF2FAM) { env_default("PS3_ENG_DIRTY", "1"); env_default("PS3_BA_DEDUP", "1"); env_default("PS3_BA_VBUF_ASYNC", "1"); }
    if (G_IF1)    { env_default("PS3_ENG_DIRTY", "1"); env_default("PS3_BA_DEDUP", "1"); env_default("PS3_BA_VBUF_ASYNC", "1"); }
    /* ba idx ref (t34): draws whose index list lives in the engine's index memo pass a pointer through the proxy queue
     * instead of ~1.3 KB of indices (block tickets + deferred free keep the array alive until the worker has replayed the
     * draw). BC-250 verify mode (=2): 1.97M draws checked, 0 mismatched; independent review: no defect. =0 in env.txt = copy. */
    if (G_IF2FAM) env_default("PS3_BA_IDX_REF", "1");
    if (G_IF1)    env_default("PS3_BA_IDX_REF", "1");
    /* t35 (2026-11-12): each verified on the BC-250 with its own proof mode on all three games (0 mismatches: PS3_BA_VS_DELTA=2,
     * PS3_BA_REPLAY_OP=2, PS3RECOMP_ENG_DT_FETCHSKIP=2, PS3RECOMP_ENG_DRAW_FAST_N=8 + _VERIFY, PS3RECOMP_ENG_CASTER_VERIFY with
     * mode 3), then run for real: boot loops 8/8, watched with frame generation on. One line per game group (gate-per-game rule).
     * Off switches through env.txt: the same names with 0 (DRAW_FAST_N=1, CASTER_FAST=2, PS3_BA_KICK=96 PS3_BA_NOLOCK=0). */
    if (G_IF2FAM) { env_default("PS3_BA_VS_DELTA", "1"); env_default("PS3_BA_REPLAY_OP", "1");
                    env_default("PS3RECOMP_ENG_DT_FETCHSKIP", "1"); env_default("PS3RECOMP_ENG_DRAW_FAST_N", "8"); }
    /* t35 texdelta (2026-11-12): draws that miss the draw-fast template only on texture registers replay with re-resolved
     * units (verify mode 2: 0 mismatches all three games; RSX-thread instructions/frame if2 -6 %, fob -3 %). Own line per
     * group. PS3_ENG_DT_TEXDELTA=0 in env.txt = off. */
    if (G_IF2FAM) env_default("PS3_ENG_DT_TEXDELTA", "1");
    if (G_IF1)    env_default("PS3_ENG_DT_TEXDELTA", "1");
    if (G_IF1)    { env_default("PS3_BA_VS_DELTA", "1"); env_default("PS3_BA_REPLAY_OP", "1");
                    env_default("PS3_SPU_OVL_PREFIX", "1"); env_default("PS3_IF1_JL_SPIN_US", "50");
                    env_default("PS3_BA_KICK", "512"); env_default("PS3_BA_NOLOCK", "1"); }   /* hand-off as if2/fob; guard 2 in rsx_be_async.c */
    /* fg guard OFF (2026-11-11, t31 regression: with frame generation on, pink/purple blinking in the if2 intro cutscene,
     * Zeke's head). Before t31 the ghost guard ran for the neural method only; t31 made it run for the default
     * flow+mvwarp method too (vk_fgguard.inc, guard.comp copies the next real frame over the generated one: 20-30% of
     * the generated frames in that cutscene) and it was never watched on a console. 0 = the t30 behaviour. DONTFLIP
     * until the guard's copy is proven on the console (BC-250 measurement runs have frame generation off). All games. */
    env_default("PS3_FG_GUARD", "0");
    /* if1 main-thread waits (2026-11-11, console log of the user's heavy-play test): the main PPU thread is the wall
     * (0.91 busy) and spends ~20% of wall time in ~20,000 ps3_memkick_wait sleeps per second of 14-20 us, each ~5.5 us
     * of kernel on the PS5 (12-15% of the thread). A bounded 25 us spin on the kick generation before the sleep
     * (spu_coherency.c, self-stopping: it falls through to the timed wait). PS3_MK_SPIN_US=0 in env.txt = sleeps only. */
    if (G_IF1) env_default("PS3_MK_SPIN_US", "25");
    /* RSX thread = the wall in inFAMOUS 2 / FoB on the console (0.93-0.95 busy, 19-22k be-async worker wakes per second
     * at ~8-9 us each; FIFO decode 13%; user's heavy-play logs 2026-11-11). Bigger hand-off blocks without the per-op
     * producer lock (rsx_be_async.c "ba handoff"; single producer checked) and the whole-packet FIFO path
     * (cellGcmSys.c / rsx_dispatch.c "gcm fast2"; differential-tested against rsx_dispatch_method). BC-250: FoB RSX
     * thread 36.0 -> 33.5 ms/frame, if2 no change; 22 runs + a self-check soak clean. Old behaviour in env.txt:
     * PS3_BA_KICK=96 PS3_BA_NOLOCK=0 PS3_GCM_FAST_WORDS=0. NOT enabled: PS3_ENG_DIRTY (no gain), PS3_VK_SLAB_KEEP /
     * PS3_VK_TEX_POOL (unproven). */
    if (G_IF2FAM) { env_default("PS3_BA_KICK", "512"); env_default("PS3_BA_NOLOCK", "1"); env_default("PS3_GCM_FAST_WORDS", "2"); }
    /* if1 refraction: restored now that RSX signed blending is emulated; inFAMOUS 1's refraction shader writes offsets
     * biased around 0.5 (inFAMOUS 2's distortion writes them wrapped: the default mode). BC-250 route1 A/B 2026-11-08:
     * wrap mode streaked the frame, bias mode clean. PS3_IF1_REFRACTION=0 = the RPCS3 patch's "off" again. */
    /* DONTFLIP (if1 refraction): do NOT set PS3_IF1_REFRACTION=1 -- broke smoke, explosions and the start-screen effect on
     * the console (2026-11-08, user footage Veyra-2026-11-08-090311). See ~/inFamous/DONTFLIP.md. */
    /* (2026-11-08: OFF again -- with it on, the user's console footage showed smoke as flat grey cut-outs, blocky
     * patches on explosions and smeared edges; route1 on the BC-250 had none of those effects in view.) */
    if (!strcmp(game, "infamous")) env_default("PS3_VK_SIGNED_MODE", "bias");
    /* Read-modify-write draws (the decals: albedo + normals of the G-buffer they draw into) sample their own
     * targets inside the open pass after a by-region barrier, instead of two full-screen copies each with a
     * pass break (engine "eng rmw direct" + Vulkan self-dependency): drain -10.4% median in a paired in-run
     * A/B, picture unchanged. PS3RECOMP_ENG_RMW_DIRECT=0 = the copies. */
    if (G_IF1) env_default("PS3RECOMP_ENG_RMW_DIRECT", "2");
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_RMW_DIRECT", "2");
    /* t37 (2026-11-12 console bisect on t35b, inFAMOUS 2 street, user with env.txt): RMW_DIRECT=2 made the trolley rails
     * drop out (=0 fixed them). Cause (agent_railfix): the pvkCmdPipelineBarrier macro closes the open pass, so the
     * "in-pass" barrier ended it and the decal was drawn outside any render pass. PS3RECOMP_VK_RMW_INPASS=1 records the
     * barrier inside the pass (rsx_vulkan_backend.c "vk rmw inpass"; log "[RSX vulkan] engine: rmw inpass 1"). Fallback
     * if the rails still drop out: env.txt PS3RECOMP_ENG_RMW_DIRECT=0 (= the copies). DONTFLIP: RMW_DIRECT=2 without it. */
    if (G_IF2FAM) env_default("PS3RECOMP_VK_RMW_INPASS", "1");
    if (G_IF1) env_default("PS3RECOMP_VK_RMW_INPASS", "1");   /* t37 if1: decided after its console test (if1 also runs RMW_DIRECT=2) */
    /* Plain subchannel-0 NV4097 words straight to the draw engine (cellGcmSys.c "gcm fast words"; needs the
     * legacy lean): drain -4.9% median in a paired in-run A/B. PS3_GCM_FAST_WORDS=0 = the full per-word path. */
    if (G_IF1) env_default("PS3_GCM_FAST_WORDS", "1");
    if (G_IF2FAM) env_default("PS3_GCM_FAST_WORDS", "1");
    /* Index-memo key word-mixed + 8-lane sampled check, and the Vulkan descriptor-set signature check
     * ("eng micro"): drain -4.3% median / -5.1% mean in a paired in-run A/B (the 2026-11-05 "no gain" was the
     * noisy 4 s method), picture unchanged. PS3RECOMP_ENG_MICRO=0 = old. */
    if (G_IF1) env_default("PS3RECOMP_ENG_MICRO", "1");
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_MICRO", "1");
    /* Any draw whose state and sampled texture registers equal the previous full-path draw's replays its binds
     * (tools/patch_eng_draw_fast.py): ~64% of eligible non-shadow draws; drain -4.5% median in a paired
     * 120 s A/B, picture unchanged. PS3RECOMP_ENG_DRAW_FAST=0 = old. */
    if (G_IF1) env_default("PS3RECOMP_ENG_DRAW_FAST", "1");
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_DRAW_FAST", "1");
    /* Texture change hashes on a helper thread (tools/patch_eng_texhash_async.py; it sleeps on a condition
     * variable): 95% of the per-frame checks answered off the RSX thread, drain -8.4% median / -10.5% mean in
     * a paired 120 s A/B; a rewrite is seen 1-2 frames later. PS3RECOMP_ENG_TEXHASH_ASYNC=0 = old. */
    if (G_IF1) env_default("PS3RECOMP_ENG_TEXHASH_ASYNC", "1");
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_TEXHASH_ASYNC", "1");
    /* t37 (same bisect): TEXHASH_ASYNC=1 made the street manhole covers / crossing paint drop out for ~0.5 s (=0 fixed
     * them). PS3RECOMP_ENG_TEXHASH_SAFE=1 (agent_thfix): no sparse-only "unchanged" once the full hash is due + 8 frames of
     * full hashes after each upload (log "[texhash safe] on: ..."). Fallback if they still drop out: env.txt
     * PS3RECOMP_ENG_TEXHASH_ASYNC=0. DONTFLIP: TEXHASH_ASYNC=1 without it. */
    if (G_IF2FAM) env_default("PS3RECOMP_ENG_TEXHASH_SAFE", "1");
    if (G_IF1) env_default("PS3RECOMP_ENG_TEXHASH_SAFE", "1");   /* t37 if1: decided after its console test (if1 also runs TEXHASH_ASYNC=1) */
    /* inFAMOUS 2's light job on the GPU (the Vulkan backend's light_pass, toolkit edit "vk light"):
     * no per-frame write-back of normals and depth for the SPU job, no SPU lighting, no tile DMA.
     * inFAMOUS 2 only: gpu_light.c hooks its own job (image 219, LS 0x4AC8), which the other two
     * builds' image 219 need not be. PS3RECOMP_ENG_GPU_LIGHT= (empty) in env.txt puts the SPU job
     * back. Its SSAO job too (the Vulkan ssao_pass, toolkit edit "vk ssao"; needs the light pass):
     * PS3RECOMP_ENG_GPU_SSAO= (empty) puts it back on the SPUs. */
    if (!strcmp(game, "infamous2")) {
        env_default("PS3RECOMP_ENG_GPU_LIGHT", "07000B80:07384B80");
        env_default("PS3RECOMP_ENG_GPU_SSAO", "0F800000");
    }
    /* Festival of Blood: the same two jobs at FoB's ids (tools/fob_gpu_hooks.sh) and its own
     * normals/depth copies (its SSAO pass table names them). */
    if (!strcmp(game, "infamousfob")) {
        env_default("PS3RECOMP_ENG_GPU_LIGHT", "0703D780:073C1780");
        env_default("PS3RECOMP_ENG_GPU_SSAO", "0F800000");
    }
    /* The depth/normals copies are still written back with the SSAO on the GPU: something past
     * the two jobs reads them (FoB's PC run lost the night sky's clouds without, and had them
     * with; PROGRESS, 2026-10-31). PS3RECOMP_ENG_GPU_SSAO_WB=0 skips them (faster, A/B). */
    /* inFAMOUS 2: no write-back. On the console each write-back was a full GPU wait, twice a frame
     * in the world (flush site "line 2532" at 2/frame, 10-41 ms/s of waiting, PC-agent run
     * 2026-11-02 22:00), and with it the frames-in-flight present never ran: CPU and GPU took turns.
     * The BC-250 Linux runs have always been without it (run.sh does not set it) and match the
     * reference video (Beast smoke, clouds, 2026-11-03). PS3RECOMP_ENG_GPU_SSAO_WB=1 in env.txt
     * brings it back. FoB keeps it (its night sky's clouds read the copies). */
    env_default("PS3RECOMP_ENG_GPU_SSAO_WB", strcmp(game, "infamous2") ? "1" : "0");
    /* No reserve-the-low-4-GB diagnostic trap: it maps (and drops) 256 MB chunks of flexible memory. */
    env_default("PS3_NO_GUEST_PTR_TRAP", "1");
    /* A SPURS event-flag wait ("_spuEvF" queue) that has had nothing for 10 s prints the waiter's
     * registers and the flag / fios job table it waits on ([evq-stall] lines, tools/patch_evq_stall_dump.py):
     * the 2026-11-03 21:35 streaming stall was such a wait, for good. PS3_EVQ_STALL=0 turns it off. */
    env_default("PS3_EVQ_STALL", "10");
    /* The game's own PlayStation button glyphs. The port's "auto" follows the device last used and,
     * with no SDL controller seen yet, shows keyboard keys (the tenth console run). */
    env_default("PS3_BUTTON_ICONS", "playstation");
    /* vk quickmenu: the in-game menu writes its changes into the launcher's ini files (this game's and the last-played one) */
    env_default("PS3_QM_INI", APP "/launcher_" PS5_GAME_DIR ".ini:" APP "/launcher.ini");
    /* ds light: the game's colour on the DualSense light bar (Cole's blue; FoB's blood red) */
    env_default("PS3_LIGHTBAR", !strcmp(PS5_GAME_DIR, "fob") ? "200,16,24" : "40,110,255");
    /* Controller reads, once a second (calls, packets, buttons seen); PAD_TRACE=0 in env.txt turns it off. */
    env_default("PAD_TRACE", "1");
    if (!strcmp(getenv("PAD_TRACE"), "0")) unsetenv("PAD_TRACE");
    /* The runtime's per-wait / per-event lines (ps3_log.h) default to on whenever stderr is not a
     * terminal, which on the console is always, at thousands of lines a second once SPURS runs.
     * PS3_VERBOSE=1 in env.txt brings them back. */
    env_default("PS3_VERBOSE", "0");
    /* The frame timeline (include/ps3emu/ps3_ftrace.h): who waits for whom, SPU busy/wait spans, the
     * RSX's drains and the Vulkan backend's GPU waits, 60 s from 120 s in (all three games are in
     * the world by then; 60-90 s caught only menus and loading), to logs/ftrace.txt (fetched
     * over FTP and read with tools/ftrace_report.py). The span buffer is capped to 1M spans (32 MB of
     * the ~265 MB flexible memory). PS3_FTRACE= (empty) in env.txt turns it off.
     * One fixed window caught menus in one game and the opening in another, never the slow world: now
     * a 15 s window every 90 s from 45 s in, 14 of them (to 20 min), each to logs/ftrace.<k>.txt
     * (PS3_FTRACE_EVERY=<period s>:<count>, a toolkit patch). Writing one out stalls the thread that
     * closes the window for a moment. */
    { char ft[200]; snprintf(ft, sizeof ft, "45:15:%s/logs/ftrace", s_root); env_default("PS3_FTRACE", ft); }
    if (!*getenv("PS3_FTRACE")) unsetenv("PS3_FTRACE");
    /* (no PS3_FTRACE_EVERY default: a window every 90 s stalled the game while each was written -- the user's stutter, 2026-11-07) */
    env_default("PS3_FTRACE_CAP", "1000000");
    /* A half-size screenshot every 10 s to logs/shot.NNN.ppm (fetched with the logs, so the console's
     * picture can be checked without the player describing it). PS3RECOMP_VK_DUMP= turns it off. */
    env_default("PS3RECOMP_VK_DUMP", rootp("/logs/shot"));
    if (!*getenv("PS3RECOMP_VK_DUMP")) unsetenv("PS3RECOMP_VK_DUMP");
    env_default("PS3RECOMP_VK_DUMP_EVERY", "10");
    /* Holding SELECT (touchpad click) + R3 for 3/4 s saves full-size screenshots to logs/snap_<n>_<k>.ppm (13 at the
     * swapchain size, 3840x2160 = ~25 MB each, ~324 MB a hold) and a draw-list capture into the log: one now and 12 more
     * over ~1.8 s (cellPad.c "snap combo", rsx_vulkan_backend.c ps3_snap_request). Only with diagnostics = 1 now
     * (PS3_SNAP_DIR set in apply_launcher_settings; 2026-11-11), or PS3_SNAP_DIR=<dir> in env.txt. L3+R3 is the quick
     * menu's (cellPad.c pad_overlay_gate), not this. The frame-rate counter (libs/video/vk_overlay.inc) follows
     * launcher.ini's fps_counter (PS3_FPS_COUNTER 0/1/2, set above). */
    /* A SPIR-V cache miss that took over 50 ms keeps its HLSL in logs/spvmiss/<key>.hlsl ("[spv] miss"
     * lines in the log): a program whose text differs every run never hits the cache, and these show
     * what differs. PS3RECOMP_SPIRV_MISS_DIR= turns it off. */
    mkdir(rootp("/logs/spvmiss"), 0777);
    env_default("PS3RECOMP_SPIRV_MISS_DIR", rootp("/logs/spvmiss"));
    if (!*getenv("PS3RECOMP_SPIRV_MISS_DIR")) unsetenv("PS3RECOMP_SPIRV_MISS_DIR");
    /* Off unless env.txt asks: every lv2 syscall as it is entered (PS3_SCENTER=1) and a guest
     * thread's first steps (PS3_THREAD_TRACE=1). "=0" is the same as leaving them out. */
    if (getenv("PS3_SCENTER") && !strcmp(getenv("PS3_SCENTER"), "0")) unsetenv("PS3_SCENTER");
    if (getenv("PS3_THREAD_TRACE") && !strcmp(getenv("PS3_THREAD_TRACE"), "0")) unsetenv("PS3_THREAD_TRACE");
    /* Frame rate every 10 s ("[rsx fps]" lines); PS3RECOMP_ENG_FPSLOG=0 turns it off. */
    env_default("PS3RECOMP_ENG_FPSLOG", "1");
    if (!strcmp(getenv("PS3RECOMP_ENG_FPSLOG"), "0")) unsetenv("PS3RECOMP_ENG_FPSLOG");
    /* toggle reseed: the runtime knobs (include/ps3emu/ps3_toggles.h) were seeded from the environment by a
     * constructor (libsre_spu_register_ctor -> spu_register_stack_reset_entry) before this function ran, when the
     * console's environment was still empty: every knob read only through its toggle (PS3_GCM_LEGACY_LEAN,
     * PS3_GCM_FAST_WORDS, PS3RECOMP_ENG_MICRO, PS3_BUTTON_ICONS) had its built-in default, not the value set
     * above. Re-read them now that the environment is final (env.txt, launcher.ini and the defaults above);
     * "[toggle] ... (environment, reseed)" lines and a "[toggle] reseed:" summary in the log. Keep it the
     * last environment change in this function. */
    { extern void ps3_toggles_reseed_env(void); ps3_toggles_reseed_env(); }
    /* seed35: game_patches.cpp's constructor if1_unst_audio_init read PS3_IF1_AUDIO_PATCH before this function set it
     * (console: the env was empty, so the RPCS3 "Unstable audio" patch ran ON although G_IF1 sets 0 above). Re-read it
     * now; the lifted code reads g_if1_unst_audio at run time, so this takes effect. Weak: only the if1 build has it. */
    { extern int g_if1_unst_audio __attribute__((weak));
      if (&g_if1_unst_audio) { const char* e = getenv("PS3_IF1_AUDIO_PATCH"); g_if1_unst_audio = !(e && *e == '0');
          fprintf(stderr, "[patch] if1 unstable audio (reseed): %s\n", g_if1_unst_audio ? "on" : "off"); } }

    printf("=== %s: inFAMOUS PS5 port, built %s %s ===\n", game, __DATE__, __TIME__);
    printf("[ps5] anchor: ps5_app_setup at %p (crash offsets are from here)\n", (void*)&ps5_app_setup);
    /* The x86 default floating-point mode (all exceptions masked, round to nearest), as a Linux or
     * Windows process starts with; the runtime never sets one. Threads inherit it through the SDK's
     * pthread_create wrap (ps5link.sh). */
    {
        uint32_t mx = 0, def = 0x1F80;
        __asm__ volatile("stmxcsr %0" : "=m"(mx));
        __asm__ volatile("ldmxcsr %0" : : "m"(def));
        printf("[ps5] MXCSR at start 0x%04x, set to 0x%04x\n", mx, def);
    }
    { extern void ps5_sleep_probe(void); ps5_sleep_probe(); }   /* ps5_shims.c */
    { extern void ps5_clock_probe(void); ps5_clock_probe(); }
    { extern void ps5_libc_probe(void); ps5_libc_probe(); }
    place_threads();
    {   /* ps5 topology: which CPUs share a core (FreeBSD's scheduler topology), for PS5_PIN_* */
        char topo[4096]; size_t tl = sizeof topo - 1;
        if (sysctlbyname("kern.sched.topology_spec", topo, &tl, NULL, 0) == 0) {
            topo[tl] = 0;
            for (char* q = topo; *q; q++) if (*q == '\n') *q = ' ';
            printf("[ps5] topology: %s\n", topo);
        } else printf("[ps5] topology: sysctl failed (errno %d)\n", errno);
    }
    pin_setup(game);   /* ps5 pin (PS5_PIN / PS5_CPUMAP; off by default; host main moves at the end, pin_host_main) */
    /* The RSX FIFO runs on main.cpp's frame_clock thread, which this thread creates after ps5_app_setup: it inherits
     * this thread's mask. This thread itself goes on to be the guest main thread (relabelled "main", PS5_PIN_MAIN). */
    if (!s_pin_on) ps5_pin_self("RSX");
    prof_start();
    /* PS5_SELFTEST=1: the wait and contention self-tests of the ninth console run. */
    if (getenv("PS5_SELFTEST")) {
        cond_selftest();
        contention_selftest();
    }
    pthread_t st;
    if (pthread_create(&st, NULL, status_thread, NULL) == 0) pthread_detach(st);
    s_game_name = game;
    s_t0 = time(NULL);
    { const char* e = getenv("PS5_DEBUG_PORT");
      const int port = e ? atoi(e) : 9990;
      pthread_t dt;
      if (port > 0 && port < 65536 && pthread_create(&dt, NULL, dbg_server, (void*)(intptr_t)port) == 0) pthread_detach(dt);
      else if (port <= 0) printf("[ps5] debug server off (PS5_DEBUG_PORT=0, the default with diagnostics off; =9990 in env.txt turns it on)\n"); }

    static char elf[160];
    snprintf(elf, sizeof elf, "%s/game/PS3_GAME/USRDIR/EBOOT.elf", s_root);
    ps5_put_eboot(elf);
    ps5_dlc_unlocks();
    pin_host_main();   /* ps5 pin: no-op unless PS5_PIN is on */
    static char* args[3] = { "eboot.bin", elf, NULL };
    *argc = 2;
    *argv = args;
}

/* The guest's flat 4 GB (+ guard): one block of CPU direct memory at a 4 GB-aligned address (host
 * pointers are truncated to guest addresses, so vm_base's low 32 bits must be 0). Anonymous mmap
 * would come out of the ~512 MB flexible-memory budget. */
/* A 4 GB-aligned reservation. The console refuses a 4 GB alignment argument (0x80020016, EINVAL,
 * on the first console run); the SDK's probes reserve with the 64 KB direct-memory alignment and an
 * address hint. So: 4 GB-aligned hints, kept only where the kernel put the range on a 4 GB boundary;
 * failing that, reserve 4 GB more than needed, free it, and reserve again (fixed) at the 4 GB
 * boundary inside it. */
static void* reserve_4g_aligned(size_t len)
{
    const uintptr_t G4 = (uintptr_t)1 << 32;
    static const uintptr_t hints[] = { 0x800000000ull, 0x1000000000ull, 0x2000000000ull, 0x4000000000ull,
                                       0x8000000000ull, 0x10000000000ull, 0x40000000000ull };
    for (unsigned i = 0; i < sizeof hints / sizeof hints[0]; i++) {
        void* va = (void*)hints[i];
        int32_t r = sceKernelReserveVirtualRange(&va, len, 0, PS5_KERNEL_DIRECT_ALIGNMENT);
        printf("[ps5] reserve %zu MB, hint %p: 0x%08x at %p\n", len >> 20, (void*)hints[i], (unsigned)r, va);
        if (r == 0 && va && ((uintptr_t)va & (G4 - 1)) == 0) return va;
        if (r == 0 && va) sceKernelMunmap(va, len);
    }
    void* big = NULL;
    int32_t r = sceKernelReserveVirtualRange(&big, len + G4, 0, PS5_KERNEL_DIRECT_ALIGNMENT);
    printf("[ps5] reserve %zu MB anywhere: 0x%08x at %p\n", (len + G4) >> 20, (unsigned)r, big);
    if (r != 0 || !big) return NULL;
    void* va = (void*)(((uintptr_t)big + G4 - 1) & ~(G4 - 1));
    sceKernelMunmap(big, len + G4);
    void* at = va;
    r = sceKernelReserveVirtualRange(&at, len, PS5_KERNEL_MAP_FIXED, PS5_KERNEL_DIRECT_ALIGNMENT);
    printf("[ps5] reserve %zu MB fixed at %p: 0x%08x at %p\n", len >> 20, va, (unsigned)r, at);
    return r == 0 && at == va ? va : NULL;
}

/* Map the allocation at the reserved 4 GB boundary. The second console run had the one fixed map of
 * 4 GB + 64 KB refused (0x80020016) where the SDK's probe maps exactly 4 GB onto a reservation, so
 * each way is tried in turn and logged:
 *   1. one fixed map of the whole length;
 *   2. fixed maps of 1 GB pieces (the 64 KB guard as a piece of its own);
 *   3. the reservation dropped, unfixed maps at 4 GB-aligned hints, kept where they land on one. */
static void* map_guest(void* va, size_t len, int64_t phys)
{
    const int prot = PS5_KERNEL_PROT_CPU_READ | PS5_KERNEL_PROT_CPU_WRITE;
    const uintptr_t G4 = (uintptr_t)1 << 32;
    void* at = va;
    int32_t r = sceKernelMapDirectMemory(&at, len, prot, PS5_KERNEL_MAP_FIXED, phys, PS5_KERNEL_DIRECT_ALIGNMENT);
    printf("[ps5] map 1: whole %zu bytes fixed at %p: 0x%08x at %p\n", len, va, (unsigned)r, at);
    if (r == 0 && at == va) return va;
    if (r == 0) sceKernelMunmap(at, len);

    size_t done = 0;
    r = 0;
    while (done < len && r == 0) {
        const size_t piece = len - done >= ((size_t)1 << 30) ? ((size_t)1 << 30) : len - done;
        void* want = (uint8_t*)va + done;
        at = want;
        r = sceKernelMapDirectMemory(&at, piece, prot, PS5_KERNEL_MAP_FIXED, phys + (int64_t)done,
                                     PS5_KERNEL_DIRECT_ALIGNMENT);
        if (r == 0 && at != want) { sceKernelMunmap(at, piece); r = -1; }
        if (r != 0) printf("[ps5] map 2: piece at %p (%zu bytes): 0x%08x at %p\n", want, piece, (unsigned)r, at);
        else done += piece;
    }
    printf("[ps5] map 2: 1 GB pieces fixed at %p: %zu of %zu bytes mapped\n", va, done, len);
    if (done == len) return va;
    if (done) sceKernelMunmap(va, done);

    sceKernelMunmap(va, len);   /* the reservation */
    static const uintptr_t hints[] = { 0x1000000000ull, 0x2000000000ull, 0x4000000000ull, 0x8000000000ull,
                                       0xc00000000ull, 0x800000000ull };
    for (unsigned i = 0; i < sizeof hints / sizeof hints[0]; i++) {
        at = (void*)hints[i];
        r = sceKernelMapDirectMemory(&at, len, prot, 0, phys, PS5_KERNEL_DIRECT_ALIGNMENT);
        printf("[ps5] map 3: unfixed, hint %p: 0x%08x at %p\n", (void*)hints[i], (unsigned)r, at);
        if (r == 0 && ((uintptr_t)at & (G4 - 1)) == 0) return at;
        if (r == 0) sceKernelMunmap(at, len);
    }
    return NULL;
}

uint8_t* ps5_map_guest_vm(uint64_t size)
{
    const size_t len = (size_t)((size + PS5_KERNEL_DIRECT_ALIGNMENT - 1) & ~(uint64_t)(PS5_KERNEL_DIRECT_ALIGNMENT - 1));
    void* va = reserve_4g_aligned(len);
    int32_t r;
    if (!va) {
        fprintf(stderr, "[ps5] no 4 GB-aligned range of %zu bytes could be reserved\n", len);
        return NULL;
    }
    int64_t phys = 0;
    r = sceKernelAllocateDirectMemory(0, sceKernelGetDirectMemorySize(), len, PS5_KERNEL_DIRECT_ALIGNMENT,
                                      PS5_KERNEL_DIRECT_TYPE_CPU, &phys);
    if (r < 0) {
        size_t avail = 0;
        int64_t at = 0;
        sceKernelAvailableDirectMemorySize(0, sceKernelGetDirectMemorySize(), PS5_KERNEL_DIRECT_ALIGNMENT, &at, &avail);
        fprintf(stderr, "[ps5] AllocateDirectMemory(%zu) failed: 0x%08x (largest free block %zu)\n",
                len, (unsigned)r, avail);
        return NULL;
    }
    void* at = map_guest(va, len, phys);
    if (!at) {
        fprintf(stderr, "[ps5] the guest memory could not be mapped at a 4 GB boundary\n");
        sceKernelReleaseDirectMemory(phys, len);
        return NULL;
    }
    /* Fresh direct memory is not guaranteed zero, and the runtime relies on fresh guest memory
     * reading 0 (sys_memory_allocate, the ELF's bss): clear it all once. */
    memset(at, 0, len);
    s_guest_base = (uint8_t*)at;
    printf("[ps5] guest memory: %zu MB of direct memory at %p\n", len >> 20, at);
    return (uint8_t*)at;
}
