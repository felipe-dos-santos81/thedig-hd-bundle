// Oracle harness for The Dig's SAN/SMUSH path.
//
// Transcribes ONLY the Dig decode path from the vendored
// upstream/engines/scumm/smush/smush_player.cpp (container walk, AHDR/NPAL/XPAL
// palette handling, FOBJ 14-byte header + decodeFrameObject guards), and links
// the vendored codec37.cpp verbatim as the pixel decoder.
//
// `san-oracle dump FILE` writes one record per FRME, in file order:
//   b"FRMK" + u16LE(w) + u16LE(h) + pal[768] + index[w*h]
//
// `san-oracle nut FILE` writes one record per NUT glyph, in file order, from
// the vendored nut_renderer.cpp layout (ANIM/AHDR + one FRME/FOBJ per glyph):
//   b"NUTG" + u16LE(w) + u16LE(h) + u8 transparency + pal[768] + index[w*h]
// Codec 1 -> Scumm::smushDecodeRLE (vendored codec1.cpp); codec 44 -> the
// sed-extracted nut_codec21 body. Exit 2 + stderr message on a malformed
// stream or unknown codec.
//
// `san-oracle la1 FILE` writes one record per DIG.LA1 SMAP/BOMP bitmap.
//
// `san-oracle akos FILE` walks the same DIG.LA1 room container and writes one
// record per costume cel, in file order:
//   b"AKOS" + u32LE(costume) + u16LE(cel) + u16LE(w) + u16LE(h) +
//   u8 transparent + index[w*h]
// The costume id is the 1-based file-order ordinal (equal to the DIG.LA0
// rtCostume id). Cels are decoded by the transcribed codecs (1 Byle RLE,
// 5 CDAT/BOMP, 16 MajMin); an unknown codec emits a fixed-size AKOSE record
// (b"AKOSE" + u32LE(costume) + u16LE(cel) + u16LE(codec)) instead of error().

#include "shim.h"
#include "scumm/smush/codec37.h"

namespace Scumm {
void smushDecodeRLE(byte *dst, const byte *src, int left, int top, int width, int height, int pitch);
void bompDecodeLine(byte *dst, const byte *src, int len, bool setZero);
}
void nut_codec21(byte *dst, const byte *src, int width, int height, int pitch);
int la1_decompress_strip(byte *dst, int dstPitch, const byte *src, int height, byte transparentColor);
int la1_codec_supported(uint8 code);
int akos_decode_byle(byte *dst, int w, int h, const byte *src, int numColors);
int akos_decode_cdat(byte *dst, int w, int h, const byte *src);
int akos_decode_majmin(byte *dst, int w, int h, const byte *src);

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

// kDefaultTransparentColor / kSmush44TransparentColor (nut_renderer.h:37-38).
const uint8 kDefaultTransparentColor = 0;
const uint8 kSmush44TransparentColor = 2;

void emitNutGlyph(const uint8 *glyph, int width, int height, uint8 transparency) {
	fwrite("NUTG", 1, 4, stdout);
	uint8 hdr[5];
	hdr[0] = (uint8)(width & 0xff);
	hdr[1] = (uint8)((width >> 8) & 0xff);
	hdr[2] = (uint8)(height & 0xff);
	hdr[3] = (uint8)((height >> 8) & 0xff);
	hdr[4] = transparency;
	fwrite(hdr, 1, 5, stdout);
	fwrite(g_pal, 1, 768, stdout);
	fwrite(glyph, 1, (size_t)width * height, stdout);
}

