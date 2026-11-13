import sys
p = sys.argv[1]
s = open(p).read()
old = "    def check(self, level, name, msg):\n        self.checks.append((level, name, msg))\n"
new = ("    def check(self, level, name, msg):\n"
       "        # INFAMOUS2_PREPARED=1: the game folder, EBOOT and firmware were laid out and decrypted\n"
       "        # beforehand (disc + update copy, decrypted by RPCS3 on another OS); run from the 'port' step.\n"
       "        if level == 'fail' and name in ('game', 'rap', 'rpcs3', 'firmware') and os.environ.get('INFAMOUS2_PREPARED'):\n"
       "            level = 'warn'\n"
       "        self.checks.append((level, name, msg))\n")
if new not in s:
    assert old in s
    s = s.replace(old, new)
    open(p, 'w').write(s)
print('patched')

# INFAMOUS2_CMAKE_ARGS: extra CMake options for the compile step (e.g. -DPS3RECOMP_RSX_VULKAN=ON).
s = open(p).read()
old = "'-DPython3_EXECUTABLE=' + self.py])"
new = "'-DPython3_EXECUTABLE=' + self.py] + os.environ.get('INFAMOUS2_CMAKE_ARGS', '').split())"
if new not in s:
    assert old in s
    open(p, 'w').write(s.replace(old, new))
print('patched cmake args')

# main.cpp: present through the Vulkan backend when the toolkit is built with it.
m = sys.argv[2] if len(sys.argv) > 2 else None
if m:
    s = open(m).read()
    old = "#else\nextern \"C\" int  rsx_null_backend_init"
    new = ("#elif defined(PS3RECOMP_RSX_VULKAN)\n"
           "extern \"C\" int  rsx_vulkan_backend_init(uint32_t w, uint32_t h, const char* title);\n"
           "extern \"C\" void rsx_vulkan_backend_present(void);\n"
           "extern \"C\" int  rsx_vulkan_backend_pump_messages(void);\n"
           "#  define rsx_backend_init    rsx_vulkan_backend_init\n"
           "#  define rsx_backend_present rsx_vulkan_backend_present\n"
           "#  define rsx_backend_pump    rsx_vulkan_backend_pump_messages\n"
           "#  define RSX_BACKEND_NAME    \"Vulkan\"\n" + old)
    if "rsx_vulkan_backend_init(uint32_t" not in s:
        assert old in s
        open(m, 'w').write(s.replace(old, new))
    print('patched main.cpp')

# main.cpp: Linux guest VM. glibc's calloc of a huge block returns mmap+16, so vm_base is not page
# aligned and every vm_commit (mprotect) fails with EINVAL: the very first sys_memory_allocate (the
# TLS block) returns ENOMEM. Map the whole 4 GB + guard instead, page aligned and lazily backed,
# which also covers the raw-SPU window at 0xE0000000 the way the Windows reservation does.
if m:
    s = open(m).read()
    old = ("    vm_base = (uint8_t*)calloc(1, 0xE0000000u);\n"
           "    ppu_vm_size = 0xE0000000u;\n"
           "#endif\n")
    new = ("#  if defined(__APPLE__)\n"
           "    vm_base = (uint8_t*)calloc(1, 0xE0000000u);\n"
           "    ppu_vm_size = 0xE0000000u;\n"
           "#  else\n"
           "    void* m = mmap(NULL, VM_SIZE, PROT_READ | PROT_WRITE,\n"
           "                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);\n"
           "    vm_base = m == MAP_FAILED ? nullptr : (uint8_t*)m;\n"
           "    ppu_vm_size = 0;              /* the whole space is mapped, as on Windows */\n"
           "#  endif\n"
           "#endif\n")
    if "MAP_NORESERVE, -1, 0);\n    vm_base = m == MAP_FAILED" not in s:
        assert old in s
        s = s.replace(old, new)
        s = s.replace("#include <stdint.h>\n", "#include <stdint.h>\n#if !defined(_WIN32)\n#include <sys/mman.h>\n#endif\n", 1)
        open(m, 'w').write(s)
    print('patched main.cpp vm')

