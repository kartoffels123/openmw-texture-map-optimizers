"""
Lightweight DDS header parser for fast analysis.
Extracted from Kaitai Struct DDS specification (dds.ksy) - no external dependencies.
Only reads the header (first ~148 bytes) for width, height, and format.

Supported formats:
- Legacy FourCC: DXT1/DXT3/DXT5, ATI1/ATI2, BC4U/BC4S/BC5U
- DX10 extended header: All DXGI formats (BC1-BC7, RGBA, float formats, etc.)
- Uncompressed 32-bit: BGRA, BGRX
- Uncompressed 24-bit: BGR
- Uncompressed 16-bit: B5G6R5 (RGB565), B5G5R5A1, B4G4R4A4
- ~100x faster than spawning texdiag subprocess
"""

import struct
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# =============================================================================
# Parser Statistics (for tracking fast parser vs fallback usage)
# =============================================================================
_fast_parser_hits = 0
_texdiag_fallbacks = 0


def get_parser_stats() -> Tuple[int, int]:
    """Get parser statistics.

    Returns:
        (fast_parser_hits, texdiag_fallbacks)
    """
    return _fast_parser_hits, _texdiag_fallbacks


def reset_parser_stats():
    """Reset parser statistics to zero."""
    global _fast_parser_hits, _texdiag_fallbacks
    _fast_parser_hits = 0
    _texdiag_fallbacks = 0


def _increment_fast_parser_hits():
    """Increment the fast parser hit counter."""
    global _fast_parser_hits
    _fast_parser_hits += 1


def _increment_texdiag_fallbacks():
    """Increment the texdiag fallback counter."""
    global _texdiag_fallbacks
    _texdiag_fallbacks += 1


# FourCC codes for pixel formats (from dds.ksy pixel_formats enum)
FOURCC_NONE = 0x00000000
FOURCC_DXT1 = 0x31545844  # 'DXT1'
FOURCC_DXT3 = 0x33545844  # 'DXT3'
FOURCC_DXT5 = 0x35545844  # 'DXT5'
FOURCC_DX10 = 0x30315844  # 'DX10'
FOURCC_BC5U = 0x55354342  # 'BC5U'
FOURCC_ATI2 = 0x32495441  # 'ATI2' (alternative BC5 encoding)

# Additional common FourCC codes
FOURCC_BC4U = 0x55344342  # 'BC4U'
FOURCC_BC4S = 0x53344342  # 'BC4S'
FOURCC_ATI1 = 0x31495441  # 'ATI1' (alternative BC4 encoding)

# Pixel format flags (from dds.ksy format_flags enum)
DDPF_ALPHAPIXELS = 0x000001
DDPF_ALPHA = 0x000002
DDPF_FOURCC = 0x000004
DDPF_RGB = 0x000040
DDPF_YUV = 0x000200
DDPF_LUMINANCE = 0x020000

# DXGI format codes (from dds.ksy dxgi_formats enum)
# Comprehensive list matching texdiag output format names
DXGI_FORMAT_NAMES = {
    0: 'UNKNOWN',
    1: 'R32G32B32A32_TYPELESS',
    2: 'R32G32B32A32_FLOAT',
    3: 'R32G32B32A32_UINT',
    4: 'R32G32B32A32_SINT',
    10: 'R16G16B16A16_FLOAT',
    11: 'R16G16B16A16_UNORM',
    13: 'R16G16B16A16_SNORM',
    16: 'R32G32_FLOAT',
    28: 'R8G8B8A8_UNORM',
    29: 'R8G8B8A8_UNORM_SRGB',
    31: 'R8G8B8A8_SNORM',
    35: 'R16G16_UNORM',
    37: 'R16G16_SNORM',
    41: 'R32_FLOAT',
    49: 'R8G8_UNORM',
    51: 'R8G8_SNORM',
    56: 'R16_UNORM',
    61: 'R8_UNORM',
    65: 'A8_UNORM',
    70: 'BC1_TYPELESS',
    71: 'BC1_UNORM',       # DXT1
    72: 'BC1_UNORM_SRGB',
    73: 'BC2_TYPELESS',
    74: 'BC2_UNORM',       # DXT3
    75: 'BC2_UNORM_SRGB',
    76: 'BC3_TYPELESS',
    77: 'BC3_UNORM',       # DXT5
    78: 'BC3_UNORM_SRGB',
    79: 'BC4_TYPELESS',
    80: 'BC4_UNORM',
    81: 'BC4_SNORM',
    82: 'BC5_TYPELESS',
    83: 'BC5_UNORM',       # ATI2/BC5U
    84: 'BC5_SNORM',
    85: 'B5G6R5_UNORM',
    86: 'B5G5R5A1_UNORM',
    87: 'B8G8R8A8_UNORM',  # BGRA
    88: 'B8G8R8X8_UNORM',  # BGRX
    91: 'B8G8R8A8_UNORM_SRGB',
    93: 'B8G8R8X8_UNORM_SRGB',
    94: 'BC6H_TYPELESS',
    95: 'BC6H_UF16',
    96: 'BC6H_SF16',
    97: 'BC7_TYPELESS',
    98: 'BC7_UNORM',
    99: 'BC7_UNORM_SRGB',
    115: 'B4G4R4A4_UNORM',
    # Note that this is not a complete list of DXGI formats
    # Further, some "OLD" formats (e.g. BG88R8 or BGR are not even included in the microsoft documentation.)
    # However, these formats are very useful for uncompressed textures as BGR is 24bit and BGRA is 32 bit.
}


