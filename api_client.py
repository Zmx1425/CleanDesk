class CleanDeskApiClient:
    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def is_configured(self) -> bool:
        return bool(self.base_url.strip())

    def health_check(self) -> None:
        raise NotImplementedError("API client is reserved for future integration.")