// NUT font walk: ANIM (u32BE length; payload after the 8-byte header is the
// font data) -> AHDR (palette at payload[6:774]; numChars = u16LE@10) -> one
// FRME per glyph, each containing exactly one FOBJ. No metadata chunk.
void runNut(const uint8 *data, long n, const char *path) {
	if (n < 8 || memcmp(data, "ANIM", 4) != 0)
		error("missing ANIM magic in %s", path);
	uint32 animLen = READ_BE_UINT32(data + 4);
	if ((long)animLen > n - 8)
		error("ANIM length %u overruns file in %s", animLen, path);
	const uint8 *font = data + 8;
	long fontLen = (long)animLen;

	if (fontLen < 8 || memcmp(font, "AHDR", 4) != 0)
		error("missing AHDR chunk in %s", path);
	uint32 ahdrSize = READ_BE_UINT32(font + 4);
	if (ahdrSize < 0x306 || 8 + (long)ahdrSize > fontLen)
		error("bad AHDR chunk in %s", path);
	// AHDR chunk: palette at payload[6:774]; numChars = u16LE@10 (chunk start).
	memcpy(g_pal, font + 8 + 6, 0x300);
	uint32 numChars = READ_LE_UINT16(font + 10);

	long off = 8 + (long)ahdrSize + (ahdrSize & 1);
	for (uint32 i = 0; i < numChars; ++i) {
		if (off + 8 > fontLen)
			error("truncated FRME %u in %s", i, path);
		if (memcmp(font + off, "FRME", 4) != 0)
			error("no FRME chunk %u in %s", i, path);
		uint32 frmeSize = READ_BE_UINT32(font + off + 4);
		long fobj = off + 8;
		if (fobj + 22 > fontLen)
			error("truncated FOBJ %u in %s", i, path);
		if (memcmp(font + fobj, "FOBJ", 4) != 0)
			error("no FOBJ chunk in FRME %u in %s", i, path);

		uint16 codec = READ_LE_UINT16(font + fobj + 8);
		int width = READ_LE_UINT16(font + fobj + 14);
		int height = READ_LE_UINT16(font + fobj + 16);
		const uint8 *glyphData = font + fobj + 22;

		uint8 transparency;
		if (codec == 44)
			transparency = kSmush44TransparentColor;
		else if (codec == 1)
			transparency = kDefaultTransparentColor;
		else
			error("unknown NUT codec %u in %s", codec, path);

		size_t size = (size_t)width * height;
		byte *glyph = (byte *)malloc(size ? size : 1);
		if (!glyph)
			error("out of memory");
		memset(glyph, transparency, size);
		if (codec == 1)
			Scumm::smushDecodeRLE(glyph, glyphData, 0, 0, width, height, width);
		else
			nut_codec21(glyph, glyphData, width, height, width);
		emitNutGlyph(glyph, width, height, transparency);
		free(glyph);

		off += 8 + (long)frmeSize + (frmeSize & 1);
	}
}

// dump mode: container walk (ANIM + tag + u32BE size, stride +8+size+(size&1)).
void runDump(const uint8 *data, long n, const char *path) {
	if (memcmp(data, "ANIM", 4) != 0)
		error("missing ANIM magic in %s", path);

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

	delete g_decoder;
	g_decoder = nullptr;
}

// ── LA1 (SCUMM v7 room / object bitmaps) ───────────────────────────────────
//
// Container walk transcribed from room.cpp:readRoomsOffsets /
// setupRoomSubBlocks and object.cpp:getObjectImage. Chunk sizes are
// header-inclusive with NO odd padding: next = chunk_start + size (census
// docs/la1-census.txt). Decoding dispatches to the vendored gfx.cpp decoders
// (la1_core.cpp) and the vendored bompDecodeLine; unknown codecs emit an LA1E
// record instead of error().

bool la1_is_tag(const uint8 *p) {
	for (int i = 0; i < 4; ++i)
		if (p[i] < 0x20 || p[i] > 0x7e)
			return false;
	return true;
}

// findResource (resource.cpp:1599): iterate the children of the chunk at
// `start` (whose header-inclusive size is `start_size`); return the child
// chunk start or nullptr.
const uint8 *la1_find_child(const uint8 *start, uint32 start_size, const char *tag) {
	const uint8 *end = start + start_size;
	const uint8 *c = start + 8;
	while (c + 8 <= end) {
		if (!la1_is_tag(c))
			return nullptr;
		uint32 size = READ_BE_UINT32(c + 4);
		if (size < 8 || c + size > end)
			return nullptr;
		if (memcmp(c, tag, 4) == 0)
			return c;
		c += size;
	}
	return nullptr;
}

