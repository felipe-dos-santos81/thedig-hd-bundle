import unittest

import numpy as np
from PIL import Image

import object_geometry as og
import room_geometry as rg
import source_tree
import testkit


def spec(key):
    return next(o for o in testkit.DEFAULT_OBJECTS if o["key"] == key)


def images(key, rooms=testkit.DEFAULT_ROOMS):
    o = spec(key)
    room_spec = next(r for r in rooms if r["room"] == o["room"])
    room = testkit.room_image(room_spec).convert("RGBA")
    obj = testkit.to_image(testkit.object_pixels(o, rooms), testkit.object_alpha(o)).convert("RGBA")
    return o, room, obj


def promoted(room):
    """A stand-in for the promoted room: its own guide at exactly 4x."""
    guide = rg.build_guide(room)
    return guide.full.crop((0, 0, room.width * 4, room.height * 4))


class ClassifyTests(unittest.TestCase):
    def test_identical_render_and_the_diff(self):
        for key, expected in (("obj010_01", "identical"), ("obj010_02", "render"),
                              ("obj011_01", "render")):
            with self.subTest(key):
                o, room, obj = images(key)
                self.assertEqual(og.classify(obj, room, o["x"], o["y"]), expected)
        o, room, obj = images("obj011_01")
        diff = og.diff_mask(obj, room, o["x"], o["y"])
        self.assertFalse(diff[:2].any(), msg="transparent pixels never count as changed")
        self.assertTrue(diff[2:-2, 2:-2].any())


class ContextTests(unittest.TestCase):
    def test_context_boxes(self):
        cases = {   # (x, y, w, h, room_w, room_h): box
            "middle, widened": ((200, 60, 40, 40, 568, 144), (152, 16, 280, 144)),
            "left edge, widened": ((40, 24, 48, 32, 320, 144), (0, 0, 128, 128)),
            "right edge, widened": ((280, 100, 40, 40, 320, 144), (192, 16, 320, 144)),
            "a room smaller than the minimum": ((0, 0, 8, 8, 16, 200), (0, 0, 16, 128)),
            "into the padding": ((100, 200, 40, 30, 352, 230), (56, 104, 184, 232)),
        }
        for name, (args, expected) in cases.items():
            with self.subTest(name):
                box = og.context_box(*args)
                self.assertEqual(box, expected)
                self.assertTrue(all(v % 8 == 0 for v in box))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.o, self.room, self.obj = images("obj010_02")
        self.hd = promoted(self.room)
        self.inputs = og.object_inputs(self.hd, self.room, self.obj, self.o["x"], self.o["y"])

    def test_sizes_mask_and_composite(self):
        i = self.inputs
        self.assertEqual(i.box, (0, 0, 128, 128))
        for image in (i.guide, i.base, i.composite, i.mask):
            self.assertEqual(image.size, (512, 512))
        m = np.asarray(i.mask)
        self.assertTrue((m[i.changed] == 255).all())
        self.assertEqual(m[-1, -1], 0)
        keep = m == 0
        self.assertTrue((np.asarray(i.composite)[keep] == np.asarray(i.base)[keep]).all())
        self.assertTrue((np.asarray(i.composite)[i.changed] == np.asarray(i.guide)[i.changed]).all())
        self.assertEqual((i.native.size, i.rect), ((128, 128), (40, 24, 88, 56)))

    def test_a_perfect_render_passes_and_a_stray_paste_is_caught(self):
        final = og.compose(self.inputs.composite, self.inputs, 0.5)
        result = og.check_object(final, self.inputs)
        self.assertTrue(result.passed, result.issues)
        crop = og.object_crop(final, self.inputs, self.o["x"], self.o["y"], 48, 32)
        self.assertEqual(crop.size, (192, 128))
        final.paste((255, 0, 255), (500, 500, 512, 512))       # outside the mask
        self.assertIn("pixels outside the object mask differ from the promoted room",
                      " ".join(og.check_object(final, self.inputs).issues))
        slid = og.compose(testkit.shift_right(self.inputs.composite), self.inputs, 0.5)
        issues = " ".join(og.check_object(slid, self.inputs).issues)
        self.assertIn("window 1 is shifted", issues, msg="an object that slid 2 px is caught")

    def test_identical_output_is_the_promoted_crop(self):
        out = og.identical_output(self.hd, 40, 24, 48, 32)
        self.assertEqual(out.tobytes(), self.hd.crop((160, 96, 352, 224)).tobytes())

    def test_a_room_with_a_ragged_height(self):
        rooms = (testkit.room(9, 352, 230),)
        o = testkit.obj("obj050_01", 9, 100, 200, 40, 30)
        room = testkit.room_image(rooms[0]).convert("RGBA")
        obj = testkit.to_image(testkit.object_pixels(o, rooms)).convert("RGBA")
        inputs = og.object_inputs(promoted(room), room, obj, 100, 200)
        self.assertEqual((inputs.box, inputs.composite.size, inputs.native.size),
                         ((56, 104, 184, 232), (512, 512), (128, 126)))
        final = og.compose(inputs.composite, inputs, 0.5)
        self.assertTrue(og.check_object(final, inputs).passed)


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_every_placed_object_classifies(self):
        source = source_tree.load(testkit.REAL_SRC)
        rooms = {r.number: source_tree.open_rgba(testkit.REAL_SRC, r) for r in source.rooms}
        counts = {"identical": 0, "render": 0}
        for o in source.objects:
            if o.placement_error:
                continue
            obj = source_tree.open_rgba(testkit.REAL_SRC, o)
            counts[og.classify(obj, rooms[o.room], o.x, o.y)] += 1
        self.assertGreater(counts["identical"], 0)
        self.assertGreater(counts["render"], 0)


if __name__ == "__main__":
    unittest.main()
