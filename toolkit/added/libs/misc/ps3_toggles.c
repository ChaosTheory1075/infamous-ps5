#include <unistd.h>
/*
 * ps3recomp - PS3_TOGGLE_FILE: knobs switched while the game runs.
 *
 * The poll half of include/ps3emu/ps3_toggles.h (the format and the list of
 * live knobs are there). One thread calls ps3_toggles_poll() every frame; at
 * most every 250 ms it stat()s the file, and only when its modification time,
 * size or inode moved does it read and parse it. Each knob whose value then
 * differs from before is stored, logged ("[toggle] NAME old -> new"), marked
 * in the PS3_FTRACE timeline and handed to its watchers, which update the
 * module-local ints the hot paths read.
 */
#include "ps3emu/ps3_toggles.h"
#include "ps3emu/ps3_ftrace.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

#define TOGGLE_POLL_NS  (250ull * 1000000ull)
#define TOGGLE_FILE_MAX (16u * 1024u)

static uint32_t toggle_hash(const char* s)
{
    uint32_t h = 2166136261u;
    for (; *s; s++) { h ^= (uint8_t)*s; h *= 16777619u; }
    return h;
}

static char* trim(char* s)
{
    while (*s == ' ' || *s == '\t' || *s == '\r') s++;
    char* e = s + strlen(s);
    while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r')) *--e = 0;
    return s;
}

static void toggle_mark(uint32_t who, uint32_t a, uint32_t b)
{
    if (!PS3_FT_ON()) return;
    const uint64_t now = ps3_ft_now();
    ps3_ft_span(PS3_FT_TOGGLE, who, a, b, now, now);
}

/* toggle reseed: the knobs the toggle file named at its last read (they keep the file's value) */
static int s_file_set[PS3T_COUNT];

void ps3_toggles_reseed_env(void)
{
    ps3_toggles_seed();
    ps3_toggle_state* s = &g_ps3_toggles;
    int changed = 0, nondef = 0;
    for (int id = 0; id < PS3T_COUNT; id++) {
        const ps3_toggle_def* d = ps3_toggle_def_of(id);
        const char* e = getenv(d->name);
        const int v = ps3_toggle_env_parse(id, e);
        char text[PS3_TOGGLE_STR];
        snprintf(text, sizeof text, "%s", e ? e : "");
        nondef += d->kind == PS3_TK_STR ? (e && *e) : v != ps3_toggle_env_parse(id, NULL);
        ps3_toggle_lock();
        if (s->env_value[id] == v && !strcmp(s->env_str[id], text)) { ps3_toggle_unlock(); continue; }
        const int old_env = s->env_value[id];
        char old_env_str[PS3_TOGGLE_STR];
        memcpy(old_env_str, s->env_str[id], sizeof old_env_str);
        s->env_value[id] = v;
        memcpy(s->env_str[id], text, PS3_TOGGLE_STR);
        const int by_file = __atomic_load_n(&s_file_set[id], __ATOMIC_RELAXED);
        const int old = s->value[id];
        const int moved = !by_file && (d->kind == PS3_TK_STR ? strcmp(s->str[id], text) != 0 : old != v);
        if (moved) {
            __atomic_store_n(&s->value[id], v, __ATOMIC_RELAXED);
            memcpy(s->str[id], text, PS3_TOGGLE_STR);
            for (int i = 0; i < PS3_TOGGLE_WATCHERS && s->watch[id][i]; i++)
                s->watch[id][i](id, v);
        }
        ps3_toggle_unlock();
        changed++;
        if (d->kind == PS3_TK_STR)
            fprintf(stderr, "[toggle] %s %s -> %s (environment, reseed%s)\n", d->name, *old_env_str ? old_env_str : "(unset)",
                    *text ? text : "(unset)", by_file ? "; the toggle file's value stays" : "");
        else
            fprintf(stderr, "[toggle] %s %d -> %d (environment, reseed%s)\n", d->name, old_env, v,
                    by_file ? "; the toggle file's value stays" : "");
        if (moved) toggle_mark((uint32_t)id, d->kind == PS3_TK_STR ? toggle_hash(old_env_str) : (uint32_t)old,
                               d->kind == PS3_TK_STR ? toggle_hash(text) : (uint32_t)v);
    }
    fprintf(stderr, "[toggle] reseed: %d of %d knobs changed by the environment set after the first seed "
            "(%d non-default now)\n", changed, (int)PS3T_COUNT, nondef);
}

/* One built-in knob to its new text (the file's, or the environment's when the
 * file does not name it). Takes the lock; calls the watchers under it. */
