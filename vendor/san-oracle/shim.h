#pragma once
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
typedef uint8_t byte; typedef int8_t int8; typedef uint8_t uint8;
typedef int16_t int16; typedef uint16_t uint16; typedef int32_t int32; typedef uint32_t uint32;
#define READ_LE_UINT16(p) ((uint16_t)(p)[0] | ((uint16_t)(p)[1] << 8))
#define READ_LE_UINT32(p) ((uint32_t)(p)[0] | ((uint32_t)(p)[1] << 8) | ((uint32_t)(p)[2] << 16) | ((uint32_t)(p)[3] << 24))
#define READ_BE_UINT32(p) (((uint32_t)(p)[0] << 24) | ((uint32_t)(p)[1] << 16) | ((uint32_t)(p)[2] << 8) | (uint32_t)(p)[3])
#define CLIP(v, lo, hi) ((v) < (lo) ? (lo) : ((v) > (hi) ? (hi) : (v)))
#define error(...) do { fprintf(stderr, "oracle: " __VA_ARGS__); fputc('\n', stderr); exit(2); } while (0)
