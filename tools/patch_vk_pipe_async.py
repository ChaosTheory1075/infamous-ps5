# vk pipe async: engine pipelines are built on worker threads; a draw waits a few ms for its build, then is skipped until it is ready
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>''',
     '''#include <dlfcn.h>
#include <pthread.h>
#include <time.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>''',
     "vk pipe async: includes")
edit(VKF,
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];
} vk_eng_pipe;''',
     '''    u32                 cube_mask;    /* pixel shader's TextureCube units */
    VkPipeline          variant[VK_ENG_TOPOLOGIES];
    u32                 pend, bad;    /* variants being built on a worker / whose build failed */
} vk_eng_pipe;''',
     "vk pipe async: pipe fields")
edit(VKF,
     '''static void vk_eng_pipeline_release(void* user, u32 pipeline)
{
    (void)user;
    if (!pipeline || pipeline > VK_ENG_MAX_PIPE || !s_epipe[pipeline - 1].used) return;
    vk_eng_pipe* P = &s_epipe[pipeline - 1];''',
     '''/* Pipeline builds off the RSX thread (PS3RECOMP_VK_ASYNC_PIPE=0 turns it off). On the console a
 * pipeline the driver had not built before took 0.2-0.9 s in vkCreateGraphicsPipelines, on the RSX
 * thread, in the middle of a frame: inFAMOUS 2's 1-2.7 s freezes, FoB's hitches. Now the first draw
 * that needs a variant hands a copy of its create info to a worker (PS3RECOMP_VK_PIPE_THREADS, 2)
 * and waits up to PS3RECOMP_VK_PIPE_WAIT_MS (8) for it: a build the driver's cache answers is back
 * well within that and the draw happens as before. A longer one is not waited for: its draws are
 * skipped until it is done (the object appears a moment later). A pipeline released while one of
 * its variants is being built waits for that build first, so the shader modules outlive it. */
typedef struct {
    vk_eng_pipe* P;
    u32 topo;
    VkGraphicsPipelineCreateInfo gci;
    VkPipelineShaderStageCreateInfo st[2];
    VkVertexInputBindingDescription vb;
    VkVertexInputAttributeDescription va[VK_GUEST_ATTRS];
    VkPipelineVertexInputStateCreateInfo vi;
    VkPipelineInputAssemblyStateCreateInfo ia;
    VkPipelineViewportStateCreateInfo vps;
    VkPipelineRasterizationStateCreateInfo ras;
    VkPipelineMultisampleStateCreateInfo ms;
    VkPipelineDepthStencilStateCreateInfo ds;
    VkPipelineColorBlendAttachmentState cba[RSX_BE_MAX_COLOR_TARGETS];
    VkPipelineColorBlendStateCreateInfo cb;
    VkDynamicState dyn[8];
    VkPipelineDynamicStateCreateInfo dy;
} vk_pa_job;
void ps3_host_thread_label(const char* name) __attribute__((weak));   /* host_qos.h: the PS5 profile's names */
#define VK_PA_QUEUE 256u
static pthread_mutex_t s_pa_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  s_pa_work = PTHREAD_COND_INITIALIZER, s_pa_done = PTHREAD_COND_INITIALIZER;
static vk_pa_job s_pa_q[VK_PA_QUEUE];
static u32 s_pa_head, s_pa_tail;               /* s_pa_q[head % N] is the next job */
static u32 s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail;
static double s_pa_max_ms, s_pa_sum_ms;
static int s_pa_wait_ms = 8;

static void* vk_pa_worker(void* arg)
{
    (void)arg;
    if (ps3_host_thread_label) ps3_host_thread_label("vk pipeline build");
    for (;;) {
        pthread_mutex_lock(&s_pa_mu);
        while (s_pa_head == s_pa_tail) pthread_cond_wait(&s_pa_work, &s_pa_mu);
        vk_pa_job j = s_pa_q[s_pa_head % VK_PA_QUEUE];
        s_pa_head++;
        pthread_mutex_unlock(&s_pa_mu);
        /* the copy's pointers into the queue slot are re-aimed at this one */
        j.gci.pStages = j.st; j.vi.pVertexBindingDescriptions = &j.vb; j.vi.pVertexAttributeDescriptions = j.va;
        j.gci.pVertexInputState = &j.vi; j.gci.pInputAssemblyState = &j.ia; j.gci.pViewportState = &j.vps;
        j.gci.pRasterizationState = &j.ras; j.gci.pMultisampleState = &j.ms; j.gci.pDepthStencilState = &j.ds;
        j.cb.pAttachments = j.cba; j.gci.pColorBlendState = &j.cb; j.dy.pDynamicStates = j.dyn; j.gci.pDynamicState = &j.dy;
        const uint64_t t0 = ps3_ft_now();
        VkPipeline p = VK_NULL_HANDLE;
        const VkResult r = pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &j.gci, NULL, &p);
        const double ms = (ps3_ft_now() - t0) / 1e6;
        if (ms > 50.0) VK_LOG("engine: pipeline build took %.0f ms (topology %u, worker)\\n", ms, j.topo);
        pthread_mutex_lock(&s_pa_mu);
        if (r == VK_SUCCESS && p) __atomic_store_n(&j.P->variant[j.topo], p, __ATOMIC_RELEASE);
        else { j.P->bad |= 1u << j.topo; s_pa_fail++; VK_LOG("engine: vkCreateGraphicsPipelines failed (%d, worker)\\n", (int)r); }
        __atomic_and_fetch(&j.P->pend, ~(1u << j.topo), __ATOMIC_RELEASE);
        if (ms > s_pa_max_ms) s_pa_max_ms = ms;
        s_pa_sum_ms += ms;
        pthread_cond_broadcast(&s_pa_done);
        pthread_mutex_unlock(&s_pa_mu);
    }
    return NULL;
}