def parse_dds_header(filepath: Path) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Parse DDS header to extract dimensions and format.

    Returns:
        ((width, height), format_string) or (None, "UNKNOWN") on error

    Format strings match texdiag output:
        - BC1_UNORM (DXT1)
        - BC3_UNORM (DXT5)
        - BC5_UNORM (ATI2/BC5U)
        - B8G8R8A8_UNORM (BGRA)
        - B8G8R8X8_UNORM (BGR)
    """
    # Note: It is very nice if someone has included the DX10 header, and filled it out completely. However, this basically never happens.
    # Thus, we have to do our best effort to decode the format from legacy FourCC and uncompressed formats.
    # Also, finally our sources and targets probably don't even use the DX10 header.
    try:
        with open(filepath, 'rb') as f:
            # Read magic + main header + DX10 header (if present)
            data = f.read(148)

            if len(data) < 128:
                return None, "UNKNOWN"

            # Check magic number
            magic = data[0:4]
            if magic != b'DDS ':
                return None, "UNKNOWN"

            # Parse main header (little-endian)
            # Offset 4: dwSize (should be 124)
            # Offset 8: dwFlags
            # Offset 12: dwHeight
            # Offset 16: dwWidth
            header = data[4:128]

            dw_size = struct.unpack('<I', header[0:4])[0]
            if dw_size != 124:
                # Non-standard header, but try to continue
                pass

            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            # Parse pixel format structure
            # Header layout: size(4) + flags(4) + height(4) + width(4) + pitch(4) + depth(4) + mipmap(4) + reserved1(44) = 72 bytes
            # Pixel format starts at byte 72 within header (absolute byte 76 from file start)
            pf_offset = 72
            pf_size = struct.unpack('<I', header[pf_offset:pf_offset+4])[0]
            pf_flags = struct.unpack('<I', header[pf_offset+4:pf_offset+8])[0]
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            pf_rgb_bitcount = struct.unpack('<I', header[pf_offset+12:pf_offset+16])[0]

            # Determine format
            format_str = "UNKNOWN"

            # Check for DX10 extended header
            if pf_fourcc == FOURCC_DX10:
                # DX10 header starts at byte 128
                if len(data) >= 148:
                    dxgi_format = struct.unpack('<I', data[128:132])[0]
                    format_str = DXGI_FORMAT_NAMES.get(dxgi_format, f'DXGI_{dxgi_format}')

            # Check for legacy FourCC formats
            elif pf_flags & DDPF_FOURCC:
                # Map FourCC to standard DXGI-style format names
                if pf_fourcc == FOURCC_DXT1:
                    format_str = 'BC1_UNORM'
                elif pf_fourcc == FOURCC_DXT3:
                    format_str = 'BC2_UNORM'
                elif pf_fourcc == FOURCC_DXT5:
                    format_str = 'BC3_UNORM'
                elif pf_fourcc == FOURCC_ATI1 or pf_fourcc == FOURCC_BC4U:
                    format_str = 'BC4_UNORM'
                elif pf_fourcc == FOURCC_BC4S:
                    format_str = 'BC4_SNORM'
                elif pf_fourcc == FOURCC_ATI2 or pf_fourcc == FOURCC_BC5U:
                    format_str = 'BC5_UNORM'
                else:
                    # Unknown FourCC, try to decode as ASCII or return hex
                    try:
                        fourcc_str = pf_fourcc.to_bytes(4, 'little').decode('ascii', errors='replace')
                        # Clean up non-printable characters
                        if all(c.isprintable() or c.isspace() for c in fourcc_str):
                            format_str = f'FOURCC_{fourcc_str}'
                        else:
                            format_str = f'FOURCC_{pf_fourcc:08X}'
                    except:
                        format_str = f'FOURCC_{pf_fourcc:08X}'

            # Check for uncompressed RGB formats
            elif pf_flags & DDPF_RGB:
                if pf_rgb_bitcount == 32:
                    # Check alpha mask to distinguish BGRA from BGRX
                    pf_a_mask = struct.unpack('<I', header[pf_offset+28:pf_offset+32])[0]
                    if pf_a_mask != 0:
                        format_str = 'B8G8R8A8_UNORM'
                    else:
                        format_str = 'B8G8R8X8_UNORM'
                elif pf_rgb_bitcount == 24:
                    format_str = 'B8G8R8_UNORM' # 24-bit BGR, this is not included in the DXGI formats. But it still exists.
                elif pf_rgb_bitcount == 16:
                    # 16-bit formats - check bitmasks to determine exact format
                    pf_r_mask = struct.unpack('<I', header[pf_offset+16:pf_offset+20])[0]
                    pf_g_mask = struct.unpack('<I', header[pf_offset+20:pf_offset+24])[0]
                    pf_b_mask = struct.unpack('<I', header[pf_offset+24:pf_offset+28])[0]
                    pf_a_mask = struct.unpack('<I', header[pf_offset+28:pf_offset+32])[0]

                    # B5G6R5 (RGB565) - red=0xF800, green=0x07E0, blue=0x001F
                    if pf_r_mask == 0xF800 and pf_g_mask == 0x07E0 and pf_b_mask == 0x001F:
                        format_str = 'B5G6R5_UNORM'
                    # B5G5R5A1 - red=0x7C00, green=0x03E0, blue=0x001F, alpha=0x8000
                    elif pf_r_mask == 0x7C00 and pf_g_mask == 0x03E0 and pf_b_mask == 0x001F:
                        format_str = 'B5G5R5A1_UNORM'
                    # B4G4R4A4 - red=0x0F00, green=0x00F0, blue=0x000F, alpha=0xF000
                    elif pf_r_mask == 0x0F00 and pf_g_mask == 0x00F0 and pf_b_mask == 0x000F:
                        format_str = 'B4G4R4A4_UNORM'
                    else:
                        # Generic 16-bit format
                        format_str = 'RGB16_UNORM'

            return (dw_width, dw_height), format_str

    except Exception:
        return None, "UNKNOWN"


def get_dds_info(filepath: Path) -> Tuple[Optional[Tuple[int, int]], str]:
    """
    Convenience function matching the signature of the texdiag-based approach.
    Returns ((width, height), format) or (None, "UNKNOWN").
    """
    return parse_dds_header(filepath)


def parse_dds_header_extended(filepath: Path) -> Tuple[Optional[Tuple[int, int]], str, int]:
    """
    Parse DDS header to extract dimensions, format, and mipmap count.

    Returns:
        ((width, height), format_string, mipmap_count) or (None, "UNKNOWN", 0) on error

    The mipmap count is important for determining if a texture is "well compressed":
    - A properly compressed texture should have log2(max(width, height)) + 1 mipmaps
    - If mipmap_count == 1, the texture likely needs mipmap regeneration
    """
    try:
        with open(filepath, 'rb') as f:
            # Read magic + main header + DX10 header (if present)
            data = f.read(148)

            if len(data) < 128:
                return None, "UNKNOWN", 0

            # Check magic number
            magic = data[0:4]
            if magic != b'DDS ':
                return None, "UNKNOWN", 0

            # Parse main header (little-endian)
            header = data[4:128]

            dw_size = struct.unpack('<I', header[0:4])[0]
            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            # Mipmap count is at offset 24 in header (offset 28 from file start)
            dw_mipmap_count = struct.unpack('<I', header[24:28])[0]

            # If mipmap count is 0, treat as 1 (some files don't set this properly)
            if dw_mipmap_count == 0:
                dw_mipmap_count = 1

            # Parse pixel format structure
            pf_offset = 72
            pf_flags = struct.unpack('<I', header[pf_offset+4:pf_offset+8])[0]
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            pf_rgb_bitcount = struct.unpack('<I', header[pf_offset+12:pf_offset+16])[0]

            # Determine format
            format_str = "UNKNOWN"

            # Check for DX10 extended header
            if pf_fourcc == FOURCC_DX10:
                if len(data) >= 148:
                    dxgi_format = struct.unpack('<I', data[128:132])[0]
                    format_str = DXGI_FORMAT_NAMES.get(dxgi_format, f'DXGI_{dxgi_format}')

            # Check for legacy FourCC formats
            elif pf_flags & DDPF_FOURCC:
                if pf_fourcc == FOURCC_DXT1:
                    format_str = 'BC1_UNORM'
                elif pf_fourcc == FOURCC_DXT3:
                    format_str = 'BC2_UNORM'
                elif pf_fourcc == FOURCC_DXT5:
                    format_str = 'BC3_UNORM'
                elif pf_fourcc == FOURCC_ATI1 or pf_fourcc == FOURCC_BC4U:
                    format_str = 'BC4_UNORM'
                elif pf_fourcc == FOURCC_BC4S:
                    format_str = 'BC4_SNORM' # Rare to encounter.
                elif pf_fourcc == FOURCC_ATI2 or pf_fourcc == FOURCC_BC5U:
                    format_str = 'BC5_UNORM'
                else:
                    try:
                        fourcc_str = pf_fourcc.to_bytes(4, 'little').decode('ascii', errors='replace')
                        if all(c.isprintable() or c.isspace() for c in fourcc_str):
                            format_str = f'FOURCC_{fourcc_str}'
                        else:
                            format_str = f'FOURCC_{pf_fourcc:08X}'
                    except:
                        format_str = f'FOURCC_{pf_fourcc:08X}'

            # Check for uncompressed RGB formats
            elif pf_flags & DDPF_RGB:
                if pf_rgb_bitcount == 32:
                    pf_a_mask = struct.unpack('<I', header[pf_offset+28:pf_offset+32])[0]
                    if pf_a_mask != 0:
                        format_str = 'B8G8R8A8_UNORM'
                    else:
                        format_str = 'B8G8R8X8_UNORM'
                elif pf_rgb_bitcount == 24:
                    format_str = 'B8G8R8_UNORM' # Again not actually a DXGI format, but still exists.
                elif pf_rgb_bitcount == 16:
                    # 16-bit formats - check bitmasks to determine exact format
                    pf_r_mask = struct.unpack('<I', header[pf_offset+16:pf_offset+20])[0]
                    pf_g_mask = struct.unpack('<I', header[pf_offset+20:pf_offset+24])[0]
                    pf_b_mask = struct.unpack('<I', header[pf_offset+24:pf_offset+28])[0]
                    pf_a_mask = struct.unpack('<I', header[pf_offset+28:pf_offset+32])[0]

                    # B5G6R5 (RGB565) - red=0xF800, green=0x07E0, blue=0x001F
                    if pf_r_mask == 0xF800 and pf_g_mask == 0x07E0 and pf_b_mask == 0x001F:
                        format_str = 'B5G6R5_UNORM'
                    # B5G5R5A1 - red=0x7C00, green=0x03E0, blue=0x001F, alpha=0x8000
                    elif pf_r_mask == 0x7C00 and pf_g_mask == 0x03E0 and pf_b_mask == 0x001F:
                        format_str = 'B5G5R5A1_UNORM'
                    # B4G4R4A4 - red=0x0F00, green=0x00F0, blue=0x000F, alpha=0xF000
                    elif pf_r_mask == 0x0F00 and pf_g_mask == 0x00F0 and pf_b_mask == 0x000F:
                        format_str = 'B4G4R4A4_UNORM'
                    else:
                        # Generic 16-bit format
                        format_str = 'RGB16_UNORM'

            return (dw_width, dw_height), format_str, dw_mipmap_count

    except Exception:
        return None, "UNKNOWN", 0


def calculate_expected_mipmaps(width: int, height: int) -> int:
    """
    Calculate the expected number of mipmaps for a texture.

    Formula: floor(log2(max(width, height))) + 1

    Examples:
        1024x1024 -> 11 mipmaps (1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1)
        512x512 -> 10 mipmaps
        256x256 -> 9 mipmaps
    """
    import math
    if width <= 0 or height <= 0:
        return 1
    max_dim = max(width, height)
    return int(math.log2(max_dim)) + 1


def has_adequate_mipmaps(width: int, height: int, mipmap_count: int) -> bool:
    """
    Check if a texture has an adequate number of mipmaps.

    A texture is considered to have adequate mipmaps if:
    - It has at least 2 mipmaps (more than just the base level), OR
    - It's very small (max dimension <= 4) where 1 mipmap is acceptable

    This is a lenient check - some authors intentionally use fewer mipmaps.
    """
    max_dim = max(width, height)

    # Very small textures are fine with 1 mipmap
    if max_dim <= 4:
        return True

    # For larger textures, we expect at least 2 mipmaps
    # (1 mipmap means only base level, likely missing mipmaps)
    return mipmap_count >= 2


def parse_tga_header(filepath: Path) -> Tuple[Optional[Tuple[int, int]], str]:
    # TODO: Ideally this should be not in the DDS parser file. But for now it's convenient to have it here.
    # Also isn't it nice how much simpler TGA is compared to DDS?
    """
    Parse TGA header to extract dimensions.

    TGA files are always uncompressed (RGBA/BGRA) with no mipmaps.
    This is a fast alternative to spawning texdiag.exe.

    Returns:
        ((width, height), format_string) or (None, "UNKNOWN") on error

    Format is "TGA_RGBA" (32-bit) or "TGA_RGB" (24-bit).
    Caller should treat as uncompressed and needing compression.
    """
    try:
        with open(filepath, 'rb') as f:
            # TGA header is 18 bytes
            header = f.read(18)

            if len(header) < 18:
                return None, "UNKNOWN"

            # TGA header structure:
            # Bytes 12-13: Width (little-endian)
            # Bytes 14-15: Height (little-endian)
            # Byte 16: Pixel depth (bits per pixel)

            width = struct.unpack('<H', header[12:14])[0]
            height = struct.unpack('<H', header[14:16])[0]
            pixel_depth = header[16]

            # Determine format based on pixel depth
            if pixel_depth == 32:
                format_str = "TGA_RGBA"  # Has alpha
            elif pixel_depth == 24:
                format_str = "TGA_RGB"   # No alpha
            else:
                format_str = "TGA"

            return (width, height), format_str

    except Exception:
        return None, "UNKNOWN"


def parse_tga_header_extended(filepath: Path) -> Tuple[Optional[Tuple[int, int]], str, int]:
    """
    Parse TGA header - extended version matching DDS interface.

    TGA files never have mipmaps, so mipmap_count is always 1.

    Returns:
        ((width, height), format_string, mipmap_count) or (None, "UNKNOWN", 0) on error
    """
    dims, fmt = parse_tga_header(filepath)
    if dims:
        return dims, fmt, 1  # TGA always has 1 "mipmap" (base level only)
    return None, "UNKNOWN", 0


# =============================================================================
# Alpha Channel Analysis Functions (Optional - for detecting unused alpha)
# =============================================================================

# This is some unhinged pixel sniffing right here. I got the DXT1a check from a stackoverflow answer:
# https://stackoverflow.com/questions/19448/in-a-dds-file-can-you-detect-textures-with-0-1-alpha-bits
# If you have to ask why to use numpy here, it's because doing this bytewise is very slow. Matrix operations are your friend.
# No Python loops over pixels/blocks - just numpy array/matrix operations (often called "vectorized" in numpy jargon).
# Yes you can make it faster with numba or cython, but this is already fast enough for our use case.

def analyze_bc1_alpha(filepath: Path) -> bool:
    """
    Check if a BC1/DXT1 texture uses 1-bit alpha (DXT1a mode).

    BC1 block structure (8 bytes per 4x4 block):
    - 2 bytes: color0 (RGB565)
    - 2 bytes: color1 (RGB565)
    - 4 bytes: 2-bit indices for 16 pixels

    If color0 <= color1, the block uses 3-color mode with 1-bit transparency.
    In this mode, index 3 means transparent black.

    Uses NumPy for fast array/matrix operations.

    Returns:
        True if any block uses transparency (has meaningful alpha)
        False if all blocks are opaque (alpha can be ignored)
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read(148)
            if len(data) < 128:
                return True

            header = data[4:128]
            pf_offset = 72
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            header_size = 148 if pf_fourcc == FOURCC_DX10 else 128

            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            blocks_x = (dw_width + 3) // 4
            blocks_y = (dw_height + 3) // 4
            total_blocks = blocks_x * blocks_y

            f.seek(header_size)
            block_data = f.read(total_blocks * 8)

            if len(block_data) < total_blocks * 8:
                return True

            # Parse as structured array: each block is 8 bytes
            # color0 (2 bytes), color1 (2 bytes), indices (4 bytes)
            arr = np.frombuffer(block_data, dtype=np.uint8).reshape(total_blocks, 8)

            # Extract color0 and color1 as uint16 (little-endian)
            color0 = arr[:, 0].astype(np.uint16) | (arr[:, 1].astype(np.uint16) << 8)
            color1 = arr[:, 2].astype(np.uint16) | (arr[:, 3].astype(np.uint16) << 8)

            # Find blocks in 3-color mode (transparency mode): color0 <= color1
            transparent_mode = color0 <= color1

            if not np.any(transparent_mode):
                return False  # No blocks use transparency mode

            # For blocks in transparent mode, check if any pixel uses index 3
            # Extract indices as uint32 (4 bytes per block)
            indices_bytes = arr[:, 4:8]
            indices_u32 = (indices_bytes[:, 0].astype(np.uint32) |
                          (indices_bytes[:, 1].astype(np.uint32) << 8) |
                          (indices_bytes[:, 2].astype(np.uint32) << 16) |
                          (indices_bytes[:, 3].astype(np.uint32) << 24))

            # Matrix check: for blocks in transparent mode, check if any pixel uses index 3
            # Index 3 = binary 11, so we check all 16 pixel positions (2 bits each)
            # Mask: 0x55555555 = 01010101... (bit 0 of each 2-bit pair)
            # Mask: 0xAAAAAAAA = 10101010... (bit 1 of each 2-bit pair)
            # Index 3 means both bits are set, so (indices & 0x55555555) and ((indices >> 1) & 0x55555555) both have that bit
            transparent_indices = indices_u32[transparent_mode]
            bit0 = transparent_indices & 0x55555555  # Odd bits (bit 0 of each pair)
            bit1 = (transparent_indices >> 1) & 0x55555555  # Even bits shifted (bit 1 of each pair)
            # Index 3 = both bits set, so bit0 & bit1 will have a 1 where index is 3
            has_index_3 = (bit0 & bit1) != 0

            return bool(np.any(has_index_3))

    except Exception:
        return True


