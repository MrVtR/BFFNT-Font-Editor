#!/usr/bin/python
# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import struct
import math
import os
import sys
from PIL import Image, ImageTk, ImageDraw

# ==============================================================================
# BFFNT Parser and Packer Core (PIL/Pillow-based, no pypng dependency)
# ==============================================================================

VERSIONS = (0x04000000, 0x03000000)

FFNT_HEADER_SIZE = 0x14
FINF_HEADER_SIZE = 0x20
TGLP_HEADER_SIZE = 0x20
CWDH_HEADER_SIZE = 0x10
CMAP_HEADER_SIZE = 0x14

FFNT_HEADER_MAGIC = (b'FFNT', b'FFNU')
FINF_HEADER_MAGIC = b'FINF'
TGLP_HEADER_MAGIC = b'TGLP'
CWDH_HEADER_MAGIC = b'CWDH'
CMAP_HEADER_MAGIC = b'CMAP'

FFNT_HEADER_STRUCT = '%s4s2H3I'
FINF_HEADER_STRUCT = '%s4sI4B2H4B3I'
TGLP_HEADER_STRUCT = '%s4sI4BI6HI'
CWDH_HEADER_STRUCT = '%s4sI2HI'
CMAP_HEADER_STRUCT = '%s4sI4HI'

FORMAT_RGBA8 = 0x00
FORMAT_RGB8 = 0x01
FORMAT_RGBA5551 = 0x02
FORMAT_RGB565 = 0x03
FORMAT_RGBA4 = 0x04
FORMAT_LA8 = 0x05
FORMAT_HILO8 = 0x06
FORMAT_L8 = 0x07
FORMAT_A8 = 0x08
FORMAT_LA4 = 0x09
FORMAT_L4 = 0x0A
FORMAT_A4 = 0x0B
FORMAT_ETC1 = 0x0C
FORMAT_ETC1A4 = 0x0D

PIXEL_FORMATS = {
    FORMAT_RGBA8: 'RGBA8',
    FORMAT_RGB8: 'RGB8',
    FORMAT_RGBA5551: 'RGBA5551',
    FORMAT_RGB565: 'RGB565',
    FORMAT_RGBA4: 'RGBA4',
    FORMAT_LA8: 'LA8',
    FORMAT_HILO8: 'HILO8',
    FORMAT_L8: 'L8',
    FORMAT_A8: 'A8',
    FORMAT_LA4: 'LA4',
    FORMAT_L4: 'L4',
    FORMAT_A4: 'A4',
    FORMAT_ETC1: 'ETC1',
    FORMAT_ETC1A4: 'ETC1A4'
}

PIXEL_FORMAT_SIZE = {
    FORMAT_RGBA8: 32,
    FORMAT_RGB8: 24,
    FORMAT_RGBA5551: 16,
    FORMAT_RGB565: 16,
    FORMAT_RGBA4: 16,
    FORMAT_LA8: 16,
    FORMAT_HILO8: 16,
    FORMAT_L8: 8,
    FORMAT_A8: 8,
    FORMAT_LA4: 8,
    FORMAT_L4: 4,
    FORMAT_A4: 4,
    FORMAT_ETC1: 64,
    FORMAT_ETC1A4: 128
}

MAPPING_DIRECT = 0x00
MAPPING_TABLE = 0x01
MAPPING_SCAN = 0x02

TGLP_DATA_OFFSET = 0x2000

