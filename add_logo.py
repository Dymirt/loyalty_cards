from PIL import Image, ImageOps, ImageDraw, ImageFont
from PIL.Image import Image as PILImage
import barcode
from barcode.writer import ImageWriter
import os

class CardGenerator:
    def __init__(self, media_dir: str = 'media'):
        self.media_dir: str = media_dir
        self.static_dir: str = 'static'
        self.cards_dir: str = os.path.join(self.media_dir, 'cards')
        self.logo_size: tuple[int, int] = (576, 183)
        self.barcode_size: tuple[int, int] = (210, 118)
        os.makedirs(self.cards_dir, exist_ok=True)
        self.font: str = os.path.join(self.static_dir, 'fonts/Barlow/Barlow-Medium.ttf')
        self.font_bold: str = os.path.join(self.static_dir, 'fonts/Barlow/Barlow-Bold.ttf')
        self.barcode_options: dict = {
            'module_height': 5,
            'font_size': 3,
            'text_distance': 2,
            'background': 'white',
            'foreground': 'black',
            'quiet_zone': 1,
            'font_path': self.font
        }
        self.contact_info: str = 'ul. Wąwozowa 8/lokal 3a, 02-796 Warszawa\ntel.: +48 519 727 253\ne-mail: concept@martabanaszek.pl'
        self.name: str = 'where coffee meets fashion'

    def generate_barcode_image(self, barcode_text: str, barcode_file: str) -> None:
        """Generate a barcode image and save it."""
        code128 = barcode.get('code128', barcode_text, writer=ImageWriter())
        code128.save(barcode_file, self.barcode_options)

    def add_barcode(self, index: int, image: PILImage, save_dir: str) -> None:
        """Add barcode to an image."""
        barcode_text: str = f"MB-{index}"
        barcode_file: str = os.path.join(save_dir, 'barcode')
        self.generate_barcode_image(barcode_text, barcode_file)

        barcode_img: PILImage = Image.open(barcode_file + '.png')
        # barcode_img = barcode_img.resize(self.barcode_size)

        barcode_img = barcode_img.crop((0, 0, barcode_img.width, barcode_img.height - 10))
        scale_factor = 1.5
        new_size = (int(barcode_img.width * scale_factor), int(barcode_img.height * scale_factor))
        barcode_img = barcode_img.resize(new_size, resample=Image.LANCZOS)

        position: tuple[int, int] = (int(image.width / 2) - int(new_size[0] / 2), image.height - new_size[1] - 50)
        image.paste(barcode_img, position)

    def add_logo_front(self, image: PILImage) -> None:
        """Add a logo to the front image."""
        logo_path = os.path.join(self.media_dir, 'logo_atelier_cafe.png')
        logo: PILImage = Image.open(logo_path)
        logo = logo.resize(self.logo_size)
        if logo.mode != 'RGBA':
            logo = logo.convert('RGBA')

        position: tuple[int, int] = (50, 50)
        #position: tuple[int, int] = (int(image.width / 2) - int(self.logo_size[0] / 2), 50)
        #position = (int((image.width - self.logo_size[0]) / 2), int((image.height - self.logo_size[1]) / 2))


        image.paste(logo, position, logo)

    def add_logo_back(self, image: PILImage) -> None:
        """Add a logo to the back image."""
        logo_path = os.path.join(self.media_dir, 'logo_atelier_cafe.png')
        logo: PILImage = Image.open(logo_path)
        logo = logo.resize(self.logo_size)
        if logo.mode != 'RGBA':
            logo = logo.convert('RGBA')

        position: tuple[int, int] = (int(image.width / 2) - int(self.logo_size[0] / 2), 50)
        image.paste(logo, position, logo)

    def add_contact_info(self, image: PILImage):
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(self.font_bold, size=40)
        text = self.contact_info
        image_width, image_height = image.size

        # Get size of the text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Calculate X, Y position to center the text
        position = ((image_width - text_width) / 2, (image_height - text_height) / 2)

        # Draw white rectangle as background (with some padding)
        padding = 10
        rect_start = (position[0] - padding, position[1])
        rect_end = (position[0] + text_width + padding, position[1] + text_height + padding * 2)
        draw.rectangle([rect_start, rect_end], fill=(255, 255, 255, 255))

        # Draw the text on top
        color = (0, 0, 0, 255)
        draw.text(position, text, font=font, fill=color, align="center")

    def add_name (self, image: PILImage):
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(self.font_bold, size=60)
        text = self.name
        # Get size of the image
        image_width, image_height = image.size

        # Get size of the text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Calculate X, Y position to center the text
        #position = ((image_width - text_width) / 2, (image_height - text_height) / 2)
        position: tuple[int, int] = ((image_width - text_width) / 2, image_height - 100)

        color = (0, 0, 0)
        draw.text(position, text, font=font, fill=color, align="center")

    def generate_card_images(self, cropped_name_index: int) -> None:
        """Generate front and mirrored back card images with barcode."""
        save_dir: str = os.path.join(self.cards_dir, f'card-{cropped_name_index}')
        os.makedirs(save_dir, exist_ok=True)

        front_path = os.path.join(self.media_dir, 'cropped_images', f'cropped_image_{cropped_name_index}.jpg')
        front: PILImage = Image.open(front_path)
        back: PILImage = ImageOps.mirror(front)

        save_front_path: str = os.path.join(save_dir, f'MB-{cropped_name_index}_front.jpg')
        save_back_path: str = os.path.join(save_dir, f'MB-{cropped_name_index}_back.jpg')

        # Process front
        self.add_logo_front(front)
        self.add_name(front)
        # Process back
        self.add_logo_back(back)
        self.add_contact_info(back)
        self.add_barcode(cropped_name_index, back, save_dir)

        # Save images
        back.save(save_back_path)
        front.save(save_front_path, format='JPEG')

    def generate_contact_info_png(self) -> PILImage:
        """Generate a transparent PNG with the contact info text, centered."""
        font = ImageFont.truetype(self.font_bold, size=40)
        text = self.contact_info
        lines = text.split('\n')

        # Get font metrics
        ascent, descent = font.getmetrics()
        line_spacing = 10  # px between lines

        # Measure width and total height
        dummy_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy_img)
        max_width = 0
        total_height = 0
        line_sizes = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            width = bbox[2] - bbox[0]
            height = ascent + descent  # Use font metrics for line height
            line_sizes.append((width, height))
            if width > max_width:
                max_width = width
            total_height += height + line_spacing
        total_height -= line_spacing  # Remove extra spacing after last line

        # Create transparent image
        text_img = Image.new("RGBA", (max_width, total_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_img)

        # Draw each line centered
        y = 0
        for i, line in enumerate(lines):
            line_width, line_height = line_sizes[i]
            x = (max_width - line_width) // 2
            draw.text((x, y), line, font=font, fill=(0, 0, 0, 255))
            y += line_height + line_spacing

        text_img.save(self.media_dir + '/contact_info.png', format='PNG')
        return text_img

# --- Usage ---
if __name__ == "__main__":
    generator = CardGenerator()
    generator.generate_contact_info_png()
    for i in range(201, 601):
        generator.generate_card_images(i)
