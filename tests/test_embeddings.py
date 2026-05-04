import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageEnhance

from conference_report.config import DEFAULT_CONFIG
from conference_report.dedupe import dedupe_slides
from conference_report.embeddings import compute_slide_embedding_cache, semantic_candidates_from_embeddings
from conference_report.utils import read_json, write_json


def make_cfg():
    return copy.deepcopy(DEFAULT_CONFIG)


def make_slide(path: Path, *, color: tuple[int, int, int] = (240, 240, 240), title: str = "method") -> None:
    image = Image.new("RGB", (320, 180), color)
    pixels = image.load()
    for x in range(40, 220):
        for y in range(50, 80):
            pixels[x, y] = (20, 20, 20)
    if title == "other":
        for x in range(70, 150):
            for y in range(110, 140):
                pixels[x, y] = (180, 30, 30)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class SemanticEmbeddingTests(unittest.TestCase):
    def test_semantic_candidates_recall_high_similarity_transformed_slide(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            slide_a = out / "slides_original" / "[00:00:00.000].png"
            slide_b = out / "slides_original" / "[00:00:10.000].png"
            slide_c = out / "slides_original" / "[00:00:20.000].png"
            make_slide(slide_a)
            make_slide(slide_c, title="other")
            with Image.open(slide_a) as image:
                transformed = ImageEnhance.Brightness(image).enhance(0.72).resize((300, 169))
                transformed.save(slide_b)

            vectors = {
                slide_a.resolve(): [1.0, 0.0, 0.0],
                slide_b.resolve(): [0.98, 0.02, 0.0],
                slide_c.resolve(): [0.0, 1.0, 0.0],
            }
            rows = compute_slide_embedding_cache(
                [slide_a, slide_b, slide_c],
                out,
                make_cfg(),
                embed_image=lambda path: vectors[path.resolve()],
            )

            candidates = semantic_candidates_from_embeddings(rows, threshold=0.95)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["slide_a_time"], "00:00:00.000")
            self.assertEqual(candidates[0]["slide_b_time"], "00:00:10.000")
            self.assertGreaterEqual(candidates[0]["similarity"], 0.95)
            self.assertTrue((out / "embeddings" / "slides" / "00-00-00.000.json").exists())
            self.assertTrue((out / "embeddings" / "slides" / "00-00-00.000.npy").exists())

    def test_embedding_cache_reuse_skips_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            slide = out / "slides_original" / "[00:00:00.000].png"
            make_slide(slide)
            compute_slide_embedding_cache([slide], out, make_cfg(), embed_image=lambda path: [1.0, 0.0])

            rows = compute_slide_embedding_cache(
                [slide],
                out,
                make_cfg(),
                embed_image=mock.Mock(side_effect=AssertionError("cache should be reused")),
            )

            self.assertEqual(rows[0]["vector"], [1.0, 0.0])
            self.assertTrue(rows[0]["cache_hit"])

    def test_dedupe_falls_back_when_embedding_extra_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            make_slide(out / "slides_original" / "[00:00:00.000].png")
            make_slide(out / "slides_original" / "[00:00:10.000].png", title="other")
            (out / "asr").mkdir()
            (out / "asr" / "timeline.txt").write_text("[00:00:01.000] intro\n[00:00:12.000] other\n", encoding="utf-8")
            cfg = make_cfg()
            cfg["embeddings"]["enabled"] = True

            with mock.patch("conference_report.embeddings.load_local_siglip_embedder", side_effect=ImportError("missing transformers")):
                manifest = dedupe_slides(out, cfg)

            self.assertEqual(manifest["semantic_candidate_count"], 0)
            self.assertTrue((out / "dedupe" / "semantic_candidates.json").exists())
            self.assertTrue((out / "dedupe" / "agent_review_tasks.json").exists())
            embedding_manifest = read_json(out / "embeddings" / "embedding_manifest.json")
            self.assertFalse(embedding_manifest["enabled"])
            self.assertIn("missing transformers", embedding_manifest["warning"])


if __name__ == "__main__":
    unittest.main()
