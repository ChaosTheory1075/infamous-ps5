# perfdiag: thread labels, periodic ftrace windows, present GPU wait, flush sites, file read spans
edit("runtime/platform/host_qos.h",
     '''#define PS3_HOST_QOS_PPU_INTERACTIVE_BELOW 1500
''',
     '''#define PS3_HOST_QOS_PPU_INTERACTIVE_BELOW 1500

/* The host thread's name for the PS5 build's profile and wait reports
 * (tools/ps5/ps5_shims.c defines ps3_host_thread_label). Weak, so a host
 * without it links and this is a no-op. */
#if defined(__GNUC__) || defined(__clang__)
#ifdef __cplusplus
extern "C" {
#endif
void ps3_host_thread_label(const char* name) __attribute__((weak));
#ifdef __cplusplus
}
#endif
static inline void ps3_host_label(const char* name) { if (ps3_host_thread_label) ps3_host_thread_label(name); }
#else
static inline void ps3_host_label(const char* name) { (void)name; }
#endif
''',
     "perfdiag: label hook")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''    { extern void ppu_resv_register(ppu_context*); ppu_resv_register(&info->ctx); }''',
     '''    { extern void ppu_resv_register(ppu_context*); ppu_resv_register(&info->ctx); }
    ps3_host_label(info->name[0] ? info->name : "ppu");''',
     "perfdiag: ppu label")
edit("runtime/syscalls/lv2_register.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h): the SPUs set the frame rate */''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h): the SPUs set the frame rate */
    { char nm[24]; snprintf(nm, sizeof nm, "spu %X.%u", t->group_id, t->index); ps3_host_label(nm); }''',
     "perfdiag: spu label")
edit("runtime/syscalls/lv2_register.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    int32_t rc = 0;''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu fallback");
    int32_t rc = 0;''',
     "perfdiag: spu fallback label")
edit("runtime/spu/spu_workload.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    spu_async_run((spu_async_job*)p);''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu async");
    spu_async_run((spu_async_job*)p);''',
     "perfdiag: spu async label")
