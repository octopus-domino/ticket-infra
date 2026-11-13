"""Create lightweight previews/contact sheets; never modifies full-resolution artwork."""
from pathlib import Path
import json
import sys
infra = Path(__file__).resolve().parents[2]
project = infra.parent / 'ticket-editor'
sys.path.insert(0, str(project.parent/'.cache/image-tools'))
from PIL import Image, ImageDraw, ImageFont

catalog = json.loads((project/'public/backgrounds/catalog.json').read_text(encoding='utf-8'))
thumbs = project/'public/backgrounds/thumbs'
thumbs.mkdir(exist_ok=True)
for row in catalog:
    with Image.open(project/'public/backgrounds/lossless'/(row['id']+'.webp')) as image:
        image.thumbnail((240,240), Image.Resampling.LANCZOS)
        image.convert('RGB').save(thumbs/(row['id']+'.jpg'), quality=82, optimize=True)
font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 14)
for group in range((len(catalog)+29)//30):
    canvas = Image.new('RGB',(1200,1150),'#f5f4f0')
    draw = ImageDraw.Draw(canvas)
    for index,row in enumerate(catalog[group*30:(group+1)*30]):
        with Image.open(thumbs/(row['id']+'.jpg')) as image:
            canvas.paste(image.resize((190,190),Image.Resampling.LANCZOS),((index%6)*200+5,(index//6)*230+5))
        draw.text(((index%6)*200+7,(index//6)*230+202),row['en'],fill='#213b31',font=font)
    canvas.save(infra/'reports'/f'background-collection-{group+1}.jpg',quality=90)
print(json.dumps(dict(count=len(catalog),thumbnail_bytes=sum(path.stat().st_size for path in thumbs.glob('*.jpg')))))
