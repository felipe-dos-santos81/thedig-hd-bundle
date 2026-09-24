// Oracle harness for The Dig's SAN/SMUSH path.
//
// Transcribes ONLY the Dig decode path from the vendored
// upstream/engines/scumm/smush/smush_player.cpp (container walk, AHDR/NPAL/XPAL
// palette handling, FOBJ 14-byte header + decodeFrameObject guards), and links
// the vendored codec37.cpp verbatim as the pixel decoder.
//
// `san-oracle dump FILE` writes one record per FRME, in file order:
//   b"FRMK" + u16LE(w) + u16LE(h) + pal[768] + index[w*h]
// Exit 2 + stderr message on a malformed stream.

#include "shim.h"
#include "scumm/smush/codec37.h"

namespace {

const int kWidth = 320;
const int kHeight = 200;
const uint32 kCodecDeltaBlocks = 37; // SMUSH_CODEC_DELTA_BLOCKS

uint8 g_pal[768];
int16 g_deltaPal[768];
int32 g_shiftedDeltaPal[768];
uint8 g_buf[kWidth * kHeight];
Scumm::SmushDeltaBlocksDecoder *g_decoder = nullptr;

// handleNewPalette (smush_player.cpp:845): 768 palette bytes.
void handleNewPalette(const uint8 *payload, uint32 size) {
	if (size < 0x300)
		error("NPAL payload too small: %u", size);
	memcpy(g_pal, payload, 0x300);
}

// handleDeltaPalette (smush_player.cpp:815) line-for-line.
void handleDeltaPalette(const uint8 *payload, uint32 size) {
	(void)size;
	uint16 xpalCommand = READ_LE_UINT16(payload + 2);
	if (xpalCommand == 256) {
		for (int i = 0; i < 768; ++i) {
			g_shiftedDeltaPal[i] += g_deltaPal[i];
			g_pal[i] = (uint8)CLIP(g_shiftedDeltaPal[i] >> 7, 0, 255);
		}
	} else {
		for (int j = 0; j < 768; ++j) {
			g_shiftedDeltaPal[j] = g_pal[j] << 7;
			g_deltaPal[j] = (int16)READ_LE_UINT16(payload + 4 + 2 * j);
		}
		if (xpalCommand == 512)
			memcpy(g_pal, payload + 4 + 1536, 0x300);
	}
}

// decodeFrameObject (smush_player.cpp:865) with the Dig configuration:
// _insanity == false, screen 320x200, and all game hooks base-class no-ops.
void decodeFrameObject(uint16 codec, const uint8 *src, int width, int height) {
	if (height > kHeight || width > kWidth)
		return;
	if (height != kHeight || width != kWidth)
		return;

	switch (codec) {
	case kCodecDeltaBlocks:
		if (!g_decoder)
			g_decoder = new Scumm::SmushDeltaBlocksDecoder(kWidth, kHeight);
		g_decoder->decode(g_buf, src);
		break;
	default:
		error("Invalid codec for frame object : %d", codec);
	}
}

// handleFrameObject (smush_player.cpp:996): 14-byte LE header, then codec data.
void handleFrameObject(const uint8 *payload, uint32 size) {
	if (size < 14)
		error("FOBJ payload too small: %u", size);
	uint16 codec = READ_LE_UINT16(payload + 0);
	int width = READ_LE_UINT16(payload + 6);
	int height = READ_LE_UINT16(payload + 8);
	decodeFrameObject(codec, payload + 14, width, height);
}

// handleFrame (smush_player.cpp:1030): sub-chunks of the FRME payload.
// NPAL/XPAL/FOBJ are handled; IACT/TRES/PSAD/TEXT/STOR/FTCH/SKIP/LOAD/GOST
// are audio/script only and have no back-buffer effect; unknown -> ignore.
void handleFrame(const uint8 *frame, uint32 size) {
	int64_t remaining = (int64_t)size;
	uint32 p = 0;
	while (remaining > 0) {
		if (remaining < 8)
			break;
		uint32 subSize = READ_BE_UINT32(frame + p + 4);
		const uint8 *payload = frame + p + 8;
		if (memcmp(frame + p, "NPAL", 4) == 0)
			handleNewPalette(payload, subSize);
		else if (memcmp(frame + p, "XPAL", 4) == 0)
			handleDeltaPalette(payload, subSize);
		else if (memcmp(frame + p, "FOBJ", 4) == 0)
			handleFrameObject(payload, subSize);
		remaining -= (int64_t)subSize + 8;
		p += subSize + 8;
		if (subSize & 1) {
			++p;
			--remaining;
		}
	}
}

void emitFrame() {
	fwrite("FRMK", 1, 4, stdout);
	uint8 dims[4];
	dims[0] = (uint8)(kWidth & 0xff);
	dims[1] = (uint8)((kWidth >> 8) & 0xff);
	dims[2] = (uint8)(kHeight & 0xff);
	dims[3] = (uint8)((kHeight >> 8) & 0xff);
	fwrite(dims, 1, 4, stdout);
	fwrite(g_pal, 1, 768, stdout);
	fwrite(g_buf, 1, kWidth * kHeight, stdout);
}

} // namespace

int main(int argc, char **argv) {
	if (argc != 3 || strcmp(argv[1], "dump") != 0) {
		fprintf(stderr, "usage: san-oracle dump FILE\n");
		return 2;
	}

	FILE *f = fopen(argv[2], "rb");
	if (!f)
		error("cannot open %s", argv[2]);
	if (fseek(f, 0, SEEK_END) != 0)
		error("cannot seek %s", argv[2]);
	long n = ftell(f);
	if (n < 8)
		error("file too small: %ld bytes", n);
	rewind(f);
	uint8 *data = (uint8 *)malloc((size_t)n);
	if (!data)
		error("out of memory");
	if (fread(data, 1, (size_t)n, f) != (size_t)n)
		error("short read on %s", argv[2]);
	fclose(f);

	if (memcmp(data, "ANIM", 4) != 0)
		error("missing ANIM magic in %s", argv[2]);

	long off = 8;
	while (off + 8 <= n) {
		const uint8 *tag = data + off;
		uint32 size = READ_BE_UINT32(data + off + 4);
		if (off + 8 + (long)size > n)
			error("chunk %c%c%c%c size %u overruns file", tag[0], tag[1], tag[2], tag[3], size);
		const uint8 *payload = data + off + 8;
		if (memcmp(tag, "AHDR", 4) == 0) {
			if (size < 0x306)
				error("AHDR payload too small: %u", size);
			memcpy(g_pal, payload + 6, 0x300);
		} else if (memcmp(tag, "FRME", 4) == 0) {
			handleFrame(payload, size);
			emitFrame();
		} else {
			error("unknown top-level chunk %c%c%c%c", tag[0], tag[1], tag[2], tag[3]);
		}
		off += 8 + (long)size + (size & 1);
	}

	free(data);
	delete g_decoder;
	return 0;
}
