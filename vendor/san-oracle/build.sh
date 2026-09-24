#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# BOMP decode primitives as a standalone TU: verbatim upstream bodies, wrapped
# in the namespace its own header declares them in (scumm/bomp.h: namespace
# Scumm). bompDecodeLine serves the LA1 BOMP object images and the AKOS CDAT
# costume cels; decompressBomp is the full BOMP bitmap decode; bompApplyMask /
# bompApplyShadow are the (no-op under a zero mask, shadow mode 0) pixel commit
# used by the AKOS MajMin cel decoder. Helpers are emitted before the dispatcher
# that calls them so no forward declarations are needed.
{
  printf '#include "shim.h"\n'
  printf '#include "scumm/bomp.h"\n'
  printf 'namespace Scumm {\n'
  awk '/^void bompDecodeLine\(byte \*dst, const byte \*src, int len, bool setZero\)/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void decompressBomp\(byte \*dst, const byte \*src, int w, int h\)/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void bompApplyMask\(byte \*line_buffer, byte \*mask, byte maskbit, int32 size, byte transparency\)/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void bompApplyShadow0\(/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void bompApplyShadow1\(/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void bompApplyShadow3\(/,/^}/' upstream/engines/scumm/bomp.cpp
  awk '/^void bompApplyShadow\(int shadowMode, const byte \*shadowPalette, const byte \*line_buffer, byte \*dst, int32 size, byte transparency, bool HE7Check\)/,/^}/' upstream/engines/scumm/bomp.cpp
  printf '} // namespace Scumm\n'
} > bomp_core.cpp
grep -q 'setZero' bomp_core.cpp || { echo "bomp extraction failed" >&2; exit 1; }
grep -q 'decompressBomp' bomp_core.cpp || { echo "bomp decompressBomp extraction failed" >&2; exit 1; }
grep -q 'bompApplyShadow3' bomp_core.cpp || { echo "bomp shadow extraction failed" >&2; exit 1; }
# NutRenderer::codec21 body (verbatim statements) wrapped in a free function.
# The body is lines 66-93 of nut_renderer.cpp; only the signature differs.
{
  printf '#include "shim.h"\n'
  printf 'void nut_codec21(byte *dst, const byte *src, int width, int height, int pitch) {\n'
  sed -n '/^void NutRenderer::codec21(/,/^}/p' upstream/engines/scumm/nut_renderer.cpp | sed '1d;$d'
  printf '}\n'
} > nut_core.cpp
grep -q 'dstPtrNext' nut_core.cpp || { echo "codec21 extraction failed" >&2; exit 1; }
# LA1 SMAP core: the Gdi::decompressBitmap dispatcher, its required strip
# decoders, writeRoomColor and the MajMinCodec helper, extracted verbatim from
# the vendored gfx.cpp and wrapped in the minimal Gdi/MajMinCodec shims that
# supply the members and engine constants the bodies reference. The Dig is
# SCUMM v7 VGA: features==0, platform!=Amiga, version==7, bytesPerPixel==1,
# _roomPalette is the identity map (scumm.cpp:2081) and _paletteMod==0.
{
  cat <<'LA1_PREAMBLE'
#include "shim.h"
#include "majmin_codec.h"
typedef unsigned int uint;
namespace Common { enum { kPlatformAmiga = 42 }; }
#define GF_16COLOR (1 << 4)
#define GF_OLD256 (1 << 0)
/* gfx.h BMCOMP_* codec ids referenced by decompressBitmap (verbatim values). */
#define BMCOMP_RAW256           1
#define BMCOMP_TOWNS_2          2
#define BMCOMP_TOWNS_3          3
#define BMCOMP_TOWNS_4          4
#define BMCOMP_TOWNS_7          7
#define BMCOMP_TRLE8BIT         8
#define BMCOMP_RLE8BIT          9
#define BMCOMP_PIX32            10
#define BMCOMP_ZIGZAG_V4        14
#define BMCOMP_ZIGZAG_V5        15
#define BMCOMP_ZIGZAG_V6        16
#define BMCOMP_ZIGZAG_V7        17
#define BMCOMP_ZIGZAG_V8        18
#define BMCOMP_ZIGZAG_H4        24
#define BMCOMP_ZIGZAG_H5        25
#define BMCOMP_ZIGZAG_H6        26
#define BMCOMP_ZIGZAG_H7        27
#define BMCOMP_ZIGZAG_H8        28
#define BMCOMP_ZIGZAG_VT4       34
#define BMCOMP_ZIGZAG_VT5       35
#define BMCOMP_ZIGZAG_VT6       36
#define BMCOMP_ZIGZAG_VT7       37
#define BMCOMP_ZIGZAG_VT8       38
#define BMCOMP_ZIGZAG_HT4       44
#define BMCOMP_ZIGZAG_HT5       45
#define BMCOMP_ZIGZAG_HT6       46
#define BMCOMP_ZIGZAG_HT7       47
#define BMCOMP_ZIGZAG_HT8       48
#define BMCOMP_MAJMIN_H4        64
#define BMCOMP_MAJMIN_H5        65
#define BMCOMP_MAJMIN_H6        66
#define BMCOMP_MAJMIN_H7        67
#define BMCOMP_MAJMIN_H8        68
#define BMCOMP_MAJMIN_HT4       84
#define BMCOMP_MAJMIN_HT5       85
#define BMCOMP_MAJMIN_HT6       86
#define BMCOMP_MAJMIN_HT7       87
#define BMCOMP_MAJMIN_HT8       88
#define BMCOMP_RMAJMIN_H4       104
#define BMCOMP_RMAJMIN_H5       105
#define BMCOMP_RMAJMIN_H6       106
#define BMCOMP_RMAJMIN_H7       107
#define BMCOMP_RMAJMIN_H8       108
#define BMCOMP_RMAJMIN_HT4      124
#define BMCOMP_RMAJMIN_HT5      125
#define BMCOMP_RMAJMIN_HT6      126
#define BMCOMP_RMAJMIN_HT7      127
#define BMCOMP_RMAJMIN_HT8      128
#define BMCOMP_NMAJMIN_H4       134
#define BMCOMP_NMAJMIN_H5       135
#define BMCOMP_NMAJMIN_H6       136
#define BMCOMP_NMAJMIN_H7       137
#define BMCOMP_NMAJMIN_H8       138
#define BMCOMP_CUSTOM_RU_TR     143
#define BMCOMP_NMAJMIN_HT4      144
#define BMCOMP_NMAJMIN_HT5      145
#define BMCOMP_NMAJMIN_HT6      146
#define BMCOMP_NMAJMIN_HT7      147
#define BMCOMP_NMAJMIN_HT8      148
#define BMCOMP_TPIX256          149
namespace Scumm {
struct La1GameShim { uint32 features; int platform; int version; };
struct La1EngineShim { int _bytesPerPixel; La1GameShim _game; };

static byte g_la1RoomPalette[256];
static La1EngineShim g_la1Engine;

class Gdi {
public:
	La1EngineShim *_vm;
	byte _paletteMod;
	byte *_roomPalette;
	byte _transparentColor;
	byte _decomp_shr, _decomp_mask;
	uint32 _vertStripNextInc;

	Gdi();

	bool decompressBitmap(byte *dst, int dstPitch, const byte *src, int numLinesToProcess);

	/* Codecs outside the census set: never reached for DIG.LA1, error if hit. */
	void drawStripEGA(byte *, int, const byte *, int) const { error("la1: drawStripEGA not transcribed"); }
	void unkDecode8(byte *, int, const byte *, int) const { error("la1: unkDecode8 not transcribed"); }
	void unkDecode9(byte *, int, const byte *, int) const { error("la1: unkDecode9 not transcribed"); }
	void unkDecode10(byte *, int, const byte *, int) const { error("la1: unkDecode10 not transcribed"); }
	void unkDecode11(byte *, int, const byte *, int) const { error("la1: unkDecode11 not transcribed"); }
	void drawStrip3DO(byte *, int, const byte *, int, const bool) const { error("la1: drawStrip3DO not transcribed"); }
	void drawStripHE(byte *, int, const byte *, int, int, const bool) const { error("la1: drawStripHE not transcribed"); }

	void drawStripComplex(byte *dst, int dstPitch, const byte *src, int height, const bool transpCheck) const;
	void drawStripBasicH(byte *dst, int dstPitch, const byte *src, int height, const bool transpCheck) const;
	void drawStripBasicV(byte *dst, int dstPitch, const byte *src, int height, const bool transpCheck) const;
	void drawStripRaw(byte *dst, int dstPitch, const byte *src, int height, const bool transpCheck) const;

	void writeRoomColor(byte *dst, byte color) const;
};

Gdi::Gdi() : _vm(&g_la1Engine), _paletteMod(0), _roomPalette(g_la1RoomPalette),
             _transparentColor(255), _decomp_shr(0), _decomp_mask(0), _vertStripNextInc(0) {
	_vm->_bytesPerPixel = 1;
	_vm->_game.features = 0;
	_vm->_game.platform = 0;
	_vm->_game.version = 7;
	for (int i = 0; i < 256; ++i)
		_roomPalette[i] = (byte)i;
}

#define READ_BIT (cl--, bit = bits & 1, bits >>= 1, bit)
#define FILL_BITS do {              \
		if (cl <= 8) {              \
			bits |= (*src++ << cl); \
			cl += 8;                \
		}                           \
	} while (0)

#define NEXT_ROW                           \
		do {                               \
			dst += dstPitch;               \
			if (--h == 0) {                \
				if (!--x)                  \
					return;                \
				dst -= _vertStripNextInc;  \
				h = height;                \
			}                              \
		} while (0)

#define MAJMIN_FILL_BITS()                                        \
		if (_majMinData.numBits <= 8) {                                \
		  _majMinData.bits |= (*_majMinData.dataPtr++) << _majMinData.numBits;   \
		  _majMinData.numBits += 8;                                    \
		}

#define MAJMIN_EAT_BITS(n)                                        \
		_majMinData.numBits -= (n);                                    \
		_majMinData.bits >>= (n);

LA1_PREAMBLE
  awk '/^bool Gdi::decompressBitmap\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void Gdi::drawStripComplex\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void Gdi::drawStripBasicH\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void Gdi::drawStripBasicV\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void Gdi::drawStripRaw\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void Gdi::writeRoomColor\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void MajMinCodec::setupBitReader\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^byte MajMinCodec::readBits\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void MajMinCodec::skipData\(/,/^}/' upstream/engines/scumm/gfx.cpp
  awk '/^void MajMinCodec::decodeLine\(/,/^}/' upstream/engines/scumm/gfx.cpp
  cat <<'LA1_EPILOG'
} // namespace Scumm

