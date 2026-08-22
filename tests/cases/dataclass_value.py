from dataclasses import asdict, dataclass


@dataclass
class Result:
    answer: int


def run():
    return asdict(Result(answer=42))