edit("runtime/spu/spu_workload.c",
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    spu_task_interp_run(j);''',
     '''    ps3_host_qos_self(1);   /* PS3_QOS (host_qos.h) */
    ps3_host_label("spu task interp");
    spu_task_interp_run(j);''',
     "perfdiag: spu task label")

# ---- ftrace: periodic windows (PS3_FTRACE_EVERY=<period s>:<count>) and file read spans ----
edit("include/ps3emu/ps3_ftrace.h",
     '''    PS3_FT_TEXUP       = 17, /* RSX thread decoded + uploaded a guest texture: a = source KB,
                              * b = 0 new, 1 content changed; | 2 when it evicted another */''',
     '''    PS3_FT_TEXUP       = 17, /* RSX thread decoded + uploaded a guest texture: a = source KB,
                              * b = 0 new, 1 content changed; | 2 when it evicted another */
    PS3_FT_FSREAD      = 18, /* a guest file read: who = PPU tid, a = bytes read, b = fd */''',
     "perfdiag: fsread kind")
edit("include/ps3emu/ps3_ftrace.h",
     '''    ps3_ft_rec* buf;
    char path[1024];''',
     '''    ps3_ft_rec* buf;
    uint64_t period;     /* PS3_FTRACE_EVERY: next window this much later, `left` more of them */
    uint32_t left, k;
    char path[1024];''',
     "perfdiag: rotate state")
edit("include/ps3emu/ps3_ftrace.h",
     '''                atexit(ps3_ft_dump_atexit);''',
     '''                atexit(ps3_ft_dump_atexit);
                {   /* PS3_FTRACE_EVERY=<period s>:<count>: a window every <period> s, <path>.<k>.txt */
                    const char* ev = getenv("PS3_FTRACE_EVERY");
                    double per = 0; unsigned cnt = 0;
                    if (ev && sscanf(ev, "%lf:%u", &per, &cnt) == 2 && per > secs && cnt > 1) {
                        s->period = (uint64_t)(per * 1e9); s->left = cnt; s->k = 0;
                        fprintf(stderr, "[ftrace] then every %.0f s, %u windows in all, to %s.<k>.txt\\n", per, cnt, s->path);
                    }
                }''',
     "perfdiag: rotate init")
edit("include/ps3emu/ps3_ftrace.h",
     '''static inline void ps3_ft_dump_atexit(void) { ps3_ft_dump(); }''',
     '''static inline void ps3_ft_dump_atexit(void) { ps3_ft_dump(); }

/* PS3_FTRACE_EVERY: write the window that just ended to <path>.<k>.txt and arm the next one. The
 * thread whose span crossed the end does it; the others see "not recording" meanwhile. */
static inline void ps3_ft_rotate(void)
{
    ps3_ft_state* s = &g_ps3_ft;
    int expect = 2;
    if (!__atomic_compare_exchange_n(&s->on, &expect, 1, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    char base[1024];
    snprintf(base, sizeof base, "%s", s->path);
    snprintf(s->path, sizeof s->path, "%s.%u.txt", base, s->k);
    __atomic_store_n(&s->dumped, 0, __ATOMIC_RELEASE);
    ps3_ft_dump();                                    /* on -> 3 while it writes */
    snprintf(s->path, sizeof s->path, "%s", base);
    s->k++;
    if (--s->left == 0) return;                       /* that was the last: stays off */
    const uint64_t win = s->end - s->start;
    s->start += s->period;
    s->end = s->start + win;
    memset(s->us, 0, sizeof s->us);
    __atomic_store_n(&s->dropped, 0, __ATOMIC_RELAXED);
    __atomic_store_n(&s->n, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&s->dumped, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&s->on, 2, __ATOMIC_RELEASE);
}''',
     "perfdiag: rotate")
edit("include/ps3emu/ps3_ftrace.h",
     '''    if (t0 > s->end) { ps3_ft_dump(); return; }''',
     '''    if (t0 > s->end) { if (s->period) ps3_ft_rotate(); else ps3_ft_dump(); return; }''',
     "perfdiag: rotate at end")

edit("runtime/ppu/ppu_fs.cpp",
     '''#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */''',
     '''#include "../../include/ps3emu/log_first.h"   /* PS3_LOG_FIRST */
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: file read spans */''',
     "perfdiag: fs include")
edit("runtime/ppu/ppu_fs.cpp",
     '''    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */''',
     '''    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */
    if (ft_r0) ps3_ft_span(PS3_FT_FSREAD, (uint32_t)ctx->thread_id, (uint32_t)n, (uint32_t)fd, ft_r0, ps3_ft_now());''',
     "perfdiag: cellFsRead span")
edit("runtime/syscalls/sys_fs.c",
     '''#include "../memory/vm.h"''',
     '''#include "../memory/vm.h"
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: file read spans */''',
     "perfdiag: sys_fs include")
edit("runtime/syscalls/sys_fs.c",
     '''    size_t nread = fread(buf, 1, (size_t)size, f->fp);''',
     '''    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t nread = fread(buf, 1, (size_t)size, f->fp);
    if (ft_r0) ps3_ft_span(PS3_FT_FSREAD, (uint32_t)ctx->thread_id, (uint32_t)nread, (uint32_t)fd, ft_r0, ps3_ft_now());''',
     "perfdiag: sys_fs_read span")

# ---- Vulkan: every flush is a full GPU wait; count them by call site, always (not only in a trace) ----
edit("libs/video/rsx_vulkan_backend.c",
     '''static int vk_submit_and_wait_at(int line)
{''',
     '''/* "[vk] flush sites" every 10 s: each vk_flush / present is a submit and a wait for the GPU to
 * finish everything, so how many a second and from where is most of the CPU<->GPU picture.
 * The RSX thread is the only caller. */
static void vk_flush_note(int line, uint64_t wait_ns)
{
    enum { N = 48 };
    static struct { int line; unsigned n; uint64_t ns; } s[N];
    static uint64_t t0;
    const uint64_t now = ps3_ft_now();
    if (!t0) t0 = now;
    int i = 0;
    while (i < N && s[i].n && s[i].line != line) i++;
    if (i < N) { s[i].line = line; s[i].n++; s[i].ns += wait_ns; }
    if (now - t0 < 10000000000ull) return;
    const double secs = (double)(now - t0) / 1e9;
    unsigned tot = 0; uint64_t tns = 0;
    for (int k = 0; k < N && s[k].n; k++) { tot += s[k].n; tns += s[k].ns; }
    fprintf(stderr, "[vk] flush sites: %.1f/s, GPU wait %.1f ms/s:", tot / secs, tns / 1e6 / secs);
    for (int r = 0; r < 10; r++) {
        int b = -1;
        for (int k = 0; k < N && s[k].n; k++) if (s[k].line >= 0 && (b < 0 || s[k].ns > s[b].ns)) b = k;
        if (b < 0) break;
        fprintf(stderr, " line %d %.1f/s %.1f ms/s;", s[b].line, s[b].n / secs, s[b].ns / 1e6 / secs);
        s[b].line = -1 - s[b].line;   /* printed */
    }
    fputc('\\n', stderr);
    memset(s, 0, sizeof s);
    t0 = now;
}

static int vk_submit_and_wait_at(int line)
{''',
     "perfdiag: flush note")
edit("libs/video/rsx_vulkan_backend.c",
     '''    const uint64_t ft0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    if (ft0) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u,
                         (uint32_t)line, ft0, ps3_ft_now());''',
     '''    const uint64_t ft0 = ps3_ft_now();
    VK_CHECK(pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX), "vkWaitForFences");
    const uint64_t ft1 = ps3_ft_now();
    if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, s_force ? 0u : 1u, (uint32_t)line, ft0, ft1);
    vk_flush_note(line, ft1 - ft0);''',
     "perfdiag: flush wait")
edit("libs/video/rsx_vulkan_backend.c",
     '''    pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX);

    VkPresentInfoKHR pi = {''',
     '''    {   const uint64_t pw0 = ps3_ft_now();
        pvkWaitForFences(s_vk.device, 1, &s_vk.fence, VK_TRUE, UINT64_MAX);
        const uint64_t pw1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_GPU_WAIT, 0, 1u, (uint32_t)__LINE__, pw0, pw1);
        vk_flush_note(__LINE__, pw1 - pw0); }

    VkPresentInfoKHR pi = {''',
     "perfdiag: present wait")

# ---- shader stalls: time SPIR-V cache misses (and keep slow ones' HLSL), time the driver's pipeline builds ----
edit("libs/video/rsx_shader_spirv.cpp",
     '''#include <vector>
#include <unistd.h>''',
     '''#include <vector>
#include <unistd.h>
#include <chrono>
#include "../../include/ps3emu/ps3_ftrace.h"   /* PS3_FTRACE: who = 5 a SPIR-V cache miss compiled */''',
     "perfdiag: spirv include")
edit("libs/video/rsx_shader_spirv.cpp",
     '''    const int rc = rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    if (rc == 0 && *out_words) {''',
     '''    /* A miss: compile it, and say so ("[spv] miss" lines; the slow ones' HLSL to
     * PS3RECOMP_SPIRV_MISS_DIR/<key>.hlsl, so text that differs run to run -- a cache that
     * never hits -- can be diffed). */
    const auto m0 = std::chrono::steady_clock::now();
    const uint64_t ft_m0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const int rc = rsx_hlsl_to_spirv_compile(hlsl, stage, words, max_words, out_words, log, log_size);
    if (ft_m0) ps3_ft_span(PS3_FT_COMPILE, 5, rc == 0, (uint32_t)strlen(hlsl), ft_m0, ps3_ft_now());
    {   const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - m0).count();
        static int said = 0;
        if (said < 3000) { said++;
            fprintf(stderr, "[spv] miss %016llx %s %zu chars: %.1f ms%s\\n", spv_cache_key(hlsl, stage, rcp),
                    stage == RSX_SHADER_STAGE_VERTEX ? "vs" : "fs", strlen(hlsl), ms, rc ? " (failed)" : ""); }
        static const char* mdir = (const char*)-1;
        if (mdir == (const char*)-1) { mdir = getenv("PS3RECOMP_SPIRV_MISS_DIR"); if (mdir && !*mdir) mdir = nullptr; }
        static int kept = 0;
        if (mdir && ms > 50.0 && kept < 200) {
            char hp[1100];
            snprintf(hp, sizeof hp, "%s/%016llx.hlsl", mdir, spv_cache_key(hlsl, stage, rcp));
            if (FILE* f = fopen(hp, "wb")) { fputs(hlsl, f); fclose(f); kept++; }
        } }
    if (rc == 0 && *out_words) {''',
     "perfdiag: spirv miss timing")
edit("libs/video/rsx_vulkan_backend.c",
     '''    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {
        VK_LOG("engine: vkCreateGraphicsPipelines failed\\n");
        P->variant[topo_idx] = VK_NULL_HANDLE;
    }
    return P->variant[topo_idx];''',
     '''    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {
        VK_LOG("engine: vkCreateGraphicsPipelines failed\\n");
        P->variant[topo_idx] = VK_NULL_HANDLE;
    }
    {   /* the driver's pipeline build (RADV/ACO, the Mesa disk cache), at the first draw that needs it */
        const uint64_t pc1 = ps3_ft_now();
        if (PS3_FT_ON()) ps3_ft_span(PS3_FT_COMPILE, 6, P->variant[topo_idx] != VK_NULL_HANDLE, topo_idx, pc0, pc1);
        static unsigned n; static uint64_t ns, t0;
        n++; ns += pc1 - pc0;
        if (!t0) t0 = pc1;
        if (pc1 - pc0 > 50000000ull) VK_LOG("engine: pipeline build took %.0f ms (topology %u)\\n", (pc1 - pc0) / 1e6, topo_idx);
        if (pc1 - t0 > 10000000000ull) {
            if (n) VK_LOG("engine: %u pipeline builds in %.0f s, %.0f ms in all\\n", n, (pc1 - t0) / 1e9, ns / 1e6);
            n = 0; ns = 0; t0 = pc1;
        } }
    return P->variant[topo_idx];''',
     "perfdiag: pipeline build timing")
