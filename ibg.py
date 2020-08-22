import numpy as np
import matplotlib.pyplot as plt
import sys

# Seems a variant of PackBits
f = sys.argv[1]

fb = open(f,"rb").read()

w = fb[18]+fb[19]*256
h = fb[22]+fb[23]*256

print(f"{f}: format {w} x {h}")

psize = 256
palette = np.zeros((psize,4), dtype=np.uint8)

pstart = 0x36

for i in range(psize):
    palette[i,2] = fb[pstart+i*4]
    palette[i,1] = fb[pstart+i*4+1]
    palette[i,0] = fb[pstart+i*4+2]
    palette[i,3] = fb[pstart+i*4+3]

istart = pstart + psize*4 

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
else:
    print(f"Done")


oa = np.array(o, dtype=np.uint8)
oa = np.reshape(oa, (h,w))
oa = np.flipud(oa)

im= palette[oa][:,:,0:3]

plt.imsave(f.replace(".ibg",".png"),im)
