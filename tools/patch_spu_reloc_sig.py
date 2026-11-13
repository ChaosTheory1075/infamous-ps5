# spu reloc sig: position-independent job modules found by CONTENT at branch-in time (inFAMOUS 1, 2026-11-03).
# inFAMOUS 1's job 209 copies twelve small WWS job modules (EBOOT 0x670100-0x684100: 4 x ila signature, header,
# code at +0x30) into its own LS buffer wherever there is room (seen at 0x31000-0x35FFF) and calls into them;
# none was lifted, so on the rooftop 84% of all interpreted SPU steps were theirs, and the interpreter's
# per-step lifted lookup was the hottest SPU leaf. They are lifted at LS 0 --relocatable
# (tools/lift_if1_plugmods.py) and registered with spu_overlay_register_reloc_sig. When dispatch finds no lift
# at pc, spu_reloc_sig_adopt looks back from pc for a registered signature at a 16-byte boundary, checks the
# module's code bytes against its EBOOT copy, and makes the lift resident there as a relocatable code slot
# (source_ea = the module, so the per-dispatch stale-word check still guards it). PS3_SPU_RELOC_SIG=0 = off.
edit("runtime/spu/spu_channels.c",
     '''/* Register one-way runtime entries that replace the guest call stack.''',
     '''/* spu reloc sig */
typedef struct { uint8_t sig[16]; uint32_t sig_off, ea, span, code_len; int image_id; } spu_rsig;
static spu_rsig s_rsig[32];
static int s_rsig_n;
/* sig = the module's 16 bytes at sig_off: job 209 copies from the code (+0x30), not the header. */
void spu_overlay_register_reloc_sig(const uint8_t sig[16], uint32_t sig_off, uint32_t content_ea, uint32_t span, uint32_t code_len, int image_id)
{
    if (s_rsig_n >= 32 || image_id <= 0 || image_id >= 4096 || sig_off + 16 > code_len) return;
    memcpy(s_rsig[s_rsig_n].sig, sig, 16); s_rsig[s_rsig_n].sig_off = sig_off;
    s_rsig[s_rsig_n].ea = content_ea; s_rsig[s_rsig_n].span = span;
    s_rsig[s_rsig_n].code_len = code_len < span ? code_len : span; s_rsig[s_rsig_n].image_id = image_id;
    s_rsig_n++;
    s_reloc_img[image_id] = 1;
    __atomic_add_fetch(&g_spu_reg_gen, 1, __ATOMIC_RELEASE);
}
/* Returns the slot + 1 the module covering pc was made resident in, or 0. */
int spu_reloc_sig_adopt(spu_context* ctx, uint32_t pc)
{
    static int on = -1;
    if (on < 0) { const char* e = getenv("PS3_SPU_RELOC_SIG"); on = !(e && e[0] == '0'); }
    if (!on || !s_rsig_n || !ctx->ls) return 0;
    pc &= SPU_LS_MASK;
    const uint32_t lo = pc > 0x8000u ? pc - 0x8000u : 0u;
    for (uint32_t pos = pc & ~15u; ; pos -= 16) {
        uint32_t w; memcpy(&w, ctx->ls + pos, 4);
        for (int i = 0; i < s_rsig_n; i++) {
            const spu_rsig* r = &s_rsig[i];
            uint32_t sw; memcpy(&sw, r->sig, 4);
            if (w != sw || pos < r->sig_off || memcmp(ctx->ls + pos, r->sig, 16)) continue;
            const uint32_t base = pos - r->sig_off;   /* the module's offset 0, where its lift's addresses start */
            if (pc - base >= r->span || base + r->code_len > SPU_LS_SIZE) continue;
            if (!gm_equal(vm_base + r->ea + r->sig_off + 16, ctx->ls + pos + 16, r->code_len - r->sig_off - 16)) continue;
            unsigned pick = SPU_RESIDENT_CODE_SLOTS;
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS; ++s)   /* same place first, then a free one */
                if (ctx->resident_code[s].image_id && ctx->resident_code[s].lsa == base) { pick = s; break; }
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS && pick == SPU_RESIDENT_CODE_SLOTS; ++s)
                if (!ctx->resident_code[s].image_id) pick = s;
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS && pick == SPU_RESIDENT_CODE_SLOTS; ++s)   /* else another adopted module */
                for (int k = 0; k < s_rsig_n; k++) if (ctx->resident_code[s].image_id == s_rsig[k].image_id) { pick = s; break; }
            if (pick == SPU_RESIDENT_CODE_SLOTS) return 0;
            /* an adopted module overlapping this one is gone (its bytes were overwritten) */
            for (unsigned s = 0; s < SPU_RESIDENT_CODE_SLOTS; ++s)
                if (s != pick && ctx->resident_code[s].image_id && ctx->resident_code[s].reloc &&
                    ctx->resident_code[s].lsa < base + r->span && base < ctx->resident_code[s].lsa + ctx->resident_code[s].size)
                    ctx->resident_code[s].image_id = 0;
            ctx->resident_code[pick].lsa = base; ctx->resident_code[pick].size = r->span;
            ctx->resident_code[pick].source_ea = r->ea; ctx->resident_code[pick].image_id = r->image_id;
            ctx->resident_code[pick].reloc = 1;
            ctx->ib_gen++;
            { static int _n = 0; if (PS3_LOG_FIRST(_n, 16))
                fprintf(stderr, "[spu-ovl] img=%d reloc sig: module ea=0x%08X resident at LS 0x%05X+0x%X as image %d (slot %u, pc 0x%05X)\\n",
                        ctx->image_id, r->ea, base, r->span, r->image_id, pick, pc); }
            return (int)pick + 1;
        }
        if (pos <= lo || pos < 16) return 0;
    }
}

/* Register one-way runtime entries that replace the guest call stack.''',
     "spu reloc sig")
edit("runtime/spu/spu_channels.c",
     '''    for (unsigned slot = 0; slot < SPU_RESIDENT_CODE_SLOTS && !fn && code_owner >= 0; ++slot)
        if (ctx->resident_code[slot].image_id && !ctx->resident_code[slot].reloc)
            fn = spu_lookup(ctx->pc, ctx->resident_code[slot].image_id);
    /* The job returned through the link register we planted: it is finished.''',
     '''    for (unsigned slot = 0; slot < SPU_RESIDENT_CODE_SLOTS && !fn && code_owner >= 0; ++slot)
        if (ctx->resident_code[slot].image_id && !ctx->resident_code[slot].reloc)
            fn = spu_lookup(ctx->pc, ctx->resident_code[slot].image_id);
    if (!fn && code_owner >= 0) {   /* spu reloc sig: a position-independent module copied here */
        extern int spu_reloc_sig_adopt(spu_context*, uint32_t);
        const int s1 = spu_reloc_sig_adopt(ctx, ctx->pc);
        if (s1 && (fn = spu_lookup(ctx->pc - ctx->resident_code[s1 - 1].lsa, ctx->resident_code[s1 - 1].image_id)))
            ctx->code_base = ctx->resident_code[s1 - 1].lsa;
    }
    /* The job returned through the link register we planted: it is finished.''',
     "spu reloc sig adopt")
