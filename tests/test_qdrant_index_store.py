import unittest
from unittest.mock import patch

from src.core.knowledge.query_filters import MetadataFilterClause, MetadataFilterSpec
from src.infrastructure.storage.qdrant_index_store import QdrantIndexStore


class FakeMetadataFilter:
    def __init__(self, *, key, value, operator):
        self.key = key
        self.value = value
        self.operator = operator


class FakeMetadataFilters:
    def __init__(self, *, filters, condition):
        self.filters = filters
        self.condition = condition


class FakeFilterCondition:
    AND = "AND"
    OR = "OR"


class FakeFilterOperator:
    EQ = "EQ"
    NE = "NE"


class FakeQdrantFieldCondition:
    def __init__(self, *, key, match):
        self.key = key
        self.match = match


class FakeQdrantFilter:
    def __init__(self, *, must=None, must_not=None):
        self.must = must
        self.must_not = must_not


class FakeQdrantFilterSelector:
    def __init__(self, *, filter):
        self.filter = filter


class FakeQdrantMatchValue:
    def __init__(self, *, value):
        self.value = value


class FakeQdrantClient:
    def __init__(self):
        self.delete_calls = []

    def collection_exists(self, *, collection_name):
        self.collection_name = collection_name
        return True

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)


class QdrantIndexStoreTests(unittest.TestCase):
    def test_normalize_filters_converts_metadata_filter_spec(self) -> None:
        store = QdrantIndexStore()
        filters = MetadataFilterSpec(
            clauses=(
                MetadataFilterClause("course_id", "math-course"),
                MetadataFilterClause("lesson_id", "lesson-1", operator="ne"),
            )
        )

        with patch.object(
            store,
            "_load_metadata_filter_types",
            return_value=(FakeMetadataFilter, FakeMetadataFilters, FakeFilterCondition, FakeFilterOperator),
        ):
            normalized = store._normalize_filters(filters)

        self.assertIsInstance(normalized, FakeMetadataFilters)
        self.assertEqual(normalized.condition, "AND")
        self.assertEqual([(item.key, item.value, item.operator) for item in normalized.filters], [
            ("course_id", "math-course", "EQ"),
            ("lesson_id", "lesson-1", "NE"),
        ])

    def test_normalize_filters_keeps_foreign_filter_objects(self) -> None:
        store = QdrantIndexStore()
        sentinel = object()

        self.assertIs(store._normalize_filters(sentinel), sentinel)

    def test_delete_by_metadata_builds_qdrant_filter_selector(self) -> None:
        client = FakeQdrantClient()
        store = QdrantIndexStore(client=client)
        filters = MetadataFilterSpec(
            clauses=(MetadataFilterClause("session_id", "session-a"),)
        )

        with patch.object(
            store,
            "_load_qdrant_filter_types",
            return_value=(
                FakeQdrantFieldCondition,
                FakeQdrantFilter,
                FakeQdrantFilterSelector,
                FakeQdrantMatchValue,
            ),
        ):
            store.delete_by_metadata(filters)

        self.assertEqual(len(client.delete_calls), 1)
        call = client.delete_calls[0]
        self.assertEqual(call["collection_name"], store.config.collection_name)
        self.assertTrue(call["wait"])
        selector = call["points_selector"]
        self.assertEqual(selector.filter.must[0].key, "session_id")
        self.assertEqual(selector.filter.must[0].match.value, "session-a")


if __name__ == "__main__":
    unittest.main()
