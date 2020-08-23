import numpy as np
import sys


def read_ibg(f):
    fb = open(f,"rb").read()

    if fb[0:2] != b"IB":
        raise Exception("Does not start with IB header")
    
    w = fb[18]+fb[19]*256
    h = fb[22]+fb[23]*256

    psize = 256                 # ?
    palette = np.zeros((psize,4), dtype=np.uint8)

    pstart = 0x36

    for i in range(psize):
        palette[i,2] = fb[pstart+i*4]
        palette[i,1] = fb[pstart+i*4+1]
        palette[i,0] = fb[pstart+i*4+2]
        palette[i,3] = fb[pstart+i*4+3]

    istart = pstart + psize*4 

    # Seems a variant of PackBits
    o=[]
    ptr = istart
    while True:
        c = fb[ptr]
        ptr = ptr+1
        if c==0:
            break
        elif c<128:
            # print(f"Emit sequence of {c}")
            for _ in range(c):
                c = fb[ptr]
                ptr = ptr+1
                o.append(c)
        else:
            rep = c-128
            # print(f"Emit RLE of {rep}")
            c = fb[ptr]
            ptr = ptr+1
            for _ in range(rep):
                o.append(c)

    if len(o) != w*h:
        raise Exception(f"{f}: output {len(o)}, expected {w*h}")

    oa = np.array(o, dtype=np.uint8)
    oa = np.reshape(oa, (h,w))
    oa = np.flipud(oa)

    return oa, palette


if __name__ == "__main__":
    import png
    f = sys.argv[1]

    try:
        oa, palette = read_ibg(f)
        h, w = oa.shape
        print(f"{f}: format {w} x {h}")
        with open(f.replace(".ibg",".png"), "wb") as g:
            pw = png.Writer(width=w, height=h, palette=palette[:,0:3])
            pw.write(g, oa)

    except Exception as e:
        print(f"{f}: failed: {e}")

