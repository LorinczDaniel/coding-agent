# Why Output Gets Blocked When Writing Large Files

## Summary
When you write a **large amount of data** to a file and then try to **print/output** that data, the output becomes **blocked** because:

1. **I/O Buffer Limitations** - Terminal/stdout has limited buffering capacity
2. **Slow Output Stream** - Printing millions of lines is much slower than writing to disk
3. **System Buffer Saturation** - The output buffer fills up faster than it can flush

## What Happened in Our Test

### ✓ Writing (FAST)
```python
with open('test_large.txt', 'w') as f:
    for i in range(1000000):
        f.write(f"Line {i}: " + "x" * 100 + "\n")
# Result: Created 108.61 MB file in seconds
```
**Why it's fast**: Writing to disk/filesystem is highly optimized with large buffers

### ✗ Reading and Printing (BLOCKED/SLOW)
```python
with open('test_large.txt', 'r') as f:
    content = f.read()  # Loads 108 MB into memory
print(content)  # THIS BLOCKS!
```
**Why it blocks**: 
- Printing to stdout is much slower than disk I/O
- Terminal display can only handle so many characters per second
- The `print()` function tries to output 1 million lines
- Each line must be processed by the terminal emulator

## Performance Comparison

| Operation | Speed | Status |
|-----------|-------|--------|
| Write 1M lines (100 bytes each) = 108 MB | ✓ FAST | Completes quickly |
| Print same 108 MB to terminal | ✗ SLOW | Gets blocked/hangs |

## Why This Matters

### The Bottleneck Chain
```
RAM (fast) → CPU (fast) → Disk (fast) 
         BUT
Disk/RAM (fast) → stdout buffer → Terminal display (SLOW!)
```

The terminal display is the bottleneck!

## Solutions

### 1. Don't Print Everything
```python
# ✗ BAD - Will block
print(large_content)

# ✓ GOOD - Print selectively
print(large_content[:1000])  # First 1000 chars
print(f"Total lines: {len(large_content.splitlines())}")
```

### 2. Stream Processing Instead of Loading All
```python
# ✓ GOOD - Process line by line
with open('test_large.txt', 'r') as f:
    for i, line in enumerate(f):
        if i < 10:  # Only process first 10 lines
            print(line.strip())
        else:
            break
```

### 3. Write to File Instead of stdout
```python
# ✓ GOOD - Output goes to file, not terminal
with open('input_large.txt', 'r') as f_in:
    with open('output.txt', 'w') as f_out:
        for line in f_in:
            f_out.write(line)  # Fast!
```

### 4. Use Pagination/Buffering
```python
# ✓ GOOD - Print in chunks
def print_in_chunks(content, chunk_size=10000):
    for i in range(0, len(content), chunk_size):
        print(content[i:i+chunk_size])
```

### 5. Cap Tool Output
The agent caps `Read` and `Bash` tool results at 50KB before sending them to the UI or model context. Truncated output keeps the beginning and end of the original output with an explicit marker showing that middle content was omitted.

## Key Takeaway

**Writing data is fast, but displaying it is slow.**

When you have lots of data:
- ✓ Writing to files works great
- ✗ Printing everything to terminal will block
- ✓ Process data in chunks or selectively
- ✓ Use file I/O instead of terminal output
- ✓ Cap tool output before rendering it