/* Decode one SMAP strip (8 pixels wide, `height` tall) into `dst` with the
   given row pitch. Returns decompressBitmap's transpStrip flag. */
int la1_decompress_strip(byte *dst, int dstPitch, const byte *src, int height, byte transparentColor) {
	Scumm::Gdi gdi;
	gdi._transparentColor = transparentColor;
	gdi._vertStripNextInc = (uint32)(height * dstPitch - 1);
	return gdi.decompressBitmap(dst, dstPitch, src, height) ? 1 : 0;
}

/* True for codecs whose decompressBitmap arm maps to a transcribed strip
   decoder (drawStripRaw / drawStripBasicV / drawStripBasicH /
   drawStripComplex). Everything else must be reported as LA1E. */
int la1_codec_supported(uint8 code) {
	switch (code) {
	case BMCOMP_RAW256:
	case BMCOMP_ZIGZAG_V4: case BMCOMP_ZIGZAG_V5: case BMCOMP_ZIGZAG_V6:
	case BMCOMP_ZIGZAG_V7: case BMCOMP_ZIGZAG_V8:
	case BMCOMP_ZIGZAG_H4: case BMCOMP_ZIGZAG_H5: case BMCOMP_ZIGZAG_H6:
	case BMCOMP_ZIGZAG_H7: case BMCOMP_ZIGZAG_H8:
	case BMCOMP_ZIGZAG_VT4: case BMCOMP_ZIGZAG_VT5: case BMCOMP_ZIGZAG_VT6:
	case BMCOMP_ZIGZAG_VT7: case BMCOMP_ZIGZAG_VT8:
	case BMCOMP_ZIGZAG_HT4: case BMCOMP_ZIGZAG_HT5: case BMCOMP_ZIGZAG_HT6:
	case BMCOMP_ZIGZAG_HT7: case BMCOMP_ZIGZAG_HT8:
	case BMCOMP_MAJMIN_H4: case BMCOMP_MAJMIN_H5: case BMCOMP_MAJMIN_H6:
	case BMCOMP_MAJMIN_H7: case BMCOMP_MAJMIN_H8:
	case BMCOMP_MAJMIN_HT4: case BMCOMP_MAJMIN_HT5: case BMCOMP_MAJMIN_HT6:
	case BMCOMP_MAJMIN_HT7: case BMCOMP_MAJMIN_HT8:
	case BMCOMP_RMAJMIN_H4: case BMCOMP_RMAJMIN_H5: case BMCOMP_RMAJMIN_H6:
	case BMCOMP_RMAJMIN_H7: case BMCOMP_RMAJMIN_H8:
	case BMCOMP_RMAJMIN_HT4: case BMCOMP_RMAJMIN_HT5: case BMCOMP_RMAJMIN_HT6:
	case BMCOMP_RMAJMIN_HT7: case BMCOMP_RMAJMIN_HT8:
		return 1;
	default:
		return 0;
	}
}
LA1_EPILOG
} > la1_core.cpp
grep -q 'la1_decompress_strip' la1_core.cpp || { echo "la1 extraction failed" >&2; exit 1; }
grep -q 'MajMinCodec::decodeLine' la1_core.cpp || { echo "la1 MajMinCodec extraction failed" >&2; exit 1; }
# AKOS costume cel decode: the pixel decoders only (the renderer's drawing,
# clipping, palette and shadow application are not transcribed). The Byle RLE
# body comes from base-costume.cpp, the MajMin body from akos.cpp; both are
# wrapped in the minimal BaseCostumeRenderer/AkosRenderer shims that supply the
# members and engine constants the bodies reference. The Dig is SCUMM v7 VGA:
# heversion 0, features 0, bytesPerPixel 1, and the actor palette is the
# identity map, so the decoded buffers hold the raw costume colour indices.
{
  cat <<'AKOS_PREAMBLE'
#include "shim.h"
#include "majmin_codec.h"
#include "scumm/bomp.h"

namespace Common {
struct Rect { int16 left, top, right, bottom; };
}

namespace Scumm {

/* Engine shim: The Dig is SCUMM v7 VGA (heversion 0, features 0, version 7,
   bytesPerPixel 1). getMaskBuffer hands back a caller-supplied zeroed buffer so
   the cel decoders' mask test is a no-op: only the cel pixels are decoded, not
   the on-screen mask. */
struct AkosGameShim { uint32 features; int heversion; int version; };
struct AkosEngineShim {
	AkosGameShim _game;
	int _bytesPerPixel;
	byte *_maskBuf;
	byte *getMaskBuffer(int x, int y, int z) { (void)x; (void)y; (void)z; return _maskBuf; }
};

static AkosEngineShim g_akosEngine = { { 0, 0, 7 }, 1, nullptr };

/* Destination surface shim: only the members the transcribed decoders touch. */
struct AkosSurface {
	int w, h, pitch;
	byte *base;
	byte *getBasePtr(int x, int y) { return base + (size_t)y * pitch + x; }
};

#define GF_16BIT_COLOR (1 << 0)
#define READ_UINT16(p) READ_LE_UINT16(p)
#define WRITE_UINT16(p, v) do { (p)[0] = (byte)((v) & 0xff); (p)[1] = (byte)(((v) >> 8) & 0xff); } while (0)
#define revBitMask(x) (0x80 >> (x))

class BaseCostumeRenderer {
public:
	struct ByleRLEData {
		int x;
		int y;
		const byte *scaleTable;
		int skipWidth;
		byte *destPtr;
		const byte *maskPtr;
		int scaleXStep;
		byte mask, shr;
		byte repColor;
		byte repLen;
		Common::Rect boundsRect;
		int scaleXIndex, scaleYIndex;
		int scaleIndexMask;
	};

	AkosEngineShim *_vm;
	byte _shadowMode;
	byte *_shadowTable;
	AkosSurface _out;
	int32 _numStrips;
	const byte *_srcPtr;
	bool _drawActorToRight;
	bool _akosRendering;
	int _width, _height;
	int _drawTop, _drawBottom;
	uint16 _palette[256];
	byte _scaleX, _scaleY;

	byte paintCelByleRLECommon(
		int xMoveCur,
		int yMoveCur,
		int numColors,
		int scaletableSize,
		bool amiOrPcEngCost,
		bool c64Cost,
		ByleRLEData &compData,
		bool &decode);

	void byleRLEDecode(ByleRLEData &compData, int16 actorHitX = 0, int16 actorHitY = 0, bool *actorHitResult = nullptr, const uint8 *xmap = nullptr);
	void skipCelLines(ByleRLEData &compData, int num);

	virtual void markAsDirty(const Common::Rect &rect, ByleRLEData &compData, bool &decode) { (void)rect; (void)compData; (void)decode; }
};

class AkosRenderer : public BaseCostumeRenderer {
public:
	void majMinCodecDecompress(byte *dest, int32 pitch, const byte *src, int32 width, int32 height, int32 dir,
		int32 numSkipBefore, int32 numSkipAfter, byte transparency, int maskLeft, int maskTop, int zBuf);
};

/* bigCostumeScaleTable (akos.cpp:499), verbatim. */
AKOS_PREAMBLE
  awk '/^const byte bigCostumeScaleTable\[768\] = \{/,/^\};/' upstream/engines/scumm/akos.cpp
  awk '/^byte BaseCostumeRenderer::paintCelByleRLECommon\(/,/^}/' upstream/engines/scumm/base-costume.cpp
  awk '/^void BaseCostumeRenderer::byleRLEDecode\(/,/^}/' upstream/engines/scumm/base-costume.cpp
  awk '/^void BaseCostumeRenderer::skipCelLines\(/,/^}/' upstream/engines/scumm/base-costume.cpp
  awk '/^void AkosRenderer::majMinCodecDecompress\(/,/^}/' upstream/engines/scumm/akos.cpp
  cat <<'AKOS_EPILOG'
} // namespace Scumm

/* The Dig is v7 VGA: heversion 0, features 0, bytesPerPixel 1. */
static void akos_engine_init(Scumm::AkosEngineShim *vm, byte *maskBuf) {
	vm->_game.features = 0;
	vm->_game.heversion = 0;
	vm->_game.version = 7;
	vm->_bytesPerPixel = 1;
	vm->_maskBuf = maskBuf;
}

/* AKOS_BYLE_RLE_CODEC (1): the cel is a Byle RLE stream. `numColors` is the
   AKPL data size; the cel is decoded unscaled, unmasked, unshadowed and with an
   identity actor palette, so the destination receives the raw colour indices.
   The destination is pre-filled with 0 (the codec's transparent index). */
int akos_decode_byle(byte *dst, int w, int h, const byte *src, int numColors) {
	size_t msz = (size_t)w * h + 64;
	byte *maskBuf = (byte *)calloc(msz, 1);
	if (!maskBuf)
		error("out of memory");
	akos_engine_init(&Scumm::g_akosEngine, maskBuf);

	Scumm::AkosRenderer r;
	r._vm = &Scumm::g_akosEngine;
	r._width = w;
	r._height = h;
	r._out.w = w;
	r._out.h = h;
	r._out.pitch = w;
	r._out.base = dst;
	r._scaleX = 255;
	r._scaleY = 255;
	r._drawActorToRight = true;
	r._akosRendering = true;
	r._srcPtr = src;
	r._drawTop = 0x7fff;
	r._drawBottom = 0;
	r._shadowMode = 0;
	r._shadowTable = nullptr;
	r._numStrips = w;
	for (int i = 0; i < 256; ++i)
		r._palette[i] = (uint16)i;

	Scumm::BaseCostumeRenderer::ByleRLEData compData;
	compData.scaleTable = Scumm::bigCostumeScaleTable;
	compData.x = 0;
	compData.y = 0;
	compData.scaleIndexMask = -1;

	bool decode = true;
	r.paintCelByleRLECommon(0, 0, numColors, 384, false, false, compData, decode);
	if (decode) {
		compData.maskPtr = r._vm->getMaskBuffer(0, 0, 0);
		r.byleRLEDecode(compData, 0, 0, nullptr, nullptr);
	}
	free(maskBuf);
	return decode ? 1 : 0;
}

/* AKOS_CDAT_RLE_CODEC (5): the cel is a BOMP bitmap (upstream
   AkosRenderer::paintCelCDATRLE -> drawBomp at 1:1 with no mask/shadow/palette
   reduces to decompressBomp). The destination is pre-filled with 255 (the
   codec's transparent index). */
int akos_decode_cdat(byte *dst, int w, int h, const byte *src) {
	Scumm::decompressBomp(dst, src, w, h);
	return 1;
}

/* AKOS_RUN_MAJMIN_CODEC (16): the cel is a MajMin stream, decoded by the
   transcribed AkosRenderer::majMinCodecDecompress. The mask is a no-op and
   shadow mode is 0, so the destination receives the raw colour indices; the
   destination is pre-filled with 255 (the codec's transparent index). */
int akos_decode_majmin(byte *dst, int w, int h, const byte *src) {
	size_t msz = (size_t)w * h + 64;
	byte *maskBuf = (byte *)calloc(msz, 1);
	if (!maskBuf)
		error("out of memory");
	akos_engine_init(&Scumm::g_akosEngine, maskBuf);

	Scumm::AkosRenderer r;
	r._vm = &Scumm::g_akosEngine;
	r._numStrips = w;
	r._shadowMode = 0;
	r._shadowTable = nullptr;
	r.majMinCodecDecompress(dst, w, src, w, h, 1, 0, 0, 255, 0, 0, 0);
	free(maskBuf);
	return 1;
}
AKOS_EPILOG
} > akos_core.cpp
grep -q 'bigCostumeScaleTable' akos_core.cpp || { echo "akos scale table extraction failed" >&2; exit 1; }
grep -q 'BaseCostumeRenderer::byleRLEDecode' akos_core.cpp || { echo "akos byle extraction failed" >&2; exit 1; }
grep -q 'AkosRenderer::majMinCodecDecompress' akos_core.cpp || { echo "akos majmin extraction failed" >&2; exit 1; }
# bomp_core.cpp + nut_core.cpp + la1_core.cpp + akos_core.cpp + codec1.cpp +
# codec37.cpp verbatim + oracle_main.cpp
clang++ -O1 -w -std=c++17 -I upstream/engines -I inc -lz \
  -o san-oracle bomp_core.cpp nut_core.cpp la1_core.cpp akos_core.cpp \
  upstream/engines/scumm/smush/codec1.cpp \
  upstream/engines/scumm/smush/codec37.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