# main.cpp on the PS5: ps5_app_setup (tools/ps5/ps5_app.c) stands in for run.sh, and the guest VM is
# direct memory (ps5_map_guest_vm) instead of an anonymous mmap.
if m:
    s = open(m).read()
    old = "#  if defined(__APPLE__)\n    vm_base = (uint8_t*)calloc(1, 0xE0000000u);\n"
    new = ("#  if defined(__PROSPERO__)\n"
           "    vm_base = ps5_map_guest_vm(VM_SIZE);\n"
           "    ppu_vm_size = 0;\n"
           "#  elif defined(__APPLE__)\n    vm_base = (uint8_t*)calloc(1, 0xE0000000u);\n")
    if "ps5_map_guest_vm(VM_SIZE)" not in s:
        assert old in s
        s = s.replace(old, new)
    old = "int main(int argc, char** argv)\n{\n"
    new = ("#if defined(__PROSPERO__)\n"
           "extern \"C\" void ps5_app_setup(int* argc, char*** argv);\n"
           "#endif\n"
           "int main(int argc, char** argv)\n{\n"
           "#if defined(__PROSPERO__)\n"
           "    ps5_app_setup(&argc, &argv);   /* paths, environment, log: run.sh's job elsewhere */\n"
           "#endif\n")
    if "ps5_app_setup(&argc, &argv);" not in s:
        assert old in s
        s = s.replace(old, new)
    open(m, 'w').write(s)
    print('patched main.cpp ps5')

# (file-scope declaration: extern "C" is ill-formed at block scope)
if m:
    s = open(m).read()
    s = s.replace("#  if defined(__PROSPERO__)\n    extern \"C\" uint8_t* ps5_map_guest_vm(uint64_t size);\n",
                  "#  if defined(__PROSPERO__)\n")
    decl = ("#if defined(__PROSPERO__)\nextern \"C\" uint8_t* ps5_map_guest_vm(uint64_t size);\n#endif\n"
            "static bool alloc_guest_vm(void)\n")
    if decl not in s:
        s = s.replace("static bool alloc_guest_vm(void)\n", decl, 1)
    open(m, 'w').write(s)
    print('patched main.cpp ps5 decl')

# vblank 59.94: the frame clock ticked the guest vblank/flip every 16 ms (62.5 Hz) by GetTickCount64;
# the PS3's is 1001/60000 s (59.94 Hz), so vblank- or flip-paced guest timing ran 4.3% fast (the user:
# "the game is running faster than it should", console 2026-11-02). Now a nanosecond deadline that
# advances by 16683333 ns; PS3_VBLANK_NS=<ns> overrides it (16000000 = the old 62.5 Hz).
if m:
    s = open(m).read()
    if "vblank 59.94" not in s:
        reps = [
            ("static DWORD WINAPI frame_clock(LPVOID)\n{",
             "/* vblank 59.94 (if2_patch_rebuild.py): the frame clock's own nanosecond time. */\n"
             "static uint64_t fc_now_ns(void)\n{\n"
             "#ifdef _WIN32\n"
             "    LARGE_INTEGER f, c; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&c);\n"
             "    return (uint64_t)((unsigned __int128)c.QuadPart * 1000000000u / (uint64_t)f.QuadPart);\n"
             "#else\n"
             "    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);\n"
             "    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;\n"
             "#endif\n}\n\n"
             "static DWORD WINAPI frame_clock(LPVOID)\n{"),
            ("    ULONGLONG next_tick = GetTickCount64();\n",
             "    /* vblank 59.94: one tick per 1001/60000 s, on a nanosecond deadline. */\n"
             "    uint64_t vbl_ns = 16683333;\n"
             "    { const char* e = getenv(\"PS3_VBLANK_NS\"); if (e && atoll(e) > 0) vbl_ns = (uint64_t)atoll(e); }\n"
             "    fprintf(stderr, \"[rsx] vblank period %llu ns (%.3f Hz)\\n\", (unsigned long long)vbl_ns, 1e9 / (double)vbl_ns);\n"
             "    uint64_t vbl_next = fc_now_ns();\n"),
            ("        while ((long long)(now - next_tick) >= 0 && fired < 240) {\n",
             "        const uint64_t now_ns = fc_now_ns();\n"
             "        while ((int64_t)(now_ns - vbl_next) >= 0 && fired < 240) {\n"),
            ("            next_tick += 16;             /* ~60 Hz */\n",
             "            vbl_next += vbl_ns;          /* vblank 59.94 */\n"),
            ("        if (fired >= 240) next_tick = now;   /* fell too far behind -- resync */\n",
             "        if (fired >= 240) vbl_next = now_ns;   /* fell too far behind -- resync */\n"),
        ]
        for o, n in reps:
            assert o in s, o
            s = s.replace(o, n, 1)
        open(m, 'w').write(s)
    print('patched main.cpp vblank 59.94')

