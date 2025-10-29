import os
import numpy as np
import logging
import torch
import nodes
import comfy_extras
from PIL import Image, ImageDraw, ImageFont, ImageColor
from nodes import PreviewImage

base_path = os.path.dirname(__file__)
custom_path = os.path.dirname(base_path)

def _rgba_from_hex(color_str):
    if not color_str:
        return (255, 255, 255, 255)
    try:
        c = ImageColor.getcolor(color_str, 'RGBA')
        return c
    except Exception:
        return (255, 255, 255, 255)

def _pil_image_from_tensor(image_tensor):
    if image_tensor.ndim == 4:
        img = image_tensor[0]
    else:
        img = image_tensor
    img = (img.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
    pil = Image.fromarray(img, 'RGBA' if img.shape[-1] == 4 else 'RGB').convert('RGBA')
    return pil

def _tensor_from_pil(pil):
    arr = np.array(pil).astype(np.float32) / 255.0
    t = torch.from_numpy(arr)[None, ...]
    return t

def _get_font_dir():
    font_dir = os.path.join(custom_path, 'Comfyui-TextEditor-Penguin', 'font')
    if os.path.isdir(font_dir):
        try:
            for entry in os.scandir(font_dir):
                if entry.is_file() and entry.name.lower().endswith(('.ttf', '.ttc', '.otf')):
                    return font_dir
        except Exception:
            pass
    return os.path.join(base_path, 'font')

def _load_font(font_file, font_size):
    if not font_file or font_file == 'default':
        return ImageFont.load_default()
    font_dir = _get_font_dir()
    font_path = os.path.join(font_dir, font_file)
    try:
        return ImageFont.truetype(font_path, font_size)
    except Exception as e:
        logging.warning(f'Failed to load font {font_path}: {e}; fallback to default font')
        return ImageFont.load_default()

def _compute_anchor_xy(pos, W, H, tw, th):
    pos = (pos or 'left_top').lower()
    if pos.startswith('left'):
        ax = 0
    elif pos.startswith('center'):
        ax = (W - tw) / 2
    elif pos.startswith('right'):
        ax = W - tw
    else:
        ax = 0
    if pos.endswith('top'):
        ay = 0
    elif pos.endswith('center'):
        ay = (H - th) / 2
    elif pos.endswith('bottom'):
        ay = H - th
    else:
        ay = 0
    return int(round(ax)), int(round(ay))

class TextOnImage_Pandora:
    def __init__(self):
        pass
    @classmethod
    def INPUT_TYPES(cls):
        font_dir = _get_font_dir()
        try:
            font_files = [f for f in os.listdir(font_dir) if f.lower().endswith(('.ttc', '.ttf', '.otf'))]
        except Exception:
            font_files = []
        if not font_files:
            font_files = ['default']
        return {
            'required': {
                'text': ('STRING', {'default': '', 'multiline': True}),
                'image': ('IMAGE',),
                'x': ('INT', {'default': 0, 'min': -4096, 'max': 4096, 'step': 1}),
                'y': ('INT', {'default': 0, 'min': -4096, 'max': 4096, 'step': 1}),
                'font_size': ('INT', {'default': 32, 'min': 1, 'max': 512, 'step': 1}),
                'text_color': ('STRING', {'default': '#FFFFFFFF'}),
                'stroke_width': ('INT', {'default': 0, 'min': 0, 'max': 64, 'step': 1}),
                'stroke_color': ('STRING', {'default': '#000000FF'}),
                'shadow_x': ('INT', {'default': 0, 'min': -200, 'max': 200, 'step': 1}),
                'shadow_y': ('INT', {'default': 0, 'min': -200, 'max': 200, 'step': 1}),
                'shadow_color': ('STRING', {'default': '#00000080'}),
                'font_file': (font_files, {'default': font_files[0]}),
                'align': (['left', 'center', 'right'], {'default': 'left'}),
                'line_spacing': ('INT', {'default': -4, 'min': -50, 'max': 400, 'step': 1}),
                'pos': ([
                    'left,top', 'left,center', 'left,bottom',
                    'center,top', 'center,center', 'center,bottom',
                    'right,top', 'right,center', 'right,bottom'
                ], {'default': 'left,top'}),
            },
        }    
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'apply_text'
    CATEGORY = 'Pandora ⚕️/Text ⚕️'
    def apply_text(
        self,
        text,
        image,
        pos,
        x,
        y,
        font_size,
        text_color,
        stroke_width,
        stroke_color,
        shadow_x,
        shadow_y,
        shadow_color,
        font_file,
        align,
        line_spacing,
    ):
        if not text:
            return (image,)
        base = _pil_image_from_tensor(image)
        W, H = base.size
        font = _load_font(font_file, font_size)
        td = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        # Measure overall text size (including stroke)
        try:
            bbox = td.multiline_textbbox(
                (0, 0), text, font=font, align=align,
                spacing=int(line_spacing),
                stroke_width=int(stroke_width) if stroke_width else 0
            )
        except Exception:
            # Fallback for older Pillow versions
            w, h = td.textsize(text, font=font)
            bbox = (0, 0, w, h)
        bx0, by0, bx1, by1 = bbox
        tw, th = int(bx1 - bx0), int(by1 - by0)
        # 1) Compute anchor position of text block based on pos
        ax, ay = _compute_anchor_xy(pos, W, H, tw, th)
        # 2) Apply user (x, y) offset
        px = ax + int(x)
        py = ay + int(y)
        # Compute drawing region (with safe padding; considering shadow/stroke)
        pad = int(max(stroke_width * 2, abs(int(shadow_x)), abs(int(shadow_y))))
        left = int(max(0, min(W, px - pad)))
        top = int(max(0, min(H, py - pad)))
        right = int(max(0, min(W, px + tw + pad)))
        bottom = int(max(0, min(H, py + th + pad)))
        cw = int(max(0, right - left))
        ch = int(max(0, bottom - top))
        if cw == 0 or ch == 0:
            return (image,)
        # Align bbox origin to our cropped local canvas
        rx = int(px) - left - bx0
        ry = int(py) - top - by0
        # Text color and stroke
        tc = _rgba_from_hex(text_color)
        sc = _rgba_from_hex(stroke_color)
        # 3) Draw text layer (with stroke)
        text_layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        draw_text = ImageDraw.Draw(text_layer)
        draw_text.multiline_text(
            (rx, ry),
            text,
            font=font,
            fill=tc,
            align=align,
            spacing=int(line_spacing),
            stroke_width=int(stroke_width) if stroke_width else 0,
            stroke_fill=sc if stroke_width else None,
        )
        # 4) Copy text layer as shadow layer, offset and recolor (avoid baseline shift)
        if (shadow_x != 0 or shadow_y != 0):
            shadow_layer = text_layer.copy()
            shadow_rgba = _rgba_from_hex(shadow_color)
            # Replace color using alpha channel
            r, g, b, a = shadow_layer.split()
            colored_shadow = Image.new('RGBA', (cw, ch), shadow_rgba)
            shadow_layer = Image.composite(colored_shadow, Image.new('RGBA', (cw, ch), (0, 0, 0, 0)), a)
            # Composite onto base image (offset)
            base.alpha_composite(shadow_layer, (left + int(shadow_x), top + int(shadow_y)))
        # 5) Composite text layer
        base.alpha_composite(text_layer, (left, top))
        out = _tensor_from_pil(base)
        return (out,)

class PreviewImage_Pandora(PreviewImage):
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "apply_image"
    CATEGORY = "Pandora ⚕️/Image ⚕️"
    def apply_image(self, **kwargs):
        results = nodes.PreviewImage().save_images(kwargs["images"])
        results["result"] = (kwargs["images"],)
        return results

class ImageFillColor_Pandora:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "red": ("INT", {"default": 0, "min": 0, "max": 255, "step": 1}),
                "green": ("INT", {"default": 0, "min": 0, "max": 255, "step": 1}),
                "blue": ("INT", {"default": 0, "min": 0, "max": 255, "step": 1}),
            },
            "optional": {
                "mask": ("MASK",),
            },
        }
    RETURN_TYPES = ("IMAGE", "MASK",)
    FUNCTION = "image_fill_color"
    CATEGORY = "Pandora ⚕️/Image ⚕️"
    def image_fill_color(self, image, red, green, blue, mask=None):
        samples = image.movedim(-1, 1)
        height = samples.shape[2]
        width = samples.shape[3]
        r = torch.full([1, height, width, 1], red / 0xFF)
        g = torch.full([1, height, width, 1], green / 0xFF)
        b = torch.full([1, height, width, 1], blue / 0xFF)
        source = torch.cat((r, g, b), dim=-1)
        (filled_image,) = comfy_extras.nodes_mask.ImageCompositeMasked().composite(image, source, 0, 0, False, mask)
        return (filled_image, mask,)

