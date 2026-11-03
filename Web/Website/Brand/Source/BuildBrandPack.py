"""Builds the RAMMIT brand pack (logos, colour tokens, social images, zip) into Web/Website/Brand.

The mark is a vector rebuild of the 250 px app icon (Production/RAMMIT-Stable/Src/Dark/RAMMIT.png),
fitted to it pixel by pixel: only anti-aliased edges differ. Run from anywhere:

    python Web/Website/Brand/Source/BuildBrandPack.py

Needs Pillow, NumPy and fontTools, plus Segoe UI Bold (C:/Windows/Fonts/segoeuib.ttf) for the wordmark.
"""

import json
import math
import zipfile
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

BrandDir = Path(__file__).resolve().parent.parent
SiteDir = BrandDir.parent
FontPath = 'C:/Windows/Fonts/segoeuib.ttf'

# ===== COLOURS =====
# BrandBlue is the logo's own blue. The rest is the app's Dark theme (Src/Dark/CSS/Style.css).
Colours = {
    'BrandBlue': {'Hex': '#335FFF', 'Use': 'The logo background. Logo only, never UI.'},
    'Background': {'Hex': '#0A0A0A', 'Use': 'Page and window background.'},
    'Card': {'Hex': '#141414', 'Use': 'Panels.'},
    'Input': {'Hex': '#1F1F1F', 'Use': 'Text boxes, drop-downs.'},
    'Border': {'Hex': '#252525', 'Use': 'Dividers, 1 px borders.'},
    'Text': {'Hex': '#FFFFFF', 'Use': 'Main text.'},
    'TextDim': {'Hex': '#888888', 'Use': 'Secondary text, labels.'},
    'Accent': {'Hex': '#0078D4', 'Use': 'Selected rows, + ADD, panel labels.'},
    'AccentHover': {'Hex': '#1E90FF', 'Use': 'Links, hover states.'},
    'Launch': {'Hex': '#1A6B3A', 'Use': 'LAUNCH and Download buttons only.'},
    'Success': {'Hex': '#28A745', 'Use': 'Launched, confirm.'},
    'Danger': {'Hex': '#DC3545', 'Use': '- REMOVE, errors.'},
}

def Rgb(Hex):
    return tuple(int(Hex[I:I + 2], 16) for I in (1, 3, 5))

Blue = Rgb(Colours['BrandBlue']['Hex'])
White = (255, 255, 255)
Ink = Rgb(Colours['Background']['Hex'])

# ===== MARK GEOMETRY (250 x 250 grid) =====
Tile = {'Cx': 124.2, 'Cy': 124.1, 'Side': 152.4, 'Deg': 15}
Hole = {'Cx': 125.0, 'Cy': 125.0, 'Side': 42.5, 'Deg': 15}
Plus = {'Cx': 171.5, 'Cy': 63.5, 'Length': 114, 'Thick': 26, 'Gap': 6}


def SquarePoints(Sq, Scale=1.0, Dx=0.0, Dy=0.0):
    Half = Sq['Side'] / 2
    T = math.radians(Sq['Deg'])
    C, S = math.cos(T), math.sin(T)
    return [((Sq['Cx'] + X * C - Y * S) * Scale + Dx, (Sq['Cy'] + X * S + Y * C) * Scale + Dy)
            for X, Y in [(-Half, -Half), (Half, -Half), (Half, Half), (-Half, Half)]]


def PlusPath():
    Arm = Plus['Length'] / 2 - Plus['Thick'] / 2
    Cx, Cy = Plus['Cx'], Plus['Cy']
    return f'M{Cx} {Cy - Arm}V{Cy + Arm}M{Cx - Arm} {Cy}H{Cx + Arm}'


def MarkSvgBody(Fg, Bg, Id):
    """The mark in the 250 grid. Bg None = transparent background (hole and gap are cut out)."""
    Points = lambda Sq: ' '.join(f'{X:.2f},{Y:.2f}' for X, Y in SquarePoints(Sq))
    Out = []
    if Bg:
        Out.append(f'<rect width="250" height="250" fill="{Bg}"/>')
    Out.append(
        f'<mask id="{Id}" maskUnits="userSpaceOnUse" x="0" y="0" width="250" height="250">'
        f'<rect width="250" height="250" fill="#fff"/>'
        f'<polygon points="{Points(Hole)}" fill="#000"/>'
        f'<path d="{PlusPath()}" stroke="#000" stroke-width="{Plus["Thick"] + 2 * Plus["Gap"]}" stroke-linecap="round"/>'
        f'</mask>')
    Out.append(f'<polygon points="{Points(Tile)}" fill="{Fg}" mask="url(#{Id})"/>')
    Out.append(f'<path d="{PlusPath()}" stroke="{Fg}" stroke-width="{Plus["Thick"]}" stroke-linecap="round" fill="none"/>')
    return ''.join(Out)


