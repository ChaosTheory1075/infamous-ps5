# spv memcache: the SPIR-V disk cache read into memory by a loader thread, misses written by a writer thread
SPV = "libs/video/rsx_shader_spirv.cpp"
edit(SPV,
     '''#include <vector>
#include <unistd.h>
#include <chrono>''',
     '''#include <vector>
#include <unistd.h>
#include <chrono>
#include <pthread.h>
#include <dirent.h>
#include <unordered_map>
#include <deque>
#include <string>''',
     "spv memcache: includes")
edit(SPV,
     '''extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{''',
     '''/* The disk cache in memory. On the console a cache lookup was an fopen/fread on the RSX thread, and
 * the file system there stalls for up to a second at times: inFAMOUS 2's single "slow pipeline miss"
 * stalls of 0.8-1 s were spent in the backend around a SPIR-V compile that took 5-8 ms. A loader thread
 * reads every <key>.spv once at start; until it is done a lookup still goes to disk. New entries are
 * written by a writer thread. */
namespace {
pthread_mutex_t s_spv_mu = PTHREAD_MUTEX_INITIALIZER;
pthread_cond_t  s_spv_cv = PTHREAD_COND_INITIALIZER;
std::unordered_map<unsigned long long, std::vector<u32>>* s_spv_mem;
std::deque<std::pair<std::string, std::vector<u32>>>* s_spv_wq;
volatile int s_spv_loaded;                 /* 1: every file on disk is in s_spv_mem */
char s_spv_dir[1024];

void* spv_loader(void*)
{
    const auto t0 = std::chrono::steady_clock::now();
    unsigned n = 0; size_t bytes = 0;
    if (DIR* d = opendir(s_spv_dir)) {
        std::vector<u32> buf(1u << 20);
        while (struct dirent* de = readdir(d)) {
            const char* nm = de->d_name;
            const size_t L = strlen(nm);
            if (L != 20 || strcmp(nm + 16, ".spv") != 0) continue;
            char path[1100];
            snprintf(path, sizeof path, "%s/%s", s_spv_dir, nm);
            FILE* f = fopen(path, "rb");
            if (!f) continue;
            const size_t w = fread(buf.data(), sizeof(u32), buf.size(), f);
            fclose(f);
            if (w <= 5 || buf[0] != 0x07230203u) continue;
            const unsigned long long key = strtoull(std::string(nm, 16).c_str(), nullptr, 16);
            pthread_mutex_lock(&s_spv_mu);
            (*s_spv_mem)[key].assign(buf.begin(), buf.begin() + w);
            pthread_mutex_unlock(&s_spv_mu);
            n++; bytes += w * 4u;
        }
        closedir(d);
    }
    s_spv_loaded = 1;
    fprintf(stderr, "[spv] cache: %u shaders (%zu KB) in memory in %.0f ms\\n", n, bytes >> 10,
            std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    for (;;) {                             /* then the writer */
        pthread_mutex_lock(&s_spv_mu);
        while (s_spv_wq->empty()) pthread_cond_wait(&s_spv_cv, &s_spv_mu);
        auto job = std::move(s_spv_wq->front());
        s_spv_wq->pop_front();
        pthread_mutex_unlock(&s_spv_mu);
        char tmp[1200];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", job.first.c_str(), (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(job.second.data(), sizeof(u32), job.second.size(), f) == job.second.size();
            fclose(f);
            if (!ok || rename(tmp, job.first.c_str()) != 0) remove(tmp);
        }
    }
    return nullptr;
}

/* 1: the memory cache is in use (started on the first lookup). */
int spv_mem_start(const char* dir)
{
    static int on = -1;
    if (on >= 0) return on;
    const char* e = getenv("PS3RECOMP_SPIRV_MEMCACHE");
    on = 0;
    if (e && e[0] == '0') return 0;
    snprintf(s_spv_dir, sizeof s_spv_dir, "%s", dir);
    s_spv_mem = new std::unordered_map<unsigned long long, std::vector<u32>>();
    s_spv_wq = new std::deque<std::pair<std::string, std::vector<u32>>>();
    pthread_t t;
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setstacksize(&a, 256u << 10);
    if (pthread_create(&t, &a, spv_loader, nullptr) == 0) { pthread_detach(t); on = 1; }
    pthread_attr_destroy(&a);
    return on;
}
} // namespace

extern "C" int rsx_hlsl_to_spirv(const char* hlsl, int stage,
                                 u32* words, u32 max_words, u32* out_words,
                                 char* log, u32 log_size)
{''',
     "spv memcache: loader")
