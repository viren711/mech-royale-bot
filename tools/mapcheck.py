"""Dev check: build the map model, print an ASCII overview and time some paths. Usage: mapcheck.py <arena dir>"""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from world import World, Search
t=time.time(); w=World(sys.argv[1], ["v2/world.json","v2/terrain.i16"]); print("build s", round(time.time()-t,2))
print("coarse", w.cnx, w.cny, "blocked frac", round(sum(w.cb)/len(w.cb),3))
for cj in range(w.cny-1,-1,-3):
    print("".join("#" if w.cb[cj*w.cnx+ci] else "." for ci in range(0,w.cnx,2)))
import random
r=random.Random(1); worst=0
for k in range(30):
    a=w.nearest_free(r.uniform(-450,500), r.uniform(-300,350)); b=w.nearest_free(r.uniform(-450,500), r.uniform(-300,350))
    s=Search(w,a,b); t=time.time(); steps=0; mx=0
    while not s.done:
        t1=time.time(); s.step(600); mx=max(mx,time.time()-t1); steps+=1
    worst=max(worst,mx)
    print(k, "path" if s.path else "NONE", len(s.path or []), "slices", steps, "max slice ms", round(mx*1000,1), "total ms", round((time.time()-t)*1000))
print("worst slice ms", round(worst*1000,1))
