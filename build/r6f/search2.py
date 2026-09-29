import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
exec(open('build/r6f/search1.py').read().split('CASES =')[0].split("obs = ")[1].replace("pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go","",1) if False else '')
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
import importlib.util
spec=importlib.util.spec_from_file_location('s1','build/r6f/search1.py')
src=open('build/r6f/search1.py').read().split('CASES =')[0]
ns={}; exec(src, ns)
predict=ns['predict']
for name in ['I1_24','I2_24','I3_24','I4_24','I5_24','I6_24','I7_24']:
    row=[]
    for f in range(2, 11):
        for m in ('floor','tz','up'):
            got,pix=predict(name,f,m,'left','exact')
            row.append((sum(1 for a,p in zip(got,pix) if a!=obs[name][p]), f, m))
    row.sort(); print(name, row[:4])
