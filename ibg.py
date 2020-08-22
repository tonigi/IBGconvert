import numpy as np
import matplotlib.pyplot as plt
import sys

#f = "flagita1.ibg"
f = sys.argv[1]

fb = open(f,"rb").read()

w = fb[18]+fb[19]*256
h = fb[22]+fb[23]*256

print(f"Format {w} x {h}")

psize = 256
palette = np.zeros((psize,4), dtype=np.uint8)

pstart = 0x36

for i in range(psize):
    palette[i,2] = fb[pstart+i*4]
    palette[i,1] = fb[pstart+i*4+1]
    palette[i,0] = fb[pstart+i*4+2]
    palette[i,3] = fb[pstart+i*4+3]

istart = pstart + psize*4 

with open(f+".ppm","wb") as ppm:
    o=[]
    ptr = istart
    while True:
        c = fb[ptr]
        ptr = ptr+1
        if c==0:
            print(f"Done")
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
    raise Exception(f"Output {len(o)}, expected {w*h}")


oa = np.array(o, dtype=np.uint8)
oa = np.reshape(oa, (h,w))
oa = np.flipud(oa)

im = np.zeros((h,w,3), dtype=np.uint8)
for i in range(h):
    for j in range(w):
        im[i,j,:]=palette[oa[i,j],0:3]

plt.imsave(f.replace(".ibg",".png"),im)
