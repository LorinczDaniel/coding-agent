"""
Practical examples of handling large files without blocking output.
"""

import time


def example_1_bad_approach():
    """❌ BAD: This will block when printing large content"""
    print("\n=== Example 1: BAD APPROACH (BLOCKING) ===")
    print("Writing large file...")
    
    # Write lots of data
    with open('/tmp/demo_large.txt', 'w') as f:
        for i in range(100000):  # 100k lines
            f.write(f"Line {i}: data\n")
    
    # Try to print it all - THIS BLOCKS!
    print("Reading and printing entire file (will be slow)...")
    with open('/tmp/demo_large.txt', 'r') as f:
        content = f.read()
    
    # This will take forever if uncommented:
    # print(content)  # DON'T DO THIS!
    
    print(f"✗ File has {len(content)} characters - too much to print!")


def example_2_selective_print():
    """✓ GOOD: Print only what you need"""
    print("\n=== Example 2: GOOD APPROACH (SELECTIVE PRINT) ===")
    print("Writing large file...")
    
    with open('/tmp/demo_large.txt', 'w') as f:
        for i in range(100000):
            f.write(f"Line {i}: data\n")
    
    print("Reading file...")
    with open('/tmp/demo_large.txt', 'r') as f:
        content = f.read()
    
    print(f"✓ File statistics:")
    lines = content.splitlines()
    print(f"  - Total lines: {len(lines)}")
    print(f"  - Total size: {len(content)} bytes")
    print(f"\n  First 5 lines:")
    for line in lines[:5]:
        print(f"    {line}")
    print(f"\n  Last 5 lines:")
    for line in lines[-5:]:
        print(f"    {line}")


def example_3_stream_processing():
    """✓ GOOD: Process line-by-line instead of loading all"""
    print("\n=== Example 3: GOOD APPROACH (STREAMING) ===")
    print("Writing large file...")
    
    with open('/tmp/demo_large.txt', 'w') as f:
        for i in range(100000):
            f.write(f"Line {i}: {'x' * 50}\n")
    
    print("Processing file line-by-line (streaming)...")
    start = time.time()
    
    line_count = 0
    total_chars = 0
    
    with open('/tmp/demo_large.txt', 'r') as f:
        for line in f:  # Stream processing - doesn't load all at once
            line_count += 1
            total_chars += len(line)
            
            # Only display first 3 and last 3 lines
            if line_count <= 3:
                print(f"  Line {line_count}: {line[:40]}...")
            elif line_count == 4:
                print(f"  ...")
    
    elapsed = time.time() - start
    print(f"\n✓ Processed {line_count} lines ({total_chars} chars) in {elapsed:.2f}s")
    print(f"  Last 3 lines shown above")


def example_4_chunked_output():
    """✓ GOOD: Output in manageable chunks"""
    print("\n=== Example 4: GOOD APPROACH (CHUNKED OUTPUT) ===")
    print("Writing large file...")
    
    with open('/tmp/demo_large.txt', 'w') as f:
        for i in range(50000):
            f.write(f"Data {i}\n")
    
    print("Reading and processing in chunks...")
    
    def process_file_in_chunks(filename, chunk_lines=1000):
        with open(filename, 'r') as f:
            chunk = []
            for i, line in enumerate(f):
                chunk.append(line)
                
                # Process when chunk is full
                if len(chunk) >= chunk_lines:
                    yield chunk
                    chunk = []
            
            # Yield remaining
            if chunk:
                yield chunk
    
    chunk_count = 0
    total_lines = 0
    
    for chunk in process_file_in_chunks('/tmp/demo_large.txt', chunk_lines=5000):
        chunk_count += 1
        total_lines += len(chunk)
        
        if chunk_count <= 2:  # Show first 2 chunks
            print(f"\n  Chunk {chunk_count}: {len(chunk)} lines")
            print(f"    First line: {chunk[0][:40]}")
        elif chunk_count == 3:
            print(f"  ...")
    
    print(f"\n✓ Processed {total_lines} lines in {chunk_count} chunks")


def example_5_file_to_file():
    """✓ GOOD: Process without printing to terminal"""
    print("\n=== Example 5: GOOD APPROACH (FILE TO FILE) ===")
    print("Writing source file...")
    
    with open('/tmp/demo_source.txt', 'w') as f:
        for i in range(100000):
            f.write(f"Input {i}: {'y' * 30}\n")
    
    print("Processing (source → output file, no terminal output)...")
    start = time.time()
    
    line_count = 0
    with open('/tmp/demo_source.txt', 'r') as f_in:
        with open('/tmp/demo_output.txt', 'w') as f_out:
            for line in f_in:
                # Process and write directly to output
                line_count += 1
                processed = line.upper()  # Example processing
                f_out.write(processed)
    
    elapsed = time.time() - start
    
    print(f"✓ Processed {line_count} lines in {elapsed:.2f}s (no terminal blocking!)")
    print(f"  Output written to: /tmp/demo_output.txt")


if __name__ == "__main__":
    print("╔" + "=" * 60 + "╗")
    print("║  Large File Processing Examples - Avoiding Output Blocking  ║")
    print("╚" + "=" * 60 + "╝")
    
    example_1_bad_approach()
    example_2_selective_print()
    example_3_stream_processing()
    example_4_chunked_output()
    example_5_file_to_file()
    
    print("\n" + "=" * 62)
    print("KEY TAKEAWAY:")
    print("  • Writing to disk is FAST")
    print("  • Printing to terminal is SLOW (the bottleneck)")
    print("  • Always process/output strategically with large files!")
    print("=" * 62)
