def stirling_number(n, k):
    """Compute S(n, k) using iterative DP with O(k) space."""
    if k < 0 or k > n:
        return 0
    
    dp = [0] * (k + 1)
    dp[0] = 1
    
    for i in range(1, n + 1):
        for j in range(min(i, k), 0, -1):
            dp[j] = dp[j] + dp[j-1]
    
    return dp[k]

result = stirling_number(30, 20)
print(f"S(30, 20) = {result}")