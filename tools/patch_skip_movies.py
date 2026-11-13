
# skip movies: PS3_SKIP_MOVIES=intro|all makes chosen Bink movies "missing", so the game goes on
# intro: the start-up splashes and logos (movies/cutscene/splash*.bik, *logo*.bik); all: every movie
# in movies/cutscene/ (the comic-book and story videos too). In-world screens (movies/tv/) always play.
# The launcher's SKIP INTRO / SKIP CUTSCENE MOVIES settings set it.
edit("runtime/ppu/ppu_fs.cpp",
     '''    /* fopen() mode strings can't express the PS3/POSIX open semantics (e.g.''',
     '''    { static int skip = -1;
      if (skip < 0) { const char* e = getenv("PS3_SKIP_MOVIES");
                      skip = !e ? 0 : !strcmp(e, "all") ? 2 : !strcmp(e, "intro") ? 1 : 0; }
      if (skip) {
          const char* b = strrchr(gpath, '/'); b = b ? b + 1 : gpath;
          const size_t n = strlen(b);
          if (n > 4 && !strcasecmp(b + n - 4, ".bik") && strstr(gpath, "/movies/cutscene/")) {
              const int intro = !strncasecmp(b, "splash", 6) || strcasestr(b, "logo") != NULL;
              if (skip == 2 || intro) {
                  fprintf(stderr, "[fs] skipped movie '%s' (PS3_SKIP_MOVIES=%s)\\n", gpath, skip == 2 ? "all" : "intro");
                  ctx->gpr[3] = (uint64_t)(int64_t)CELL_FS_ENOENT; return;
              }
          }
      } }
    /* fopen() mode strings can't express the PS3/POSIX open semantics (e.g.''',
     "skip movies open")
