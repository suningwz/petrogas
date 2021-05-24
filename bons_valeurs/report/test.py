a = [1, 2, 3, 4]
res = []
saut = 2
for i, v in zip(a, range(0, len(a), saut)):
    print(i, ' = ', v)
    res = [a[i:i+saut] for i range(0, len(a), saut)]