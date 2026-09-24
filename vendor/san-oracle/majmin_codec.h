// Shared shim for ScummVM's MajMinCodec (upstream engines/scumm/gfx.h:633).
//
// The class body is byte-for-byte the upstream declaration; only the methods
// are defined elsewhere (transcribed verbatim from gfx.cpp into la1_core.cpp).
// Both the LA1 SMAP decoder and the AKOS costume cel decoder need the same
// class, so the definition lives here instead of being duplicated per TU.
#pragma once
#include "shim.h"

namespace Scumm {

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

} // End of namespace Scumm