# flip cap: GCM_FLIP_IMMEDIATE=2 (the shipped default, tools/ps5/ps5_app.c) completes the flip at present
# like =1, but not sooner than 33.3 ms after the last immediate one, so a 34 ms frame costs 34 ms instead
# of the 3-vblank 50 ms and fast scenes still pace at 30. Without this block =2 behaves like =1 (uncapped).
if m:
    s = open(m).read()
    if "flip cap" not in s:
        old = "    if (g_flip_immediate) cellGcmTickFlip();\n"
        new = ("    /* flip cap: GCM_FLIP_IMMEDIATE=2 completes the flip at present like =1, but not sooner than 33.3 ms after the\n"
               "     * last immediate one (the vblank tick completes it otherwise), so a 34 ms frame costs 34 ms instead of the\n"
               "     * 3-vblank 50 ms and fast scenes still pace at 30. PS5 logs 2026-11-10: if1 plateaus at 21.8/25.0 fps. */\n"
               "    if (g_flip_immediate == 2) {\n"
               "        static std::chrono::steady_clock::time_point s_last;\n"
               "        const auto now = std::chrono::steady_clock::now();\n"
               "        if (now - s_last >= std::chrono::microseconds(33300)) { s_last = now; cellGcmTickFlip(); }\n"
               "    } else if (g_flip_immediate) cellGcmTickFlip();\n")
        assert s.count(old) == 1, "flip cap: anchor"
        s = "#include <chrono>\n" + s.replace(old, new, 1)
        open(m, 'w').write(s)
    print('patched main.cpp flip cap')