def DrawMark(Draw, Scale, Dx, Dy, Fg, Cut):
    """Draws the mark onto an RGBA ImageDraw. Cut is the colour written into the hole and the plus gap."""
    Draw.polygon(SquarePoints(Tile, Scale, Dx, Dy), fill=Fg + (255,))
    Draw.polygon(SquarePoints(Hole, Scale, Dx, Dy), fill=Cut)
    for Width, Fill in [(Plus['Thick'] + 2 * Plus['Gap'], Cut), (Plus['Thick'], Fg + (255,))]:
        R = Width / 2
        Half = Plus['Length'] / 2 + (Width - Plus['Thick']) / 2
        Cx, Cy = Plus['Cx'], Plus['Cy']
        for Box in [(Cx - R, Cy - Half, Cx + R, Cy + Half), (Cx - Half, Cy - R, Cx + Half, Cy + R)]:
            Draw.rounded_rectangle([Box[0] * Scale + Dx, Box[1] * Scale + Dy, Box[2] * Scale + Dx, Box[3] * Scale + Dy],
                                   radius=R * Scale, fill=Fill)


def RenderMark(Size, Fg=White, Bg=Blue, Ss=4):
    Big = Size * Ss
    Im = Image.new('RGBA', (Big, Big), (Bg + (255,)) if Bg else (0, 0, 0, 0))
    Cut = (Bg + (255,)) if Bg else (0, 0, 0, 0)
    DrawMark(ImageDraw.Draw(Im), Big / 250, 0, 0, Fg, Cut)
    return Im.resize((Size, Size), Image.LANCZOS)


# ===== WORDMARK =====
Font = TTFont(FontPath)
Upm = Font['head'].unitsPerEm
CapHeight = Font['OS/2'].sCapHeight
GlyphSet = Font.getGlyphSet()
Cmap = Font.getBestCmap()
Tracking = 0.06  # extra space between letters, as a share of the cap height (keeps R and A apart)


def WordmarkPath(Text, CapPx):
    """SVG path for Text with its cap height at CapPx, baseline at y = CapPx. Returns (path, width)."""
    Scale = CapPx / CapHeight
    Pen = SVGPathPen(GlyphSet)
    X = 0.0
    for Ch in Text:
        Name = Cmap[ord(Ch)]
        GlyphPen = TransformPen(Pen, (Scale, 0, 0, -Scale, X, CapPx))
        GlyphSet[Name].draw(GlyphPen)
        X += GlyphSet[Name].width * Scale + Tracking * CapPx
    # Trim the last glyph's right side bearing so the box ends at the ink
    Last = Cmap[ord(Text[-1])]
    Glyf = Font['glyf'][Last]
    X -= (GlyphSet[Last].width - Glyf.xMax) * Scale
    return Pen.getCommands(), X


def Svg(Width, Height, Body, Title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {Width:g} {Height:g}" width="{Width:g}" height="{Height:g}">'
            f'<title>{Title}</title>{Body}</svg>\n')


# Horizontal lockup: icon 250, wordmark cap height = 34% of the icon, gap = 25% of the icon.
LockCap = 85
LockGap = 62.5
WordPath, WordW = WordmarkPath('RAMMIT', LockCap)
LockW = 250 + LockGap + WordW
LockH = 250


def LockupSvg(TextColour, Id):
    Y = (LockH - LockCap) / 2
    return Svg(LockW, LockH,
               MarkSvgBody('#FFFFFF', Colours['BrandBlue']['Hex'], Id)
               + f'<path transform="translate({250 + LockGap} {Y})" d="{WordPath}" fill="{TextColour}"/>',
               'RAMMIT')


