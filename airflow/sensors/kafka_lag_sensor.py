"""Airflow sensor: waits for the interview-text-stream consumer group lag to reach zero.

Blocks the retraining DAG from starting until the streaming consumer has caught
up with all produced messages — guaranteeing the Delta Lake snapshot is complete
before embeddings are computed.

Usage in a DAG:
    from airflow.sensors.kafka_lag_sensor import KafkaTextStreamLagSensor

    wait_for_lag = KafkaTextStreamLagSensor(
        task_id="wait_for_text_stream_lag_zero",
        kafka_bootstrap_servers="{{ var.value.KAFKA_BOOTSTRAP_SERVERS }}",
        topic="{{ var.value.KAFKA_TOPIC_TEXT }}",
        consumer_group="{{ var.value.TEXT_CONSUMER_GROUP }}",
        max_lag=0,
        poke_interval=30,
        timeout=3600,
    )
"""

from __future__ import annotations

import structlog
from airflow.sensors.base import BaseSensorOperator
from confluent_kafka import Consumer, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient

logger = structlog.get_logger(__name__)


class KafkaTextStreamLagSensor(BaseSensorOperator):
    """Poke the Kafka consumer group until its lag on ``topic`` reaches ``max_lag``.

    Args:
        kafka_bootstrap_servers: Kafka broker address(es), e.g. "localhost:9092".
        topic: Kafka topic to monitor (interview-text-stream).
        consumer_group: Consumer group whose committed offsets are checked.
        max_lag: Maximum acceptable total lag across all partitions (default 0).
        poke_interval: Seconds between polls (passed to BaseSensorOperator).
        timeout: Total seconds before the sensor fails (passed to BaseSensorOperator).
    """

    template_fields = ("kafka_bootstrap_servers", "topic", "consumer_group")

    def __init__(
        self,
        *,
        kafka_bootstrap_servers: str,
        topic: str,
        consumer_group: str,
        max_lag: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.kafka_bootstrap_servers = kafka_bootstrap_servers
        self.topic = topic
        self.consumer_group = consumer_group
        self.max_lag = max_lag
        self._log = logger.bind(
            sensor="KafkaTextStreamLagSensor",
            topic=topic,
            consumer_group=consumer_group,
        )

    def poke(self, context: dict) -> bool:  # type: ignore[override]
        """Return True when total consumer group lag ≤ max_lag.

        Args:
            context: Airflow task context (unused but required by interface).

        Returns:
            True if lag is within the acceptable threshold, False to retry.
        """
        try:
            lag = self._get_consumer_lag()
        except KafkaException as exc:
            self._log.error("lag_check_failed", error=str(exc))
            return False

        self._log.info("lag_checked", total_lag=lag, max_lag=self.max_lag)
        return lag <= self.max_lag

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_consumer_lag(self) -> int:
        """Compute total consumer group lag across all partitions.

        Returns:
            Total number of unconsumed messages across all partitions of ``topic``
            for the configured consumer group.

        Raises:
            KafkaException: On broker communication failure.
        """
        admin = AdminClient({"bootstrap.servers": self.kafka_bootstrap_servers})

        # Discover partition count from topic metadata
        metadata = admin.list_topics(topic=self.topic, timeout=10)
        if self.topic not in metadata.topics:
            raise KafkaException(f"Topic '{self.topic}' not found in broker metadata")

        partitions = [
            TopicPartition(self.topic, pid)
            for pid in metadata.topics[self.topic].partitions.keys()
        ]

        # Fetch high-watermark (end offsets) for each partition
        consumer = Consumer(
            {
                "bootstrap.servers": self.kafka_bootstrap_servers,
                "group.id": self.consumer_group,
                "enable.auto.commit": False,
            }
        )
        try:
            # Committed offsets for the consumer group
            committed = consumer.committed(partitions, timeout=10)

            total_lag = 0
            for tp in committed:
                # tp.offset == OFFSET_INVALID (-1001) means the group has never committed
                committed_offset = max(tp.offset, 0)

                # High watermark: (low, high) = query_watermark_offsets(...)
                _, high = consumer.get_watermark_offsets(tp, timeout=10)
                partition_lag = max(high - committed_offset, 0)
                total_lag += partition_lag

                self._log.debug(
                    "partition_lag",
                    partition=tp.partition,
                    committed=committed_offset,
                    high_watermark=high,
                    lag=partition_lag,
                )
        finally:
            consumer.close()

        return total_lag
