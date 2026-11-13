
# vk readback view: engine readback of a VIEW handle reads its colour surface (diagnostic dumps)
# PS3RECOMP_ENG_OCCDUMP read texture units back with be->readback, which accepted only colour
# targets; a unit bound through surface_view (every depth->RGBA8 copy with a crossbar) returned
# nothing and the dump file held whatever malloc gave back -- the previous dump's bytes (2026-11-03,
# a "particle depth == particle colour" false lead). Views now read their surface; the dump buffer
# is zeroed first.
edit("libs/video/rsx_vulkan_backend.c",
     '''    (void)user;
    vk_eng_obj* o = vk_eng_get(surface, VK_ENG_COLOR);
    if (!o || !out || !out_pitch || !w || !h || x + w > o->w || y + h > o->h) return;''',
     '''    (void)user;
    if (vk_eng_get(surface, VK_ENG_VIEW)) surface = s_eobj[surface].surface;   /* vk readback view */
    vk_eng_obj* o = vk_eng_get(surface, VK_ENG_COLOR);
    if (!o || !out || !out_pitch || !w || !h || x + w > o->w || y + h > o->h) return;''',
     "vk readback view")
edit("libs/video/rsx_draw_engine.c",
     '''                  u8* tp = (u8*)malloc((size_t)t.width * t.height * 4);
                  if (!tp) continue;
                  g.be->readback(g.be->user, textures[u], 0, 0, t.width, t.height, tp, t.width * obpp);''',
     '''                  u8* tp = (u8*)calloc((size_t)t.width * t.height, 4);   /* vk readback view: zeroed */
                  if (!tp) continue;
                  g.be->readback(g.be->user, textures[u], 0, 0, t.width, t.height, tp, t.width * obpp);''',
     "vk readback view calloc")
