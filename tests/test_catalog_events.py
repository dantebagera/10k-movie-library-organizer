import json
import queue
import unittest

from services.catalog_events import CatalogEventBroker


class CatalogEventBrokerTests(unittest.TestCase):
    def test_initial_sync_and_strict_post_commit_generation(self):
        broker = CatalogEventBroker()
        client = broker.subscribe(current_generation=4)
        self.assertEqual(client.get_nowait(), {"type": "catalog-sync", "generation": 4})
        self.assertTrue(broker.publish(5, reason="observer", movie_keys=["tmdb:5"], changed_count=1))
        event = client.get_nowait()
        self.assertEqual(event["generation"], 5)
        self.assertFalse(broker.publish(5, reason="observer", changed_count=1))

    def test_replay_is_strictly_newer_and_old_cursor_gets_sync(self):
        broker = CatalogEventBroker()
        for generation in (10, 11, 12):
            broker.publish(generation, reason="recovery", changed_count=1)
        replay = broker.subscribe(last_event_id="10", current_generation=12)
        self.assertEqual([replay.get_nowait()["generation"] for _ in range(2)], [11, 12])
        old = broker.subscribe(last_event_id="1", current_generation=12)
        self.assertEqual(old.get_nowait(), {"type": "catalog-sync", "generation": 12})

    def test_slow_client_pressure_coalesces_without_blocking_publish(self):
        broker = CatalogEventBroker()
        client = broker.subscribe(current_generation=0)
        client.get_nowait()
        for generation in range(1, 80):
            self.assertTrue(broker.publish(generation, reason="observer", changed_count=1))
        retained = []
        while True:
            try: retained.append(client.get_nowait())
            except queue.Empty: break
        self.assertLessEqual(len(retained), broker.CLIENT_CAPACITY)
        self.assertTrue(any(event["type"] == "catalog-sync" for event in retained))

    def test_stream_headers_payload_shape_and_shutdown(self):
        broker = CatalogEventBroker()
        stream = broker.stream(current_generation=8)
        self.assertEqual(next(stream), "retry: 2000\n\n")
        sync = next(stream)
        self.assertIn("event: catalog-sync", sync)
        self.assertEqual(json.loads(sync.split("data: ", 1)[1]), {"type": "catalog-sync", "generation": 8})
        broker.shutdown()
        with self.assertRaises(StopIteration):
            next(stream)


if __name__ == "__main__":
    unittest.main()
