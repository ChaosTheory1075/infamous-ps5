# vk pipe block: a draw into an off-screen target waits for its pipeline build instead of being skipped
VKF = "libs/video/rsx_vulkan_backend.c"
edit(VKF,
     '''static int s_pa_wait_ms = 8;''',
     '''static int s_pa_wait_ms = 8;
/* The draw at hand targets less than 3/4 of a 1280x720 screen (a reflection or shadow map, a
 * look-up table, a cube face): it waits for its build however long that takes. Skipping is only
 * safe for screen-sized targets, which are drawn again next frame; the console run that skipped
 * every late draw left inFAMOUS 2's metal props purple for good (an environment map drawn once at
 * load had been skipped). */
static int s_pa_block;
static unsigned s_pa_blocked;''',
     "vk pipe block: flag")
edit(VKF,
     '''    while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
        if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;''',
     '''    if (s_pa_block) {
        if (P->pend & (1u << topo)) s_pa_blocked++;
        while (P->pend & (1u << topo)) pthread_cond_wait(&s_pa_done, &s_pa_mu);
    } else
        while ((P->pend & (1u << topo)) && s_pa_wait_ms > 0)
            if (pthread_cond_timedwait(&s_pa_done, &s_pa_mu, &dl) != 0) break;''',
     "vk pipe block: submit wait")
edit(VKF,
     '''            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;''',
     '''            VK_LOG("engine: async pipelines in %.0f s: %u queued, %u in time, %u late (skipped until built), %u waited for (off-screen target), %u queue-full, %u failed; builds %.0f ms in all, longest %.0f ms\\n",
                   (now - t0) / 1e9, s_pa_queued, s_pa_in_time, s_pa_late, s_pa_blocked, s_pa_skips, s_pa_fail, s_pa_sum_ms, s_pa_max_ms);
            s_pa_queued = s_pa_in_time = s_pa_late = s_pa_blocked = s_pa_skips = s_pa_fail = 0; s_pa_sum_ms = s_pa_max_ms = 0; t0 = now;''',
     "vk pipe block: log")
edit(VKF,
     '''        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx))
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */''',
     '''        if (__atomic_load_n(&P->pend, __ATOMIC_ACQUIRE) & (1u << topo_idx)) {
            if (s_pa_block) {                                                  /* off-screen: wait */
                pthread_mutex_lock(&s_pa_mu);
                if (P->pend & (1u << topo_idx)) s_pa_blocked++;
                while (P->pend & (1u << topo_idx)) pthread_cond_wait(&s_pa_done, &s_pa_mu);
                pthread_mutex_unlock(&s_pa_mu);
            }
            return __atomic_load_n(&P->variant[topo_idx], __ATOMIC_ACQUIRE);   /* still building */
        }''',
     "vk pipe block: pending wait")
edit(VKF,
     '''    VkPipeline pipe = vk_eng_variant(P, (u32)topology - 1u);
    VkRenderPass rp = vk_eng_render_pass(n);''',
     '''    s_pa_block = (uint64_t)w * h < 1280u * 720u * 3u / 4u;
    VkPipeline pipe = vk_eng_variant(P, (u32)topology - 1u);
    VkRenderPass rp = vk_eng_render_pass(n);''',
     "vk pipe block: draw size")
