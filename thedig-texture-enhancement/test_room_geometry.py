import unittest

import numpy as np
from PIL import Image

import room_geometry as rg
import testkit


def checkerboard(a, b, size=(32, 32)):
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w]
    arr = np.where(((xs + ys) % 2 == 0)[..., None], np.array(a, np.uint8), np.array(b, np.uint8))
    return Image.fromarray(arr.astype(np.uint8))


def fixture_room(number):
    spec = next(s for s in testkit.DEFAULT_ROOMS if s["room"] == number)
    return testkit.room_image(spec)


def noise(size, seed=0):
    w, h = size
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8))


def boxes(windows):
    return [w.box for w in windows]


class GuideTests(unittest.TestCase):
    def test_build_guide_sizes(self):
        guide = rg.build_guide(fixture_room(2))
        self.assertEqual((guide.native.size, guide.full.size), ((568, 144), (2272, 576)))
        self.assertEqual((guide.native.mode, guide.full.mode), ("RGB", "RGB"))

    def test_dedither_softens_the_checkerboard(self):
        board = checkerboard((100, 100, 100), (130, 130, 130))
        board_std = np.asarray(board, dtype=float).std()
        for method, factor in (("palette-smooth", 0.2), ("gaussian", 0.5)):
            with self.subTest(method=method):
                out = np.asarray(rg.dedither(board, method), dtype=float)
                self.assertLess(out.std(), factor * board_std)

    def test_palette_smooth_keeps_edges_between_far_colours(self):
        arr = np.zeros((8, 16, 3), np.uint8)
        arr[:, :8], arr[:, 8:] = 20, 220
        image = Image.fromarray(arr)
        self.assertEqual(rg.dedither(image, "palette-smooth").tobytes(), image.tobytes())

    def test_unknown_method(self):
        with self.assertRaisesRegex(ValueError, "unknown de-dither method 'median'"):
            rg.dedither(checkerboard((0, 0, 0), (1, 1, 1)), "median")

    def test_the_guide_is_padded_to_whole_strips(self):
        image = testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 230)))
        guide = rg.build_guide(image)
        self.assertEqual((guide.native.size, guide.full.size), ((352, 230), (1408, 928)))
        padded = rg.pad_rows(image.convert("RGB"), 232)
        last = np.asarray(image.convert("RGB"))[-1]
        self.assertTrue((np.asarray(padded)[230:] == last).all())


