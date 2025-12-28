"""
Lightweight DDS header parser for fast analysis.
Extracted from Kaitai Struct DDS specification (dds.ksy) - no external dependencies.
Only reads the header (first ~148 bytes) for width, height, and format.

Supported formats:
- Legacy FourCC: DXT1/DXT3/DXT5, ATI1/ATI2, BC4U/BC4S/BC5U
- DX10 extended header: All DXGI formats (BC1-BC7, RGBA, float formats, etc.)
- Uncompressed: BGRA, BGRX, BGR
- ~100x faster than spawning texdiag subprocess
"""

import struct
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


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
    88: 'B8G8R8X8_UNORM',  # BGRX/BGR
    91: 'B8G8R8A8_UNORM_SRGB',
    93: 'B8G8R8X8_UNORM_SRGB',
    94: 'BC6H_TYPELESS',
    95: 'BC6H_UF16',
    96: 'BC6H_SF16',
    97: 'BC7_TYPELESS',
    98: 'BC7_UNORM',
    99: 'BC7_UNORM_SRGB',
    115: 'B4G4R4A4_UNORM',
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
            # Kaitai says fourcc is at absolute 0x54 (84), which is 84-4=80 in header, which is 72+8
            pf_offset = 72  # Not 0x44!
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
                    format_str = 'B8G8R8_UNORM'

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
                    format_str = 'BC4_SNORM'
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
                    format_str = 'B8G8R8_UNORM'

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

def analyze_bc1_alpha(filepath: Path) -> bool:
    """
    Check if a BC1/DXT1 texture uses 1-bit alpha (DXT1a mode).

    BC1 block structure (8 bytes per 4x4 block):
    - 2 bytes: color0 (RGB565)
    - 2 bytes: color1 (RGB565)
    - 4 bytes: 2-bit indices for 16 pixels

    If color0 <= color1, the block uses 3-color mode with 1-bit transparency.
    In this mode, index 3 means transparent black.

    Uses NumPy for fast vectorized analysis.

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

            # Check only blocks in transparent mode
            for block_idx in np.where(transparent_mode)[0]:
                indices = indices_u32[block_idx]
                # Check each of 16 pixels (2 bits each) for index 3
                for p in range(16):
                    if ((indices >> (p * 2)) & 0x3) == 3:
                        return True

            return False

    except Exception:
        return True


def analyze_bc2_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if a BC2/DXT3 texture has meaningful alpha.

    BC2 block structure (16 bytes per 4x4 block):
    - 8 bytes: explicit 4-bit alpha for each of 16 pixels
    - 8 bytes: BC1-style color block

    Uses NumPy for fast vectorized analysis.

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

    Uses NumPy for fast vectorized analysis with optimized fast-paths.

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

                # Check index data for 6-value mode blocks
                for block_idx in six_value_blocks:
                    index_bytes = block_data[block_idx * 16 + 2:block_idx * 16 + 8]
                    indices = int.from_bytes(index_bytes, 'little')
                    for p in range(16):
                        idx = (indices >> (p * 3)) & 0x7
                        if idx == 6:  # Index 6 = 0 in 6-value mode
                            return True

                return False  # No transparency found

            # General case: need to compute interpolated values per block
            # This is slower but handles arbitrary thresholds
            for i in range(total_blocks):
                a0 = alpha0[i]
                a1 = alpha1[i]

                if a0 > a1:
                    alphas = [a0, a1,
                              (6 * a0 + 1 * a1) // 7, (5 * a0 + 2 * a1) // 7,
                              (4 * a0 + 3 * a1) // 7, (3 * a0 + 4 * a1) // 7,
                              (2 * a0 + 5 * a1) // 7, (1 * a0 + 6 * a1) // 7]
                else:
                    alphas = [a0, a1,
                              (4 * a0 + 1 * a1) // 5, (3 * a0 + 2 * a1) // 5,
                              (2 * a0 + 3 * a1) // 5, (1 * a0 + 4 * a1) // 5,
                              0, 255]

                index_bytes = block_data[i * 16 + 2:i * 16 + 8]
                indices = int.from_bytes(index_bytes, 'little')

                for p in range(16):
                    idx = (indices >> (p * 3)) & 0x7
                    if alphas[idx] < threshold:
                        return True

            return False

    except Exception:
        return True


def analyze_bgra_alpha(filepath: Path, threshold: int = 255) -> bool:
    """
    Check if an uncompressed BGRA DDS texture has meaningful alpha.

    Uses NumPy for fast vectorized analysis of alpha channel.

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

    Uses NumPy for fast vectorized analysis. Supports uncompressed and RLE TGA.

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
