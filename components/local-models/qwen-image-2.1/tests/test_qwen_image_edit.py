#!/usr/bin/env python3

import importlib.util
import os
import sys
import unittest
from pathlib import Path


SCRIPT = Path(os.environ["QWEN_IMAGE_EDIT_SCRIPT"])
SPEC = importlib.util.spec_from_file_location("qwen_image_edit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class WorkflowTests(unittest.TestCase):
    def test_image_edit_workflow_uses_selected_precision_and_core_nodes(self):
        graph = MODULE.workflow(["input/example.png"], "make it blue", "", 25, 1024, 42)

        self.assertEqual(
            graph["1"]["inputs"]["unet_name"],
            "qwen_image_2.1_int8_convrot.safetensors",
        )
        self.assertEqual(
            graph["2"]["inputs"]["clip_name"],
            "qwen3vl_8b_int8_convrot.safetensors",
        )
        self.assertEqual(graph["2"]["inputs"]["type"], "qwen_image")
        self.assertEqual(graph["5"]["inputs"]["images.image_1"], ["4", 0])
        self.assertEqual(graph["5"]["inputs"]["resolution"], 1024)
        self.assertEqual(graph["6"]["inputs"]["device"], "cpu")
        self.assertEqual(graph["6"]["inputs"]["dtype"], "default")
        self.assertEqual(graph["7"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["7"]["inputs"]["steps"], 25)
        self.assertEqual(graph["7"]["inputs"]["seed"], 42)
        self.assertEqual(graph["9"]["class_type"], "SaveImage")

    def test_multi_image_workflow_connects_each_reference_in_order(self):
        graph = MODULE.workflow(
            ["primary.jpg", "style.jpg", "subject.png"],
            "put the subject from Image 3 into Image 1 using Image 2's style",
            "", 25, 1024, 42,
        )

        self.assertEqual(graph["4"]["inputs"]["image"], "primary.jpg")
        self.assertEqual(graph["10"]["inputs"]["image"], "style.jpg")
        self.assertEqual(graph["11"]["inputs"]["image"], "subject.png")
        self.assertEqual(graph["5"]["inputs"]["images.image_1"], ["4", 0])
        self.assertEqual(graph["5"]["inputs"]["images.image_2"], ["10", 0])
        self.assertEqual(graph["5"]["inputs"]["images.image_3"], ["11", 0])

    def test_workflow_rejects_more_than_sixteen_images(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 16 images"):
            MODULE.workflow([f"{index}.png" for index in range(17)], "edit", "", 25, 1024, 42)


if __name__ == "__main__":
    unittest.main()
