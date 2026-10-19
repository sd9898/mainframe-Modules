"""Demo Python file for the CST/AST microservices."""


def greet(name: str, times: int = 1) -> str:
    messages = []
    for _ in range(times):
        messages.append(f"Hello, {name}!")
    return " ".join(messages)


class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a, b):
        result = a + b
        self.history.append(result)
        return result


if __name__ == "__main__":
    print(greet("COBOL world"))