def analyze_bc2_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if a BC2/DXT3 texture has meaningful alpha.

    BC2 block structure (16 bytes per 4x4 block):
    - 8 bytes: explicit 4-bit alpha for each of 16 pixels
    - 8 bytes: BC1-style color block

    Uses NumPy for fast array/matrix operations.

    Returns:
        True if any pixel has alpha < threshold (has meaningful alpha)
        False if all pixels are essentially opaque
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read(148)
            if len(data) < 128:
                return True

            header = data[4:128]
            pf_offset = 72
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            header_size = 148 if pf_fourcc == FOURCC_DX10 else 128

            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            blocks_x = (dw_width + 3) // 4
            blocks_y = (dw_height + 3) // 4
            total_blocks = blocks_x * blocks_y

            f.seek(header_size)
            block_data = f.read(total_blocks * 16)

            if len(block_data) < total_blocks * 16:
                return True

            # 4-bit threshold (0-15 scale)
            threshold_4bit = threshold // 16

            # Reshape to extract alpha bytes (first 8 bytes of each 16-byte block)
            arr = np.frombuffer(block_data, dtype=np.uint8).reshape(total_blocks, 16)
            alpha_bytes = arr[:, :8].flatten()  # First 8 bytes of each block

            # Extract low and high nibbles (4-bit alpha values)
            alpha_lo = alpha_bytes & 0x0F
            alpha_hi = (alpha_bytes >> 4) & 0x0F

            # Check if any 4-bit alpha is below threshold
            return bool(np.any(alpha_lo < threshold_4bit) or np.any(alpha_hi < threshold_4bit))

    except Exception:
        return True