// findPalInPals (palette.cpp:1523) at index 0: WRAP -> OFFS, then
// offs + READ_LE_UINT32(offs) = the active APAL payload (768 bytes).
const uint8 *la1_room_palette(const uint8 *pals) {
	const uint8 *wrap = la1_find_child(pals, READ_BE_UINT32(pals + 4), "WRAP");
	if (!wrap)
		return nullptr;
	const uint8 *offs = la1_find_child(wrap, READ_BE_UINT32(wrap + 4), "OFFS");
	if (!offs)
		return nullptr;
	const uint8 *offsPayload = offs + 8;
	return offsPayload + READ_LE_UINT32(offsPayload);
}

void emitLa1Bitmap(int w, int h, uint8 transparent, const uint8 *pal, const uint8 *idx) {
	fwrite("LA1B", 1, 4, stdout);
	uint8 hdr[5];
	hdr[0] = (uint8)(w & 0xff);
	hdr[1] = (uint8)((w >> 8) & 0xff);
	hdr[2] = (uint8)(h & 0xff);
	hdr[3] = (uint8)((h >> 8) & 0xff);
	hdr[4] = transparent;
	fwrite(hdr, 1, 5, stdout);
	fwrite(pal, 1, 768, stdout);
	fwrite(idx, 1, (size_t)w * h, stdout);
}

void emitLa1Error(uint32 off, const char *reason) {
	fwrite("LA1E", 1, 4, stdout);
	uint8 b[4];
	b[0] = (uint8)(off & 0xff);
	b[1] = (uint8)((off >> 8) & 0xff);
	b[2] = (uint8)((off >> 16) & 0xff);
	b[3] = (uint8)((off >> 24) & 0xff);
	fwrite(b, 1, 4, stdout);
	fwrite(reason, 1, strlen(reason), stdout);
}

// Codecs whose decompressBitmap arm maps to a transcribed strip decoder are
// reported by la1_codec_supported() (la1_core.cpp); everything else becomes an
// LA1E record via the callers below.

// Decode one SMAP image (gfx.cpp:drawStrip v7 branch + decompressBitmap).
// `smap` is the SMAP chunk start; `resOff` is the owning IMxx/IM00 chunk
// offset, used for LA1E records.
void la1_decode_smap(const uint8 *smap, int w, int h, const uint8 *pal,
					 uint8 transparentColor, uint32 resOff) {
	uint32 smaplen = READ_BE_UINT32(smap + 4);
	int numstrips = w / 8;
	size_t npix = (size_t)w * h;
	uint8 *buf = (uint8 *)malloc(npix ? npix : 1);
	if (!buf)
		error("out of memory");
	memset(buf, 0, npix);

	bool transp = false;
	for (int s = 0; s < numstrips; ++s) {
		// drawStrip: offset = READ_LE_UINT32(smap_ptr + stripnr*4 + 8)
		if ((uint32)(s * 4 + 8) >= smaplen) {
			emitLa1Error(resOff, "SMAP strip table overrun");
			free(buf);
			return;
		}
		uint32 off = READ_LE_UINT32(smap + s * 4 + 8);
		if (off >= smaplen) {
			emitLa1Error(resOff, "SMAP strip offset out of range");
			free(buf);
			return;
		}
		uint8 code = smap[off];
		if (!la1_codec_supported(code)) {
			emitLa1Error(resOff, "unsupported SMAP codec");
			free(buf);
			return;
		}
		if (la1_decompress_strip(buf + (size_t)s * 8, w, smap + off, h, transparentColor))
			transp = true;
	}
	emitLa1Bitmap(w, h, transp ? 1 : 0, pal, buf);
	free(buf);
}

// Decode one BOMP image (object.cpp:drawBlastObject v7 path + decompressBomp).
// `bomp` is the IMxx payload, i.e. the BOMP chunk start.
void la1_decode_bomp(const uint8 *bomp, int w, int h, const uint8 *pal, uint32 resOff) {
	const uint8 *data = bomp + 8; // BOMP payload ("skip the bomp header")
	int bw = READ_LE_UINT16(data + 2);
	int bh = READ_LE_UINT16(data + 4);
	if (bw != w || bh != h) {
		emitLa1Error(resOff, "BOMP dimensions disagree with IMHD");
		return;
	}
	size_t npix = (size_t)w * h;
	uint8 *buf = (uint8 *)malloc(npix ? npix : 1);
	if (!buf)
		error("out of memory");
	memset(buf, 0, npix);
	const uint8 *src = data + 10;
	for (int y = 0; y < bh; ++y) {
		Scumm::bompDecodeLine(buf + (size_t)y * w, src + 2, bw, true);
		src += READ_LE_UINT16(src) + 2;
	}
	emitLa1Bitmap(w, h, 0, pal, buf);
	free(buf);
}

