/* LD_PRELOAD counter for pthread objects (the PS5 "ScePthread Internal Memory is running out" hunt):
 * every mutex/cond/rwlock/attr init and destroy, key create and thread create/detach/join, by call
 * site. An object initialized again at the same address without a destroy in between is a leak on
 * the PS5 (libkernel allocates on init, frees on destroy), as is one still live at the report.
 * Every 30 s (and at exit) the sites with leaks or high counts go to $PTL_OUT (default
 * /tmp/pthread_leaks.txt) as "site(binary+offset) kind inits destroys reinit-leaks live".
 *   clang -O2 -shared -fPIC -o pthread_leakcount.so pthread_leakcount.c -ldl -lpthread
 *   LD_PRELOAD=.../pthread_leakcount.so <game>      (symbolize offsets with addr2line -e <game>) */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { K_MUTEX, K_COND, K_RWLOCK, K_MATTR, K_CATTR, K_KEY, K_THREAD, K_DETACH, K_JOIN, NK };
static const char* kname[NK] = { "mutex", "cond", "rwlock", "mutexattr", "condattr", "key", "thread", "detach", "join" };

#define NSITE 4096
typedef struct { uintptr_t pc; int kind; unsigned long init, destroy, reinit; } site_t;
static site_t s_site[NSITE];
#define NOBJ (1 << 20)
typedef struct { uintptr_t addr; int site; } obj_t;     /* live objects: open addressing */
static obj_t s_obj[NOBJ];
static pthread_spinlock_t s_lk;
static int s_init;
static time_t s_last;

static int (*r_mutex_init)(pthread_mutex_t*, const pthread_mutexattr_t*);
static int (*r_mutex_destroy)(pthread_mutex_t*);
static int (*r_cond_init)(pthread_cond_t*, const pthread_condattr_t*);
static int (*r_cond_destroy)(pthread_cond_t*);
static int (*r_rw_init)(pthread_rwlock_t*, const pthread_rwlockattr_t*);
static int (*r_rw_destroy)(pthread_rwlock_t*);
static int (*r_mattr_init)(pthread_mutexattr_t*);
static int (*r_mattr_destroy)(pthread_mutexattr_t*);
static int (*r_cattr_init)(pthread_condattr_t*);
static int (*r_cattr_destroy)(pthread_condattr_t*);
static int (*r_key_create)(pthread_key_t*, void (*)(void*));
static int (*r_create)(pthread_t*, const pthread_attr_t*, void* (*)(void*), void*);
static int (*r_detach)(pthread_t);
static int (*r_join)(pthread_t, void**);