static void toggle_apply(int id, const char* text, int from_file)
{
    ps3_toggle_state* s = &g_ps3_toggles;
    const ps3_toggle_def* d = ps3_toggle_def_of(id);
    int v;
    if (!from_file) v = s->env_value[id];
    else if (d->kind == PS3_TK_STR) v = atoi(text);
    else {
        char* end = NULL;
        const long l = strtol(text, &end, 0);
        if (!*text || (end && *end)) {
            fprintf(stderr, "[toggle] %s=%s: not a number, ignored\n", d->name, text);
            return;
        }
        v = (int)l;
    }
    ps3_toggle_lock();
    const int old = s->value[id];
    char old_str[PS3_TOGGLE_STR];
    memcpy(old_str, s->str[id], sizeof old_str);
    const int changed = d->kind == PS3_TK_STR ? strcmp(old_str, text) != 0 : old != v;
    if (changed) {
        __atomic_store_n(&s->value[id], v, __ATOMIC_RELAXED);
        snprintf(s->str[id], PS3_TOGGLE_STR, "%s", text);
        for (int i = 0; i < PS3_TOGGLE_WATCHERS && s->watch[id][i]; i++)
            s->watch[id][i](id, v);
    }
    ps3_toggle_unlock();
    if (!changed) return;
    if (d->kind == PS3_TK_STR) {
        fprintf(stderr, "[toggle] %s %s -> %s%s\n", d->name, *old_str ? old_str : "(unset)",
                *text ? text : "(unset)", from_file ? "" : " (environment)");
        toggle_mark((uint32_t)id, toggle_hash(old_str), toggle_hash(text));
    } else {
        fprintf(stderr, "[toggle] %s %d -> %d%s\n", d->name, old, v, from_file ? "" : " (environment)");
        toggle_mark((uint32_t)id, (uint32_t)old, (uint32_t)v);
    }
}

/* A name that is not a built-in knob: kept for ps3_toggle_get(). */
static void toggle_apply_extra(const char* name, const char* text, int set)
{
    ps3_toggle_state* s = &g_ps3_toggles;
    const int v = set ? (int)strtol(text, NULL, 0) : 0;
    ps3_toggle_lock();
    int i = 0;
    while (i < s->n_extra && strcmp(s->extra[i].name, name)) i++;
    if (i == s->n_extra) {
        if (!set || i >= PS3_TOGGLE_EXTRA) { ps3_toggle_unlock(); return; }
        snprintf(s->extra[i].name, sizeof s->extra[i].name, "%s", name);
        s->n_extra++;
        fprintf(stderr, "[toggle] %s is not a built-in knob: only ps3_toggle_get() sees it\n", name);
    }
    const int was_set = s->extra[i].set, old = s->extra[i].value;
    s->extra[i].set = set;
    s->extra[i].value = v;
    ps3_toggle_unlock();
    if (was_set == set && (!set || old == v)) return;
    char was[16];
    snprintf(was, sizeof was, "%d", old);
    fprintf(stderr, "[toggle] %s %s -> %s\n", name, was_set ? was : "(unset)", set ? text : "(unset)");
    toggle_mark(64u + (uint32_t)i, (uint32_t)old, (uint32_t)v);
}

static void toggles_apply_text(char* buf)
{
    int seen[PS3T_COUNT] = { 0 };
    char seen_extra[PS3_TOGGLE_EXTRA][48];
    int n_seen_extra = 0;
    int line_no = 0;
    for (char* line = buf; line && *line;) {
        char* next = strchr(line, '\n');
        if (next) *next++ = 0;
        line_no++;
        char* hash = strchr(line, '#');
        if (hash) *hash = 0;
        char* l = trim(line);
        line = next;
        if (!*l) continue;
        char* eq = strchr(l, '=');
        if (!eq) {
            fprintf(stderr, "[toggle] line %d: '%s' has no '=', ignored\n", line_no, l);
            continue;
        }
        *eq = 0;
        char* name = trim(l);
        char* val = trim(eq + 1);
        int id = 0;
        while (id < PS3T_COUNT && strcmp(ps3_toggle_def_of(id)->name, name)) id++;
        if (id < PS3T_COUNT) {
            seen[id] = 1;
            toggle_apply(id, val, 1);
        } else if (*name) {
            if (n_seen_extra < PS3_TOGGLE_EXTRA)
                snprintf(seen_extra[n_seen_extra++], 48, "%s", name);
            toggle_apply_extra(name, val, 1);
        }
    }
    /* What the file no longer names goes back to the environment. */
    for (int id = 0; id < PS3T_COUNT; id++) {
        __atomic_store_n(&s_file_set[id], seen[id], __ATOMIC_RELAXED);   /* toggle reseed */
        if (!seen[id]) toggle_apply(id, g_ps3_toggles.env_str[id], 0);
    }
    for (int i = 0; i < g_ps3_toggles.n_extra; i++) {
        int named = 0;
        for (int k = 0; k < n_seen_extra && !named; k++)
            named = !strcmp(seen_extra[k], g_ps3_toggles.extra[i].name);
        if (!named) toggle_apply_extra(g_ps3_toggles.extra[i].name, "", 0);
    }
}