def RenderLockup(Height, TextRgb, Bg=None):
    Scale = Height / LockH
    W = math.ceil(LockW * Scale)
    Ss = 4
    Im = Image.new('RGBA', (W * Ss, Height * Ss), (Bg + (255,)) if Bg else (0, 0, 0, 0))
    Icon = RenderMark(Height * Ss, Ss=1)
    Im.paste(Icon, (0, 0), Icon)
    Text = RenderWordmark(LockCap * Scale * Ss, TextRgb)
    Im.alpha_composite(Text, (round((250 + LockGap) * Scale * Ss), round((LockH - LockCap) / 2 * Scale * Ss - Text.info['Top'])))
    return Im.resize((W, Height), Image.LANCZOS)


def RenderWordmark(CapPx, TextRgb):
    """Wordmark as RGBA; info['Top'] is how far above the cap line the image starts."""
    Size = round(CapPx * Upm / CapHeight)
    Pil = ImageFont.truetype(FontPath, Size)
    # Letter by letter with the same advances and tracking as WordmarkPath
    Advances = [GlyphSet[Cmap[ord(Ch)]].width * CapPx / CapHeight + Tracking * CapPx for Ch in 'RAMMIT']
    L, T, R, B = Pil.getbbox('R', anchor='ls')
    Width = math.ceil(sum(Advances)) + 8
    Im = Image.new('RGBA', (Width, B - T + 8), (0, 0, 0, 0))
    D = ImageDraw.Draw(Im)
    X = 4.0
    for Ch, Adv in zip('RAMMIT', Advances):
        D.text((X, 4 - T), Ch, font=Pil, fill=TextRgb + (255,), anchor='ls')
        X += Adv
    Im.info['Top'] = (4 - T) - CapPx  # baseline sits at 4-T; the cap line is CapPx above it
    return Im


# ===== SOCIAL =====
def Text(Draw, Xy, S, Size, Rgb_, Bold=True):
    F = ImageFont.truetype(FontPath if Bold else 'C:/Windows/Fonts/segoeui.ttf', Size)
    Draw.text(Xy, S, font=F, fill=Rgb_)


def Screenshot(Width):
    Shot = Image.open(SiteDir / 'Assets/Shots/main-idle.png').convert('RGB')
    H = round(Shot.height * Width / Shot.width)
    Shot = Shot.resize((Width, H), Image.LANCZOS)
    Framed = Image.new('RGB', (Width + 2, H + 2), Rgb(Colours['Border']['Hex']))
    Framed.paste(Shot, (1, 1))
    return Framed


def SocialCard(W, H, Pad, IconPx, Head, Sub, ShotW, ShotX, ShotY):
    Im = Image.new('RGBA', (W, H), Ink + (255,))
    D = ImageDraw.Draw(Im)
    Icon = RenderMark(IconPx)
    Im.paste(Icon, (Pad, Pad), Icon)
    Word = RenderWordmark(IconPx * 0.34, White)
    Im.alpha_composite(Word, (Pad + IconPx + round(IconPx * 0.25), round(Pad + IconPx * 0.33 - Word.info['Top'])))
    Y = Pad + IconPx + round(H * 0.09)
    for Line in Head:
        Text(D, (Pad - 3, Y), Line, round(H * 0.105), White)
        Y += round(H * 0.125)
    Y += round(H * 0.03)
    for Line in Sub:
        Text(D, (Pad, Y), Line, round(H * 0.042), Rgb(Colours['TextDim']['Hex']), Bold=False)
        Y += round(H * 0.06)
    Im.paste(Screenshot(ShotW), (ShotX, ShotY))
    return Im.convert('RGB')