def analyze_bc3_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if a BC3/DXT5 texture has meaningful alpha.

    BC3 block structure (16 bytes per 4x4 block):
    - 8 bytes: interpolated alpha block
      - 1 byte: alpha0
      - 1 byte: alpha1
      - 6 bytes: 3-bit indices for 16 pixels
    - 8 bytes: BC1-style color block

    Uses NumPy for fast array/matrix operations with optimized fast-paths.

    Returns:
        True if alpha varies meaningfully (has meaningful alpha)
        False if all pixels are essentially opaque
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read(148)
            if len(data) < 128:
                return True

            header = data[4:128]
            pf_offset = 72
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            header_size = 148 if pf_fourcc == FOURCC_DX10 else 128

            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            blocks_x = (dw_width + 3) // 4
            blocks_y = (dw_height + 3) // 4
            total_blocks = blocks_x * blocks_y

            f.seek(header_size)
            block_data = f.read(total_blocks * 16)

            if len(block_data) < total_blocks * 16:
                return True

            # Reshape to access block structure
            arr = np.frombuffer(block_data, dtype=np.uint8).reshape(total_blocks, 16)

            # Extract alpha endpoints (first 2 bytes of each block)
            alpha0 = arr[:, 0]
            alpha1 = arr[:, 1]

            # FAST PATH for threshold=255: If both endpoints are 255, all interpolated
            # values are also 255 (regardless of mode), so the block is fully opaque
            if threshold == 255:
                # Any block where either endpoint < 255 could have non-opaque pixels
                # But we need to be more careful: in 6-value mode, index 6 = 0 (transparent)
                # So check: if alpha0 <= alpha1 (6-value mode), indices 6 or 7 mean transparency

                # Blocks in 8-value mode (alpha0 > alpha1) with both endpoints = 255 are opaque
                # Blocks in 6-value mode (alpha0 <= alpha1) could have index 6 (=0) or 7 (=255)

                # Quick check: if all alpha0 and alpha1 are 255, and none use 6-value mode
                # with index 6, then fully opaque
                eight_value_mode = alpha0 > alpha1
                both_255 = (alpha0 == 255) & (alpha1 == 255)

                # If in 8-value mode and both endpoints are 255, block is opaque
                opaque_8mode = eight_value_mode & both_255

                # For 6-value mode, need to check if index 6 (=0) is used
                # This requires checking the index data - fallback to per-block check
                needs_index_check = ~eight_value_mode  # 6-value mode blocks

                if np.all(opaque_8mode | ~needs_index_check):
                    # All blocks are either opaque 8-mode or we need to check indices
                    pass

                # For simplicity with threshold=255: if min of all alpha0/alpha1 >= 255
                # AND no 6-value mode blocks, we're done
                if np.all(both_255) and np.all(eight_value_mode):
                    return False  # All blocks opaque

                # Otherwise check if any endpoint < 255
                if np.any(alpha0 < 255) or np.any(alpha1 < 255):
                    return True  # Some blocks have non-255 endpoints

                # All endpoints are 255, but some blocks use 6-value mode
                # In 6-value mode with both endpoints 255: interpolated values are all 255
                # except index 6 = 0. Need to check if any block uses index 6.
                six_value_blocks = np.where(~eight_value_mode)[0]
                if len(six_value_blocks) == 0:
                    return False  # No 6-value mode blocks

                # Vectorized check for index 6 in 6-value mode blocks
                # Extract index bytes (bytes 2-7 of each block) as 48-bit values
                six_value_arr = arr[six_value_blocks]
                # Combine 6 bytes into 48-bit index data per block
                idx_bytes = six_value_arr[:, 2:8]
                indices_48 = (idx_bytes[:, 0].astype(np.uint64) |
                             (idx_bytes[:, 1].astype(np.uint64) << 8) |
                             (idx_bytes[:, 2].astype(np.uint64) << 16) |
                             (idx_bytes[:, 3].astype(np.uint64) << 24) |
                             (idx_bytes[:, 4].astype(np.uint64) << 32) |
                             (idx_bytes[:, 5].astype(np.uint64) << 40))

                # Check all 16 pixels (3 bits each) for index 6 (binary 110)
                # Mask for each 3-bit position and check if == 6
                for shift in range(0, 48, 3):
                    pixel_indices = (indices_48 >> shift) & 0x7
                    if np.any(pixel_indices == 6):
                        return True

                return False  # No transparency found

            # General case: matrix computation of interpolated alpha values
            # Build lookup tables for all 8 possible indices per block

            # Convert to int16 for interpolation math (avoid overflow)
            a0 = alpha0.astype(np.int16)
            a1 = alpha1.astype(np.int16)
            eight_mode = a0 > a1

            # Pre-compute all 8 alpha values for each block (shape: total_blocks x 8)
            alpha_lut = np.zeros((total_blocks, 8), dtype=np.int16)
            alpha_lut[:, 0] = a0
            alpha_lut[:, 1] = a1

            # 8-value mode interpolation (a0 > a1)
            em = eight_mode
            alpha_lut[em, 2] = (6 * a0[em] + 1 * a1[em]) // 7
            alpha_lut[em, 3] = (5 * a0[em] + 2 * a1[em]) // 7
            alpha_lut[em, 4] = (4 * a0[em] + 3 * a1[em]) // 7
            alpha_lut[em, 5] = (3 * a0[em] + 4 * a1[em]) // 7
            alpha_lut[em, 6] = (2 * a0[em] + 5 * a1[em]) // 7
            alpha_lut[em, 7] = (1 * a0[em] + 6 * a1[em]) // 7

            # 6-value mode interpolation (a0 <= a1)
            sm = ~eight_mode
            alpha_lut[sm, 2] = (4 * a0[sm] + 1 * a1[sm]) // 5
            alpha_lut[sm, 3] = (3 * a0[sm] + 2 * a1[sm]) // 5
            alpha_lut[sm, 4] = (2 * a0[sm] + 3 * a1[sm]) // 5
            alpha_lut[sm, 5] = (1 * a0[sm] + 4 * a1[sm]) // 5
            alpha_lut[sm, 6] = 0
            alpha_lut[sm, 7] = 255

            # Quick check: if min alpha in any LUT row < threshold, we might have transparency
            if np.all(np.min(alpha_lut, axis=1) >= threshold):
                return False  # All possible alpha values >= threshold

            # Extract 48-bit index data for all blocks
            idx_bytes = arr[:, 2:8]
            indices_48 = (idx_bytes[:, 0].astype(np.uint64) |
                         (idx_bytes[:, 1].astype(np.uint64) << 8) |
                         (idx_bytes[:, 2].astype(np.uint64) << 16) |
                         (idx_bytes[:, 3].astype(np.uint64) << 24) |
                         (idx_bytes[:, 4].astype(np.uint64) << 32) |
                         (idx_bytes[:, 5].astype(np.uint64) << 40))

            # Check each of 16 pixels across all blocks
            for shift in range(0, 48, 3):
                pixel_idx = ((indices_48 >> shift) & 0x7).astype(np.int64)
                # Look up alpha value for each block's pixel
                pixel_alpha = alpha_lut[np.arange(total_blocks), pixel_idx]
                if np.any(pixel_alpha < threshold):
                    return True

            return False

    except Exception:
        return True