static uint64_t toggles_now_ns(void)
{
    return ps3_ft_now();   /* monotonic, the timeline's own clock */
}

#if defined(__linux__) || defined(__FreeBSD__) || defined(__PROSPERO__)
#include <sys/uio.h>
#endif
extern uint8_t* vm_base;
static void ps3_gmem_dump(int n)
{
    if (!vm_base) return;
    char dir[600]; const char* d = getenv("PS3_GMEM_DIR");
    if (d && *d) snprintf(dir, sizeof dir, "%s", d);
    else { const char* t = getenv("PS3_TOGGLE_FILE"); snprintf(dir, sizeof dir, "%s", t ? t : "."); char* sl = strrchr(dir, '/'); if (sl) *sl = 0; else snprintf(dir, sizeof dir, "."); }
    char path[700]; snprintf(path, sizeof path, "%s/gmem_%d.bin", dir, n);
    FILE* f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "[gmem] cannot write %s\n", path); return; }
    static const uint32_t rg[][2] = { { 0x00010000u, 0x10000000u }, { 0x20000000u, 0x40000000u }, { 0xD0000000u, 0xD1000000u } };
    enum { CH = 1u << 20 };
    static uint8_t* buf; if (!buf) buf = (uint8_t*)malloc(CH);
    uint64_t total = 0;
    for (unsigned r = 0; r < sizeof rg / sizeof rg[0]; r++)
        for (uint64_t a = rg[r][0]; a < rg[r][1]; a += CH) {
            ssize_t got = -1;
#if defined(__linux__)
            struct iovec lo = { buf, CH }, re = { vm_base + a, CH };
            got = process_vm_readv(getpid(), &lo, 1, &re, 1, 0);
#else
            if (r == 0) { memcpy(buf, vm_base + a, CH); got = CH; }   /* main memory: always mapped */
#endif
            if (got != (ssize_t)CH) continue;
            const uint32_t hdr[2] = { (uint32_t)a, CH };
            fwrite(hdr, 4, 2, f); fwrite(buf, 1, CH, f); total += CH;
        }
    fclose(f);
    fprintf(stderr, "[gmem] dump %d: %llu MB -> %s\n", n, (unsigned long long)(total >> 20), path);
}

void ps3_toggles_poll(void)
{
    static int s_on = -1;              /* -1 not read yet, 0 no file, 1 polling */
    static char s_path[1024];
    static uint64_t s_next;
    static int s_had;                  /* the last stat found the file */
    static long long s_mt_s, s_mt_ns, s_size, s_ino;
    if (__builtin_expect(s_on == 0, 1)) return;
    if (s_on < 0) {
        const char* e = getenv("PS3_TOGGLE_FILE");
        if (!e || !*e) { s_on = 0; return; }
        snprintf(s_path, sizeof s_path, "%s", e);
        ps3_toggles_seed();
        s_on = 1;
        fprintf(stderr, "[toggle] watching %s (every 250 ms)\n", s_path);
    }
    const uint64_t now = toggles_now_ns();
    if (now < s_next) return;
    s_next = now + TOGGLE_POLL_NS;

    struct stat st;
    const int have = stat(s_path, &st) == 0;
    long long mt_s = 0, mt_ns = 0;
    if (have) {
        mt_s = (long long)st.st_mtime;
#if defined(__APPLE__)
        mt_ns = (long long)st.st_mtimespec.tv_nsec;
#elif defined(__linux__)
        mt_ns = (long long)st.st_mtim.tv_nsec;
#endif
    }
    if (have == s_had && (!have || (mt_s == s_mt_s && mt_ns == s_mt_ns &&
                                    (long long)st.st_size == s_size &&
                                    (long long)st.st_ino == s_ino)))
        return;
    s_had = have;
    if (have) { s_mt_s = mt_s; s_mt_ns = mt_ns; s_size = (long long)st.st_size; s_ino = (long long)st.st_ino; }

    static char buf[TOGGLE_FILE_MAX + 1];
    size_t n = 0;
    if (have) {
        FILE* f = fopen(s_path, "rb");
        if (f) { n = fread(buf, 1, TOGGLE_FILE_MAX, f); fclose(f); }
    }
    buf[n] = 0;
    toggles_apply_text(buf);
    {   /* gmem dump: PS3_GMEM_DUMP=<n> in the toggle file writes guest memory to <PS3_GMEM_DIR or the toggle file's
         * folder>/gmem_<n>.bin when n changes (cheat hunting: diff two moments). Pages the guest has not mapped are
         * skipped (process_vm_readv on ourselves), so it cannot fault. Format: repeated {u32 addr, u32 len, data}. */
        static int last = 0;
        const int n = ps3_toggle_get("PS3_GMEM_DUMP", 0);
        if (n && n != last) { last = n; ps3_gmem_dump(n); }
    }
}
