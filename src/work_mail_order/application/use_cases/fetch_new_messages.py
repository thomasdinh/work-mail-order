from __future__ import annotations

import logging

from work_mail_order.application.ports.message_source import Message, MessageSource

logger = logging.getLogger(__name__)


class FetchNewMessages:
    """
    Application use case. Knows nothing about Gmail, IMAP, or HTTP --
    only about the MessageSource port. This is what makes the source
    swappable: this class never changes when you add/replace an adapter.
    """

    def __init__(self, message_source: MessageSource):
        self._message_source = message_source

    def execute(self, max_results: int = 20) -> list[Message]:
        ids = self._message_source.list_new_message_ids(max_results=max_results)
        logger.info("Found %d new message id(s) from %s", len(ids), self._message_source.service_name)

        messages: list[Message] = []
        for message_id in ids:
            msg = self._message_source.get_message(message_id)
            if msg is None:
                logger.warning("Could not fetch message %s, skipping", message_id)
                continue
            messages.append(msg)
        return messages