def analyze_bgra_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if an uncompressed BGRA DDS texture has meaningful alpha.

    Uses NumPy for fast array operations on alpha channel.

    Returns:
        True if any pixel has alpha < threshold
        False if all pixels are essentially opaque
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read(148)
            if len(data) < 128:
                return True

            header = data[4:128]
            pf_offset = 72
            pf_fourcc = struct.unpack('<I', header[pf_offset+8:pf_offset+12])[0]
            header_size = 148 if pf_fourcc == FOURCC_DX10 else 128

            dw_height = struct.unpack('<I', header[8:12])[0]
            dw_width = struct.unpack('<I', header[12:16])[0]

            total_pixels = dw_width * dw_height

            f.seek(header_size)

            # Read all pixel data at once and use NumPy
            pixel_data = f.read(total_pixels * 4)
            if len(pixel_data) < total_pixels * 4:
                return True  # Incomplete file, assume has alpha

            # Convert to numpy array and extract alpha channel (every 4th byte starting at index 3)
            arr = np.frombuffer(pixel_data, dtype=np.uint8)
            alpha_channel = arr[3::4]  # Slice: start at 3, step by 4

            # Check if any alpha value is below threshold
            return bool(np.any(alpha_channel < threshold))

    except Exception:
        return True


def analyze_tga_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if a 32-bit TGA texture has meaningful alpha.

    Uses NumPy for fast array/matrix operations. Supports uncompressed and RLE TGA.

    Returns:
        True if any pixel has alpha < threshold
        False if all pixels are essentially opaque (alpha can be ignored)
    """
    try:
        with open(filepath, 'rb') as f:
            header = f.read(18)
            if len(header) < 18:
                return True

            id_length = header[0]
            colormap_type = header[1]
            image_type = header[2]

            # Skip if not true-color (uncompressed or RLE)
            if image_type not in (2, 10):
                return True

            width = struct.unpack('<H', header[12:14])[0]
            height = struct.unpack('<H', header[14:16])[0]
            pixel_depth = header[16]

            # Only analyze 32-bit TGA (has alpha)
            if pixel_depth != 32:
                return False  # No alpha channel

            # Skip ID field
            if id_length > 0:
                f.read(id_length)

            # Skip colormap
            if colormap_type == 1:
                cm_length = struct.unpack('<H', header[5:7])[0]
                cm_size = header[7]
                f.read(cm_length * ((cm_size + 7) // 8))

            total_pixels = width * height

            if image_type == 2:  # Uncompressed - fast NumPy path
                pixel_data = f.read(total_pixels * 4)
                if len(pixel_data) < total_pixels * 4:
                    return True

                arr = np.frombuffer(pixel_data, dtype=np.uint8)
                alpha_channel = arr[3::4]
                return bool(np.any(alpha_channel < threshold))

            elif image_type == 10:  # RLE compressed - decompress then analyze
                # Decompress RLE data
                pixels = []
                pixels_read = 0
                while pixels_read < total_pixels:
                    packet = f.read(1)
                    if not packet:
                        break

                    count = (packet[0] & 0x7F) + 1
                    is_rle = packet[0] & 0x80

                    if is_rle:
                        pixel = f.read(4)
                        if len(pixel) < 4:
                            break
                        pixels.extend(pixel * count)
                    else:
                        raw_data = f.read(count * 4)
                        if len(raw_data) < count * 4:
                            break
                        pixels.extend(raw_data)

                    pixels_read += count

                if pixels:
                    arr = np.array(pixels, dtype=np.uint8)
                    alpha_channel = arr[3::4]
                    return bool(np.any(alpha_channel < threshold))

            return False

    except Exception:
        return True


def has_meaningful_alpha(filepath: Path, format_str: str, threshold: int = 255) -> bool:
    """
    Main entry point for alpha analysis.

    Determines the appropriate analysis function based on format and runs it.

    Args:
        filepath: Path to the texture file
        format_str: Format string from parse_dds_header (e.g., 'BC1_UNORM', 'BC3_UNORM')
        threshold: Alpha value below which a pixel is considered "non-opaque" (0-255)

    Returns:
        True if the texture has meaningful alpha (should use BC3/alpha format)
        False if alpha is unused (can safely use BC1/no-alpha format)
    """
    format_lower = format_str.lower()

    # BC1/DXT1 - check for DXT1a transparency mode
    if 'bc1' in format_lower or format_str == 'BC1_UNORM':
        return analyze_bc1_alpha(filepath)

    # BC2/DXT3 - explicit 4-bit alpha
    if 'bc2' in format_lower or format_str == 'BC2_UNORM':
        return analyze_bc2_alpha(filepath, threshold)

    # BC3/DXT5 - interpolated alpha
    if 'bc3' in format_lower or format_str == 'BC3_UNORM':
        return analyze_bc3_alpha(filepath, threshold)

    # Uncompressed BGRA/RGBA (matches B8G8R8A8_UNORM, R8G8B8A8_UNORM, or normalized 'BGRA'/'RGBA')
    # Both have alpha at byte offset 3 in each 4-byte pixel
    if 'b8g8r8a8' in format_lower or 'r8g8b8a8' in format_lower or format_lower in ('bgra', 'rgba'):
        return analyze_bgra_alpha(filepath, threshold)

    # TGA with alpha
    if format_str == 'TGA_RGBA':
        return analyze_tga_alpha(filepath, threshold)

    # For unknown formats with alpha in the name, assume meaningful
    if 'a' in format_lower or 'alpha' in format_lower:
        return True

    # No alpha channel in format
    return False


# =============================================================================
# DX10 Header Stripping (for legacy compatibility)
# =============================================================================

# DXGI format code -> legacy FourCC for BC formats only
# Cuttlefish outputs DX10 headers which OpenMW doesn't support
DXGI_TO_LEGACY_FOURCC = {
    71: FOURCC_DXT1,   # BC1_UNORM -> DXT1
    72: FOURCC_DXT1,   # BC1_UNORM_SRGB -> DXT1
    74: FOURCC_DXT3,   # BC2_UNORM -> DXT3
    75: FOURCC_DXT3,   # BC2_UNORM_SRGB -> DXT3
    77: FOURCC_DXT5,   # BC3_UNORM -> DXT5
    78: FOURCC_DXT5,   # BC3_UNORM_SRGB -> DXT5
}


def has_dx10_header(filepath: Path) -> bool:
    """
    Check if a DDS file has a DX10 extended header.

    Args:
        filepath: Path to DDS file

    Returns:
        True if file has DX10 header, False otherwise
    """
    try:
        with open(filepath, 'rb') as f:
            data = f.read(88)

        if len(data) < 88:
            return False

        if data[0:4] != b'DDS ':
            return False

        pf_fourcc = struct.unpack('<I', data[84:88])[0]
        return pf_fourcc == FOURCC_DX10

    except Exception:
        return False


def strip_dx10_header(filepath: Path) -> Tuple[bool, Optional[str]]:
    """
    Strip the DX10 extended header from a DDS file, converting to legacy format.

    Only supports BC1/BC2/BC3 formats (what cuttlefish outputs for us).
    Returns a warning for unexpected DX10 formats.

    DDS structure:
    - 4 bytes: Magic "DDS "
    - 124 bytes: DDS_HEADER (pixel format at offset 76, FourCC at offset 84)
    - 20 bytes: DDS_HEADER_DXT10 (only if FourCC == "DX10")
    - N bytes: Pixel data

    Args:
        filepath: Path to DDS file to modify (in-place)

    Returns:
        (True, None) on success
        (True, warning_message) if unexpected format (file unchanged)
        (False, error_message) on failure
    """
    try:
        with open(filepath, 'rb') as f:
            data = bytearray(f.read())

        if len(data) < 148:
            return True, None  # Too small to have DX10 header

        # Check magic
        if data[0:4] != b'DDS ':
            return False, "Not a valid DDS file"

        # Check if DX10 header present (FourCC at offset 84)
        pf_fourcc = struct.unpack('<I', data[84:88])[0]

        if pf_fourcc != FOURCC_DX10:
            return True, None  # No DX10 header, nothing to do

        # Read DXGI format from DX10 header (at byte 128)
        dxgi_format = struct.unpack('<I', data[128:132])[0]

        # Only handle BC1/BC2/BC3
        if dxgi_format not in DXGI_TO_LEGACY_FOURCC:
            format_name = DXGI_FORMAT_NAMES.get(dxgi_format, f'DXGI_{dxgi_format}')
            return True, f"Unexpected DX10 format {format_name} - file unchanged"

        legacy_fourcc = DXGI_TO_LEGACY_FOURCC[dxgi_format]

        # Update pixel format: set flags to DDPF_FOURCC
        struct.pack_into('<I', data, 80, DDPF_FOURCC)

        # Set legacy FourCC (DXT1/DXT3/DXT5)
        struct.pack_into('<I', data, 84, legacy_fourcc)

        # Clear bit count and masks (not used for compressed formats)
        struct.pack_into('<I', data, 88, 0)   # dwRGBBitCount
        struct.pack_into('<I', data, 92, 0)   # dwRBitMask
        struct.pack_into('<I', data, 96, 0)   # dwGBitMask
        struct.pack_into('<I', data, 100, 0)  # dwBBitMask
        struct.pack_into('<I', data, 104, 0)  # dwABitMask

        # Remove 20-byte DX10 header: keep bytes 0-127, skip 128-147, keep 148+
        new_data = data[:128] + data[148:]

        # Write back
        with open(filepath, 'wb') as f:
            f.write(new_data)

        return True, None

    except Exception as e:
        return False, str(e)


def convert_bgrx32_to_bgr24(filepath: Path) -> Tuple[bool, Optional[str]]:
    """
    Convert a B8G8R8X8_UNORM (32-bit BGRX) DDS file to B8G8R8 (24-bit BGR) in-place.

    This strips the unused X (padding) byte from each pixel, reducing file size by 25%.
    Only works on uncompressed B8G8R8X8_UNORM format files.
    BTW, we know it's BGRX because the alpha mask is 0 in that format.
    Our decision tree, if it detects wasted BGRA space the procedure is to convert to BGRX.
    From there we can convert to BGR24 as a hacky post clean up.

    Args:
        filepath: Path to DDS file to convert (in-place)

    Returns:
        (True, None) on success
        (False, error_message) on failure or if format is not B8G8R8X8_UNORM
    """
    try:
        with open(filepath, 'rb') as f:
            data = bytearray(f.read())

        if len(data) < 128:
            return False, "File too small to be valid DDS"

        # Check magic
        if data[0:4] != b'DDS ':
            return False, "Not a valid DDS file"

        # Check for DX10 header - we don't handle that here
        pf_fourcc = struct.unpack('<I', data[84:88])[0]
        if pf_fourcc == FOURCC_DX10:
            return False, "DX10 header present - strip it first or use a different approach"

        # Check pixel format flags
        pf_flags = struct.unpack('<I', data[80:84])[0]
        if not (pf_flags & DDPF_RGB):
            return False, "Not an RGB format"

        # Check bit count
        rgb_bitcount = struct.unpack('<I', data[88:92])[0]
        if rgb_bitcount != 32:
            return False, f"Not 32-bit format (found {rgb_bitcount}-bit)"

        # Verify it's BGRX (alpha mask should be 0)
        a_mask = struct.unpack('<I', data[104:108])[0]
        if a_mask != 0:
            return False, "Has alpha mask - this is BGRA, not BGRX"

        # Get dimensions and mipmap count
        height = struct.unpack('<I', data[12:16])[0]
        width = struct.unpack('<I', data[16:20])[0]
        mipmap_count = struct.unpack('<I', data[28:32])[0]
        if mipmap_count == 0:
            mipmap_count = 1

        # Header is 128 bytes for non-DX10
        header_size = 128

        # Convert pixel data: strip every 4th byte (the X padding)
        src_offset = header_size
        new_pixel_data = bytearray()

        mip_w, mip_h = width, height
        for _ in range(mipmap_count):
            mip_pixels = mip_w * mip_h
            src_size = mip_pixels * 4

            if src_offset + src_size > len(data):
                return False, "Incomplete pixel data"

            # Use numpy for fast conversion
            mip_data = np.frombuffer(data[src_offset:src_offset + src_size], dtype=np.uint8)
            # Reshape to Nx4 and take only first 3 columns (BGR, drop X)
            mip_data = mip_data.reshape(-1, 4)[:, :3].flatten()
            new_pixel_data.extend(mip_data.tobytes())

            src_offset += src_size
            # Next mip level (halve dimensions, min 1)
            mip_w = max(1, mip_w // 2)
            mip_h = max(1, mip_h // 2)

        # Update header for 24-bit format
        # dwRGBBitCount = 24
        struct.pack_into('<I', data, 88, 24)

        # Update pitch (bytes per row for base level)
        # dwPitchOrLinearSize = width * 3
        struct.pack_into('<I', data, 20, width * 3)

        # Bit masks for 24-bit BGR:
        # R mask = 0x00FF0000 (bits 16-23)
        # G mask = 0x0000FF00 (bits 8-15)
        # B mask = 0x000000FF (bits 0-7)
        # A mask = 0x00000000 (no alpha)
        struct.pack_into('<I', data, 92, 0x00FF0000)   # R mask
        struct.pack_into('<I', data, 96, 0x0000FF00)   # G mask
        struct.pack_into('<I', data, 100, 0x000000FF)  # B mask
        struct.pack_into('<I', data, 104, 0x00000000)  # A mask (already 0, but explicit)

        # Write new file: header + new pixel data
        with open(filepath, 'wb') as f:
            f.write(data[:header_size])
            f.write(new_pixel_data)

        return True, None

    except Exception as e:
        return False, str(e)


def convert_bgrx32_to_bgr24_batch(directory: Path, recursive: bool = True) -> Tuple[int, int, list]:
    """
    Convert all B8G8R8X8_UNORM DDS files in a directory to B8G8R8 (24-bit).

    Args:
        directory: Directory to scan
        recursive: If True, scan subdirectories

    Returns:
        (converted_count, skipped_count, messages_list)
    """
    converted = 0
    skipped = 0
    messages = []

    pattern = '**/*.dds' if recursive else '*.dds'

    for dds_file in directory.glob(pattern):
        # Quick check: parse header to see if it's B8G8R8X8
        _, fmt = parse_dds_header(dds_file)
        if fmt == 'B8G8R8X8_UNORM':
            success, msg = convert_bgrx32_to_bgr24(dds_file)
            if success:
                converted += 1
            else:
                messages.append(f"{dds_file.name}: {msg}")
                skipped += 1
        # else: not BGRX, skip silently

    return converted, skipped, messages


def strip_dx10_headers_batch(directory: Path, recursive: bool = True) -> Tuple[int, int, list]:
    """
    Strip DX10 headers from all DDS files in a directory.

    Args:
        directory: Directory to scan
        recursive: If True, scan subdirectories

    Returns:
        (stripped_count, skipped_count, warnings_list)
    """
    stripped = 0
    skipped = 0
    warnings = []

    pattern = '**/*.dds' if recursive else '*.dds'

    for dds_file in directory.glob(pattern):
        if has_dx10_header(dds_file):
            success, msg = strip_dx10_header(dds_file)
            if success:
                if msg:  # Warning
                    warnings.append(f"{dds_file.name}: {msg}")
                    skipped += 1
                else:
                    stripped += 1
            else:
                warnings.append(f"{dds_file.name}: ERROR - {msg}")
                skipped += 1

    return stripped, skipped, warnings


if __name__ == "__main__":
    # Test on local DDS files
    import sys
    from pathlib import Path

    if len(sys.argv) > 1:
        test_file = Path(sys.argv[1])
    else:
        # Test on any DDS file in current directory
        test_files = list(Path('.').glob('*.dds'))
        if not test_files:
            print("No DDS files found in current directory")
            sys.exit(1)
        test_file = test_files[0]

    dims, fmt = parse_dds_header(test_file)
    if dims:
        print(f"File: {test_file}")
        print(f"Dimensions: {dims[0]}x{dims[1]}")
        print(f"Format: {fmt}")

        # Test alpha analysis
        has_alpha = has_meaningful_alpha(test_file, fmt)
        print(f"Has meaningful alpha: {has_alpha}")
    else:
        print(f"Failed to parse {test_file}")