void la1_process_room(const uint8 *data, uint32 roomOff) {
	const uint8 *room = data + roomOff;
	uint32 roomSize = READ_BE_UINT32(room + 4);
	const uint8 *roomEnd = room + roomSize;

	const uint8 *rmhd = la1_find_child(room, roomSize, "RMHD");
	int rw = 0, rh = 0;
	if (rmhd) {
		rw = READ_LE_UINT16(rmhd + 8 + 4);
		rh = READ_LE_UINT16(rmhd + 8 + 6);
	}

	const uint8 *trns = la1_find_child(room, roomSize, "TRNS");
	uint8 transparentColor = trns ? trns[8] : 255;

	uint8 palBuf[768];
	const uint8 *pals = la1_find_child(room, roomSize, "PALS");
	const uint8 *pal = pals ? la1_room_palette(pals) : nullptr;
	if (!pal) {
		memset(palBuf, 0, sizeof(palBuf));
		pal = palBuf;
	} else {
		memcpy(palBuf, pal, sizeof(palBuf));
		pal = palBuf;
	}

	const uint8 *c = room + 8;
	while (c + 8 <= roomEnd) {
		if (!la1_is_tag(c))
			break;
		uint32 size = READ_BE_UINT32(c + 4);
		if (size < 8 || c + size > roomEnd)
			break;

		if (memcmp(c, "RMIM", 4) == 0) {
			const uint8 *im00 = la1_find_child(c, size, "IM00");
			if (im00) {
				const uint8 *smap = la1_find_child(im00, READ_BE_UINT32(im00 + 4), "SMAP");
				if (smap)
					la1_decode_smap(smap, rw, rh, pal, transparentColor, (uint32)(im00 - data));
			}
		} else if (memcmp(c, "OBIM", 4) == 0) {
			const uint8 *imhd = la1_find_child(c, size, "IMHD");
			if (imhd) {
				int ow = READ_LE_UINT16(imhd + 8 + 12);
				int oh = READ_LE_UINT16(imhd + 8 + 14);
				const uint8 *ic = c + 8;
				while (ic + 8 <= c + size) {
					if (!la1_is_tag(ic))
						break;
					uint32 isz = READ_BE_UINT32(ic + 4);
					if (isz < 8 || ic + isz > c + size)
						break;
					if (ic[0] == 'I' && ic[1] == 'M' && ic[2] != 'H') {
						const uint8 *payload = ic + 8;
						if (memcmp(payload, "SMAP", 4) == 0)
							la1_decode_smap(payload, ow, oh, pal, transparentColor, (uint32)(ic - data));
						else if (memcmp(payload, "BOMP", 4) == 0)
							la1_decode_bomp(payload, ow, oh, pal, (uint32)(ic - data));
						else
							emitLa1Error((uint32)(ic - data), "unknown OBIM image container");
					}
					ic += isz;
				}
			}
		}
		c += size;
	}
}

// runLa1: LECF -> LOFF (u8 count, 111 x (u8 room, u32LE offset)) -> LFLF/ROOM.
void runLa1(const uint8 *data, long n, const char *path) {
	if (n < 16 || memcmp(data, "LECF", 4) != 0)
		error("missing LECF magic in %s", path);
	uint32 lecfSize = READ_BE_UINT32(data + 4);
	if ((long)lecfSize > n)
		error("LECF size %u overruns file in %s", lecfSize, path);
	if (memcmp(data + 8, "LOFF", 4) != 0)
		error("missing LOFF chunk in %s", path);

	const uint8 *loff = data + 16;
	uint8 count = loff[0];
	for (int i = 0; i < count; ++i) {
		uint32 roomOff = READ_LE_UINT32(loff + 2 + 5 * i);
		if (roomOff < 8 || roomOff + 8 > (uint32)n)
			error("room %d offset %u out of range in %s", i + 1, roomOff, path);
		if (memcmp(data + roomOff, "ROOM", 4) != 0)
			error("room %d at %u is not ROOM in %s", i + 1, roomOff, path);
		la1_process_room(data, roomOff);
	}
}

