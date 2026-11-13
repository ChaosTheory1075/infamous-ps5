import sys
p = sys.argv[1]
s = open(p).read()
bs = "\\"
# in the patch script: C "\n" inside these lines must be written \n in the Python source
pairs = [
    ('register(t0);' + bs + 'n' + bs + '";' + bs + 'n"', 'register(t0);' + bs + bs + 'n' + bs + '";' + bs + 'n"'),
    ('register(t%u);' + bs + 'n' + bs + '", u, u);' + bs + 'n"', 'register(t%u);' + bs + bs + 'n' + bs + '", u, u);' + bs + 'n"'),
    ('translation failed: %s' + bs + 'n' + bs + '",' + bs + 'n"', 'translation failed: %s' + bs + bs + 'n' + bs + '",' + bs + 'n"'),
]
for a, b in pairs:
    s = s.replace(a, b)
open(p, 'w').write(s)
