
# tdump spu and event queues: PS3_THREAD_DUMP also prints every live SPU context and event queue
# A hang between a PPU thread and an SPU (Bink's RADG5 decoder: the PPU spins, the SPU waits on its
# event queue) shows only one side in the guest-thread list. Each SPU context: id, group, image, pc,
# status, event status/mask, stop code, inbound mailbox count; each active queue: type, name, count.
edit("runtime/spu/spu_channels.c",
     '''static spu_mfc_slot s_mfc_slots[SPU_MAX_CONTEXTS];
static SRWLOCK      s_mfc_claim_lock = SRWLOCK_INIT;''',
     '''static spu_mfc_slot s_mfc_slots[SPU_MAX_CONTEXTS];
static SRWLOCK      s_mfc_claim_lock = SRWLOCK_INIT;

/* PS3_THREAD_DUMP's SPU half (sys_ppu_thread.c): every context with an MFC slot. */
void spu_dump_contexts(void)
{
    for (int i = 0; i < SPU_MAX_CONTEXTS; i++) {
        const spu_context* c = __atomic_load_n(&s_mfc_slots[i].ctx, __ATOMIC_ACQUIRE);
        if (!c) continue;
        fprintf(stderr, "[tdump] spu ctx%-3d id=0x%X grp=0x%X img=%d pc=0x%05X status=0x%X evstat=0x%X evmask=0x%X stop=0x%X inmbox=%u\\n",
                i, c->spu_id, c->spu_group_id, c->image_id, c->pc & SPU_LS_MASK, c->status,
                c->event_status, c->event_mask, c->stop_code, (unsigned)spu_channel_count(&c->ch_in_mbox));
    }
}''',
     "tdump spu contexts")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''            fputc('\\n', stderr);
        }
        fflush(stderr);''',
     '''            fputc('\\n', stderr);
        }
        { extern void spu_dump_contexts(void); spu_dump_contexts(); }
        for (int q = 0; q < SYS_EVENT_QUEUE_MAX; q++) {
            const sys_event_queue_info* e = &g_sys_event_queues[q];
            if (!e->active) continue;
            fprintf(stderr, "[tdump] equeue %-3d type=%d name=%.8s key=0x%llX pending=%d%s\\n", q + 1, e->type,
                    e->name, (unsigned long long)e->key, e->count, e->cancelled ? " CANCELLED" : "");
        }
        fflush(stderr);''',
     "tdump event queues")
edit("runtime/syscalls/sys_ppu_thread.c",
     '''#ifndef _WIN32
#include <pthread.h>
#include <unistd.h>
static uint32_t td_rd32(uint32_t a)''',
     '''#ifndef _WIN32
#include <pthread.h>
#include <unistd.h>
#include "sys_event.h"   /* tdump: g_sys_event_queues */
static uint32_t td_rd32(uint32_t a)''',
     "tdump event include")
