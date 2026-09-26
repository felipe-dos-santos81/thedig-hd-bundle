class DecodeError(Exception):
    def __init__(self, source: str, offset: int, reason: str):
        super().__init__(f"{source}@{offset:#x}: {reason}")
        self.source, self.offset, self.reason = source, offset, reason

    def to_dict(self) -> dict:
        return {"source": self.source, "offset": self.offset, "reason": self.reason}
