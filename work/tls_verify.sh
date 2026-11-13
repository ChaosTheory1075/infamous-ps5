if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Compare each eboot's PT_TLS initial image with the ELF's .tdata (they must be equal).
for g in if1 if2 fob; do E=$HOME/if2/ps5/build-$g/Infamous2Recomp
set -- $(readelf -SW $E | sed 's/^ *\[ *[0-9]*\] *//' | awk '$1==".tdata"{print $4, $5}')
a=$(xxd -p -s 0x$1 -l 0x$2 $E | tr -d '\n')
b=$(readelf -lW $E.eboot.elf | awk '$1=="TLS"{print $2, $5}' | while read o s; do xxd -p -s $o -l $s $E.eboot.elf; done | tr -d '\n')
echo "$g: elf tdata $a"; echo "$g: eboot tls  $b"; [ "$a" = "$b" ] && echo "$g: TLS OK" || echo "$g: TLS MISMATCH"; done
# The PT_TLS must lie inside a loaded segment of the eboot, or the console refuses to start it.
for g in if1 if2 fob; do readelf -lW $HOME/if2/ps5/build-$g/Infamous2Recomp.eboot.elf | awk -v g=$g '
  function strtonum(h,  i,c,v){v=0; h=tolower(h); sub(/^0x/,"",h); for(i=1;i<=length(h);i++){c=index("0123456789abcdef",substr(h,i,1))-1; v=v*16+c}; return v}   # mawk has no strtonum
  $1=="LOAD"{n++; lo[n]=strtonum($3); hi[n]=strtonum($3)+strtonum($6)}
  $1=="TLS"{t=strtonum($3); te=t+strtonum($5)}
  END{ok=0; for(i=1;i<=n;i++) if(t>=lo[i] && te<=hi[i]) ok=1; print g ": TLS " (ok?"inside a LOAD segment":"OUTSIDE every LOAD segment")}'; done
