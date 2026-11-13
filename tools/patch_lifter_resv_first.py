# lifter resv first: lwarx/ldarx register the line reservation before the load (see
# tools/resv_note_first.py, which rewrote the already-generated inFAMOUS 1 sources the same way):
# a writer committing between a load and a later registration was never seen by the
# store-conditional -> lost wake-ups (inFAMOUS 1 load-screen stall, 2026-11-02).
LIFT = "tools/ppu_lifter.py"
edit(LIFT,
     '''            return (f"{{ uint64_t ea = {ea}; "
                    f"ctx->gpr[{rd}] = vm_read32(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; "
                    f"ppu_resv_line_note(ea); }}")''',
     '''            return (f"{{ uint64_t ea = {ea}; ppu_resv_line_note(ea); "   # lifter resv first: reserve, then load
                    f"ctx->gpr[{rd}] = vm_read32(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; }}")''',
     "lifter resv first: lwarx")
edit(LIFT,
     '''            return (f"{{ uint64_t ea = {ea}; "
                    f"ctx->gpr[{rd}] = vm_read64(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; "
                    f"ppu_resv_line_note(ea); }}")''',
     '''            return (f"{{ uint64_t ea = {ea}; ppu_resv_line_note(ea); "   # lifter resv first: reserve, then load
                    f"ctx->gpr[{rd}] = vm_read64(ea); "
                    f"ctx->reserve_addr = (uint32_t)ea; ctx->reserve_value = ctx->gpr[{rd}]; }}")''',
     "lifter resv first: ldarx")