# rsx doorbell (2026-11-11, OFF by default): the frame clock's wait between two FIFO passes can poll for the guest's
# answer (PS3_RSX_SPIN_US=<us>) or sleep until a thread rings (PS3_RSX_DOORBELL=1) instead of the bare usleep.
# Needs the toolkit's cellGcmSys.c "rsx doorbell" (cellGcm_rsx_idle_state / _doorbell_wait / _progress /
# _doorbell_counts, toolkit/ps3recomp-fork.patch). After vblank 59.94 (it anchors on vbl_next). Every anchor must
# be there exactly once; a missing one stops the script (the edit is never skipped).
DB_HELPERS = r'''#if !defined(_WIN32)
/* rsx doorbell: the wait between two passes of the frame clock, when PS3_RSX_SPIN_US / PS3_RSX_DOORBELL ask for
 * more than the bare sleep (cellGcmSys.c "rsx doorbell" has the mechanism and the no-lost-wake-up argument).
 *
 *   1. Work already there (the last pass stopped at a flip with commands behind it, the guest was quick): no wait.
 *   2. PS3_RSX_SPIN_US, only after a pass that found work: poll for the guest's answer -- the next put, the label
 *      an acquire is parked on -- instead of sleeping through it. The guest that just got its label / ref / flip
 *      usually answers within microseconds, and usleep cannot return in under ~100 us on the PS5. The spin ends
 *      on this thread's own clock (every PS5 thread is FIFO: a spinner has to stop itself), at the next vblank
 *      deadline, and on a stalled walker; an idle RSX thread never spins.
 *   3. PS3_RSX_DOORBELL: the timed sleep, woken by the threads that can tell there is work. Else the bare sleep.
 *
 * Returns 1 when it came back early for work. The caller holds it to that: an early pass that finds none is
 * followed by one bare sleep, so nothing here can turn the loop into a busy one. */
static struct { unsigned at_once, spins, spin_hits, bells, bell_early, wasted; } g_fc_db;

static inline void fc_relax(void)
{
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    __asm__ __volatile__("yield");
#endif
}

static int fc_idle_wait(int us, int spin_us, int bell, int productive, uint64_t vbl_next)
{
    int st = cellGcm_rsx_idle_state();
    if (st > 0) { g_fc_db.at_once++; return 1; }
    if (st == 0 && spin_us > 0 && productive) {
        if (spin_us > 2000) spin_us = 2000;
        g_fc_db.spins++;
        const uint64_t t0 = fc_now_ns(), lim = (uint64_t)spin_us * 1000ull;
        for (unsigned k = 1;; k++) {
            for (int i = 0; i < 8; i++) fc_relax();
            st = cellGcm_rsx_idle_state();
            if (st > 0) { g_fc_db.spin_hits++; return 1; }
            if (st < 0) break;
            if (!(k & 7u)) {
                const uint64_t t = fc_now_ns();
                if ((int64_t)(t - vbl_next) >= 0) return 0;   /* a vblank tick is due: no sleep on top of it */
                if (t - t0 >= lim) break;
            }
        }
    }
    /* A stalled walker (st < 0) gets the bare sleep: its watchdogs count passes, a full sleep apart. */
    if (bell && st == 0) {
        g_fc_db.bells++;
        const int early = cellGcm_rsx_doorbell_wait((unsigned)us);
        g_fc_db.bell_early += (unsigned)early;
        return early;
    }
    usleep((useconds_t)us);
    return 0;
}
#endif

'''
DB_ENV = r'''    /* rsx doorbell: PS3_RSX_SPIN_US=<us> (default 0 = off, capped at 2000) -- after a pass that found work, poll
     * that long for the guest's next put / label before sleeping. PS3_RSX_DOORBELL=1 (default 0) -- the sleep is
     * woken by an HLE flip or put, an SPU write of the label an acquire is parked on, a guest reading the ref
     * register. With both 0 the wait below is the usleep it always was. Read live (PS3_TOGGLE_FILE). Off until
     * the title's first flip: before it every pass presents, and boot should not change. */
    int spin_us_env = 0, bell_env = 0;
    { const char* e = getenv("PS3_RSX_SPIN_US");  if (e && atoi(e) > 0) spin_us_env = atoi(e); }
    { const char* e = getenv("PS3_RSX_DOORBELL"); if (e && atoi(e) > 0) bell_env = 1; }
    if (spin_us_env || bell_env)
        fprintf(stderr, "[rsx] doorbell: spin %d us, doorbell %d\n", spin_us_env, bell_env);
'''
DB_VARS = r'''#if !defined(_WIN32)
    /* rsx doorbell: what the pass before this wait did, and whether that wait came back early */
    int db_early = 0, db_live = 0;
    unsigned db_prog = 0;
    LONG db_pres = 0;
    ULONGLONG db_log = 0;
#endif
'''
DB_WAIT = r'''            /* rsx doorbell */
            const int spin_us = ps3_toggle_get("PS3_RSX_SPIN_US", spin_us_env);
            const int bell    = ps3_toggle_get("PS3_RSX_DOORBELL", bell_env) > 0;
            db_live = (spin_us > 0 || bell) && rsx_ok && cellGcm_flip_request_count() != 0;
            if (db_live) {
                const int productive = cellGcm_rsx_progress() != db_prog || g_frames_presented != db_pres;
                if (db_early && !productive) {       /* came back early and found nothing: one bare sleep */
                    g_fc_db.wasted++;
                    usleep((useconds_t)us);
                    db_early = 0;
                } else
                    db_early = fc_idle_wait(us, spin_us, bell, productive, vbl_next);
                db_prog = cellGcm_rsx_progress();
                db_pres = g_frames_presented;
            } else {
                usleep((useconds_t)us);
                db_early = 0;
            }
'''
DB_LOG = r'''#if !defined(_WIN32)
        if (db_live && now - db_log >= 10000) {      /* rsx doorbell: what the waits did, per 10 s */
            unsigned c[3];
            cellGcm_rsx_doorbell_counts(c);
            if (db_log)
                fprintf(stderr, "[rsx doorbell] 10 s: %u waits skipped (work already there), %u spins (%u hit), "
                        "%u doorbell waits (%u ended early; rings: hle %u, spu label %u, ref read %u), "
                        "%u early passes found nothing\n",
                        g_fc_db.at_once, g_fc_db.spins, g_fc_db.spin_hits, g_fc_db.bells, g_fc_db.bell_early,
                        c[0], c[1], c[2], g_fc_db.wasted);
            memset(&g_fc_db, 0, sizeof g_fc_db);
            db_log = now;
        }
#endif
'''
if m:
    s = open(m).read()
    if "/* rsx doorbell (cellGcmSys.c) */" not in s:
        a_ext = "int      cellGcm_drain_sema_blocked(void);\n"
        a_fc = "static DWORD WINAPI frame_clock(LPVOID)\n{\n"
        a_env = "    { const char* e = getenv(\"PS3_FRAMECLOCK_US\"); if (e && atoi(e) > 0) clock_us_env = atoi(e); }\n"
        a_loop = "    uint64_t vbl_next = fc_now_ns();\n\n    for (;;) {\n"
        a_wait = ("#else\n"
                  "            usleep((useconds_t)us);\n"
                  "#endif\n"
                  "        }\n"
                  "        ULONGLONG now = GetTickCount64();\n")
        reps = [
            (a_ext, a_ext +
             "/* rsx doorbell (cellGcmSys.c) */\n"
             "int      cellGcm_rsx_idle_state(void);            /* 1 a pass now makes progress, 0 nothing to do, -1 stalled */\n"
             "int      cellGcm_rsx_doorbell_wait(unsigned us);  /* the timed sleep, ended early by a ring: 1 = early */\n"
             "unsigned cellGcm_rsx_progress(void);              /* passes that moved get */\n"
             "void     cellGcm_rsx_doorbell_counts(unsigned c[3]);\n"),
            (a_fc, DB_HELPERS + a_fc),
            (a_env, a_env + DB_ENV),
            (a_loop, "    uint64_t vbl_next = fc_now_ns();\n" + DB_VARS + "\n    for (;;) {\n"),
            (a_wait, "#else\n" + DB_WAIT + "#endif\n        }\n        ULONGLONG now = GetTickCount64();\n" + DB_LOG),
        ]
        for o, n in reps:
            if s.count(o) != 1:
                sys.exit("main.cpp: rsx doorbell: anchor found %d times, expected 1: %r" % (s.count(o), o[:70]))
            s = s.replace(o, n, 1)
        open(m, 'w').write(s)
    print('patched main.cpp rsx doorbell')