// ── AKOS (SCUMM v7 costume cels) ───────────────────────────────────────────
//
// Each room's AKOS chunk is one costume resource whose payload is a chunk list
// (AKHD, AKPL, RGBS, AKSQ, AKCH, AKOF, AKCI, AKCD). The cel tables are read
// exactly as AkosRenderer::setCostume/drawLimb do: AKHD carries celsCount and
// celCompressionCodec; AKOF is an array of { u32 akcd; u16 akci } (6 bytes);
// the cel's width/height are the first two u16 of AKCI at akci; the cel data is
// AKCD + akcd. Only the cel pixel decode is performed (codecs 1 Byle RLE,
// 5 CDAT/BOMP, 16 MajMin); an unknown codec emits an AKOSE record. The costume
// id is the 1-based file-order ordinal, which equals the DIG.LA0 rtCostume id
// (the DCOS table's 331 non-zero entries map one-to-one onto the AKOS chunks in
// this order).

const uint8 kAkosTransparentByle = 0;
const uint8 kAkosTransparentBomp = 255;

void emitAkosCel(uint32 costume, uint16 cel, int w, int h, uint8 transparent, const uint8 *idx) {
	fwrite("AKOS", 1, 4, stdout);
	uint8 hdr[11];
	hdr[0] = (uint8)(costume & 0xff);
	hdr[1] = (uint8)((costume >> 8) & 0xff);
	hdr[2] = (uint8)((costume >> 16) & 0xff);
	hdr[3] = (uint8)((costume >> 24) & 0xff);
	hdr[4] = (uint8)(cel & 0xff);
	hdr[5] = (uint8)((cel >> 8) & 0xff);
	hdr[6] = (uint8)(w & 0xff);
	hdr[7] = (uint8)((w >> 8) & 0xff);
	hdr[8] = (uint8)(h & 0xff);
	hdr[9] = (uint8)((h >> 8) & 0xff);
	hdr[10] = transparent;
	fwrite(hdr, 1, sizeof(hdr), stdout);
	fwrite(idx, 1, (size_t)w * h, stdout);
}

void emitAkosError(uint32 costume, uint16 cel, uint16 codec) {
	fwrite("AKOSE", 1, 5, stdout);
	uint8 b[8];
	b[0] = (uint8)(costume & 0xff);
	b[1] = (uint8)((costume >> 8) & 0xff);
	b[2] = (uint8)((costume >> 16) & 0xff);
	b[3] = (uint8)((costume >> 24) & 0xff);
	b[4] = (uint8)(cel & 0xff);
	b[5] = (uint8)((cel >> 8) & 0xff);
	b[6] = (uint8)(codec & 0xff);
	b[7] = (uint8)((codec >> 8) & 0xff);
	fwrite(b, 1, sizeof(b), stdout);
}

void akos_process_costume(const uint8 *akos, uint32 costume) {
	uint32 akosSize = READ_BE_UINT32(akos + 4);
	const uint8 *akhd = la1_find_child(akos, akosSize, "AKHD");
	const uint8 *akof = la1_find_child(akos, akosSize, "AKOF");
	const uint8 *akci = la1_find_child(akos, akosSize, "AKCI");
	const uint8 *akcd = la1_find_child(akos, akosSize, "AKCD");
	const uint8 *akpl = la1_find_child(akos, akosSize, "AKPL");
	if (!akhd || !akof || !akci || !akcd)
		return;
	uint16 cels = READ_LE_UINT16(akhd + 8 + 6);
	uint16 codec = READ_LE_UINT16(akhd + 8 + 8);
	int numColors = akpl ? (int)READ_BE_UINT32(akpl + 4) - 8 : 0;

	for (uint16 i = 0; i < cels; ++i) {
		uint32 akcdOff = READ_LE_UINT32(akof + 8 + 6 * i);
		uint16 akciOff = READ_LE_UINT16(akof + 8 + 6 * i + 4);
		int w = READ_LE_UINT16(akci + 8 + akciOff);
		int h = READ_LE_UINT16(akci + 8 + akciOff + 2);
		if (w <= 0 || h <= 0 || (codec != 1 && codec != 5 && codec != 16)) {
			emitAkosError(costume, i, codec);
			continue;
		}
		size_t np = (size_t)w * h;
		uint8 *idx = (uint8 *)malloc(np);
		if (!idx)
			error("out of memory");
		uint8 transparent = (codec == 1) ? kAkosTransparentByle : kAkosTransparentBomp;
		memset(idx, transparent, np);
		const uint8 *src = akcd + 8 + akcdOff;
		if (codec == 1)
			akos_decode_byle(idx, w, h, src, numColors);
		else if (codec == 5)
			akos_decode_cdat(idx, w, h, src);
		else
			akos_decode_majmin(idx, w, h, src);
		emitAkosCel(costume, i, w, h, transparent, idx);
		free(idx);
	}
}

