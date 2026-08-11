# ports/message_source.py
from abc import ABC, abstractmethod
from typing import Optional



class MessageSource(ABC):
    """Abstract base for anything that can supply/discover messages."""

    def __init__(self, service_type: str, service_name: str):
        self._service_type = service_type
        self._service_name = service_name

    @property
    def service_type(self) -> str:
        return self._service_type

    @property
    def service_name(self) -> str:
        return self._service_name

    @abstractmethod
    def get_message(self, message_id: str) :
        """Fetch a single message by ID, normalized to InboundMessage."""
        ...

    @abstractmethod
    def list_new_message_ids(self, max_results: int = 20) -> list[str]:
        """Return IDs of messages not yet processed. This is what makes
        discovery possible — get_message() alone can't find anything new."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} service={self._service_type}/{self._service_name}>"