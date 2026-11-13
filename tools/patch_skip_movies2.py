
# skip movies case: lower-case the name by hand (no strcasestr/strncasecmp: no new PS5 imports)
edit("runtime/ppu/ppu_fs.cpp",
     '''          const char* b = strrchr(gpath, '/'); b = b ? b + 1 : gpath;
          const size_t n = strlen(b);
          if (n > 4 && !strcasecmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncasecmp(b, "splash", 6) || strcasestr(b, "logo") != NULL;''',
     '''          const char* b0 = strrchr(gpath, '/'); b0 = b0 ? b0 + 1 : gpath;
          char b[256]; size_t n = 0;
          for (; b0[n] && n < sizeof b - 1; n++) b[n] = (b0[n] >= 'A' && b0[n] <= 'Z') ? (char)(b0[n] + 32) : b0[n];
          b[n] = 0;
          if (n > 4 && !strcmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncmp(b, "splash", 6) || strstr(b, "logo") != NULL;''',
     "skip movies case")