void akos_process_room(const uint8 *data, uint32 roomOff, uint32 &costume) {
	const uint8 *room = data + roomOff;
	uint32 lflfOff = roomOff - 8;
	const uint8 *lflfEnd = data + lflfOff + READ_BE_UINT32(data + lflfOff + 4);
	const uint8 *c = room + 8;
	while (c + 8 <= lflfEnd) {
		if (!la1_is_tag(c))
			break;
		uint32 size = READ_BE_UINT32(c + 4);
		if (size < 8 || c + size > lflfEnd)
			break;
		if (memcmp(c, "AKOS", 4) == 0) {
			++costume;
			akos_process_costume(c, costume);
		}
		c += size;
	}
}

// runAkos: same LECF -> LOFF -> ROOM walk as runLa1; the costume ordinal is the
// 1-based count of AKOS chunks in file order.
//
// The walk starts at the ROOM payload (ROOM + 8) and runs to the end of the
// enclosing LFLF, exactly as the census does: ROOM's payload and the room's
// other resources (SCRP/SOUN/AKOS, addressed by room-relative offsets) are
// contiguous, so the two form one flat chunk list. AKOS lives after the ROOM
// chunk (it is a room resource, not a ROOM child), which is why this walk uses
// the LFLF bound rather than ROOM's own size.
void runAkos(const uint8 *data, long n, const char *path) {
	if (n < 16 || memcmp(data, "LECF", 4) != 0)
		error("missing LECF magic in %s", path);
	uint32 lecfSize = READ_BE_UINT32(data + 4);
	if ((long)lecfSize > n)
		error("LECF size %u overruns file in %s", lecfSize, path);
	if (memcmp(data + 8, "LOFF", 4) != 0)
		error("missing LOFF chunk in %s", path);

	const uint8 *loff = data + 16;
	uint8 count = loff[0];
	uint32 costume = 0;
	for (int i = 0; i < count; ++i) {
		uint32 roomOff = READ_LE_UINT32(loff + 2 + 5 * i);
		if (roomOff < 8 || roomOff + 8 > (uint32)n)
			error("room %d offset %u out of range in %s", i + 1, roomOff, path);
		if (memcmp(data + roomOff, "ROOM", 4) != 0)
			error("room %d at %u is not ROOM in %s", i + 1, roomOff, path);
		akos_process_room(data, roomOff, costume);
	}
}

} // namespace

int main(int argc, char **argv) {
	if (argc != 3 || (strcmp(argv[1], "dump") != 0 && strcmp(argv[1], "nut") != 0 &&
					  strcmp(argv[1], "la1") != 0 && strcmp(argv[1], "akos") != 0)) {
		fprintf(stderr, "usage: san-oracle {dump|nut|la1|akos} FILE\n");
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

	if (strcmp(argv[1], "dump") == 0)
		runDump(data, n, argv[2]);
	else if (strcmp(argv[1], "nut") == 0)
		runNut(data, n, argv[2]);
	else if (strcmp(argv[1], "la1") == 0)
		runLa1(data, n, argv[2]);
	else
		runAkos(data, n, argv[2]);

	free(data);
	return 0;
}
