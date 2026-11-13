
/* ppu sp fast (2026-11-10): guest accesses addressed off r1 (the thread's stack -- plain guest memory, never MMIO
 * or the HLE inject page) skip the range/inject check and the pre-store reservation check; the store still
 * re-checks the SPU reservation bitmap after it (as VM_ST_INL does), so a reserved stack line still notifies.
 * tools: the lifted .cpp calls vm_sp_*(ctx->gpr[1] ...) (patched by work/ppu_sp_patch.py). */
#define VM_SP_ST(T, ea, val) do { const uint32_t _se = (uint32_t)(ea); const T _sv = (val); \
    memcpy(vm_base + _se, &_sv, sizeof(T)); __atomic_signal_fence(__ATOMIC_SEQ_CST); \
    if (__builtin_expect(vm_coh_res_inl(_se), 0)) vm_coh_after_store(_se, sizeof(T)); } while (0)
static inline __attribute__((always_inline)) void vm_sp_write8 (uint64_t a, uint8_t  v) { VM_SP_ST(uint8_t,  a, v); }
static inline __attribute__((always_inline)) void vm_sp_write16(uint64_t a, uint16_t v) { VM_SP_ST(uint16_t, a, __builtin_bswap16(v)); }
static inline __attribute__((always_inline)) void vm_sp_write32(uint64_t a, uint32_t v) { VM_SP_ST(uint32_t, a, __builtin_bswap32(v)); }
static inline __attribute__((always_inline)) void vm_sp_write64(uint64_t a, uint64_t v) { VM_SP_ST(uint64_t, a, __builtin_bswap64(v)); }
static inline __attribute__((always_inline)) uint8_t  vm_sp_read8 (uint64_t a) { uint8_t  v; memcpy(&v, vm_base + (uint32_t)a, 1); return v; }
static inline __attribute__((always_inline)) uint16_t vm_sp_read16(uint64_t a) { uint16_t v; memcpy(&v, vm_base + (uint32_t)a, 2); return __builtin_bswap16(v); }
static inline __attribute__((always_inline)) uint32_t vm_sp_read32(uint64_t a) { uint32_t v; memcpy(&v, vm_base + (uint32_t)a, 4); return __builtin_bswap32(v); }
static inline __attribute__((always_inline)) uint64_t vm_sp_read64(uint64_t a) { uint64_t v; memcpy(&v, vm_base + (uint32_t)a, 8); return __builtin_bswap64(v); }
