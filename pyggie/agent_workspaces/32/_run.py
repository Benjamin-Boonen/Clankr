import sys

def fibonacci_generator(n):
    """Generate first n Fibonacci numbers using a generator."""
    if n <= 0:
        return
    
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b


def fibonacci_list(n):
    """Generate first n Fibonacci numbers as a list."""
    if n <= 0:
        return []
    
    result = [0, 1]
    for i in range(2, n):
        result.append(result[-1] + result[-2])
    return result[:n]


# Test with n=20
n = 20

print(f"First {n} Fibonacci Numbers:")

# Method 1: Generator (most memory efficient - O(1) space)
print("\nUsing Generator (O(1) space):")
gen = fibonacci_generator(n)
result_gen = [next(gen) for _ in range(n)]
print(result_gen)

# Method 2: List comprehension (O(n) space)
print("\nUsing List Comprehension (O(n) space):")
result_list = fibonacci_list(n)
print(result_list)

# Memory comparison
gen_mem = sys.getsizeof(gen)
list_mem = sys.getsizeof(result_list)

print(f"\nGenerator memory: {gen_mem} bytes")
print(f"List memory: {list_mem} bytes")
print(f"Savings: {(1 - gen_mem/list_mem)*100:.1f}%")