def Main():
    Out = {}

    def Save(Rel, Data):
        P = BrandDir / Rel
        P.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(Data, str):
            P.write_text(Data, encoding='utf-8', newline='\n')
        elif isinstance(Data, Image.Image):
            Data.save(P, optimize=True)
        else:
            P.write_bytes(Data)
        Out[Rel] = P

    # Icon: full colour square, the app icon itself
    Save('Logo/Icon/RAMMIT-Icon.svg', Svg(250, 250, MarkSvgBody('#FFFFFF', Colours['BrandBlue']['Hex'], 'Cut'), 'RAMMIT'))
    for S in [16, 32, 48, 64, 128, 256, 512, 1024]:
        Save(f'Logo/Icon/RAMMIT-Icon-{S}.png', RenderMark(S))
    Ico = RenderMark(256)
    IcoPath = BrandDir / 'Logo/Icon/RAMMIT.ico'
    Ico.save(IcoPath, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    Out['Logo/Icon/RAMMIT.ico'] = IcoPath

    # Mark: no background square, hole and gap cut out
    Save('Logo/Mark/RAMMIT-Mark-White.svg', Svg(250, 250, MarkSvgBody('#FFFFFF', None, 'Cut'), 'RAMMIT'))
    Save('Logo/Mark/RAMMIT-Mark-Blue.svg', Svg(250, 250, MarkSvgBody(Colours['BrandBlue']['Hex'], None, 'Cut'), 'RAMMIT'))
    Save('Logo/Mark/RAMMIT-Mark-Black.svg', Svg(250, 250, MarkSvgBody('#0A0A0A', None, 'Cut'), 'RAMMIT'))
    Save('Logo/Mark/RAMMIT-Mark-White-1024.png', RenderMark(1024, White, None))
    Save('Logo/Mark/RAMMIT-Mark-Blue-1024.png', RenderMark(1024, Blue, None))
    Save('Logo/Mark/RAMMIT-Mark-Black-1024.png', RenderMark(1024, Ink, None))

    # Horizontal lockup
    Save('Logo/Horizontal/RAMMIT-Logo-OnDark.svg', LockupSvg('#FFFFFF', 'Cut'))
    Save('Logo/Horizontal/RAMMIT-Logo-OnLight.svg', LockupSvg('#0A0A0A', 'Cut'))
    Save('Logo/Horizontal/RAMMIT-Logo-OnDark-512h.png', RenderLockup(512, White))
    Save('Logo/Horizontal/RAMMIT-Logo-OnLight-512h.png', RenderLockup(512, Ink))

    # Wordmark alone
    Path_, W = WordmarkPath('RAMMIT', 100)
    for Name, Fill in [('White', '#FFFFFF'), ('Black', '#0A0A0A')]:
        Save(f'Logo/Wordmark/RAMMIT-Wordmark-{Name}.svg', Svg(W, 100, f'<path d="{Path_}" fill="{Fill}"/>', 'RAMMIT'))

    # Colour tokens
    Save('Colours/RAMMIT-Colours.json', json.dumps(
        {Name: {'Hex': V['Hex'], 'Rgb': list(Rgb(V['Hex'])), 'Use': V['Use']} for Name, V in Colours.items()}, indent=2) + '\n')
    Css = ['/* RAMMIT colours. BrandBlue is for the logo; the rest is the app\'s Dark theme. */', ':root {']
    Css += [f'    --{Name}: {V["Hex"]};  /* {V["Use"]} */' for Name, V in Colours.items()]
    Css += ['    --Font: \'Segoe UI\', system-ui, -apple-system, \'Helvetica Neue\', Arial, sans-serif;', '}', '']
    Save('Colours/RAMMIT-Colours.css', '\n'.join(Css))
    Gpl = ['GIMP Palette', 'Name: RAMMIT', 'Columns: 4', '#']
    Gpl += [f'{R:3d} {G:3d} {B:3d}\t{Name}' for Name, V in Colours.items() for R, G, B in [Rgb(V['Hex'])]]
    Save('Colours/RAMMIT-Colours.gpl', '\n'.join(Gpl) + '\n')

    # Social
    Save('Social/RAMMIT-Avatar-800.png', RenderMark(800))
    Save('Social/RAMMIT-Card-1280x640.png',
         SocialCard(1280, 640, 64, 72, ['One click.', 'Every account.'],
                    ['Free, open-source Roblox', 'multi-account launcher for Windows.'], 600, 640, 120))
    Save('Social/RAMMIT-Banner-1500x500.png',
         SocialCard(1500, 500, 56, 56, ['One click.', 'Every account.'],
                    ['Free, open-source Roblox', 'multi-account launcher for Windows.'], 640, 800, 64))

    # Everything (not this script) in one zip
    ZipPath = BrandDir / 'RAMMIT-BrandPack.zip'
    with zipfile.ZipFile(ZipPath, 'w', zipfile.ZIP_DEFLATED) as Z:
        for Rel, P in sorted(Out.items()):
            Z.write(P, f'RAMMIT-BrandPack/{Rel}')
        Z.write(BrandDir / 'README.md', 'RAMMIT-BrandPack/README.md')
    print(f'{len(Out)} files + README.md -> {ZipPath.name} ({ZipPath.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    Main()
