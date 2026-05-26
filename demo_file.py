"""
This is a demonstration file for viewing diffs.
Updated to show multiple changes across the file.
Version: 2.0
"""

def greet(name, greeting="Hello"):
    """Greet a person by name with a custom greeting."""
    print(f"{greeting}, {name}!")

def calculate_sum(a, b):
    """Calculate the sum of two numbers."""
    result = a + b
    print(f"Computing: {a} + {b} = {result}")
    return result

def multiply(x, y):
    """Multiply two numbers and return the result."""
    return x * y

def main():
    """Main entry point for the application."""
    print("=== Starting Application ===")
    greet("World", greeting="Hey")
    greet("Python")
    total = calculate_sum(5, 3)
    print(f"The sum is: {total}")
    print("=== Application Complete ===")

if __name__ == "__main__":
    main()
