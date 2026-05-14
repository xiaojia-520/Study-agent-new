import unittest
from unittest.mock import patch

from src.core.knowledge.llamaindex_embedding import SentenceTransformerEmbedding


class SentenceTransformerEmbeddingDeviceTests(unittest.TestCase):
    @patch("src.core.knowledge.llamaindex_embedding.resolve_device", return_value="cpu")
    @patch("src.core.knowledge.llamaindex_embedding.SentenceTransformer")
    @patch("src.core.knowledge.llamaindex_embedding._load_base_embedding")
    def test_auto_device_is_resolved_before_model_init(
        self,
        mock_load_base_embedding,
        mock_sentence_transformer,
        mock_resolve_device,
    ) -> None:
        class FakeBaseEmbedding:
            def __init__(self, **kwargs):
                self.model_name = kwargs.get("model_name")
                self.embed_batch_size = kwargs.get("embed_batch_size")
                self.normalize_embeddings = kwargs.get("normalize_embeddings")
                self.show_progress_bar = kwargs.get("show_progress_bar")
                self.device = kwargs.get("device")

        mock_load_base_embedding.return_value = FakeBaseEmbedding
        mock_sentence_transformer.return_value = object()

        embedding = SentenceTransformerEmbedding(model_name="demo-model", device="auto")

        mock_resolve_device.assert_called_once_with("auto")
        mock_sentence_transformer.assert_called_once_with("demo-model", device="cpu")
        self.assertEqual(embedding.device, "cpu")


if __name__ == "__main__":
    unittest.main()
