# Most Memory-Efficient Fibonacci Generator in Python

## Memory Complexity: O(1) space - only stores last 2 numbers
## Time Complexity: O(n) time

---

## Method 1: Generator (MOST MEMORY EFFICIENT - O(1) space)

```python
def fibonacci_generator(n):
    """
    Generate first n Fibonacci numbers using a generator.
    
    Args:
        n: Number of Fibonacci numbers to generate
        
    Yields:
        Fibonacci numbers one at a time (lazy evaluation)
    """
    if n <= 0:
        return
    
    a, b = 0, 1
    for _ in range(n):
        yield a
        a, b = b, a + b


# Usage - generates and prints first 20 Fibonacci numbers
n = 20
print(f"First {n} Fibonacci Numbers:")
for num in fibonacci_generator(n):
    print(num, end=' ')
```

**Why it's the most memory efficient:**
- Uses lazy evaluation (generator)
- Only stores 2 variables at any time (`a` and `b`)
- Produces one number at a time as requested
- Memory usage: ~200 bytes regardless of n size

---

## Method 2: List Comprehension (O(n) space)

```python
def fibonacci_list(n):
    """
    Generate first n Fibonacci numbers as a list.
    
    Args:
        n: Number of Fibonacci numbers to generate
        
    Returns:
        List of Fibonacci numbers
    """
    if n <= 0:
        return []
    
    result = [0, 1]
    for i in range(2, n):
        result.append(result[-1] + result[-2])
    return result[:n]


# Usage - generates first 20 Fibonacci numbers as a list
n = 20
result = fibonacci_list(n)
print(f"\nFirst {n} Fibonacci Numbers (list):")
for num in result:
    print(num, end=' ')
```

**Memory usage:** O(n) space - stores all n numbers simultaneously

---

## Performance Comparison

| Method | Space Complexity | Memory Usage (n=20) | Best For |
|--------|-----------------|---------------------|----------|
| Generator | O(1) | ~200 bytes | Streaming, large n |
| List Comp | O(n) | ~2000+ bytes | Random access, small n |

---

## Key Takeaways

1. **Generator is the most memory-efficient** - produces numbers on-demand
2. **Use generator when:** you need to process Fibonacci numbers one at a time or have very large n values
3. **Use list when:** you need random access to previously generated numbers
4. **Avoid recursion** - causes stack overflow for large n and is inefficient
