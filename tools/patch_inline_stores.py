# inline stores: lifted guest stores get the same inline fast path the loads have
# Every lifted stw/std/stb/sth was an out-of-line call into ppu_loader.cpp (vm_write32 etc.), and
# each of those called spu_coh_is_reserved -- another out-of-line call -- twice. On the console the
# main PPU thread (the frame limiter in all three games) was hot in vm_write32/vm_write64 and their
# coherence calls. Now the generated header stores inline when the address is ordinary guest
# memory (vm_inl_ok: no diagnostic armed, not the null page / raw SPU windows / gcm ref word / past
# the mapping), no write watch or null sweep is active, and the 128-byte line is not SPU-reserved
# (the bitmap and armed flag are read inline). After the store the line is checked again, as in
# VM_WRITE_COH, and a line reserved meanwhile gets the lock + LR notify (vm_coh_after_store).
# Everything else takes the old out-of-line call. -DPPU_NO_INLINE_STORES turns it off.
SCO = "runtime/spu/spu_coherency.c"
edit(SCO,
     '''static unsigned char s_coh_bitmap[SPU_COH_BITMAP_SZ];''',
     '''unsigned char s_coh_bitmap[SPU_COH_BITMAP_SZ];   /* read inline by ppu_recomp.h stores */''',
     "inline stores: bitmap")
edit(SCO,
     '''static int s_coh_armed;''',
     '''int s_coh_armed;   /* read inline by ppu_recomp.h stores */''',
     "inline stores: armed")

PLD = "runtime/ppu/ppu_loader.cpp"
edit(PLD,
     '''    v = __builtin_bswap64(v); VM_WRITE_COH(a, &v, 8); }
}''',
     '''    v = __builtin_bswap64(v); VM_WRITE_COH(a, &v, 8); }
/* The inline stores in ppu_recomp.h: the line became SPU-reserved between the check and the store. */
void vm_coh_after_store(uint32_t ca, uint32_t n)
{
    const uint64_t llm = spu_lockline_mask_range(ca, n);
    spu_lockline_lock_mask(llm);
    spu_coh_notify_write_from_ppu(ca);
    spu_lockline_unlock_mask(llm);
}
}''',
     "inline stores: after-store notify")

HDR_OLD = '''#define vm_read64(a) vm_read64_inl(a)
#endif
'''
HDR_NEW = '''#define vm_read64(a) vm_read64_inl(a)
#endif

/* Inline guest-store fast paths: plain memory, no watch, line not SPU-reserved (checked again after
 * the store, as VM_WRITE_COH does); everything else goes to the out-of-line vm_write*. */
#ifdef __cplusplus
extern "C" {
#endif
extern int           s_coh_armed;
extern unsigned char s_coh_bitmap[];
extern uint32_t      g_barrier_sync_watch, g_null_sweep_hi;
void vm_coh_after_store(uint32_t ea, uint32_t n);
#ifdef __cplusplus
}
#endif
static inline int vm_coh_res_inl(uint32_t ea)
{
    if (!__atomic_load_n(&s_coh_armed, __ATOMIC_ACQUIRE)) return 0;
    const uint32_t line = ea >> 7;
    return (__atomic_load_n(&s_coh_bitmap[line >> 3], __ATOMIC_RELAXED) >> (line & 7)) & 1u;
}
static inline int vm_st_inl_ok(uint32_t ea, uint32_t n)
{
    return vm_inl_ok(ea, n) && __builtin_expect(!g_barrier_sync_watch && !g_null_sweep_hi, 1) &&
           !vm_coh_res_inl(ea);
}
#define VM_ST_INL(T, raw, slow) do { const uint32_t _ea = (uint32_t)a; \\
    if (vm_st_inl_ok(_ea, sizeof(T))) { \\
        VM_RAW_ST(T, _ea, raw); \\
        __atomic_signal_fence(__ATOMIC_SEQ_CST); \\
        if (__builtin_expect(vm_coh_res_inl(_ea), 0)) vm_coh_after_store(_ea, sizeof(T)); \\
    } else slow; } while (0)
static inline void vm_write8_inl (uint64_t a, uint8_t  v) { VM_ST_INL(uint8_t,  v,                   vm_write8(a, v)); }
static inline void vm_write16_inl(uint64_t a, uint16_t v) { VM_ST_INL(uint16_t, __builtin_bswap16(v), vm_write16(a, v)); }
static inline void vm_write32_inl(uint64_t a, uint32_t v) { VM_ST_INL(uint32_t, __builtin_bswap32(v), vm_write32(a, v)); }
static inline void vm_write64_inl(uint64_t a, uint64_t v) { VM_ST_INL(uint64_t, __builtin_bswap64(v), vm_write64(a, v)); }
#ifndef PPU_NO_INLINE_STORES
#define vm_write8(a, v)  vm_write8_inl(a, v)
#define vm_write16(a, v) vm_write16_inl(a, v)
#define vm_write32(a, v) vm_write32_inl(a, v)
#define vm_write64(a, v) vm_write64_inl(a, v)
#endif
'''
for _g in ("if1", "if2", "fob"):
    edit(__import__("os").path.expanduser("~") + f"/{_g}/infamous2-lle/recompiled/ppu_recomp.h", HDR_OLD, HDR_NEW, f"inline stores: header {_g}")
edit(PLD,
     '''#define PPU_NO_INLINE_LOADS   /* this file defines the out-of-line accessors */''',
     '''#define PPU_NO_INLINE_LOADS   /* this file defines the out-of-line accessors */
#define PPU_NO_INLINE_STORES''',
     "inline stores: loader opt-out")
