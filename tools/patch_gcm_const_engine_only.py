
# gcm const engine only: with the draw engine on, constant data words skip the legacy rsx_process_method
# Every FIFO word went through two dispatchers: the draw engine (rsx_draw_engine_method ->
# rsx_dispatch_method) and the legacy state (rsx_process_method). The real PS3 frame
# (work/ps3_if2_20261103, frame.py) is mostly vertex-program constant uploads: 0x1EFC load slot then
# 0x1F00..0x1F7C data, ~4200 runs a frame. The legacy copy of those constants is read only by the
# vtable guest-draw path (rsx_vulkan_backend.c vk guest draw, D3D12), which is not used when the engine
# drives the backend. So with the engine on, a data word in 0x1F00..0x1F7C on subchannel 0 goes to the
# engine only. GCM_CONST_LEGACY=1: both, as before.
edit("libs/video/cellGcmSys.c",
     '''                    rsx_process_method(&s_state, m, dw);
                    /* NV406E_SET_REFERENCE: queue the fence value for PACED''',
     '''                    { static int legacy = -1;   /* gcm const engine only */
                      if (legacy < 0) { const char* e = getenv("GCM_CONST_LEGACY"); legacy = (e && *e == '1') || !rsx_draw_engine_enabled(); }
                      if (legacy || subch != 0 || m < 0x1F00u || m >= 0x1F80u)
                          rsx_process_method(&s_state, m, dw); }
                    /* NV406E_SET_REFERENCE: queue the fence value for PACED''',
     "gcm const engine only")
