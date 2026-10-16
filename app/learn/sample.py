from typing import Optional

def func(b, a: Optional[int]=0):
    if a:
        return a + b
    return b

print(func(b = 2, a = 2))