class MarginTests(unittest.TestCase):
    def test_blank_margins(self):
        every_side = np.zeros((10, 20), np.uint8)   # a black frame ...
        every_side[3:8, 2:16] = 5                   # ... around content of index 5 ...
        every_side[4:6, 6:10] = 7                   # ... with some detail
        cases = {
            "right margin of the wraparound fixture": (
                testkit.room_pixels(testkit.DEFAULT_ROOMS[2]), rg.Margins(0, 88, 0, 0)),
            "margins on every side": (every_side, rg.Margins(2, 4, 3, 2)),
        }
        for name, (pixels, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(rg.blank_margins(pixels), expected)

    def test_a_run_needs_one_index_throughout(self):
        pixels = np.full((4, 8), 3, np.uint8)
        pixels[:, 0], pixels[:, 1] = 1, 2           # two flat columns of different indices
        pixels[1, 4] = 9
        self.assertEqual(rg.blank_margins(pixels).left, 1)


class WrapTests(unittest.TestCase):
    def test_find_wrap(self):
        end = 1152 - 88                                                 # wrap (840, 224), 88 margin
        exact = testkit.room_pixels(testkit.DEFAULT_ROOMS[2])
        few_diffs = exact.copy()
        few_diffs[:4, 900:904] = 1                  # 16 of 32256 pixels: a 99.95% match
        many_diffs = exact.copy()
        many_diffs[:13, 900:905] = 1                # 65 of 32256 pixels: a 99.8% match
        cases = {
            "finds the repeat": (exact, end, rg.Wrap(840, 224)),
            "tolerates a few differences": (few_diffs, end, rg.Wrap(840, 224)),
            "needs nearly every pixel": (many_diffs, end, None),
            "no repeat": (testkit.room_pixels(testkit.room(9, 1152, 144, right_margin=88)),
                         end, None),
            "ignores a repeat closer than one screen": (
                testkit.room_pixels(testkit.room(9, 400, 144, wrap=(200, 200))), 400, None),
        }
        for name, (pixels, plan_end, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(rg.find_wrap(pixels, plan_end), expected)


class WindowPlanTests(unittest.TestCase):
    def test_known_plans(self):
        cases = {
            (0, 320, 320): [(0, 320)],
            (64, 240, 320): [(64, 240)],
            (0, 568, 320): [(0, 320), (248, 568)],
            (0, 840, 320): [(0, 320), (168, 488), (344, 664), (520, 840)],
            (0, 232, 240): [(0, 232)],
            (0, 400, 240): [(0, 240), (160, 400)],
            (0, 472, 240): [(0, 240), (112, 352), (232, 472)],
            (0, 784, 240): [(0, 240), (136, 376), (272, 512), (408, 648), (544, 784)],
        }
        for (start, end, size), expected in cases.items():
            with self.subTest(span=(start, end, size)):
                self.assertEqual(list(rg.plan_axis(start, end, size)), expected)

    def test_rules_hold_on_both_axes(self):
        for size in (rg.WINDOW_HEIGHT, rg.WINDOW_WIDTH):
            for end in range(size + 8, 2000, 8):
                with self.subTest(size=size, end=end):
                    spans = rg.plan_axis(0, end, size)
                    self.assertEqual((spans[0][0], spans[-1][1]), (0, end))
                    for a, b in spans:
                        self.assertEqual((b - a, a % 8), (size, 0))
                    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
                        self.assertGreaterEqual(a1 - b0, rg.WINDOW_OVERLAP)
                        self.assertLess(a0, b0)


class RoomPlanTests(unittest.TestCase):
    def test_fixture_rooms(self):
        one = rg.plan_room(fixture_room(1))
        self.assertEqual((boxes(one.windows), one.wrap, one.span),
                         ([(0, 0, 320, 144)], None, (0, 320)))
        self.assertEqual(rg.stitch_boundaries(one), rg.Boundaries([], []), msg="stitch boundaries")
        two = rg.plan_room(fixture_room(2))
        self.assertEqual(boxes(two.windows), [(0, 0, 320, 144), (248, 0, 568, 144)])
        self.assertEqual(rg.stitch_boundaries(two).columns, [1136], msg="stitch boundaries")
        wrap = rg.plan_room(fixture_room(3))
        self.assertEqual((wrap.wrap, wrap.span, wrap.margins),
                         (rg.Wrap(840, 224), (0, 840), rg.Margins(0, 88, 0, 0)))
        self.assertEqual(len(wrap.windows), 4)
        self.assertEqual(rg.stitch_boundaries(wrap).columns, [320, 976, 1664, 2368, 3040, 3360],
                         msg="stitch boundaries")

    def test_margins_round_the_span_out_to_8_columns(self):
        pixels = testkit.room_pixels(testkit.room(9, 320, 200))
        pixels[:, :66], pixels[:, 239:] = 0, 0      # the labyrinth pieces' side margins
        plan = rg.plan_room(testkit.to_image(pixels))
        self.assertEqual((plan.margins.left, plan.margins.right), (66, 81))
        self.assertEqual((plan.span, boxes(plan.windows)), ((64, 240), [(64, 0, 240, 200)]))

    def test_a_flat_room_has_nothing_to_render(self):
        with self.assertRaisesRegex(ValueError, "set kind: skip"):
            rg.plan_room(fixture_room(4))

    def test_a_tall_room_is_padded_and_planned_in_rows(self):
        plan = rg.plan_room(testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 470))))
        self.assertEqual((plan.height, plan.span, plan.rows), (472, (0, 352), (0, 472)))
        self.assertEqual(boxes(plan.windows),
                         [(0, 0, 320, 240), (32, 0, 352, 240),
                          (0, 112, 320, 352), (32, 112, 352, 352),
                          (0, 232, 320, 472), (32, 232, 352, 472)])
        for win in plan.windows:
            self.assertEqual((win.width * 4 % 32, win.height * 4 % 32), (0, 0))

    def test_top_and_bottom_margins_trim_the_rows(self):
        pixels = testkit.room_pixels(testkit.room(9, 320, 144))
        pixels[:28], pixels[-26:] = 0, 0
        plan = rg.plan_room(testkit.to_image(pixels))
        self.assertEqual((plan.margins.top, plan.margins.bottom, plan.rows), (28, 26, (24, 120)))

    def test_a_wraparound_taller_than_one_window_row_is_refused(self):
        # right_margin=88 makes content_end land exactly at period + span (840 + 224 = 1064
        # of 1152), the same pairing as the wraparound fixture (DEFAULT_ROOMS[2]); without it
        # find_wrap never matches and no ValueError is raised.
        spec = testkit.room(9, 1152, 480, wrap=(840, 224), right_margin=88)
        with self.assertRaisesRegex(ValueError, "taller than one window row"):
            rg.plan_room(testkit.to_image(testkit.room_pixels(spec)))


class WindowInputTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(fixture_room(2))           # windows (0, 320), (248, 568)
        self.guide = noise((2272, 576), seed=1)
        self.canvas = noise((2272, 576), seed=2)

    def test_window_inputs(self):
        with self.subTest("a first window is painted whole"):
            crop, composite, mask = rg.window_inputs(self.guide, self.canvas,
                                                      self.plan.windows[0], None, None)
            self.assertEqual(crop.size, (1280, 576))
            self.assertEqual(composite.tobytes(), crop.tobytes())
            self.assertEqual((mask.mode, set(np.asarray(mask).ravel())), ("L", {255}))
        with self.subTest("a later window holds the outer half of its overlap"):
            first, second = self.plan.windows
            crop, composite, mask = rg.window_inputs(self.guide, self.canvas, second, first, None)
            m = np.asarray(mask)
            self.assertTrue((m[:, :144] == 0).all())                # 36 native columns held
            ramp = m[0, 144:288]
            self.assertTrue(((ramp > 0) & (ramp < 255)).all())
            self.assertTrue((np.diff(ramp.astype(int)) >= 0).all())
            self.assertTrue((m[:, 288:] == 255).all())
            c = np.asarray(composite)
            self.assertTrue((c[:, :288] == np.asarray(self.canvas)[:, 992:1280]).all())
            self.assertTrue((c[:, 288:] == np.asarray(crop)[:, 288:]).all())

    def test_paste_window_starts_mid_overlap(self):
        first, second = self.plan.windows
        rendered = noise((1280, 576), seed=3)
        before = np.asarray(self.canvas).copy()
        rg.paste_window(self.canvas, second, first, None, rendered)
        after = np.asarray(self.canvas)
        self.assertTrue((after[:, :1136] == before[:, :1136]).all())
        self.assertTrue((after[:, 1136:] == np.asarray(rendered)[:, 144:]).all())


class GridTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(testkit.to_image(testkit.room_pixels(testkit.room(9, 352, 470))))
        self.guide = noise((1408, 1888), seed=1)
        self.canvas = noise((1408, 1888), seed=2)

    def test_neighbours_and_boundaries(self):
        w = self.plan.windows
        self.assertEqual(rg.neighbours(self.plan, 0), (None, None))
        self.assertEqual(rg.neighbours(self.plan, 1), (w[0], None))
        self.assertEqual(rg.neighbours(self.plan, 3), (w[2], w[1]))
        self.assertEqual(rg.stitch_origin(w[3], w[2], w[1]), (176, 176))
        self.assertEqual(rg.stitch_boundaries(self.plan), rg.Boundaries([704], [704, 1168]))

    def test_an_inner_window_keeps_an_l_of_what_is_painted(self):
        w = self.plan.windows
        crop, composite, mask = rg.window_inputs(self.guide, self.canvas, w[3], w[2], w[1])
        self.assertEqual(crop.size, (1280, 960))
        m = np.asarray(mask)
        self.assertEqual((m[0, 0], m[0, -1], m[-1, 0], m[-1, -1]), (0, 0, 0, 255))
        c, canvas = np.asarray(composite), np.asarray(self.canvas)
        # overlap with the upper window: native rows 112-240, all columns of the window
        self.assertTrue((c[:512] == canvas[448:960, 128:1408]).all())
        # overlap with the left window: native columns 32-320, all rows of the window
        self.assertTrue((c[:, :1152] == canvas[448:1408, 128:1280]).all())

    def test_paste_starts_at_the_stitch_origin(self):
        w = self.plan.windows
        before = np.asarray(self.canvas).copy()
        rendered = noise((1280, 960), seed=3)
        rg.paste_window(self.canvas, w[3], w[2], w[1], rendered)
        after, r = np.asarray(self.canvas), np.asarray(rendered)
        self.assertTrue((after[704:1408, 704:1408] == r[256:, 576:]).all())
        self.assertTrue((after[:704] == before[:704]).all())
        self.assertTrue((after[:, :704] == before[:, :704]).all())


class SeamTests(unittest.TestCase):
    def setUp(self):
        self.plan = rg.plan_room(fixture_room(3))           # wrap (840, 224)
        self.guide = noise((4608, 576), seed=4)
        self.canvas = noise((4608, 576), seed=5)

    def test_seam_inputs_roll_the_join_into_the_middle(self):
        strip, composite, mask = rg.seam_inputs(self.guide, self.canvas, self.plan)
        self.assertEqual(strip.size, (1280, 576))
        c, canvas = np.asarray(composite), np.asarray(self.canvas)
        self.assertTrue((c[:, :640] == canvas[:, 2720:3360]).all())
        self.assertTrue((c[:, 640:] == canvas[:, :640]).all())
        m = np.asarray(mask)[0]
        self.assertTrue((m[:320] == 0).all() and (m[960:] == 0).all())
        self.assertTrue((m[480:800] == 255).all())
        self.assertTrue(((m[320:480] > 0) & (m[320:480] < 255)).all())

    def test_apply_seam_writes_both_ends(self):
        rendered = noise((1280, 576), seed=6)
        before = np.asarray(self.canvas).copy()
        rg.apply_seam(self.canvas, self.plan, rendered)
        after, r = np.asarray(self.canvas), np.asarray(rendered)
        self.assertTrue((after[:, 3040:3360] == r[:, 320:640]).all())
        self.assertTrue((after[:, :320] == r[:, 640:960]).all())
        self.assertTrue((after[:, 320:3040] == before[:, 320:3040]).all())
        self.assertTrue((after[:, 3360:] == before[:, 3360:]).all())


class FixupTests(unittest.TestCase):
    def test_apply_fixups_blanks_margins_and_copies_the_wrap(self):
        with self.subTest("wrap copy and right margin"):
            image = fixture_room(3)
            out = np.asarray(rg.apply_fixups(noise((4608, 576), seed=7), rg.plan_room(image),
                                             image))
            self.assertTrue((out[:, 3360:4256] == out[:, :896]).all())
            self.assertTrue((out[:, 4256:] == 0).all())
        with self.subTest("top and bottom margins"):
            pixels = testkit.room_pixels(testkit.room(9, 320, 144))
            pixels[:28], pixels[-26:] = 0, 0            # room 58's letterbox rows
            image = testkit.to_image(pixels)
            out = np.asarray(rg.apply_fixups(noise((1280, 576), seed=8), rg.plan_room(image),
                                             image))
            self.assertTrue((out[:112] == 0).all() and (out[-104:] == 0).all())
            self.assertFalse((out[112:-104] == 0).all())

    def test_nothing_to_fix(self):
        image = fixture_room(1)
        canvas = noise((1280, 576), seed=9)
        self.assertEqual(rg.apply_fixups(canvas, rg.plan_room(image), image).tobytes(),
                         canvas.tobytes())


if __name__ == "__main__":
    unittest.main()
