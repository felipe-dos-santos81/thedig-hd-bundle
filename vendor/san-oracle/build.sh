#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# bompDecodeLine as a standalone TU: verbatim upstream body, wrapped in the
# namespace its own header declares it in (scumm/bomp.h: namespace Scumm).
{
  printf '#include "shim.h"\n'
  printf '#include "scumm/bomp.h"\n'
  printf 'namespace Scumm {\n'
  awk '/^void bompDecodeLine\(byte \*dst, const byte \*src, int len, bool setZero\)/,/^}/' upstream/engines/scumm/bomp.cpp
  printf '} // namespace Scumm\n'
} > bomp_core.cpp
grep -q 'setZero' bomp_core.cpp || { echo "bomp extraction failed" >&2; exit 1; }
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

class MajMinCodec {
public:
	struct {
		bool repeatMode;
		int repeatCount;
		byte color;
		byte shift;
		uint16 bits;
		byte numBits;
		const byte *dataPtr;
		byte buffer[336];
	} _majMinData;

	void setupBitReader(byte shift, const byte *src);
	void skipData(int32 numSkip);
	void decodeLine(byte *buf, int32 numBytes, int32 dir);
	inline byte readBits(byte n);
};

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
# bomp_core.cpp + nut_core.cpp + la1_core.cpp + codec1.cpp + codec37.cpp verbatim + oracle_main.cpp
clang++ -O1 -w -std=c++17 -I upstream/engines -I inc -lz \
  -o san-oracle bomp_core.cpp nut_core.cpp la1_core.cpp \
  upstream/engines/scumm/smush/codec1.cpp \
  upstream/engines/scumm/smush/codec37.cpp oracle_main.cpp
echo built: vendor/san-oracle/san-oracle
