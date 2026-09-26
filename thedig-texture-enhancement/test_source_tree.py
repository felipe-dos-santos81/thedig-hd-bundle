import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import source_tree
import testkit
from source_tree import SourceError


class SourceTreeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.src = testkit.make_source(self.tmp)

    def test_loads_rooms_and_objects_and_ignores_other_kinds(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source.rooms], [1, 2, 3, 4])
        room = source.rooms[2]
        self.assertEqual((room.key, room.out_name, room.rel), ("room_003", "room_003.png",
                                                               Path("la1/room003.png")))
        self.assertEqual(((room.width, room.height), room.out_size, room.mode),
                         ((1152, 144), (4608, 576), "RGB"))
        self.assertEqual([o.key for o in source.objects],
                         ["obj010_01", "obj010_02", "obj011_01", "obj012_01", "obj013_01",
                          "obj014_01"])
        sprite = source.objects[2]
        self.assertEqual((sprite.room, sprite.room_key, sprite.box, sprite.mode,
                          sprite.out_name, sprite.out_size),
                         (1, "room_001", (200, 60, 240, 100), "RGBA", "obj011_01.png",
                          (160, 160)))
        self.assertIsNone(sprite.placement_error)

    def test_an_object_outside_its_room_loads_with_a_placement_error(self):
        testkit.rewrite_manifest(self.src, lambda assets: assets.append(
            dict(next(a for a in assets if a["name"] == "obj014_01"),
                 id="la1:obj099_01", name="obj099_01", room=77)))
        by_key = {o.key: o for o in source_tree.load(self.src).objects}
        self.assertRegex(by_key["obj013_01"].placement_error, r"not inside room_001 \(320x144\)")
        self.assertRegex(by_key["obj099_01"].placement_error, "room 77 is not in the manifest")

    def test_refuses_a_manifest_that_disagrees_with_its_files(self):
        def edit(field, value, name="room001"):
            def change(assets):
                next(a for a in assets if a.get("name") == name)[field] = value
            return change

        def drop(field, name):
            def change(assets):
                del next(a for a in assets if a.get("name") == name)[field]
            return change

        cases = {
            "missing file": (edit("path", "la1/room999.png"), "file not found"),
            "size": (edit("width", 336), "the manifest says 336x144"),
            "strips": (edit("width", 322), "multiple of 8"),
            "escaping path": (edit("path", "../x.png"), "relative path inside"),
            "room number": (edit("room", 2), "room001 must be room 1"),
            "mode": (edit("has_alpha", True), "mode RGB, expected RGBA"),
            "no placement": (drop("x", "obj010_01"), '"x" must be an integer'),
            "no room": (drop("room", "obj010_01"), '"room" must be a positive integer'),
            "odd name": (edit("name", "sprite7"), "unexpected la1 asset name"),
            "duplicate": (lambda assets: next(a for a in assets if a.get("name") == "room002")
                          .update(name="room001", room=1), "duplicate room 1"),
            "no rooms": (lambda assets: assets.clear(), "lists no rooms"),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name):
                src = testkit.make_source(self.tmp / name)
                testkit.rewrite_manifest(src, change)
                with self.assertRaisesRegex(SourceError, message):
                    source_tree.load(src)

    def test_refuses_an_old_or_foreign_manifest(self):
        with self.subTest("0.1.0 has no placement"):
            src = testkit.make_source(self.tmp / "old", tool_version="0.1.0")
            with self.assertRaisesRegex(SourceError, "re-extract with thedig-textures >= 0.2.0"):
                source_tree.load(src)
        with self.subTest("unreadable image"):
            (self.src / "la1/room001.png").write_bytes(b"not a png")
            with self.assertRaisesRegex(SourceError, "not a readable image"):
                source_tree.load(self.src)
        with self.subTest("no manifest"):
            with self.assertRaisesRegex(SourceError, "not found"):
                source_tree.load(self.tmp / "nowhere")

    def test_selection(self):
        source = source_tree.load(self.src)
        self.assertEqual([r.number for r in source_tree.select(source, [3, 1, 3])], [1, 3])
        self.assertEqual(len(source_tree.select(source, None)), 4)
        with self.assertRaisesRegex(SourceError, "room 9"):
            source_tree.select(source, [9])
        self.assertEqual([o.key for o in source_tree.objects_of(source, [2, 4])],
                         ["obj012_01", "obj014_01"])
        self.assertEqual([o.key for o in source_tree.select_objects(source, ["obj014_01"])],
                         ["obj014_01"])
        with self.assertRaisesRegex(SourceError, "obj999_01"):
            source_tree.select_objects(source, ["obj999_01"])

    def test_images_and_colour_keys(self):
        source = source_tree.load(self.src)
        room = source_tree.open_rgba(self.src, source.rooms[0])
        self.assertEqual((room.mode, room.size), ("RGBA", (320, 144)))
        keys = source_tree.colour_keys(room)
        r, g, b = testkit.PALETTE[int(testkit.room_pixels(testkit.DEFAULT_ROOMS[0])[0, 0])]
        self.assertEqual(int(keys[0, 0]), (r << 16) | (g << 8) | b)
        sprite = source_tree.open_rgba(self.src, source.objects[2])
        sprite_keys = source_tree.colour_keys(sprite)
        self.assertTrue((sprite_keys[:2] == source_tree.TRANSPARENT_KEY).all())
        self.assertFalse((sprite_keys[2:-2, 2:-2] == source_tree.TRANSPARENT_KEY).any())


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_the_real_manifest(self):
        source = source_tree.load(testkit.REAL_SRC)
        self.assertEqual((len(source.rooms), len(source.objects)), (111, 642))
        rooms = {r.number: r for r in source.rooms}
        self.assertEqual((rooms[27].width, rooms[27].height), (512, 780))
        self.assertEqual({r.number for r in source.rooms if r.has_alpha}, {32, 34, 85, 88, 107})


if __name__ == "__main__":
    unittest.main()
