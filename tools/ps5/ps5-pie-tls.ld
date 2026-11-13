/*
 * ps5-native-app-boilerplate - Intermediate PIE linker layout (inFAMOUS copy with a PT_TLS).
 * Copyright (C) 2026 BlackBearReloaded
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Keeps code, immutable data, RELRO, and writable data in distinct address
 * ranges. The native converter replaces LLVM's generic dynamic metadata.
 */

OUTPUT_FORMAT("elf64-x86-64")
OUTPUT_ARCH(i386:x86-64)

PHDRS {
    text PT_LOAD FLAGS (0x5);
    ro PT_LOAD FLAGS (0x4);
    relro PT_LOAD FLAGS (0x6);
    data PT_LOAD FLAGS (0x6);
    dynamic PT_DYNAMIC FLAGS (0x6);
    tls PT_TLS FLAGS (0x4);
}

SECTIONS {
    .text 0 : ALIGN(CONSTANT(MAXPAGESIZE)) {
        QUAD(0xcccccccccccccccc)
        QUAD(0xcccccccccccccccc)
        /* ps5 text hot (agent_ppucost 2026-11-11): the PGO section prefixes grouped as GNU ld's default script
         * does on the BC (cold first, then hot, then the rest). With the plain *(.text .text.*) the 572 PGO-hot
         * lifted if1 functions (3.5 MB) were spread over 65 MB of text; the BC packs them into 3.5 MB. */
        *(.text.unlikely .text.*_unlikely .text.unlikely.*)
        *(.text.exit .text.exit.*)
        *(.text.startup .text.startup.*)
        *(.text.hot .text.hot.*)
        *(.text .text.*)
        *(.plt .plt.*)
    } : text

    .eh_frame_hdr : ALIGN(CONSTANT(MAXPAGESIZE)) {
        KEEP(*(.eh_frame_hdr))
    } : ro
    .eh_frame : { KEEP(*(.eh_frame)) } : ro
    .gcc_except_table : { *(.gcc_except_table .gcc_except_table.*) } : ro
    .rodata : { *(.rodata .rodata.*) } : ro

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    /* inFAMOUS: ReCharged: a PT_TLS for the runtime's native thread-locals (ps5cc builds with
     * -fno-emulated-tls). Aligned to 32, the alignment ps5-native-tool gives the eboot's PT_TLS,
     * placed inside RELRO between .data.rel.ro and .got: the tool starts the RELRO segment at its
     * first .data.rel.ro/.got/array section (.tdata first fell outside the loaded segment: no launch)
     * and writes the SCE process parameters right after .fini_array (.tdata there was overwritten).
     * lld's local-exec offsets (tp - align(size, 32)) match where the loader puts the block. */
    .data.rel.ro : {
        *(.data.rel.ro .data.rel.ro.*)
    } : relro
    .tdata : ALIGN(32) { *(.tdata .tdata.*) } : relro : tls
    .tbss : ALIGN(32) { *(.tbss .tbss.*) . = ALIGN(32); } : relro : tls
    .got : { *(.got) } : relro
    .got.plt : { *(.got.plt) } : relro
    .preinit_array : {
        PROVIDE_HIDDEN(__preinit_array_start = .);
        KEEP(*(.preinit_array))
        PROVIDE_HIDDEN(__preinit_array_end = .);
    } : relro
    .init_array : {
        PROVIDE_HIDDEN(__init_array_start = .);
        KEEP(*(SORT_BY_INIT_PRIORITY(.init_array.*) SORT_BY_INIT_PRIORITY(.ctors.*)))
        KEEP(*(.init_array .ctors))
        PROVIDE_HIDDEN(__init_array_end = .);
    } : relro
    .fini_array : {
        PROVIDE_HIDDEN(__fini_array_start = .);
        KEEP(*(SORT_BY_INIT_PRIORITY(.fini_array.*) SORT_BY_INIT_PRIORITY(.dtors.*)))
        KEEP(*(.fini_array .dtors))
        PROVIDE_HIDDEN(__fini_array_end = .);
    } : relro

    /* Kept only long enough for the converter to read and rewrite them. */
    .dynsym : { *(.dynsym) } : relro
    .gnu.hash : { *(.gnu.hash) } : relro
    .dynstr : { *(.dynstr) } : relro
    .rela.dyn : { *(.rela.dyn) } : relro
    .rela.plt : { *(.rela.plt) } : relro

    . = ALIGN(CONSTANT(MAXPAGESIZE));
    .dynamic : {
        *(.dynamic)
    } : data : dynamic
    .data : { *(.data .data.*) } : data
    .bss : {
        *(.bss .bss.*)
        *(COMMON)
    } : data
}