static int vk_pa_on(void)
{
    static int on = -1;
    if (on >= 0) return on;
    const char* e = getenv("PS3RECOMP_VK_ASYNC_PIPE");
    on = 0;
    if (e && e[0] == '0') return 0;
    const char* w = getenv("PS3RECOMP_VK_PIPE_WAIT_MS");
    if (w && *w) s_pa_wait_ms = atoi(w);
    const char* t = getenv("PS3RECOMP_VK_PIPE_THREADS");
    int n = t && *t ? atoi(t) : 2;
    if (n < 1) n = 1;
    if (n > 4) n = 4;
    int made = 0;
    for (int i = 0; i < n; i++) {
        pthread_t th;
        pthread_attr_t a;
        pthread_attr_init(&a);
        pthread_attr_setstacksize(&a, 2u << 20);
        if (pthread_create(&th, &a, vk_pa_worker, NULL) == 0) { pthread_detach(th); made++; }
        pthread_attr_destroy(&a);
    }
    on = made > 0;
    VK_LOG("engine: pipelines built on %d worker thread(s), a draw waits up to %d ms for its build\\n", made, s_pa_wait_ms);
    return on;
}

/* Queue the build of P's variant `topo` from `g` (all of it copied) and wait up to the budget. */
static VkPipeline vk_pa_submit(vk_eng_pipe* P, u32 topo, const VkGraphicsPipelineCreateInfo* g)
{
    pthread_mutex_lock(&s_pa_mu);
    if (s_pa_tail - s_pa_head >= VK_PA_QUEUE) { pthread_mutex_unlock(&s_pa_mu); s_pa_skips++; return VK_NULL_HANDLE; }
    vk_pa_job* j = &s_pa_q[s_pa_tail % VK_PA_QUEUE];
    memset(j, 0, sizeof *j);
    j->P = P; j->topo = topo;
    j->gci = *g;
    memcpy(j->st, g->pStages, sizeof j->st);
    j->vi = *g->pVertexInputState;
    if (j->vi.vertexBindingDescriptionCount) j->vb = *g->pVertexInputState->pVertexBindingDescriptions;
    if (j->vi.vertexAttributeDescriptionCount > VK_GUEST_ATTRS) j->vi.vertexAttributeDescriptionCount = VK_GUEST_ATTRS;
    memcpy(j->va, g->pVertexInputState->pVertexAttributeDescriptions, j->vi.vertexAttributeDescriptionCount * sizeof j->va[0]);
    j->ia = *g->pInputAssemblyState; j->vps = *g->pViewportState; j->ras = *g->pRasterizationState;
    j->ms = *g->pMultisampleState; j->ds = *g->pDepthStencilState;
    j->cb = *g->pColorBlendState;
    if (j->cb.attachmentCount > RSX_BE_MAX_COLOR_TARGETS) j->cb.attachmentCount = RSX_BE_MAX_COLOR_TARGETS;
    memcpy(j->cba, g->pColorBlendState->pAttachments, j->cb.attachmentCount * sizeof j->cba[0]);
    j->dy = *g->pDynamicState;
    if (j->dy.dynamicStateCount > 8) j->dy.dynamicStateCount = 8;
    memcpy(j->dyn, g->pDynamicState->pDynamicStates, j->dy.dynamicStateCount * sizeof j->dyn[0]);
    __atomic_or_fetch(&P->pend, 1u << topo, __ATOMIC_RELEASE);
    s_pa_tail++;
    s_pa_queued++;
    pthread_cond_signal(&s_pa_work);
    struct timespec dl;
    clock_gettime(CLOCK_REALTIME, &dl);
    dl.tv_nsec += (long)s_pa_wait_ms * 1000000L;
    while (dl.tv_nsec >= 1000000000L) { dl.tv_nsec -= 1000000000L; dl.tv_sec++; }
    while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
        if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;
    const int late = (P->pend & (1u << topo)) != 0;
    if (late) s_pa_late++; else s_pa_in_time++;
    {   static uint64_t t0;
        const uint64_t now = ps3_ft_now();
        if (!t0) t0 = now;
        if (now - t0 >= 10000000000ull) {
            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;
        } }
    pthread_mutex_unlock(&s_pa_mu);
    return __atomic_load_n(&P->variant[topo], __ATOMIC_ACQUIRE);
}

