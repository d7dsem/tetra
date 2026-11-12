"""Канальне декодування TCH (дані) для DMO: .tch від dmo_rx (type-4, 432 біти/кадр) -> інформаційні біти.
Типи: 2.4 (144 біти/кадр), 4.8 (288), 7.2 (432, без кодування); перемежування N = 1, 4, 8 (для 7.2 лише 1).
Вихід: файл бітів, 1 біт = 1 байт (0/1). Режим --scan пробує всі варіанти й друкує таблицю індикаторів.
Ref: ETSI EN 300 392-2 8.2.3.1 (RCPC), 8.2.4.1-8.2.4.2 (перемежування), 8.3.1.3.2-8.3.1.3.4 (TCH/4.8, 2.4, 7.2)."""
import argparse, os, sys
import numpy as np

P23=[0,1,2,5]; P13=[0,1,2,3,5,6,7]
# тип -> (інфо-біти, кроків Вітербі, P, t, період, ділник i_func)
TYPES={"2.4":(144,148,P13,6,35),"4.8":(288,292,P23,3,65)}

def mother_index(typ):
    info,steps,P,t,div=TYPES[typ]
    idx=[]
    for j in range(1,433):
        i=j+(j-1)//div
        idx.append(8*((i-1)//t)+P[i-t*((i-1)//t)]-1)
    return np.array(idx)

def block_deint(x,a=103,K=432):
    return x[(1+(a*np.arange(1,K+1))%K)-1]

def unwrap_n(t4,N):
    """N послідовних type-4 блоків -> type-3 блоки (8.2.4.2). Видає len(t4)-N+1 блоків."""
    bp=np.array([block_deint(f) for f in t4])
    if N==1: return bp
    q=432//N; i=np.arange(q)
    out=np.zeros((len(bp)-N+1,432),np.uint8)
    for n in range(len(out)):
        for j in range(N):
            out[n,j+i*N]=bp[n+j,j*q+i]
    return out

# Вітербі: стан = (d0,d1,d2,d3) як біти s; наступний = b | (s&7)<<1; попередники ns: (ns>>1)|d3<<3
def _outputs():
    o=np.zeros((16,2,4),np.uint8)
    for s in range(16):
        d0,d1,d2,d3=(s>>0)&1,(s>>1)&1,(s>>2)&1,(s>>3)&1
        for b in (0,1):
            o[s,b]=((b+d0+d3)&1,(b+d1+d2+d3)&1,(b+d0+d1+d3)&1,(b+d0+d2+d3)&1)
    return o
OUT=_outputs()
PRED=np.array([[(ns>>1)|(d3<<3) for d3 in (0,1)] for ns in range(16)])
PB=np.arange(16)&1

def viterbi(rx,known,steps):
    INF=10**6; pm=np.full(16,INF); pm[0]=0; back=np.zeros((steps,16),np.int8)
    for t in range(steps):
        r=rx[4*t:4*t+4]; k=known[4*t:4*t+4]
        bm=((OUT!=r)&k).sum(2)            # [s,b]
        cand=np.stack([pm[PRED[:,d]]+bm[PRED[:,d],PB] for d in (0,1)],1)
        back[t]=cand.argmin(1); pm=cand.min(1)
    s=0; bits=np.zeros(steps,np.uint8)
    for t in range(steps-1,-1,-1):
        d=back[t,s]; bits[t]=s&1; s=PRED[s,d]
    return bits,int(pm[0])

def decode_t3(t3,typ):
    info,steps,*_=TYPES[typ]
    rx=np.zeros(4*steps,np.uint8); known=np.zeros(4*steps,bool)
    idx=mother_index(typ); rx[idx]=t3; known[idx]=True
    bits,m=viterbi(rx,known,steps)
    return bits[:info],m

def decode(t4,typ,N):
    """Список (інфо-біти, метрика) по type-3 блоках. Для 7.2 метрики немає (None)."""
    if typ=="7.2": return [(f,None) for f in t4]
    return [decode_t3(b,typ) for b in unwrap_n(t4,N)]

def read_tch(path):
    r=np.fromfile(path,dtype='<i2').reshape(-1,690)
    return (r[:,np.r_[1:115,116:230,231:345,346:436]]<0).astype(np.uint8)

def scan(t4):
    """Метрика лише по ненульових type-3 блоках: нульовий блок є кодовим словом будь-якого варіанту."""
    rng=np.random.default_rng(1)
    ctrl=rng.integers(0,2,t4.shape,dtype=np.uint8)
    print("%-4s %-2s %9s %10s %8s | контроль (випадкові біти): ненульових, середня"%("тип","N","ненульових","метрика=0","середня"))
    for typ in ("2.4","4.8"):
        for N in (1,4,8):
            row=[]
            for src in (t4,ctrl):
                b3=unwrap_n(src,N); b3=b3[b3.any(1)]
                m=np.array([decode_t3(x,typ)[1] for x in b3]); row.append(m)
            m,c=row
            print("%-4s %-2d %9d %9.1f%% %8.2f | %9d %8.2f"%(typ,N,len(m),100*(m==0).mean(),m.mean(),len(c),c.mean()))
    print("7.2  1  без кодування: індикатора помилок немає, перевіряйте структуру даних вручну")

def main():
    ap=argparse.ArgumentParser(description="TCH (дані): .tch -> інфо-біти (1 біт = 1 байт)")
    ap.add_argument("infile",help=".tch з dmo_rx")
    ap.add_argument("--type",choices=["2.4","4.8","7.2"],default="2.4")
    ap.add_argument("-n","--interleave",type=int,choices=[1,4,8],default=1,help="глибина перемежування N")
    ap.add_argument("--scan",action="store_true",help="спробувати всі варіанти, надрукувати таблицю, нічого не писати")
    ap.add_argument("-o","--out",help="вихід (за замовчуванням <вхід>.tch<тип>_n<N>.bits)")
    a=ap.parse_args()
    t4=read_tch(a.infile)
    if a.scan: scan(t4); return 0
    if a.type=="7.2" and a.interleave!=1: sys.exit("для TCH/7.2 N=1 (перемежування немає)")
    res=decode(t4,a.type,a.interleave)
    out=a.out or "%s.tch%s_n%d.bits"%(os.path.splitext(a.infile)[0],a.type.replace(".",""),a.interleave)
    np.concatenate([x[0] for x in res]).astype(np.uint8).tofile(out)
    ms=[x[1] for x in res if x[1] is not None]
    print("TCH/%s N=%d: блоків %d%s -> %s"%(a.type,a.interleave,len(res),
          ", метрика=0: %d, макс. %d"%(sum(m==0 for m in ms),max(ms)) if ms else "",out))
    return 0

if __name__=="__main__":
    sys.exit(main())