class Bffnt:
    def __init__(self, load_order='<'):
        self.order = load_order
        self.invalid = False
        self.file_size = 0
        self.filename = ''
        self.font_info = {}
        self.tglp = {}
        self.cwdh_sections = []
        self.cmap_sections = []
        self.version = 0x04000000
        self.filetype = 'ffnt'

    def read(self, filename):
        with open(filename, 'rb') as f:
            data = f.read()
        self.file_size = len(data)
        self.filename = filename

        self._parse_header(data[:FFNT_HEADER_SIZE])
        position = FFNT_HEADER_SIZE
        if self.invalid:
            return

        self._parse_finf(data[position:position + FINF_HEADER_SIZE])
        if self.invalid:
            return

        position = self.tglp_offset - 8
        self._parse_tglp_header(data[position:position + TGLP_HEADER_SIZE])
        if self.invalid:
            return

        cwdh = self.cwdh_offset
        self.cwdh_sections = []
        while cwdh > 0:
            position = cwdh - 8
            cwdh = self._parse_cwdh_header(data[position:position + CWDH_HEADER_SIZE])
            if self.invalid:
                return

            position += CWDH_HEADER_SIZE
            info = self.cwdh_sections[-1]
            self._parse_cwdh_data(info, data[position:position + info['size'] - CWDH_HEADER_SIZE])

        cmap = self.cmap_offset
        self.cmap_sections = []
        while cmap > 0:
            position = cmap - 8
            cmap = self._parse_cmap_header(data[position:position + CMAP_HEADER_SIZE])
            if self.invalid:
                return

            position += CMAP_HEADER_SIZE
            info = self.cmap_sections[-1]
            self._parse_cmap_data(info, data[position:position + info['size'] - CMAP_HEADER_SIZE])

        self._parse_tglp_data(data)

    def _parse_header(self, data):
        bom = struct.unpack_from('>H', data, 4)[0]
        if bom == 0xFFFE:
            self.order = '<'
        elif bom == 0xFEFF:
            self.order = '>'
        else:
            self.invalid = True
            return

        magic, bom, header_size, self.version, file_size, sections = struct.unpack(FFNT_HEADER_STRUCT % self.order, data)
        if magic not in FFNT_HEADER_MAGIC:
            self.invalid = True
            return
        self.filetype = magic.decode('ascii').lower()

    def _parse_finf(self, data):
        magic, section_size, font_type, height, width, ascent, line_feed, alter_char_idx, def_left, def_glyph_width, \
                def_char_width, encoding, tglp_offset, cwdh_offset, cmap_offset \
                = struct.unpack(FINF_HEADER_STRUCT % self.order, data)
        
        if magic != FINF_HEADER_MAGIC:
            self.invalid = True
            return

        self.font_info = {
            'height': height,
            'width': width,
            'ascent': ascent,
            'lineFeed': line_feed,
            'alterCharIdx': alter_char_idx,
            'defaultWidth': {
                'left': def_left,
                'glyphWidth': def_glyph_width,
                'charWidth': def_char_width
            },
            'fontType': font_type,
            'encoding': encoding
        }
        self.tglp_offset = tglp_offset
        self.cwdh_offset = cwdh_offset
        self.cmap_offset = cmap_offset

    def _parse_tglp_header(self, data):
        magic, section_size, cell_width, cell_height, num_sheets, max_char_width, sheet_size, baseline_position, \
                sheet_pixel_format, num_sheet_cols, num_sheet_rows, sheet_width, sheet_height, sheet_data_offset \
                = struct.unpack(TGLP_HEADER_STRUCT % self.order, data)

        if magic != TGLP_HEADER_MAGIC:
            self.invalid = True
            return

        self.tglp = {
            'size': section_size,
            'glyph': {
                'width': cell_width,
                'height': cell_height,
                'baseline': baseline_position
            },
            'sheetCount': num_sheets,
            'maxCharWidth': max_char_width,
            'sheet': {
                'size': sheet_size,
                'cols': num_sheet_cols,
                'rows': num_sheet_rows,
                'width': sheet_width,
                'height': sheet_height,
                'format': sheet_pixel_format
            },
            'sheetOffset': sheet_data_offset
        }

    def _parse_tglp_data(self, data):
        position = self.tglp['sheetOffset']
        self.tglp['sheets'] = []
        format_ = self.tglp['sheet']['format']
        for i in range(self.tglp['sheetCount']):
            sheet = data[position:position + self.tglp['sheet']['size']]
            bmp_data = self._sheet_to_bitmap(sheet)
            self.tglp['sheets'].append({
                'width': self.tglp['sheet']['width'],
                'height': self.tglp['sheet']['height'],
                'data': bmp_data
            })
            position = position + self.tglp['sheet']['size']

    def _sheet_to_bitmap(self, data, to_tglp=False):
        width = self.tglp['sheet']['width']
        height = self.tglp['sheet']['height']
        format_ = self.tglp['sheet']['format']

        data_width = width
        data_height = height

        width = 1 << int(math.ceil(math.log(width, 2)))
        height = 1 << int(math.ceil(math.log(height, 2)))

        if to_tglp:
            bmp = data
            data = [0] * self.tglp['sheet']['size']
        else:
            bmp = [[0, 0, 0, 0]] * (width * height)

        tile_width = width // 8
        tile_height = height // 8

        for tile_y in range(tile_height):
            for tile_x in range(tile_width):
                for y in range(2):
                    for x in range(2):
                        for y2 in range(2):
                            for x2 in range(2):
                                for y3 in range(2):
                                    for x3 in range(2):
                                        if tile_y * 8 + y * 4 + y2 * 2 + y3 >= data_height:
                                            continue
                                        if tile_x * 8 + x * 4 + x2 * 2 + x3 >= data_width:
                                            continue

                                        pixel_x = (x3 + (x2 * 2) + (x * 4) + (tile_x * 8))
                                        pixel_y = (y3 + (y2 * 2) + (y * 4) + (tile_y * 8))

                                        data_x = (x3 + (x2 * 4) + (x * 16) + (tile_x * 64))
                                        data_y = ((y3 * 2) + (y2 * 8) + (y * 32) + (tile_y * width * 8))

                                        data_pos = data_x + data_y
                                        bmp_pos = pixel_x + (pixel_y * width)

                                        if to_tglp:
                                            bytes_ = self._get_tglp_pixel_data(bmp, format_, bmp_pos)
                                            if len(bytes_) > 1:
                                                data[data_pos:data_pos + len(bytes_)] = bytes_
                                            else:
                                                if PIXEL_FORMAT_SIZE[format_] == 4:
                                                    data_pos //= 2
                                                data[data_pos] |= bytes_[0]
                                        else:
                                            bmp[bmp_pos] = self._get_pixel_data(data, format_, data_pos)
        if to_tglp:
            return struct.pack('%dB' % len(data), *data)
        else:
            return bmp

    def _get_pixel_data(self, data, format_, index):
        red = green = blue = alpha = 0

        if format_ == FORMAT_RGBA8:
            red, green, blue, alpha = struct.unpack('4B', data[index * 4:index * 4 + 4])
        elif format_ == FORMAT_RGB8:
            red, green, blue = struct.unpack('3B', data[index * 3:index * 3 + 3])
            alpha = 255
        elif format_ == FORMAT_RGBA5551:
            b1, b2 = struct.unpack('2B', data[index * 2:index * 2 + 2])
            red = ((b1 >> 3) & 0x1F) * 8
            green = (((b1 & 0x07) << 2) | ((b2 >> 6) & 0x03)) * 8
            blue = ((b2 >> 1) & 0x1F) * 8
            alpha = (b2 & 0x01) * 255
        elif format_ == FORMAT_RGB565:
            b1, b2 = struct.unpack('2B', data[index * 2:index * 2 + 2])
            red = ((b1 >> 3) & 0x1F) * 8
            green = (((b1 & 0x07) << 3) | ((b2 >> 5) & 0x07)) * 4
            blue = (b2 & 0x1F) * 8
            alpha = 255
        elif format_ == FORMAT_RGBA4:
            b1, b2 = struct.unpack('2B', data[index * 2:index * 2 + 2])
            red = ((b1 >> 4) & 0x0F) * 0x11
            alpha = (b1 & 0x0F) * 0x11
            blue = ((b2 >> 4) & 0x0F) * 0x11
            green = (b2 & 0x0F) * 0x11
        elif format_ == FORMAT_LA8:
            l, alpha = struct.unpack('2B', data[index * 2:index * 2 + 2])
            red = green = blue = l
        elif format_ == FORMAT_L8:
            red = green = blue = struct.unpack('B', data[index:index + 1])[0]
            alpha = 255
        elif format_ == FORMAT_A8:
            alpha = struct.unpack('B', data[index:index + 1])[0]
            red = green = blue = 255
        elif format_ == FORMAT_LA4:
            la = struct.unpack('B', data[index:index + 1])[0]
            red = green = blue = ((la >> 4) & 0x0F) * 0x11
            alpha = (la & 0x0F) * 0x11
        elif format_ == FORMAT_L4:
            l = struct.unpack('B', data[index // 2:index // 2 + 1])[0]
            shift = (index & 1) * 4
            red = green = blue = ((l >> shift) & 0x0F) * 0x11
            alpha = 255
        elif format_ == FORMAT_A4:
            byte = data[index // 2]
            shift = (index & 1) * 4
            alpha = ((byte >> shift) & 0x0F) * 0x11
            green = red = blue = 255

        return [red, green, blue, alpha]

    def _get_tglp_pixel_data(self, bmp, format_, index):
        red, green, blue, alpha = bmp[index]

        if format_ == FORMAT_RGBA8:
            return [red, green, blue, alpha]
        elif format_ == FORMAT_RGB8:
            return [red, green, blue]
        elif format_ == FORMAT_RGBA5551:
            r5 = (red // 8) & 0x1F
            g5 = (green // 8) & 0x1F
            b5 = (blue // 8) & 0x1F
            a = 1 if alpha > 0 else 0
            b1 = (r5 << 3) | (g5 >> 2)
            b2 = ((g5 << 6) | (b5 << 1) | a) & 0xFF
            return [b1, b2]
        elif format_ == FORMAT_RGB565:
            r5 = (red // 8) & 0x1F
            g6 = (green // 4) & 0x3F
            b5 = (blue // 8) & 0x1F
            b1 = (r5 << 3) | (g6 >> 3)
            b2 = ((g6 << 5) | b5) & 0xFF
            return [b1, b2]
        elif format_ == FORMAT_RGBA4:
            r4 = (red // 17) & 0x0F
            g4 = (green // 17) & 0x0F
            b4 = (blue // 17) & 0x0F
            a4 = (alpha // 17) & 0x0F
            b1 = (r4 << 4) | g4
            b2 = (b4 << 4) | a4
            return [b1, b2]
        elif format_ == FORMAT_LA8:
            l = int((red * 0.2126) + (green * 0.7152) + (blue * 0.0722))
            return [l, alpha]
        elif format_ == FORMAT_L8:
            l = int((red * 0.2126) + (green * 0.7152) + (blue * 0.0722))
            return [l]
        elif format_ == FORMAT_A8:
            return [alpha]
        elif format_ == FORMAT_LA4:
            l = int((red * 0.2126) + (green * 0.7152) + (blue * 0.0722)) // 17
            a = (alpha // 17) & 0x0F
            b = (l << 4) | a
            return [b]
        elif format_ == FORMAT_L4:
            l = int((red * 0.2126) + (green * 0.7152) + (blue * 0.0722)) // 17
            shift = (index & 1) * 4
            return [l << shift]
        elif format_ == FORMAT_A4:
            a = alpha // 17
            shift = (index & 1) * 4
            return [a << shift]

        return [0]

    def _parse_cwdh_header(self, data):
        magic, section_size, start_index, end_index, next_cwdh_offset \
            = struct.unpack(CWDH_HEADER_STRUCT % self.order, data)

        if magic != CWDH_HEADER_MAGIC:
            self.invalid = True
            return

        self.cwdh_sections.append({
            'size': section_size,
            'start': start_index,
            'end': end_index
        })
        return next_cwdh_offset

    def _parse_cwdh_data(self, info, data):
        count = info['end'] - info['start'] + 1
        output = []
        position = 0
        for i in range(count):
            left, glyph, char = struct.unpack('%sb2B' % self.order, data[position:position + 3])
            position += 3
            output.append({
                'left': left,
                'glyph': glyph,
                'char': char
            })
        info['data'] = output

    def _parse_cmap_header(self, data):
        magic, section_size, code_begin, code_end, map_method, unknown, next_cmap_offset \
            = struct.unpack(CMAP_HEADER_STRUCT % self.order, data)

        if magic != CMAP_HEADER_MAGIC:
            self.invalid = True

        self.cmap_sections.append({
            'size': section_size,
            'start': code_begin,
            'end': code_end,
            'type': map_method
        })
        return next_cmap_offset

    def _parse_cmap_data(self, info, data):
        type_ = info['type']
        if type_ == MAPPING_DIRECT:
            info['indexOffset'] = struct.unpack('%sH' % self.order, data[:2])[0]
        elif type_ == MAPPING_TABLE:
            count = info['end'] - info['start'] + 1
            position = 0
            output = []
            for i in range(count):
                offset = struct.unpack('%sH' % self.order, data[position:position + 2])[0]
                position += 2
                output.append(offset)
            info['indexTable'] = output
        elif type_ == MAPPING_SCAN:
            position = 0
            count = struct.unpack('%sH' % self.order, data[position:position + 2])[0]
            position += 2
            output = {}
            for i in range(count):
                code, offset = struct.unpack('%s2H' % self.order, data[position:position + 4])
                position += 4
                output[chr(code)] = offset
            info['entries'] = output

    def save(self, filename):
        file_ = open(filename, 'wb')
        section_count = 0

        bom = 0xFEFF

        # write header
        file_size_pos = 0x0C
        section_count_pos = 0x10
        magic = self.filetype.upper().encode('ascii')

        data = struct.pack(FFNT_HEADER_STRUCT % self.order, magic, bom, FFNT_HEADER_SIZE, self.version, 0, 0)
        file_.write(data)
        position = FFNT_HEADER_SIZE

        # write finf
        font_info = self.font_info
        default_width = font_info['defaultWidth']
        finf_tglp_offset_pos = position + 0x14
        finf_cwdh_offset_pos = position + 0x18
        finf_cmap_offset_pos = position + 0x1C
        
        data = struct.pack(FINF_HEADER_STRUCT % self.order, FINF_HEADER_MAGIC, FINF_HEADER_SIZE, font_info['fontType'],
                           font_info['height'], font_info['width'], font_info['ascent'], font_info['lineFeed'],
                           font_info['alterCharIdx'], default_width['left'], default_width['glyphWidth'],
                           default_width['charWidth'], font_info['encoding'], 0, 0, 0)
        file_.write(data)
        position += FINF_HEADER_SIZE
        section_count += 1

        # write tglp
        tglp = self.tglp
        sheet = tglp['sheet']
        tglp_size_pos = position + 0x04
        tglp_data_size = int(sheet['width'] * sheet['height'] * (PIXEL_FORMAT_SIZE[sheet['format']] / 8.0))

        file_.seek(finf_tglp_offset_pos)
        file_.write(struct.pack('%sI' % self.order, position + 8))
        file_.seek(position)

        tglp_start_pos = position
        data = struct.pack(TGLP_HEADER_STRUCT % self.order, TGLP_HEADER_MAGIC, 0, tglp['glyph']['width'],
                       tglp['glyph']['height'], tglp['sheetCount'], tglp['maxCharWidth'], tglp_data_size,
                       tglp['glyph']['baseline'], sheet['format'], sheet['cols'], sheet['rows'], sheet['width'],
                       sheet['height'], TGLP_DATA_OFFSET)
        file_.write(data)

        file_.seek(TGLP_DATA_OFFSET)
        position = TGLP_DATA_OFFSET
        section_count += 1

        for idx in range(tglp['sheetCount']):
            sheet_data = tglp['sheets'][idx]['data']
            data = self._sheet_to_bitmap(sheet_data, to_tglp=True)
            file_.write(data)
            position += len(data)

        file_.seek(tglp_size_pos)
        file_.write(struct.pack('%sI' % self.order, position - tglp_start_pos))

        file_.seek(finf_cwdh_offset_pos)
        file_.write(struct.pack('%sI' % self.order, position + 8))
        file_.seek(position)

        # write cwdh
        prev_cwdh_offset_pos = 0
        for cwdh in self.cwdh_sections:
            section_count += 1
            if prev_cwdh_offset_pos > 0:
                file_.seek(prev_cwdh_offset_pos)
                file_.write(struct.pack('%sI' % self.order, position + 8))
                file_.seek(position)

            size_pos = position + 0x04
            prev_cwdh_offset_pos = position + 0x0C

            start_pos = position
            data = struct.pack(CWDH_HEADER_STRUCT % self.order, CWDH_HEADER_MAGIC, 0, cwdh['start'], cwdh['end'], 0)
            file_.write(data)
            position += CWDH_HEADER_SIZE

            for code in range(cwdh['start'], cwdh['end'] + 1):
                widths = cwdh['data'][code - cwdh['start']]
                for key in ('left', 'glyph', 'char'):
                    file_.write(struct.pack('=b', widths[key]))
                    position += 1

            # Pad cwdh to 4-byte boundary
            padding_needed = (4 - (position % 4)) % 4
            if padding_needed > 0:
                file_.write(b'\x00' * padding_needed)
                position += padding_needed

            file_.seek(size_pos)
            file_.write(struct.pack('%sI' % self.order, position - start_pos))
            file_.seek(position)

        file_.seek(finf_cmap_offset_pos)
        file_.write(struct.pack('%sI' % self.order, position + 8))
        file_.seek(position)

        # write cmap
        prev_cmap_offset_pos = 0
        for cmap in self.cmap_sections:
            section_count += 1
            if prev_cmap_offset_pos > 0:
                file_.seek(prev_cmap_offset_pos)
                file_.write(struct.pack('%sI' % self.order, position + 8))
                file_.seek(position)

            size_pos = position + 0x04
            prev_cmap_offset_pos = position + 0x10

            start_pos = position
            data = struct.pack(CMAP_HEADER_STRUCT % self.order, CMAP_HEADER_MAGIC, 0, cmap['start'], cmap['end'],
                               cmap['type'], 0, 0)
            file_.write(data)
            position += CMAP_HEADER_SIZE

            if cmap['type'] == MAPPING_DIRECT:
                file_.write(struct.pack('%sH' % self.order, cmap['indexOffset']))
                position += 2
            elif cmap['type'] == MAPPING_TABLE:
                for index in cmap['indexTable']:
                    file_.write(struct.pack('%sH' % self.order, index))
                    position += 2
            elif cmap['type'] == MAPPING_SCAN:
                file_.write(struct.pack('%sH' % self.order, len(cmap['entries'])))
                position += 2
                keys = list(cmap['entries'].keys())
                keys.sort()
                for code in keys:
                    index = cmap['entries'][code]
                    file_.write(struct.pack('%s2H' % self.order, ord(code), index))
                    position += 4

            # Pad cmap to 4-byte boundary
            padding_needed = (4 - (position % 4)) % 4
            if padding_needed > 0:
                file_.write(b'\x00' * padding_needed)
                position += padding_needed

            file_.seek(size_pos)
            file_.write(struct.pack('%sI' % self.order, position - start_pos))
            file_.seek(position)

        file_.seek(file_size_pos)
        file_.write(struct.pack('%sI' % self.order, position))

        file_.seek(section_count_pos)
        file_.write(struct.pack('%sI' % self.order, section_count))
        file_.close()

    def get_character_mappings(self):
        glyph_to_chars = {}
        for cmap in self.cmap_sections:
            if cmap['type'] == MAPPING_DIRECT:
                for code in range(cmap['start'], cmap['end'] + 1):
                    glyph_idx = code - cmap['start'] + cmap['indexOffset']
                    glyph_to_chars.setdefault(glyph_idx, []).append(chr(code))
            elif cmap['type'] == MAPPING_TABLE:
                for code in range(cmap['start'], cmap['end'] + 1):
                    idx = code - cmap['start']
                    if idx < len(cmap['indexTable']):
                        glyph_idx = cmap['indexTable'][idx]
                        if glyph_idx != 0xFFFF:
                            glyph_to_chars.setdefault(glyph_idx, []).append(chr(code))
            elif cmap['type'] == MAPPING_SCAN:
                for char, glyph_idx in cmap['entries'].items():
                    glyph_to_chars.setdefault(glyph_idx, []).append(char)
        return glyph_to_chars

    def get_glyph_widths(self):
        glyph_widths = {}
        for cwdh in self.cwdh_sections:
            for index in range(cwdh['start'], cwdh['end'] + 1):
                idx = index - cwdh['start']
                if idx < len(cwdh['data']):
                    glyph_widths[index] = cwdh['data'][idx]
        return glyph_widths

    def add_mapping(self, char, glyph_idx):
        self.remove_mapping(char)
        
        # 1. First, check if the character falls within any existing TABLE cmap section range.
        # If it does, we MUST map it in that TABLE section, otherwise the 0xFFFF entry in the
        # TABLE section will block the game from ever reading the SCAN mapping.
        for cmap in self.cmap_sections:
            if cmap['type'] == MAPPING_TABLE:
                if cmap['start'] <= ord(char) <= cmap['end']:
                    cmap['indexTable'][ord(char) - cmap['start']] = glyph_idx
                    return True
                    
        # 2. If it is not in range of any existing TABLE section, map it in the SCAN mapping
        for cmap in self.cmap_sections:
            if cmap['type'] == MAPPING_SCAN:
                cmap['entries'][char] = glyph_idx
                cmap['start'] = min(cmap['start'], ord(char))
                cmap['end'] = max(cmap['end'], ord(char))
                return True
                
        return False

    def remove_mapping(self, char):
        removed = False
        for cmap in self.cmap_sections:
            if cmap['type'] == MAPPING_SCAN:
                if char in cmap['entries']:
                    del cmap['entries'][char]
                    removed = True
            elif cmap['type'] == MAPPING_TABLE:
                if cmap['start'] <= ord(char) <= cmap['end']:
                    idx = ord(char) - cmap['start']
                    if idx < len(cmap['indexTable']):
                        cmap['indexTable'][idx] = 0xFFFF
                        removed = True
        return removed

# ==============================================================================
# Tkinter GUI implementation (Sleek Dark Theme)
# ==============================================================================

class PixelEditorWindow(tk.Toplevel):
    clipboard_pixels = None
    clipboard_w = None
    clipboard_h = None

    def __init__(self, parent, glyph_index, cell_w, cell_h, current_pixels, on_save_callback):
        super().__init__(parent.root)
        self.parent = parent
        self.glyph_index = glyph_index
        parent.open_editors[glyph_index] = self
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.on_save_callback = on_save_callback
        
        self.pixels = [list(p) for p in current_pixels]
        self.history = []
        
        self.title(f"Pixel Editor - Glyph {glyph_index}")
        self.geometry("640x730")
        self.minsize(550, 650)
        self.transient(parent.root)
        self.configure(bg=parent.bg_dark)
        
        self.brush_color = [255, 255, 255, 255]
        
        self.editor_mode = "pencil"
        self.selection_start = None
        self.selection_end = None
        self.active_selection = None
        
        # Calculate pixel grid scale
        max_dim = max(cell_w, cell_h)
        self.pixel_scale = max(8, min(24, 360 // max_dim))
        self.canvas_w = cell_w * self.pixel_scale
        self.canvas_h = cell_h * self.pixel_scale
        
        self.create_widgets()
        self.draw_grid()
        
        # Bind keyboard shortcuts
        self.bind("<Control-c>", lambda e: self.copy_to_clipboard())
        self.bind("<Control-v>", lambda e: self.paste_from_clipboard())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-s>", lambda e: self.on_save_click())
        self.canvas.bind("<Control-c>", lambda e: self.copy_to_clipboard())
        self.canvas.bind("<Control-v>", lambda e: self.paste_from_clipboard())
        self.canvas.bind("<Control-z>", lambda e: self.undo())
        self.canvas.bind("<Control-s>", lambda e: self.on_save_click())
        
        self.update_idletasks()
        x = parent.root.winfo_x() + (parent.root.winfo_width() - self.winfo_width()) // 2
        y = parent.root.winfo_y() + (parent.root.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        main_frame = ttk.Frame(self, style='Panel.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Left side: Canvas inside a container to center it
        canvas_container = ttk.Frame(main_frame, style='Panel.TFrame')
        canvas_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(canvas_container, bg="#111111", highlightthickness=1, 
                                highlightbackground=self.parent.border_color, 
                                width=self.canvas_w, height=self.canvas_h)
        self.canvas.pack(expand=True)
        
        # Bind events
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<B3-Motion>", self.on_canvas_right_drag)
        
        # Right side: controls panel
        right_col = ttk.Frame(main_frame, style='Panel.TFrame', width=200)
        right_col.pack(side=tk.RIGHT, fill=tk.Y, padx=(15, 0))
        
        # Tool Mode Switcher
        ttk.Label(right_col, text="Editor Mode", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(0, 2))
        mode_frame = ttk.Frame(right_col, style='Panel.TFrame')
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_pencil_mode = ttk.Button(mode_frame, text="✏️ Pencil Tool [ON]", command=lambda: self.set_editor_mode("pencil"))
        self.btn_pencil_mode.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        
        self.btn_select_mode = ttk.Button(mode_frame, text="🔲 Select Tool", command=lambda: self.set_editor_mode("select"))
        self.btn_select_mode.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        # Brush Intensity
        ttk.Label(right_col, text="Brush Opacity", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(0, 2))
        
        self.alpha_var = tk.IntVar(value=255)
        self.scale_alpha = tk.Scale(right_col, from_=0, to=255, orient=tk.HORIZONTAL, variable=self.alpha_var,
                                    bg=self.parent.bg_card, fg=self.parent.fg_light, highlightthickness=0,
                                    troughcolor="#1e1e1e", activebackground=self.parent.bg_selected)
        self.scale_alpha.pack(fill=tk.X, pady=(0, 10))
        
        # Presets
        ttk.Label(right_col, text="Brush Presets", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        presets_frame = ttk.Frame(right_col, style='Panel.TFrame')
        presets_frame.pack(fill=tk.X, pady=(0, 15))
        
        presets = [
            ("Solid White (100%)", 255),
            ("Medium Gray (50%)", 128),
            ("Soft Shadow (25%)", 64),
            ("Eraser (0%)", 0)
        ]
        for label, a_val in presets:
            btn = ttk.Button(presets_frame, text=label, command=lambda a=a_val: self.set_alpha_preset(a))
            btn.pack(fill=tk.X, pady=2)
            
        ttk.Label(right_col, text="Canvas Tools", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        
        self.btn_undo = ttk.Button(right_col, text="↩️ Undo (Ctrl+Z)", command=self.undo, state="disabled")
        self.btn_undo.pack(fill=tk.X, pady=2)
        
        ttk.Button(right_col, text="🧹 Clear All", command=self.clear_all).pack(fill=tk.X, pady=2)
        ttk.Button(right_col, text="🪣 Fill All", command=self.fill_all).pack(fill=tk.X, pady=2)
        ttk.Button(right_col, text="🔄 Invert", command=self.invert_pixels).pack(fill=tk.X, pady=2)
        ttk.Button(right_col, text="🎨 Choose Color...", command=self.choose_custom_color).pack(fill=tk.X, pady=(2, 10))
        
        # Clipboard frame
        ttk.Label(right_col, text="Clipboard", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        clip_frame = ttk.Frame(right_col, style='Panel.TFrame')
        clip_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(clip_frame, text="📋 Copy (Ctrl+C)", command=self.copy_to_clipboard).pack(fill=tk.X, pady=2)
        ttk.Button(clip_frame, text="📋 Paste (Ctrl+V)", command=self.paste_from_clipboard).pack(fill=tk.X, pady=2)
        
        # Bottom controls in sidebar
        btn_frame = ttk.Frame(right_col, style='Panel.TFrame')
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        btn_save = ttk.Button(btn_frame, text="Apply & Save", style='Accent.TButton', command=self.on_save_click)
        btn_save.pack(fill=tk.X, pady=2, ipady=3)
        
        btn_cancel = ttk.Button(btn_frame, text="Cancel", command=self.destroy)
        btn_cancel.pack(fill=tk.X, pady=2)

    def set_editor_mode(self, mode):
        self.editor_mode = mode
        if mode == "pencil":
            self.btn_pencil_mode.config(text="✏️ Pencil Tool [ON]")
            self.btn_select_mode.config(text="🔲 Select Tool")
            self.active_selection = None
            self.selection_start = None
            self.selection_end = None
            self.canvas.delete("selection_outline")
        else:
            self.btn_pencil_mode.config(text="✏️ Pencil Tool")
            self.btn_select_mode.config(text="🔲 Select Tool [ON]")

    def copy_to_clipboard(self):
        if self.active_selection:
            sc, sr, ec, er = self.active_selection
            w = ec - sc + 1
            h = er - sr + 1
            copied_pixels = []
            for r in range(sr, er + 1):
                for c in range(sc, ec + 1):
                    copied_pixels.append(self.pixels[r * self.cell_w + c])
            PixelEditorWindow.clipboard_pixels = [list(p) for p in copied_pixels]
            PixelEditorWindow.clipboard_w = w
            PixelEditorWindow.clipboard_h = h
            self.parent.lbl_status.config(text=f"Copied selection ({w}x{h}) of glyph {self.glyph_index} to clipboard.")
        else:
            PixelEditorWindow.clipboard_pixels = [list(p) for p in self.pixels]
            PixelEditorWindow.clipboard_w = self.cell_w
            PixelEditorWindow.clipboard_h = self.cell_h
            self.parent.lbl_status.config(text=f"Copied all {self.cell_w}x{self.cell_h} pixels of glyph {self.glyph_index} to clipboard.")
        
        # Write to system clipboard as JSON so other editor instances can read it
        try:
            import json
            clip_data = {
                "type": "bffnt_editor_pixels",
                "width": PixelEditorWindow.clipboard_w,
                "height": PixelEditorWindow.clipboard_h,
                "pixels": PixelEditorWindow.clipboard_pixels
            }
            self.clipboard_clear()
            self.clipboard_append(json.dumps(clip_data))
        except Exception as e:
            print(f"Error copying to system clipboard: {e}")
        
    def paste_from_clipboard(self):
        # Try to read from the system clipboard first
        try:
            import json
            clip_text = self.clipboard_get()
            if clip_text:
                clip_data = json.loads(clip_text)
                if isinstance(clip_data, dict) and clip_data.get("type") == "bffnt_editor_pixels":
                    PixelEditorWindow.clipboard_pixels = clip_data["pixels"]
                    PixelEditorWindow.clipboard_w = clip_data["width"]
                    PixelEditorWindow.clipboard_h = clip_data["height"]
        except Exception:
            # Fall back to in-memory class variables if system clipboard doesn't contain valid pixel data
            pass

        if not PixelEditorWindow.clipboard_pixels:
            messagebox.showwarning("Clipboard Empty", "No pixels have been copied to the clipboard yet.", parent=self)
            return
            
        self.save_history()
        if self.active_selection:
            start_col, start_row, _, _ = self.active_selection
        else:
            start_col, start_row = 0, 0
            
        for r in range(PixelEditorWindow.clipboard_h):
            target_row = start_row + r
            if target_row >= self.cell_h:
                break
            for c in range(PixelEditorWindow.clipboard_w):
                target_col = start_col + c
                if target_col >= self.cell_w:
                    break
                src_idx = r * PixelEditorWindow.clipboard_w + c
                self.pixels[target_row * self.cell_w + target_col] = list(PixelEditorWindow.clipboard_pixels[src_idx])
            
        self.draw_grid()
        self.parent.lbl_status.config(text=f"Pasted clipboard ({PixelEditorWindow.clipboard_w}x{PixelEditorWindow.clipboard_h}) at ({start_col}, {start_row}).")

    def draw_grid(self):
        self.rect_ids = {}
        self.canvas.delete("all")
        for row in range(self.cell_h):
            for col in range(self.cell_w):
                x1 = col * self.pixel_scale
                y1 = row * self.pixel_scale
                x2 = x1 + self.pixel_scale
                y2 = y1 + self.pixel_scale
                
                bg_color = "#202020" if (col + row) % 2 == 1 else "#151515"
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=bg_color, outline="#2d2d2d", width=1)
                
                pixel_val = self.pixels[row * self.cell_w + col]
                color_hex = self.get_blended_hex(col, row, pixel_val)
                rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, fill=color_hex, outline="", width=0)
                self.rect_ids[(col, row)] = rect_id
        if self.active_selection:
            self.draw_selection_visual()

    def get_blended_hex(self, col, row, rgba):
        if rgba[3] == 0:
            return ""
        bg_rgb = (32, 32, 32) if (col + row) % 2 == 1 else (21, 21, 21)
        if rgba[3] == 255:
            return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"
        alpha_frac = rgba[3] / 255.0
        r = int(rgba[0] * alpha_frac + bg_rgb[0] * (1.0 - alpha_frac))
        g = int(rgba[1] * alpha_frac + bg_rgb[1] * (1.0 - alpha_frac))
        b = int(rgba[2] * alpha_frac + bg_rgb[2] * (1.0 - alpha_frac))
        return f"#{r:02x}{g:02x}{b:02x}"

    def get_pixel_coords(self, event):
        col = event.x // self.pixel_scale
        row = event.y // self.pixel_scale
        if 0 <= col < self.cell_w and 0 <= row < self.cell_h:
            return col, row
        return None

    def set_pixel(self, col, row, color):
        idx = row * self.cell_w + col
        if self.pixels[idx] != color:
            self.pixels[idx] = list(color)
            self.update_canvas_pixel(col, row)

    def update_canvas_pixel(self, col, row):
        idx = row * self.cell_w + col
        pixel_val = self.pixels[idx]
        color_hex = self.get_blended_hex(col, row, pixel_val)
        rect_id = self.rect_ids[(col, row)]
        self.canvas.itemconfigure(rect_id, fill=color_hex)

    def set_alpha_preset(self, a_val):
        self.alpha_var.set(a_val)
        # If it is solid or shadow, reset to white brush
        if a_val > 0:
            self.brush_color = [255, 255, 255, 255]

    def draw_selection_visual(self):
        self.canvas.delete("selection_outline")
        if self.selection_start is None or self.selection_end is None:
            return
        c1, r1 = self.selection_start
        c2, r2 = self.selection_end
        
        start_col = min(c1, c2)
        end_col = max(c1, c2)
        start_row = min(r1, r2)
        end_row = max(r1, r2)
        
        x1 = start_col * self.pixel_scale
        y1 = start_row * self.pixel_scale
        x2 = (end_col + 1) * self.pixel_scale
        y2 = (end_row + 1) * self.pixel_scale
        
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="#00ffcc", dash=(4, 4), width=2, tags="selection_outline")

    def on_canvas_click(self, event):
        coords = self.get_pixel_coords(event)
        if coords:
            if self.editor_mode == "select":
                self.selection_start = coords
                self.selection_end = coords
                self.active_selection = None
                self.canvas.delete("selection_outline")
            else:
                self.save_history()
                col, row = coords
                color = [self.brush_color[0], self.brush_color[1], self.brush_color[2], self.alpha_var.get()]
                self.set_pixel(col, row, color)

    def on_canvas_drag(self, event):
        coords = self.get_pixel_coords(event)
        if coords:
            if self.editor_mode == "select":
                if self.selection_start:
                    self.selection_end = coords
                    self.draw_selection_visual()
            else:
                col, row = coords
                color = [self.brush_color[0], self.brush_color[1], self.brush_color[2], self.alpha_var.get()]
                self.set_pixel(col, row, color)

    def on_canvas_release(self, event):
        if self.editor_mode == "select":
            if self.selection_start and self.selection_end:
                c1, r1 = self.selection_start
                c2, r2 = self.selection_end
                start_col = min(c1, c2)
                end_col = max(c1, c2)
                start_row = min(r1, r2)
                end_row = max(r1, r2)
                self.active_selection = (start_col, start_row, end_col, end_row)
                self.draw_selection_visual()

    def on_canvas_right_click(self, event):
        coords = self.get_pixel_coords(event)
        if coords:
            if self.editor_mode == "select":
                # Right click clears selection in select mode
                self.active_selection = None
                self.selection_start = None
                self.selection_end = None
                self.canvas.delete("selection_outline")
            else:
                self.save_history()
                col, row = coords
                self.set_pixel(col, row, [0, 0, 0, 0])

    def on_canvas_right_drag(self, event):
        coords = self.get_pixel_coords(event)
        if coords:
            if self.editor_mode != "select":
                col, row = coords
                self.set_pixel(col, row, [0, 0, 0, 0])

    def choose_custom_color(self):
        from tkinter import colorchooser
        init_hex = f"#{self.brush_color[0]:02x}{self.brush_color[1]:02x}{self.brush_color[2]:02x}"
        color = colorchooser.askcolor(initialcolor=init_hex, title="Select Brush Color")
        if color[0]:
            r, g, b = [int(c) for c in color[0]]
            self.brush_color = [r, g, b, 255]
            self.alpha_var.set(255)

    def clear_all(self):
        self.save_history()
        for row in range(self.cell_h):
            for col in range(self.cell_w):
                idx = row * self.cell_w + col
                self.pixels[idx] = [0, 0, 0, 0]
                self.update_canvas_pixel(col, row)

    def fill_all(self):
        self.save_history()
        color = [self.brush_color[0], self.brush_color[1], self.brush_color[2], self.alpha_var.get()]
        for row in range(self.cell_h):
            for col in range(self.cell_w):
                idx = row * self.cell_w + col
                self.pixels[idx] = list(color)
                self.update_canvas_pixel(col, row)

    def invert_pixels(self):
        self.save_history()
        for row in range(self.cell_h):
            for col in range(self.cell_w):
                idx = row * self.cell_w + col
                pixel = self.pixels[idx]
                pixel[0] = 255 - pixel[0]
                pixel[1] = 255 - pixel[1]
                pixel[2] = 255 - pixel[2]
                pixel[3] = 255 - pixel[3]
                self.update_canvas_pixel(col, row)

    def save_history(self):
        # Save exact copy of pixel values
        self.history.append([list(p) for p in self.pixels])
        if len(self.history) > 50:
            self.history.pop(0)
        self.btn_undo.config(state="normal")

    def undo(self, event=None):
        if not self.history:
            return
        self.pixels = self.history.pop()
        self.draw_grid()
        if not self.history:
            self.btn_undo.config(state="disabled")

    def on_save_click(self, event=None):
        self.on_save_callback(self.pixels)
        self.destroy()

    def destroy(self):
        if hasattr(self, 'parent') and hasattr(self.parent, 'open_editors'):
            if self.glyph_index in self.parent.open_editors:
                del self.parent.open_editors[self.glyph_index]
        super().destroy()

class BFFNTApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Antigravity BFFNT Font Editor")
        self.root.geometry("1300x750")
        self.root.minsize(1200, 680)

        # Style colors
        self.bg_dark = "#1e1e1e"
        self.bg_card = "#252526"
        self.bg_selected = "#007acc"
        self.fg_light = "#f5f5f5"
        self.fg_dim = "#aaaaaa"
        self.border_color = "#3c3c3c"
        self.accent_color = "#007acc"

        self.bffnt = None
        self.current_filepath = None
        self.is_modified = False
        self.character_mappings = {}
        self.glyph_widths = {}
        self.selected_glyph_index = None
        self.open_editors = {}
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.apply_filter())

        self.apply_theme()
        self.create_widgets()
        self.setup_drag_and_drop()

    def apply_theme(self):
        self.root.configure(bg=self.bg_dark)
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=self.bg_dark, foreground=self.fg_light, font=("Segoe UI", 10))
        style.configure("TFrame", background=self.bg_dark)
        style.configure("Panel.TFrame", background=self.bg_card)
        
        style.configure("TLabel", background=self.bg_dark, foreground=self.fg_light)
        style.configure("Panel.TLabel", background=self.bg_card, foreground=self.fg_light)
        style.configure("Title.TLabel", background=self.bg_card, foreground=self.fg_light, font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", background=self.bg_card, foreground=self.fg_dim, font=("Segoe UI", 9))
        
        style.configure("TButton", background="#3c3c3c", foreground=self.fg_light, borderwidth=1, focuscolor="none")
        style.map("TButton", background=[("active", "#4c4c4c"), ("pressed", "#5c5c5c")])
        
        style.configure("Accent.TButton", background=self.accent_color, foreground=self.fg_light, borderwidth=0, focuscolor="none")
        style.map("Accent.TButton", background=[("active", "#108ad4"), ("pressed", "#209ae4")])

        # Treeview styling
        style.configure("Treeview", background=self.bg_card, fieldbackground=self.bg_card, foreground=self.fg_light, borderwidth=0, rowheight=24)
        style.map("Treeview", background=[("selected", self.bg_selected)], foreground=[("selected", self.fg_light)])
        style.configure("Treeview.Heading", background="#2d2d30", foreground=self.fg_light, borderwidth=1, font=("Segoe UI", 10, "bold"))
        style.map("Treeview.Heading", background=[("active", "#3e3e42")])

        # Combobox styling (style background to match dark background color)
        style.configure("TCombobox", background=self.bg_dark, fieldbackground=self.bg_dark, foreground=self.fg_light, bordercolor=self.border_color, arrowcolor=self.fg_light)
        style.map("TCombobox", 
                  fieldbackground=[("readonly", self.bg_dark), ("active", self.bg_dark), ("disabled", self.bg_dark)], 
                  background=[("readonly", self.bg_dark), ("active", self.bg_dark), ("disabled", self.bg_dark)],
                  foreground=[("disabled", self.fg_dim)],
                  arrowcolor=[("disabled", self.fg_dim)])
        self.root.option_add("*TCombobox*Listbox.background", self.bg_dark)
        self.root.option_add("*TCombobox*Listbox.foreground", self.fg_light)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.bg_selected)

    def create_widgets(self):
        # Create Menu
        menubar = tk.Menu(self.root, bg=self.bg_card, fg=self.fg_light, activebackground=self.bg_selected)
        filemenu = tk.Menu(menubar, tearoff=0, bg=self.bg_card, fg=self.fg_light, activebackground=self.bg_selected)
        filemenu.add_command(label="Open BFFNT...", command=self.on_open, accelerator="Ctrl+O")
        filemenu.add_command(label="Save", command=self.on_save, accelerator="Ctrl+S")
        filemenu.add_command(label="Save As...", command=self.on_save_as, accelerator="Ctrl+Shift+S")
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        self.root.bind("<Control-o>", self.on_open)
        self.root.bind("<Control-s>", self.on_save)
        self.root.bind("<Control-Shift-S>", self.on_save_as)
        self.root.bind("<Control-Shift-s>", self.on_save_as)
        self.root.bind("<Control-d>", self.add_mapping_ui)
        self.root.bind("<Control-f>", self.remove_mapping_ui)
        self.root.bind("<Control-l>", self.export_glyph_png)
        self.root.bind("<Control-m>", self.import_glyph_png)
        self.root.bind("<Control-Return>", self.apply_glyph_metrics)
        self.root.bind("<Control-e>", self.export_sheet)
        self.root.bind("<Control-r>", self.import_sheet)
        self.root.bind("<Control-q>", self.add_new_sheet)
        self.root.bind("<Control-w>", self.remove_last_sheet)
        self.root.bind("<Control-k>", self.open_pixel_editor)

        # Main Layout: 2 Panels (Left Sidebar + Right Editor)
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # ----------------------------------------------------------------------
        # LEFT PANEL (Metadata & Sheet preview)
        # ----------------------------------------------------------------------
        left_panel = ttk.Frame(main_paned, style='Panel.TFrame')
        main_paned.add(left_panel, weight=0)

        left_content = ttk.Frame(left_panel, style='Panel.TFrame')
        left_content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        ttk.Label(left_content, text="Font Metadata", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))

        # Metadata grid
        meta_grid = ttk.Frame(left_content, style='Panel.TFrame')
        meta_grid.pack(fill=tk.X, pady=(0, 15))
        
        self.meta_labels = {}
        fields = [
            ("Height", "N/A"), ("Width", "N/A"), ("Ascent", "N/A"), 
            ("Line Feed", "N/A"), ("Type", "N/A"), ("Encoding", "N/A"), 
            ("Sheets", "N/A"), ("Glyphs", "N/A")
        ]
        for idx, (label, val) in enumerate(fields):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(meta_grid, text=f"{label}:", style='Panel.TLabel', font=('Segoe UI', 9, 'bold')).grid(row=row, column=col, sticky=tk.W, padx=(5, 5), pady=2)
            lbl_val = ttk.Label(meta_grid, text=val, style='Panel.TLabel', font=('Segoe UI', 9))
            lbl_val.grid(row=row, column=col+1, sticky=tk.W, padx=(0, 10), pady=2)
            self.meta_labels[label] = lbl_val

        # Separator
        ttk.Separator(left_content, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        ttk.Label(left_content, text="Texture Sheet Viewer", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))

        # Sheet selector
        sheet_sel_frame = ttk.Frame(left_content, style='Panel.TFrame')
        sheet_sel_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(sheet_sel_frame, text="Sheet:", style='Panel.TLabel').pack(side=tk.LEFT, padx=(0, 5))
        self.sheet_combo = ttk.Combobox(sheet_sel_frame, state="disabled", width=15)
        self.sheet_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.sheet_combo.bind("<<ComboboxSelected>>", self.on_sheet_changed)

        # Sheet canvas thumbnail
        self.sheet_canvas = tk.Canvas(left_content, bg="#111111", highlightthickness=1, highlightbackground=self.border_color, width=280, height=280)
        self.sheet_canvas.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Import / Export Sheet Buttons
        sheet_btns = ttk.Frame(left_content, style='Panel.TFrame')
        sheet_btns.pack(fill=tk.X, pady=(0, 5))
        self.btn_export_sheet = ttk.Button(sheet_btns, text="Export Sheet... (Ctrl+E)", state="disabled", command=self.export_sheet)
        self.btn_export_sheet.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.btn_import_sheet = ttk.Button(sheet_btns, text="Import Sheet... (Ctrl+R)", state="disabled", command=self.import_sheet)
        self.btn_import_sheet.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        self.btn_add_sheet = ttk.Button(left_content, text="➕ Add New Sheet (Ctrl+Q)", state="disabled", command=self.add_new_sheet)
        self.btn_add_sheet.pack(fill=tk.X, pady=(5, 2))

        self.btn_remove_sheet = ttk.Button(left_content, text="➖ Remove Last Sheet (Ctrl+W)", state="disabled", command=self.remove_last_sheet)
        self.btn_remove_sheet.pack(fill=tk.X, pady=(2, 5))


        # ----------------------------------------------------------------------
        # RIGHT PANEL (Glyph metrics & Character List)
        # ----------------------------------------------------------------------
        right_panel = ttk.Frame(main_paned, style='TFrame')
        main_paned.add(right_panel, weight=1)

        # Upper Part: Search & Character list
        list_frame = ttk.Frame(right_panel, style='TFrame')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=(10, 0))

        # Search Bar
        search_frame = ttk.Frame(list_frame, style='TFrame')
        search_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(search_frame, text="Search Glyphs:", style='TLabel', font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        self.entry_search = tk.Entry(search_frame, textvariable=self.search_var, bg="#2d2d30", fg=self.fg_light, insertbackground=self.fg_light, borderwidth=1, relief=tk.FLAT, font=("Segoe UI", 10))
        self.entry_search.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        # Character Table Treeview
        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.glyph_tree = ttk.Treeview(list_frame, columns=("Index", "Char", "Unicode", "Left", "Glyph", "TotalWidth"), show="headings", yscrollcommand=tree_scroll.set)
        self.glyph_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.config(command=self.glyph_tree.yview)

        # Define columns
        cols_config = [
            ("Index", "Glyph Index", 80),
            ("Char", "Char", 60),
            ("Unicode", "Unicode Code", 120),
            ("Left", "Left Margin (left)", 100),
            ("Glyph", "Glyph Width (glyph)", 100),
            ("TotalWidth", "Horizontal Advance (char)", 120)
        ]
        for cid, text, width in cols_config:
            self.glyph_tree.heading(cid, text=text, anchor=tk.CENTER)
            self.glyph_tree.column(cid, width=width, anchor=tk.CENTER)

        self.glyph_tree.bind("<<TreeviewSelect>>", self.on_glyph_selected)

        # Bottom Part: Metrics Editor Canvas & Real-time Spacing Preview
        editor_frame = ttk.Frame(right_panel, style='Panel.TFrame')
        editor_frame.pack(fill=tk.X, expand=False, padx=(10, 0), pady=(15, 0))

        editor_content = ttk.Frame(editor_frame, style='Panel.TFrame')
        editor_content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        ttk.Label(editor_content, text="Real-time Visual Spacing Editor & Glyph Manager", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))

        editor_cols = ttk.Frame(editor_content, style='Panel.TFrame')
        editor_cols.pack(fill=tk.BOTH, expand=True)

        # Col 1: Visual Canvas Preview & Edit Pixels Button
        col1_frame = ttk.Frame(editor_cols, style='Panel.TFrame')
        col1_frame.pack(side=tk.LEFT, padx=(0, 20), anchor=tk.NW)

        self.preview_canvas = tk.Canvas(col1_frame, bg="#111111", highlightthickness=1, highlightbackground=self.border_color, width=220, height=220)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        self.preview_canvas.bind("<Double-Button-1>", lambda e: self.open_pixel_editor())

        self.btn_edit_pixels = ttk.Button(col1_frame, text="✏️ Edit Pixels (Ctrl+K)", command=self.open_pixel_editor, state="disabled")
        self.btn_edit_pixels.pack(fill=tk.X, pady=(5, 0), ipady=2)

        # Col 2: Metric Sliders & Spinboxes
        sliders_frame = ttk.Frame(editor_cols, style='Panel.TFrame')
        sliders_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, anchor=tk.NW)

        # Metric left
        ttk.Label(sliders_frame, text="Left Spacing Margin (left):", style='Panel.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        self.val_left = tk.IntVar(value=0)
        self.spin_left = tk.Spinbox(sliders_frame, from_=-128, to=127, textvariable=self.val_left, bg="#2d2d30", fg=self.fg_light, buttonbackground="#3c3c3c", bd=0, font=("Segoe UI", 10), width=8, command=self.on_slider_spin_change)
        self.spin_left.pack(anchor=tk.W, pady=(0, 5))
        self.spin_left.bind("<KeyRelease>", lambda e: self.on_slider_spin_change())

        # Metric glyph
        ttk.Label(sliders_frame, text="Glyph Rendering Width (glyph):", style='Panel.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        self.val_glyph = tk.IntVar(value=0)
        self.spin_glyph = tk.Spinbox(sliders_frame, from_=0, to=255, textvariable=self.val_glyph, bg="#2d2d30", fg=self.fg_light, buttonbackground="#3c3c3c", bd=0, font=("Segoe UI", 10), width=8, command=self.on_slider_spin_change)
        self.spin_glyph.pack(anchor=tk.W, pady=(0, 5))
        self.spin_glyph.bind("<KeyRelease>", lambda e: self.on_slider_spin_change())

        # Metric char (total advance width)
        ttk.Label(sliders_frame, text="Horizontal Advance Width (char):", style='Panel.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        self.val_char = tk.IntVar(value=0)
        self.spin_char = tk.Spinbox(sliders_frame, from_=-128, to=127, textvariable=self.val_char, bg="#2d2d30", fg=self.fg_light, buttonbackground="#3c3c3c", bd=0, font=("Segoe UI", 10), width=8, command=self.on_slider_spin_change)
        self.spin_char.pack(anchor=tk.W, pady=(0, 15))
        self.spin_char.bind("<KeyRelease>", lambda e: self.on_slider_spin_change())

        # Save Metrics Button
        self.btn_apply_metrics = ttk.Button(sliders_frame, text="Apply Metric Changes (Ctrl+Enter)", style='Accent.TButton', command=self.apply_glyph_metrics, state="disabled")
        self.btn_apply_metrics.pack(anchor=tk.W, ipady=3, ipadx=10)

        # Col 3: Glyph Actions & Mappings
        ops_frame = ttk.Frame(editor_cols, style='Panel.TFrame')
        ops_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 0), anchor=tk.NW)

        ttk.Label(ops_frame, text="Single Glyph I/O", style='Panel.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        
        io_btn_frame = ttk.Frame(ops_frame, style='Panel.TFrame')
        io_btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_export_glyph = ttk.Button(io_btn_frame, text="Export Glyph PNG... (Ctrl+L)", command=self.export_glyph_png, state="disabled")
        self.btn_export_glyph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_import_glyph = ttk.Button(io_btn_frame, text="Import Glyph PNG... (Ctrl+M)", command=self.import_glyph_png, state="disabled")
        self.btn_import_glyph.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        ttk.Label(ops_frame, text="Character Mappings", style='Panel.TLabel', font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(5, 2))
        
        # Mappings listbox with scrollbar
        map_list_frame = ttk.Frame(ops_frame, style='Panel.TFrame')
        map_list_frame.pack(fill=tk.BOTH, expand=True)
        
        map_scroll = ttk.Scrollbar(map_list_frame, orient=tk.VERTICAL)
        map_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.mapping_listbox = tk.Listbox(map_list_frame, bg="#2d2d30", fg=self.fg_light, highlightthickness=0, selectbackground=self.bg_selected, font=("Segoe UI", 9), yscrollcommand=map_scroll.set)
        self.mapping_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        map_scroll.config(command=self.mapping_listbox.yview)
        
        # Mapping buttons
        map_btn_frame = ttk.Frame(ops_frame, style='Panel.TFrame')
        map_btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.btn_add_mapping = ttk.Button(map_btn_frame, text="➕ Add (Ctrl+D)", command=self.add_mapping_ui, state="disabled")
        self.btn_add_mapping.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        self.btn_remove_mapping = ttk.Button(map_btn_frame, text="➖ Remove (Ctrl+F)", command=self.remove_mapping_ui, state="disabled")
        self.btn_remove_mapping.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))

        # Status Bar
        status_frame = ttk.Frame(self.root, style='Panel.TFrame', height=24)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        self.lbl_status = ttk.Label(status_frame, text="Ready. Open a .bffnt file to start editing.", style='Status.TLabel')
        self.lbl_status.pack(side=tk.LEFT, padx=10, pady=2)

    def load_bffnt_file(self, path):
        try:
            self.bffnt = Bffnt()
            self.bffnt.read(path)
            if self.bffnt.invalid:
                messagebox.showerror("Invalid File", "Failed to parse BFFNT. Invalid magic bytes or format.")
                self.bffnt = None
                return

            self.current_filepath = path
            self.is_modified = False
            self.selected_glyph_index = None

            # Get metadata mapping
            self.character_mappings = self.bffnt.get_character_mappings()
            self.glyph_widths = self.bffnt.get_glyph_widths()

            # Refresh UI
            self.refresh_metadata()
            self.refresh_sheet_view()
            self.refresh_glyph_table()
            self.lbl_status.config(text=f"Loaded successfully: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load BFFNT:\n{str(e)}")
            self.bffnt = None

    def refresh_metadata(self):
        info = self.bffnt.font_info
        tglp = self.bffnt.tglp
        
        self.meta_labels["Height"].config(text=str(info['height']))
        self.meta_labels["Width"].config(text=str(info['width']))
        self.meta_labels["Ascent"].config(text=str(info['ascent']))
        self.meta_labels["Line Feed"].config(text=str(info['lineFeed']))
        self.meta_labels["Type"].config(text=f"0x{info['fontType']:02x}")
        self.meta_labels["Encoding"].config(text=f"{info['encoding']}")
        self.meta_labels["Sheets"].config(text=str(tglp['sheetCount']))
        
        total_glyphs = tglp['sheetCount'] * tglp['sheet']['cols'] * tglp['sheet']['rows']
        self.meta_labels["Glyphs"].config(text=str(total_glyphs))

        # Enable sheet combos and buttons
        self.sheet_combo.config(state="readonly")
        self.sheet_combo['values'] = [f"Sheet {i}" for i in range(tglp['sheetCount'])]
        self.sheet_combo.current(0)
        
        self.btn_export_sheet.config(state="normal")
        self.btn_import_sheet.config(state="normal")
        self.btn_add_sheet.config(state="normal")
        self.btn_remove_sheet.config(state="normal" if tglp['sheetCount'] > 1 else "disabled")


    def refresh_sheet_view(self):
        if not self.bffnt:
            return
        idx = self.sheet_combo.current()
        sheet = self.bffnt.tglp['sheets'][idx]
        width, height = sheet['width'], sheet['height']

        # Flatten and convert [r,g,b,a] to Image
        flat_data = bytes([c for pixel in sheet['data'] for c in pixel])
        img = Image.frombytes("RGBA", (width, height), flat_data)
        
        # Scale to canvas size
        canvas_w = self.sheet_canvas.winfo_width()
        canvas_h = self.sheet_canvas.winfo_height()
        if canvas_w < 10: canvas_w = 280
        if canvas_h < 10: canvas_h = 280

        img.thumbnail((canvas_w - 4, canvas_h - 4), Image.Resampling.LANCZOS)
        
        # Draw on canvas
        self.sheet_photo = ImageTk.PhotoImage(img)
        self.sheet_canvas.delete("all")
        self.sheet_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.sheet_photo)

    def on_sheet_changed(self, event):
        self.refresh_sheet_view()

    def refresh_glyph_table(self):
        # Clear
        for item in self.glyph_tree.get_children():
            self.glyph_tree.delete(item)

        if not self.bffnt:
            return

        tglp = self.bffnt.tglp
        total_glyphs = tglp['sheetCount'] * tglp['sheet']['cols'] * tglp['sheet']['rows']

        for glyph_idx in range(total_glyphs):
            chars = self.character_mappings.get(glyph_idx, [])
            char_str = chars[0] if chars else ""
            unicode_str = ", ".join([f"U+{ord(c):04X}" for c in chars]) if chars else ""

            # Check widths
            widths = self.glyph_widths.get(glyph_idx, {"left": 0, "glyph": 0, "char": 0})
            
            self.glyph_tree.insert("", tk.END, values=(
                glyph_idx,
                char_str,
                unicode_str,
                widths["left"],
                widths["glyph"],
                widths["char"]
            ))

    def apply_filter(self):
        query = self.search_var.get().strip().lower()
        if not self.bffnt:
            return
        
        # Re-populate using search criteria
        for item in self.glyph_tree.get_children():
            self.glyph_tree.delete(item)

        tglp = self.bffnt.tglp
        total_glyphs = tglp['sheetCount'] * tglp['sheet']['cols'] * tglp['sheet']['rows']

        for glyph_idx in range(total_glyphs):
            chars = self.character_mappings.get(glyph_idx, [])
            char_str = chars[0] if chars else ""
            unicode_str = ", ".join([f"U+{ord(c):04X}" for c in chars]) if chars else ""
            widths = self.glyph_widths.get(glyph_idx, {"left": 0, "glyph": 0, "char": 0})

            # Check matches (only search the Char column)
            match = False
            if not query:
                match = True
            elif query in char_str.lower():
                match = True

            if match:
                self.glyph_tree.insert("", tk.END, values=(
                    glyph_idx,
                    char_str,
                    unicode_str,
                    widths["left"],
                    widths["glyph"],
                    widths["char"]
                ))

    def on_glyph_selected(self, event):
        sel = self.glyph_tree.selection()
        if not sel:
            return
        values = self.glyph_tree.item(sel[0], "values")
        self.selected_glyph_index = int(values[0])

        widths = self.glyph_widths.get(self.selected_glyph_index, {"left": 0, "glyph": 0, "char": 0})
        self.val_left.set(widths["left"])
        self.val_glyph.set(widths["glyph"])
        self.val_char.set(widths["char"])

        # Enable edit and mapping controls
        self.btn_edit_pixels.config(state="normal")
        self.btn_apply_metrics.config(state="normal")
        self.btn_export_glyph.config(state="normal")
        self.btn_import_glyph.config(state="normal")
        self.btn_add_mapping.config(state="normal")
        self.btn_remove_mapping.config(state="normal")

        self.refresh_mappings_list()
        self.draw_glyph_preview()

    def on_slider_spin_change(self):
        self.draw_glyph_preview()

    def draw_glyph_preview(self):
        if self.selected_glyph_index is None or not self.bffnt:
            return

        tglp = self.bffnt.tglp
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        cell_width = tglp['glyph']['width']
        cell_height = tglp['glyph']['height']

        sheet_idx = self.selected_glyph_index // (cols * rows)
        cell_idx = self.selected_glyph_index % (cols * rows)
        col = cell_idx % cols
        row = cell_idx // cols

        # Extract sub-image
        if sheet_idx >= len(tglp['sheets']):
            return
        sheet = tglp['sheets'][sheet_idx]
        
        flat_data = bytes([c for pixel in sheet['data'] for c in pixel])
        sheet_img = Image.frombytes("RGBA", (sheet['width'], sheet['height']), flat_data)

        x_left = 1 + col * (cell_width + 1)
        y_top = 1 + row * (cell_height + 1)
        glyph_crop = sheet_img.crop((x_left, y_top, x_left + cell_width, y_top + cell_height))

        scale = 6
        target_w = cell_width * scale
        target_h = cell_height * scale
        glyph_crop = glyph_crop.resize((target_w, target_h), Image.Resampling.NEAREST)

        # Base composite canvas
        final_img = Image.new("RGBA", (220, 220), (17, 17, 17, 255))
        draw = ImageDraw.Draw(final_img)

        # Draw transparency checkerboard under glyph
        square_size = 10
        for y in range(0, 220, square_size):
            for x in range(0, 220, square_size):
                if ((x // square_size) + (y // square_size)) % 2 == 1:
                    draw.rectangle([x, y, x + square_size, y + square_size], fill=(25, 25, 25, 255))

        baseline_pos_in_cell = tglp['glyph']['baseline']
        try:
            left = self.val_left.get()
        except (tk.TclError, ValueError):
            left = 0
        try:
            glyph_w = self.val_glyph.get()
        except (tk.TclError, ValueError):
            glyph_w = 0
        try:
            char_w = self.val_char.get()
        except (tk.TclError, ValueError):
            char_w = 0

        # Dynamic horizontal centering math
        midpoint_pixels = left + glyph_w / 2.0
        origin_x = 110 - int(midpoint_pixels * scale)
        cell_y = 110 - int(baseline_pos_in_cell * scale)

        # Paste character cell onto composite preview
        final_img.paste(glyph_crop, (origin_x, cell_y), glyph_crop)

        # Baseline (horizontal red line at y=110)
        draw.line([(0, 110), (220, 110)], fill=(220, 50, 50, 200), width=1)

        # Pen Origin (vertical light-blue line at origin_x)
        draw.line([(origin_x, 0), (origin_x, 220)], fill=(50, 150, 250, 150), width=1)

        # Left Margin (vertical margin line)
        margin_x = origin_x + left * scale
        draw.line([(margin_x, 0), (margin_x, 220)], fill=(100, 200, 100, 100), width=1)

        # Horizontal Advance (vertical advance line)
        advance_x = origin_x + char_w * scale
        draw.line([(advance_x, 0), (advance_x, 220)], fill=(200, 100, 200, 150), width=1)

        # Highlight Box around active glyph rendering area
        glyph_right = margin_x + glyph_w * scale
        draw.rectangle([margin_x, cell_y, glyph_right, cell_y + target_h], outline=(240, 200, 50, 150), width=1)

        # Show on preview canvas
        self.preview_photo = ImageTk.PhotoImage(final_img)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(110, 110, image=self.preview_photo)

    def apply_glyph_metrics(self, event=None):
        if self.selected_glyph_index is None:
            return
        
        try:
            left = self.val_left.get()
        except (tk.TclError, ValueError):
            left = 0
        try:
            glyph = self.val_glyph.get()
        except (tk.TclError, ValueError):
            glyph = 0
        try:
            char = self.val_char.get()
        except (tk.TclError, ValueError):
            char = 0

        # Ensure widths entry exists in self.glyph_widths
        if self.selected_glyph_index not in self.glyph_widths:
            self.glyph_widths[self.selected_glyph_index] = {"left": 0, "glyph": 0, "char": 0}
            
        widths = self.glyph_widths[self.selected_glyph_index]
        widths["left"] = left
        widths["glyph"] = glyph
        widths["char"] = char

        # Ensure a CWDH section covers self.selected_glyph_index
        found = False
        for cwdh in self.bffnt.cwdh_sections:
            if cwdh["start"] <= self.selected_glyph_index <= cwdh["end"]:
                idx = self.selected_glyph_index - cwdh["start"]
                cwdh["data"][idx] = {
                    "left": left,
                    "glyph": glyph,
                    "char": char
                }
                found = True
                break
                
        if not found:
            # We must extend an existing CWDH section or create one
            if self.bffnt.cwdh_sections:
                # Extend the closest CWDH section (usually the one with the highest end index)
                cwdh = max(self.bffnt.cwdh_sections, key=lambda c: c['end'])
                if self.selected_glyph_index > cwdh['end']:
                    gap = self.selected_glyph_index - cwdh['end']
                    for _ in range(gap):
                        cwdh['data'].append({"left": 0, "glyph": 0, "char": 0})
                    cwdh['end'] = self.selected_glyph_index
                    cwdh['data'][-1] = {
                        "left": left,
                        "glyph": glyph,
                        "char": char
                    }
                    found = True
                elif self.selected_glyph_index < cwdh['start']:
                    gap = cwdh['start'] - self.selected_glyph_index
                    for _ in range(gap):
                        cwdh['data'].insert(0, {"left": 0, "glyph": 0, "char": 0})
                    cwdh['start'] = self.selected_glyph_index
                    cwdh['data'][0] = {
                        "left": left,
                        "glyph": glyph,
                        "char": char
                    }
                    found = True
            else:
                # Create a new CWDH section
                new_cwdh = {
                    'size': CWDH_HEADER_SIZE,
                    'start': self.selected_glyph_index,
                    'end': self.selected_glyph_index,
                    'data': [{
                        "left": left,
                        "glyph": glyph,
                        "char": char
                    }]
                }
                self.bffnt.cwdh_sections.append(new_cwdh)
                found = True

        self.is_modified = True
        # Update the selected listbox row directly
        sel = self.glyph_tree.selection()
        if sel:
            # Keep old values but update the metrics
            old_vals = list(self.glyph_tree.item(sel[0], "values"))
            old_vals[3] = left
            old_vals[4] = glyph
            old_vals[5] = char
            self.glyph_tree.item(sel[0], values=old_vals)

        self.lbl_status.config(text="Applied metric changes to selected glyph.")

    def open_pixel_editor(self, event=None):
        if self.selected_glyph_index is None or not self.bffnt:
            return
        
        glyph_idx_to_edit = self.selected_glyph_index
        
        if glyph_idx_to_edit in self.open_editors:
            self.open_editors[glyph_idx_to_edit].lift()
            self.open_editors[glyph_idx_to_edit].focus_force()
            return
        
        tglp = self.bffnt.tglp
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        cell_width = tglp['glyph']['width']
        cell_height = tglp['glyph']['height']

        sheet_idx = glyph_idx_to_edit // (cols * rows)
        cell_idx = glyph_idx_to_edit % (cols * rows)
        col = cell_idx % cols
        row = cell_idx // cols

        if sheet_idx >= len(tglp['sheets']):
            return
        sheet = tglp['sheets'][sheet_idx]
        
        # Extract the current crop to a 1D pixel list
        x_left = 1 + col * (cell_width + 1)
        y_top = 1 + row * (cell_height + 1)
        
        current_pixels = []
        for r in range(cell_height):
            y = y_top + r
            for c in range(cell_width):
                x = x_left + c
                pixel = sheet['data'][y * sheet['width'] + x]
                current_pixels.append(pixel)
                
        # Define callback for saving
        def save_pixels_callback(new_pixels):
            # Update back into sheet['data']
            for r in range(cell_height):
                y = y_top + r
                for c in range(cell_width):
                    x = x_left + c
                    src_pixel = new_pixels[r * cell_width + c]
                    sheet['data'][y * sheet['width'] + x] = src_pixel
                     
            self.is_modified = True
            self.refresh_sheet_view()
            if self.selected_glyph_index == glyph_idx_to_edit:
                self.draw_glyph_preview()
            self.lbl_status.config(text=f"Saved pixel edits for glyph {glyph_idx_to_edit}")
             
        # Create editor window
        PixelEditorWindow(self, glyph_idx_to_edit, cell_width, cell_height, current_pixels, save_pixels_callback)

    def export_glyph_png(self, event=None):
        if self.selected_glyph_index is None or not self.bffnt:
            return
        
        tglp = self.bffnt.tglp
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        cell_width = tglp['glyph']['width']
        cell_height = tglp['glyph']['height']

        sheet_idx = self.selected_glyph_index // (cols * rows)
        cell_idx = self.selected_glyph_index % (cols * rows)
        col = cell_idx % cols
        row = cell_idx // cols

        if sheet_idx >= len(tglp['sheets']):
            return
        sheet = tglp['sheets'][sheet_idx]
        
        flat_data = bytes([c for pixel in sheet['data'] for c in pixel])
        sheet_img = Image.frombytes("RGBA", (sheet['width'], sheet['height']), flat_data)

        x_left = 1 + col * (cell_width + 1)
        y_top = 1 + row * (cell_height + 1)
        glyph_crop = sheet_img.crop((x_left, y_top, x_left + cell_width, y_top + cell_height))
        
        # Suggest filename
        chars = self.character_mappings.get(self.selected_glyph_index, [])
        char_suffix = f"_{ord(chars[0]):04X}" if chars else ""
        default_filename = f"glyph_{self.selected_glyph_index}{char_suffix}.png"
        
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")], initialfile=default_filename)
        if not path:
            return
            
        try:
             glyph_crop.save(path)
             self.lbl_status.config(text=f"Exported glyph {self.selected_glyph_index} to {os.path.basename(path)}")
             messagebox.showinfo("Export Successful", f"Glyph {self.selected_glyph_index} exported successfully to:\n{path}")
        except Exception as e:
             messagebox.showerror("Export Failed", f"Failed to export glyph:\n{str(e)}")

    def import_glyph_png(self, event=None):
        if self.selected_glyph_index is None or not self.bffnt:
            return
        
        tglp = self.bffnt.tglp
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        cell_width = tglp['glyph']['width']
        cell_height = tglp['glyph']['height']

        path = filedialog.askopenfilename(filetypes=[("PNG Image", "*.png")])
        if not path:
            return
            
        try:
             img = Image.open(path).convert("RGBA")
             w, h = img.size
             if w != cell_width or h != cell_height:
                 messagebox.showerror("Invalid Size", f"Imported glyph PNG dimensions ({w}x{h}) must exactly match expected cell dimensions ({cell_width}x{cell_height}).")
                 return
                 
             sheet_idx = self.selected_glyph_index // (cols * rows)
             cell_idx = self.selected_glyph_index % (cols * rows)
             col = cell_idx % cols
             row = cell_idx // cols

             sheet = tglp['sheets'][sheet_idx]
             
             # Paste the imported glyph on top of sheet
             flat_data = bytes([c for pixel in sheet['data'] for c in pixel])
             sheet_img = Image.frombytes("RGBA", (sheet['width'], sheet['height']), flat_data)
             
             x_left = 1 + col * (cell_width + 1)
             y_top = 1 + row * (cell_height + 1)
             sheet_img.paste(img, (x_left, y_top))
             
             raw_bytes = sheet_img.tobytes()
             bmp = [list(raw_bytes[i:i+4]) for i in range(0, len(raw_bytes), 4)]
             sheet['data'] = bmp
             
             self.is_modified = True
             self.refresh_sheet_view()
             self.draw_glyph_preview()
             self.lbl_status.config(text=f"Imported glyph {self.selected_glyph_index} from {os.path.basename(path)}")
             messagebox.showinfo("Import Successful", f"Glyph {self.selected_glyph_index} imported successfully.")
        except Exception as e:
             messagebox.showerror("Import Failed", f"Failed to import glyph:\n{str(e)}")

    def refresh_mappings_list(self):
        self.mapping_listbox.delete(0, tk.END)
        if self.selected_glyph_index is None:
            return
        chars = self.character_mappings.get(self.selected_glyph_index, [])
        for c in chars:
            self.mapping_listbox.insert(tk.END, f"'{c}' (U+{ord(c):04X})")

    def add_mapping_ui(self, event=None):
         if self.selected_glyph_index is None or not self.bffnt:
             return
         
         dialog = tk.Toplevel(self.root)
         dialog.title("Add Character Mapping")
         dialog.geometry("350x180")
         dialog.transient(self.root)
         dialog.grab_set()
         dialog.configure(bg=self.bg_dark)
         dialog.resizable(False, False)
         
         dialog.update_idletasks()
         x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
         y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
         dialog.geometry(f"+{x}+{y}")
         
         ttk.Label(dialog, text="Enter a single character or Unicode codepoint\n(e.g., 'A', 'U+0041', or '0x0041'):", 
                   style='TLabel', justify=tk.LEFT).pack(padx=20, pady=(20, 10), anchor=tk.W)
         
         entry_var = tk.StringVar()
         entry = tk.Entry(dialog, textvariable=entry_var, bg="#2d2d30", fg=self.fg_light, 
                          insertbackground=self.fg_light, borderwidth=1, relief=tk.FLAT, font=("Segoe UI", 10))
         entry.pack(fill=tk.X, padx=20, pady=5, ipady=3)
         entry.focus_set()
         
         btn_frame = ttk.Frame(dialog, style='TFrame')
         btn_frame.pack(fill=tk.X, padx=20, pady=(15, 10))
         
         def on_confirm():
             val = entry_var.get().strip()
             if not val:
                 dialog.destroy()
                 return
             
             char = None
             if len(val) == 1:
                 char = val
             elif val.lower().startswith("u+") or val.lower().startswith("0x"):
                 try:
                     code = int(val[2:], 16)
                     char = chr(code)
                 except ValueError:
                     pass
             else:
                 try:
                     code = int(val, 16)
                     char = chr(code)
                 except ValueError:
                     try:
                         code = int(val)
                         char = chr(code)
                     except ValueError:
                         pass
             
             if not char:
                 messagebox.showerror("Error", "Invalid character or Unicode format.", parent=dialog)
                 return
             
             success = self.bffnt.add_mapping(char, self.selected_glyph_index)
             if not success:
                 # Auto create SCAN cmap section as fallback
                 new_cmap = {
                     'size': CMAP_HEADER_SIZE,
                     'start': ord(char),
                     'end': ord(char),
                     'type': MAPPING_SCAN,
                     'entries': {char: self.selected_glyph_index}
                 }
                 self.bffnt.cmap_sections.append(new_cmap)
                 success = True
             
             if success:
                 self.is_modified = True
                 self.character_mappings = self.bffnt.get_character_mappings()
                 self.refresh_mappings_list()
                 self.refresh_glyph_table()
                 self.lbl_status.config(text=f"Mapped character U+{ord(char):04X} to glyph {self.selected_glyph_index}")
                 dialog.destroy()
             else:
                 messagebox.showerror("Error", "Could not add character mapping.", parent=dialog)
         
         btn_ok = ttk.Button(btn_frame, text="Add Mapping", style='Accent.TButton', command=on_confirm)
         btn_ok.pack(side=tk.RIGHT, padx=(10, 0))
         btn_cancel = ttk.Button(btn_frame, text="Cancel", command=dialog.destroy)
         btn_cancel.pack(side=tk.RIGHT)
         
         dialog.bind("<Return>", lambda e: on_confirm())
         dialog.bind("<Escape>", lambda e: dialog.destroy())

    def remove_mapping_ui(self, event=None):
         if self.selected_glyph_index is None or not self.bffnt:
             return
         sel = self.mapping_listbox.curselection()
         if not sel:
             return
         
         item_text = self.mapping_listbox.get(sel[0])
         import re
         m = re.match(r"^'(.)'", item_text)
         if not m:
             m2 = re.search(r"U\+([0-9A-Fa-f]+)", item_text)
             if m2:
                 char = chr(int(m2.group(1), 16))
             else:
                 return
         else:
             char = m.group(1)
             
         ans = messagebox.askyesno("Confirm Removal", f"Are you sure you want to remove the mapping for character '{char}' (U+{ord(char):04X})?")
         if ans:
             if self.bffnt.remove_mapping(char):
                 self.is_modified = True
                 self.character_mappings = self.bffnt.get_character_mappings()
                 self.refresh_mappings_list()
                 self.refresh_glyph_table()
                 self.lbl_status.config(text=f"Removed mapping for character U+{ord(char):04X}")

    def export_sheet(self, event=None):
        if not self.bffnt:
            return
        idx = self.sheet_combo.current()
        sheet = self.bffnt.tglp['sheets'][idx]
        
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")], initialfile=f"sheet_{idx}.png")
        if not path:
            return

        try:
            # Flatten pixel data
            flat_data = bytes([c for pixel in sheet['data'] for c in pixel])
            img = Image.frombytes("RGBA", (sheet['width'], sheet['height']), flat_data)
            img.save(path)
            messagebox.showinfo("Export Successful", f"Sheet {idx} successfully exported to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to export sheet:\n{str(e)}")

    def import_sheet(self, event=None):
        if not self.bffnt:
            return
        idx = self.sheet_combo.current()
        sheet = self.bffnt.tglp['sheets'][idx]

        path = filedialog.askopenfilename(filetypes=[("PNG Image", "*.png")])
        if not path:
            return

        try:
            img = Image.open(path).convert("RGBA")
            w, h = img.size
            if w != sheet['width'] or h != sheet['height']:
                messagebox.showerror("Invalid Size", f"Imported PNG dimensions ({w}x{h}) must exactly match expected sheet dimensions ({sheet['width']}x{sheet['height']}).")
                return

            raw_bytes = img.tobytes()
            bmp = [list(raw_bytes[i:i+4]) for i in range(0, len(raw_bytes), 4)]
            
            # Save into current sheet data
            self.bffnt.tglp['sheets'][idx]['data'] = bmp
            self.is_modified = True
            
            self.refresh_sheet_view()
            self.draw_glyph_preview()
            messagebox.showinfo("Import Successful", f"Sheet {idx} successfully replaced with:\n{path}")
        except Exception as e:
            messagebox.showerror("Import Failed", f"Failed to import sheet:\n{str(e)}")

    def add_new_sheet(self, event=None):
        if not self.bffnt:
            return
        
        tglp = self.bffnt.tglp
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        added_glyphs = cols * rows
        
        ans = messagebox.askyesno("Add New Sheet", f"Are you sure you want to add a new texture sheet?\n\nThis will add 1 new sheet and {added_glyphs} empty glyph slots (Index {tglp['sheetCount'] * added_glyphs} to {(tglp['sheetCount'] + 1) * added_glyphs - 1 }).")
        if not ans:
            return
            
        # Padded dimensions (power-of-two) required by the console format
        pot_width = 1 << int(math.ceil(math.log(tglp['sheet']['width'], 2)))
        pot_height = 1 << int(math.ceil(math.log(tglp['sheet']['height'], 2)))
        new_sheet_data = [[0, 0, 0, 0] for _ in range(pot_width * pot_height)]
        
        tglp['sheets'].append({
            'width': tglp['sheet']['width'],
            'height': tglp['sheet']['height'],
            'data': new_sheet_data
        })
        tglp['sheetCount'] += 1
        self.is_modified = True
        
        # Refresh UI
        self.refresh_metadata()
        self.sheet_combo.current(tglp['sheetCount'] - 1)
        self.refresh_sheet_view()
        self.refresh_glyph_table()
        
        self.lbl_status.config(text=f"Added new sheet. Sheet count is now {tglp['sheetCount']}.")
        messagebox.showinfo("Success", f"Added new texture sheet successfully! Added {added_glyphs} new blank glyphs.")

    def remove_last_sheet(self, event=None):
        if not self.bffnt:
            return
        
        tglp = self.bffnt.tglp
        if tglp['sheetCount'] <= 1:
            messagebox.showerror("Error", "Cannot remove sheet. A font must contain at least one texture sheet.")
            return
            
        cols = tglp['sheet']['cols']
        rows = tglp['sheet']['rows']
        removed_glyphs = cols * rows
        new_sheet_count = tglp['sheetCount'] - 1
        total_glyphs = new_sheet_count * removed_glyphs
        
        ans = messagebox.askyesno("Remove Last Sheet", f"Are you sure you want to remove the last texture sheet?\n\nThis will permanently delete the last sheet, all {removed_glyphs} glyph slots on it (Index {total_glyphs} to {tglp['sheetCount'] * removed_glyphs - 1}), and any character mappings associated with them.")
        if not ans:
            return
            
        # 1. Update sheet count and remove sheet data
        tglp['sheets'].pop()
        tglp['sheetCount'] = new_sheet_count
        self.is_modified = True
        
        # 2. Clean up character mappings & widths in our active caches
        self.character_mappings = {g_idx: chars for g_idx, chars in self.character_mappings.items() if g_idx < total_glyphs}
        self.glyph_widths = {g_idx: w for g_idx, w in self.glyph_widths.items() if g_idx < total_glyphs}
        
        # 3. Update CWDH sections in the BFFNT object
        new_cwdh_sections = []
        for cwdh in self.bffnt.cwdh_sections:
            if cwdh['start'] >= total_glyphs:
                # Entire section is on the removed sheet, delete it
                continue
            elif cwdh['end'] >= total_glyphs:
                # Truncate the section
                cwdh['end'] = total_glyphs - 1
                cwdh['data'] = cwdh['data'][:(total_glyphs - cwdh['start'])]
                new_cwdh_sections.append(cwdh)
            else:
                new_cwdh_sections.append(cwdh)
        self.bffnt.cwdh_sections = new_cwdh_sections
        
        # 4. Clean up CMAP sections in the BFFNT object
        for cmap in self.bffnt.cmap_sections:
            if cmap['type'] == MAPPING_SCAN:
                cmap['entries'] = {char: idx for char, idx in cmap['entries'].items() if idx < total_glyphs}
            elif cmap['type'] == MAPPING_TABLE:
                for i in range(len(cmap['indexTable'])):
                    if cmap['indexTable'][i] >= total_glyphs and cmap['indexTable'][i] != 0xFFFF:
                        cmap['indexTable'][i] = 0xFFFF
                        
        # 5. Clear selections
        self.selected_glyph_index = None
        self.btn_edit_pixels.config(state="disabled")
        self.btn_apply_metrics.config(state="disabled")
        self.btn_export_glyph.config(state="disabled")
        self.btn_import_glyph.config(state="disabled")
        self.btn_add_mapping.config(state="disabled")
        self.btn_remove_mapping.config(state="disabled")
        self.mapping_listbox.delete(0, tk.END)
        self.preview_canvas.delete("all")
        
        # 6. Refresh UI
        self.refresh_metadata()
        self.sheet_combo.current(0)
        self.refresh_sheet_view()
        self.refresh_glyph_table()
        
        self.lbl_status.config(text=f"Removed last sheet. Sheet count is now {tglp['sheetCount']}.")
        messagebox.showinfo("Success", f"Removed the last texture sheet successfully! Cleared associated character slots.")


    def on_open(self, event=None):
        if self.is_modified:
            ans = messagebox.askyesnocancel("Unsaved Changes", "You have unsaved changes. Save them before opening another file?")
            if ans is True:
                self.on_save()
            elif ans is None:
                return

        path = filedialog.askopenfilename(filetypes=[("BFFNT Files", "*.bffnt")])
        if path:
            self.load_bffnt_file(path)

    def on_save(self, event=None):
        if not self.bffnt:
            return
        if not self.current_filepath:
            self.on_save_as()
            return
        
        try:
            self.bffnt.save(self.current_filepath)
            self.is_modified = False
            self.lbl_status.config(text=f"Saved successfully: {os.path.basename(self.current_filepath)}")
            messagebox.showinfo("Success", "BFFNT saved successfully!")
        except Exception as e:
            messagebox.showerror("Save Failed", f"Failed to save BFFNT file:\n{str(e)}")

    def on_save_as(self, event=None):
        if not self.bffnt:
            return
        path = filedialog.asksaveasfilename(defaultextension=".bffnt", filetypes=[("BFFNT Files", "*.bffnt")], initialfile=os.path.basename(self.current_filepath) if self.current_filepath else "")
        if path:
            self.current_filepath = path
            self.on_save()

    def on_exit(self):
        if self.is_modified:
            ans = messagebox.askyesnocancel("Unsaved Changes", "You have unsaved changes. Do you want to save before exiting?")
            if ans is True:
                self.on_save()
                self.root.destroy()
            elif ans is False:
                self.root.destroy()
        else:
            self.root.destroy()

    def setup_drag_and_drop(self):
        try:
            import ctypes
            from ctypes import wintypes
            
            GWL_WNDPROC = -4
            WM_DROPFILES = 0x0233
            
            LRESULT = ctypes.c_ssize_t
            self.WNDPROC_TYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
            
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                self.SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
                self.SetWindowLong.restype = ctypes.c_void_p
                self.SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                
                self.GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
                self.GetWindowLong.restype = ctypes.c_void_p
                self.GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
            else:
                self.SetWindowLong = ctypes.windll.user32.SetWindowLongW
                self.SetWindowLong.restype = ctypes.c_void_p
                self.SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                
                self.GetWindowLong = ctypes.windll.user32.GetWindowLongW
                self.GetWindowLong.restype = ctypes.c_void_p
                self.GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
                
            self.CallWindowProc = ctypes.windll.user32.CallWindowProcW
            self.CallWindowProc.restype = LRESULT
            self.CallWindowProc.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
            
            self.DragAcceptFiles = ctypes.windll.shell32.DragAcceptFiles
            self.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            self.DragAcceptFiles.restype = None
            
            self.DragQueryFile = ctypes.windll.shell32.DragQueryFileW
            self.DragQueryFile.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
            self.DragQueryFile.restype = ctypes.c_uint
            
            self.DragFinish = ctypes.windll.shell32.DragFinish
            self.DragFinish.argtypes = [ctypes.c_void_p]
            self.DragFinish.restype = None
            
            # Allow WM_DROPFILES and WM_COPYGLOBALDATA messages through UIPI message filter (for elevated/admin privileges)
            try:
                ctypes.windll.user32.ChangeWindowMessageFilter(0x0233, 1) # WM_DROPFILES
                ctypes.windll.user32.ChangeWindowMessageFilter(0x0049, 1) # WM_COPYGLOBALDATA
            except AttributeError:
                pass
            
            # Subclass storage
            self.old_wndproc = None
            self.new_wndproc = self.WNDPROC_TYPE(self.wndproc)
            
            # Wait for all widgets to be drawn so we can retrieve their real HWNDs
            self.root.update_idletasks()
            
            # Subclass ONLY the root/main window
            root_hwnd = self.root.winfo_id()
            self.DragAcceptFiles(root_hwnd, True)
            self.old_wndproc = self.GetWindowLong(root_hwnd, GWL_WNDPROC)
            self.SetWindowLong(root_hwnd, GWL_WNDPROC, self.new_wndproc)
            
            # Recursively enable drag/drop for all child widgets, but do NOT subclass them
            self.register_drag_accept(self.root)
        except Exception as e:
            print("Failed to initialize native drag and drop:", e)
            
    def register_drag_accept(self, widget):
        try:
            hwnd = widget.winfo_id()
            self.DragAcceptFiles(hwnd, True)
        except Exception:
            pass
            
        # Recursively walk Tcl/Tk children
        for child in widget.winfo_children():
            self.register_drag_accept(child)
            
    def wndproc(self, hwnd, msg, wp, lp):
        WM_DROPFILES = 0x0233
        import ctypes
        if msg == WM_DROPFILES:
            hDrop = wp
            num_files = self.DragQueryFile(hDrop, 0xFFFFFFFF, None, 0)
            files = []
            for i in range(num_files):
                length = self.DragQueryFile(hDrop, i, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                self.DragQueryFile(hDrop, i, buf, length + 1)
                files.append(buf.value)
            
            self.DragFinish(hDrop)
            
            if files:
                self.root.after(0, lambda: self.on_files_dropped(files))
            return 0
            
        if self.old_wndproc:
            return self.CallWindowProc(self.old_wndproc, hwnd, msg, wp, lp)
        return 0
            
    def on_files_dropped(self, files):
        if not files:
            return
            
        filepath = files[0]
        if isinstance(filepath, bytes):
            try:
                filepath = filepath.decode('utf-8')
            except UnicodeDecodeError:
                filepath = filepath.decode('ansi')
                
        if not filepath.lower().endswith(".bffnt"):
            messagebox.showwarning("Invalid File", "Only .bffnt files can be opened.")
            return
            
        if self.is_modified:
            ans = messagebox.askyesnocancel("Unsaved Changes", "You have unsaved changes. Do you want to save them before loading another file?")
            if ans is True:
                self.on_save()
                self.load_bffnt_file(filepath)
            elif ans is False:
                self.load_bffnt_file(filepath)
        else:
            self.load_bffnt_file(filepath)

def main():
    root = tk.Tk()
    app = BFFNTApp(root)
    
    # If a file is passed as command-line argument, open it automatically
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.exists(path):
            app.load_bffnt_file(path)
            
    root.protocol("WM_DELETE_WINDOW", app.on_exit)
    root.mainloop()

if __name__ == '__main__':
    main()
