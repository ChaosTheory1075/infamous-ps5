#!/usr/bin/env python3
# audgap.py <file.f32> [ch=2] [rate=48000]: cut-out finder for cellAudio float dumps. 5 ms RMS windows; reports
# exact-zero runs and dropouts (window < -45 dBFS while the 50 ms before and after are > -30 dBFS).
import sys, array, math
f=sys.argv[1]; ch=int(sys.argv[2]) if len(sys.argv)>2 else 2; rate=int(sys.argv[3]) if len(sys.argv)>3 else 48000
a=array.array('f'); a.frombytes(open(f,'rb').read()); n=len(a)//ch
W=rate*5//1000; nw=n//W; db=[]
for w in range(nw):
    s=a[w*W*ch:(w+1)*W*ch]; e=sum(x*x for x in s)/len(s)
    db.append(10*math.log10(e) if e>0 else -200.0)
print("%s: %.1f s, %d windows, median %.1f dBFS" % (f, n/rate, nw, sorted(db)[nw//2]))
zero=[w for w in range(nw) if db[w]<=-199]
runs=[]; 
for w in zero:
    if runs and w==runs[-1][1]+1: runs[-1][1]=w
    else: runs.append([w,w])
print("exact-zero runs:", len(runs), [(round(r[0]*0.005,2), (r[1]-r[0]+1)*5) for r in runs[:15]])
drops=[]
for w in range(10,nw-10):
    if db[w]<-45 and min(db[w-10:w-1])>-30 and min(db[w+2:w+11])>-30: drops.append(w)
print("dropouts (sound-gap-sound):", len(drops), [round(w*0.005,3) for w in drops[:30]])
