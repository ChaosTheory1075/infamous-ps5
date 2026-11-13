/* udelta_enc.c - encoder for the USA->Europe patch format (UDP1). See udelta_dec.c for the format.
   usage: udelta_enc <src_root> <dst_root> <list> <out.patch>
   list lines: "name" = delta of dst_root/name against src_root/name; "+name" = whole file stored (DATA only);
               "name<TAB>srcname" = delta against src_root/srcname.
   Matching: index of a 32-byte rolling hash at every STEP-th source position; every target position is
   looked up; candidates are verified, extended forward and backward. COPY emitted when >= MINCOPY bytes. */
#define _FILE_OFFSET_BITS 64
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

#define W 32

static const uint32_t K256[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
#define RR(x,n) (((x)>>(n))|((x)<<(32-(n))))
static void sha_blk(uint32_t*H,const uint8_t*p){ uint32_t w[64],a,b,c,d,e,f,g,h; for(int i=0;i<16;i++) w[i]=(uint32_t)p[4*i]<<24|p[4*i+1]<<16|p[4*i+2]<<8|p[4*i+3];
  for(int i=16;i<64;i++){ uint32_t s0=RR(w[i-15],7)^RR(w[i-15],18)^(w[i-15]>>3), s1=RR(w[i-2],17)^RR(w[i-2],19)^(w[i-2]>>10); w[i]=w[i-16]+s0+w[i-7]+s1; }
  a=H[0];b=H[1];c=H[2];d=H[3];e=H[4];f=H[5];g=H[6];h=H[7];
  for(int i=0;i<64;i++){ uint32_t t1=h+(RR(e,6)^RR(e,11)^RR(e,25))+((e&f)^(~e&g))+K256[i]+w[i], t2=(RR(a,2)^RR(a,13)^RR(a,22))+((a&b)^(a&c)^(b&c)); h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2; }
  H[0]+=a;H[1]+=b;H[2]+=c;H[3]+=d;H[4]+=e;H[5]+=f;H[6]+=g;H[7]+=h; }
static void SHA256(const uint8_t*p,uint64_t n,uint8_t*o){ uint32_t H[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  uint64_t i=0; for(;i+64<=n;i+=64) sha_blk(H,p+i); uint8_t t[128]={0}; uint64_t r=n-i; memcpy(t,p+i,r); t[r]=0x80; int L=r<56?64:128;
  uint64_t bits=n*8; for(int k=0;k<8;k++) t[L-1-k]=(uint8_t)(bits>>(8*k)); sha_blk(H,t); if(L==128) sha_blk(H,t+64);
  for(int k=0;k<8;k++){ o[4*k]=H[k]>>24;o[4*k+1]=H[k]>>16;o[4*k+2]=H[k]>>8;o[4*k+3]=H[k]; } }
static int STEP = 16, MINCOPY = 24;
static const uint64_t P = 0x100000001B3ULL;
static FILE *out;
static uint64_t tot_lit, tot_copy, tot_ops;

static uint32_t crc_tab[256];
static void crc_init(void){ for(uint32_t i=0;i<256;i++){uint32_t c=i;for(int k=0;k<8;k++)c=c&1?0xEDB88320u^(c>>1):c>>1;crc_tab[i]=c;} }
static uint32_t crc32u(uint32_t c,const uint8_t*p,size_t n){ c=~c; while(n--) c=crc_tab[(c^*p++)&255]^(c>>8); return ~c; }

static void put(uint64_t v,int n){ uint8_t b[8]; for(int i=0;i<n;i++) b[i]=(uint8_t)(v>>(8*(n-1-i))); fwrite(b,1,n,out); }
static void emit_data(const uint8_t*p,uint64_t n){ while(n){ uint32_t k=n>0x7fffffff?0x7fffffff:(uint32_t)n; fputc('D',out); put(k,4); fwrite(p,1,k,out); p+=k; n-=k; tot_lit+=k; tot_ops++; } }
static void emit_copy(uint64_t off,uint64_t n){ while(n){ uint32_t k=n>0x7fffffff?0x7fffffff:(uint32_t)n; fputc('C',out); put(off,8); put(k,4); off+=k; n-=k; tot_copy+=k; tot_ops++; } }

static const uint8_t *map(const char*fn,uint64_t*sz){ int fd=open(fn,O_RDONLY); if(fd<0){perror(fn);exit(1);} struct stat st; fstat(fd,&st); *sz=st.st_size;
  if(!*sz){close(fd);return (const uint8_t*)"";} void*m=mmap(0,*sz,PROT_READ,MAP_PRIVATE,fd,0); close(fd); if(m==MAP_FAILED){perror("mmap");exit(1);} madvise(m,*sz,MADV_SEQUENTIAL); return m; }

static void delta(const uint8_t*s,uint64_t sn,const uint8_t*d,uint64_t dn){
  if(dn<W||sn<W){ emit_data(d,dn); return; }
  uint64_t nb=(sn-W)/STEP+1, tsz=1; while(tsz<nb*2) tsz<<=1; uint64_t mask=tsz-1;
  uint32_t *tab=calloc(tsz,4); if(!tab){fprintf(stderr,"oom\n");exit(1);}
  uint64_t PW=1; for(int i=0;i<W-1;i++) PW*=P;
  for(uint64_t b=nb;b-->0;){ uint64_t h=0; const uint8_t*q=s+b*STEP; for(int i=0;i<W;i++) h=h*P+q[i]; tab[(h>>20)&mask]=(uint32_t)(b+1); }
  uint64_t i=0,lit=0,h=0; int hv=0;
  while(i+W<=dn){
    if(!hv){ h=0; for(int k=0;k<W;k++) h=h*P+d[i+k]; hv=1; }
    uint32_t e=tab[(h>>20)&mask];
    if(e){ uint64_t so=(uint64_t)(e-1)*STEP;
      if(!memcmp(s+so,d+i,W)){
        uint64_t f=W; while(i+f<dn && so+f<sn && s[so+f]==d[i+f]) f++;
        uint64_t bk=0; while(i-bk>lit && so-bk>0 && s[so-bk-1]==d[i-bk-1]) bk++;
        if(f+bk>=(uint64_t)MINCOPY){ emit_data(d+lit,i-bk-lit); emit_copy(so-bk,f+bk); i+=f; lit=i; hv=0; continue; } } }
    if(i+W<dn) h=(h-d[i]*PW)*P+d[i+W];
    i++; }
  emit_data(d+lit,dn-lit); free(tab);
}

int main(int argc,char**argv){
  if(argc<5){fprintf(stderr,"usage: %s src_root dst_root list out.patch [step mincopy]\n",argv[0]);return 1;}
  if(argc>5) STEP=atoi(argv[5]); if(argc>6) MINCOPY=atoi(argv[6]);
  crc_init(); out=fopen(argv[4],"wb"); if(!out){perror(argv[4]);return 1;}
  FILE*l=fopen(argv[3],"r"); char line[4096]; int nf=0;
  fwrite("UDP1",1,4,out);
  while(fgets(line,sizeof line,l)){
    line[strcspn(line,"\r\n")]=0; if(!*line) continue;
    int whole=line[0]=='+'; char*name=line+whole; char*src=strchr(name,'\t'); if(src) *src++=0; else src=name;
    char fs[8192],fd[8192]; snprintf(fs,sizeof fs,"%s/%s",argv[1],src); snprintf(fd,sizeof fd,"%s/%s",argv[2],name);
    uint64_t sn=0,dn; const uint8_t*s=whole?NULL:map(fs,&sn); const uint8_t*d=map(fd,&dn);
    uint8_t sha[32]; SHA256(d,dn,sha);
    uint64_t l0=tot_lit,c0=tot_copy,o0=tot_ops;
    fputc('F',out); put(strlen(name),2); fwrite(name,1,strlen(name),out); put(whole?0:strlen(src),2); if(!whole) fwrite(src,1,strlen(src),out);
    put(dn,8); put(crc32u(0,d,dn),4); fwrite(sha,1,32,out);
    if(whole) emit_data(d,dn); else delta(s,sn,d,dn);
    fputc('E',out);
    fprintf(stderr,"%s\t%llu\tlit %llu\tcopy %llu\tops %llu\n",name,(unsigned long long)dn,(unsigned long long)(tot_lit-l0),(unsigned long long)(tot_copy-c0),(unsigned long long)(tot_ops-o0));
    if(s&&sn) munmap((void*)s,sn); if(dn) munmap((void*)d,dn); nf++; }
  fputc('Z',out); long sz=ftell(out); fclose(out);
  fprintf(stderr,"TOTAL files %d literal %llu copy %llu ops %llu patch %ld bytes\n",nf,(unsigned long long)tot_lit,(unsigned long long)tot_copy,(unsigned long long)tot_ops,sz);
  return 0; }