class MaskToImage_Pandora(PreviewImage):
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mask": ("MASK",), 
            },
        }
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "mask_to_image"
    CATEGORY = "Pandora ⚕️/Mask ⚕️"
    def mask_to_image(self, mask):
        image = mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1])).movedim(1, -1).expand(-1, -1, -1, 3)
        results = nodes.PreviewImage().save_images(image)
        results["result"] = (image,)
        return results

class PreviewMask_Pandora(MaskToImage_Pandora):
    RETURN_TYPES = ("MASK",)
    FUNCTION = "preview_mask"
    def preview_mask(self, mask):
        image = mask.reshape((-1, 1, mask.shape[-2], mask.shape[-1])).movedim(1, -1).expand(-1, -1, -1, 3)
        results = nodes.PreviewImage().save_images(image)
        results["result"] = (mask,)
        return results


NODE_CLASS_MAPPINGS = {
    "Text On Image | Pandora": TextOnImage_Pandora,
    "Preview Image | Pandora": PreviewImage_Pandora,
    "Image Fill Color | Pandora": ImageFillColor_Pandora,
    "Mask to Image | Pandora": MaskToImage_Pandora,
    "Preview Mask | Pandora": PreviewMask_Pandora,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Text On Image | Pandora": "Text On Image ⚕️",
    "Preview Image | Pandora": "Preview Image ⚕️",
    "Image Fill Color | Pandora": "Image Fill Color ⚕️",
    "Mask to Image | Pandora": "Mask to Image ⚕️",
    "Preview Mask | Pandora": "Preview Mask ⚕️",
}
