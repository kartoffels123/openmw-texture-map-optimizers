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
    else:
        print(f"Failed to parse {test_file}")