static void report(void);
static void setup(void)
{
    if (s_init) return;
    pthread_spin_init(&s_lk, 0);
#define R(v, n) v = dlsym(RTLD_NEXT, n)
    R(r_mutex_init, "pthread_mutex_init"); R(r_mutex_destroy, "pthread_mutex_destroy");
    R(r_cond_init, "pthread_cond_init"); R(r_cond_destroy, "pthread_cond_destroy");
    R(r_rw_init, "pthread_rwlock_init"); R(r_rw_destroy, "pthread_rwlock_destroy");
    R(r_mattr_init, "pthread_mutexattr_init"); R(r_mattr_destroy, "pthread_mutexattr_destroy");
    R(r_cattr_init, "pthread_condattr_init"); R(r_cattr_destroy, "pthread_condattr_destroy");
    R(r_key_create, "pthread_key_create"); R(r_create, "pthread_create");
    R(r_detach, "pthread_detach"); R(r_join, "pthread_join");
    s_init = 1;
    atexit(report);
}
static int site_of(uintptr_t pc, int kind)
{
    unsigned h = (unsigned)((pc * 0x9E3779B97F4A7C15ull) >> 52) % NSITE;
    for (unsigned i = 0; i < NSITE; i++) {
        site_t* s = &s_site[(h + i) % NSITE];
        if (s->pc == pc && s->kind == kind) return (int)((h + i) % NSITE);
        if (!s->pc) { s->pc = pc; s->kind = kind; return (int)((h + i) % NSITE); }
    }
    return 0;
}
static obj_t* obj_slot(uintptr_t a, int add)
{
    unsigned h = (unsigned)((a * 0x9E3779B97F4A7C15ull) >> 44) & (NOBJ - 1);
    for (unsigned i = 0; i < 64; i++) {
        obj_t* o = &s_obj[(h + i) & (NOBJ - 1)];
        if (o->addr == a) return o;
        if (!o->addr && add) return o;
    }
    return NULL;
}
static void note(int kind, void* obj, uintptr_t pc, int is_init)
{
    if (!s_init) setup();
    pthread_spin_lock(&s_lk);
    int si = site_of(pc, kind);
    if (is_init) {
        s_site[si].init++;
        if (obj) {
            obj_t* o = obj_slot((uintptr_t)obj, 1);
            if (o && o->addr) s_site[o->site].reinit++;      /* init over a live object: leaked */
            if (o) { o->addr = (uintptr_t)obj; o->site = si; }
        }
    } else {
        s_site[si].destroy++;
        obj_t* o = obj ? obj_slot((uintptr_t)obj, 0) : NULL;
        if (o) o->addr = 0;       /* (tombstone-free: rare probe-chain breaks only miscount) */
    }
    pthread_spin_unlock(&s_lk);
    time_t t = time(NULL);
    if (t - s_last >= 30) { s_last = t; report(); }
}
static void report(void)
{
    static unsigned long live[NSITE];
    memset(live, 0, sizeof live);
    for (unsigned i = 0; i < NOBJ; i++) if (s_obj[i].addr) live[s_obj[i].site]++;
    const char* p = getenv("PTL_OUT");
    FILE* f = fopen(p ? p : "/tmp/pthread_leaks.txt", "w");
    if (!f) return;
    fprintf(f, "# t=%ld  site kind inits destroys reinit-leaks live\n", (long)time(NULL));
    for (int i = 0; i < NSITE; i++) {
        const site_t* s = &s_site[i];
        if (!s->pc) continue;
        Dl_info di; const char* mod = "?"; uintptr_t off = s->pc;
        if (dladdr((void*)s->pc, &di) && di.dli_fname) { mod = strrchr(di.dli_fname, '/') ? strrchr(di.dli_fname, '/') + 1 : di.dli_fname; off = s->pc - (uintptr_t)di.dli_fbase; }
        fprintf(f, "%s+0x%lx %s %lu %lu %lu %lu\n", mod, (unsigned long)off, kname[s->kind], s->init, s->destroy, s->reinit, live[i]);
    }
    fclose(f);
}
#define PC ((uintptr_t)__builtin_return_address(0))
int pthread_mutex_init(pthread_mutex_t* m, const pthread_mutexattr_t* a) { if (!s_init) setup(); note(K_MUTEX, m, PC, 1); return r_mutex_init(m, a); }
int pthread_mutex_destroy(pthread_mutex_t* m) { if (!s_init) setup(); note(K_MUTEX, m, PC, 0); return r_mutex_destroy(m); }
int pthread_cond_init(pthread_cond_t* c, const pthread_condattr_t* a) { if (!s_init) setup(); note(K_COND, c, PC, 1); return r_cond_init(c, a); }
int pthread_cond_destroy(pthread_cond_t* c) { if (!s_init) setup(); note(K_COND, c, PC, 0); return r_cond_destroy(c); }
int pthread_rwlock_init(pthread_rwlock_t* r, const pthread_rwlockattr_t* a) { if (!s_init) setup(); note(K_RWLOCK, r, PC, 1); return r_rw_init(r, a); }
int pthread_rwlock_destroy(pthread_rwlock_t* r) { if (!s_init) setup(); note(K_RWLOCK, r, PC, 0); return r_rw_destroy(r); }
int pthread_mutexattr_init(pthread_mutexattr_t* a) { if (!s_init) setup(); note(K_MATTR, a, PC, 1); return r_mattr_init(a); }
int pthread_mutexattr_destroy(pthread_mutexattr_t* a) { if (!s_init) setup(); note(K_MATTR, a, PC, 0); return r_mattr_destroy(a); }
int pthread_condattr_init(pthread_condattr_t* a) { if (!s_init) setup(); note(K_CATTR, a, PC, 1); return r_cattr_init(a); }
int pthread_condattr_destroy(pthread_condattr_t* a) { if (!s_init) setup(); note(K_CATTR, a, PC, 0); return r_cattr_destroy(a); }
int pthread_key_create(pthread_key_t* k, void (*d)(void*)) { if (!s_init) setup(); note(K_KEY, NULL, PC, 1); return r_key_create(k, d); }
int pthread_create(pthread_t* t, const pthread_attr_t* a, void* (*fn)(void*), void* arg) { if (!s_init) setup(); note(K_THREAD, NULL, PC, 1); return r_create(t, a, fn, arg); }
int pthread_detach(pthread_t t) { if (!s_init) setup(); note(K_DETACH, NULL, PC, 1); return r_detach(t); }
int pthread_join(pthread_t t, void** rv) { if (!s_init) setup(); note(K_JOIN, NULL, PC, 1); return r_join(t, rv); }
