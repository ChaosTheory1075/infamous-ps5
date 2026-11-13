/* tooling/psbc/ps5-pie-unwind.ld with ps5-pie-tls.ld (a PT_TLS) as the base layout. */
INCLUDE ps5-pie-tls.ld

PROVIDE(__eh_frame_start = ADDR(.eh_frame));
PROVIDE(__eh_frame_end = ADDR(.eh_frame) + SIZEOF(.eh_frame));
PROVIDE(__eh_frame_hdr_start = ADDR(.eh_frame_hdr));
PROVIDE(__eh_frame_hdr_end = ADDR(.eh_frame_hdr) + SIZEOF(.eh_frame_hdr));