/* Every variant of P that a worker is building is finished. */
static void vk_pa_wait_idle(vk_eng_pipe* P)
{
    if (!__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE)) return;
    pthread_mutex_lock(&s_pa_mu);
    while (P->pend) pthread_cond_wait(&s_pa_done, &s_pa_mu);
    pthread_mutex_unlock(&s_pa_mu);
}

static void vk_eng_pipeline_release(void* user, u32 pipeline)
{
    (void)user;
    if (!pipeline || pipeline > VK_ENG_MAX_PIPE || !s_epipe[pipeline - 1].used) return;
    vk_eng_pipe* P = &s_epipe[pipeline - 1];
    vk_pa_wait_idle(P);''',
     "vk pipe async: workers")
edit(VKF,
     '''        VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP };
    if (P->variant[topo_idx]) return P->variant[topo_idx];''',
     '''        VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP };
    {   const VkPipeline have = __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);
        if (have) return have;
        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx))
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */
        if (P->bad & (1u << topo_idx)) return VK_NULL_HANDLE; }''',
     "vk pipe async: variant check")
edit(VKF,
     '''    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {''',
     '''    if (vk_pa_on()) return vk_pa_submit(P, topo_idx, &gci);
    const uint64_t pc0 = ps3_ft_now();
    if (pvkCreateGraphicsPipelines(s_vk.device, VK_NULL_HANDLE, 1, &gci, NULL,
                                   &P->variant[topo_idx]) != VK_SUCCESS) {''',
     "vk pipe async: submit")