edit(SPV,
     '''    snprintf(path, sizeof path, "%s/%016llx.spv", dir, spv_cache_key(hlsl, stage, rcp));
    if (FILE* f = fopen(path, "rb")) {
        const size_t n = fread(words, sizeof(u32), max_words, f);
        fclose(f);
        if (n > 5 && words[0] == 0x07230203u) { *out_words = (u32)n; return 0; }
    }''',
     '''    const unsigned long long key = spv_cache_key(hlsl, stage, rcp);
    snprintf(path, sizeof path, "%s/%016llx.spv", dir, key);
    const int mem = spv_mem_start(dir);
    int on_disk_too = 1;
    if (mem) {
        pthread_mutex_lock(&s_spv_mu);
        auto it = s_spv_mem->find(key);
        const bool hit = it != s_spv_mem->end() && it->second.size() <= max_words;
        if (hit) { memcpy(words, it->second.data(), it->second.size() * sizeof(u32)); *out_words = (u32)it->second.size(); }
        pthread_mutex_unlock(&s_spv_mu);
        if (hit) return 0;
        on_disk_too = !s_spv_loaded;       /* still loading: it may be on disk */
    }
    if (on_disk_too) {
        const auto r0 = std::chrono::steady_clock::now();
        size_t n = 0;
        if (FILE* f = fopen(path, "rb")) {
            n = fread(words, sizeof(u32), max_words, f);
            fclose(f);
        }
        const double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r0).count();
        static int said;
        if (ms > 20.0 && said < 100) { said++; fprintf(stderr, "[spv] slow cache read %.0f ms\\n", ms); }
        if (n > 5 && words[0] == 0x07230203u) { *out_words = (u32)n; return 0; }
    }''',
     "spv memcache: lookup")
edit(SPV,
     '''    if (rc == 0 && *out_words) {
        char tmp[1100];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(words, sizeof(u32), *out_words, f) == *out_words;
            fclose(f);
            if (!ok || rename(tmp, path) != 0) remove(tmp);
        }
    }
    return rc;''',
     '''    if (rc == 0 && *out_words && mem) {
        pthread_mutex_lock(&s_spv_mu);
        (*s_spv_mem)[key].assign(words, words + *out_words);
        s_spv_wq->emplace_back(std::string(path), std::vector<u32>(words, words + *out_words));
        pthread_cond_signal(&s_spv_cv);
        pthread_mutex_unlock(&s_spv_mu);
    } else if (rc == 0 && *out_words) {
        char tmp[1100];
        snprintf(tmp, sizeof tmp, "%s.%d.tmp", path, (int)getpid());
        if (FILE* f = fopen(tmp, "wb")) {
            const bool ok = fwrite(words, sizeof(u32), *out_words, f) == *out_words;
            fclose(f);
            if (!ok || rename(tmp, path) != 0) remove(tmp);
        }
    }
    return rc;''',
     "spv memcache: write")

# guest file reads over 5 ms: how much is pre-faulting the buffer and how much is fread
edit("runtime/ppu/ppu_fs.cpp",
     '''    fs_prefault(buf, nbytes);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */''',
     '''    const uint64_t sr0 = ps3_ft_now();
    fs_prefault(buf, nbytes);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const uint64_t sr1 = ps3_ft_now();
    size_t n = fread(vm_base + buf, 1, (size_t)nbytes, g_files[fd]);   /* raw bytes, no swap */
    {   const uint64_t sr2 = ps3_ft_now();
        static unsigned said;
        if (sr2 - sr0 > 5000000ull && said < 300) { said++;
            fprintf(stderr, "[fs] slow cellFsRead fd %d %zu bytes at %ld: prefault %.1f ms, fread %.1f ms\\n",
                    fd, n, fpos_before, (sr1 - sr0) / 1e6, (sr2 - sr1) / 1e6); } }''',
     "fs slow: cellFsRead")
edit("runtime/syscalls/sys_fs.c",
     '''    if (size) vm_commit(buf_addr, (uint32_t)size);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    size_t nread = fread(buf, 1, (size_t)size, f->fp);''',
     '''    const uint64_t sr0 = ps3_ft_now();
    if (size) vm_commit(buf_addr, (uint32_t)size);
    const uint64_t ft_r0 = PS3_FT_ON() ? ps3_ft_now() : 0;
    const uint64_t sr1 = ps3_ft_now();
    size_t nread = fread(buf, 1, (size_t)size, f->fp);
    {   const uint64_t sr2 = ps3_ft_now();
        static unsigned said;
        if (sr2 - sr0 > 5000000ull && said < 300) { said++;
            fprintf(stderr, "[fs] slow sys_fs_read fd %d %zu bytes at %ld: commit %.1f ms, fread %.1f ms\\n",
                    fd, nread, pos_before, (sr1 - sr0) / 1e6, (sr2 - sr1) / 1e6); } }''',
     "fs slow: sys_fs_read")
